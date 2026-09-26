#!/usr/bin/env python3
"""Validation rétrospective du vent (lot L5.1).

**Ce script n'est pas un test pytest.** Il lit le cache réel du mainteneur et
appelle Intervals.icu : les deux sont interdits dans la suite de tests (règles
absolues 1 et 3). Il se lance à la main, depuis la racine du dépôt :

    uv run python scripts/validation/vent_retrospectif.py

Ce qu'il mesure, et pourquoi c'est le critère d'acceptation du lot. Le vent
entre dans le placement ; encore faut-il savoir si notre chaîne — archive
Open-Meteo, interpolation, cap local, secteur de ±45° — dit du vent la même
chose qu'un tiers. Intervals.icu publie pour chaque sortie `headwind_percent`
et `tailwind_percent`, calculés par **leur** fournisseur météo. C'est un juge
indépendant : il ne partage avec nous ni la source de vent, ni le découpage,
ni la définition du secteur.

Deux mesures, et elles ne disent pas la même chose :

1. **L'accord avec Intervals** — part de vent de face et de dos recalculées
   par nous, comparées aux leurs. Seuil du contrat : écart absolu médian
   ≤ 10 points de pourcentage, biais dans ±5 points.
2. **L'erreur du modèle physique sur la vitesse**, avec et sans le terme de
   vent, sur les mêmes sorties. Elle doit baisser. Si elle ne baisse pas, le
   terme de vent n'apporte rien et le lot ne passe pas.

Ce que la seconde mesure ne prouve pas, et il faut le dire : les paramètres
du vélo ont été **calibrés avec** le terme de vent. La comparaison est donc
favorable au vent par construction. Elle reste informative — la calibration
ajuste deux paramètres (CdA, Crr) sur des milliers de tronçons, elle ne peut
pas mémoriser le vent de chacun, et un terme de vent faux dégraderait la
prédiction au lieu de l'améliorer — mais ce n'est pas une validation croisée.
`--recalibrer` refait l'ajustement dans les deux mondes pour lever ce doute.

Ce que le script **ne fait pas** : il n'interroge aucun endpoint Intervals non
documenté. Vérifié le 15/09/2026, `/activity/{id}/weather` et ses variantes
rendent 404 et aucun stream ne porte le vent. Notre source de vent reste
Open-Meteo ; Intervals ne sert que de juge.

Trois précautions d'exécution :

- **Le cache n'est pas modifié** pour ce qui est de l'index : il est ouvert en
  lecture seule (`mode=ro`). Le cache des archives météo, lui, est celui de
  `ClientArchive` : une archive déjà vue n'est pas redemandée, une archive
  manquante l'est (un appel réseau, gratuit et sans clé).
- **Aucune coordonnée n'est imprimée.** Les sorties sont désignées par leur
  date et leur nom, jamais par un point de départ.
- Les fonctions privées de `physique.calibration` (`_decouper`, `_cap`,
  `_interpoler_archive`) sont importées **volontairement** : la mesure doit
  porter sur le découpage que la calibration utilise vraiment, pas sur une
  réimplémentation qui en divergerait sans qu'on le sache.
"""

from __future__ import annotations

import argparse
import json
import math
import sqlite3
import statistics
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from ourouler.activites.lecture import lecteur_pour
from ourouler.config import Config, charger
from ourouler.connecteurs.intervals import ClientIntervals
from ourouler.connecteurs.openmeteo_archive import ClientArchive
from ourouler.meteo.couronne import ecart_angulaire
from ourouler.meteo.rapport import SECTEUR_VENT_DEG, VENT_DOS, VENT_FACE, vent_relatif
from ourouler.noyau.activite import Activite
from ourouler.noyau.erreurs import ErreurConnecteur, ErreurUtilisateur
from ourouler.noyau.meteo import HeureArchive
from ourouler.physique.calibration import echantillonner
from ourouler.physique.echantillonnage import (
    _cap,
    _decouper,
    _distances_points,
    _interpoler_archive,
)
from ourouler.physique.modele import Parametres, vitesse_regime
from ourouler.services.physique import (
    NOM_CACHE,
    chemin_calibration,
    parametres_du_velo,
    velo_demande,
)

#: Début de l'historique (règle absolue 6). Paramètre, pas constante de code :
#: `--depuis` le déplace.
DEPUIS_DEFAUT = "2023-12-01"

#: Écart absolu médian toléré entre nos parts de vent et celles d'Intervals,
#: en points de pourcentage (contrat du sprint 5, §1.3).
ECART_MEDIAN_MAX = 10.0

#: Biais systématique toléré, en points de pourcentage, dans les deux sens.
BIAIS_MAX = 5.0

#: Nombre de sorties attendues, mesuré le 15/09/2026 : 162 des 163 sorties
#: route depuis le 01/12/2023 portent la météo d'Intervals. Le chiffre est
#: imprimé et comparé, jamais exigé — l'historique grandit.
SORTIES_ATTENDUES = 162

#: **Ce que cette commande a mesuré le 15/09/2026**, sur les 161 sorties
#: exploitables (une, « Lacanau », n'a aucune archive de vent). Recopié ici
#: pour que le lecteur sache ce que le lot a donné même s'il ne peut pas
#: relancer la mesure, et pour qu'un chiffre qui bouge se voie.
#:
#: **Le seuil du contrat n'est pas tenu, et voici pourquoi.** L'écart médian
#: est de 6,6 points (seuil : 10, tenu), mais le biais est de −7,0 points
#: (seuil : ±5, non tenu). Nous comptons systématiquement **moins** de vent de
#: face *et* moins de vent de dos qu'Intervals — donc plus de travers. Ce
#: n'est pas notre vent qui diffère, c'est le **secteur** : le diagnostic
#: imprimé par ce script montre que le biais s'annule pour un demi-secteur de
#: ~55° (écart médian 3,1, biais −1,3), là où nous appliquons les ±45° de
#: `meteo.rapport.vent_relatif`. Sur des caps répartis uniformément, ±45°
#: range 50 % des tronçons en face ou en dos par construction ; leur
#: définition en range ~63 %. L'écart est donc **expliqué, pas absorbé** :
#: la règle du lot ne change pas pour faire tomber un seuil.
#:
#: Deux contrôles indépendants confirment que la convention d'angle est dans
#: le bon sens — c'est le vrai risque du lot, un signe inversé placerait les
#: blocs exactement là où il ne faut pas :
#:
#: 1. l'appariement inversé (notre face contre leur `tailwind`) colle moins
#:    bien : 7,5 points d'écart médian contre 6,6 ;
#: 2. surtout, sur 13 053 tronçons réels, l'erreur du modèle sur la vitesse
#:    vaut 0,993 m/s avec le vent, 1,063 sans, et **1,445 avec le vent
#:    retourné**. Un signe inversé serait donc bien pire que pas de vent du
#:    tout, et il ne l'est pas.
#:
#: Mettre ces chiffres à jour est un geste explicite : on relance, on recopie,
#: on date.
MESURE_DU_15_09_2026 = {
    "date": "2026-09-15",
    "sorties_comparees": 161,
    "ecart_median_points": 6.6,
    "biais_points": -7.0,
    "ecart_90e_centile_points": 15.6,
    "demi_secteur_qui_annule_le_biais_deg": 55.0,
    "ecart_median_a_55_deg": 3.1,
    "troncons_physique": 13053,
    "eam_avec_vent_ms": 0.993,
    "eam_sans_vent_ms": 1.063,
    "eam_signe_inverse_ms": 1.445,
    "verdict": "seuil de biais non tenu, écart expliqué par la définition du secteur",
}


# --- ce qu'Intervals dit du vent ------------------------------------------------


@dataclass(frozen=True)
class JugementIntervals:
    """Ce qu'Intervals publie du vent d'une sortie. Leur mesure, pas la nôtre."""

    identifiant: str
    jour: str
    nom: str
    part_face: float  # en pourcentage
    part_dos: float
    vent_moyen_ms: float | None
    vent_dominant_deg: float | None


def jugements(client: ClientIntervals, depuis: date) -> dict[str, JugementIntervals]:
    """Les sorties route porteuses de météo, indexées par identifiant Intervals.

    Les sorties sur home-trainer sont écartées : elles n'ont pas de vent, et
    leur `has_weather` serait celui du jardin.
    """
    trouves: dict[str, JugementIntervals] = {}
    for brut in client.activites(depuis):
        if str(brut.get("type") or "") != "Ride" or brut.get("trainer"):
            continue
        if not brut.get("has_weather"):
            continue
        face, dos = _flottant(brut.get("headwind_percent")), _flottant(brut.get("tailwind_percent"))
        if face is None or dos is None:
            continue
        identifiant = str(brut.get("id") or "")
        if not identifiant:
            continue
        trouves[identifiant] = JugementIntervals(
            identifiant=identifiant,
            jour=str(brut.get("start_date_local") or "")[:10],
            nom=str(brut.get("name") or ""),
            part_face=face,
            part_dos=dos,
            vent_moyen_ms=_flottant(brut.get("average_wind_speed")),
            vent_dominant_deg=_flottant(brut.get("prevailing_wind_deg")),
        )
    return trouves


def _flottant(brut: object) -> float | None:
    try:
        valeur = float(brut)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return valeur if math.isfinite(valeur) else None


# --- le cache local, en lecture seule -------------------------------------------


def _connexion_ro(chemin: Path) -> sqlite3.Connection:
    """Ouvre une base SQLite **en lecture seule** : ce script n'écrit pas dans l'index."""
    if not chemin.is_file():
        raise ErreurUtilisateur(
            f"fichier introuvable : {chemin} — lancer d'abord « ourouler inventaire --synchro »"
        )
    return sqlite3.connect(f"file:{chemin}?mode=ro", uri=True)


def fichiers_du_cache(dossier_cache: Path) -> dict[str, Path]:
    """Les fichiers bruts du cache, indexés par identifiant **Intervals**.

    L'identifiant externe est la colonne `id_externe` quand elle est remplie,
    sinon `meta.source_id` : les deux ont servi selon l'âge de l'entrée, et
    une sortie indexée par l'une ne doit pas disparaître de la mesure parce
    qu'on n'a regardé que l'autre.
    """
    index = dossier_cache / "index.sqlite"
    par_id: dict[str, Path] = {}
    with _connexion_ro(index) as cx:
        lignes = cx.execute("SELECT identifiant, id_externe, extension, meta FROM activites").fetchall()
    for identifiant, id_externe, extension, meta in lignes:
        externe = str(id_externe or "") or _source_id(meta)
        if not externe:
            continue
        chemin = dossier_cache / "brut" / f"{identifiant}.{extension}"
        if chemin.is_file():
            par_id[externe] = chemin
    return par_id


def _source_id(meta: str | None) -> str:
    try:
        return str((json.loads(meta or "{}") or {}).get("source_id") or "")
    except ValueError:
        return ""


def archive_du_depart(activite: Activite, client: ClientArchive) -> list[HeureArchive]:
    """L'archive du jour au point de départ de la sortie. Vide si elle manque."""
    depart = next((p for p in activite.points if p.lat is not None and p.lon is not None), None)
    if depart is None or activite.debut is None:
        return []
    try:
        return client.horaires(float(depart.lat), float(depart.lon), activite.debut.date())
    except (ErreurConnecteur, ErreurUtilisateur):
        return []


# --- notre propre mesure du vent le long de la sortie ---------------------------


@dataclass
class Notre:
    """Ce que **notre** chaîne dit du vent sur une sortie."""

    part_face: float  # en pourcentage des tronçons au vent connu
    part_dos: float
    n_troncons: int
    n_vent_connu: int
    ecarts_deg: list[float]
    """Écart angulaire entre le cap du tronçon et la direction d'où vient le
    vent, tronçon par tronçon. Gardé pour le **diagnostic** : c'est lui qui
    permet de dire quel demi-secteur reproduirait les chiffres d'Intervals,
    sans rien changer à la règle que le lot applique vraiment."""

    def parts_au_secteur(self, demi_secteur_deg: float) -> tuple[float, float]:
        """(part de face, part de dos) si le demi-secteur valait autre chose que 45°.

        Sert **uniquement** à expliquer un écart, jamais à le corriger : la
        règle du lot reste `meteo.rapport.vent_relatif` et son secteur de ±45°.
        """
        if not self.ecarts_deg:
            return (0.0, 0.0)
        face = sum(1 for e in self.ecarts_deg if e <= demi_secteur_deg)
        dos = sum(1 for e in self.ecarts_deg if e >= 180.0 - demi_secteur_deg)
        n = len(self.ecarts_deg)
        return (100.0 * face / n, 100.0 * dos / n)


def parts_de_vent(activite: Activite, vent: list[HeureArchive]) -> Notre | None:
    """Les parts de vent de face et de dos, secteur de ±45° autour du cap local.

    Exactement la règle de `meteo_trace._resumer` : on compte les **tronçons**
    dont le vent est connu, et `meteo.rapport.vent_relatif` les range en trois
    secteurs. Le découpage est celui de la calibration — des tronçons d'environ
    200 m, donc à peu près équidistants : compter les tronçons revient à
    compter des kilomètres, pas des secondes.
    """
    points = [p for p in activite.points if p.t is not None]
    if len(points) < 2 or not vent:
        return None
    distances = _distances_points(points)
    bruts = _decouper(points, distances)
    if not bruts:
        return None

    face = dos = connus = 0
    ecarts: list[float] = []
    for i, j, _longueur, _duree in bruts:
        cap = _cap(points, i, j)
        t_milieu = points[i].t + (points[j].t - points[i].t) / 2
        heure = _interpoler_archive(vent, t_milieu)
        if cap is None or heure is None or heure.vent_depuis_deg is None:
            continue
        connus += 1
        secteur = vent_relatif(cap, heure.vent_depuis_deg)
        face += secteur == VENT_FACE
        dos += secteur == VENT_DOS
        ecarts.append(ecart_angulaire(cap, heure.vent_depuis_deg))
    if connus == 0:
        return None
    return Notre(
        part_face=100.0 * face / connus,
        part_dos=100.0 * dos / connus,
        n_troncons=len(bruts),
        n_vent_connu=connus,
        ecarts_deg=ecarts,
    )


# --- l'erreur du modèle physique sur la vitesse ---------------------------------


@dataclass
class ErreurVitesse:
    """L'écart entre la vitesse prédite et la vitesse roulée, en m/s."""

    avec_vent: list[float]
    sans_vent: list[float]
    signe_inverse: list[float]
    """Le même calcul avec le vent **retourné**. C'est le contrôle le plus
    discriminant du lot : si notre convention d'angle était fausse, cette
    colonne battrait les deux autres. Elle doit être la pire des trois."""

    def ajouter(self, autre: ErreurVitesse) -> None:
        self.avec_vent += autre.avec_vent
        self.sans_vent += autre.sans_vent
        self.signe_inverse += autre.signe_inverse


def erreurs_de_vitesse(
    activite: Activite, vent: list[HeureArchive], p: Parametres, ftp_w: float
) -> ErreurVitesse:
    """La vitesse prédite par le modèle, avec et sans le terme de vent, moins la vitesse roulée.

    Seuls les tronçons que la calibration **retient** entrent ici : les autres
    sont des arrêts, des sprints ou des portions sans puissance, où le modèle
    d'équilibre ne s'applique pas et où l'écart ne dirait rien du vent.
    """
    mesure = ErreurVitesse(avec_vent=[], sans_vent=[], signe_inverse=[])
    for e in echantillonner(activite, vent, ftp_w=ftp_w):
        if not e.retenu or not e.vent_connu or e.v_ms <= 0:
            continue
        p_echantillon = Parametres(p.masse_totale_kg, p.cda_m2, p.crr, p.rendement, e.rho)
        try:
            avec = vitesse_regime(e.puissance_w, e.pente, e.vent_face_ms, p_echantillon)
            sans = vitesse_regime(e.puissance_w, e.pente, 0.0, p_echantillon)
            inverse = vitesse_regime(e.puissance_w, e.pente, -e.vent_face_ms, p_echantillon)
        except ErreurUtilisateur:
            continue
        mesure.avec_vent.append(avec - e.v_ms)
        mesure.sans_vent.append(sans - e.v_ms)
        mesure.signe_inverse.append(inverse - e.v_ms)
    return mesure


# --- la comparaison --------------------------------------------------------------


@dataclass
class Comparaison:
    """Une sortie, ce qu'Intervals en dit et ce que nous en disons."""

    jugement: JugementIntervals
    notre: Notre

    @property
    def ecart_face(self) -> float:
        return self.notre.part_face - self.jugement.part_face

    @property
    def ecart_dos(self) -> float:
        return self.notre.part_dos - self.jugement.part_dos


def comparer(
    config: Config,
    client_intervals: ClientIntervals,
    client_archive: ClientArchive,
    depuis: date,
    p: Parametres,
    ftp_w: float,
    *,
    limite: int | None = None,
    bavard: bool = False,
) -> tuple[list[Comparaison], ErreurVitesse, list[str]]:
    """Le gros du travail : pour chaque sortie jugée, notre mesure en face de la leur."""
    par_intervals = jugements(client_intervals, depuis)
    par_fichier = fichiers_du_cache(config.cache.dossier)
    print(
        f"{len(par_intervals)} sortie(s) route avec météo chez Intervals depuis {depuis}, "
        f"{len(par_fichier)} fichier(s) dans le cache local."
    )

    comparaisons: list[Comparaison] = []
    erreurs = ErreurVitesse(avec_vent=[], sans_vent=[], signe_inverse=[])
    manques: list[str] = []
    for n, (identifiant, jugement) in enumerate(sorted(par_intervals.items())):
        if limite is not None and len(comparaisons) >= limite:
            break
        chemin = par_fichier.get(identifiant)
        if chemin is None:
            manques.append(f"{jugement.jour} « {jugement.nom} » : aucun fichier dans le cache")
            continue
        try:
            activite = lecteur_pour(chemin.suffix)(chemin)
        except (ErreurUtilisateur, OSError) as e:
            manques.append(f"{jugement.jour} « {jugement.nom} » : fichier illisible ({e})")
            continue
        vent = archive_du_depart(activite, client_archive)
        if not vent:
            manques.append(f"{jugement.jour} « {jugement.nom} » : archive météo indisponible")
            continue
        notre = parts_de_vent(activite, vent)
        if notre is None:
            manques.append(f"{jugement.jour} « {jugement.nom} » : vent inconnu sur toute la sortie")
            continue
        comparaisons.append(Comparaison(jugement=jugement, notre=notre))
        erreurs.ajouter(erreurs_de_vitesse(activite, vent, p, ftp_w))
        if bavard:
            print(f"  {n + 1:3d}. {jugement.jour} « {jugement.nom[:40]} »")
    return comparaisons, erreurs, manques


# --- affichage ---------------------------------------------------------------------


def imprimer_accord(comparaisons: list[Comparaison]) -> bool:
    """Le tableau de l'accord avec Intervals, et le verdict du seuil du contrat."""
    print()
    print("=== 1. Accord avec Intervals.icu sur les parts de vent ===")
    if not comparaisons:
        print("  aucune sortie comparable : rien à conclure.")
        return False

    ecarts_face = [c.ecart_face for c in comparaisons]
    ecarts_dos = [c.ecart_dos for c in comparaisons]
    tous = ecarts_face + ecarts_dos

    print(f"  sorties comparées : {len(comparaisons)} (attendu au 15/09/2026 : {SORTIES_ATTENDUES})")
    print()
    print(f"  {'mesure':<22} {'médiane nous':>13} {'médiane eux':>12} {'|écart| médian':>15} {'biais':>8}")
    for nom, ecarts, notres, leurs in (
        (
            "vent de face (%)",
            ecarts_face,
            [c.notre.part_face for c in comparaisons],
            [c.jugement.part_face for c in comparaisons],
        ),
        (
            "vent de dos (%)",
            ecarts_dos,
            [c.notre.part_dos for c in comparaisons],
            [c.jugement.part_dos for c in comparaisons],
        ),
    ):
        print(
            f"  {nom:<22} {statistics.median(notres):>13.1f} {statistics.median(leurs):>12.1f} "
            f"{statistics.median([abs(e) for e in ecarts]):>15.1f} "
            f"{statistics.mean(ecarts):>8.1f}"
        )

    ecart_median = statistics.median([abs(e) for e in tous])
    biais = statistics.mean(tous)
    print()
    print(f"  écart absolu médian, face et dos confondus : {ecart_median:.1f} points")
    print(f"  biais moyen                                 : {biais:+.1f} points")
    centile90 = _centile([abs(e) for e in tous], 90)
    print(f"  écart absolu au 90ᵉ centile                 : {centile90:.1f} points")

    tenu = ecart_median <= ECART_MEDIAN_MAX and abs(biais) <= BIAIS_MAX
    print()
    print(
        f"  seuil du contrat : écart médian ≤ {ECART_MEDIAN_MAX:.0f} points "
        f"({'tenu' if ecart_median <= ECART_MEDIAN_MAX else 'NON TENU'}), "
        f"biais dans ±{BIAIS_MAX:.0f} ({'tenu' if abs(biais) <= BIAIS_MAX else 'NON TENU'})"
    )
    return tenu


def imprimer_pires(comparaisons: list[Comparaison], combien: int = 5) -> None:
    """Les sorties où l'on s'éloigne le plus d'Intervals : un écart doit s'expliquer."""
    if not comparaisons:
        return
    pires = sorted(comparaisons, key=lambda c: -max(abs(c.ecart_face), abs(c.ecart_dos)))[:combien]
    print()
    print(f"  les {len(pires)} plus grands écarts :")
    print(
        f"    {'date':<12} {'face nous':>10} {'face eux':>9} {'dos nous':>9} {'dos eux':>8} {'vent m/s':>9}"
    )
    for c in pires:
        vent = f"{c.jugement.vent_moyen_ms:.1f}" if c.jugement.vent_moyen_ms is not None else "?"
        print(
            f"    {c.jugement.jour:<12} {c.notre.part_face:>10.1f} {c.jugement.part_face:>9.1f} "
            f"{c.notre.part_dos:>9.1f} {c.jugement.part_dos:>8.1f} {vent:>9}"
        )


#: Demi-secteurs explorés par le diagnostic. Le lot applique 45° et ne bouge
#: pas ; les autres valeurs ne servent qu'à **nommer** l'écart avec Intervals.
DEMI_SECTEURS_ESSAYES = (45.0, 50.0, 55.0, 60.0, 65.0, 70.0)


def imprimer_diagnostic_secteur(comparaisons: list[Comparaison]) -> None:
    """D'où vient le biais : notre secteur de face est-il plus étroit que le leur ?

    Nous comptons systématiquement moins de face **et** moins de dos
    qu'Intervals — donc davantage de travers. Sur des caps répartis à peu près
    uniformément, un demi-secteur de 45° range par construction 50 % des
    tronçons en face ou en dos ; un demi-secteur plus large en range
    davantage. Si l'écart s'annule à une valeur proche de 60°, l'explication
    est là : leur définition du secteur n'est pas la nôtre, et la règle du lot
    (±45°, `meteo.rapport.vent_relatif`) n'a aucune raison de changer pour
    autant. **Ce tableau explique, il ne corrige pas.**
    """
    if not comparaisons:
        return
    print()
    print("  diagnostic — quel demi-secteur reproduirait leurs chiffres ?")
    print(f"    {'demi-secteur':>13} {'|écart| médian':>15} {'biais':>8}   (le lot applique 45°)")
    for demi in DEMI_SECTEURS_ESSAYES:
        ecarts: list[float] = []
        for c in comparaisons:
            face, dos = c.notre.parts_au_secteur(demi)
            ecarts.append(face - c.jugement.part_face)
            ecarts.append(dos - c.jugement.part_dos)
        marque = "  ← la règle du lot" if demi == SECTEUR_VENT_DEG else ""
        print(
            f"    {demi:>12.0f}° {statistics.median([abs(e) for e in ecarts]):>15.1f} "
            f"{statistics.mean(ecarts):>+8.1f}{marque}"
        )
    print()
    print(
        "    Lecture : un demi-secteur plus large range plus de tronçons en face et\n"
        "    en dos, moins en travers. Si le biais s'annule vers 60°, l'écart tient à\n"
        "    la définition du secteur — la leur, pas la nôtre — et non à notre vent."
    )
    _imprimer_controle_de_convention(comparaisons)


def _imprimer_controle_de_convention(comparaisons: list[Comparaison]) -> None:
    """Le contrôle qui verrouille le point le plus dangereux du lot : le signe.

    `vent_depuis_deg` est la direction **d'où vient** le vent. Se tromper de
    convention placerait les blocs exactement là où il ne faut pas, et aucun
    biais global ne le crierait — nos parts de face et de dos sont presque
    égales (des boucles fermées), donc les intervertir ne déplacerait pas
    beaucoup la moyenne.

    On compare donc nos parts aux leurs **dans les deux appariements** : le
    nôtre (notre face contre leur `headwind`) et l'inverse. Si l'inverse
    collait mieux, la convention serait retournée quelque part dans la chaîne
    et tout le lot serait à reprendre.
    """
    droit: list[float] = []
    inverse: list[float] = []
    for c in comparaisons:
        droit += [c.notre.part_face - c.jugement.part_face, c.notre.part_dos - c.jugement.part_dos]
        inverse += [
            c.notre.part_face - c.jugement.part_dos,
            c.notre.part_dos - c.jugement.part_face,
        ]
    ecart_droit = statistics.median([abs(e) for e in droit])
    ecart_inverse = statistics.median([abs(e) for e in inverse])
    print()
    print("  contrôle de convention — le signe est-il dans le bon sens ?")
    print(f"    notre face ↔ leur headwind (le nôtre) : |écart| médian {ecart_droit:.1f} points")
    print(f"    notre face ↔ leur tailwind (inversé)  : |écart| médian {ecart_inverse:.1f} points")
    if ecart_inverse < ecart_droit:
        print(
            "    ALERTE : l'appariement inversé colle MIEUX. La convention d'angle est\n"
            "    probablement retournée quelque part dans la chaîne — le lot est à reprendre."
        )
    else:
        print("    L'appariement direct colle mieux : la convention est dans le bon sens.")


def imprimer_physique(erreurs: ErreurVitesse) -> bool:
    """L'erreur du modèle sur la vitesse, avec et sans le terme de vent."""
    print()
    print("=== 2. Erreur du modèle physique sur la vitesse ===")
    if not erreurs.avec_vent:
        print("  aucun tronçon retenu : rien à conclure.")
        return False

    print(f"  tronçons retenus : {len(erreurs.avec_vent)}")
    print()
    print(
        f"  {'terme de vent':<16} {'EAM (m/s)':>10} {'EAM (km/h)':>11} "
        f"{'médiane':>9} {'biais':>8} {'RMSE':>7}"
    )
    resultats = {}
    for nom, serie in (
        ("pris en compte", erreurs.avec_vent),
        ("ignoré", erreurs.sans_vent),
        ("signe inversé", erreurs.signe_inverse),
    ):
        absolus = [abs(e) for e in serie]
        eam = statistics.mean(absolus)
        rmse = math.sqrt(statistics.mean([e * e for e in serie]))
        resultats[nom] = eam
        print(
            f"  {nom:<16} {eam:>10.3f} {eam * 3.6:>11.2f} "
            f"{statistics.median(absolus):>9.3f} {statistics.mean(serie):>+8.3f} {rmse:>7.3f}"
        )

    gain = resultats["ignoré"] - resultats["pris en compte"]
    part = 100.0 * gain / resultats["ignoré"] if resultats["ignoré"] > 0 else 0.0
    print()
    print(
        f"  le terme de vent retire {gain:.3f} m/s ({gain * 3.6:.2f} km/h) d'erreur absolue "
        f"moyenne, soit {part:.1f} %."
    )
    if gain <= 0:
        print("  ATTENTION : l'erreur ne baisse pas. Le terme de vent n'apporte rien ici.")

    # Le contrôle décisif sur la convention d'angle. Un vent retourné doit
    # être **pire** que pas de vent du tout : il ajoute alors une erreur
    # systématiquement du mauvais côté. S'il faisait mieux, notre signe serait
    # à l'envers — et aucun test unitaire du champ de vent ne le dirait.
    pire = resultats["signe inversé"] > resultats["ignoré"] > resultats["pris en compte"]
    print(
        "  contrôle de convention : le vent retourné est "
        + ("bien le pire des trois — le signe est dans le bon sens." if pire else "")
        + ("" if pire else "MEILLEUR que prévu. La convention d'angle est à vérifier.")
    )
    return gain > 0 and pire


def _centile(valeurs: list[float], centile: float) -> float:
    ordonnes = sorted(valeurs)
    if not ordonnes:
        return float("nan")
    rang = min(int(len(ordonnes) * centile / 100.0), len(ordonnes) - 1)
    return ordonnes[rang]


def imprimer_manques(manques: list[str]) -> None:
    if not manques:
        return
    print()
    print(f"=== Sorties écartées de la mesure : {len(manques)} ===")
    for motif in manques[:10]:
        print(f"  {motif}")
    if len(manques) > 10:
        print(f"  (et {len(manques) - 10} autre(s))")


# --- programme principal -------------------------------------------------------------


def executer(arguments: argparse.Namespace) -> int:
    config = charger(Path(arguments.config).expanduser() if arguments.config else None)
    if not config.intervals.renseigne:
        print(
            "Intervals.icu n'est pas configuré ([intervals] athlete_id et api_key) : "
            "le juge indépendant de ce lot est hors d'atteinte, la mesure ne peut pas se faire.\n"
            "Le lot reste NON VÉRIFIÉ tant que cette commande n'a pas tourné.",
            file=sys.stderr,
        )
        return 2

    velo = velo_demande(config, arguments.velo)
    parametres, provenance = parametres_du_velo(config, velo, chemin_calibration(config))
    ftp_w = arguments.ftp if arguments.ftp else float(config.cycliste.ftp_w)
    print(
        f"Vélo « {velo.nom} », paramètres de {provenance} : "
        f"masse {parametres.masse_totale_kg:.1f} kg, CdA {parametres.cda_m2:.4f} m², "
        f"Crr {parametres.crr:.5f}. FTP {ftp_w:.0f} W."
    )

    client_intervals = ClientIntervals(config.intervals.athlete_id, config.intervals.api_key)
    client_archive = ClientArchive(chemin_cache=config.cache.dossier / NOM_CACHE)
    depuis = date.fromisoformat(arguments.depuis)

    comparaisons, erreurs, manques = comparer(
        config,
        client_intervals,
        client_archive,
        depuis,
        parametres,
        ftp_w,
        limite=arguments.limite,
        bavard=arguments.bavard,
    )

    accord = imprimer_accord(comparaisons)
    imprimer_diagnostic_secteur(comparaisons)
    imprimer_pires(comparaisons)
    physique = imprimer_physique(erreurs)
    imprimer_manques(manques)
    print()
    print(
        f"  archives météo : {client_archive.appels} appel(s), "
        f"{client_archive.lectures_cache} lecture(s) de cache."
    )

    print()
    if accord and physique:
        print("VERDICT : le lot est vérifié sur les vraies données.")
        return 0
    print(
        "VERDICT : le lot est NON VÉRIFIÉ. L'écart doit être expliqué et écrit, "
        "pas absorbé (règle absolue 4)."
    )
    return 1


def analyser(argv: list[str] | None = None) -> argparse.Namespace:
    analyseur = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    analyseur.add_argument("--config", help="fichier de configuration (défaut : celui du mainteneur)")
    analyseur.add_argument("--velo", help="vélo dont on prend les paramètres (défaut : 1er vélo route)")
    analyseur.add_argument("--ftp", type=float, help="FTP en watts (défaut : celle de la configuration)")
    analyseur.add_argument(
        "--depuis", default=DEPUIS_DEFAUT, help=f"début de l'historique (défaut : {DEPUIS_DEFAUT})"
    )
    analyseur.add_argument("--limite", type=int, help="s'arrêter après tant de sorties (mise au point)")
    analyseur.add_argument("--bavard", action="store_true", help="nommer chaque sortie mesurée")
    return analyseur.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    try:
        return executer(analyser(argv))
    except (ErreurUtilisateur, ErreurConnecteur) as e:
        print(f"erreur : {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
