"""Règle d'imports : les couches d'`ARCHITECTURE.md`, vérifiées sur le code.

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

**Les exceptions.** Une arête qui monte ne s'accepte que datée, dans
`EXCEPTIONS`, avec le changement qui doit la retirer. Le test échoue :
(a) si une violation nouvelle apparaît ;
(b) si une exception ne sert plus : on la retire, la dette ne peut que baisser ;
(c) si une exception a dépassé sa date.

Résumé des exceptions (vérifié par `test_le_resume_dit_vrai`) :

    total : 0 exceptions

**Ce que les couches imposent, en clair.**

* `noyau/` ne porte que des types et des protocoles (`noyau/ports` :
  `Routeur`, `SourcePrevisions`, `SourceSeances`, `DepotActivites`) : le
  domaine reçoit ces protocoles à la place des clients concrets.
* Le rendu (tableau texte, JSON, phrases, page du jour, carte HTML) vit dans
  `rendu/` et ne lit ni fichier, ni configuration, ni horloge.
* Chaque commande a sa `Demande` et un service `executer(demande, contexte,
  clients…)` qui rend un résultat sans rien imprimer ; le
  `services.contexte.Contexte` porte le profil, le dossier de cache et le
  fichier de calibration **déjà résolus**. Le paquet d'entrée `commandes/`
  lit le `Namespace`, construit la demande, appelle le service puis le rendu,
  et imprime.
* La physique est pure : `physique/` n'importe ni
  `pathlib`, ni `httpx`, ni `config`, ni le cache, ni `boucle`
  (`test_la_physique_pure_n_importe_ni_chemin_ni_reseau_ni_configuration`).
* `cli/` importe des modules de `api/` (serveur, dépôt des comptes, client
  SMTP, environnement de l'hébergé) pour construire les dépendances qu'il passe
  aux services : ce sont des arêtes d'une entrée à une autre, sans cycle, donc
  permises.

Deux cycles ont longtemps lié plusieurs paquets en une seule composante —
`config` ↔ `seance` (le modèle de séance et les zones) et `boucle` ↔ `physique`
(le tracé) ; rangés dans leurs couches, ils sont devenus des arêtes qui
descendent. Une arête qui monterait encore serait listée dans `EXCEPTIONS`.

Le rangement de chaque module est dans `MODULES` : la couche qu'il occupe
**de fait**, par son rôle, pas par son dossier. Aucun module de réexport ne
subsiste (`REEXPORTS` est vide) : tout import passe par sa cible.
`config.Velo`/`Depart`/… restent un alias public délibéré.
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
#: - les `services/<domaine>.py` (`sortie`, `boucle`, `physique`…) sont des
#:   **cas d'usage** (couche 3) : ils orchestrent connecteurs et domaine ; le
#:   rendu et argparse en sont sortis, vers `rendu/` et `commandes/` ;
#: - `physique/calibration.py` est au **domaine** : il ne fait que
#:   calculer ; le choix et la lecture des sorties sont dans
#:   `services/calibrer.py` ;
#: - `activites/inventaire.py` et `apprentissage/routes.py` sont des **cas
#:   d'usage** : ils lisent le cache (et BRouter pour les routes) pour rendre
#:   un résultat ; la comparaison physique aussi, dans `services/comparer.py` ;
#: - `meteo/openmeteo.py` est un **connecteur** (client HTTP) ; ses types de
#:   prévision sont au noyau (`noyau/meteo.py`) ;
#: - `boucle/gpx.py` est du **stockage** (lecteur et écrivain GPX) ;
#: - la carte HTML est du **rendu** : `rendu/carte.py` ;
#: - dans `api/`, trois modules ne sont pas des entrées :
#:   `api/comptes.py` est du **stockage** (le dépôt PostgreSQL des comptes),
#:   `api/courriel.py` un **connecteur** (le client SMTP), et
#:   `api/proprietaire.py` un type du **noyau** (bibliothèque standard
#:   seulement) ; c'est ce qui laisse `services/comptes.py` s'en servir ;
#: - `config.py` est une **entrée** (lecture TOML et environnement) : les
#:   dataclasses du profil sont au noyau (`noyau/profil.py`) ;
#:   `Config` et `ParametresCache` y restent.
MODULES: dict[str, str] = {
    # 0. noyau
    "ourouler": "noyau",
    "ourouler.noyau": "noyau",
    "ourouler.noyau.activite": "noyau",
    "ourouler.noyau.erreurs": "noyau",
    "ourouler.noyau.lecture": "noyau",
    "ourouler.noyau.meteo": "noyau",
    "ourouler.noyau.ports": "noyau",
    "ourouler.noyau.profil": "noyau",
    "ourouler.noyau.proprietaire": "noyau",
    "ourouler.noyau.seance": "noyau",
    "ourouler.noyau.sqlite": "noyau",
    "ourouler.noyau.texte": "noyau",
    "ourouler.noyau.trace": "noyau",
    "ourouler.noyau.zones": "noyau",
    "ourouler.activites": "noyau",
    "ourouler.api.proprietaire": "noyau",
    # 1. domaine pur
    "ourouler.physique": "physique",
    "ourouler.physique.modele": "physique",
    "ourouler.physique.litterature": "physique",
    "ourouler.physique.calibration": "physique",
    "ourouler.physique.echantillonnage": "physique",
    "ourouler.physique.groupe": "physique",
    "ourouler.physique.validation": "physique",
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
    "ourouler.seance.lecture_commune": "seance",
    "ourouler.seance.mrc": "seance",
    "ourouler.seance.placement": "seance",
    "ourouler.seance.pas_trace": "seance",
    "ourouler.seance.placement_resultat": "seance",
    "ourouler.seance.placement_note": "seance",
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
    "ourouler.services.activites": "services",
    "ourouler.services.apprentissage": "services",
    "ourouler.services.boucle": "services",
    "ourouler.services.geocodage": "services",
    "ourouler.services.meteo": "services",
    "ourouler.services.physique": "services",
    "ourouler.services.seance": "services",
    "ourouler.services.sortie": "services",
    "ourouler.activites.inventaire": "services",
    "ourouler.apprentissage": "services",
    "ourouler.apprentissage.routes": "services",
    "ourouler.seance.ecran_ftp": "services",
    # 4. rendu
    "ourouler.rendu": "rendu",
    "ourouler.rendu.boucle": "rendu",
    "ourouler.rendu.boucle_json": "rendu",
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
    # 5. entrées
    "ourouler.config": "config",
    "ourouler.cli": "cli",
    "ourouler.cli.__main__": "cli",
    "ourouler.cli.comptes": "cli",
    "ourouler.cli.depart": "cli",
    "ourouler.cli.options": "cli",
    "ourouler.cli.parseur": "cli",
    # du `Namespace` à la `Demande`, puis au rendu imprimé
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
    "ourouler.api.calculs": "api",
    "ourouler.api.double_chemin": "api",
    "ourouler.api.reponses": "api",
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
    # Vide. Une violation nouvelle ne s'ajoute pas ici sans le changement qui
    # la retire, et une date.
]

#: Ancien chemin → module qu'il réexporte. Vide : tout import passe par la
#: cible directement.
REEXPORTS: dict[str, str] = {}

#: Les imports sous `if TYPE_CHECKING:` : permis, mais nommés.
IMPORTS_TYPE_CHECKING: set[tuple[str, str]] = {
    # Les annotations des adaptateurs de comptes : `cli/comptes.py` reste importable
    # sans le pilote PostgreSQL, que `services/comptes.py` tire.
    ("ourouler.cli.comptes", "ourouler.api.comptes"),
    ("ourouler.cli.comptes", "ourouler.api.courriel"),
    ("ourouler.cli.comptes", "ourouler.services.comptes"),
    # Le rendu du profil annote `Config` sans dépendre, à l'exécution, de
    # l'entrée qui la charge ; celui des parcours de même.
    ("ourouler.rendu.profil", "ourouler.config"),
    ("ourouler.rendu.boucle", "ourouler.config"),
    ("ourouler.rendu.boucle_json", "ourouler.config"),  # le JSON de boucle
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
        if nom == "config":
            assert (SOURCES / f"{nom}.py").exists()
            continue
        assert (SOURCES / nom).is_dir() == existe, f"{nom}/ : « existe={existe} » ne dit plus vrai"


def test_les_imports_type_checking_sont_nommes():
    trouves = {(i.importeur, i.importe) for i in tous_les_imports() if i.genre == "type_checking"}
    assert trouves == IMPORTS_TYPE_CHECKING


def test_aucune_violation_nouvelle():
    nouvelles, _, _ = confronter(violations(tous_les_imports()), EXCEPTIONS, aujourd_hui())
    assert not nouvelles, (
        "import interdit par le contrat de couches (docs/journal/ouverture_plan.md §2) :\n  "
        + "\n  ".join(nouvelles)
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


def test_aucun_reexport_ne_reste():
    """Le lot final a retiré tous les modules de réexport : la table est vide."""
    assert REEXPORTS == {}


#: `docs/journal/ouverture_plan.md` §2 : « Le modèle physique pur […] n'importe ni
#: `Config`, ni cache, ni `Path`, ni `httpx`, ni `boucle` ; numpy est permis. »
#: Préfixes interdits, bibliothèque standard et tierces comprises.
INTERDITS_PHYSIQUE_PURE = (
    "pathlib",
    "httpx",
    "ourouler.config",
    "ourouler.activites.cache",
    "ourouler.boucle",
)

#: Tout `physique/` est du domaine : ses cas d'usage (`calibrer`, `simuler`,
#: `analyser`) vivent dans `services/physique.py`, la comparaison dans
#: `services/comparer.py`.


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
        nom for nom in modules_sources() if nom == "ourouler.physique" or nom.startswith("ourouler.physique.")
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
