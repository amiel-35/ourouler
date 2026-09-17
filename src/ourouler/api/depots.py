"""Où vivent les données, et à qui elles appartiennent.

**Chaque méthode publique de ce module prend un `Proprietaire` en premier
argument positionnel.** Ce n'est pas une convention d'écriture, c'est la
clause de propriétaire de la doctrine §10.2 (« aucune requête sans clause de
propriétaire ») posée pendant qu'elle est gratuite. Un invariant de
`tests/test_invariants.py` le vérifie sur l'arbre syntaxique : le jour où ces
dépôts parleront à PostgreSQL, la signature qui force le `WHERE` sera déjà là.

Deux dépôts, deux natures de données :

- `DepotProfils` — le profil : le **socle** servi par le serveur, plus ce que
  **ce propriétaire-là** a modifié depuis l'interface. Le TOML du mainteneur
  n'est jamais réécrit (voir `enregistrer`).
- `DepotFichiers` — les fichiers produits (GPX, carte) et déposés (`.ZWO`,
  `.MRC`), rangés sous un préfixe par propriétaire et servis par un
  identifiant opaque, jamais par un chemin.

Aucun des deux ne lit l'environnement : ils reçoivent les chemins que
`exploitation.py` a résolus, comme le cœur reçoit sa `Config`.
"""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from ourouler.api.exploitation import construire, ecrire_toml, lire_toml
from ourouler.api.proprietaire import PROPRIETAIRE_LOCAL, Proprietaire
from ourouler.config import Config
from ourouler.erreurs import ErreurConfig, ErreurUtilisateur

#: Ce qu'un propriétaire a le droit de modifier dans son profil, section par
#: section. Liste blanche et non liste noire : un champ inconnu est refusé,
#: pas ignoré — le front doit apprendre son erreur, pas la découvrir en
#: constatant que rien n'a changé.
#:
#: Ce qui n'y est **pas**, et pourquoi : `cache` (exploitation, pas profil),
#: `brouter` (le serveur du mainteneur, pas un réglage de cycliste), `meteo`
#: et les seuils de placement (réglages fins, écran avancé de V2),
#: `historique_depuis` (Q6, il se change en connaissance de cause).
CHAMPS_MODIFIABLES: dict[str, tuple[str, ...]] = {
    "depart": ("nom", "latitude", "longitude"),
    "cycliste": ("masse_kg", "ftp_w"),
    # La position dans la zone, et elle seule : la décision 7 interdit de
    # stocker une valeur en watts à côté d'une table qui bouge.
    "seance": ("position_zone",),
    "intervals": ("athlete_id", "api_key"),
}

#: Les tables qui se remplacent en entier plutôt que champ par champ. Un vélo
#: se supprime, se renomme et se réordonne : fusionner une liste par index
#: donnerait des résultats que personne ne peut prévoir.
LISTES_MODIFIABLES = ("velos",)

#: Le nom du fichier de profil d'un propriétaire, dans son dossier.
NOM_PROFIL = "profil.json"

#: Les extensions de fichier que le dépôt accepte de garder, et leur type de
#: contenu. Fermé : un dépôt de fichiers qui accepte tout est un hébergeur.
EXTENSIONS = {
    ".gpx": "application/gpx+xml",
    ".html": "text/html; charset=utf-8",
    ".zwo": "application/xml",
    ".mrc": "text/plain; charset=utf-8",
}

#: Forme d'un identifiant de fichier : un UUID sans tirets. Vérifiée avant
#: toute construction de chemin — c'est ce qui rend la traversée impossible.
FORME_IDENTIFIANT = re.compile(r"^[0-9a-f]{32}$")


class SocleTOML:
    """Le socle lu dans un fichier TOML, relu à chaque requête.

    **Il appartient à quelqu'un.** Un fichier de configuration porte un point
    de départ, une clé Intervals et un identifiant d'athlète : ce n'est pas
    un réglage de serveur, c'est le profil d'une personne. `proprietaire` dit
    de qui, et `DepotProfils` refuse de le servir à un autre — voir
    `DepotProfils.config`.

    `variables` est **reçu**, jamais lu ici : seul `exploitation.py` sait où
    il tourne (règle absolue 2), et l'invariant adversarial refuse jusqu'au
    nom `environ` dans le cœur. Vide par défaut, pour qu'une application
    construite dans un test n'absorbe pas les variables de la machine.
    """

    modifiable = True

    def __init__(
        self,
        chemin: Path,
        *,
        variables: Mapping[str, str] | None = None,
        proprietaire: Proprietaire | None = PROPRIETAIRE_LOCAL,
    ) -> None:
        self.chemin = chemin
        self.proprietaire = proprietaire
        self._variables = dict(variables or {})

    def config(self, surcharge: dict) -> Config:
        return construire(fusionner(lire_toml(self.chemin), surcharge), environ=self._variables)


class SocleVide:
    """Aucun profil de départ : tout vient de la surcharge du propriétaire.

    C'est le socle d'une application construite sans rien — `creer_application()`.
    Elle publie son contrat (`/openapi.json`, `/docs`) et sert ses routes,
    mais tant que personne n'a écrit de profil, `depuis_dict` refuse la
    configuration (« section [depart] manquante ») et les routes de données
    répondent `configuration_invalide`. C'est volontaire : inventer un point
    de départ par défaut mettrait une coordonnée dans le code (règle absolue 1),
    et aller le chercher sur le disque ferait lire l'environnement à la
    fabrique (règle absolue 2).
    """

    modifiable = True
    proprietaire: Proprietaire | None = None

    def config(self, surcharge: dict) -> Config:
        return construire(dict(surcharge), environ={})


class SocleFixe:
    """Une `Config` déjà construite, injectée par l'appelant.

    Le point d'injection de la règle absolue 3 : un test — et demain la
    couche qui lira le profil dans PostgreSQL — donne une `Config` toute
    faite, sans fichier ni environnement. Lecture seule : il n'y a pas de
    dict TOML sous cette `Config` sur lequel fusionner une surcharge, et
    fabriquer un dict à partir d'une dataclasse validée rendrait un socle qui
    n'est plus celui qu'on a injecté. `enregistrer` refuse donc en le disant.
    """

    modifiable = False
    proprietaire: Proprietaire | None = None

    def __init__(self, config: Config) -> None:
        self._config = config

    def config(self, surcharge: dict) -> Config:
        del surcharge  # aucune ne peut exister : `enregistrer` refuse d'en écrire
        return self._config


class DepotProfils:
    """Le profil de chaque propriétaire, et la `Config` qui en sort.

    Le **socle** porte ce qu'aucun cycliste n'édite (cache, serveur BRouter,
    modèles météo). Le profil d'un propriétaire est une **surcharge** JSON,
    rangée dans son dossier, appliquée par-dessus avant validation.

    **Pourquoi ne pas réécrire le TOML.** Trois raisons, dans l'ordre : le
    fichier du mainteneur porte ses commentaires et ses réglages fins, et un
    service web qui le réécrit les perd ; il n'y a qu'un fichier pour tous
    les propriétaires, donc y écrire ferait fuir le profil de l'un dans celui
    de l'autre dès le lot F3 ; et la surcharge par propriétaire est
    exactement la forme de la table PostgreSQL de demain (doctrine §10.1 :
    « `Config` gagnera un identifiant d'utilisateur et sera chargée depuis la
    base au lieu d'un TOML : le cœur ne le verra pas »).
    """

    def __init__(self, socle: SocleTOML | SocleVide | SocleFixe, dossier_donnees: Path) -> None:
        self._socle = socle
        self._dossier = dossier_donnees

    def dossier(self, proprietaire: Proprietaire) -> Path:
        """Le dossier de ce propriétaire, créé au besoin. La clause, en chemin."""
        chemin = self._dossier / proprietaire.identifiant
        chemin.mkdir(parents=True, exist_ok=True)
        return chemin

    def surcharge(self, proprietaire: Proprietaire) -> dict:
        """Ce que ce propriétaire a modifié, ou un dict vide."""
        chemin = self.dossier(proprietaire) / NOM_PROFIL
        if not chemin.is_file():
            return {}
        try:
            charge = json.loads(chemin.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError) as e:
            raise ErreurConfig(f"{chemin} : profil illisible ({e})") from e
        if not isinstance(charge, dict):
            raise ErreurConfig(f"{chemin} : profil attendu sous forme d'objet")
        return charge

    def config(self, proprietaire: Proprietaire) -> Config:
        """La `Config` de ce propriétaire : le socle, sa surcharge, puis la validation.

        **Un socle qui appartient à quelqu'un ne se sert qu'à lui.** Sans ce
        contrôle, tout ce qu'un propriétaire ne surcharge pas, il en hérite —
        y compris `[intervals] api_key`, `athlete_id` et `[depart]`, c'est-à-dire
        la clé et le domicile du mainteneur. C'était le cas jusqu'au
        17/09/2026, et c'était une fuite silencieuse : la surcharge par
        propriétaire n'a jamais eu pour but de partager les secrets du socle,
        seulement d'éviter de réécrire un TOML commenté.

        Le refus est volontairement **total** plutôt que section par section :
        décider quelles sections d'un TOML sont communes au serveur (cache,
        BRouter, modèles météo) et lesquelles appartiennent au cycliste est un
        arbitrage produit que le mainteneur n'a pas encore rendu — il est posé
        dans `docs/questions_mainteneur.md`. Tant qu'il ne l'est pas, servir
        un socle personnel à quelqu'un d'autre est ce qu'il ne faut pas faire,
        et refuser est ce qui se fait de moins faux.
        """
        possesseur = self._socle.proprietaire
        if possesseur is not None and possesseur != proprietaire:
            raise ErreurConfig(
                f"profil de « {proprietaire} » : le socle de ce serveur est le profil de "
                f"« {possesseur} » (départ, clé Intervals) et ne se partage pas — ce serveur "
                "n'a pas de configuration pour ce propriétaire"
            )
        return self._socle.config(self.surcharge(proprietaire))

    def enregistrer(self, proprietaire: Proprietaire, modifications: dict) -> Config:
        """Applique des modifications au profil, et rend la `Config` qui en résulte.

        Rien n'est écrit tant que la `Config` résultante n'est pas valide :
        une FTP négative ou un vélo sans nom laisse le profil précédent
        intact, et le front reçoit le nom du champ fautif.
        """
        if not self._socle.modifiable:
            raise ErreurUtilisateur(
                "profil : cette application sert une configuration injectée, en lecture seule — "
                "la construire depuis un fichier de configuration pour pouvoir la modifier"
            )
        self.config(proprietaire)  # même contrôle de propriétaire qu'en lecture
        proposee = fusionner(self.surcharge(proprietaire), valider(modifications))
        config = self._socle.config(proposee)  # lève ErreurConfig si invalide
        ecrire_toml(
            self.dossier(proprietaire) / NOM_PROFIL,
            json.dumps(proposee, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        )
        return config


@dataclass(frozen=True)
class Fichier:
    """Un fichier du dépôt : son identifiant opaque, son nom et son chemin."""

    identifiant: str
    nom: str
    chemin: Path
    type_contenu: str

    def json(self) -> dict:
        """Ce que le front reçoit : jamais le chemin sur le disque du serveur."""
        return {
            "id": self.identifiant,
            "nom": self.nom,
            "url": f"/api/v1/fichiers/{self.identifiant}",
        }


class DepotFichiers:
    """Les fichiers d'un propriétaire, adressés par un identifiant opaque.

    Un chemin de disque ne sort jamais d'ici : il dit où le serveur est
    installé, il ne sert à rien au front, et il invite à demander le fichier
    du voisin. L'identifiant, lui, ne dit rien — et le dépôt vérifie qu'il
    appartient bien au propriétaire qui le demande, **côté serveur**
    (doctrine §10.2), en le cherchant dans son dossier et nulle part ailleurs.
    """

    def __init__(self, dossier_donnees: Path) -> None:
        self._dossier = dossier_donnees

    def dossier(self, proprietaire: Proprietaire) -> Path:
        chemin = self._dossier / proprietaire.identifiant / "fichiers"
        chemin.mkdir(parents=True, exist_ok=True)
        return chemin

    def reserver(self, proprietaire: Proprietaire, nom: str) -> Fichier:
        """Un emplacement neuf pour un fichier que le cœur va écrire.

        `nom` sert à nommer le téléchargement côté navigateur ; il ne sert
        jamais à construire le chemin — c'est l'identifiant qui le fait — et
        il est assaini avant d'être gardé (`nom_sur`).
        """
        extension = _extension(nom)
        identifiant = uuid.uuid4().hex
        return Fichier(
            identifiant=identifiant,
            nom=nom_sur(nom),
            chemin=self.dossier(proprietaire) / f"{identifiant}{extension}",
            type_contenu=EXTENSIONS[extension],
        )

    def deposer(self, proprietaire: Proprietaire, nom: str, contenu: bytes) -> Fichier:
        """Range un fichier envoyé par le front (un `.ZWO`, un `.MRC`) et rend sa fiche."""
        fichier = self.reserver(proprietaire, nom)
        fichier.chemin.write_bytes(contenu)
        _ecrire_nom(fichier)
        return fichier

    def enregistrer(self, proprietaire: Proprietaire, fichier: Fichier) -> Fichier:
        """Note le nom d'affichage d'un fichier que le cœur vient d'écrire.

        Vérifie que le fichier est bien dans le dossier de ce propriétaire :
        la clause ne se contente pas d'être dans la signature, elle est
        contrôlée — c'est ce que la doctrine appelle « vérifiée côté serveur ».
        """
        if fichier.chemin.parent != self.dossier(proprietaire):
            raise ErreurUtilisateur(
                f"fichier {fichier.identifiant} : n'appartient pas à ce propriétaire"
            )
        _ecrire_nom(fichier)
        return fichier

    def trouver(self, proprietaire: Proprietaire, identifiant: str) -> Fichier:
        """Le fichier de **ce** propriétaire portant cet identifiant.

        Lève `ErreurUtilisateur` si l'identifiant est mal formé ou si le
        fichier n'est pas dans le dossier de ce propriétaire — les deux cas
        se répondent de la même façon au front, qui n'a pas à apprendre si le
        fichier existe ailleurs.
        """
        if not FORME_IDENTIFIANT.match(identifiant or ""):
            raise ErreurUtilisateur(f"fichier {identifiant!r} : identifiant inconnu")
        dossier = self.dossier(proprietaire)
        for chemin in sorted(dossier.glob(f"{identifiant}.*")):
            if chemin.suffix == ".nom":
                continue
            nom = _lire_nom(chemin) or chemin.name
            return Fichier(
                identifiant=identifiant,
                nom=nom,
                chemin=chemin,
                type_contenu=EXTENSIONS.get(chemin.suffix, "application/octet-stream"),
            )
        raise ErreurUtilisateur(f"fichier {identifiant} : introuvable")


#: Ce qu'un nom d'affichage a le droit de contenir. Tout le reste devient un
#: tiret bas. Fermé parce que ce nom **ressort dans un en-tête HTTP**
#: (`Content-Disposition`) : un guillemet y coupe l'en-tête, un retour chariot
#: en ajoute un autre. Le nom vient du front, donc de n'importe où.
CARACTERES_NOM = re.compile(r"[^A-Za-z0-9 ._-]")

#: Longueur maximale d'un nom d'affichage.
NOM_MAX = 120

#: Quand il ne reste rien du nom proposé.
NOM_PAR_DEFAUT = "fichier"


def nom_sur(nom: str) -> str:
    """Le nom d'affichage, réduit à son dernier segment et à des caractères sûrs."""
    base = str(nom or "").replace("\\", "/").rsplit("/", 1)[-1]
    propre = CARACTERES_NOM.sub("_", base).strip(" .")[:NOM_MAX]
    return propre or NOM_PAR_DEFAUT


def _extension(nom: str) -> str:
    extension = Path(nom).suffix.lower()
    if extension not in EXTENSIONS:
        raise ErreurUtilisateur(
            f"{nom} : extension {extension or 'absente'} refusée — attendu une de "
            f"{', '.join(sorted(EXTENSIONS))}"
        )
    return extension


def _fichier_nom(fichier: Fichier) -> Path:
    return fichier.chemin.with_suffix(".nom")


def _ecrire_nom(fichier: Fichier) -> None:
    """Le nom d'affichage, à côté du fichier. Un index SQLite serait de trop ici."""
    try:
        _fichier_nom(fichier).write_text(fichier.nom, encoding="utf-8")
    except OSError:  # pragma: no cover - le dossier vient d'être créé
        pass


def _lire_nom(chemin: Path) -> str | None:
    try:
        return chemin.with_suffix(".nom").read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def valider(modifications: dict) -> dict:
    """Ne garde que ce qu'un propriétaire a le droit de modifier. Refuse le reste.

    Refuser plutôt qu'ignorer : un champ tu, c'est un front qui croit avoir
    enregistré quelque chose. Le message nomme le champ.
    """
    if not isinstance(modifications, dict):
        raise ErreurUtilisateur("profil : objet attendu")
    propre: dict = {}
    for section, contenu in modifications.items():
        if section in LISTES_MODIFIABLES:
            if not isinstance(contenu, list):
                raise ErreurUtilisateur(f"profil : « {section} » attendu sous forme de liste")
            propre[section] = contenu
            continue
        if section not in CHAMPS_MODIFIABLES:
            raise ErreurUtilisateur(
                f"profil : « {section} » n'est pas modifiable depuis l'interface — "
                f"modifiables : {', '.join(sorted([*CHAMPS_MODIFIABLES, *LISTES_MODIFIABLES]))}"
            )
        if not isinstance(contenu, dict):
            raise ErreurUtilisateur(f"profil : « {section} » attendu sous forme d'objet")
        autorises = CHAMPS_MODIFIABLES[section]
        for champ in contenu:
            if champ not in autorises:
                raise ErreurUtilisateur(
                    f"profil : « {section}.{champ} » n'est pas modifiable — "
                    f"modifiables dans cette section : {', '.join(autorises)}"
                )
        propre[section] = dict(contenu)
    return propre


def fusionner(socle: dict, surcharge: dict) -> dict:
    """Le socle, recouvert par la surcharge. Une section se complète, une liste se remplace.

    Ne mute ni l'un ni l'autre : les deux peuvent être relus ailleurs.
    """
    resultat = dict(socle)
    for cle, valeur in surcharge.items():
        ancien = resultat.get(cle)
        if isinstance(ancien, dict) and isinstance(valeur, dict):
            resultat[cle] = fusionner(ancien, valeur)
        else:
            resultat[cle] = valeur
    return resultat


__all__ = [
    "CHAMPS_MODIFIABLES",
    "EXTENSIONS",
    "LISTES_MODIFIABLES",
    "DepotFichiers",
    "DepotProfils",
    "Fichier",
    "SocleFixe",
    "SocleTOML",
    "SocleVide",
    "fusionner",
    "nom_sur",
    "valider",
]
