"""Tests du cache mutualisé des prévisions Open-Meteo (lot L9.3).

Aucun réseau : le client enrobé est un bouchon qui compte ses appels et rend
des `PrevisionPoint` fabriqués — ce module ne connaît même pas `httpx`.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime

from ourouler.meteo.cache_previsions import (
    PRECISION_MAILLE_DEG,
    ClientOpenMeteoCache,
    _arrondir,
)
from ourouler.noyau.meteo import PrevisionHeure, PrevisionPoint

DEBUT = datetime(2026, 9, 13, 8, 0, tzinfo=UTC)


def _point(lat: float, lon: float) -> PrevisionPoint:
    return PrevisionPoint(
        lat=lat,
        lon=lon,
        heures=[
            PrevisionHeure(
                t=DEBUT,
                pluie_mm=0.0,
                vent_kmh=10.0,
                rafales_kmh=15.0,
                vent_depuis_deg=180.0,
                ressenti_c=15.0,
                temp_c=16.0,
            )
        ],
    )


@dataclass
class ClientCompteur:
    """Le client enrobé : rend un point par coordonnée demandée, compte ses lots."""

    lots: list[list[tuple[float, float]]] = field(default_factory=list)

    def previsions(self, points, *, modele, debut, horizon_h):
        del modele, debut, horizon_h
        self.lots.append(list(points))
        return [_point(lat, lon) for lat, lon in points]


class Horloge:
    """Horloge injectable pour `ClientOpenMeteoCache` — un flottant qu'on avance à la main."""

    def __init__(self, depart: float = 0.0) -> None:
        self.maintenant = depart

    def __call__(self) -> float:
        return self.maintenant

    def avancer(self, secondes: float) -> None:
        self.maintenant += secondes


def test_deux_demandes_du_meme_point_ne_font_qu_un_appel():
    sous_jacent = ClientCompteur()
    cache = ClientOpenMeteoCache(sous_jacent)

    cache.previsions([(10.0, 10.0)], modele="m", debut=DEBUT, horizon_h=6)
    cache.previsions([(10.0, 10.0)], modele="m", debut=DEBUT, horizon_h=6)

    assert len(sous_jacent.lots) == 1, "le second appel devait être servi depuis le cache"
    assert cache.appels_reels == 1
    assert cache.appels_servis_cache == 1


def test_deux_comptes_qui_demandent_le_meme_point_ne_paient_qu_un_appel():
    """Le point du lot : le cache ne connaît aucun compte, il se partage entre tous."""
    sous_jacent = ClientCompteur()
    cache = ClientOpenMeteoCache(sous_jacent)

    # Rien dans l'API du cache ne distingue « compte A » de « compte B » —
    # c'est précisément ce qui fait la mutualisation, et ce qui garantit
    # qu'aucun identifiant de compte n'entre dans la clé.
    cache.previsions([(45.0, 5.0)], modele="m", debut=DEBUT, horizon_h=6)
    cache.previsions([(45.0, 5.0)], modele="m", debut=DEBUT, horizon_h=6)

    assert cache.appels_reels == 1
    assert cache.appels_servis_cache == 1


def test_un_point_different_declenche_un_nouvel_appel():
    sous_jacent = ClientCompteur()
    cache = ClientOpenMeteoCache(sous_jacent)

    cache.previsions([(45.0, 5.0)], modele="m", debut=DEBUT, horizon_h=6)
    cache.previsions([(46.0, 5.0)], modele="m", debut=DEBUT, horizon_h=6)

    assert cache.appels_reels == 2
    assert cache.appels_servis_cache == 0


def test_un_lot_mixte_ne_redemande_que_les_points_manquants():
    """Une requête à plusieurs points, dont certains déjà en cache."""
    sous_jacent = ClientCompteur()
    cache = ClientOpenMeteoCache(sous_jacent)

    cache.previsions([(1.0, 1.0)], modele="m", debut=DEBUT, horizon_h=6)
    resultat = cache.previsions([(1.0, 1.0), (2.0, 2.0)], modele="m", debut=DEBUT, horizon_h=6)

    assert len(resultat) == 2
    assert cache.appels_reels == 2  # le premier lot, puis le point manquant du second
    assert sous_jacent.lots[-1] == [(2.0, 2.0)], "seul le point manquant repart au réseau"
    assert cache.appels_servis_cache == 1


def test_points_dans_la_meme_maille_partagent_la_cle():
    """L'arrondi à `PRECISION_MAILLE_DEG` : deux points très proches, une seule clé."""
    sous_jacent = ClientCompteur()
    cache = ClientOpenMeteoCache(sous_jacent)

    cache.previsions([(10.0, 10.0)], modele="m", debut=DEBUT, horizon_h=6)
    cache.previsions([(10.0 + PRECISION_MAILLE_DEG / 4, 10.0)], modele="m", debut=DEBUT, horizon_h=6)

    assert cache.appels_reels == 1, "un point à moins d'un quart de maille reste la même clé"


def test_un_modele_different_n_est_pas_la_meme_clef():
    sous_jacent = ClientCompteur()
    cache = ClientOpenMeteoCache(sous_jacent)

    cache.previsions([(1.0, 1.0)], modele="arome", debut=DEBUT, horizon_h=6)
    cache.previsions([(1.0, 1.0)], modele="icon", debut=DEBUT, horizon_h=6)

    assert cache.appels_reels == 2


def test_un_horizon_different_n_est_pas_la_meme_clef():
    """`horizon_h` fait partie de la clé : 6 h et 12 h ne sont pas la même demande."""
    sous_jacent = ClientCompteur()
    cache = ClientOpenMeteoCache(sous_jacent)

    cache.previsions([(1.0, 1.0)], modele="m", debut=DEBUT, horizon_h=6)
    cache.previsions([(1.0, 1.0)], modele="m", debut=DEBUT, horizon_h=12)

    assert cache.appels_reels == 2
    assert cache.appels_servis_cache == 0

    # Et une troisième demande, à l'horizon déjà vu, retombe bien en cache.
    cache.previsions([(1.0, 1.0)], modele="m", debut=DEBUT, horizon_h=6)
    assert cache.appels_reels == 2
    assert cache.appels_servis_cache == 1


def test_les_minutes_du_debut_ne_changent_pas_la_cle():
    """`start_hour` d'Open-Meteo ne porte pas les minutes : ni la clé de cache."""
    sous_jacent = ClientCompteur()
    cache = ClientOpenMeteoCache(sous_jacent)

    cache.previsions([(1.0, 1.0)], modele="m", debut=DEBUT, horizon_h=6)
    cache.previsions([(1.0, 1.0)], modele="m", debut=DEBUT.replace(minute=45), horizon_h=6)

    assert cache.appels_reels == 1


def test_une_entree_expiree_redemande_le_reseau():
    sous_jacent = ClientCompteur()
    horloge = Horloge()
    cache = ClientOpenMeteoCache(sous_jacent, ttl_s=1800.0, horloge=horloge)

    cache.previsions([(1.0, 1.0)], modele="m", debut=DEBUT, horizon_h=6)
    horloge.avancer(1799.0)
    cache.previsions([(1.0, 1.0)], modele="m", debut=DEBUT, horizon_h=6)
    assert cache.appels_reels == 1, "encore dans les 30 minutes : servi depuis le cache"

    horloge.avancer(2.0)  # 1801 s après le premier appel : périmé
    cache.previsions([(1.0, 1.0)], modele="m", debut=DEBUT, horizon_h=6)
    assert cache.appels_reels == 2, "au-delà du TTL, le cache rappelle le réseau"


def test_la_taille_du_cache_est_bornee_lru():
    sous_jacent = ClientCompteur()
    cache = ClientOpenMeteoCache(sous_jacent, taille_max=2)

    cache.previsions([(1.0, 1.0)], modele="m", debut=DEBUT, horizon_h=6)
    cache.previsions([(2.0, 2.0)], modele="m", debut=DEBUT, horizon_h=6)
    cache.previsions([(3.0, 3.0)], modele="m", debut=DEBUT, horizon_h=6)  # évince (1.0, 1.0)

    cache.previsions([(1.0, 1.0)], modele="m", debut=DEBUT, horizon_h=6)  # doit rappeler
    cache.previsions([(3.0, 3.0)], modele="m", debut=DEBUT, horizon_h=6)  # encore là

    assert cache.appels_reels == 4  # (1,1) (2,2) (3,3) puis (1,1) de nouveau
    assert cache.appels_servis_cache == 1  # seul le dernier (3,3) était encore en cache


def test_appels_concurrents_ne_corrompent_pas_le_cache():
    """Concurrence simple : plusieurs fils tapent le cache en même temps, sans y laisser de plumes.

    Une assertion levée **dans** un fil ne fait pas échouer le test — un fil
    dont le corps lève termine juste silencieusement, et `join()` ne le
    répercute pas (trouvé en relecture Opus, L9.3) : les échecs sont donc
    collectés ici et rejoués dans le fil principal, seul capable de faire
    échouer le test pour de vrai.
    """
    sous_jacent = ClientCompteur()
    cache = ClientOpenMeteoCache(sous_jacent)
    points = [(float(i), float(i)) for i in range(8)]
    nb_fils = 6
    verrou_erreurs = threading.Lock()
    erreurs: list[BaseException] = []

    def taper() -> None:
        try:
            for _ in range(20):
                for point in points:
                    resultat = cache.previsions([point], modele="m", debut=DEBUT, horizon_h=6)
                    assert resultat[0].lat == point[0]
                    assert resultat[0].lon == point[1]
        except BaseException as e:  # noqa: BLE001 - remonté tel quel au fil principal
            with verrou_erreurs:
                erreurs.append(e)

    fils = [threading.Thread(target=taper) for _ in range(nb_fils)]
    for f in fils:
        f.start()
    for f in fils:
        f.join()

    assert not erreurs, f"{len(erreurs)} fil(s) en échec : {erreurs!r}"

    # Une borne resserrée, qui prouve quelque chose : la seule vraie course
    # est le tout premier tour, où plusieurs fils peuvent manquer le cache
    # au même instant sur le même point avant que l'un d'eux ne le
    # remplisse (voir la docstring du module — aucune déduplication des
    # requêtes concurrentes en vol). Après ce premier tour, chaque point est
    # en cache et les 19 tours suivants ne devraient plus jamais y toucher.
    # Le pire des cas est donc **un appel réel par fil, par point du premier
    # tour** — jamais un par tour de boucle (160 par fil, 960 en tout).
    assert cache.appels_reels >= len(points), "au moins un appel réel par point distinct"
    assert cache.appels_reels <= len(points) * nb_fils, (
        f"{cache.appels_reels} appels réels pour {len(points)} points × {nb_fils} fils : "
        "la mutualisation ne s'est pas vue"
    )
    assert cache.stats()["entrees"] == len(points)


def test_arrondir_est_stable_sur_les_flottants_impurs():
    assert _arrondir(0.15 - 0.05) == _arrondir(0.10)
