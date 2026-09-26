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
import re
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path

from ourouler.activites.lecture import EXTENSIONS, lecteur_pour
from ourouler.noyau.activite import Activite
from ourouler.noyau.erreurs import ErreurLecture, ErreurUtilisateur
from ourouler.noyau.proprietaire import PROPRIETAIRE_LOCAL
from ourouler.noyau.sqlite import colonne_existe, table_existe

NOM_INDEX = "index.sqlite"
NOM_BRUT = "brut"

#: Le sous-dossier de `brut/` où chaque propriétaire **autre que local** range
#: ses fichiers, un dossier par propriétaire (contre-lecture Fable du
#: 25/09/2026). Voir `Cache.__init__`.
NOM_BRUT_COMPTES = "comptes"

#: Ce qu'un propriétaire doit être pour servir tel quel de nom de dossier —
#: la forme des identifiants de compte (`api/proprietaire.FORME_IDENTIFIANT`).
#: Tout autre propriétaire est rangé sous l'empreinte de son nom : jamais un
#: `..` ni un séparateur dans un chemin.
_SEGMENT_SUR = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")

#: Schéma 1 : `identifiant` (sha256 du contenu) était la clé primaire, donc
#: deux activités distinctes partageant un même fichier d'origine (les deux
#: segments d'un triathlon, natation et vélo dans le même FIT) n'avaient
#: qu'une ligne. Schéma 2 : **une ligne par (source, id_externe)**, le
#: fichier brut restant partagé. Schéma 3 : la table gagne une colonne
#: `proprietaire`, qui entre aussi dans l'identité. Voir `_migrer`.
VERSION_SCHEMA = 3

#: Nom de l'index qui porte l'identité d'une activité. Sa présence sert aussi
#: à reconnaître un index déjà passé du schéma 1 au schéma 2.
INDEX_IDENTITE = "idx_activites_identite"

_SCHEMA = f"""
CREATE TABLE IF NOT EXISTS activites (
    proprietaire      TEXT NOT NULL DEFAULT '{PROPRIETAIRE_LOCAL}',
    identifiant       TEXT NOT NULL,
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
    meta              TEXT NOT NULL DEFAULT '{{}}',
    ajoutee_le        TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_activites_debut ON activites(proprietaire, debut);
CREATE INDEX IF NOT EXISTS idx_activites_identifiant
    ON activites(proprietaire, identifiant);
CREATE UNIQUE INDEX IF NOT EXISTS {INDEX_IDENTITE}
    ON activites(proprietaire, source, COALESCE(id_externe, identifiant));
"""

#: Cible du `ON CONFLICT` de `ajouter` : exactement les colonnes de
#: `INDEX_IDENTITE`. Un `id_externe` absent retombe sur le contenu, qui était
#: l'identité du schéma 1 — un même fichier réimporté deux fois sans nom
#: extérieur ne fait toujours qu'une ligne.
#:
#: **Pourquoi `proprietaire` est passé en tête de l'unicité (schéma 3).**
#: `(source, id_externe)` seul supposait qu'un identifiant Intervals ne
#: désigne qu'une activité au monde. C'est faux dès qu'il y a deux
#: utilisateurs : une sortie en groupe, un même compte Intervals rattaché à
#: deux profils, un ménage qui partage un Garmin. Sans le propriétaire dans
#: l'index, le second import ne lèverait même pas d'erreur — le `ON CONFLICT
#: DO UPDATE` ci-dessous **écraserait** la ligne du premier, en silence, avec
#: le vélo et les métadonnées de l'autre. C'est la forme la plus discrète
#: qu'une fuite de données puisse prendre. Avec le propriétaire en tête,
#: chacun garde sa ligne, et la convergence de `--synchroniser` (réimporter
#: la même activité met à jour au lieu d'ajouter) vaut désormais **par
#: propriétaire**, ce qui est ce qu'on voulait dire depuis le début.
_CONFLIT_IDENTITE = "proprietaire, source, COALESCE(id_externe, identifiant)"

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
    """Dossier de cache : `brut/<identifiant>.<extension>` + `index.sqlite`.

    **Les fichiers bruts d'un compte sont à lui** (contre-lecture Fable du
    25/09/2026). Ils étaient rangés par contenu dans un `brut/` commun à tous
    les propriétaires : deux comptes aux octets identiques partageaient le
    même fichier, la suppression de l'un devait vérifier que l'autre ne le
    citait plus, et l'existence du fichier disait, à qui savait regarder,
    qu'un autre compte l'avait déjà déposé. Désormais le propriétaire local
    — la ligne de commande, le cache du mainteneur — garde `brut/` tel quel,
    et tout autre propriétaire a le sien, `brut/comptes/<propriétaire>/`.
    Supprimer un compte n'y touche qu'à ses propres fichiers.
    """

    def __init__(self, dossier: Path, proprietaire: str = PROPRIETAIRE_LOCAL):
        self.dossier = Path(dossier)
        self.proprietaire = _proprietaire_valide(proprietaire)
        #: Le `brut/` commun, celui du propriétaire local — et celui où un
        #: fichier déposé avant le 25/09/2026 par un autre compte se relit encore.
        self.brut_commun = self.dossier / NOM_BRUT
        self.brut = (
            self.brut_commun
            if self.proprietaire == PROPRIETAIRE_LOCAL
            else self.brut_commun / NOM_BRUT_COMPTES / _segment(self.proprietaire)
        )
        self.index = self.dossier / NOM_INDEX
        try:
            self.brut_commun.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise ErreurUtilisateur(f"cache : dossier {self.dossier} inutilisable ({e})") from e
        self.echecs: list[str] = []
        with self._connexion() as cx:
            self._migrer(cx)
            cx.executescript(_SCHEMA)
            cx.execute(f"PRAGMA user_version = {VERSION_SCHEMA}")

    def _migrer(self, cx: sqlite3.Connection) -> None:
        """Amène un index existant au schéma courant. Refuse un schéma plus récent.

        Un index plus récent que le code est refusé : il porte peut-être des
        colonnes qu'on relirait de travers. Un index plus ancien est
        **reconstruit sur place**, sans toucher aux fichiers bruts : c'est le
        même contenu, rangé sous une autre clé.

        `PRAGMA user_version` vaut 0 sur une base tout juste créée comme sur
        un index antérieur au versionnement : c'est la présence de la table,
        de l'index ou de la colonne, jamais le numéro, qui dit s'il reste
        quelque chose à migrer. **Une migration déjà faite ne se refait
        donc pas**, et rouvrir dix fois un cache migré ne le touche pas.

        L'escalier se monte marche par marche : un index du schéma 1 passe par
        2 avant d'arriver à 3.
        """
        version = cx.execute("PRAGMA user_version").fetchone()[0]
        if version > VERSION_SCHEMA:
            raise ErreurUtilisateur(
                f"cache : index {self.index} au schéma {version}, attendu {VERSION_SCHEMA} "
                "— supprimer le fichier index.sqlite le reconstruira (les fichiers "
                "bruts sont conservés)"
            )
        if not table_existe(cx, "activites"):
            return  # base neuve : `_SCHEMA` la crée directement au schéma courant
        if not _index_existe(cx, INDEX_IDENTITE):
            self._migrer_vers_identite(cx)  # 1 → 3, d'un coup : la table est recopiée
        if not colonne_existe(cx, "activites", "proprietaire"):
            self._migrer_vers_proprietaire(cx)  # 2 → 3

    def _migrer_vers_identite(self, cx: sqlite3.Connection) -> None:
        """Schéma 1 → 2 : `identifiant` cesse d'être la clé, `(source, id_externe)` la devient.

        La table du schéma 1 déclare `identifiant TEXT PRIMARY KEY`, et SQLite
        ne sait pas retirer une clé primaire : on recopie dans une table
        neuve. Les colonnes sont les mêmes, seules les contraintes changent.

        La table neuve est déjà celle du schéma 3 (`_SCHEMA` porte
        `proprietaire`) : un index du schéma 1 arrive donc directement au
        schéma courant, la colonne prenant sa valeur par défaut. C'est bien
        un déplacement et pas une réécriture — aucune ligne n'est perdue,
        aucun fichier brut n'est touché.

        Deux lignes du schéma 1 ne peuvent pas entrer en conflit sur
        `(source, id_externe)` par construction — mais un index bricolé à la
        main le pourrait : on garde alors la plus récemment ajoutée plutôt que
        de refuser d'ouvrir le cache.
        """
        colonnes = f"{_COLONNES}, ajoutee_le"
        cx.executescript(
            f"""
            ALTER TABLE activites RENAME TO activites_schema1;
            {_SCHEMA}
            INSERT INTO activites ({colonnes})
                SELECT {colonnes} FROM activites_schema1
                WHERE rowid IN (
                    SELECT MAX(rowid) FROM activites_schema1
                    GROUP BY source, COALESCE(id_externe, identifiant)
                );
            DROP TABLE activites_schema1;
            """
        )

    def _migrer_vers_proprietaire(self, cx: sqlite3.Connection) -> None:
        """Schéma 2 → 3 : la table gagne `proprietaire`, qui entre dans l'unicité.

        Migration **douce** : un `ALTER TABLE … ADD COLUMN` avec un défaut
        constant, donc aucune ligne recopiée, aucune activité perdue, aucun
        fichier brut touché. Toutes les lignes déjà là appartiennent au seul
        utilisateur qui existait, `PROPRIETAIRE_LOCAL`.

        La colonne se range en queue sur un index migré et en tête sur un
        index neuf ; l'ordre physique n'a aucune conséquence — toutes les
        requêtes nomment leurs colonnes — et seul le nom compte.

        Les trois index, eux, doivent être **refaits** : `CREATE INDEX IF NOT
        EXISTS` ne redéfinit pas un index qui existe déjà sous le même nom, et
        celui d'unicité porterait encore l'ancienne clé sans propriétaire. On
        les supprime ici ; `_SCHEMA`, exécuté juste après par `__init__`, les
        recrée à la bonne forme. Tout tient dans un seul script, donc dans une
        seule transaction : il n'existe pas d'état intermédiaire où la colonne
        serait là et l'unicité encore l'ancienne.
        """
        cx.executescript(
            f"""
            ALTER TABLE activites
                ADD COLUMN proprietaire TEXT NOT NULL DEFAULT '{PROPRIETAIRE_LOCAL}';
            DROP INDEX IF EXISTS idx_activites_debut;
            DROP INDEX IF EXISTS idx_activites_identifiant;
            DROP INDEX IF EXISTS {INDEX_IDENTITE};
            {_SCHEMA}
            """
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

        **Une ligne par `(source, id_externe)`, un fichier brut par contenu.**
        Deux activités distinctes peuvent partager le même fichier d'origine —
        Intervals découpe un triathlon en un segment natation et un segment
        vélo qui citent le même FIT : chacune garde sa ligne, et le fichier
        n'est écrit qu'une fois. Réajouter la même `(source, id_externe)` met
        la ligne à jour au lieu d'en créer une seconde, donc `--synchroniser`
        converge : la deuxième passe n'ajoute rien et ne retélécharge rien.

        Sans `id_externe`, l'identité retombe sur le contenu : réimporter deux
        fois les mêmes octets ne fait toujours qu'une entrée.

        Lève `ErreurLecture` si le contenu est illisible — rien n'est écrit.
        """
        extension = extension.lower().lstrip(".")
        activite = lecteur_pour(extension)(contenu)
        identifiant = hashlib.sha256(contenu).hexdigest()
        chemin = self.brut / f"{identifiant}.{extension}"
        if not chemin.exists():
            try:
                self.brut.mkdir(parents=True, exist_ok=True)
                chemin.write_bytes(contenu)
            except OSError as e:
                raise ErreurUtilisateur(f"cache : écriture impossible dans {self.brut} ({e})") from e
        ligne = _ligne(identifiant, source, id_externe, extension, activite, meta or {})
        with self._connexion() as cx:
            cx.execute(
                f"INSERT INTO activites (proprietaire, {_COLONNES}, ajoutee_le) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
                f"ON CONFLICT({_CONFLIT_IDENTITE}) DO UPDATE SET "
                "identifiant=excluded.identifiant, extension=excluded.extension, "
                "debut=excluded.debut, duree_s=excluded.duree_s, "
                "distance_m=excluded.distance_m, puissance_moy_w=excluded.puissance_moy_w, "
                "sport=excluded.sport, appareil=excluded.appareil, "
                "equipement=excluded.equipement, meta=excluded.meta",
                (self.proprietaire, *ligne, datetime.now(UTC).isoformat(timespec="seconds")),
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
        """Réécrit `meta` (et ce qui en dérive) d'une entrée déjà indexée. Vrai si trouvée.

        Sert à enrichir des entrées rapatriées avant qu'on sache quoi en
        retenir (capteur de puissance, identifiant d'équipement) **sans**
        retélécharger le fichier : le fichier brut n'est pas touché, seule la
        ligne d'index change.

        `sport` et `appareil` sont recalculés avec `meta`, parce qu'ils en
        **dérivent** (`_ligne` : les métadonnées de la source priment sur le
        fichier). Les laisser en place réécrivait `meta` sans réécrire les
        colonnes qui la résument : l'index se contredisait lui-même, et une
        ligne héritée d'une collision de contenu — le cas des triathlons du
        schéma 1 — restait classée au sport de l'autre segment pour toujours.
        Une valeur absente de `meta` laisse en place ce qu'on savait déjà,
        plutôt que de l'effacer avec une réponse plus pauvre ; c'est aussi la
        règle pour `equipement`.
        """
        meta = meta or {}
        charge = json.dumps(_serialisable(meta), ensure_ascii=False, default=str)
        with self._connexion() as cx:
            curseur = cx.execute(
                "UPDATE activites SET meta = ?, equipement = COALESCE(?, equipement), "
                "sport = COALESCE(?, sport), appareil = COALESCE(?, appareil) "
                "WHERE proprietaire = ? AND source = ? AND id_externe = ?",
                (
                    charge,
                    equipement or None,
                    meta.get("sport") or None,
                    meta.get("appareil") or None,
                    self.proprietaire,
                    str(source),
                    str(id_externe),
                ),
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
                # Déjà importé : même nom **et** même contenu. Un même contenu
                # sous un autre nom est une autre entrée (l'identité est
                # `(source, id_externe)`) ; un même nom au contenu modifié met
                # l'entrée à jour au lieu d'en créer une seconde.
                if self.contient(source="fichier", id_externe=chemin.name) and (
                    self.contient_identifiant(identifiant)
                ):
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

    def supprimer_tout(self) -> int:
        """Efface toutes les entrées de **ce** propriétaire. Rend le nombre effacé.

        Écrit pour le lot L7.B (export et suppression des données
        personnelles, `docs/journal/sprints/sprint7_contrat.md`). Un fichier du `brut/`
        **commun** peut être cité par plusieurs propriétaires (le local, et
        les comptes qui y ont déposé avant le 25/09/2026) : on ne l'y supprime
        qu'une fois qu'**aucune** ligne, d'aucun propriétaire, ne le cite
        plus. Un fichier du dossier propre à ce propriétaire, lui, n'est cité
        que par lui : il part avec ses lignes.
        """
        with self._connexion() as cx:
            lignes = cx.execute(
                "SELECT identifiant, extension FROM activites WHERE proprietaire = ?",
                (self.proprietaire,),
            ).fetchall()
            cx.execute("DELETE FROM activites WHERE proprietaire = ?", (self.proprietaire,))
            # « Reste-t-il une ligne d'un **autre** propriétaire sur cet
            # identifiant ? » — posée après la suppression ci-dessus, dans la
            # même transaction : un identifiant que ce propriétaire partageait
            # avec lui-même deux fois (schéma 1, contenu identique) ne compte
            # plus, et un identifiant qu'un autre propriétaire référence
            # encore protège son fichier brut. `proprietaire != ?` est un
            # filtre sans effet ici (les lignes de ce propriétaire viennent
            # d'être effacées) mais il dit ce que la requête vérifie vraiment,
            # au lieu d'une lecture non filtrée sur toute la table.
            orphelins = [
                (identifiant, extension)
                for identifiant, extension in lignes
                if cx.execute(
                    "SELECT 1 FROM activites WHERE identifiant = ? AND proprietaire != ? LIMIT 1",
                    (identifiant, self.proprietaire),
                ).fetchone()
                is None
            ]
        for identifiant, extension in orphelins:
            (self.brut_commun / f"{identifiant}.{extension}").unlink(missing_ok=True)
        if self.brut != self.brut_commun:
            for identifiant, extension in lignes:
                (self.brut / f"{identifiant}.{extension}").unlink(missing_ok=True)
            try:
                self.brut.rmdir()
            except OSError:
                pass  # pas vide (un fichier que l'index ne cite pas) ou déjà absent
        return len(lignes)

    # --- lecture --------------------------------------------------------------

    def contient(self, *, source: str, id_externe: str) -> bool:
        with self._connexion() as cx:
            trouve = cx.execute(
                "SELECT 1 FROM activites "
                "WHERE proprietaire = ? AND source = ? AND id_externe = ? LIMIT 1",
                (self.proprietaire, source, str(id_externe)),
            ).fetchone()
        return trouve is not None

    def contient_identifiant(self, identifiant: str) -> bool:
        with self._connexion() as cx:
            trouve = cx.execute(
                "SELECT 1 FROM activites WHERE proprietaire = ? AND identifiant = ? LIMIT 1",
                (self.proprietaire, identifiant),
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
        # Les bornes de date sont facultatives et s'assemblent ; la clause de
        # propriétaire, elle, est **écrite en toutes lettres dans le SQL**
        # ci-dessous. Assemblée comme les autres, elle disparaîtrait du texte
        # de la requête, et l'invariant de `tests/test_invariants.py` ne
        # pourrait plus voir si elle est là — ce qui est exactement le cas
        # qu'il existe pour attraper.
        conditions, parametres = [], [self.proprietaire]
        if depuis is not None:
            conditions.append("substr(debut, 1, 10) >= ?")
            parametres.append(depuis.isoformat())
        if jusqua is not None:
            conditions.append("substr(debut, 1, 10) <= ?")
            parametres.append(jusqua.isoformat())
        bornes = "".join(f" AND {condition}" for condition in conditions)
        with self._connexion() as cx:
            lignes = cx.execute(
                f"SELECT {_COLONNES} FROM activites WHERE proprietaire = ?{bornes} "
                "ORDER BY debut, identifiant, source, id_externe",
                parametres,
            ).fetchall()
        return [self._entree(ligne) for ligne in lignes]

    def chemin(self, identifiant: str) -> Path:
        """Chemin du fichier brut. Lève `KeyError` si l'identifiant est inconnu.

        Le fichier brut est rangé par **contenu** (`brut/<sha256>.<ext>`) :
        deux propriétaires qui possèdent les mêmes octets ne les stockent pas
        deux fois. Ce n'est pas une brèche tant que c'est **l'index** qui
        donne le chemin, et que l'index filtre : un identifiant qui n'est pas
        dans les lignes de ce propriétaire est inconnu, exactement comme s'il
        n'existait pas. En hébergé, les fichiers bruts iront dans un stockage
        d'objets avec un préfixe par utilisateur (doctrine §10.2) et la
        mutualisation disparaîtra d'elle-même.
        """
        with self._connexion() as cx:
            ligne = cx.execute(
                "SELECT extension FROM activites WHERE proprietaire = ? AND identifiant = ?",
                (self.proprietaire, identifiant),
            ).fetchone()
        if ligne is None:
            raise KeyError(identifiant)
        return self._fichier(identifiant, ligne[0])

    def _fichier(self, identifiant: str, extension: str) -> Path:
        """Le fichier brut de ce propriétaire — ou, s'il a été déposé avant le
        25/09/2026, celui du `brut/` commun."""
        propre = self.brut / f"{identifiant}.{extension}"
        if propre.exists() or self.brut == self.brut_commun:
            return propre
        ancien = self.brut_commun / f"{identifiant}.{extension}"
        return ancien if ancien.exists() else propre

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
            chemin=self._fichier(identifiant, extension),
            meta=_json(meta),
            extension=extension,
        )


def _index_existe(cx: sqlite3.Connection, nom: str) -> bool:
    return (
        cx.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'index' AND name = ?", (nom,)
        ).fetchone()
        is not None
    )


def _segment(proprietaire: str) -> str:
    """Le nom de dossier d'un propriétaire : lui-même s'il est sûr, son empreinte sinon."""
    if _SEGMENT_SUR.match(proprietaire):
        return proprietaire
    return hashlib.sha256(proprietaire.encode("utf-8")).hexdigest()[:32]


def _proprietaire_valide(valeur: str) -> str:
    """Un propriétaire est une chaîne non vide. Rien d'autre n'est admis.

    Un `None` ou une chaîne vide se glisserait dans le `WHERE` et n'y
    sélectionnerait rien — une isolation qui « marche » en ne rendant jamais
    de données est la panne la plus difficile à diagnostiquer. On refuse tout
    de suite, à la construction du dépôt.
    """
    if not isinstance(valeur, str) or not valeur.strip():
        raise ErreurUtilisateur(
            f"cache : propriétaire {valeur!r} invalide — une chaîne non vide est attendue"
        )
    return valeur.strip()


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
