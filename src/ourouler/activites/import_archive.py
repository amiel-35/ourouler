"""Importer l'historique qu'un cycliste dépose : fichiers isolés, `.gz`, ou
archive d'export Strava/Garmin (lot L9.2, `docs/sprint9_contrat.md`).

**Doctrine §2** : ce module ne lit ni fichier de configuration ni variable
d'environnement — il reçoit un `Cache` déjà construit pour un propriétaire
(voir `api/routes.py:_cache`, même règle que `Cache.indexer_dossier`) et des
octets déjà en mémoire. Il ne sait pas d'où ils viennent (HTTP, disque,
test) : c'est à l'appelant de les borner à la source (`api/routes.py` le
fait sur `Content-Length` avant même de lire le corps).

**Rien n'est jamais extrait sur disque.** Toute décompression — `.gz`,
`.zip`, et les `.zip` imbriqués que Garmin range dans son archive — se fait
en mémoire, avec un plafond vérifié à la lecture et pas seulement lu dans les
métadonnées de l'archive (une taille déclarée dans un en-tête `.zip` n'est
pas digne de confiance : `_lire_borne` et `_degzip_borne` coupent au premier
octet en trop, quoi que l'archive prétende contenir).

**Les bornes ci-dessous viennent des deux archives réelles du mainteneur**
(`docs/services_externes.md`, §« Les archives d'export, mesurées sur de
vraies données »), avec une marge généreuse — pas d'un chiffre rond choisi à
l'aveugle :

- Strava : 665 Mo, 3 730 entrées, 20 Mo utiles une fois le tri fait.
- Garmin : six `.zip` imbriqués dans le `.zip` principal, un ratio de
  décompression de 11 sur l'enveloppe *intérieure* quand l'extérieure n'est
  qu'à 1,5 — d'où un plafond de ratio vérifié **à chaque niveau
  d'imbrication**, pas seulement sur l'archive déposée : « un plafond de
  ratio posé sur l'enveloppe ne verrait rien » (services_externes.md).

Un fichier corrompu, une archive hostile ou une entrée hors liste ne fait
jamais échouer l'import : il compte dans `RapportImport.ignorees`, avec un
motif lisible — même philosophie que `Cache.indexer_dossier`, qui ne laisse
pas un `.fit` abîmé faire échouer tout un dossier.
"""

from __future__ import annotations

import gzip
import hashlib
import io
import stat
import zipfile
from dataclasses import dataclass, field

from ourouler.activites.cache import Cache
from ourouler.erreurs import ErreurLecture, ErreurUtilisateur

#: `.fit`/`.gpx`/`.tcx`, avec ou sans `.gz` — Strava gzippe ses fichiers
#: d'activité à l'intérieur de son archive (`docs/questions_mainteneur.md`,
#: Q48 : « le seul angle mort mesuré »).
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

#: Taille décompressée max d'une *seule* entrée — défense en profondeur,
#: pour qu'une entrée ne consomme pas à elle seule tout le plafond ci-dessus.
TAILLE_MAX_FICHIER = 200 * 1024 * 1024

#: Ratio décompressé/compressé max toléré pour une entrée. Mesuré à 11 sur
#: l'archive Garmin réelle (`docs/services_externes.md`) ; marge x9.
RATIO_MAX_DECOMPRESSION = 100

#: Profondeur d'imbrication max (un `.zip` dans un `.zip`, dans un `.zip`…).
#: Garmin range ses sorties sous des `.zip` imbriqués à un seul niveau ; on
#: en garde trois pour la marge, sans ouvrir la porte à une récursion sans
#: fin.
PROFONDEUR_MAX_ARCHIVE = 3

#: Combien d'octets on lit à la fois lorsqu'on borne une décompression.
TAILLE_BLOC = 65_536


class ErreurArchiveHostile(ErreurUtilisateur):
    """Signal interne : une entrée dépasse une borne à la lecture, pas aux métadonnées."""


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
        }


@dataclass
class _Etat:
    """Ce que l'import accumule en traversant, éventuellement, plusieurs archives."""

    cache: Cache
    rapport: RapportImport
    fichiers_vus: int = 0
    octets_decompresses: int = 0
    limites_signalees: set[str] = field(default_factory=set)


def importer(cache: Cache, depots: list[tuple[str, bytes]]) -> RapportImport:
    """Importe un ou plusieurs fichiers/archives déposés en une requête.

    `depots` : `[(nom, octets)]`, tels que reçus du multipart — chaque
    élément est traité indépendamment, et un dépôt corrompu n'empêche pas les
    suivants. Plusieurs archives successives, à des appels distincts, sont le
    cas normal ([[Q62]]) : les bornes de `_Etat` sont neuves à chaque appel,
    et `Cache.ajouter` dédoublonne par `(propriétaire, source, id_externe)`
    contre ce qui est déjà indexé — réimporter la même archive n'ajoute rien
    de plus.
    """
    etat = _Etat(cache=cache, rapport=RapportImport())
    for nom, contenu in depots:
        _importer_un(etat, nom or "(sans nom)", contenu)
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


def _importer_un(etat: _Etat, nom: str, contenu: bytes) -> None:
    base = nom.lower()
    if base.endswith(".zip"):
        _traiter_zip(etat, contenu, prefixe="", profondeur=0)
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
        return
    if base.endswith(".gz"):
        try:
            contenu = _degzip_borne(contenu, TAILLE_MAX_FICHIER)
        except (ErreurLecture, ErreurArchiveHostile) as e:
            etat.rapport.ignorees.append(Ignoree(nom=nom, motif=f"gz illisible ({e})"))
            return
    _importer_contenu(etat, nom, contenu, extension)


def _traiter_zip(etat: _Etat, contenu: bytes, prefixe: str, profondeur: int) -> None:
    """Lit une archive `.zip` en mémoire, entrée par entrée, bornée à chaque étape."""
    if profondeur > PROFONDEUR_MAX_ARCHIVE:
        _signaler_une_fois(
            etat,
            f"imbrication:{prefixe}",
            f"{prefixe or '(archive)'} : imbriquée au-delà de {PROFONDEUR_MAX_ARCHIVE} "
            "niveaux, ignorée",
        )
        return
    try:
        zf = zipfile.ZipFile(io.BytesIO(contenu))
    except zipfile.BadZipFile as e:
        etat.rapport.ignorees.append(Ignoree(nom=prefixe or "(archive)", motif=f"archive corrompue ({e})"))
        return

    with zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            if etat.fichiers_vus >= NOMBRE_MAX_FICHIERS:
                _signaler_une_fois(
                    etat,
                    "nombre_de_fichiers",
                    f"plus de {NOMBRE_MAX_FICHIERS} fichiers rencontrés, le reste est ignoré",
                )
                return
            etat.fichiers_vus += 1
            nom_interne = f"{prefixe}{info.filename}"

            if not _chemin_sur(info.filename) or _est_lien_symbolique(info):
                etat.rapport.ignorees.append(
                    Ignoree(nom=nom_interne, motif="chemin refusé (absolu, « .. » ou lien symbolique)")
                )
                continue

            motif = _motif_hostile(info)
            if motif:
                etat.rapport.ignorees.append(Ignoree(nom=nom_interne, motif=motif))
                continue

            est_zip_imbrique = info.filename.lower().endswith(".zip")
            extension = _extension_utile(info.filename)
            if extension is None and not est_zip_imbrique:
                # Média, `.csv`, `.json`… hors liste (contacts, messages — jamais lus,
                # règle absolue 1). Compté et motivé, jamais téléchargé au-delà de ces
                # octets : on ne lit ni n'écrit son contenu.
                etat.rapport.ignorees.append(
                    Ignoree(
                        nom=nom_interne,
                        motif="extension non prise en charge — média, .csv, .json… hors liste",
                    )
                )
                continue

            restant = TAILLE_MAX_DECOMPRESSEE - etat.octets_decompresses
            if restant <= 0:
                _signaler_une_fois(
                    etat,
                    "total_decompresse",
                    f"plus de {TAILLE_MAX_DECOMPRESSEE // (1024 * 1024)} Mo décompressés au "
                    "total, import arrêté (bombe de décompression suspectée)",
                )
                return
            try:
                donnees = _lire_borne(zf, info, min(TAILLE_MAX_FICHIER, restant))
            except ErreurArchiveHostile:
                etat.rapport.ignorees.append(
                    Ignoree(nom=nom_interne, motif="décompression au-delà du plafond attendu, ignorée")
                )
                continue
            except (zipfile.BadZipFile, OSError, EOFError) as e:
                etat.rapport.ignorees.append(Ignoree(nom=nom_interne, motif=f"fichier corrompu ({e})"))
                continue
            etat.octets_decompresses += len(donnees)

            if est_zip_imbrique:
                _traiter_zip(etat, donnees, f"{nom_interne}:", profondeur + 1)
                continue

            if info.filename.lower().endswith(".gz"):
                try:
                    donnees = _degzip_borne(donnees, TAILLE_MAX_FICHIER)
                except (ErreurLecture, ErreurArchiveHostile) as e:
                    etat.rapport.ignorees.append(Ignoree(nom=nom_interne, motif=f"gz illisible ({e})"))
                    continue
            _importer_contenu(etat, nom_interne, donnees, extension)


def _importer_contenu(etat: _Etat, nom: str, contenu: bytes, extension: str) -> None:
    """Indexe des octets déjà décompressés — dédoublonne comme `Cache.indexer_dossier`."""
    identifiant = hashlib.sha256(contenu).hexdigest()
    if etat.cache.contient(source="fichier", id_externe=nom) and etat.cache.contient_identifiant(identifiant):
        etat.rapport.doublons += 1
        return
    try:
        etat.cache.ajouter(
            contenu, source="fichier", id_externe=nom, extension=extension, meta={"fichier": nom}
        )
    except (ErreurLecture, ErreurUtilisateur) as e:
        etat.rapport.ignorees.append(Ignoree(nom=nom, motif=f"fichier corrompu ({e})"))
        return
    etat.rapport.importees += 1


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


def _motif_hostile(info: zipfile.ZipInfo) -> str | None:
    """Le motif de refus d'après les métadonnées de l'entrée, ou `None`.

    Un contrôle **rapide**, sur ce que l'archive annonce — il ne dispense pas
    de `_lire_borne`, qui vérifie ce qui sort vraiment : une métadonnée de
    `.zip` n'engage que celui qui l'a écrite.
    """
    if info.file_size > TAILLE_MAX_FICHIER:
        return f"fichier annoncé à {info.file_size} octets décompressés, au-delà du plafond"
    if info.compress_size > 0 and info.file_size / info.compress_size > RATIO_MAX_DECOMPRESSION:
        ratio = info.file_size / info.compress_size
        return f"taux de décompression suspect ({ratio:.0f}×) — refusé comme une bombe"
    return None


def _lire_borne(zf: zipfile.ZipFile, info: zipfile.ZipInfo, plafond: int) -> bytes:
    """Lit une entrée par blocs, et coupe dès que `plafond` est dépassé.

    C'est ce contrôle-ci, pas `_motif_hostile`, qui protège vraiment contre
    une bombe : il porte sur les octets réellement décompressés, pas sur ce
    que l'en-tête de l'entrée prétend.
    """
    morceaux: list[bytes] = []
    lu = 0
    with zf.open(info) as source:
        while True:
            bloc = source.read(TAILLE_BLOC)
            if not bloc:
                break
            lu += len(bloc)
            if lu > plafond:
                raise ErreurArchiveHostile(f"{info.filename} : décompression au-delà de {plafond} octets")
            morceaux.append(bloc)
    return b"".join(morceaux)


def _degzip_borne(contenu: bytes, plafond: int) -> bytes:
    """Décompresse un `.gz` en mémoire, borné — même règle que `_lire_borne`."""
    morceaux: list[bytes] = []
    lu = 0
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(contenu)) as source:
            while True:
                bloc = source.read(TAILLE_BLOC)
                if not bloc:
                    break
                lu += len(bloc)
                if lu > plafond:
                    raise ErreurArchiveHostile(f"gz : décompression au-delà de {plafond} octets")
                morceaux.append(bloc)
    except OSError as e:  # gzip.BadGzipFile hérite d'OSError
        raise ErreurLecture(f"gz corrompu ({e})") from e
    return b"".join(morceaux)


def _signaler_une_fois(etat: _Etat, cle: str, motif: str) -> None:
    """Ajoute `motif` au rapport une seule fois par `cle` — une bombe ne doit pas
    produire vingt mille lignes identiques."""
    if cle in etat.limites_signalees:
        return
    etat.limites_signalees.add(cle)
    etat.rapport.ignorees.append(Ignoree(nom="(archive)", motif=motif))


__all__ = [
    "EXTENSIONS_ACTIVITE",
    "NOMBRE_MAX_FICHIERS",
    "PROFONDEUR_MAX_ARCHIVE",
    "RATIO_MAX_DECOMPRESSION",
    "TAILLE_MAX_DECOMPRESSEE",
    "TAILLE_MAX_FICHIER",
    "TAILLE_MAX_REQUETE",
    "ErreurArchiveHostile",
    "Ignoree",
    "RapportImport",
    "etat",
    "importer",
]
