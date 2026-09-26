"""Cas d'usage `calibrer` : choisir et lire les sorties d'un vélo, puis les calibrer.

Couche 3 (cas d'usage) de la règle d'imports (`ARCHITECTURE.md`). Le **calcul** — échantillons, deux
passes d'ajustement, validation, porte à porte — reste dans
`physique.calibration`, qui ne reçoit que des activités déjà lues, l'archive
météo déjà obtenue et une masse. Ce module fait le reste :

- **choisir** les sorties d'un vélo dans l'index du cache (`motif_exclusion`,
  `sorties_calibrables_et_motifs`) : sport, home-trainer, rattachement au
  vélo (`activites.inventaire`), puissance, distance, mots de groupe du
  profil ;
- **lire** chaque sortie retenue (une seule fois, `_Lecteur`) et l'archive
  météo de son jour à son point de départ (`connecteurs.openmeteo_archive`) ;
- **calibrer** (`calibrer_velo`) avec les réglages du profil, sans rien
  écrire ni imprimer : la ligne de commande (`physique.commande`) et la
  tâche de fond de l'API (`api/calibrations.py`) en sont les adaptateurs.

Il reçoit le profil du cycliste (`noyau.profil.Profil`, dont `config.Config`
est un exemple) et en lit les attributs, sans dépendre de l'entrée qui
charge la configuration (l'annotation n'est pas la `Config`). L'ordre des
sorties et des sommes est figé : une calibration existante doit rester la
même au dernier chiffre.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime

from ourouler.activites.cache import Cache, EntreeCache
from ourouler.activites.inventaire import en_interieur, rattachement_explicite, rattacher_velo
from ourouler.connecteurs.openmeteo_archive import ClientArchive
from ourouler.noyau.activite import Activite, est_sport_velo
from ourouler.noyau.erreurs import ErreurConnecteur, ErreurUtilisateur
from ourouler.noyau.profil import Profil, Velo
from ourouler.physique import calibration as calib
from ourouler.physique import litterature
from ourouler.physique.parametres_velo import CRR_DEFAUT, crr_du_velo
from ourouler.stockage.calibrations import contenu_calibration

#: Date de repli pour trier une entrée sans horodatage — avant tout le reste,
#: et consciente du fuseau, sinon la comparaison échoue sur un mélange de
#: dates naïves et datées.
_JAMAIS = datetime.min.replace(tzinfo=UTC)


# --- choix des sorties --------------------------------------------------------


def masse_totale_kg(config: Profil, velo: Velo) -> float:
    """Cycliste + vélo. Un vélo sans masse déclarée pèse `MASSE_VELO_DEFAUT_KG`.

    Une masse approximative par vélo suffit : 1 kg sur 100 kg fait 1 % en
    montée et rien sur le plat. Le calcul est
    `physique.calibration.masse_totale` ; ici, on lit la masse du cycliste.
    """
    return calib.masse_totale(config.cycliste.masse_kg, velo)


#: Le motif d'une sortie qu'on ne sait pas attribuer, en rattachement strict.
MOTIF_VELO_NON_IDENTIFIE = "vélo non identifié"


def motif_exclusion(entree: EntreeCache, config: Profil, velo: Velo, *, strict: bool = False) -> str | None:
    """Pourquoi cette sortie n'est pas calibrable, ou `None` si elle l'est.

    Rendre le motif, et pas seulement un booléen, permet à la commande de dire
    « 102 calibrables, 8 trop courtes, 2 en groupe » au lieu d'un nombre nu.

    `strict` (calibration depuis l'écran) : quand le profil a plusieurs
    vélos, une sortie qui ne désigne aucun vélo elle-même (ni capteur, ni
    équipement, ni période — `rattachement_explicite`) n'est plus créditée au
    premier vélo de route : elle est écartée, motif `MOTIF_VELO_NON_IDENTIFIE`,
    et comptée **pour chaque vélo**, pour que l'écran dise combien de sorties
    attendent d'être rattachées. Avec un seul vélo, rien ne change : toutes
    ses sorties sont les siennes.
    """
    if not est_sport_velo(entree.sport):
        return "pas du vélo"
    if en_interieur(entree):
        return "home-trainer"
    if strict and len(config.velos) > 1 and rattachement_explicite(entree, config) is None:
        return MOTIF_VELO_NON_IDENTIFIE
    if rattacher_velo(entree, config) != velo.nom:
        return "autre vélo"
    if entree.puissance_moy_w is None:
        return "sans puissance"
    if (entree.distance_m or 0.0) < calib.DISTANCE_MINIMALE_M:
        return "moins de 20 km"
    nom = str(entree.meta.get("nom") or "").casefold()
    for mot in config.calibration.mots_groupe:
        if mot and mot in nom:
            return f"nom « {mot} »"
    return None


def sorties_calibrables_et_motifs(
    cache: Cache,
    config: Profil,
    velo: Velo,
    *,
    depuis: date | None = None,
    relire: Callable[[str], Activite | None] | None = None,
    strict: bool = False,
) -> tuple[list[EntreeCache], dict[str, int]]:
    """(sorties utilisables, décompte des sorties **de ce vélo** écartées et pourquoi).

    `relire` est le seul moyen d'atteindre le contenu d'un fichier : l'index ne
    dit pas combien de sessions il porte. Il n'est appelé que sur les sorties
    qui ont déjà passé tous les filtres à bon marché, donc jamais sur les
    footings ni sur les sorties de l'autre vélo. Sans lui, la fonction se
    comporte exactement comme avant : le motif « multisport » n'existe pas.

    Les motifs « pas du vélo », « autre vélo » et « home-trainer » ne sont pas
    comptés : ils décrivent le reste du cache, pas ce que ce vélo a perdu.
    """
    depuis = depuis if depuis is not None else config.historique_depuis
    hors_sujet = ("pas du vélo", "autre vélo", "home-trainer")
    retenues: list[EntreeCache] = []
    motifs: dict[str, int] = {}
    for entree in cache.lister(depuis=depuis):
        motif = motif_exclusion(entree, config, velo, strict=strict)
        if motif is None and relire is not None:
            motif = calib.motif_multisport(relire(entree.identifiant))
        if motif is None:
            retenues.append(entree)
        elif motif not in hors_sujet:
            motifs[motif] = motifs.get(motif, 0) + 1
    retenues.sort(key=lambda e: (e.debut or _JAMAIS, e.identifiant))
    return (retenues, motifs)


def sorties_calibrables(
    cache: Cache,
    config: Profil,
    velo: Velo,
    *,
    depuis: date | None = None,
    relire: Callable[[str], Activite | None] | None = None,
) -> list[EntreeCache]:
    """Les sorties utilisables pour calibrer ce vélo, de la plus ancienne à la plus récente."""
    return sorties_calibrables_et_motifs(cache, config, velo, depuis=depuis, relire=relire)[0]


# --- calibrer un vélo ---------------------------------------------------------


@dataclass
class ResultatCalibration:
    """Ce que `calibrer_velo` a trouvé — de quoi écrire le fichier de calibration et le rapport."""

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
        """L'entrée de ce vélo dans le fichier de calibration (`stockage.calibrations`)."""
        return contenu_calibration(self.rapport, self.crr_source, self.velo.pneu)


#: Signature du rappel d'avancement de `calibrer_velo` : (étape, faits, total).
Progres = Callable[[str, int, int], None]

#: Les étapes que `calibrer_velo` annonce, dans l'ordre.
ETAPE_LECTURE = "lecture"
ETAPE_METEO = "meteo"
ETAPE_AJUSTEMENT = "ajustement"


def calibrer_velo(
    config: Profil,
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

    `crr_usage` : un vélo sans pneu ni Crr déclarés garde fixé le Crr
    du jeu de son usage (`physique.litterature`) au lieu de l'ajuster avec le
    CdA — c'est ce que l'écran propose à qui ne connaît pas ses pneus,
    l'ajustement libre dérivant sur les vraies données.

    `rattachement_strict` : quand le profil a plusieurs vélos, seules
    les sorties **explicitement** rattachées à celui-ci (capteur, équipement,
    période) comptent — voir `motif_exclusion`.

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
    candidates, _ = sorties_calibrables_et_motifs(
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

    entrees, motifs = sorties_calibrables_et_motifs(
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
        masse_totale_kg=masse_totale_kg(config, velo),
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


def _crr_de_calibration(velo: Velo, crr_libre: bool, crr_usage: bool = False) -> tuple[float | None, str]:
    """(Crr fixé ou `None`, provenance) pour `ourouler calibrer`.

    Le Crr connu (pneu ou configuration) est gardé fixe et seul le CdA est
    cherché — la méthode qui converge. `--crr-libre`, ou un vélo sans pneu ni
    Crr déclarés, garde l'ajustement à deux paramètres : provenance
    « ajuste ». Sauf `crr_usage` (l'écran) : le Crr du jeu de l'usage est alors fixé, provenance « usage ».
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
        sorties.append(calib.SortieCalibration(activite=activite, vent=vent, identifiant=entree.identifiant))
    return (sorties, pannes)


def _archive_du_depart(activite, client: ClientArchive, pannes: list[str]) -> list:
    """L'archive du jour au **point de départ** de la sortie, arrondi à 0,05°."""
    depart = next((p for p in activite.points if p.lat is not None and p.lon is not None), None)
    if depart is None or activite.debut is None:
        return []
    try:
        return client.horaires(float(depart.lat), float(depart.lon), activite.debut.date())
    except (ErreurConnecteur, ErreurUtilisateur) as e:
        motif = f"archive météo du {activite.debut.date()} indisponible ({e})"
        if motif not in pannes:
            pannes.append(motif)
        return []
