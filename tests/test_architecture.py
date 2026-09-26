"""Contrat d'imports : les couches de `docs/ouverture_plan.md` §2, vérifiées sur le code.

Les dépendances ne vont que de haut en bas :

    5 entrées (cli, api, config, commandes) → tout
    4 rendu                                → 0 à 3
    3 cas d'usage (services)               → 0 à 2
    2 adaptateurs (connecteurs, stockage)  → 0 et 1
    1 domaine pur, dans l'ordre physique < meteo < boucle < seance < sortie
                                           → 0 et le domaine placé avant
    0 noyau                                → bibliothèque standard

Le test lit par arbre syntaxique tous les modules de `src/ourouler/` et
leurs imports internes, **imports différés compris** (dans une fonction).
Un import sous `if TYPE_CHECKING:` ne s'exécute jamais : il est permis, mais
listé à part (`IMPORTS_TYPE_CHECKING`), pour qu'il ne serve pas de porte
dérobée sans que ça se voie.

**Mode « constat » (lot 1).** Chaque violation d'aujourd'hui est une
exception datée (`EXCEPTIONS`), rattachée au lot du §6
qui doit la retirer. Le test échoue :
(a) si une violation nouvelle apparaît ;
(b) si une exception ne sert plus : on la retire, la dette ne peut que baisser ;
(c) si une exception a dépassé sa date.

Résumé des exceptions (vérifié par `test_le_resume_dit_vrai`) :

    total : 0 exceptions

Le lot 3 n'en retire aucune : il a déplacé sous `noyau/` des modules que
cette table rangeait déjà au noyau. Le lot 10 retire les treize dernières ;
les lots 11 à 14 travaillent à l'intérieur d'une couche (fonctions longues,
routes de l'API, front).

**Lot 3 fait.** `noyau/` existe : `trace`, `activite`, `erreurs`,
`proprietaire`. Les anciens chemins sont des réexports (`REEXPORTS`), rangés
au noyau eux aussi : chacun n'importe que sa cible, et aucun module de
`src/` ne les importe plus (`scripts/reecrire_imports.py`).

**Lot 4 fait.** `noyau/seance` et `noyau/zones` (réexportés à leurs anciens
chemins), `noyau/meteo` (les types de prévision, que `meteo/openmeteo.py`
réexporte) et `noyau/profil` (le profil du cycliste, que `config.py` compose
et réexporte). Sur ses 21 exceptions, 11 sont tombées ; les 10 qui tiennent à
la `Config` entière sont re-datées aux lots 7, 8 et 10, chacune avec sa
raison.

**Lot 5 fait.** `rendu/` et `services/` existent. `profil_json` et le
masquage des secrets sont dans `rendu/profil.py` (que `config.py` réexporte
pour `en_dict_public` et `MASQUE`) ; `api/vues.py` n'importe plus `cli`, et
les dix exceptions du cycle `api` ↔ `cli` sont tombées. Inviter, lister les
invitations, réinitialiser et retirer sont dans `services/comptes.py`, leur
affichage dans `rendu/comptes.py` ; `api/invitation_commande.py` et
`api/retrait_commande.py` ont disparu. `cli.py` importe encore des modules
de `api/` — le serveur, le dépôt des comptes, le client SMTP, la lecture de
l'environnement de l'hébergé, les dépôts à effacer — pour construire les
dépendances qu'il passe au service : ce sont des arêtes d'une entrée à une
autre, sans cycle, donc permises.

**Lot 6 fait** (pour `sortie` et `boucle` ; `physique/commande.py` attend le
lot 8). Le tableau texte, le JSON, les phrases et la page du jour sont dans
`rendu/sortie.py` et `rendu/boucle.py`, la carte HTML dans `rendu/carte.py`
(`sortie/carte.py` n'en est plus que le réexport, dans `REEXPORTS`). Les
commandes cherchent, mesurent, écrivent les fichiers et appellent le rendu,
qui ne lit ni fichier, ni configuration, ni horloge. L'exception du lot 6
(`sortie.commande` → la carte) est tombée ; mais c'est encore `executer`
qui imprime, donc chaque commande importe son rendu (import différé) : ces
deux arêtes qui montent sont datées au lot 10, quand `cli` appellera le
rendu lui-même.

**Lot 9 fait.** `noyau/ports` porte les protocoles que le domaine reçoit à
la place des clients concrets : `Routeur` (BRouter), `SourcePrevisions`
(Open-Meteo) et `SourceSeances` (Intervals). Le découpage d'un tracé en
mailles passe d'`apprentissage/routes` (un cas d'usage) au domaine
(`boucle/mailles`), que `sortie/contraste` importe désormais. Ses 5
exceptions sont tombées.

**Lot 7 fait.** `stockage/` existe : `stockage/calibrations` lit et écrit
`calibration.json` (réexporté par `physique.commande`). Le choix des
paramètres d'un vélo (`physique/parametres_velo`) et le calcul de l'écran de
FTP (`seance/ftp`) sont du domaine pur : ils reçoivent la calibration lue et
le modèle du vélo. `seance/ecran_ftp` devient la commande qui les prépare
(rangée aux cas d'usage, son import de `config` re-daté au lot 10). Le
connecteur Intervals range les sorties dans un `noyau.ports.DepotActivites`
au lieu d'importer le cache. Ses 3 exceptions sont tombées ; une est re-datée.

**Lot 8 fait.** La physique est pure : `physique/calibration.py` ne fait
plus que calculer (échantillons, ajustement, validation, porte à porte, filtre
des fichiers multisport) sur des activités déjà lues, l'archive déjà obtenue
(`HeureArchive`, passée au noyau dans `noyau/meteo`) et une masse. Choisir et
lire les sorties — index du cache, rattachement aux vélos, archive météo,
`Config` — est le cas d'usage `services/calibrer` (qui n'annote la `Config`
que sous `TYPE_CHECKING`) ; le texte et le JSON des commandes physiques sont
dans `rendu/physique`. Ses 4 exceptions sont tombées ; deux s'ouvrent,
datées au lot 10 : les commandes impriment encore le rendu
(`physique.commande` et `physique.comparer` → `rendu.physique`).
`test_la_physique_pure_n_importe_ni_chemin_ni_reseau_ni_configuration`
tient le §2 : hors `commande.py` et `comparer.py`, `physique/` n'importe ni
`pathlib`, ni `httpx`, ni `config`, ni le cache, ni `boucle`.
`physique/comparer.py`, déjà rangé aux cas d'usage (`MODULES`), rejoint
`services/` au lot 10 (2026-12-31), avec les autres commandes : c'est alors
que `PHYSIQUE_CAS_D_USAGE` se réduit à `commande.py`.

**Lot 10 fait.** argparse est sorti des cas d'usage. Chaque commande a sa
`Demande` (dataclass, dans le module du service) et un service
`executer(demande, contexte, clients…)` qui rend un résultat sans rien
imprimer ; le `services.contexte.Contexte` porte le profil
(`noyau.profil.Profil`, que `Config` satisfait), le dossier de cache et le
fichier de calibration **déjà résolus**, et le canal des avertissements. Le
nouveau paquet d'entrée `commandes/` (couche 5, importé par `cli` et `api`,
n'important ni l'un ni l'autre) lit le `Namespace`, construit la demande et
le contexte depuis la `Config`, appelle le service puis le rendu, et imprime.
L'API passe encore par un `Namespace` et la capture de la sortie standard
(`commandes.executer_depuis_namespace`, appelé par `api/adaptateur.py`) :
c'est le lot 11. `physique/comparer.py` a rejoint `services/comparer.py`
(réexporté) ; le texte et le JSON de `ourouler routes` sont passés dans
`rendu/routes.py`, et `services/calibrer` annote le profil au lieu de la
`Config`. Les 13 exceptions sont tombées.

Les deux cycles principaux qui restent, sur les paquets tels qu'ils sont
rangés aujourd'hui (imports différés compris) — le premier, `api` ↔ `cli`,
est rompu depuis le lot 5 :

1. `config` ↔ `seance` : `config.py` importait le modèle de séance et les
   zones, que `seance/commande.py`, `seance/ecran_ftp.py` et
   `seance/tenue.py` lui rendaient en important `Config`. Depuis le lot 4,
   `config.py` les prend au noyau et `seance/tenue.py` y prend
   `ParametresTenue` ; depuis le lot 7, l'écran de FTP est une commande ;
   depuis le lot 10, plus aucune commande n'importe `config`.
2. `boucle` ↔ `physique` : `physique/modele.py` et `physique/calibration.py`
   importaient `boucle/trace.py`, et `boucle/commande.py` importe
   `physique/modele.py`. Depuis le lot 3, ils importent `noyau/trace.py` ;
   entre dossiers, le cycle ne tient plus que par `physique/commande.py`
   (un cas d'usage) qui importe `boucle/`, et n'est pas une violation.

Ces deux-là appartiennent à une seule composante de huit paquets :
`activites`, `apprentissage`, `boucle`, `config`, `connecteurs`, `meteo`,
`physique` et `seance`. Rangés dans leurs couches cibles, ces cycles
deviennent des arêtes qui montent, listées dans `EXCEPTIONS`.

Le rangement de chaque module est dans `MODULES` : la couche qu'il occupe
**de fait** aujourd'hui, par son rôle, pas par son dossier.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from datetime import date
from functools import cache
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[1]
SOURCES = RACINE / "src" / "ourouler"

# --- les paquets cibles -------------------------------------------------------

#: Paquet cible → (couche, existe déjà sous ce nom dans `src/ourouler/`).
#: Un paquet « à venir » n'a pas encore de dossier : ses modules vivent
#: ailleurs aujourd'hui, et `MODULES` dit lesquels.
PAQUETS: dict[str, tuple[int, bool]] = {
    "noyau": (0, True),
    "physique": (1, True),
    "meteo": (1, True),
    "boucle": (1, True),
    "seance": (1, True),
    "sortie": (1, True),
    "connecteurs": (2, True),
    "stockage": (2, True),
    "services": (3, True),
    "rendu": (4, True),
    "config": (5, True),
    "api": (5, True),
    "cli": (5, True),
    "commandes": (5, True),
}

#: L'ordre du domaine pur : un paquet n'importe que ceux placés avant lui.
ORDRE_DOMAINE = ("physique", "meteo", "boucle", "seance", "sortie")

#: Chaque module de `src/ourouler/`, rangé dans son paquet cible.
#:
#: Choix de rangement, là où le code mêle deux rôles :
#: - les `*/commande.py` sont des **cas d'usage** (couche 3) : ils
#:   orchestrent connecteurs et domaine ; le rendu (lot 6) et argparse
#:   (lot 10) en sont sortis, vers `rendu/` et `commandes/` ;
#: - `physique/calibration.py` est au **domaine** : depuis le lot 8, il ne
#:   fait plus que calculer ; le choix et la lecture des sorties sont dans
#:   `services/calibrer.py` ;
#: - `activites/inventaire.py` et `apprentissage/routes.py` sont des **cas
#:   d'usage** : ils lisent le cache (et BRouter pour les routes) pour rendre
#:   un résultat ; `physique/comparer.py` aussi, devenu `services/comparer.py`
#:   au lot 10 (l'ancien chemin est un réexport) ;
#: - `meteo/openmeteo.py` est un **connecteur** (client HTTP) ; ses types de
#:   prévision sont au noyau depuis le lot 4 (`noyau/meteo.py`) ;
#: - `boucle/gpx.py` est du **stockage** (lecteur et écrivain GPX) ;
#: - la carte HTML est du **rendu** : `rendu/carte.py` depuis le lot 6,
#:   `sortie/carte.py` n'en est plus que le réexport ;
#: - dans `api/`, trois modules ne sont pas des entrées (lot 5) :
#:   `api/comptes.py` est du **stockage** (le dépôt PostgreSQL des comptes),
#:   `api/courriel.py` un **connecteur** (le client SMTP), et
#:   `api/proprietaire.py` un type du **noyau** (bibliothèque standard
#:   seulement) ; c'est ce qui laisse `services/comptes.py` s'en servir ;
#: - `config.py` est une **entrée** (lecture TOML et environnement) : les
#:   dataclasses du profil sont au noyau depuis le lot 4 (`noyau/profil.py`) ;
#:   `Config` et `ParametresCache` y restent.
MODULES: dict[str, str] = {
    # 0. noyau
    "ourouler": "noyau",
    "ourouler.noyau": "noyau",
    "ourouler.noyau.activite": "noyau",
    "ourouler.noyau.erreurs": "noyau",
    "ourouler.noyau.meteo": "noyau",
    "ourouler.noyau.ports": "noyau",
    "ourouler.noyau.profil": "noyau",
    "ourouler.noyau.proprietaire": "noyau",
    "ourouler.noyau.seance": "noyau",
    "ourouler.noyau.trace": "noyau",
    "ourouler.noyau.zones": "noyau",
    "ourouler.activites": "noyau",
    # les réexports temporaires des lots 3 et 4 (`REEXPORTS`), retirés au lot final
    "ourouler.activites.modele": "noyau",
    "ourouler.boucle.trace": "noyau",
    "ourouler.erreurs": "noyau",
    "ourouler.proprietaire": "noyau",
    "ourouler.seance.modele": "noyau",
    "ourouler.seance.zones": "noyau",
    "ourouler.api.proprietaire": "noyau",
    # 1. domaine pur
    "ourouler.physique": "physique",
    "ourouler.physique.modele": "physique",
    "ourouler.physique.litterature": "physique",
    "ourouler.physique.calibration": "physique",
    "ourouler.physique.parametres_velo": "physique",
    "ourouler.meteo": "meteo",
    "ourouler.meteo.couronne": "meteo",
    "ourouler.meteo.rapport": "meteo",
    "ourouler.meteo.portee": "meteo",
    "ourouler.boucle": "boucle",
    "ourouler.boucle.antennes": "boucle",
    "ourouler.boucle.candidates": "boucle",
    "ourouler.boucle.couts": "boucle",
    "ourouler.boucle.geometrie": "boucle",
    "ourouler.boucle.horaire": "boucle",
    "ourouler.boucle.mailles": "boucle",
    "ourouler.boucle.marqueurs": "boucle",
    "ourouler.boucle.meteo_trace": "boucle",
    "ourouler.boucle.tags_importes": "boucle",
    "ourouler.seance": "seance",
    "ourouler.seance.fichier": "seance",
    "ourouler.seance.ftp": "seance",
    "ourouler.seance.intervals": "seance",
    "ourouler.seance.mrc": "seance",
    "ourouler.seance.placement": "seance",
    "ourouler.seance.tenue": "seance",
    "ourouler.seance.terrain": "seance",
    "ourouler.seance.vent": "seance",
    "ourouler.seance.zwo": "seance",
    "ourouler.sortie": "sortie",
    "ourouler.sortie.contraste": "sortie",
    "ourouler.sortie.orientation": "sortie",
    "ourouler.sortie.vent_demande": "sortie",
    # 2. adaptateurs
    "ourouler.connecteurs": "connecteurs",
    "ourouler.connecteurs.brouter": "connecteurs",
    "ourouler.connecteurs.geocodage": "connecteurs",
    "ourouler.connecteurs.intervals": "connecteurs",
    "ourouler.connecteurs.openmeteo_archive": "connecteurs",
    "ourouler.meteo.openmeteo": "connecteurs",
    "ourouler.stockage": "stockage",
    "ourouler.stockage.calibrations": "stockage",
    "ourouler.activites.cache": "stockage",
    "ourouler.activites.import_archive": "stockage",
    "ourouler.activites.lecture": "stockage",
    "ourouler.boucle.gpx": "stockage",
    "ourouler.meteo.cache_previsions": "stockage",
    "ourouler.api.comptes": "stockage",
    "ourouler.api.courriel": "connecteurs",
    # 3. cas d'usage
    "ourouler.services": "services",
    "ourouler.services.calibrer": "services",
    "ourouler.services.comparer": "services",
    "ourouler.services.comptes": "services",
    "ourouler.services.contexte": "services",
    "ourouler.activites.commande": "services",
    "ourouler.activites.inventaire": "services",
    "ourouler.apprentissage": "services",
    "ourouler.apprentissage.commande": "services",
    "ourouler.apprentissage.routes": "services",
    "ourouler.boucle.commande": "services",
    "ourouler.geocodage": "services",
    "ourouler.geocodage.commande": "services",
    "ourouler.meteo.commande": "services",
    "ourouler.physique.commande": "services",
    # le réexport temporaire du lot 10 (`REEXPORTS`), retiré au lot final
    "ourouler.physique.comparer": "services",
    "ourouler.seance.commande": "services",
    "ourouler.seance.ecran_ftp": "services",
    "ourouler.sortie.commande": "services",
    # 4. rendu
    "ourouler.rendu": "rendu",
    "ourouler.rendu.boucle": "rendu",
    "ourouler.rendu.carte": "rendu",
    "ourouler.rendu.carte_dessin": "rendu",
    "ourouler.rendu.carte_jour": "rendu",
    "ourouler.rendu.comparaison": "rendu",
    "ourouler.rendu.comptes": "rendu",
    "ourouler.rendu.physique": "rendu",
    "ourouler.rendu.profil": "rendu",
    "ourouler.rendu.routes": "rendu",
    "ourouler.rendu.sortie": "rendu",
    "ourouler.rendu.sortie_json": "rendu",
    # le réexport temporaire du lot 6 (`REEXPORTS`), retiré au lot final
    "ourouler.sortie.carte": "rendu",
    # 5. entrées
    "ourouler.config": "config",
    "ourouler.cli": "cli",
    # lot 10 : du `Namespace` à la `Demande`, puis au rendu imprimé
    "ourouler.commandes": "commandes",
    "ourouler.commandes.boucle": "commandes",
    "ourouler.commandes.commun": "commandes",
    "ourouler.commandes.comparer": "commandes",
    "ourouler.commandes.geocoder": "commandes",
    "ourouler.commandes.inventaire": "commandes",
    "ourouler.commandes.meteo": "commandes",
    "ourouler.commandes.physique": "commandes",
    "ourouler.commandes.routes": "commandes",
    "ourouler.commandes.seance": "commandes",
    "ourouler.commandes.sortie": "commandes",
    "ourouler.api": "api",
    "ourouler.api.adaptateur": "api",
    "ourouler.api.application": "api",
    "ourouler.api.base_de_donnees": "api",
    "ourouler.api.calibrations": "api",
    "ourouler.api.depots": "api",
    "ourouler.api.erreurs": "api",
    "ourouler.api.exploitation": "api",
    "ourouler.api.garde_avant_corps": "api",
    "ourouler.api.imports_fond": "api",
    "ourouler.api.limite_corps": "api",
    "ourouler.api.modeles": "api",
    "ourouler.api.quotas": "api",
    "ourouler.api.routes": "api",
    "ourouler.api.routes.activites": "api",
    "ourouler.api.routes.calibrations": "api",
    "ourouler.api.routes.commun": "api",
    "ourouler.api.routes.fichiers": "api",
    "ourouler.api.routes.generations": "api",
    "ourouler.api.routes.inventaire": "api",
    "ourouler.api.routes.meteo": "api",
    "ourouler.api.routes.moi": "api",
    "ourouler.api.routes.parcours": "api",
    "ourouler.api.routes.profil": "api",
    "ourouler.api.routes.seances": "api",
    "ourouler.api.routes.sessions": "api",
    "ourouler.api.routes.systeme": "api",
    "ourouler.api.session": "api",
    "ourouler.api.taches_fond": "api",
    "ourouler.api.vie_privee": "api",
    "ourouler.api.vues": "api",
}

# --- la dette, datée ----------------------------------------------------------

#: Échéance par lot du §6 : lots 3–4 en octobre, 5–9 en novembre, 10–14 en
#: décembre 2026.
ECHEANCES = {
    **dict.fromkeys((3, 4), "2026-10-31"),
    **dict.fromkeys((5, 6, 7, 8, 9), "2026-11-30"),
    **dict.fromkeys((10, 11, 12, 13, 14), "2026-12-31"),
}

#: Chaque violation d'aujourd'hui : (importeur, importé, lot qui la retire,
#: échéance). Une ligne par paire de modules, quel que soit le nombre
#: d'instructions `import` qui la portent.
EXCEPTIONS: list[tuple[str, str, str, str]] = [
    # Vide depuis le lot 10. Une violation nouvelle ne s'ajoute pas ici sans
    # un lot du §6 qui la retire, et une date.
]

#: Ancien chemin → module qu'il réexporte (lots 3 et 4 : le noyau ; lot 6 : la
#: carte, au rendu). Un réexport
#: n'importe que sa cible, et plus aucun module de `src/` ne l'importe : un
#: `monkeypatch.setattr` qui le viserait ne remplacerait rien dans le vrai
#: module. `scripts/reecrire_imports.py` a fait suivre imports et cibles de
#: `src/` et `tests/` ; le lot final retire ces modules et cette table.
REEXPORTS: dict[str, str] = {
    "ourouler.activites.modele": "ourouler.noyau.activite",
    "ourouler.boucle.trace": "ourouler.noyau.trace",
    "ourouler.erreurs": "ourouler.noyau.erreurs",
    "ourouler.proprietaire": "ourouler.noyau.proprietaire",
    "ourouler.seance.modele": "ourouler.noyau.seance",
    "ourouler.seance.zones": "ourouler.noyau.zones",
    # lot 6 : la carte HTML, rangée au rendu avec sa cible
    "ourouler.sortie.carte": "ourouler.rendu.carte",
    # lot 10 : la comparaison de deux vélos, un cas d'usage comme sa cible
    "ourouler.physique.comparer": "ourouler.services.comparer",
}

#: Les imports sous `if TYPE_CHECKING:` : permis, mais nommés.
IMPORTS_TYPE_CHECKING: set[tuple[str, str]] = {
    # Les annotations des adaptateurs de comptes : `cli.py` reste importable sans
    # le pilote PostgreSQL, que `services/comptes.py` tire (lot 5).
    ("ourouler.cli", "ourouler.api.comptes"),
    ("ourouler.cli", "ourouler.api.courriel"),
    ("ourouler.cli", "ourouler.services.comptes"),
    # Le rendu du profil annote `Config` sans dépendre, à l'exécution, de
    # l'entrée qui la charge (lot 5) ; celui des parcours de même (lot 6).
    ("ourouler.rendu.profil", "ourouler.config"),
    ("ourouler.rendu.boucle", "ourouler.config"),
    ("ourouler.rendu.sortie", "ourouler.config"),
}


def aujourd_hui() -> date:
    """La date de référence du contrat ; un test la remplace pour vérifier (c)."""
    return date.today()


# --- lecture des imports ------------------------------------------------------


@dataclass(frozen=True)
class Import:
    importeur: str
    importe: str
    genre: str  # "module", "différé" ou "type_checking"
    ligne: int


def _nom_de_module(chemin: Path) -> str:
    parties = list(chemin.relative_to(SOURCES.parent).with_suffix("").parts)
    if parties[-1] == "__init__":
        parties.pop()
    return ".".join(parties)


@cache
def modules_sources() -> dict[str, Path]:
    return {_nom_de_module(p): p for p in sorted(SOURCES.rglob("*.py"))}


def _resoudre(nom: str, connus: dict[str, Path]) -> str | None:
    """Le module interne le plus précis que désigne `nom` (`paquet.module.Objet`)."""
    while nom and nom not in connus:
        nom = nom.rpartition(".")[0]
    return nom or None


def _cibles(noeud: ast.Import | ast.ImportFrom, importeur: str, est_paquet: bool) -> list[str]:
    if isinstance(noeud, ast.Import):
        return [alias.name for alias in noeud.names]
    base = noeud.module or ""
    if noeud.level:
        # Import relatif : on remonte depuis le paquet de l'importeur.
        paquet = importeur if est_paquet else importeur.rpartition(".")[0]
        for _ in range(noeud.level - 1):
            paquet = paquet.rpartition(".")[0]
        base = f"{paquet}.{base}" if base else paquet
    return [f"{base}.{alias.name}" for alias in noeud.names]


def lire_imports(
    source: str, importeur: str, connus: dict[str, Path], est_paquet: bool = False
) -> list[Import]:
    """Les imports internes d'un module, différés et `TYPE_CHECKING` compris."""
    arbre = ast.parse(source)
    sous_type_checking: set[int] = set()
    for noeud in ast.walk(arbre):
        if isinstance(noeud, ast.If) and "TYPE_CHECKING" in ast.unparse(noeud.test):
            for instruction in noeud.body:
                sous_type_checking.update(id(n) for n in ast.walk(instruction))
    au_niveau_module = {id(n) for n in arbre.body}
    trouves = []
    for noeud in ast.walk(arbre):
        if not isinstance(noeud, ast.Import | ast.ImportFrom):
            continue
        if id(noeud) in sous_type_checking:
            genre = "type_checking"
        elif id(noeud) in au_niveau_module:
            genre = "module"
        else:
            genre = "différé"
        for cible in _cibles(noeud, importeur, est_paquet):
            if cible != "ourouler" and not cible.startswith("ourouler."):
                continue
            importe = _resoudre(cible, connus)
            if importe and importe != importeur:
                trouves.append(Import(importeur, importe, genre, noeud.lineno))
    return trouves


@cache
def tous_les_imports() -> tuple[Import, ...]:
    connus = modules_sources()
    resultat: list[Import] = []
    for nom, chemin in connus.items():
        source = chemin.read_text(encoding="utf-8")
        resultat += lire_imports(source, nom, connus, est_paquet=chemin.name == "__init__.py")
    return tuple(resultat)


# --- la règle -----------------------------------------------------------------


def _couche(module: str) -> int:
    return PAQUETS[MODULES[module]][0]


def _motif_de_couche(importeur: str, importe: str) -> str | None:
    """Pourquoi l'arête est interdite par les couches, ou None si elle est permise."""
    pa, pb = MODULES[importeur], MODULES[importe]
    ca, cb = _couche(importeur), _couche(importe)
    if pa == pb or cb < ca:
        return None
    if cb > ca:
        return f"la couche {ca} ({pa}) importe la couche {cb} ({pb})"
    if ca == 1:
        if ORDRE_DOMAINE.index(pb) < ORDRE_DOMAINE.index(pa):
            return None
        return f"le domaine {pa} importe {pb}, placé après lui"
    if ca == 5:
        return None  # les entrées peuvent tout importer, sous réserve des cycles
    return f"couche {ca} : {pa} importe {pb}, un autre paquet de la même couche"


def composantes(aretes: set[tuple[str, str]]) -> list[set[str]]:
    """Composantes fortement connexes d'un petit graphe orienté (Tarjan)."""
    voisins: dict[str, set[str]] = {}
    for a, b in aretes:
        voisins.setdefault(a, set()).add(b)
        voisins.setdefault(b, set())
    index: dict[str, int] = {}
    bas: dict[str, int] = {}
    pile: list[str] = []
    resultat: list[set[str]] = []

    def visiter(v: str) -> None:
        index[v] = bas[v] = len(index)
        pile.append(v)
        for w in sorted(voisins[v]):
            if w not in index:
                visiter(w)
                bas[v] = min(bas[v], bas[w])
            elif w in pile:
                bas[v] = min(bas[v], index[w])
        if bas[v] == index[v]:
            composante = set()
            while True:
                w = pile.pop()
                composante.add(w)
                if w == v:
                    break
            resultat.append(composante)

    for v in sorted(voisins):
        if v not in index:
            visiter(v)
    return resultat


def violations(imports: tuple[Import, ...] | list[Import]) -> dict[tuple[str, str], str]:
    """Chaque arête interdite (importeur, importé) et son motif.

    Un import `TYPE_CHECKING` ne compte pas. Un cycle entre deux paquets de
    couches différentes passe forcément par une arête qui monte, et un cycle
    dans le domaine par une arête contre l'ordre : les deux sont déjà
    interdites. Seul un cycle entre paquets d'une **même** couche hors
    domaine (les entrées, qui peuvent tout importer) demande la règle du
    cycle.
    """
    reelles = {(i.importeur, i.importe) for i in imports if i.genre != "type_checking"}
    interdites = {}
    for a, b in reelles:
        motif = _motif_de_couche(a, b)
        if motif:
            interdites[(a, b)] = motif
    aretes_paquets = {(MODULES[a], MODULES[b]) for a, b in reelles if MODULES[a] != MODULES[b]}
    composante_de = {p: frozenset(c) for c in composantes(aretes_paquets) for p in c}
    for a, b in reelles:
        pa, pb = MODULES[a], MODULES[b]
        if (a, b) in interdites or pa == pb or _couche(a) != _couche(b) or _couche(a) == 1:
            continue
        if composante_de[pa] == composante_de[pb]:
            interdites[(a, b)] = f"cycle entre paquets : {' ↔ '.join(sorted(composante_de[pa]))}"
    return interdites


def confronter(
    constatees: dict[tuple[str, str], str],
    exceptions: list[tuple[str, str, str, str]],
    jour: date,
) -> tuple[list[str], list[str], list[str]]:
    """(nouvelles, inutiles, échues) : les trois façons de faire rougir le contrat."""
    listees = {(a, b) for a, b, _, _ in exceptions}
    nouvelles = [
        f"{a} → {b} : {motif}" for (a, b), motif in sorted(constatees.items()) if (a, b) not in listees
    ]
    inutiles = [f"{a} → {b} ({lot})" for a, b, lot, _ in exceptions if (a, b) not in constatees]
    echues = [
        f"{a} → {b} ({lot}, échéance {echeance})"
        for a, b, lot, echeance in exceptions
        if date.fromisoformat(echeance) < jour
    ]
    return nouvelles, inutiles, echues


# --- les tests ----------------------------------------------------------------


def test_chaque_module_a_sa_place():
    """Un module nouveau doit être rangé ; un module disparu, retiré de la table."""
    presents = set(modules_sources())
    assert presents - MODULES.keys() == set(), "modules à ranger dans MODULES"
    assert MODULES.keys() - presents == set(), "modules disparus, à retirer de MODULES"
    assert set(MODULES.values()) <= PAQUETS.keys()


def test_les_paquets_a_venir_sont_bien_a_venir():
    """Quand un lot crée `noyau/` ou `services/`, la table doit le dire."""
    for nom, (_, existe) in PAQUETS.items():
        if nom in ("config", "cli"):
            assert (SOURCES / f"{nom}.py").exists()
            continue
        assert (SOURCES / nom).is_dir() == existe, f"{nom}/ : « existe={existe} » ne dit plus vrai"


def test_les_imports_type_checking_sont_nommes():
    trouves = {(i.importeur, i.importe) for i in tous_les_imports() if i.genre == "type_checking"}
    assert trouves == IMPORTS_TYPE_CHECKING


def test_aucune_violation_nouvelle():
    nouvelles, _, _ = confronter(violations(tous_les_imports()), EXCEPTIONS, aujourd_hui())
    assert not nouvelles, (
        "import interdit par le contrat de couches (docs/ouverture_plan.md §2) :\n  " + "\n  ".join(nouvelles)
    )


def test_aucune_exception_inutile():
    _, inutiles, _ = confronter(violations(tous_les_imports()), EXCEPTIONS, aujourd_hui())
    assert not inutiles, (
        "exceptions qui ne servent plus : retirez-les d'EXCEPTIONS, la dette ne remonte pas :\n  "
        + "\n  ".join(inutiles)
    )


def test_aucune_exception_echue():
    _, _, echues = confronter(violations(tous_les_imports()), EXCEPTIONS, aujourd_hui())
    assert not echues, "exceptions échues : le lot qui devait les retirer est en retard :\n  " + "\n  ".join(
        echues
    )


def test_un_reexport_n_importe_que_sa_cible():
    for ancien, cible in REEXPORTS.items():
        assert MODULES[ancien] == MODULES[cible]
        importes = {i.importe for i in tous_les_imports() if i.importeur == ancien}
        assert importes == {cible}, ancien


def test_personne_n_importe_un_reexport():
    """Le code importe le noyau directement : les réexports ne servent qu'aux appelants du dehors."""
    fautifs = [
        f"{i.importeur}:{i.ligne} → {i.importe}"
        for i in tous_les_imports()
        if i.importe in REEXPORTS and i.importeur not in REEXPORTS
    ]
    assert not fautifs, "importer depuis ourouler.noyau :\n  " + "\n  ".join(fautifs)


#: `docs/ouverture_plan.md` §2 : « Le modèle physique pur […] n'importe ni
#: `Config`, ni cache, ni `Path`, ni `httpx`, ni `boucle` ; numpy est permis. »
#: Préfixes interdits, bibliothèque standard et tierces comprises.
INTERDITS_PHYSIQUE_PURE = (
    "pathlib",
    "httpx",
    "ourouler.config",
    "ourouler.activites.cache",
    "ourouler.boucle",
)

#: Le module de `physique/` qui n'est pas du domaine : un cas d'usage
#: (`MODULES`) qui lit le cache et les fichiers. `physique/comparer.py` n'est
#: plus qu'un réexport de `services/comparer.py` (lot 10), vérifié comme pur.
PHYSIQUE_CAS_D_USAGE = ("ourouler.physique.commande",)


def _modules_importes(source: str) -> list[tuple[str, int]]:
    """Tous les modules importés (absolus), différés et `TYPE_CHECKING` compris."""
    trouves = []
    for noeud in ast.walk(ast.parse(source)):
        if isinstance(noeud, ast.Import):
            trouves += [(alias.name, noeud.lineno) for alias in noeud.names]
        elif isinstance(noeud, ast.ImportFrom) and noeud.module and not noeud.level:
            trouves.append((noeud.module, noeud.lineno))
            trouves += [(f"{noeud.module}.{alias.name}", noeud.lineno) for alias in noeud.names]
    return trouves


def test_la_physique_pure_n_importe_ni_chemin_ni_reseau_ni_configuration():
    fautifs = []
    pures = [
        nom
        for nom in modules_sources()
        if (nom == "ourouler.physique" or nom.startswith("ourouler.physique."))
        and nom not in PHYSIQUE_CAS_D_USAGE
    ]
    assert "ourouler.physique.calibration" in pures and "ourouler.physique.modele" in pures
    for nom in pures:
        source = modules_sources()[nom].read_text(encoding="utf-8")
        for importe, ligne in _modules_importes(source):
            for interdit in INTERDITS_PHYSIQUE_PURE:
                if importe == interdit or importe.startswith(interdit + "."):
                    fautifs.append(f"{nom}:{ligne} importe {importe}")
    assert not fautifs, "la physique pure (§2) importe :\n  " + "\n  ".join(sorted(set(fautifs)))


def test_la_verification_de_la_physique_pure_voit_un_import_differe():
    source = "def f():\n    from pathlib import Path\n    import httpx\n"
    assert {m for m, _ in _modules_importes(source)} >= {"pathlib", "httpx"}


def test_les_exceptions_sont_bien_formees():
    paires = [(a, b) for a, b, _, _ in EXCEPTIONS]
    assert len(paires) == len(set(paires)), "une paire listée deux fois"
    for a, b, lot, echeance in EXCEPTIONS:
        assert a in MODULES and b in MODULES, (a, b)
        numero = re.fullmatch(r"lot (\d+)", lot)
        assert numero and int(numero[1]) in ECHEANCES, lot
        assert echeance == ECHEANCES[int(numero[1])], (a, b, lot, echeance)


def test_le_resume_dit_vrai():
    """Le résumé en tête du fichier suit la liste : il ne ment pas longtemps."""
    par_lot: dict[str, int] = {}
    for _, _, lot, _ in EXCEPTIONS:
        par_lot[lot] = par_lot.get(lot, 0) + 1
    ecrit = dict(re.findall(r"^\s+(lot \d+) : (\d+) exceptions?,", __doc__, re.MULTILINE))
    assert {lot: int(n) for lot, n in ecrit.items()} == par_lot
    total = re.search(r"total : (\d+) exceptions", __doc__)
    assert total and int(total[1]) == len(EXCEPTIONS)


# --- le contrat se vérifie lui-même -------------------------------------------

_CONNUS = {nom: Path() for nom in ("ourouler.boucle.trace", "ourouler.cli", "ourouler.physique.modele")}


def test_un_import_differe_est_vu():
    source = "def f():\n    from ourouler.cli import profil_json\n"
    (imp,) = lire_imports(source, "ourouler.physique.modele", _CONNUS)
    assert (imp.importe, imp.genre) == ("ourouler.cli", "différé")


def test_un_import_type_checking_est_mis_a_part():
    source = "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    from ourouler.cli import X\n"
    (imp,) = lire_imports(source, "ourouler.physique.modele", _CONNUS)
    assert imp.genre == "type_checking"
    assert violations([imp]) == {}


def test_un_objet_importe_se_ramene_a_son_module():
    source = "from ourouler.boucle import trace\nfrom ourouler.boucle.trace import Trace\n"
    importes = {i.importe for i in lire_imports(source, "ourouler.physique.modele", _CONNUS)}
    assert importes == {"ourouler.boucle.trace"}


def test_une_arete_montante_est_interdite():
    imp = Import("ourouler.physique.modele", "ourouler.cli", "différé", 1)
    assert list(violations([imp])) == [("ourouler.physique.modele", "ourouler.cli")]


def test_le_domaine_n_importe_pas_un_domaine_place_apres_lui():
    avant = Import("ourouler.sortie.orientation", "ourouler.physique.modele", "module", 1)
    apres = Import("ourouler.physique.modele", "ourouler.sortie.orientation", "module", 1)
    assert violations([avant]) == {}
    motif = violations([apres])[("ourouler.physique.modele", "ourouler.sortie.orientation")]
    assert "placé après lui" in motif


def test_un_cycle_entre_entrees_est_interdit():
    aller = Import("ourouler.cli", "ourouler.api.vues", "différé", 1)
    retour = Import("ourouler.api.vues", "ourouler.cli", "différé", 1)
    assert violations([aller]) == {}
    assert set(violations([aller, retour])) == {
        ("ourouler.cli", "ourouler.api.vues"),
        ("ourouler.api.vues", "ourouler.cli"),
    }


@pytest.mark.parametrize(("jour", "attendu"), [(date(2026, 10, 31), 0), (date(2026, 11, 1), 1)])
def test_une_exception_echue_rougit(jour, attendu):
    exceptions = [("a", "b", "lot 4", "2026-10-31")]
    _, _, echues = confronter({("a", "b"): "motif"}, exceptions, jour)
    assert len(echues) == attendu
