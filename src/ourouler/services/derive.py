"""Ce que l'import garde d'une sortie pour un compte qui ne garde pas ses fichiers d'origine.

Fiche « choix de garder ou d'effacer ses fichiers d'origine » : passé à
« ne pas garder », un compte hébergé n'a plus, après l'import, le fichier
d'activité brut (FIT/GPX/TCX) — seulement ce qu'on en a tiré pour la
calibration et le dédoublonnage. Ce module fait ce tri à l'import, range le
résultat dans la table `derives` du cache (`activites/cache.py`) et le relit
à la calibration.

Le dérivé d'une sortie, c'est `physique.validation.SortieDerivee` : ce que la
calibration lit, **sans une coordonnée, ni un instant, ni un ordre**. Voir sa
docstring pour le détail des champs.

**Le vent est résolu pendant l'import**, depuis l'archive Open-Meteo : c'est
le seul moment où l'on connaît encore le point de départ et le cap de chaque
tronçon. Les appels partent **en parallèle** (`APPELS_SIMULTANES`), pendant
que l'import continue de lire les fichiers suivants ; une archive
indisponible ne fait pas échouer l'import — la sortie est dérivée sans vent,
comptée, et refaite au prochain dépôt de la même archive (`a_rafraichir`).

**Versionné** : `VERSION_DERIVATION` entre dans chaque ligne. Quand la
méthode change, on l'incrémente : les dérivés anciens deviennent périmés, la
calibration ne s'en sert plus, et l'écran demande de redéposer l'archive.
Redéposer la même archive ne réimporte rien de nouveau : le dépôt reconnaît
chaque sortie à son empreinte et ne refait que les dérivés périmés ou tirés
sans vent.

Ce module ne lit ni fichier de configuration ni variable d'environnement : il
reçoit un `Cache` et un client d'archive météo déjà construits.
"""

from __future__ import annotations

import json
import math
import random
import zlib
from collections import deque
from collections.abc import Callable, Iterable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from datetime import date
from pathlib import Path

from ourouler.activites.cache import Cache, EntreeCache
from ourouler.activites.inventaire import en_interieur
from ourouler.connecteurs.openmeteo_archive import ClientArchive
from ourouler.noyau.activite import Activite, est_sport_velo
from ourouler.noyau.erreurs import ErreurConnecteur, ErreurUtilisateur
from ourouler.physique import calibration as calib
from ourouler.physique.modele import ProfilSimulation, _bornes_pas
from ourouler.physique.validation import SortieDerivee, trace_depuis_activite

#: La version de la méthode de dérivation. **À incrémenter** dès que ce que
#: `serialiser` range change pour une même sortie — et avec elle, les
#: dérivés déjà rangés deviennent périmés (voir le module).
VERSION_DERIVATION = 1

#: Le motif d'une sortie dont le fichier n'est plus là et dont le dérivé
#: manque ou est périmé : il faut redéposer l'archive pour qu'elle compte.
MOTIF_A_REDEPOSER = "à redéposer"

#: Combien d'appels à l'archive météo un import garde en vol. La cadence du
#: service borne de toute façon le débit réseau ; ceci borne la mémoire :
#: autant de sorties lues attendent leur vent.
APPELS_SIMULTANES = 6

#: Ce que les statuts de `Derivateur.__call__` veulent dire.
STATUT_EN_ATTENTE = "en_attente"
STATUT_INEXPLOITABLE = "inexploitable"
STATUT_HORS_CALIBRATION = "hors_calibration"

#: Les champs d'un tronçon qu'on range, dans cet ordre. Ni `lat`, ni `lon`,
#: ni `t`, ni `dist_m` : la position, l'instant et la place dans la sortie
#: restent dans le fichier, qui s'en va.
_CHAMPS_ECHANTILLON = (
    "v_ms",
    "puissance_w",
    "pente",
    "vent_face_ms",
    "temp_c",
    "motif",
    "longueur_m",
    "rho",
    "vent_connu",
    "v_debut_ms",
    "v_fin_ms",
    "au_depart",
    "accelere_voisin",
)


def candidate(entree: EntreeCache) -> bool:
    """Vrai si une calibration pourrait retenir cette sortie, pour l'un ou l'autre vélo.

    Les filtres de `calibration.motif_exclusion` (via `services.calibrer`)
    qui ne dépendent d'**aucun** réglage du cycliste : du vélo, en extérieur,
    avec puissance, 20 km et plus. Le vélo, les mots de groupe et la date de
    début d'historique, eux, se décident à la calibration.
    """
    return (
        est_sport_velo(entree.sport)
        and not en_interieur(entree)
        and entree.puissance_moy_w is not None
        and (entree.distance_m or 0.0) >= calib.DISTANCE_MINIMALE_M
    )


def entree_de(activite: Activite, identifiant: str, meta: dict | None = None) -> EntreeCache:
    """La ligne d'index qu'`Cache.ajouter` écrirait pour cette activité — sans relire l'index."""
    meta = meta or {}
    return EntreeCache(
        identifiant=identifiant,
        source="fichier",
        id_externe=identifiant,
        debut=activite.debut,
        duree_s=activite.duree_s,
        distance_m=activite.distance_m,
        puissance_moy_w=activite.puissance_moy_w
        if activite.puissance_moy_w is not None
        else meta.get("puissance_moy_w"),
        sport=meta.get("sport") or activite.sport,
        appareil=meta.get("appareil") or activite.appareil,
        equipement=meta.get("equipement") or None,
        chemin=Path(),
        meta=dict(meta),
    )


# --- sérialisation --------------------------------------------------------------


def melanger(d: SortieDerivee, alea: random.Random | None = None) -> SortieDerivee:
    """Le même dérivé, tronçons et pas **dans le désordre**, sans distance cumulée ni nom.

    `alea` n'est donné que par les tests ; sinon, le hasard du système, dont
    la graine n'est écrite nulle part. Mélanger avant de sérialiser retire
    tout ce qui pourrait redonner la trace par navigation à l'estime — une
    suite de pentes et de vents de face le long de la distance, rapprochée du
    vent public du jour, redonne le cap pas à pas.
    """
    alea = alea or random.SystemRandom()
    echantillons = [replace(e, dist_m=0.0, lat=None, lon=None, t=None) for e in d.echantillons]
    alea.shuffle(echantillons)
    profil = d.profil
    if profil is not None:
        if profil.longueurs is None:
            bornes = _bornes_pas(profil.distance_m)
            pas = [
                (bornes[i + 1] - bornes[i], profil.pentes[i], profil.vents_face_ms[i])
                for i in range(len(bornes) - 1)
                if bornes[i + 1] - bornes[i] > 0
            ]
        else:
            pas = list(zip(profil.longueurs, profil.pentes, profil.vents_face_ms, strict=True))
        alea.shuffle(pas)
        profil = ProfilSimulation(
            distance_m=profil.distance_m,
            pentes=tuple(p[1] for p in pas),
            vents_face_ms=tuple(p[2] for p in pas),
            longueurs=tuple(p[0] for p in pas),
        )
    return replace(d, nom="", echantillons=echantillons, profil=profil, _qualifies={})


def serialiser(d: SortieDerivee, alea: random.Random | None = None) -> bytes:
    """Le dérivé en octets (JSON compressé), **mélangé** (`melanger`). Les nombres
    gardent toute leur précision : `json` sérialise un flottant par son
    `repr`, qui se relit à l'identique."""
    d = melanger(d, alea)
    colonnes: dict[str, list] = {nom: [] for nom in _CHAMPS_ECHANTILLON}
    for e in d.echantillons:
        for nom in _CHAMPS_ECHANTILLON:
            colonnes[nom].append(_nombre(getattr(e, nom)))
    charge = {
        "version": VERSION_DERIVATION,
        "jour": d.jour.isoformat() if d.jour else None,
        "duree_ecoulee_s": d.duree_ecoulee_s,
        "temps_mouvement_s": d.temps_mouvement_s,
        "puissance_mouvement_w": d.puissance_mouvement_w,
        "vent_manquant": d.vent_manquant,
        "refus_profil": d.refus_profil,
        "echantillons": colonnes,
        "profil": None
        if d.profil is None
        else {
            "distance_m": d.profil.distance_m,
            "longueurs": list(d.profil.longueurs or ()),
            "pentes": list(d.profil.pentes),
            "vents_face_ms": list(d.profil.vents_face_ms),
        },
    }
    texte = json.dumps(charge, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    return zlib.compress(texte.encode("utf-8"), 6)


def deserialiser(octets: bytes) -> SortieDerivee:
    """L'inverse de `serialiser`. Lève `ErreurUtilisateur` sur un contenu illisible."""
    try:
        charge = json.loads(zlib.decompress(octets).decode("utf-8"))
        colonnes = charge["echantillons"]
        n = len(colonnes["v_ms"])
        echantillons = [
            calib.Echantillon(
                v_ms=colonnes["v_ms"][i],
                puissance_w=colonnes["puissance_w"][i],
                pente=colonnes["pente"][i],
                vent_face_ms=colonnes["vent_face_ms"][i],
                temp_c=_flottant(colonnes["temp_c"][i]),
                retenu=False,
                motif=colonnes["motif"][i],
                longueur_m=colonnes["longueur_m"][i],
                rho=colonnes["rho"][i],
                vent_connu=bool(colonnes["vent_connu"][i]),
                t=None,
                v_debut_ms=colonnes["v_debut_ms"][i],
                v_fin_ms=colonnes["v_fin_ms"][i],
                au_depart=bool(colonnes["au_depart"][i]),
                accelere_voisin=bool(colonnes["accelere_voisin"][i]),
            )
            for i in range(n)
        ]
        profil = charge["profil"]
        return SortieDerivee(
            jour=date.fromisoformat(charge["jour"]) if charge["jour"] else None,
            nom="",
            duree_ecoulee_s=charge["duree_ecoulee_s"],
            temps_mouvement_s=charge["temps_mouvement_s"],
            puissance_mouvement_w=charge["puissance_mouvement_w"],
            echantillons=echantillons,
            profil=None
            if profil is None
            else ProfilSimulation(
                distance_m=profil["distance_m"],
                pentes=tuple(profil["pentes"]),
                vents_face_ms=tuple(profil["vents_face_ms"]),
                longueurs=tuple(profil["longueurs"]),
            ),
            refus_profil=str(charge.get("refus_profil") or ""),
            vent_manquant=bool(charge.get("vent_manquant")),
        )
    except (zlib.error, ValueError, KeyError, TypeError, IndexError) as e:
        raise ErreurUtilisateur(f"dérivé illisible ({type(e).__name__})") from e


def en_json(octets: bytes) -> dict:
    """Le dérivé tel qu'il est stocké, décompressé — pour l'export RGPD."""
    try:
        return json.loads(zlib.decompress(octets).decode("utf-8"))
    except (zlib.error, ValueError) as e:
        raise ErreurUtilisateur(f"dérivé illisible ({type(e).__name__})") from e


def _nombre(valeur):
    """`NaN` (température inconnue) n'existe pas en JSON : il voyage en `null`."""
    if isinstance(valeur, float) and not math.isfinite(valeur):
        return None
    return valeur


def _flottant(valeur) -> float:
    return float("nan") if valeur is None else valeur


# --- à l'import ------------------------------------------------------------------


@dataclass
class _EnAttente:
    identifiant: str
    nom: str
    activite: Activite
    deja: bool
    vent: Future | None


@dataclass
class Derivateur:
    """Dérive, à l'import, les sorties qu'une calibration pourrait retenir. Voir le module.

    `__call__` lit ce qui ne demande pas de réseau et envoie la demande
    d'archive météo en fond ; le dérivé est calculé et rangé quand le vent
    arrive, au plus tard à `terminer()`. Au plus `APPELS_SIMULTANES` sorties
    attendent en mémoire. Une archive indisponible ne fait pas échouer
    l'import : la sortie est dérivée **sans vent**, comptée, et refaite au
    prochain dépôt (`a_rafraichir`).

    `verifier`, s'il est donné, est appelé avant chaque écriture — la tâche
    de fond y passe sa vérification d'annulation : un compte supprimé pendant
    l'import ne reçoit plus rien.
    """

    cache: Cache
    client_archive: ClientArchive | None
    verifier: Callable[[], None] | None = None
    appels_simultanes: int = APPELS_SIMULTANES
    derivees: int = 0
    rafraichies: int = 0
    inexploitables: int = 0
    sans_vent: int = 0
    echecs: list[tuple[str, str]] = field(default_factory=list)
    _connus: dict[str, tuple[int, str, bool]] | None = field(default=None, repr=False)
    _candidats: set[str] | None = field(default=None, repr=False)
    _file: deque = field(default_factory=deque, repr=False)
    _pool: ThreadPoolExecutor | None = field(default=None, repr=False)

    def a_rafraichir(self, identifiant: str) -> bool:
        """Cette sortie, déjà indexée, attend-elle un dérivé (absent, périmé, ou tiré sans vent) ?

        Sur l'index seul, sans relire le fichier : c'est ce qui permet au
        dépôt de ne relire, dans une archive redéposée, que les sorties qui
        comptent. Une sortie tirée sans vent — archive en panne, ou jour trop
        récent pour elle — se refait à chaque dépôt, jusqu'à ce que le vent
        soit là.
        """
        if self._connus is None or self._candidats is None:
            self._connus = self.cache.etats_derives()
            self._candidats = {e.identifiant for e in self.cache.lister() if candidate(e)}
        if identifiant not in self._candidats:
            return False
        connu = self._connus.get(identifiant)
        return connu is None or connu[0] != VERSION_DERIVATION or connu[2]

    def __call__(
        self,
        identifiant: str,
        activite: Activite,
        meta: dict | None = None,
        *,
        nom: str = "",
        deja: bool = False,
    ) -> str:
        """Prend en charge cette sortie si elle est candidate. Rend un `STATUT_…`."""
        try:
            if not candidate(entree_de(activite, identifiant, meta)):
                return STATUT_HORS_CALIBRATION
            motif = calib.motif_multisport(activite)
            if motif is None and trace_depuis_activite(activite) is None:
                motif = "sans trace"
        except Exception as e:  # noqa: BLE001 — une sortie hostile ne fait pas échouer l'import
            self.echecs.append((nom or identifiant[:12], str(e) or type(e).__name__))
            return STATUT_INEXPLOITABLE
        if motif is not None:
            self._ecrire(identifiant, contenu=None, motif=motif, vent_manquant=False)
            self.inexploitables += 1
            return STATUT_INEXPLOITABLE
        self._file.append(_EnAttente(identifiant, nom, activite, deja, self._demander_vent(activite)))
        while len(self._file) > self.appels_simultanes:
            self._deriver(self._file.popleft())
        return STATUT_EN_ATTENTE

    def terminer(self) -> None:
        """Dérive tout ce qui attend encore son vent, puis rend les fils."""
        try:
            while self._file:
                self._deriver(self._file.popleft())
        finally:
            self.fermer()

    def fermer(self) -> None:
        """Abandonne ce qui attend (annulation, panne) et rend les fils. Idempotent."""
        self._file.clear()
        if self._pool is not None:
            self._pool.shutdown(wait=True, cancel_futures=True)
            self._pool = None

    def _demander_vent(self, activite: Activite) -> Future | None:
        depart = next((p for p in activite.points if p.lat is not None and p.lon is not None), None)
        client = self.client_archive
        if depart is None or activite.debut is None or client is None:
            return None
        lat, lon = depart.lat, depart.lon
        if lat is None or lon is None:
            return None
        if self._pool is None:
            self._pool = ThreadPoolExecutor(
                max_workers=self.appels_simultanes, thread_name_prefix="archive-meteo"
            )
        return self._pool.submit(client.horaires, float(lat), float(lon), activite.debut.date())

    def _deriver(self, attente: _EnAttente) -> None:
        vent: list = []
        if attente.vent is not None:
            try:
                vent = attente.vent.result()
            except (ErreurConnecteur, ErreurUtilisateur):
                vent = []
        try:
            contenu = serialiser(calib.deriver_sortie(attente.activite, vent))
        except Exception as e:  # noqa: BLE001 — une sortie hostile ne fait pas échouer l'import
            self.echecs.append((attente.nom or attente.identifiant[:12], str(e) or type(e).__name__))
            return
        self._ecrire(attente.identifiant, contenu=contenu, motif="", vent_manquant=not vent)
        self.derivees += 1
        if attente.deja:
            self.rafraichies += 1
        if not vent:
            self.sans_vent += 1

    def _ecrire(self, identifiant: str, *, contenu: bytes | None, motif: str, vent_manquant: bool) -> None:
        if self.verifier is not None:
            self.verifier()
        self.cache.ecrire_derive(
            identifiant,
            version=VERSION_DERIVATION,
            contenu=contenu,
            motif=motif,
            vent_manquant=vent_manquant,
        )
        if self._connus is not None:
            self._connus[identifiant] = (VERSION_DERIVATION, motif, vent_manquant)


# --- à la calibration --------------------------------------------------------------


def etat(cache: Cache, entrees: Iterable[EntreeCache]) -> dict[str, str | None]:
    """`{identifiant: None | motif}` : `None` si le dérivé est là et à jour, sinon pourquoi pas.

    Sur la seule table des versions, sans décompresser aucun dérivé : c'est
    ce que l'écran consulte pour compter. Un dérivé sans vent est utilisable :
    il compte, un peu moins précis (la calibration le dit dans ses pannes).
    """
    connus = cache.versions_derives()
    resultat: dict[str, str | None] = {}
    for entree in entrees:
        connu = connus.get(entree.identifiant)
        if connu is None or connu[0] != VERSION_DERIVATION:
            resultat[entree.identifiant] = MOTIF_A_REDEPOSER
        else:
            resultat[entree.identifiant] = connu[1] or None
    return resultat


def trier(cache: Cache, entrees: list[EntreeCache]) -> tuple[list[EntreeCache], dict[str, int]]:
    """(sorties dont le dérivé est utilisable, décompte des autres par motif)."""
    motifs: dict[str, int] = {}
    gardees: list[EntreeCache] = []
    statut = etat(cache, entrees)
    for entree in entrees:
        motif = statut[entree.identifiant]
        if motif is None:
            gardees.append(entree)
        else:
            motifs[motif] = motifs.get(motif, 0) + 1
    return (gardees, motifs)


def purger_avec_derivation(
    cache: Cache,
    client_archive,
    *,
    verifier: Callable[[], None] | None = None,
    avancer: Callable[[int, int], None] | None = None,
) -> dict:
    """Dérive puis efface les fichiers d'origine déjà déposés — le geste de « ne plus les garder ».

    **Dans cet ordre, et c'est ce qui compte** : chaque sortie qu'une
    calibration pourrait retenir (`candidate`) est dérivée pendant que son
    fichier est encore là — c'est le seul moment où l'archive météo peut
    encore être appelée pour elle (`Derivateur`, comme à l'import) —, et ce
    n'est qu'une fois **toutes** dérivées que `Cache.effacer_bruts` retire
    les fichiers d'un coup. Effacer d'abord et dériver ensuite laisserait
    les sorties déjà passées sans trace ni dérivé si la tâche s'arrêtait en
    cours de route (panne, compte supprimé) : l'ordre inverse est sans
    risque, une sortie déjà dérivée reste dérivée même si le reste échoue.

    Une sortie hors calibration (home-trainer, sans puissance, trop courte)
    n'a rien à dériver ; son fichier part quand même avec les autres.

    `verifier` : la vérification d'annulation à passer à chaque écriture
    (`Job.verifier_annulation`) — un compte supprimé pendant la tâche ne
    reçoit plus rien, exactement comme un import. `avancer(traites, total)`
    suit la dérivation ; l'effacement lui-même, une fois les fichiers déjà
    connus, ne dure pas assez pour valoir un second décompte.
    """
    entrees = [e for e in cache.lister() if candidate(e)]
    deriver = Derivateur(cache=cache, client_archive=client_archive, verifier=verifier)
    total = len(entrees)
    try:
        for rang, entree in enumerate(entrees, start=1):
            if avancer is not None:
                avancer(rang, total)
            try:
                activite = cache.relire(entree.identifiant)
            except (KeyError, ErreurUtilisateur, OSError):
                continue  # fichier déjà absent ou illisible : rien à en tirer, il part quand même
            deriver(
                entree.identifiant,
                activite,
                entree.meta,
                nom=str(entree.meta.get("fichier") or ""),
                deja=True,
            )
        deriver.terminer()
    except BaseException:
        deriver.fermer()
        raise
    fichiers_effaces = cache.effacer_bruts()
    return {
        "candidates": total,
        "derivees": deriver.derivees,
        "sans_vent": deriver.sans_vent,
        "echecs": len(deriver.echecs),
        "fichiers_effaces": fichiers_effaces,
    }


def charger(
    cache: Cache,
    entrees: list[EntreeCache],
    avancer: Callable[[int], None] | None = None,
) -> tuple[list[calib.SortieCalibration], list[str]]:
    """Les `SortieCalibration` de ces sorties, relues sur leur seul dérivé.

    Le pendant de `services.calibrer._charger_sorties` sans la trace : une
    sortie dont le dérivé ne se relit pas est signalée et passée ; une
    sortie dérivée sans vent (archive indisponible au dépôt) l'est aussi,
    comme une archive indisponible en mode personnel.
    """
    sorties: list[calib.SortieCalibration] = []
    pannes: list[str] = []
    for rang, entree in enumerate(entrees, start=1):
        if avancer is not None:
            avancer(rang)
        lu = cache.lire_derive(entree.identifiant)
        if lu is None or lu[0] != VERSION_DERIVATION or lu[2] is None:
            pannes.append(f"sortie {entree.identifiant[:12]} : dérivé absent ou périmé")
            continue
        try:
            derivee = deserialiser(lu[2])
        except ErreurUtilisateur as e:
            pannes.append(f"sortie {entree.identifiant[:12]} : {e}")
            continue
        nom = entree.meta.get("nom")
        if nom:
            derivee.nom = str(nom)
        if derivee.vent_manquant:
            pannes.append(f"sortie du {derivee.jour} : vent inconnu (archive météo indisponible au dépôt)")
        sorties.append(calib.SortieCalibration.depuis_derivee(derivee, identifiant=entree.identifiant))
    return (sorties, pannes)


__all__ = [
    "APPELS_SIMULTANES",
    "MOTIF_A_REDEPOSER",
    "STATUT_EN_ATTENTE",
    "STATUT_HORS_CALIBRATION",
    "STATUT_INEXPLOITABLE",
    "VERSION_DERIVATION",
    "Derivateur",
    "candidate",
    "charger",
    "deserialiser",
    "en_json",
    "entree_de",
    "etat",
    "melanger",
    "purger_avec_derivation",
    "serialiser",
    "trier",
]
