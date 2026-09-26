"""Sous-commandes `ourouler calibrer` et `ourouler simuler`.

Ce module est la couche qui **touche les fichiers** : il lit le cache, écrit
`calibration.json` et relit ce dernier pour les autres commandes. Le cœur
(`physique.modele`, `physique.calibration`) ne connaît aucun chemin : il reçoit
des objets déjà construits, comme `boucle.commande` le fait pour les tracés.

`calibrer` enchaîne : choix des sorties → archives météo (mémoïsées) →
échantillons → deux passes d'ajustement → validation sur les sorties les plus
récentes → rapport et JSON. Les appels réseau sont ceux de l'archive, un par
jour de sortie, et une seule fois dans la vie du cache.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path

from ourouler.activites.cache import Cache
from ourouler.boucle.geometrie import geometrie_json
from ourouler.boucle.gpx import lire_gpx_parcours, lire_gpx_trace
from ourouler.boucle.horaire import Pause, analyser_pause, construire_horaire, valider_pauses
from ourouler.boucle.meteo_trace import MeteoTrace, fleches_vent
from ourouler.boucle.meteo_trace import evaluer as evaluer_meteo
from ourouler.config import Config
from ourouler.connecteurs.openmeteo_archive import ClientArchive
from ourouler.meteo import portee
from ourouler.meteo.openmeteo import ClientOpenMeteo
from ourouler.noyau.erreurs import ErreurConnecteur, ErreurUtilisateur
from ourouler.noyau.profil import Velo
from ourouler.physique import calibration as calib
from ourouler.physique import litterature, parametres_velo
from ourouler.physique.modele import (
    FourchettePorteAPorte,
    Parametres,
    PorteAPorte,
    Simulation,
    puissance_a_plat_w,
    simuler,
    temps_ecoule,
    vent_au_cycliste,
)

# Réexports temporaires (lot 7) : l'ancien emplacement de ce qui touche à
# `calibration.json`, retirés avec les autres réexports au lot final.
from ourouler.physique.parametres_velo import (
    ALERTE_PNEU_CHANGE,
    CDA_DEFAUT,
    CRR_DEFAUT,
    Calibration,
    crr_du_velo,
    fourchette_defaut,
)
from ourouler.stockage.calibrations import (
    VERSION_CALIBRATION,
    contenu_calibration,
    ecrire_calibration,
    lire_calibration,
    porte_a_porte_json,
)

#: Distance maximale d'un GPX déposé pour `ourouler analyser` : la même borne
#: que `DemandeBoucle.distance_km` (`api/modeles.py`) — au-delà, ni une
#: Flèche ni un BRM ne va plus loin, et un tracé plus long a de bonnes
#: chances d'être une erreur de dépôt plutôt qu'un vrai parcours.
DISTANCE_MAX_ANALYSE_M = 1_000_000.0

#: Borne haute d'une vitesse à plat saisie à la main, en km/h. Au-delà, ce
#: n'est plus un cycliste lancé sur le plat sans vent, c'est une faute de
#: frappe — et la puissance déduite serait délirante.
VITESSE_A_PLAT_MAXI_KMH = 80.0

#: Mention affichée à côté d'un temps, selon d'où il vient. La seconde vaut
#: pour un modèle qui tourne sur des valeurs de `physique.litterature` : le
#: temps est calculé, mais sur des CdA et Crr jamais mesurés sur ce vélo
#: (règle absolue 5). Mêmes mots que `boucle.commande`.
MENTION_MODELE = "(modèle)"
MENTION_MODELE_LITTERATURE = "(modèle, littérature)"


#: Nom du fichier de mémoïsation des archives météo, dans le dossier de cache (lu par la CLI seule).
NOM_CACHE = "archive_meteo.sqlite"


# --- calibration.json : la commande résout le chemin, le stockage lit ---------

#: Nom du fichier où la calibration est écrite, dans le dossier de cache.
NOM_CALIBRATION = "calibration.json"
#
# Depuis le lot 7, la lecture et l'écriture vivent dans `stockage.calibrations`
# et le calcul (quels paramètres pour quel vélo) dans `physique.parametres_velo`,
# qui reçoit la `Calibration` déjà lue. Les fonctions ci-dessous gardent leurs
# signatures d'avant — une `Config` et un chemin — pour les appelants : elles
# lisent et délèguent.


def chemin_calibration(config: Config) -> Path:
    """Le `calibration.json` de cette configuration.

    Dans le dossier de cache pour la ligne de commande ; à l'endroit que la
    couche web a posé pour un compte hébergé (`ParametresCache.fichier_calibration`,
    L9.4) — c'est ce qui fait que les boucles, les sorties et les simulations
    d'un compte lisent **sa** calibration, et jamais celle d'un autre.
    """
    if config.cache.fichier_calibration is not None:
        return config.cache.fichier_calibration
    return config.cache.dossier / NOM_CALIBRATION


def parametres_du_velo(config: Config, velo: Velo, chemin: Path) -> tuple[Parametres, str]:
    """(paramètres, provenance) du vélo : voir `physique.parametres_velo.parametres_du_velo`."""
    return parametres_velo.parametres_du_velo(
        velo, calib.masse_totale_kg(config, velo), lire_calibration(chemin, velo.nom)
    )


def alerte_calibration(velo: Velo, chemin: Path) -> str | None:
    """L'alerte « pneu changé » : voir `physique.parametres_velo.alerte_calibration`."""
    return parametres_velo.alerte_calibration(velo, lire_calibration(chemin, velo.nom))


def fourchette_du_velo(velo: Velo, chemin: Path) -> FourchettePorteAPorte:
    """La fourchette du porte à porte : voir `physique.parametres_velo.fourchette_du_velo`."""
    return parametres_velo.fourchette_du_velo(lire_calibration(chemin, velo.nom))



def puissance_voulue(args: argparse.Namespace, parametres: Parametres) -> float | None:
    """La puissance demandée : `--puissance`, ou celle que `--vitesse-a-plat` exige.

    `None` si aucune des deux options n'est donnée — c'est à l'appelant de
    décider ce qu'il en fait (`boucle` retombe sur une part de la FTP,
    `simuler` refuse).

    **Les deux options disent la même chose de deux façons et sont exclusives.**
    Le mainteneur, le 18/09/2026 : « et s'il n'a pas de FTP ? » Pour chronométrer
    un parcours, le produit n'a pas besoin d'une FTP mais d'une puissance ; la
    vitesse à plat, sans vent, lancé, en est l'autre chemin — c'est la
    décision 7 du cycle UX, et l'inversion est celle qu'emploie déjà l'écran de
    FTP (`physique.modele.puissance_a_plat_w`), pas une seconde.

    La conversion dépend des `parametres` du vélo : la même vitesse ne demande
    pas la même puissance à un cycliste calibré et à un vélo servi par la
    littérature. C'est pourquoi cette fonction les reçoit au lieu de les lire.
    """
    puissance = getattr(args, "puissance", None)
    vitesse = getattr(args, "vitesse_a_plat", None)
    if puissance is not None and vitesse is not None:
        raise ErreurUtilisateur(
            "--puissance et --vitesse-a-plat disent la même chose de deux façons "
            "(la seconde se convertit en watts par le modèle du vélo) : n'en donner qu'une."
        )
    if vitesse is None:
        return None if puissance is None else float(puissance)
    if not math.isfinite(float(vitesse)) or not (0 < float(vitesse) <= VITESSE_A_PLAT_MAXI_KMH):
        raise ErreurUtilisateur(
            f"--vitesse-a-plat {vitesse} : une vitesse à plat en km/h entre 0 et "
            f"{VITESSE_A_PLAT_MAXI_KMH:g} est attendue (sans vent, lancé — pas une "
            "moyenne de compteur)"
        )
    return puissance_a_plat_w(float(vitesse), parametres)


def velo_demande(config: Config, nom: str | None) -> Velo:
    """Le vélo nommé, ou le premier vélo d'usage route (`parametres_velo.velo_demande`)."""
    return parametres_velo.velo_demande(config, nom)



# --- ourouler calibrer --------------------------------------------------------


def executer_calibrer(
    args: argparse.Namespace,
    config: Config,
    client_archive: ClientArchive | None = None,
    cache: Cache | None = None,
) -> int:
    """Calibre un vélo sur les sorties réelles du cache. Code de sortie 0 si ça a marché.

    **`cache` s'injecte** (L9.4), sur le patron d'`activites/commande.executer` :
    absent — la ligne de commande —, la commande construit celui du
    propriétaire local sur `config.cache.dossier`, comme avant. Le calcul
    lui-même est `calibrer_velo`, qui n'imprime rien : c'est lui que la tâche
    de fond de l'API appelle (`api/calibrations.py`), parce qu'une commande
    qui écrit sur la sortie standard ne peut pas tourner dans un fil pendant
    que d'autres requêtes capturent la leur (`api/adaptateur.py`).
    """
    velo = velo_demande(config, getattr(args, "velo", None))
    cache = cache if cache is not None else Cache(config.cache.dossier)
    client = (
        client_archive
        if client_archive is not None
        else ClientArchive(chemin_cache=config.cache.dossier / NOM_CACHE)
    )
    resultat = calibrer_velo(
        config,
        velo,
        cache,
        client,
        depuis=_date_option(getattr(args, "depuis", None), config.historique_depuis),
        maximum=getattr(args, "max", None),
        crr_libre=bool(getattr(args, "crr_libre", False)),
    )

    chemin = chemin_calibration(config)
    ecrire_calibration(chemin, velo.nom, resultat.contenu())
    for panne in resultat.pannes:
        print(f"ourouler : {panne}", file=sys.stderr)
    arguments = (
        resultat.rapport,
        velo,
        config,
        chemin,
        client,
        resultat.motifs,
        resultat.n_calibrables,
        resultat.crr_source,
    )
    if getattr(args, "json", False):
        print(json.dumps(rendre_json_calibration(*arguments), ensure_ascii=False, indent=2))
    else:
        print(rendre_texte_calibration(*arguments))
    return 0


@dataclass
class ResultatCalibration:
    """Ce que `calibrer_velo` a trouvé — de quoi écrire `calibration.json` et le rapport."""

    velo: Velo
    rapport: calib.RapportCalibration
    #: Sorties de ce vélo écartées, et pourquoi (`sorties_calibrables_et_motifs`).
    motifs: dict[str, int]
    #: Combien de sorties ont passé le choix (avant relecture des fichiers).
    n_calibrables: int
    #: Sorties illisibles et archives météo indisponibles — la calibration a
    #: continué sans elles (ou sans vent), mais il faut le dire.
    pannes: list[str]
    #: D'où vient le Crr : « pneu », « configuration », « usage » ou « ajuste ».
    crr_source: str

    def contenu(self) -> dict:
        """L'entrée de ce vélo dans `calibration.json`."""
        return contenu_calibration(self.rapport, self.crr_source, self.velo.pneu)


#: Signature du rappel d'avancement de `calibrer_velo` : (étape, faits, total).
Progres = Callable[[str, int, int], None]

#: Les étapes que `calibrer_velo` annonce, dans l'ordre.
ETAPE_LECTURE = "lecture"
ETAPE_METEO = "meteo"
ETAPE_AJUSTEMENT = "ajustement"


def calibrer_velo(
    config: Config,
    velo: Velo,
    cache: Cache,
    client_archive: ClientArchive,
    *,
    depuis: date | None = None,
    maximum: int | None = None,
    crr_libre: bool = False,
    crr_usage: bool = False,
    rattachement_strict: bool = False,
    progres: Progres | None = None,
) -> ResultatCalibration:
    """Calibre `velo` sur les sorties de `cache`. N'écrit rien, n'imprime rien.

    `crr_usage` (L9.4) : un vélo sans pneu ni Crr déclarés garde fixé le Crr
    du jeu de son usage (`physique.litterature`) au lieu de l'ajuster avec le
    CdA — c'est ce que l'écran propose à qui ne connaît pas ses pneus,
    l'ajustement libre dérivant sur les vraies données (note du 23/09).

    `rattachement_strict` (L9.4) : quand le profil a plusieurs vélos, seules
    les sorties **explicitement** rattachées à celui-ci (capteur, équipement,
    période) comptent — voir `calibration.motif_exclusion`.

    `progres(étape, faits, total)` est appelé au fil de la relecture des
    fichiers et des archives météo, puis une fois avant l'ajustement.
    """
    if config.cycliste.ftp_w is None:
        raise ErreurUtilisateur(
            "calibration : FTP non renseignée dans la configuration — cette commande a "
            "besoin d'une FTP de référence pour repérer les sorties calibrables"
        )
    depuis = depuis if depuis is not None else config.historique_depuis
    annoncer = progres or (lambda etape, faits, total: None)

    # Un seul lecteur pour tout le calcul : le choix des sorties a besoin du
    # contenu des fichiers (combien de sessions ? quel sport ?) et le
    # chargement en a besoin aussi. Sans mémoïsation, chaque FIT serait analysé
    # deux fois.
    lecteur = _Lecteur(cache)
    candidates, _ = calib.sorties_calibrables_et_motifs(
        cache, config, velo, depuis=depuis, strict=rattachement_strict
    )
    total = len(candidates)
    annoncer(ETAPE_LECTURE, 0, total)

    def relire(identifiant: str):
        deja = identifiant in lecteur._lues
        activite = lecteur(identifiant)
        if not deja:
            annoncer(ETAPE_LECTURE, len(lecteur._lues), total)
        return activite

    entrees, motifs = calib.sorties_calibrables_et_motifs(
        cache, config, velo, depuis=depuis, relire=relire, strict=rattachement_strict
    )
    if maximum:
        entrees = entrees[-int(maximum) :]
    if not entrees:
        raise ErreurUtilisateur(
            f"calibration : aucune sortie calibrable pour {velo.nom} depuis le {depuis} "
            "— vérifier le rattachement au vélo (`ourouler inventaire`)"
        )

    sorties, pannes = _charger_sorties(
        lecteur, entrees, client_archive, lambda faits: annoncer(ETAPE_METEO, faits, len(entrees))
    )
    if not sorties:
        raise ErreurUtilisateur(
            f"calibration : aucune des {len(entrees)} sortie(s) de {velo.nom} n'est relisible"
        )

    annoncer(ETAPE_AJUSTEMENT, 0, 1)
    crr, crr_source = _crr_de_calibration(velo, crr_libre, crr_usage)
    rapport = calib.calibrer_en_deux_passes(
        sorties,
        velo=velo.nom,
        masse_totale_kg=calib.masse_totale_kg(config, velo),
        part_validation=config.calibration.part_validation,
        ftp_w=config.cycliste.ftp_w,
        vitesse_min_kmh=config.calibration.vitesse_min_kmh,
        crr_fixe=crr,
        part_groupe_max=config.calibration.part_groupe_max,
    )
    annoncer(ETAPE_AJUSTEMENT, 1, 1)
    return ResultatCalibration(
        velo=velo,
        rapport=rapport,
        motifs=motifs,
        n_calibrables=len(entrees),
        pannes=pannes,
        crr_source=crr_source,
    )


def _crr_de_calibration(
    velo: Velo, crr_libre: bool, crr_usage: bool = False
) -> tuple[float | None, str]:
    """(Crr fixé ou `None`, provenance) pour `ourouler calibrer`.

    Le Crr connu (pneu ou configuration) est gardé fixe et seul le CdA est
    cherché — la méthode que la note du 23/09 a trouvée convergente.
    `--crr-libre`, ou un vélo sans pneu ni Crr déclarés, garde l'ajustement à
    deux paramètres d'avant : provenance « ajuste ». Sauf `crr_usage` (L9.4,
    l'écran) : le Crr du jeu de l'usage est alors fixé, provenance « usage ».
    """
    connu = None if crr_libre else crr_du_velo(velo)
    if connu is not None:
        return connu
    if crr_usage and not crr_libre:
        return (crr_de_l_usage(velo), "usage")
    return (None, "ajuste")


def crr_de_l_usage(velo: Velo) -> float:
    """Le Crr de la littérature pour l'usage de ce vélo, ou `CRR_DEFAUT`."""
    choix = litterature.pour_usage(velo.usage)
    return choix.jeu.crr if choix is not None else CRR_DEFAUT


class _Lecteur:
    """Relit une sortie du cache **une seule fois**, et retient les pannes.

    `cache.relire` analyse un FIT de bout en bout ; la commande a besoin du
    contenu deux fois (choisir les sorties, puis les échantillonner). Un
    dictionnaire suffit à ne payer qu'une fois — et une lecture impossible est
    mémorisée comme telle, elle aussi, pour ne pas être retentée.
    """

    def __init__(self, cache: Cache):
        self.cache = cache
        self._lues: dict[str, object] = {}
        self.pannes: dict[str, str] = {}

    def __call__(self, identifiant: str):
        if identifiant not in self._lues:
            try:
                self._lues[identifiant] = self.cache.relire(identifiant)
            except (KeyError, ErreurUtilisateur, OSError) as e:
                self._lues[identifiant] = None
                self.pannes[identifiant] = str(e)
        return self._lues[identifiant]


def _charger_sorties(
    lecteur: _Lecteur,
    entrees,
    client: ClientArchive,
    avancer: Callable[[int], None] | None = None,
) -> tuple[list[calib.SortieCalibration], list[str]]:
    """Relit chaque sortie et va chercher l'archive météo de son jour, à son départ.

    Une sortie illisible ou une archive indisponible ne fait pas échouer la
    calibration : elle est signalée et la sortie continue sans vent (ou pas du
    tout, si c'est le fichier qui manque).
    """
    sorties: list[calib.SortieCalibration] = []
    pannes: list[str] = []
    for rang, entree in enumerate(entrees, start=1):
        if avancer is not None:
            avancer(rang)
        activite = lecteur(entree.identifiant)
        if activite is None:
            motif = lecteur.pannes.get(entree.identifiant, "cause inconnue")
            pannes.append(f"sortie {entree.identifiant[:12]} illisible ({motif})")
            continue
        # Le nom de la sortie vit dans l'index du cache, pas dans le fichier
        # brut : sans ce report, le rapport désignait chaque sortie par le
        # chemin de son FIT, ce qui n'apprend rien à personne.
        nom = entree.meta.get("nom")
        if nom:
            activite.meta["nom"] = str(nom)
        vent = _archive_du_depart(activite, client, pannes)
        sorties.append(
            calib.SortieCalibration(activite=activite, vent=vent, identifiant=entree.identifiant)
        )
    return (sorties, pannes)


def _archive_du_depart(activite, client: ClientArchive, pannes: list[str]) -> list:
    """L'archive du jour au **point de départ** de la sortie, arrondi à 0,05°."""
    depart = next(
        (p for p in activite.points if p.lat is not None and p.lon is not None), None
    )
    if depart is None or activite.debut is None:
        return []
    try:
        return client.horaires(float(depart.lat), float(depart.lon), activite.debut.date())
    except (ErreurConnecteur, ErreurUtilisateur) as e:
        motif = f"archive météo du {activite.debut.date()} indisponible ({e})"
        if motif not in pannes:
            pannes.append(motif)
        return []


def rendre_texte_calibration(
    rapport: calib.RapportCalibration,
    velo: Velo,
    config: Config,
    chemin: Path,
    client: ClientArchive,
    motifs: dict[str, int],
    n_calibrables: int,
    crr_source: str = "ajuste",
) -> str:
    a = rapport.ajustement
    v = rapport.validation
    lignes = [
        f"Calibration {velo.nom} — {n_calibrables} sortie(s) calibrable(s) "
        f"depuis le {config.historique_depuis.isoformat()}"
    ]
    if motifs:
        detail = ", ".join(f"{nombre} {motif}" for motif, nombre in sorted(motifs.items()))
        lignes.append(f"Sorties du vélo écartées : {detail}")
    lignes.append(
        f"Archives météo : {client.appels} appel(s), {client.lectures_cache} déjà en cache"
    )
    lignes.append("")
    lignes.append(
        f"Apprentissage : {rapport.n_apprentissage} sortie(s), "
        f"{rapport.echantillons_retenus} échantillon(s) retenu(s) sur {rapport.echantillons}"
    )
    if rapport.motifs:
        detail = ", ".join(f"{motif} {nombre}" for motif, nombre in rapport.motifs.items())
        lignes.append(f"  échantillons écartés : {detail}")
    if rapport.echantillons_sans_vent:
        lignes.append(
            f"  {rapport.echantillons_sans_vent} échantillon(s) retenu(s) sans vent archivé "
            "(comptés à vent nul)"
        )
    # Ce que les données mesurent vraiment vient en premier ; CdA et Crr, qui
    # peuvent se compenser l'un l'autre, sont relégués à une ligne de détail
    # (décision du 13/09 — on ne cherche plus à les séparer).
    lignes.append("  résistance totale sur le plat sans vent, vélo + cycliste :")
    for vitesse, force, puissance in a.resistances:
        lignes.append(
            f"    à {vitesse:g} km/h : {_fr(force, 1)} N  —  {_fr(puissance, 0)} W au pédalier"
        )
    lignes.append(
        f"  résidu de puissance : RMSE {_fr(a.rmse_w, 1)} W, MAE {_fr(a.mae_w, 1)} W"
    )
    if a.crr_fixe:
        # L9.1 : le Crr est reçu (pneu ou configuration), seul le CdA est
        # cherché — il se cite donc, lui, sans la réserve « mal séparé ».
        lignes.append(
            f"  CdA {_fr(a.cda_m2, 3)} m²{_incertitude(a.incertitudes.cda, 3)} (cherché), "
            f"Crr {_fr(a.crr, 4)} fixé ({_crr_texte(crr_source, velo)}), "
            f"masse {_fr(a.masse_totale_kg, 1)} kg, ρ moyen {_fr(a.rho_moyen, 3)}"
        )
    else:
        lignes.append(
            f"  détail (mal séparé, à ne pas citer seul) : CdA {_fr(a.cda_m2, 3)} m²"
            f"{_incertitude(a.incertitudes.cda, 3)}, Crr {_fr(a.crr, 5)}"
            f"{_incertitude(a.incertitudes.crr, 5)}, masse {_fr(a.masse_totale_kg, 1)} kg, "
            f"ρ moyen {_fr(a.rho_moyen, 3)}"
        )
    lignes.append(
        f"  première passe (avec les sorties en groupe) : CdA {_fr(rapport.passe1.cda_m2, 3)}, "
        f"Crr {_fr(rapport.passe1.crr, 5)}"
    )
    if a.crr_fixe:
        lignes.append(
            f"  CdA cherché sur le temps de {rapport.n_solo} sortie(s) d'apprentissage à moins "
            f"de {rapport.part_groupe_max:.0%} de signal de groupe"
        )
    if rapport.repli_solo:
        lignes.append(f"  ⚠ {rapport.repli_solo}")
    for borne in a.bornes_atteintes:
        lignes.append(f"  ⚠ borne atteinte : {borne} — la vraie valeur est probablement au-delà")
    for avertissement in a.avertissements:
        lignes.append(f"  ⚠ {avertissement}")
    if rapport.groupes:
        lignes.append(f"  {len(rapport.groupes)} sortie(s) écartée(s) au résidu (« groupe ») :")
        for nom, part in rapport.groupes:
            lignes.append(f"    {part:.0%} de la distance trop rapide — {nom}")

    lignes.append("")
    lignes.append(f"Validation : {v.n} sortie(s) les plus récentes, jamais vues par l'ajustement")
    if v.n:
        lignes.append(
            f"  erreur de temps en mouvement : MAE {_pourcent(v.mae)}  "
            f"médiane {_pourcent(v.mediane)}  biais {_pourcent(v.biais, signe=True)}"
        )
        lignes.append(f"  {'jour':<12}{'km':>7}{'réel':>9}{'simulé':>9}{'écart':>9}  nom")
        for sortie in sorted(v.sorties, key=lambda s: abs(s.erreur_relative), reverse=True):
            lignes.append(
                f"  {sortie.jour or '?':<12}{sortie.distance_m / 1000:>7.1f}"
                f"{_duree(sortie.temps_reel_s):>9}{_duree(sortie.temps_simule_s):>9}"
                f"{sortie.erreur_relative * 100:>+8.1f}%  {sortie.nom[:40]}"
            )
    if rapport.groupes_en_validation:
        lignes.append(
            f"  dont {len(rapport.groupes_en_validation)} sortie(s) que le même critère "
            "désigne comme « groupe » — elles restent comptées dans l'erreur :"
        )
        for nom, part in rapport.groupes_en_validation:
            lignes.append(f"    {part:.0%} de la distance trop rapide — {nom}")
    lignes.append("")
    lignes.extend(_lignes_porte_a_porte(rapport.porte_a_porte))
    lignes.append("")
    lignes.append(
        "Le temps simulé est un temps **en mouvement** : ni les arrêts, ni les "
        "redémarrages n'y sont modélisés — la fourchette du porte à porte les ajoute."
    )
    lignes.append(f"Écrit dans {chemin}")
    return "\n".join(lignes)


def _crr_texte(crr_source: str, velo: Velo) -> str:
    """« pneu course_quatre_saisons », « configuration »… — d'où vient un Crr fixé."""
    if crr_source == "pneu":
        pneu = litterature.pour_pneu(velo.pneu)
        return f"pneu {pneu.libelle}, littérature" if pneu is not None else "pneu"
    if crr_source == "usage":
        return f"usage {velo.usage}, littérature — aucun pneu déclaré"
    return crr_source


def _lignes_porte_a_porte(mesure: calib.MesurePorteAPorte) -> list[str]:
    """Le paragraphe « porte à porte » du rapport : la fourchette, ou pourquoi il n'y en a pas."""
    seuil = f"{mesure.seuil_groupe:.0%}"
    centiles = mesure.centiles
    if centiles is None:
        return [
            f"Porte à porte : {mesure.n} sortie(s) de validation roulée(s) seul (moins de "
            f"{seuil} de signal de groupe), il en faut {calib.SORTIES_MIN_FOURCHETTE} — la "
            "fourchette par défaut (convention) reste en vigueur."
        ]
    bas, mediane, haut = centiles
    lignes = [
        f"Porte à porte : temps simulé × {_fr(bas, 3)} à × {_fr(haut, 3)} "
        f"(médiane × {_fr(mediane, 3)}), centiles 25-75 du temps écoulé réel sur le "
        f"temps simulé, {mesure.n} sortie(s) de validation sur {len(mesure.sorties)} à "
        f"moins de {seuil} de signal de groupe"
    ]
    mouvement = mesure.centiles_mouvement
    if mouvement is not None:
        lignes.append(
            f"  sur le seul temps en mouvement : × {_fr(mouvement[0], 3)} à × "
            f"{_fr(mouvement[2], 3)} (médiane × {_fr(mouvement[1], 3)}) — l'erreur du modèle, "
            "arrêts exclus"
        )
    return lignes


def rendre_json_calibration(
    rapport: calib.RapportCalibration,
    velo: Velo,
    config: Config,
    chemin: Path,
    client: ClientArchive,
    motifs: dict[str, int],
    n_calibrables: int,
    crr_source: str = "ajuste",
) -> dict:
    a = rapport.ajustement
    v = rapport.validation
    return {
        "velo": velo.nom,
        "depuis": config.historique_depuis.isoformat(),
        "sorties_calibrables": n_calibrables,
        "sorties_ecartees": motifs,
        "archives": {"appels": client.appels, "cache": client.lectures_cache},
        "apprentissage": {
            "n_sorties": rapport.n_apprentissage,
            "echantillons": rapport.echantillons,
            "echantillons_retenus": rapport.echantillons_retenus,
            "echantillons_sans_vent": rapport.echantillons_sans_vent,
            "motifs": rapport.motifs,
            "groupes": [{"nom": nom, "part": round(part, 3)} for nom, part in rapport.groupes],
        },
        "ajustement": {
            "cda_m2": a.cda_m2,
            "crr": a.crr,
            "crr_fixe": a.crr_fixe,
            "n_solo": rapport.n_solo,
            "part_groupe_max": rapport.part_groupe_max,
            "repli_solo": rapport.repli_solo or None,
            "crr_source": crr_source,
            "pneu": velo.pneu if crr_source == "pneu" else None,
            "cda_incertitude": a.incertitudes.cda,
            "crr_incertitude": a.incertitudes.crr,
            "masse_totale_kg": a.masse_totale_kg,
            "rho_moyen": a.rho_moyen,
            "n_echantillons": a.n_echantillons,
            "rmse_w": a.rmse_w,
            "mae_w": a.mae_w,
            "resistance": [
                {
                    "v_kmh": vitesse,
                    "force_n": round(force, 2),
                    "puissance_w": round(puissance, 1),
                }
                for vitesse, force, puissance in a.resistances
            ],
            "bornes_atteintes": list(a.bornes_atteintes),
            "avertissements": list(a.avertissements),
        },
        "passe1": {"cda_m2": rapport.passe1.cda_m2, "crr": rapport.passe1.crr},
        "validation": {
            "n": v.n,
            "mae": v.mae,
            "mediane": v.mediane,
            "biais": v.biais,
            "groupes": [
                {"nom": nom, "part": round(part, 3)} for nom, part in rapport.groupes_en_validation
            ],
            "sorties": [
                {
                    "jour": s.jour or None,
                    "nom": s.nom,
                    "distance_km": round(s.distance_m / 1000, 2),
                    "temps_reel_s": round(s.temps_reel_s),
                    "temps_simule_s": round(s.temps_simule_s),
                    "erreur_relative": round(s.erreur_relative, 4),
                }
                for s in v.sorties
            ],
        },
        "porte_a_porte": porte_a_porte_json(rapport.porte_a_porte),
        "fichier": str(chemin),
    }


# --- ourouler simuler ---------------------------------------------------------


def executer_simuler(
    args: argparse.Namespace, config: Config, client_meteo: ClientOpenMeteo | None = None
) -> int:
    """Simule un GPX à puissance constante, avec le vent prévu si un départ est donné."""
    chemin_gpx = getattr(args, "gpx", None)
    if not chemin_gpx:
        raise ErreurUtilisateur("simuler : --gpx FICHIER.GPX est obligatoire")
    chemin_gpx = Path(chemin_gpx)
    if not chemin_gpx.is_file():
        raise ErreurUtilisateur(f"--gpx {chemin_gpx} : fichier introuvable")

    # Les paramètres du vélo sont résolus **avant** la puissance : une vitesse
    # à plat ne se convertit en watts qu'avec eux (L8.5, lot C).
    velo = velo_demande(config, getattr(args, "velo", None))
    parametres, provenance = parametres_du_velo(config, velo, chemin_calibration(config))
    alerte = alerte_calibration(velo, chemin_calibration(config))
    puissance = puissance_voulue(args, parametres)
    if puissance is None:
        raise ErreurUtilisateur(
            "simuler : donner --puissance W, ou --vitesse-a-plat KMH pour qui ne connaît "
            "pas sa puissance"
        )
    if not (0 < float(puissance) <= 2000):
        vitesse = getattr(args, "vitesse_a_plat", None)
        if vitesse is not None:
            raise ErreurUtilisateur(
                f"--vitesse-a-plat {vitesse} : il faudrait {puissance:.0f} W pour la tenir "
                f"à plat sur le {velo.nom}, au-delà des 2000 W que le modèle accepte"
            )
        raise ErreurUtilisateur(
            f"--puissance {puissance} : une puissance en watts entre 1 et 2000 est attendue"
        )
    trace = lire_gpx_trace(chemin_gpx)

    pauses = tuple(analyser_pause(p) for p in getattr(args, "pause", None) or [])
    valider_pauses(pauses, distance_m=trace.distance_m)

    vent = None
    panne = None
    depart_brut = getattr(args, "depart", None)
    depart_dt: datetime | None = None
    if depart_brut:
        from ourouler.meteo.commande import heure_depart

        depart_dt = heure_depart(depart_brut)
        client = client_meteo if client_meteo is not None else ClientOpenMeteo()
        try:
            vent, resume = vent_prevu(trace, client, config, depart_dt, pauses=pauses)
        except ErreurConnecteur as e:
            panne, resume = str(e), None
    else:
        resume = None
        if pauses:
            # Une pause décale l'heure de passage météo ; sans départ, il n'y
            # a pas d'heure à décaler — le signaler plutôt que de laisser
            # croire que `--pause` a joué un rôle.
            print(
                "ourouler : --pause sans --heure-depart n'a aucun effet "
                "(rien à dater sans heure de départ)",
                file=sys.stderr,
            )

    simulation = simuler(trace, float(puissance), parametres, vent=vent)
    arrivee = (
        depart_dt + timedelta(seconds=simulation.temps_s + _duree_pauses_s(pauses))
        if depart_dt is not None
        else None
    )
    if panne is not None:
        print(f"ourouler : météo indisponible ({panne}) — simulation à vent nul", file=sys.stderr)
    if getattr(args, "json", False):
        print(
            json.dumps(
                rendre_json_simulation(
                    simulation, trace, velo, parametres, provenance, float(puissance), resume,
                    pauses, arrivee, alerte,
                ),
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print(
            rendre_texte_simulation(
                simulation, trace, velo, parametres, provenance, float(puissance), resume,
                pauses, arrivee, alerte,
            )
        )
    return 0


def _duree_pauses_s(pauses: Sequence[Pause]) -> float:
    return sum(p.duree_s for p in pauses)


def vent_prevu(
    trace, client: ClientOpenMeteo, config: Config, depart: datetime, *, pauses: Sequence[Pause] = ()
):
    """(fonction de vent pour `simuler`, résumé lisible) à partir de la prévision.

    Le vent vient de `boucle.meteo_trace`, échantillonné le long du tracé : le
    modèle a besoin de la composante de face en m/s, que la direction
    interpolée et le cap local donnent. `pauses` décale l'heure de passage de
    chaque échantillon situé après elles (`boucle.horaire`), jamais le temps
    en mouvement que `simuler` calcule par ailleurs.
    """
    from ourouler.boucle.meteo_trace import evaluer as evaluer_meteo

    meteo = evaluer_meteo(
        trace,
        client,
        horaire=construire_horaire(depart, config.boucle.vitesse_moyenne_kmh, pauses),
        modele=config.meteo.modele,
        second_avis=None,
    )
    return (vent_depuis_meteo(meteo), meteo)


def vent_depuis_meteo(meteo):
    """`vent(dist_m, cap_deg)` en m/s de face, depuis les échantillons météo d'un tracé.

    L'échantillon le plus proche en distance sert tel quel : les échantillons
    sont espacés de 5 km, le vent d'une prévision horaire ne varie pas plus
    vite que ça.

    La prévision, comme l'archive, donne le vent à 10 m du sol :
    `vent_au_cycliste` le ramène à la hauteur où il est subi. C'est le **seul**
    endroit où la prévision est convertie — `ourouler simuler --heure-depart` et la
    colonne « temps » de `ourouler boucle` passent toutes deux par ici — et
    c'est le pendant exact de ce que fait la calibration sur l'archive. Les
    échantillons météo, eux, gardent la valeur du bulletin : la colonne
    « vent » d'un rapport météo doit rester comparable à ce qu'annonce
    Météo-France.
    """
    connus = [
        (e.dist_m, e.vent_kmh, e.vent_depuis_deg)
        for e in meteo.echantillons
        if e.vent_kmh is not None and e.vent_depuis_deg is not None
    ]
    if not connus:
        return None

    def face(dist_m: float, cap: float) -> float:
        _, vitesse, depuis = min(connus, key=lambda c: abs(c[0] - dist_m))
        return vent_au_cycliste((vitesse / 3.6) * math.cos(math.radians(depuis - cap)))

    return face


# --- ourouler analyser --------------------------------------------------------


def executer_analyser(
    args: argparse.Namespace, config: Config, client_meteo: ClientOpenMeteo | None = None
) -> int:
    """Analyse un parcours **déjà en main** (BRM, Flèche, boucle de club) : durée porte à
    porte en fourchette, météo par tronçon à l'heure où on y passe, heure d'arrivée.

    C'est `ourouler simuler` retourné dans l'autre sens : `simuler` chronomètre un GPX à
    puissance constante et prend la météo en option ; `analyser` part d'un parcours qu'on
    n'a pas choisi (l'imposé d'un brevet, la boucle du club) et veut savoir **quand** on
    y passera et ce qu'on y trouvera — `--heure-depart` y est donc obligatoire, là où
    `simuler` s'en passe.

    **La puissance, par défaut, est celle de l'endurance du profil** :
    `config.seance.puissance_endurance_pct × config.cycliste.ftp_w` — le même calcul que
    l'écran de FTP (`seance.ecran_ftp.apercu_zones`). `--puissance`/`--vitesse-a-plat`
    la remplacent pour qui veut un autre rythme (Q7, même inversion que `simuler`).

    **La vitesse qui date les échantillons météo est celle du modèle, pas la moyenne
    configurée** : `physique.modele.simuler` à vent nul donne une vitesse moyenne qui
    tient compte du relief de *ce* parcours-ci — exactement `boucle.commande._vitesse_meteo`,
    rejoué ici pour un GPX déposé plutôt que pour une candidate générée. Sur un parcours
    vallonné, c'est très différent d'une vitesse moyenne plate, et c'est tout l'intérêt :
    la météo d'un col à 12 km/h n'est pas celle d'une plaine à 30.

    **Les heures de passage sont celles du porte à porte** (L9.8, relecture) : le
    temps en mouvement à vent nul, multiplié par la médiane de la fourchette L9.1
    du vélo (mesurée ou convention). Sur un 600 km, caler la météo sur le seul
    temps en mouvement la décalait de plusieurs heures — les arrêts arrivent
    bien, eux aussi.

    **Horizon météo** : au-delà de `config.meteo.horizon_jours`, aucun appel n'est fait —
    la durée est rendue sans météo, et le dit (même mécanisme que `ourouler boucle`,
    `meteo.portee`). Un 600 km dépasse presque toujours la portée horaire utile du modèle
    régional (AROME) avant son arrivée : `boucle.meteo_trace.evaluer` bascule alors sur
    `second_avis` pour la fin du parcours, et chaque échantillon dit lequel a répondu
    (`Echantillon.modele`) — jamais mélangé en silence (règle absolue 5). Un
    parcours parti le dernier jour couvert qui arrive le lendemain : les
    échantillons d'après la fin de ce jour sont vides et marqués
    `au_dela_prevision`, jamais présentés comme une prévision.

    **Plusieurs traces** : lues toutes, enchaînées (`boucle.gpx.lire_gpx_parcours`),
    et chaque trou franchi en ligne droite est dit.
    """
    chemin_gpx = getattr(args, "gpx", None)
    if not chemin_gpx:
        raise ErreurUtilisateur("analyser : --gpx FICHIER.GPX est obligatoire")
    chemin_gpx = Path(chemin_gpx)
    if not chemin_gpx.is_file():
        raise ErreurUtilisateur(f"--gpx {chemin_gpx} : fichier introuvable")

    depart_brut = getattr(args, "depart", None)
    if not depart_brut:
        raise ErreurUtilisateur(
            "analyser : --heure-depart est obligatoire (sans elle, rien à caler dans le "
            "temps — ni la météo, ni l'heure d'arrivée)"
        )
    from ourouler.meteo.commande import heure_depart

    depart_dt = heure_depart(depart_brut)

    trace, avertissements_trace = lire_gpx_parcours(chemin_gpx)
    for avertissement in avertissements_trace:
        print(f"ourouler : {avertissement}", file=sys.stderr)
    if trace.distance_m > DISTANCE_MAX_ANALYSE_M:
        raise ErreurUtilisateur(
            f"analyser : {trace.distance_m / 1000:.0f} km, au-delà des "
            f"{DISTANCE_MAX_ANALYSE_M / 1000:.0f} km qu'un parcours à analyser accepte"
        )

    velo = velo_demande(config, getattr(args, "velo", None))
    parametres, provenance = parametres_du_velo(config, velo, chemin_calibration(config))
    alerte = alerte_calibration(velo, chemin_calibration(config))

    puissance = puissance_voulue(args, parametres)
    if puissance is None:
        if config.cycliste.ftp_w is None:
            raise ErreurUtilisateur(
                "analyser : donner --puissance W ou --vitesse-a-plat KMH — aucune FTP dans "
                "le profil pour calculer par défaut la puissance d'endurance"
            )
        puissance = config.seance.puissance_endurance_pct * config.cycliste.ftp_w
    if not (0 < float(puissance) <= 2000):
        raise ErreurUtilisateur(
            f"--puissance {puissance} : une puissance en watts entre 1 et 2000 est attendue"
        )
    puissance = float(puissance)

    client = client_meteo if client_meteo is not None else ClientOpenMeteo()
    fourchette = fourchette_du_velo(velo, chemin_calibration(config))

    dernier_jour = portee.dernier_jour_couvert(config.meteo.horizon_jours, aujourdhui=date.today())
    jour_demande = depart_dt.date()
    meteo_absente = (
        portee.constater(jour_demande, dernier_jour) if jour_demande > dernier_jour else None
    )

    meteo: MeteoTrace | None = None
    panne: str | None = None
    vitesse_a_vent_nul = _vitesse_a_vent_nul(trace, puissance, parametres, config)
    if meteo_absente is None:
        # Porte à porte, pas en mouvement : la vitesse « de montre », arrêts
        # compris, à la médiane de la fourchette du vélo.
        vitesse_montre = vitesse_a_vent_nul / fourchette.mediane
        fuseau = depart_dt.tzinfo or UTC
        fin_de_prevision = datetime.combine(
            dernier_jour + timedelta(days=1), time(0), tzinfo=fuseau
        )
        try:
            meteo = evaluer_meteo(
                trace,
                client,
                horaire=construire_horaire(depart_dt, vitesse_montre),
                limite=fin_de_prevision,
                modele=config.meteo.modele,
                second_avis=config.meteo.second_avis,
                # Même repli que `boucle`/`sortie` (Q19) : un parcours plus
                # long que la portée horaire du modèle régional ne perd pas
                # toute sa météo, seulement la partie que le repli ne couvre
                # pas non plus.
                modele_repli=config.meteo.second_avis,
            )
        except ErreurConnecteur as e:
            panne = str(e)

    vent = vent_depuis_meteo(meteo) if meteo is not None else None
    simulation = simuler(trace, puissance, parametres, vent=vent)

    ecoule = temps_ecoule(simulation.temps_s, fourchette)
    arrivee_bas = depart_dt + timedelta(seconds=ecoule.bas_s)
    arrivee_mediane = depart_dt + timedelta(seconds=ecoule.mediane_s)
    arrivee_haut = depart_dt + timedelta(seconds=ecoule.haut_s)

    if panne is not None:
        print(f"ourouler : météo indisponible ({panne}) — durée rendue sans météo", file=sys.stderr)
    elif meteo_absente is not None:
        print(f"ourouler : {meteo_absente.message} — durée rendue sans météo", file=sys.stderr)

    if getattr(args, "json", False):
        print(
            json.dumps(
                rendre_json_analyse(
                    simulation, trace, velo, parametres, provenance, puissance, meteo,
                    ecoule, depart_dt, arrivee_bas, arrivee_mediane, arrivee_haut, alerte,
                    meteo_absente, fourchette, panne, avertissements_trace,
                    vitesse_a_vent_nul,
                ),
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print(
            rendre_texte_analyse(
                simulation, trace, velo, parametres, provenance, puissance, meteo,
                ecoule, depart_dt, arrivee_mediane, alerte, meteo_absente, panne,
            )
        )
    return 0


def _vitesse_a_vent_nul(
    trace, puissance_w: float, parametres: Parametres, config: Config
) -> float:
    """La vitesse qui date les échantillons météo — le pendant, pour un GPX déposé, de
    `boucle.commande._vitesse_meteo` : une simulation à vent nul (la météo qu'on cherche
    dépendrait sinon de l'heure, qui dépend de la vitesse, qui dépend du vent — second
    ordre, voir la docstring de `_vitesse_meteo`). Retombe sur la vitesse moyenne
    configurée si la simulation échoue (tracé dégénéré) : la météo reste utilisable.
    """
    try:
        vitesse = simuler(trace, puissance_w, parametres).vitesse_moy_kmh
    except ErreurUtilisateur:
        return config.boucle.vitesse_moyenne_kmh
    if not math.isfinite(vitesse) or vitesse <= 0:
        return config.boucle.vitesse_moyenne_kmh
    return vitesse


def rendre_texte_analyse(
    simulation: Simulation,
    trace,
    velo: Velo,
    parametres: Parametres,
    provenance: str,
    puissance_w: float,
    meteo: MeteoTrace | None,
    ecoule: PorteAPorte,
    depart: datetime,
    arrivee_mediane: datetime,
    alerte: str | None,
    meteo_absente,
    panne: str | None,
) -> str:
    lignes = [
        f"Analyse de « {trace.nom} » — {_fr(trace.distance_m / 1000, 1)} km"
        + (f", D+ {trace.denivele_m:.0f} m" if trace.denivele_m is not None else ""),
        f"Vélo {velo.nom} — CdA {_fr(parametres.cda_m2, 3)} m², Crr {_fr(parametres.crr, 5)}, "
        f"{_fr(parametres.masse_totale_kg, 1)} kg ({provenance}), ρ {_fr(parametres.rho, 3)}",
        f"Puissance tenue : {puissance_w:.0f} W",
        "",
    ]
    mention = MENTION_MODELE_LITTERATURE if provenance == "littérature" else MENTION_MODELE
    lignes.append(
        f"Temps en mouvement : {_duree(simulation.temps_s)} "
        f"({_fr(simulation.vitesse_moy_kmh, 1)} km/h de moyenne) {mention}"
    )
    source = (
        "mesurée sur vos sorties" if ecoule.provenance == "mesure" else "convention par défaut"
    )
    lignes.append(
        f"Porte à porte : {_duree(ecoule.bas_s)} à {_duree(ecoule.haut_s)} "
        f"({source}) — arrivée vers {arrivee_mediane.strftime('%d/%m %H:%M')}"
    )
    if panne is not None:
        lignes.append(f"Météo indisponible ({panne}) : durée rendue sans météo.")
    elif meteo_absente is not None:
        lignes.append(f"{meteo_absente.message} : durée rendue sans météo.")
    elif meteo is not None:
        lignes.append(
            f"Vent : face sur {meteo.part_vent_face:.0%} des échantillons "
            f"({meteo.n_vent_connu}/{len(meteo.echantillons)} connus), "
            f"pluie cumulée {_fr(meteo.pluie_cumulee_mm, 1)} mm"
            + (" (sur la partie prévue)" if _debut_au_dela(meteo) is not None else "")
        )
        if meteo.repli and meteo.bascule_dist_m is not None:
            lignes.append(
                f"  au-delà du km {meteo.bascule_dist_m / 1000:.0f}, la prévision vient du "
                "second modèle (portée horaire du principal dépassée)"
            )
        debut_au_dela = _debut_au_dela(meteo)
        if debut_au_dela is not None:
            lignes.append(
                f"  à partir du km {debut_au_dela / 1000:.0f} : au-delà de la prévision, "
                "pas de météo"
            )
        lignes.append(
            "  (heures de passage estimées porte à porte, arrêts compris)"
        )
    if alerte:
        lignes.append(alerte)
    return "\n".join(lignes)


def rendre_json_analyse(
    simulation: Simulation,
    trace,
    velo: Velo,
    parametres: Parametres,
    provenance: str,
    puissance_w: float,
    meteo: MeteoTrace | None,
    ecoule: PorteAPorte,
    depart: datetime,
    arrivee_bas: datetime,
    arrivee_mediane: datetime,
    arrivee_haut: datetime,
    alerte: str | None,
    meteo_absente,
    fourchette: FourchettePorteAPorte,
    panne: str | None,
    avertissements_trace: list[str],
    vitesse_a_vent_nul_kmh: float,
) -> dict:
    return {
        "nom": trace.nom,
        "distance_km": round(trace.distance_m / 1000.0, 3),
        "denivele_m": trace.denivele_m,
        "velo": velo.nom,
        "parametres": {
            "cda_m2": parametres.cda_m2,
            "crr": parametres.crr,
            "masse_totale_kg": parametres.masse_totale_kg,
            "rendement": parametres.rendement,
            "rho": parametres.rho,
            "provenance": provenance,
            "alerte": alerte,
            "litterature": litterature_json(provenance, velo.usage),
        },
        "puissance_w": puissance_w,
        "depart": depart.isoformat(),
        "temps_estime_s": round(simulation.temps_s),
        "vitesse_moy_kmh": round(simulation.vitesse_moy_kmh, 2),
        "pas_plafonnes": simulation.pas_plafonnes,
        "pas_bloques": simulation.pas_bloques,
        # Le porte à porte en fourchette (L9.1) — jamais un seul chiffre, la
        # provenance dit si elle vient des sorties de ce vélo ou d'une
        # convention (règle absolue 5). Même trio de champs que les
        # candidates de `boucle` (`temps_ecoule_s`/`_bas_s`/`_haut_s`).
        "temps_ecoule_s": round(ecoule.mediane_s),
        "temps_ecoule_bas_s": round(ecoule.bas_s),
        "temps_ecoule_haut_s": round(ecoule.haut_s),
        "temps_ecoule_source": ecoule.provenance,
        "heure_arrivee": arrivee_mediane.isoformat(),
        "heure_arrivee_bas": arrivee_bas.isoformat(),
        "heure_arrivee_haut": arrivee_haut.isoformat(),
        # La fourchette elle-même, pour le dépliant « d'où viennent ces
        # chiffres » : sa médiane date aussi les échantillons météo.
        "porte_a_porte": {
            "bas": fourchette.bas,
            "mediane": fourchette.mediane,
            "haut": fourchette.haut,
            "provenance": fourchette.provenance,
            "n": fourchette.n,
        },
        # La vitesse qui a daté les échantillons météo, divisée par la
        # médiane ci-dessus : à vent nul (le vent attendu dépend de l'heure,
        # qui dépend du vent — second ordre, voir `_vitesse_a_vent_nul`).
        "vitesse_a_vent_nul_kmh": round(vitesse_a_vent_nul_kmh, 3),
        "meteo_absente": None if meteo_absente is None else meteo_absente.json(),
        # La panne Open-Meteo, dite à part : l'API rembourse la consultation
        # quand aucune météo n'a été rendue.
        "meteo_panne": panne,
        "avertissements_trace": avertissements_trace,
        "meteo": _meteo_json_analyse(meteo),
        # Même forme que `boucle._candidate_json["trace"]` (F0.1) : `points`
        # pour la carte, `profil` pour la courbe d'altitude — le front
        # réutilise `Carte`/`ProfilAltitude` sans rien réécrire.
        "trace": geometrie_json(trace),
    }


def _meteo_json_analyse(meteo: MeteoTrace | None) -> dict | None:
    """Même forme que `boucle.commande._meteo_json` (candidate d'une boucle) : un front qui
    sait déjà lire `candidate.meteo` (flèches de vent, échantillons) lit celui-ci sans
    code neuf. Dupliquée plutôt qu'importée depuis `boucle.commande` : c'est de la mise en
    forme de données déjà calculées par `MeteoTrace`/`fleches_vent`, pas une deuxième
    implémentation du calcul météo — la même règle que `boucle.commande._meteo_json`
    documente pour elle-même.
    """
    if meteo is None:
        return None
    return {
        "pluie_cumulee_mm": round(meteo.pluie_cumulee_mm, 3),
        "minutes_pluie": round(meteo.minutes_pluie, 1),
        "part_vent_face": round(meteo.part_vent_face, 3),
        "part_vent_dos": round(meteo.part_vent_dos, 3),
        "n_vent_connu": meteo.n_vent_connu,
        "n_echantillons": len(meteo.echantillons),
        "ressenti_min_c": meteo.ressenti_min_c,
        "confiance": meteo.confiance,
        "modele_utilise": meteo.modele_utilise,
        "repli": meteo.repli,
        "bascule_dist_m": (
            None if meteo.bascule_dist_m is None else round(meteo.bascule_dist_m, 1)
        ),
        # Le premier kilomètre (en mètres) passé **au-delà de la prévision** —
        # `None` si tout le parcours est couvert.
        "au_dela_prevision_dist_m": _debut_au_dela(meteo),
        "fleches_vent": fleches_vent(meteo),
        "echantillons": [
            {
                "dist_m": round(e.dist_m, 1),
                "t": e.t.isoformat(),
                "cap_deg": round(e.cap_deg, 1),
                "pluie_mm": e.pluie_mm,
                "vent_kmh": e.vent_kmh,
                "vent_relatif": e.vent_relatif,
                "ressenti_c": e.ressenti_c,
                "modele": e.modele,
                "au_dela_prevision": e.au_dela_prevision,
            }
            for e in meteo.echantillons
        ],
    }


def _debut_au_dela(meteo: MeteoTrace) -> float | None:
    """La distance du premier échantillon au-delà de la prévision, ou `None`."""
    for e in meteo.echantillons:
        if e.au_dela_prevision:
            return round(e.dist_m, 1)
    return None


def rendre_texte_simulation(
    simulation: Simulation,
    trace,
    velo: Velo,
    parametres: Parametres,
    provenance: str,
    puissance_w: float,
    meteo,
    pauses: Sequence[Pause] = (),
    arrivee: datetime | None = None,
    alerte: str | None = None,
) -> str:
    lignes = [
        f"Simulation de « {trace.nom} » — {_fr(simulation.distance_m / 1000, 1)} km"
        + (f", D+ {trace.denivele_m:.0f} m" if trace.denivele_m is not None else ""),
        f"Vélo {velo.nom} — CdA {_fr(parametres.cda_m2, 3)} m², Crr {_fr(parametres.crr, 5)}, "
        f"{_fr(parametres.masse_totale_kg, 1)} kg ({provenance}), ρ {_fr(parametres.rho, 3)}",
        f"Puissance tenue : {puissance_w:.0f} W",
    ]
    if meteo is not None:
        lignes.append(
            f"Vent prévu : face sur {meteo.part_vent_face:.0%} des échantillons "
            f"({meteo.n_vent_connu}/{len(meteo.echantillons)} connus)"
        )
    lignes.append("")
    mention = MENTION_MODELE_LITTERATURE if provenance == "littérature" else MENTION_MODELE
    lignes.append(
        f"Temps en mouvement : {_duree(simulation.temps_s)} "
        f"({_fr(simulation.vitesse_moy_kmh, 1)} km/h de moyenne) {mention}"
    )
    if simulation.pas_plafonnes:
        lignes.append(
            f"  {simulation.pas_plafonnes} pas de 100 m plafonnés à 60 km/h en descente"
        )
    if simulation.pas_bloques:
        lignes.append(
            f"  {simulation.pas_bloques} pas où la vitesse calculée est sous 0,5 m/s "
            "(temps plancher, pas une mesure)"
        )
    lignes.append(
        "Les arrêts ne sont pas modélisés : feux, stops et ravitaillements s'ajoutent à ce temps."
    )
    if pauses:
        total = _duree_pauses_s(pauses)
        lignes.append(
            f"Pauses déclarées : {len(pauses)}, {_duree(total)} au total — s'ajoutent "
            "par-dessus le temps en mouvement, pas confondues avec les arrêts ci-dessus."
        )
        if arrivee is not None:
            from ourouler.meteo.rapport import date_en_francais

            lignes.append(f"Arrivée estimée : {date_en_francais(arrivee)}.")
    if alerte:
        lignes.append(f"⚠ Calibration du {velo.nom} : {alerte} (`ourouler calibrer --velo {velo.nom}`).")
    if provenance != "calibration":
        lignes.append(
            f"CdA et Crr viennent de la {provenance} et n'ont pas été mesurés : "
            f"lancer `ourouler calibrer --velo {velo.nom}`."
        )
        lignes.extend(lignes_litterature(provenance, velo.usage))
    return "\n".join(lignes)


def lignes_litterature(provenance: str, usage: str) -> list[str]:
    """Ce que vaut le jeu générique servi, en clair. Vide si rien de générique.

    Règle absolue 5 : un temps calculé sur des valeurs jamais mesurées le dit,
    et dit **de combien il dérive** là où la dérive a pu être mesurée. Le
    chiffre vient de `physique.litterature`, qui le tient de la campagne du
    17/09/2026 sur les 34 sorties de validation du mainteneur — un cycliste,
    deux vélos.
    """
    if provenance != "littérature":
        return []
    choix = litterature.pour_usage(usage)
    if choix is None:  # pragma: no cover - la provenance vient justement de la table
        return []
    return [f"Catégorie {choix.resume}"]


def litterature_json(provenance: str, usage: str) -> dict | None:
    """Le bloc « littérature » du JSON, ou `None` si le modèle n'en vient pas.

    Même contenu que `lignes_litterature`, pour un appelant qui met en forme
    lui-même : le front doit pouvoir écrire sa propre phrase sans réapprendre
    d'où sortent les chiffres.
    """
    if provenance != "littérature":
        return None
    choix = litterature.pour_usage(usage)
    if choix is None:  # pragma: no cover - la provenance vient justement de la table
        return None
    return {
        "usage": choix.usage,
        "jeu": choix.jeu.nom,
        "source": choix.jeu.source,
        "mesure_sur": choix.mesure_sur,
        "derive_min_2h": choix.derive_min_2h,
        "f27_jeu_n": choix.f27_jeu_n,
        "f27_reference_n": choix.f27_reference_n,
        "mesuree": False,
    }


def rendre_json_simulation(
    simulation: Simulation,
    trace,
    velo: Velo,
    parametres: Parametres,
    provenance: str,
    puissance_w: float,
    meteo,
    pauses: Sequence[Pause] = (),
    arrivee: datetime | None = None,
    alerte: str | None = None,
) -> dict:
    return {
        "trace": trace.nom,
        "distance_m": round(simulation.distance_m, 1),
        "denivele_m": trace.denivele_m,
        "velo": velo.nom,
        "parametres": {
            "cda_m2": parametres.cda_m2,
            "crr": parametres.crr,
            "masse_totale_kg": parametres.masse_totale_kg,
            "rendement": parametres.rendement,
            "rho": parametres.rho,
            "provenance": provenance,
            "alerte": alerte,
            "litterature": litterature_json(provenance, velo.usage),
        },
        "puissance_w": puissance_w,
        "temps_mouvement_s": round(simulation.temps_s),
        "vitesse_moy_kmh": round(simulation.vitesse_moy_kmh, 2),
        "pas_plafonnes": simulation.pas_plafonnes,
        "pas_bloques": simulation.pas_bloques,
        "vent": None
        if meteo is None
        else {
            "part_vent_face": round(meteo.part_vent_face, 3),
            "n_vent_connu": meteo.n_vent_connu,
            "n_echantillons": len(meteo.echantillons),
        },
        "arrets_modelises": False,
        # Les pauses telles que déclarées (`--pause`), et l'heure d'arrivée
        # qui en tient compte — `null` sans `--heure-depart` (rien à dater).
        "pauses": [
            {"km": round(p.dist_m / 1000.0, 3), "duree_s": round(p.duree_s)} for p in pauses
        ],
        "heure_arrivee": arrivee.isoformat() if arrivee is not None else None,
    }


# --- petits rendus ------------------------------------------------------------


def _date_option(texte: str | None, defaut: date) -> date:
    if not texte:
        return defaut
    try:
        return date.fromisoformat(str(texte).strip())
    except ValueError as e:
        raise ErreurUtilisateur(f"--depuis {texte!r} : date AAAA-MM-JJ attendue") from e


def _fr(valeur: float, decimales: int) -> str:
    """Un nombre à la française : virgule décimale."""
    return f"{valeur:.{decimales}f}".replace(".", ",")


def _incertitude(valeur: float | None, decimales: int) -> str:
    return "" if valeur is None else f" ± {_fr(valeur, decimales)}"


def _pourcent(valeur: float | None, *, signe: bool = False) -> str:
    if valeur is None:
        return "—"
    texte = f"{valeur * 100:{'+' if signe else ''}.1f}"
    return texte.replace(".", ",") + " %"


def _duree(secondes: float) -> str:
    """« 2:14 » — heures et minutes."""
    minutes = round(secondes / 60)
    return f"{minutes // 60}:{minutes % 60:02d}"


__all__ = [
    "DISTANCE_MAX_ANALYSE_M",
    "NOM_CALIBRATION",
    "VERSION_CALIBRATION",
    "CDA_DEFAUT",
    "CRR_DEFAUT",
    "ALERTE_PNEU_CHANGE",
    "Calibration",
    "alerte_calibration",
    "chemin_calibration",
    "crr_du_velo",
    "ecrire_calibration",
    "executer_analyser",
    "executer_calibrer",
    "executer_simuler",
    "fourchette_defaut",
    "fourchette_du_velo",
    "lignes_litterature",
    "lire_calibration",
    "litterature_json",
    "parametres_du_velo",
    "puissance_voulue",
    "rendre_json_analyse",
    "velo_demande",
    "vent_depuis_meteo",
]
