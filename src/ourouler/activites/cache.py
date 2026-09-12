"""Cache local : les fichiers bruts tels que reçus + un index SQLite.

Le dénominateur commun est le fichier (doctrine §5) : quelle que soit la
source, on garde le FIT/GPX/TCX d'origine sous `<dossier>/brut/` et on le
relit toujours avec le même lecteur. L'index n'existe que pour retrouver une
activité par date, vélo ou source sans tout relire.

Ce module reçoit un `Path` déjà résolu : il ne lit ni la configuration, ni
l'environnement, ni `~`.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path

from ourouler.activites.lecture import EXTENSIONS, lecteur_pour
from ourouler.activites.modele import Activite
from ourouler.erreurs import ErreurLecture, ErreurUtilisateur

NOM_INDEX = "index.sqlite"
NOM_BRUT = "brut"
VERSION_SCHEMA = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS activites (
    identifiant       TEXT PRIMARY KEY,
    source            TEXT NOT NULL,
    id_externe        TEXT,
    extension         TEXT NOT NULL,
    debut             TEXT,
    duree_s           REAL,
    distance_m        REAL,
    puissance_moy_w   REAL,
    sport             TEXT,
    appareil          TEXT,
    equipement        TEXT,
    meta              TEXT NOT NULL DEFAULT '{}',
    ajoutee_le        TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_activites_debut ON activites(debut);
CREATE INDEX IF NOT EXISTS idx_activites_source ON activites(source, id_externe);
"""

_COLONNES = (
    "identifiant, source, id_externe, extension, debut, duree_s, distance_m, "
    "puissance_moy_w, sport, appareil, equipement, meta"
)


@dataclass
class EntreeCache:
    """Une ligne de l'index : de quoi inventorier sans relire le fichier brut."""

    identifiant: str
    source: str  # "intervals" | "fichier" | …
    id_externe: str | None
    debut: datetime | None  # UTC
    duree_s: float | None
    distance_m: float | None
    puissance_moy_w: float | None
    sport: str | None
    appareil: str | None
    equipement: str | None  # nom du vélo côté source, s'il existe
    chemin: Path
    meta: dict = field(default_factory=dict)
    extension: str = ""

    @property
    def jour(self) -> date | None:
        return self.debut.date() if self.debut else None


class Cache:
    """Dossier de cache : `brut/<identifiant>.<extension>` + `index.sqlite`."""

    def __init__(self, dossier: Path):
        self.dossier = Path(dossier)
        self.brut = self.dossier / NOM_BRUT
        self.index = self.dossier / NOM_INDEX
        try:
            self.brut.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise ErreurUtilisateur(f"cache : dossier {self.dossier} inutilisable ({e})") from e
        self.echecs: list[str] = []
        index_existant = self.index.is_file()
        with self._connexion() as cx:
            if index_existant:
                self._verifier_version(cx)
            cx.executescript(_SCHEMA)
            cx.execute(f"PRAGMA user_version = {VERSION_SCHEMA}")

    def _verifier_version(self, cx: sqlite3.Connection) -> None:
        """Refuse d'ouvrir un index d'un schéma plus ancien ou plus récent.

        `PRAGMA user_version` était écrit sans jamais être relu : au schéma 2,
        un index v1 aurait été relu comme s'il était à jour, avec des colonnes
        manquantes et des lectures fausses. Le cache est reconstructible
        (fichiers bruts + réimport), donc le message dit quoi faire plutôt que
        de tenter une migration qui n'existe pas encore.
        """
        version = cx.execute("PRAGMA user_version").fetchone()[0]
        if version == VERSION_SCHEMA:
            return
        if version == 0:
            # Index antérieur au versionnement, ou base tout juste créée par
            # une connexion précédente : le schéma est posé en `CREATE IF NOT
            # EXISTS`, laisser faire.
            return
        raise ErreurUtilisateur(
            f"cache : index {self.index} au schéma {version}, attendu {VERSION_SCHEMA} "
            "— supprimer le fichier index.sqlite le reconstruira (les fichiers "
            "bruts sont conservés)"
        )

    # --- écriture -------------------------------------------------------------

    def ajouter(
        self,
        contenu: bytes,
        *,
        source: str,
        id_externe: str | None,
        extension: str,
        meta: dict,
    ) -> str:
        """Relit le contenu, l'archive et l'indexe. Renvoie l'identifiant (sha256).

        Idempotent : ajouter deux fois le même contenu ne crée qu'une entrée.
        Lève `ErreurLecture` si le contenu est illisible — rien n'est écrit.
        """
        extension = extension.lower().lstrip(".")
        activite = lecteur_pour(extension)(contenu)
        identifiant = hashlib.sha256(contenu).hexdigest()
        chemin = self.brut / f"{identifiant}.{extension}"
        if not chemin.exists():
            try:
                chemin.write_bytes(contenu)
            except OSError as e:
                raise ErreurUtilisateur(f"cache : écriture impossible dans {self.brut} ({e})") from e
        ligne = _ligne(identifiant, source, id_externe, extension, activite, meta or {})
        with self._connexion() as cx:
            cx.execute(
                f"INSERT INTO activites ({_COLONNES}, ajoutee_le) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(identifiant) DO UPDATE SET "
                "source=excluded.source, id_externe=excluded.id_externe, "
                "equipement=excluded.equipement, meta=excluded.meta",
                (*ligne, datetime.now(UTC).isoformat(timespec="seconds")),
            )
        return identifiant

    def mettre_a_jour_meta(
        self,
        *,
        source: str,
        id_externe: str,
        meta: dict,
        equipement: str | None = None,
    ) -> bool:
        """Réécrit `meta` (et `equipement`) d'une entrée déjà indexée. Vrai si trouvée.

        Sert à enrichir des entrées rapatriées avant qu'on sache quoi en
        retenir (capteur de puissance, identifiant d'équipement) **sans**
        retélécharger le fichier : le fichier brut n'est pas touché, seule la
        ligne d'index change. `equipement` à `None` laisse en place ce qu'on
        savait déjà, plutôt que de l'effacer avec une réponse plus pauvre.
        """
        charge = json.dumps(_serialisable(meta or {}), ensure_ascii=False, default=str)
        with self._connexion() as cx:
            curseur = cx.execute(
                "UPDATE activites SET meta = ?, equipement = COALESCE(?, equipement) "
                "WHERE source = ? AND id_externe = ?",
                (charge, equipement or None, str(source), str(id_externe)),
            )
            modifiees = curseur.rowcount
        return modifiees > 0

    def indexer_dossier(self, dossier: Path) -> int:
        """Importe tous les .fit/.gpx/.tcx d'un dossier. Renvoie le nombre ajoutés.

        Les fichiers illisibles sont comptés dans `self.echecs` et ignorés :
        un seul fichier abîmé ne doit pas faire échouer tout un import. Cela
        vaut pour le **contenu** illisible comme pour le **fichier** illisible
        (droits, lien cassé, disparu entre le parcours et la lecture) : la
        lecture des octets est donc dans le `try`, et `OSError` compté comme
        une `ErreurLecture`. Jamais de trace : un import n'a pas à se
        terminer en code 1 parce qu'un fichier du dossier est en mode 000.
        """
        dossier = Path(dossier)
        if not dossier.is_dir():
            raise ErreurUtilisateur(f"dossier à importer introuvable : {dossier}")
        self.echecs = []
        ajoutes = 0
        for chemin in sorted(dossier.rglob("*")):
            if not chemin.is_file() or chemin.suffix.lower().lstrip(".") not in EXTENSIONS:
                continue
            try:
                contenu = chemin.read_bytes()
                identifiant = hashlib.sha256(contenu).hexdigest()
                if self.contient_identifiant(identifiant):
                    continue
                self.ajouter(
                    contenu,
                    source="fichier",
                    id_externe=chemin.name,
                    extension=chemin.suffix,
                    meta={"fichier": chemin.name},
                )
            except (ErreurLecture, ErreurUtilisateur, OSError) as e:
                # Le lecteur a reçu des octets : il ne connaît pas le nom du
                # fichier, on le remplace par celui qu'on a sous la main.
                self.echecs.append(f"{chemin.name} : {str(e).removeprefix('<octets> : ')}")
                continue
            ajoutes += 1
        return ajoutes

    # --- lecture --------------------------------------------------------------

    def contient(self, *, source: str, id_externe: str) -> bool:
        with self._connexion() as cx:
            trouve = cx.execute(
                "SELECT 1 FROM activites WHERE source = ? AND id_externe = ? LIMIT 1",
                (source, str(id_externe)),
            ).fetchone()
        return trouve is not None

    def contient_identifiant(self, identifiant: str) -> bool:
        with self._connexion() as cx:
            trouve = cx.execute(
                "SELECT 1 FROM activites WHERE identifiant = ? LIMIT 1", (identifiant,)
            ).fetchone()
        return trouve is not None

    def lister(self, depuis: date | None = None, jusqua: date | None = None) -> list[EntreeCache]:
        """Entrées dont le jour de début est dans l'intervalle, triées par date.

        Les bornes acceptent une `date`, un `datetime` (ramené à sa date) ou une
        chaîne ISO ; tout autre type est une erreur utilisateur. Des bornes
        inversées ne sont pas une erreur : l'intervalle est vide, on renvoie [].
        """
        depuis = _borne_en_date(depuis, "depuis")
        jusqua = _borne_en_date(jusqua, "jusqua")
        conditions, parametres = [], []
        if depuis is not None:
            conditions.append("substr(debut, 1, 10) >= ?")
            parametres.append(depuis.isoformat())
        if jusqua is not None:
            conditions.append("substr(debut, 1, 10) <= ?")
            parametres.append(jusqua.isoformat())
        ou = (" WHERE " + " AND ".join(conditions)) if conditions else ""
        with self._connexion() as cx:
            lignes = cx.execute(
                f"SELECT {_COLONNES} FROM activites{ou} ORDER BY debut, identifiant", parametres
            ).fetchall()
        return [self._entree(ligne) for ligne in lignes]

    def chemin(self, identifiant: str) -> Path:
        """Chemin du fichier brut. Lève `KeyError` si l'identifiant est inconnu."""
        with self._connexion() as cx:
            ligne = cx.execute(
                "SELECT extension FROM activites WHERE identifiant = ?", (identifiant,)
            ).fetchone()
        if ligne is None:
            raise KeyError(identifiant)
        return self.brut / f"{identifiant}.{ligne[0]}"

    def relire(self, identifiant: str) -> Activite:
        """Relit l'activité complète (tous ses points) depuis le fichier brut."""
        chemin = self.chemin(identifiant)
        return lecteur_pour(chemin.suffix)(chemin)

    # --- interne --------------------------------------------------------------

    @contextmanager
    def _connexion(self) -> Iterator[sqlite3.Connection]:
        """Connexion SQLite le temps d'une opération, erreurs traduites."""
        try:
            cx = sqlite3.connect(self.index)
        except sqlite3.Error as e:
            raise ErreurUtilisateur(f"cache : index {self.index} inutilisable ({e})") from e
        try:
            yield cx
            cx.commit()
        except sqlite3.Error as e:
            cx.rollback()
            raise ErreurUtilisateur(
                f"cache : index {self.index} illisible ou corrompu ({e}) — "
                "le supprimer le reconstruira depuis les fichiers bruts"
            ) from e
        finally:
            cx.close()

    def _entree(self, ligne: tuple) -> EntreeCache:
        (
            identifiant,
            source,
            id_externe,
            extension,
            debut,
            duree_s,
            distance_m,
            puissance_moy_w,
            sport,
            appareil,
            equipement,
            meta,
        ) = ligne
        return EntreeCache(
            identifiant=identifiant,
            source=source,
            id_externe=id_externe,
            debut=_instant(debut),
            duree_s=duree_s,
            distance_m=distance_m,
            puissance_moy_w=puissance_moy_w,
            sport=sport,
            appareil=appareil,
            equipement=equipement,
            chemin=self.brut / f"{identifiant}.{extension}",
            meta=_json(meta),
            extension=extension,
        )


def _ligne(
    identifiant: str,
    source: str,
    id_externe: str | None,
    extension: str,
    activite: Activite,
    meta: dict,
) -> tuple:
    """Une ligne d'index. Les métadonnées de la source priment sur le fichier
    pour le sport, l'appareil et l'équipement (Intervals sait ce que le FIT
    ignore) ; les mesures (durée, distance, puissance) viennent du fichier."""
    return (
        identifiant,
        source,
        None if id_externe is None else str(id_externe),
        extension,
        activite.debut.isoformat() if activite.debut else None,
        activite.duree_s,
        activite.distance_m,
        activite.puissance_moy_w if activite.puissance_moy_w is not None else meta.get("puissance_moy_w"),
        meta.get("sport") or activite.sport,
        meta.get("appareil") or activite.appareil,
        meta.get("equipement") or None,
        json.dumps(_serialisable(meta), ensure_ascii=False, default=str),
    )


def _serialisable(meta: dict) -> dict:
    return {k: v for k, v in meta.items() if v is not None}


def _instant(texte: str | None) -> datetime | None:
    if not texte:
        return None
    try:
        t = datetime.fromisoformat(texte)
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=UTC)


def _json(texte: str | None) -> dict:
    if not texte:
        return {}
    try:
        charge = json.loads(texte)
    except json.JSONDecodeError:
        return {}
    return charge if isinstance(charge, dict) else {}


def _borne_en_date(valeur: object, nom: str) -> date | None:
    """Normalise une borne de `lister` en `date`, ou lève une erreur utilisateur.

    Accepté : `None`, `date`, `datetime` (ramené à sa date), chaîne ISO
    (`AAAA-MM-JJ` ou datetime ISO complet). Refusé : tout le reste, y compris
    les booléens et les nombres, pour lesquels une conversion silencieuse
    serait un piège.
    """
    if valeur is None:
        return None
    if isinstance(valeur, datetime):
        return valeur.date()
    if isinstance(valeur, date):
        return valeur
    if isinstance(valeur, str):
        texte = valeur.strip()
        try:
            return datetime.fromisoformat(texte).date() if len(texte) > 10 else date.fromisoformat(texte)
        except ValueError as e:
            raise ErreurUtilisateur(
                f"cache : borne {nom} = {valeur!r} n'est pas une date ISO (AAAA-MM-JJ)"
            ) from e
    raise ErreurUtilisateur(
        f"cache : borne {nom} de type {type(valeur).__name__} — date, datetime ou chaîne ISO attendue"
    )
