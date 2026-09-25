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
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

from ourouler.activites.cache import Cache
from ourouler.boucle.gpx import lire_gpx_trace
from ourouler.boucle.horaire import Pause, analyser_pause, construire_horaire, valider_pauses
from ourouler.config import Config, Velo
from ourouler.connecteurs.openmeteo_archive import ClientArchive
from ourouler.erreurs import ErreurConnecteur, ErreurUtilisateur
from ourouler.meteo.openmeteo import ClientOpenMeteo
from ourouler.physique import calibration as calib
from ourouler.physique import litterature
from ourouler.physique.modele import (
    FourchettePorteAPorte,
    Parametres,
    Simulation,
    puissance_a_plat_w,
    simuler,
    vent_au_cycliste,
)

#: Nom du fichier où la calibration est écrite, dans le dossier de cache.
NOM_CALIBRATION = "calibration.json"

#: Version du format de `calibration.json`. Un fichier plus récent est ignoré
#: plutôt que relu de travers.
VERSION_CALIBRATION = 1

#: CdA et Crr de dernier recours, pour un vélo dont l'usage n'est **pas** dans
#: la table de `physique.litterature` (aucun aujourd'hui, `config.USAGES_VELO`
#: ne portant que « route » et « clm » — mais le jour où un gravel s'y
#: ajoutera, mieux vaut un défaut muet qu'un jeu emprunté à une autre
#: catégorie). Ils ne sont **pas** une mesure : toute commande qui s'en sert le
#: dit, et `boucle` refuse d'en faire un temps « modèle ».
CDA_DEFAUT = 0.32
CRR_DEFAUT = 0.005

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


# --- lecture et écriture de calibration.json ---------------------------------


@dataclass(frozen=True)
class Calibration:
    """Ce que `calibration.json` garde d'un vélo."""

    velo: str
    parametres: Parametres
    date: str = ""
    n_sorties: int = 0
    mae: float | None = None
    #: La fourchette du porte à porte mesurée sur ce vélo (L9.1), ou `None`
    #: pour une calibration d'avant le 25/09/2026 ou faite sur trop peu de
    #: sorties roulées seul : l'appelant retombe alors sur la convention.
    porte_a_porte: FourchettePorteAPorte | None = None
    #: D'où vient le Crr : « pneu », « configuration » ou « ajuste » (cherché
    #: avec le CdA, l'ancienne méthode). Vide pour une calibration ancienne.
    crr_source: str = ""

    @property
    def resume(self) -> str:
        mae = f", MAE {self.mae * 100:.1f} %" if self.mae is not None else ""
        return (
            f"CdA {self.parametres.cda_m2:.3f} m², Crr {self.parametres.crr:.5f}, "
            f"{self.parametres.masse_totale_kg:.1f} kg (calibré le {self.date or '?'} "
            f"sur {self.n_sorties} sortie(s){mae})"
        )


def chemin_calibration(config: Config) -> Path:
    return config.cache.dossier / NOM_CALIBRATION


def lire_calibration(chemin: Path, velo: str) -> Calibration | None:
    """La calibration d'un vélo, ou `None` si le fichier manque, est illisible ou muet.

    Jamais d'exception : une calibration absente n'empêche pas de rouler, elle
    change seulement la mention affichée à côté du temps estimé.
    """
    try:
        charge = json.loads(chemin.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(charge, dict) or charge.get("version") != VERSION_CALIBRATION:
        return None
    velos = charge.get("velos")
    if not isinstance(velos, dict):
        return None
    brut = velos.get(velo) or _sans_casse(velos, velo)
    if not isinstance(brut, dict):
        return None
    try:
        parametres = Parametres(
            masse_totale_kg=float(brut["masse_totale_kg"]),
            cda_m2=float(brut["cda_m2"]),
            crr=float(brut["crr"]),
            rendement=float(brut.get("rendement", Parametres.rendement)),
            rho=float(brut.get("rho", Parametres.rho)),
        )
    except (KeyError, TypeError, ValueError):
        return None
    mae = brut.get("mae")
    return Calibration(
        velo=velo,
        parametres=parametres,
        date=str(brut.get("date") or ""),
        n_sorties=int(brut.get("n_sorties") or 0),
        mae=float(mae) if isinstance(mae, (int, float)) else None,
        porte_a_porte=_lire_porte_a_porte(brut.get("porte_a_porte")),
        crr_source=str(brut.get("crr_source") or ""),
    )


def _lire_porte_a_porte(brut: object) -> FourchettePorteAPorte | None:
    """La fourchette écrite par `ourouler calibrer`, ou `None` si absente ou illisible.

    Jamais d'exception, comme `lire_calibration` : une fourchette abîmée
    retombe sur la convention, elle n'empêche pas de rouler.
    """
    if not isinstance(brut, dict):
        return None
    try:
        return FourchettePorteAPorte(
            bas=float(brut["bas"]),
            mediane=float(brut["mediane"]),
            haut=float(brut["haut"]),
            provenance="mesure",
            n=int(brut.get("n") or 0),
        )
    except (KeyError, TypeError, ValueError, ErreurUtilisateur):
        return None


def _sans_casse(velos: dict, nom: str) -> dict | None:
    for cle, valeur in velos.items():
        if str(cle).casefold() == nom.casefold():
            return valeur
    return None


def ecrire_calibration(chemin: Path, velo: str, contenu: dict) -> None:
    """Écrit (ou remplace) l'entrée d'un vélo **sans toucher aux autres.

    Calibrer le BMC ne doit pas effacer le RCR : le fichier est relu, l'entrée
    du vélo remplacée, et le tout réécrit.
    """
    charge: dict = {"version": VERSION_CALIBRATION, "velos": {}}
    try:
        ancien = json.loads(chemin.read_text(encoding="utf-8"))
        if isinstance(ancien, dict) and isinstance(ancien.get("velos"), dict):
            charge["velos"] = dict(ancien["velos"])
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        pass
    charge["velos"][velo] = contenu
    try:
        chemin.parent.mkdir(parents=True, exist_ok=True)
        chemin.write_text(
            json.dumps(charge, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    except OSError as e:
        raise ErreurUtilisateur(f"calibration : écriture impossible dans {chemin} ({e})") from e


def parametres_du_velo(config: Config, velo: Velo, chemin: Path) -> tuple[Parametres, str]:
    """(paramètres, provenance) : la calibration, sinon la configuration, sinon la littérature.

    Provenance vaut « calibration », « configuration », « littérature » ou
    « défaut ». Elle est affichée telle quelle : un CdA de littérature n'est
    pas une mesure, et la commande ne doit jamais laisser croire le contraire
    (règle absolue 5).

    **L'ordre ne change pas** : une calibration mesurée prime toujours sur ce
    que la table générique propose. La littérature ne sert qu'à celui qui n'a
    encore rien mesuré — et c'est tout l'objet de l'arbitrage du 17/09/2026,
    « la littérature plutôt que la précision ».

    Comme avant, une valeur donnée en configuration est **gardée** même quand
    l'autre manque : la provenance nomme alors d'où vient la moitié complétée.
    Un tel couple mi-configuré, mi-générique n'est pas un des couples dont
    `physique.litterature` a mesuré la dérive — ce qui s'y mesure est une
    somme, pas un CdA isolé.
    """
    calibree = lire_calibration(chemin, velo.nom)
    if calibree is not None:
        return (calibree.parametres, "calibration")
    masse = calib.masse_totale_kg(config, velo)
    if velo.cda_m2 is not None and velo.crr is not None:
        return (Parametres(masse, velo.cda_m2, velo.crr), "configuration")
    # Le Crr du pneu déclaré (L9.1) passe avant celui du jeu de l'usage, mais
    # jamais avant une valeur écrite à la main dans la configuration.
    connu = crr_du_velo(velo)
    crr = connu[0] if connu is not None else None
    choix = litterature.pour_usage(velo.usage)
    if choix is not None:
        return (
            Parametres(
                masse,
                velo.cda_m2 if velo.cda_m2 is not None else choix.jeu.cda_m2,
                crr if crr is not None else choix.jeu.crr,
            ),
            "littérature",
        )
    return (
        Parametres(
            masse,
            velo.cda_m2 if velo.cda_m2 is not None else CDA_DEFAUT,
            crr if crr is not None else CRR_DEFAUT,
        ),
        "défaut",
    )


def crr_du_velo(velo: Velo) -> tuple[float, str] | None:
    """(Crr, provenance) quand le Crr du vélo est **connu** sans calibration, sinon `None`.

    Provenance « configuration » (un `crr` écrit à la main, qui prime) ou
    « pneu » (la catégorie déclarée, `physique.litterature.PNEUS`). `None` :
    ni l'un ni l'autre, et la calibration ajuste alors le Crr avec le CdA.
    """
    if velo.crr is not None:
        return (velo.crr, "configuration")
    pneu = litterature.pour_pneu(velo.pneu)
    if pneu is not None:
        return (pneu.crr, "pneu")
    return None


def fourchette_du_velo(velo: Velo, chemin: Path) -> FourchettePorteAPorte:
    """La fourchette du porte à porte de ce vélo : mesurée si elle l'a été, sinon la convention.

    Mesurée : écrite par `ourouler calibrer` dans `calibration.json`
    (provenance « mesure »). Sinon — vélo jamais calibré, calibration
    antérieure au 25/09/2026, ou trop peu de sorties roulées seul —
    `litterature.FOURCHETTE_PORTE_A_PORTE_DEFAUT` (provenance « defaut »),
    une convention mesurée sur un seul cycliste, et dite comme telle.
    """
    calibree = lire_calibration(chemin, velo.nom)
    if calibree is not None and calibree.porte_a_porte is not None:
        return calibree.porte_a_porte
    return fourchette_defaut()


def fourchette_defaut() -> FourchettePorteAPorte:
    """La convention de `physique.litterature`, en objet."""
    bas, mediane, haut = litterature.FOURCHETTE_PORTE_A_PORTE_DEFAUT
    return FourchettePorteAPorte(bas=bas, mediane=mediane, haut=haut, provenance="defaut", n=0)


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
    """Le vélo nommé, ou le premier vélo d'usage route."""
    if nom:
        return config.velo(nom)
    for velo in config.velos:
        if velo.usage == "route":
            return velo
    if not config.velos:
        raise ErreurUtilisateur("aucun vélo dans la configuration : ajouter une section [[velos]]")
    return config.velos[0]


# --- ourouler calibrer --------------------------------------------------------


def executer_calibrer(
    args: argparse.Namespace, config: Config, client_archive: ClientArchive | None = None
) -> int:
    """Calibre un vélo sur les sorties réelles du cache. Code de sortie 0 si ça a marché."""
    velo = velo_demande(config, getattr(args, "velo", None))
    if config.cycliste.ftp_w is None:
        raise ErreurUtilisateur(
            "calibration : FTP non renseignée dans la configuration — cette commande a "
            "besoin d'une FTP de référence pour repérer les sorties calibrables"
        )
    depuis = _date_option(getattr(args, "depuis", None), config.historique_depuis)
    cache = Cache(config.cache.dossier)

    # Un seul lecteur pour toute la commande : le choix des sorties a besoin
    # du contenu des fichiers (combien de sessions ? quel sport ?) et le
    # chargement en a besoin aussi. Sans mémoïsation, chaque FIT serait analysé
    # deux fois.
    lecteur = _Lecteur(cache)
    entrees, motifs = calib.sorties_calibrables_et_motifs(
        cache, config, velo, depuis=depuis, relire=lecteur
    )
    maximum = getattr(args, "max", None)
    if maximum:
        entrees = entrees[-int(maximum) :]
    if not entrees:
        raise ErreurUtilisateur(
            f"calibration : aucune sortie calibrable pour {velo.nom} depuis le {depuis} "
            "— vérifier le rattachement au vélo (`ourouler inventaire`)"
        )

    client = (
        client_archive
        if client_archive is not None
        else ClientArchive(chemin_cache=config.cache.dossier / NOM_CACHE)
    )
    sorties, pannes = _charger_sorties(lecteur, entrees, client)
    if not sorties:
        raise ErreurUtilisateur(
            f"calibration : aucune des {len(entrees)} sortie(s) de {velo.nom} n'est relisible"
        )

    crr, crr_source = _crr_de_calibration(velo, bool(getattr(args, "crr_libre", False)))
    rapport = calib.calibrer_en_deux_passes(
        sorties,
        velo=velo.nom,
        masse_totale_kg=calib.masse_totale_kg(config, velo),
        part_validation=config.calibration.part_validation,
        ftp_w=config.cycliste.ftp_w,
        vitesse_min_kmh=config.calibration.vitesse_min_kmh,
        crr_fixe=crr,
    )

    chemin = chemin_calibration(config)
    ecrire_calibration(chemin, velo.nom, _contenu_json(rapport, crr_source, velo.pneu))
    for panne in pannes:
        print(f"ourouler : {panne}", file=sys.stderr)
    if getattr(args, "json", False):
        print(
            json.dumps(
                rendre_json_calibration(
                    rapport, velo, config, chemin, client, motifs, len(entrees), crr_source
                ),
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print(
            rendre_texte_calibration(
                rapport, velo, config, chemin, client, motifs, len(entrees), crr_source
            )
        )
    return 0


def _crr_de_calibration(velo: Velo, crr_libre: bool) -> tuple[float | None, str]:
    """(Crr fixé ou `None`, provenance) pour `ourouler calibrer`.

    Le Crr connu (pneu ou configuration) est gardé fixe et seul le CdA est
    cherché — la méthode que la note du 23/09 a trouvée convergente.
    `--crr-libre`, ou un vélo sans pneu ni Crr déclarés, garde l'ajustement à
    deux paramètres d'avant : provenance « ajuste ».
    """
    connu = None if crr_libre else crr_du_velo(velo)
    if connu is None:
        return (None, "ajuste")
    return connu


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
    lecteur: _Lecteur, entrees, client: ClientArchive
) -> tuple[list[calib.SortieCalibration], list[str]]:
    """Relit chaque sortie et va chercher l'archive météo de son jour, à son départ.

    Une sortie illisible ou une archive indisponible ne fait pas échouer la
    calibration : elle est signalée et la sortie continue sans vent (ou pas du
    tout, si c'est le fichier qui manque).
    """
    sorties: list[calib.SortieCalibration] = []
    pannes: list[str] = []
    for entree in entrees:
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


def _contenu_json(
    rapport: calib.RapportCalibration, crr_source: str = "ajuste", pneu: str | None = None
) -> dict:
    a = rapport.ajustement
    return {
        "cda_m2": round(a.cda_m2, 5),
        "crr": round(a.crr, 6),
        # D'où vient le Crr (L9.1) : « pneu » ou « configuration » (fixé, seul
        # le CdA a été cherché) ou « ajuste » (cherché avec le CdA).
        "crr_source": crr_source,
        "pneu": pneu if crr_source == "pneu" else None,
        "masse_totale_kg": round(a.masse_totale_kg, 2),
        "rendement": a.parametres().rendement,
        "rho": round(a.rho_moyen, 4),
        "date": datetime.now().date().isoformat(),
        "n_sorties": rapport.n_apprentissage,
        "n_echantillons": a.n_echantillons,
        "cda_incertitude": _arrondi(a.incertitudes.cda, 5),
        "crr_incertitude": _arrondi(a.incertitudes.crr, 6),
        "rmse_w": round(a.rmse_w, 2),
        "resistance": {
            f"{vitesse:g}": {"force_n": round(force, 2), "puissance_w": round(puissance, 1)}
            for vitesse, force, puissance in a.resistances
        },
        "mae": _arrondi(rapport.validation.mae, 4),
        "mediane": _arrondi(rapport.validation.mediane, 4),
        "biais": _arrondi(rapport.validation.biais, 4),
        "n_validation": rapport.validation.n,
        "bornes_atteintes": list(a.bornes_atteintes),
        "porte_a_porte": _porte_a_porte_json(rapport.porte_a_porte),
    }


def _porte_a_porte_json(mesure: calib.MesurePorteAPorte) -> dict | None:
    """La fourchette telle que `calibration.json` la garde, ou `None` si trop peu de sorties.

    `None` n'est pas une panne : `fourchette_du_velo` retombera sur la
    convention, et le dira.
    """
    centiles = mesure.centiles
    if centiles is None:
        return None
    bas, mediane, haut = centiles
    mouvement = mesure.centiles_mouvement
    return {
        "bas": round(bas, 4),
        "mediane": round(mediane, 4),
        "haut": round(haut, 4),
        "centiles": list(calib.CENTILES_PORTE_A_PORTE),
        "n": mesure.n,
        "n_total": len(mesure.sorties),
        "seuil_groupe": mesure.seuil_groupe,
        # Ce que les centiles mesurent : temps écoulé réel (du premier au
        # dernier point, arrêts compris) / temps simulé en mouvement.
        "base": "temps_ecoule",
        # Les mêmes centiles sur le temps **en mouvement** — l'erreur du
        # modèle seul, arrêts exclus. Gardés pour comparer à la note du 23/09,
        # qui les avait lus sous ce nom.
        "ratio_mouvement": None if mouvement is None else [round(x, 4) for x in mouvement],
    }


def _arrondi(valeur: float | None, decimales: int) -> float | None:
    return None if valeur is None else round(valeur, decimales)


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
    return crr_source


def _lignes_porte_a_porte(mesure: calib.MesurePorteAPorte) -> list[str]:
    """Le paragraphe « porte à porte » du rapport : la fourchette, ou pourquoi il n'y en a pas."""
    seuil = f"{mesure.seuil_groupe:.0%}"
    centiles = mesure.centiles
    if centiles is None:
        return [
            f"Porte à porte : {mesure.n} sortie(s) roulée(s) seul (moins de {seuil} de "
            f"signal de groupe), il en faut {calib.SORTIES_MIN_FOURCHETTE} — la fourchette "
            "par défaut (convention) reste en vigueur."
        ]
    bas, mediane, haut = centiles
    lignes = [
        f"Porte à porte : temps simulé × {_fr(bas, 3)} à × {_fr(haut, 3)} "
        f"(médiane × {_fr(mediane, 3)}), centiles 25-75 du temps écoulé réel sur le "
        f"temps simulé, {mesure.n} sortie(s) sur {len(mesure.sorties)} à moins de "
        f"{seuil} de signal de groupe"
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
        "porte_a_porte": _porte_a_porte_json(rapport.porte_a_porte),
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
                    pauses, arrivee,
                ),
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print(
            rendre_texte_simulation(
                simulation, trace, velo, parametres, provenance, float(puissance), resume,
                pauses, arrivee,
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
    "NOM_CALIBRATION",
    "Calibration",
    "chemin_calibration",
    "crr_du_velo",
    "ecrire_calibration",
    "executer_calibrer",
    "executer_simuler",
    "fourchette_defaut",
    "fourchette_du_velo",
    "lignes_litterature",
    "lire_calibration",
    "litterature_json",
    "parametres_du_velo",
    "puissance_voulue",
    "velo_demande",
    "vent_depuis_meteo",
]
