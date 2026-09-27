"""Importer l'historique qu'un cycliste dépose : fichiers isolés, `.gz`, ou
archive d'export Strava/Garmin.

**Doctrine §2** : ce module ne lit ni fichier de configuration ni variable
d'environnement — il reçoit un `Cache` déjà construit pour un propriétaire
(voir `api/routes/commun.py:_cache`, même règle que `Cache.indexer_dossier`) et des
octets ou des fichiers binaires déjà ouverts. Il ne sait pas d'où ils
viennent (HTTP, disque, test) : c'est à l'appelant de borner leur taille
totale (`api/routes/` le fait avant d'appeler).

**Rien n'est jamais extrait sur disque, et le dépôt n'est jamais chargé
d'un bloc.** L'archive déposée est lue entrée par entrée depuis le fichier
que l'appelant fournit ; seules une entrée d'activité (au plus
`TAILLE_MAX_ACTIVITE`) et, au besoin, une archive imbriquée (au plus
`TAILLE_MAX_FICHIER`) passent en mémoire. Toute décompression — `.gz`,
`.zip`, et les `.zip` imbriqués que Garmin range dans son archive — se fait
en mémoire, avec un plafond vérifié à la lecture et pas seulement lu dans les
métadonnées de l'archive (une taille déclarée dans un en-tête `.zip` n'est
pas digne de confiance : `_lire_borne_compte` coupe au premier
octet en trop, quoi que l'archive prétende contenir).

**Les bornes ci-dessous viennent de deux archives réelles**
(`docs/journal/archives_export_mesures.md`), avec une marge généreuse — pas d'un chiffre rond choisi à
l'aveugle :

- Strava : 665 Mo, 3 730 entrées, 20 Mo utiles une fois le tri fait.
- Garmin : six `.zip` imbriqués dans le `.zip` principal, un ratio de
  décompression de 11 sur l'enveloppe *intérieure* quand l'extérieure n'est
  qu'à 1,5 — d'où un plafond de ratio vérifié **à chaque niveau
  d'imbrication**, pas seulement sur l'archive déposée : « un plafond de
  ratio posé sur l'enveloppe ne verrait rien » (archives_export_mesures.md).

Un fichier corrompu, une archive hostile ou une entrée hors liste ne fait
jamais échouer l'import : il compte dans `RapportImport.ignorees`, avec un
motif lisible — même philosophie que `Cache.indexer_dossier`, qui ne laisse
pas un `.fit` abîmé faire échouer tout un dossier.

**Pour un compte qui ne garde pas ses fichiers d'origine** (fiche « choix de
garder ou d'effacer ses fichiers d'origine ») : l'appelant passe un cache qui
ne conserve pas le brut (`Cache(..., conserver_brut=False)`) et un `deriver`
— ce qu'on tire de chaque sortie pour la calibration, sans coordonnées
(`services/derive.py`). Ce module ne sait pas ce que le dérivé contient : il
le fait calculer pendant que les octets sont encore en mémoire, et c'est
tout.
"""

from __future__ import annotations

import gzip
import hashlib
import io
import sqlite3
import stat
import zipfile
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import BinaryIO, Protocol

from ourouler.activites.cache import Cache
from ourouler.activites.lecture import lecteur_pour
from ourouler.noyau.activite import Activite

#: `(fichiers_traites, total_estime)`, rappelé pendant l'import — pour la
#: tâche de fond (`api/imports_fond.py`) : une archive Strava réelle prend
#: environ 16 minutes à 0,33 s/fichier, largement au-delà des 180 s où le
#: front abandonne, et son avancement doit se voir. `total_estime` grandit
#: au fil de la lecture : il ne compte au départ que les entrées du niveau
#: qu'on vient d'ouvrir (le dépôt lui-même, une archive Garmin imbriquée
#: qu'on découvre en cours de route) — jamais un dénombrement complet
#: d'avance, qui coûterait aussi cher que l'import.
Progres = Callable[[int, int], None]


class Deriveur(Protocol):
    """Ce que l'import demande à qui dérive (`services.derive.Derivateur`) — voir le module.

    `__call__` peut rendre la main avant d'avoir fini (le vent de la sortie
    arrive en fond) : `terminer()` attend ce qui reste, `fermer()` l'abandonne.
    Les compteurs se lisent une fois `terminer()` fait.
    """

    derivees: int
    rafraichies: int
    sans_vent: int
    echecs: list[tuple[str, str]]

    def a_rafraichir(self, identifiant: str) -> bool: ...

    def __call__(
        self, identifiant: str, activite: Activite, meta: dict | None = None, *, nom: str, deja: bool
    ) -> str: ...

    def terminer(self) -> None: ...

    def fermer(self) -> None: ...


#: `.fit`/`.gpx`/`.tcx`, avec ou sans `.gz` — Strava gzippe ses fichiers
#: d'activité à l'intérieur de son archive (décision Q48,
#: `docs/journal/questions/questions_mainteneur.md`).
EXTENSIONS_ACTIVITE = ("fit", "gpx", "tcx")

#: Taille max d'une requête entière (tous les fichiers déposés d'un coup).
#: Au-dessus des 665 Mo mesurés pour une archive Strava complète, en dessous
#: du gigaoctet.
TAILLE_MAX_REQUETE = 750 * 1024 * 1024

#: Fichiers utiles rencontrés, tous niveaux d'imbrication confondus. Strava
#: en compte 3 730 ; Garmin, une fois ses six `.zip` ouverts, environ
#: 2 500 — marge x5.
NOMBRE_MAX_FICHIERS = 20_000

#: Total d'octets décompressés qu'un import peut produire, tous fichiers et
#: niveaux confondus — la protection qui compte contre une bombe de
#: décompression, plutôt qu'un plafond posé sur la seule enveloppe
#: extérieure.
TAILLE_MAX_DECOMPRESSEE = 2 * 1024 * 1024 * 1024

#: Taille décompressée max d'une archive `.zip` *imbriquée* — elle est lue
#: dans un tampon en mémoire avant d'être ouverte. Garmin range 238 Mo dans
#: six `.zip`, soit une quarantaine de Mo chacun : marge x5.
TAILLE_MAX_FICHIER = 200 * 1024 * 1024

#: Taille décompressée max d'un fichier d'activité (`.fit`/`.gpx`/`.tcx`).
#: Mesurée sur les 936 fichiers d'un historique réel : le plus gros fait
#: 3,7 Mo (un `.gpx`), le plus gros `.fit` 3,0 Mo. Un plafond de 200 Mo, comme
#: pour les archives, laisserait `gpxpy` monter un
#: arbre XML de plusieurs Go à partir d'un seul `.gpx.gz` de quelques Ko.
#:
#: **16 Mo et non 50**, sur mesure :
#: un `.gpx` valide et synthétique de 50 Mo (555 000 points) prend 6,4 s et
#: **+745 Mo** de mémoire résidente à lire (`lecture.py`, `gpxpy`) — sur un
#: serveur partagé avec BRouter, c'est un fichier qui suffit à tout faire
#: tomber. À 16 Mo : 1,9 s et +240 Mo (10 Mo : 1,1 s, +150 Mo). 16 Mo, c'est
#: plus de 4 fois le plus gros fichier réel mesuré, et une sortie de 15 h
#: enregistrée à la seconde avec cardio, cadence et puissance.
TAILLE_MAX_ACTIVITE = 16 * 1024 * 1024

#: Ratio décompressé/compressé max toléré pour une entrée. Mesuré à 11 sur
#: l'archive Garmin réelle (`docs/journal/archives_export_mesures.md`) ; marge x9.
RATIO_MAX_DECOMPRESSION = 100

#: Profondeur d'imbrication max (un `.zip` dans un `.zip`, dans un `.zip`…).
#: Garmin range ses sorties sous des `.zip` imbriqués à un seul niveau ; on
#: en garde trois pour la marge, sans ouvrir la porte à une récursion sans
#: fin.
PROFONDEUR_MAX_ARCHIVE = 3

#: Combien d'octets on lit à la fois lorsqu'on borne une décompression.
TAILLE_BLOC = 65_536


@dataclass
class Ignoree:
    """Un fichier ou une archive qu'on n'a pas importé, et pourquoi."""

    nom: str
    motif: str


@dataclass
class RapportImport:
    """Ce que `importer()` rend : de quoi écrire la réponse de l'API."""

    importees: int = 0
    doublons: int = 0
    ignorees: list[Ignoree] = field(default_factory=list)
    #: Faux pour un compte qui ne garde pas ses fichiers d'origine : le
    #: fichier n'a pas été gardé, seul ce qu'on en a tiré. L'écran le dit à
    #: côté du rapport.
    fichiers_conserves: bool = True
    #: Sorties dont on a tiré de quoi calibrer (compte sans fichiers gardés
    #: seulement) — dont `rafraichies` : déjà connues, mais dont le dérivé
    #: manquait ou était périmé, ce qu'un nouveau dépôt de la même archive
    #: vient réparer.
    derivees: int = 0
    rafraichies: int = 0
    #: Sorties dérivées sans vent : l'archive météo de leur jour n'a pas
    #: répondu (ou le jour est trop récent pour elle).
    sans_vent: int = 0
    #: Sorties déjà connues dont le fichier d'origine manquait (compte
    #: revenu à « garder » après un passage par « ne pas garder ») et que ce
    #: dépôt vient de rendre — ni un doublon, ni un nouvel import.
    restaurees: int = 0

    def resume_ignorees(self, max_exemples: int = 5) -> list[dict]:
        """Les motifs groupés, comptés, avec quelques noms d'exemple.

        Une archive Strava réelle porte des centaines de médias hors liste :
        les lister un par un noierait les deux ou trois motifs qui comptent
        vraiment (bombe, chemin refusé, fichier corrompu) sous des lignes
        « photo.jpg : extension non prise en charge » répétées à l'identique.
        """
        par_motif: dict[str, list[str]] = {}
        for entree in self.ignorees:
            par_motif.setdefault(entree.motif, []).append(entree.nom)
        return [
            {"motif": motif, "nombre": len(noms), "exemples": noms[:max_exemples]}
            for motif, noms in par_motif.items()
        ]

    def json(self) -> dict:
        return {
            "importees": self.importees,
            "doublons": self.doublons,
            "ignorees": self.resume_ignorees(),
            "fichiers_conserves": self.fichiers_conserves,
            "derivees": self.derivees,
            "rafraichies": self.rafraichies,
            "sans_vent": self.sans_vent,
            "restaurees": self.restaurees,
        }


@dataclass
class _Etat:
    """Ce que l'import accumule en traversant, éventuellement, plusieurs archives."""

    cache: Cache
    rapport: RapportImport
    fichiers_vus: int = 0
    total_estime: int = 0
    octets_decompresses: int = 0
    limites_signalees: set[str] = field(default_factory=set)
    progres: Progres | None = None
    deriver: Deriveur | None = None

    def compter(self, entrees: int) -> None:
        """Une archive (le dépôt, ou une archive imbriquée) vient de s'ouvrir : `entrees`
        de plus dans l'estimation totale."""
        self.total_estime += entrees
        self._avertir()

    def avancer(self) -> None:
        """Une entrée de plus a été traitée (importée, doublon ou ignorée)."""
        self.fichiers_vus += 1
        self._avertir()

    def _avertir(self) -> None:
        if self.progres is not None:
            self.progres(self.fichiers_vus, max(self.total_estime, self.fichiers_vus))


def importer(
    cache: Cache,
    depots: list[tuple[str, bytes | BinaryIO]],
    progres: Progres | None = None,
    deriver: Deriveur | None = None,
) -> RapportImport:
    """Importe un ou plusieurs fichiers/archives déposés en une requête.

    `depots` : `[(nom, contenu)]`, où `contenu` est soit des octets, soit un
    **fichier binaire positionnable** (le fichier temporaire où la couche web
    a déjà reçu le dépôt). La seconde forme est celle de l'API : une archive
    Strava de 665 Mo n'est jamais chargée en mémoire d'un bloc, `zipfile` la
    lit entrée par entrée depuis ce fichier.

    Chaque élément est traité indépendamment, et un dépôt corrompu n'empêche
    pas les suivants. Plusieurs archives successives, à des appels
    distincts, sont le cas normal (un export volumineux peut arriver en
    plusieurs archives) : les bornes de `_Etat` sont
    neuves à chaque appel.

    **L'identité d'une sortie déposée est son contenu**, pas son nom (voir
    `_importer_contenu`) : réimporter la même archive, ou le même fichier
    sous un autre nom, n'ajoute rien ; deux sorties différentes qui portent
    le même nom (« Morning_Ride.gpx ») restent deux sorties.

    `progres`, s'il est donné, est rappelé avec `(fichiers_traites, total_estime)`
    à mesure que l'import avance — voir `Progres`.

    `deriver`, s'il est donné (compte sans fichiers gardés), tire de chaque
    sortie ce que la calibration lira plus tard, pendant que ses octets sont
    encore là — et refait ce dérivé pour une sortie déjà connue dont le
    dérivé manque ou est périmé (redéposer son archive répare, sans rien
    dupliquer).
    """
    etat = _Etat(
        cache=cache,
        rapport=RapportImport(fichiers_conserves=cache.conserver_brut),
        progres=progres,
        deriver=deriver,
    )
    try:
        for nom, contenu in depots:
            source = io.BytesIO(contenu) if isinstance(contenu, bytes | bytearray) else contenu
            if not nom.lower().endswith(".zip"):
                etat.compter(1)
            _importer_un(etat, nom or "(sans nom)", source)
        if deriver is not None:
            deriver.terminer()
            etat.rapport.derivees = deriver.derivees
            etat.rapport.rafraichies = deriver.rafraichies
            etat.rapport.sans_vent = deriver.sans_vent
            etat.rapport.ignorees.extend(
                Ignoree(nom=nom, motif=f"importée, mais rien à en tirer pour la calibration ({motif})")
                for nom, motif in deriver.echecs
            )
    finally:
        # Annulation, panne : les appels à l'archive encore en vol sont abandonnés.
        if deriver is not None:
            deriver.fermer()
    return etat.rapport


def etat(cache: Cache) -> dict:
    """Combien de sorties ce propriétaire a déjà déposées, et sur quelle période.

    Ne compte que `source == "fichier"` : c'est l'état du **dépôt**, pas
    l'inventaire complet d'`activites/inventaire.py` (qui mélange aussi les
    sorties synchronisées depuis Intervals.icu et exige un profil complet
    pour rattacher chaque sortie à un vélo — un invité qui vient d'arriver
    n'en a pas encore un).
    """
    entrees = [e for e in cache.lister() if e.source == "fichier"]
    jours = [e.jour for e in entrees if e.jour is not None]
    return {
        "nombre": len(entrees),
        "premiere": min(jours).isoformat() if jours else None,
        "derniere": max(jours).isoformat() if jours else None,
    }


# --- un dépôt, isolé ou archive ------------------------------------------------


def _importer_un(etat: _Etat, nom: str, source: BinaryIO) -> None:
    if nom.lower().endswith(".zip"):
        _traiter_zip(etat, source, prefixe="", profondeur=0, nom_archive=nom)
        return
    extension = _extension_utile(nom)
    if extension is None:
        etat.rapport.ignorees.append(
            Ignoree(
                nom=nom,
                motif="extension non prise en charge — .fit/.gpx/.tcx (.gz compris) ou une "
                "archive .zip Strava/Garmin attendue",
            )
        )
        etat.avancer()
        return
    donnees = _lire_activite(etat, nom, source)
    if donnees is not None:
        _importer_contenu(etat, nom, donnees, extension)
    etat.avancer()


def _traiter_zip(etat: _Etat, source: BinaryIO, prefixe: str, profondeur: int, nom_archive: str) -> None:
    """Lit une archive `.zip` entrée par entrée, bornée à chaque étape.

    `source` est un fichier positionnable (le dépôt lui-même, ou le tampon
    d'une archive imbriquée) : `zipfile` n'en lit que le répertoire central
    puis les entrées qu'on lui demande.
    """
    if profondeur > PROFONDEUR_MAX_ARCHIVE:
        _signaler_une_fois(
            etat,
            f"imbrication:{prefixe}",
            f"{prefixe or '(archive)'} : imbriquée au-delà de {PROFONDEUR_MAX_ARCHIVE} niveaux, ignorée",
        )
        return
    try:
        zf = zipfile.ZipFile(source)
    except Exception as e:  # entrée hostile : tout échec est « illisible »
        etat.rapport.ignorees.append(
            Ignoree(nom=prefixe or nom_archive, motif=f"archive corrompue ({_cause(e)})")
        )
        return

    utiles = [i for i in zf.infolist() if not i.is_dir()]
    etat.compter(len(utiles))

    with zf:
        for info in utiles:
            if etat.fichiers_vus >= NOMBRE_MAX_FICHIERS:
                _signaler_une_fois(
                    etat,
                    "nombre_de_fichiers",
                    f"plus de {NOMBRE_MAX_FICHIERS} fichiers rencontrés, le reste est ignoré",
                )
                return
            if _traiter_entree(etat, zf, info, prefixe, profondeur):
                return


def _traiter_entree(
    etat: _Etat, zf: zipfile.ZipFile, info: zipfile.ZipInfo, prefixe: str, profondeur: int
) -> bool:
    """Traite une entrée de l'archive ; `True` si la lecture de l'archive doit s'arrêter."""
    nom_interne = f"{prefixe}{info.filename}"

    if not _chemin_sur(info.filename) or _est_lien_symbolique(info):
        etat.rapport.ignorees.append(
            Ignoree(nom=nom_interne, motif="chemin refusé (absolu, « .. » ou lien symbolique)")
        )
        etat.avancer()
        return False

    est_zip_imbrique = info.filename.lower().endswith(".zip")
    extension = _extension_utile(info.filename)
    if extension is None and not est_zip_imbrique:
        # Média, `.csv`, `.json`… hors liste (contacts, messages — jamais lus,
        # ce ne sont pas des données de sortie). Compté et motivé, jamais
        # décompressé.
        etat.rapport.ignorees.append(
            Ignoree(
                nom=nom_interne,
                motif="extension non prise en charge — média, .csv, .json… hors liste",
            )
        )
        etat.avancer()
        return False

    motif = _motif_hostile(info, TAILLE_MAX_FICHIER if est_zip_imbrique else TAILLE_MAX_ACTIVITE)
    if motif:
        etat.rapport.ignorees.append(Ignoree(nom=nom_interne, motif=motif))
        etat.avancer()
        return False

    if est_zip_imbrique:
        tampon = _lire_entree(etat, zf, info, nom_interne, TAILLE_MAX_FICHIER)
        if tampon is None:
            etat.avancer()
            return etat.octets_decompresses >= TAILLE_MAX_DECOMPRESSEE
        _traiter_zip(etat, tampon, f"{nom_interne}:", profondeur + 1, nom_interne)
        etat.avancer()
        return False

    try:
        entree = zf.open(info)
    except Exception as e:  # chiffrée, méthode inconnue, en-tête faux
        etat.rapport.ignorees.append(Ignoree(nom=nom_interne, motif=f"fichier corrompu ({_cause(e)})"))
        etat.avancer()
        return False
    with entree:
        donnees = _lire_activite(etat, nom_interne, entree)
    if donnees is None:
        etat.avancer()
        return etat.octets_decompresses >= TAILLE_MAX_DECOMPRESSEE
    _importer_contenu(etat, nom_interne, donnees, extension)
    etat.avancer()
    return False


def _importer_contenu(etat: _Etat, nom: str, contenu: bytes, extension: str) -> None:
    """Indexe des octets déjà décompressés, **identifiés par leur contenu**.

    `id_externe` est le sha256 du contenu, pas le nom du fichier. Avec le
    nom, deux défauts : deux sorties différentes portant le même nom
    (« Morning_Ride.gpx », le nom qu'un export Strava donne à une sortie)
    s'écraseraient — `Cache.ajouter` met la ligne à jour — et compteraient
    comme deux imports ; et la même sortie déposée isolée puis dans l'archive
    (`1234.fit`, puis `activities/1234.fit.gz`) ferait deux lignes. Le nom reste dans `meta["fichier"]`.

    `Cache.indexer_dossier` (la ligne de commande) garde le nom : là, c'est
    un chemin sur un disque, qui désigne vraiment un fichier.
    """
    identifiant = hashlib.sha256(contenu).hexdigest()
    deja = etat.cache.contient(source="fichier", id_externe=identifiant)
    a_deriver = deja and etat.deriver is not None and etat.deriver.a_rafraichir(identifiant)
    # « Revenir à garder puis réimporter garde de nouveau les fichiers » (fiche
    # « choix de garder ou d'effacer ses fichiers d'origine ») : une sortie
    # déjà connue, mais dont le fichier a été effacé (compte qui était passé
    # par « ne pas garder »), doit le retrouver si le compte garde à nouveau
    # ses fichiers — sans dupliquer sa ligne d'index.
    fichier_absent = deja and etat.cache.conserver_brut and not etat.cache.chemin(identifiant).is_file()
    if deja and not a_deriver and not fichier_absent:
        etat.rapport.doublons += 1
        return
    # Le nom du fichier n'est gardé qu'avec le fichier : sans lui (compte qui
    # ne garde pas ses fichiers d'origine), un nom d'export Strava
    # (`activities/1234567890.fit.gz`) est l'identifiant de l'activité chez
    # Strava, qui désigne la trace ailleurs.
    meta = {"fichier": nom} if etat.cache.conserver_brut else {}
    try:
        activite = lecteur_pour(extension)(contenu)
        if not deja or fichier_absent:
            etat.cache.ajouter(
                contenu,
                source="fichier",
                id_externe=identifiant,
                extension=extension,
                meta=meta,
                activite=activite,
            )
    except sqlite3.Error:
        raise  # l'index du serveur est en panne : ce n'est pas la faute du fichier
    except Exception as e:  # noqa: BLE001 — les lecteurs FIT/GPX/TCX sur octets hostiles
        etat.rapport.ignorees.append(Ignoree(nom=nom, motif=f"fichier corrompu ({_cause(e)})"))
        return
    if not deja:
        etat.rapport.importees += 1
    elif fichier_absent:
        etat.rapport.restaurees += 1
    if etat.deriver is None:
        return
    # Le dérivateur rattrape lui-même ce qu'une sortie hostile lui fait lever ;
    # ce qui passe ici (annulation de la tâche, index en panne) doit arrêter l'import.
    statut = etat.deriver(identifiant, activite, meta, nom=nom, deja=deja)
    if deja and statut != "en_attente":  # `services.derive.STATUT_EN_ATTENTE`, en clair pour éviter le cycle
        etat.rapport.doublons += 1


# --- bornes, vérifiées à la lecture, pas seulement aux métadonnées ------------


def _extension_utile(nom: str) -> str | None:
    """`fit`/`gpx`/`tcx` si ce nom en est un, `.gz` ôté au besoin — sinon `None`."""
    base = nom.lower()
    if base.endswith(".gz"):
        base = base[:-3]
    extension = base.rsplit(".", 1)[-1] if "." in base else ""
    return extension if extension in EXTENSIONS_ACTIVITE else None


def _chemin_sur(nom: str) -> bool:
    """Refuse un chemin absolu ou qui remonte hors de l'archive (`..`)."""
    if not nom:
        return False
    normalise = nom.replace("\\", "/")
    if normalise.startswith("/"):
        return False
    premier = normalise.split("/", 1)[0]
    if len(premier) == 2 and premier[1] == ":":  # lecteur Windows, « C: »
        return False
    return ".." not in normalise.split("/")


def _est_lien_symbolique(info: zipfile.ZipInfo) -> bool:
    mode = (info.external_attr >> 16) & 0xFFFF
    return bool(mode) and stat.S_ISLNK(mode)


def _motif_hostile(info: zipfile.ZipInfo, plafond: int) -> str | None:
    """Le motif de refus d'après les métadonnées de l'entrée, ou `None`.

    Un contrôle **rapide**, sur ce que l'archive annonce — il ne dispense pas
    de `_lire_borne_compte`, qui vérifie ce qui sort vraiment : une métadonnée de
    `.zip` n'engage que celui qui l'a écrite.
    """
    if info.file_size > plafond:
        return f"fichier annoncé à {info.file_size} octets décompressés, au-delà du plafond"
    if info.compress_size > 0 and info.file_size / info.compress_size > RATIO_MAX_DECOMPRESSION:
        ratio = info.file_size / info.compress_size
        return f"taux de décompression suspect ({ratio:.0f}×) — refusé comme une bombe"
    return None


def _lire_entree(
    etat: _Etat, zf: zipfile.ZipFile, info: zipfile.ZipInfo, nom: str, plafond: int
) -> io.BytesIO | None:
    """Une archive imbriquée, lue bornée dans un tampon — `None` (et motivé) sinon."""
    try:
        with zf.open(info) as source:
            return _lire_borne_compte(etat, nom, source, plafond)
    except Exception as e:  # entrée hostile : tout échec est « illisible »
        etat.rapport.ignorees.append(Ignoree(nom=nom, motif=f"fichier corrompu ({_cause(e)})"))
        return None


def _lire_activite(etat: _Etat, nom: str, source: BinaryIO) -> bytes | None:
    """Les octets d'un fichier d'activité, `.gz` ôté, bornés — `None` (et motivé) sinon.

    Tout ce qui sort compte dans `TAILLE_MAX_DECOMPRESSEE`, y compris la
    décompression d'un `.gz` rangé dans une archive : sans quoi vingt mille
    `.gz` de 50 Mo passeraient sous le plafond total.
    """
    try:
        if nom.lower().endswith(".gz"):
            with gzip.GzipFile(fileobj=source, mode="rb") as degzip:
                tampon = _lire_borne_compte(etat, nom, degzip, TAILLE_MAX_ACTIVITE)
        else:
            tampon = _lire_borne_compte(etat, nom, source, TAILLE_MAX_ACTIVITE)
    except Exception as e:  # zlib, lzma, bz2, en-tête faux : tout est « illisible »
        etat.rapport.ignorees.append(Ignoree(nom=nom, motif=f"fichier corrompu ({_cause(e)})"))
        return None
    if tampon is None:
        return None
    return tampon.getvalue()


def _lire_borne_compte(etat: _Etat, nom: str, source, plafond: int) -> io.BytesIO | None:
    """Lit `source` par blocs, coupe au premier octet au-delà de `plafond` ou du total.

    C'est ce contrôle-ci, pas `_motif_hostile`, qui protège vraiment contre
    une bombe : il porte sur les octets réellement décompressés, pas sur ce
    que l'en-tête prétend. Le tampon est rendu tel quel, sans recopie : une
    archive imbriquée est relue directement depuis lui.
    """
    tampon = io.BytesIO()
    while True:
        bloc = source.read(TAILLE_BLOC)
        if not bloc:
            break
        etat.octets_decompresses += len(bloc)
        if etat.octets_decompresses > TAILLE_MAX_DECOMPRESSEE:
            _signaler_une_fois(
                etat,
                "total_decompresse",
                f"plus de {TAILLE_MAX_DECOMPRESSEE // (1024 * 1024)} Mo décompressés au "
                "total, import arrêté (bombe de décompression suspectée)",
            )
            return None
        if tampon.tell() + len(bloc) > plafond:
            etat.rapport.ignorees.append(
                Ignoree(nom=nom, motif="décompression au-delà du plafond attendu, ignorée")
            )
            return None
        tampon.write(bloc)
    tampon.seek(0)
    return tampon


def _cause(e: Exception) -> str:
    """Le message d'une exception, ou son type quand elle n'en a pas."""
    return str(e).removeprefix("<octets> : ") or type(e).__name__


def _signaler_une_fois(etat: _Etat, cle: str, motif: str) -> None:
    """Ajoute `motif` au rapport une seule fois par `cle` — une bombe ne doit pas
    produire vingt mille lignes identiques."""
    if cle in etat.limites_signalees:
        return
    etat.limites_signalees.add(cle)
    etat.rapport.ignorees.append(Ignoree(nom="(archive)", motif=motif))


__all__ = [
    "EXTENSIONS_ACTIVITE",
    "Deriveur",
    "NOMBRE_MAX_FICHIERS",
    "PROFONDEUR_MAX_ARCHIVE",
    "RATIO_MAX_DECOMPRESSION",
    "TAILLE_MAX_ACTIVITE",
    "TAILLE_MAX_DECOMPRESSEE",
    "TAILLE_MAX_FICHIER",
    "TAILLE_MAX_REQUETE",
    "Ignoree",
    "RapportImport",
    "etat",
    "importer",
]
