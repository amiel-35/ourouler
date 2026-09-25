"""Cache mutualisé des prévisions Open-Meteo, pour le service hébergé (lot L9.3).

Doctrine §10.1 : Open-Meteo gratuit tolère ~10 000 appels par jour et par
**adresse IP** — et un service hébergé, où tous les comptes appellent depuis
la même adresse, additionne leurs appels. Une « sortie » à cinq candidates en
coûte à elle seule ~150 (« 1 + 2 × candidates » requêtes, 14 points chacune).
L'escalade décidée : « (1) cache mutualisé par maille (~2 km) et par heure,
dès le premier jour ». C'est ce module.

**Ce qui se mutualise, et ce qui ne se voit jamais.** Une prévision pour un
point et une plage horaire est la même pour tout le monde : deux comptes qui
demandent le même point à la même heure reçoivent la même réponse, et un seul
appel HTTP est passé pour les deux. La clé de cache ne porte **aucun**
identifiant de compte — seulement le modèle, le point arrondi et la plage
horaire — donc rien de ce que ce cache retient ne relie une requête à un
compte, et le journal ne nomme jamais un compte non plus (seulement des
compteurs globaux au processus).

**Ce qui n'est pas fait ici** : dédupliquer deux requêtes concurrentes pour
la **même** clé manquante (chacune part sur le réseau). C'est un choix, pas
un oubli — la fenêtre est courte (un aller-retour HTTP), le risque est un
appel Open-Meteo de plus, jamais une incohérence, et l'alternative
(verrouiller par clé, faire attendre la seconde requête) coûterait de la
latence perçue pour un gain qui ne vaut la peine que sous une charge que ce
service n'a pas encore.
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from ourouler.meteo.openmeteo import PrevisionPoint

#: La maille du point arrondi, en degrés (doctrine §10.1 : « par maille
#: (~2 km) »). À l'équateur, 0,02° de latitude fait environ 2,2 km ; la
#: longitude est plus serrée aux latitudes françaises (~1,5 km à 45°), donc
#: un peu plus fine que « ~2 km » sur cet axe — pas un problème : arrondir
#: plus fin ne fait que réduire le taux de partage, jamais la justesse.
PRECISION_MAILLE_DEG = 0.02

#: Combien de temps une prévision reste servie sans rappeler le réseau. Une
#: demi-heure : assez pour qu'une session de recherche (plusieurs boucles,
#: plusieurs comptes qui regardent la même zone) ne refasse pas le même
#: appel, assez court pour qu'une prévision qui change ne s'affiche pas
#: périmée pendant des heures — Open-Meteo se met à jour plus vite que ça.
TTL_CACHE_PREVISIONS_S = 1800.0

#: Combien d'entrées le cache garde au maximum, pour un processus qui ne
#: redémarre pas : au-delà, la plus ancienne cède la place (LRU). 500 couvre
#: largement des dizaines de points × plusieurs plages horaires en une
#: journée, pour un service à l'usage d'un cercle restreint (doctrine §10.2).
TAILLE_MAX_CACHE = 500


def _arrondir(valeur: float, pas: float = PRECISION_MAILLE_DEG) -> float:
    """Ramène une coordonnée au multiple de `pas` le plus proche.

    Même précaution que `connecteurs/openmeteo_archive.arrondir` : passer par
    les centièmes évite qu'un `0.15000000000000002` issu d'un chemin de
    calcul légèrement différent fasse deux clés de cache pour le même point.
    """
    return round(round(valeur / pas) * pas, 6)


def _debut_arrondi(debut: datetime) -> datetime:
    """`debut` ramené à l'heure : les minutes ne changent rien à la requête
    Open-Meteo (`start_hour` ne porte que l'heure), donc pas à la clé."""
    debut_utc = debut.astimezone(UTC) if debut.tzinfo else debut.replace(tzinfo=UTC)
    return debut_utc.replace(minute=0, second=0, microsecond=0)


@dataclass(frozen=True)
class _Entree:
    point: PrevisionPoint
    expire_a: float


class ClientOpenMeteoCache:
    """Enrobe un client de prévisions (`ClientOpenMeteo` ou compatible) d'un
    cache partagé, en mémoire du processus, borné en taille et thread-safe.

    **Injectable** : `client` est ce qui appelle vraiment le réseau (ou un
    bouchon, dans un test) — ce module n'en construit aucun lui-même. C'est
    l'objet posé sur `Clients.meteo` par `api/application.application()` en
    mode hébergé (`api/routes.FABRIQUES_CONNECTEUR` le prend alors tel quel,
    comme n'importe quel connecteur déjà construit).

    Une requête à plusieurs points est coupée en deux : les points déjà en
    cache sont servis directement, les autres partent en **un seul** appel
    groupé au client enrobé — exactement la mutualisation « un seul appel
    pour tous » du contrat de sprint, y compris quand certains points d'une
    même requête sont déjà connus et d'autres non.
    """

    def __init__(
        self,
        client,
        *,
        ttl_s: float = TTL_CACHE_PREVISIONS_S,
        taille_max: int = TAILLE_MAX_CACHE,
        horloge: Callable[[], float] = time.monotonic,
    ) -> None:
        self._client = client
        self._ttl_s = ttl_s
        self._taille_max = taille_max
        self._horloge = horloge
        self._verrou = threading.Lock()
        self._entrees: OrderedDict[tuple, _Entree] = OrderedDict()
        #: Appels HTTP réellement passés au client enrobé — un par lot de
        #: points manquants, pas un par point (même convention que
        #: `ClientArchive.appels`).
        self.appels_reels = 0
        #: Points rendus depuis le cache, sans toucher au réseau.
        self.appels_servis_cache = 0

    def previsions(
        self,
        points: Sequence[tuple[float, float]],
        *,
        modele: str,
        debut: datetime,
        horizon_h: int,
    ) -> list[PrevisionPoint]:
        cles = [self._cle(point, modele, debut, horizon_h) for point in points]
        maintenant = self._horloge()
        resultat: list[PrevisionPoint | None] = [None] * len(points)
        manquants: list[int] = []

        with self._verrou:
            self._purger(maintenant)
            for i, cle in enumerate(cles):
                entree = self._entrees.get(cle)
                if entree is None:
                    manquants.append(i)
                    continue
                resultat[i] = entree.point
                self._entrees.move_to_end(cle)
                self.appels_servis_cache += 1

        if manquants:
            with self._verrou:
                # Compté **avant** l'appel, pas après : un appel qui échoue
                # (Open-Meteo hors domaine, en panne) a quand même touché le
                # réseau, et `appels_reels` répond à « combien de fois ce
                # processus a-t-il appelé Open-Meteo », pas « combien de
                # fois avec succès ».
                self.appels_reels += 1
            # **Hors du verrou** : l'appel réseau ne doit pas bloquer les
            # requêtes d'autres comptes qui, elles, tombent en cache.
            obtenus = self._client.previsions(
                [points[i] for i in manquants], modele=modele, debut=debut, horizon_h=horizon_h
            )
            if len(obtenus) != len(manquants):  # pragma: no cover - contrat du client enrobé
                raise ValueError(
                    f"ClientOpenMeteoCache : {len(obtenus)} prévision(s) reçue(s) pour "
                    f"{len(manquants)} point(s) manquant(s) demandés"
                )
            expire_a = maintenant + self._ttl_s
            with self._verrou:
                for i, point_obtenu in zip(manquants, obtenus, strict=True):
                    resultat[i] = point_obtenu
                    cle = cles[i]
                    self._entrees[cle] = _Entree(point=point_obtenu, expire_a=expire_a)
                    self._entrees.move_to_end(cle)
                while len(self._entrees) > self._taille_max:
                    self._entrees.popitem(last=False)  # le plus ancien (LRU)

        return resultat  # type: ignore[return-value]  # entièrement rempli à ce point

    def stats(self) -> dict:
        """Pour `/systeme` : ce que ce processus a réellement demandé au réseau."""
        with self._verrou:
            return {
                "appels_reels": self.appels_reels,
                "appels_servis_cache": self.appels_servis_cache,
                "entrees": len(self._entrees),
            }

    def _cle(
        self, point: tuple[float, float], modele: str, debut: datetime, horizon_h: int
    ) -> tuple:
        lat, lon = point
        return (
            modele,
            _arrondir(lat),
            _arrondir(lon),
            _debut_arrondi(debut).isoformat(),
            horizon_h,
        )

    def _purger(self, maintenant: float) -> None:
        perimees = [cle for cle, entree in self._entrees.items() if entree.expire_a <= maintenant]
        for cle in perimees:
            del self._entrees[cle]


__all__ = [
    "PRECISION_MAILLE_DEG",
    "TAILLE_MAX_CACHE",
    "TTL_CACHE_PREVISIONS_S",
    "ClientOpenMeteoCache",
]
