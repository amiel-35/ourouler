"""Filet 0d : les formats persistés, relus et réécrits à l'identique.

Trois promesses, pour que la restructuration du plan d'ouverture
(`docs/ouverture_plan.md`, §1 D5 et §4 « 0d ») ne puisse pas casser les
données d'un cycliste sans qu'un test rougisse :

1. **Relire.** Chaque échantillon figé dans `echantillons/` — écrit par le code
   d'aujourd'hui — est relu par le code du moment, qui doit en tirer les mêmes
   valeurs (`echantillons/lecture.json`). C'est ce qui permet, après un lot,
   de relire ce que la version d'avant a écrit.
2. **Réécrire à l'identique.** Une fabrication fraîche (`fabrique_echantillons`)
   doit produire le même contenu que les échantillons, une fois normalisé
   (lignes d'un SQLite, JSON relu). C'est ce qui permet un **retour
   arrière** : l'ancien code relit ce que le nouveau a écrit, parce que le
   nouveau écrit exactement ce qu'écrivait l'ancien.
3. **Versions et migrations figées** (`echantillons/versions.json`) : les
   constantes de version de schéma, et la liste des migrations Postgres avec
   l'empreinte de leur SQL. Ajouter une migration est un geste explicite
   (régénération relue en PR) ; en modifier ou en retirer une rougit.

Régénération, **seulement** pour un changement de format voulu, décidé et
relu (jamais dans un lot de restructuration) :

    uv run pytest tests/compatibilite --regenerer-golden
"""

from __future__ import annotations

import dataclasses
import difflib
import hashlib
import importlib
import json
import math
import re
import shutil
import sqlite3
from datetime import date
from pathlib import Path
from typing import Any

import httpx
import pytest
from fabrique_echantillons import (
    COMPTE,
    ECHANTILLONS,
    FICHIERS,
    contenu_comparable,
    copier_echantillons,
    fabriquer,
    trace_synthetique,
    vider_sqlite,
)
from outils_caracterisation import arrondir, ecrire_config, serialiser

from ourouler.activites.cache import Cache
from ourouler.api.base_de_donnees import migrations_disponibles
from ourouler.api.comptes import verifier_mot_de_passe
from ourouler.api.depots import DepotFichiers, DepotProfils, JournalServices, SocleTOML
from ourouler.api.proprietaire import Proprietaire
from ourouler.apprentissage.routes import BaseRoutes, lire_poids
from ourouler.boucle.gpx import lire_gpx_trace
from ourouler.connecteurs.openmeteo_archive import ClientArchive
from ourouler.noyau.erreurs import ErreurUtilisateur
from ourouler.stockage.calibrations import lire_calibration

MESSAGE = (
    "format persisté modifié : un lot de restructuration ne touche ni format, ni "
    "constante de version, ni migration (plan §4, 0d)"
)
REGENERER = "uv run pytest tests/compatibilite --regenerer-golden"

LECTURE = ECHANTILLONS / "lecture.json"
VERSIONS = ECHANTILLONS / "versions.json"

#: Les constantes de version de schéma, par nom qualifié. Un lot qui déplace
#: un module garde un réexport (lot 3) ou met ce nom à jour ; il ne change
#: jamais la **valeur**.
CONSTANTES_DE_VERSION = (
    "ourouler.activites.cache.VERSION_SCHEMA",
    "ourouler.apprentissage.routes.VERSION_SCHEMA",
    "ourouler.connecteurs.openmeteo_archive.VERSION_SCHEMA",
    "ourouler.physique.commande.VERSION_CALIBRATION",
)

#: Migrations Postgres autorisées à contenir `DROP` ou `RENAME`, par nom de
#: fichier. Vide, et doit le rester dans tout lot de restructuration (plan
#: §4, 0d : on ajoute d'abord, on retire plus tard). Y inscrire un nom est une
#: décision du mainteneur, prise hors restructuration.
MIGRATIONS_DESTRUCTIVES_ADMISES: frozenset[str] = frozenset()

#: Chiffres significatifs gardés pour `calibration.json` : l'ajustement passe
#: par numpy, dont le dernier chiffre dépend de la machine (même choix que
#: `CHIFFRES_CALIBRER` du filet 0b).
CHIFFRES_CALIBRATION = 6

#: Écart relatif admis sur les autres flottants (géométrie, `math`) : l'écart
#: de plateforme, pas une dérive de format.
TOLERANCE_RELATIVE = 1e-9


# --- comparaison -------------------------------------------------------------------


def _proches(a: Any, b: Any) -> bool:
    """Même structure, mêmes types ; flottants à `TOLERANCE_RELATIVE` près."""
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(_proches(a[k], b[k]) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(_proches(x, y) for x, y in zip(a, b, strict=True))
    if type(a) is float and type(b) is float:
        return math.isclose(a, b, rel_tol=TOLERANCE_RELATIVE, abs_tol=1e-12)
    return type(a) is type(b) and a == b


def _echec(nom: str, attendu: Any, obtenu: Any) -> None:
    texte_attendu = serialiser(attendu) if not isinstance(attendu, str) else attendu
    texte_obtenu = serialiser(obtenu) if not isinstance(obtenu, str) else obtenu
    diff = "".join(
        difflib.unified_diff(
            texte_attendu.splitlines(keepends=True),
            texte_obtenu.splitlines(keepends=True),
            fromfile=f"{nom} (échantillon)",
            tofile=f"{nom} (code actuel)",
            n=2,
        )
    )
    if len(diff) > 6000:
        diff = diff[:6000] + "\n[… diff tronqué …]\n"
    pytest.fail(f"{MESSAGE}\n{nom} — régénérer seulement après décision : {REGENERER}\n{diff}",
                pytrace=False)


def comparer(nom: str, attendu: Any, obtenu: Any) -> None:
    if attendu == obtenu or _proches(attendu, obtenu):
        return
    _echec(nom, attendu, obtenu)


def _jsonable(valeur: Any) -> Any:
    """Relu et trié comme une référence : dates en ISO, tuples en listes."""
    return json.loads(json.dumps(valeur, default=str, sort_keys=True, ensure_ascii=False))


def comparer_a_la_reference(fichier: Path, cle: str, obtenu: Any, regenerer: bool) -> None:
    """Compare `obtenu` à `fichier[cle]`, ou l'y écrit en régénération."""
    obtenu = _jsonable(obtenu)
    reference = json.loads(fichier.read_text(encoding="utf-8")) if fichier.is_file() else {}
    if regenerer:
        reference[cle] = obtenu
        fichier.write_text(serialiser(reference), encoding="utf-8")
        pytest.skip(f"référence régénérée : {fichier.name}[{cle}]")
    assert cle in reference, f"{fichier.name} n'a pas d'entrée « {cle} » — {REGENERER}"
    comparer(f"{fichier.name}[{cle}]", reference[cle], obtenu)


# --- la fabrication fraîche, une fois par module ------------------------------------


@pytest.fixture(scope="module")
def regenerer(request) -> bool:
    return request.config.getoption("--regenerer-golden")


@pytest.fixture(scope="module")
def fraiche(tmp_path_factory, regenerer) -> Path:
    """Les échantillons tels que le code **actuel** les écrit aujourd'hui.

    En régénération, ils remplacent `echantillons/` (le dossier est vidé
    d'abord : un format retiré ne doit pas y survivre).
    """
    racine = tmp_path_factory.mktemp("fabrication")
    with pytest.MonkeyPatch.context() as monkeypatch:
        sortie = fabriquer(racine, monkeypatch)
    if regenerer:
        for relatif in FICHIERS:
            (ECHANTILLONS / relatif).unlink(missing_ok=True)
        shutil.rmtree(ECHANTILLONS / "donnees", ignore_errors=True)
        copier_echantillons(sortie, ECHANTILLONS)
    return sortie


@pytest.fixture
def copie(tmp_path: Path, fraiche: Path) -> Path:
    """Une copie des échantillons figés : les relire ne doit jamais les toucher.

    Dépend de `fraiche` pour qu'en régénération, on relise les nouveaux.
    """
    destination = tmp_path / "echantillons"
    copier_echantillons(ECHANTILLONS, destination)
    return destination


# --- 2. réécrire à l'identique -------------------------------------------------------


@pytest.mark.parametrize("relatif", sorted(FICHIERS))
def test_le_code_actuel_reecrit_le_meme_contenu(relatif: str, fraiche: Path, regenerer: bool):
    if regenerer:
        pytest.skip("échantillons régénérés")
    nature = FICHIERS[relatif]
    echantillon = ECHANTILLONS / relatif
    assert echantillon.is_file(), f"échantillon absent : {relatif} — {REGENERER}"
    attendu = contenu_comparable(echantillon, nature)
    obtenu = contenu_comparable(fraiche / relatif, nature)
    if relatif.endswith("calibration.json"):
        attendu, obtenu = arrondir(attendu, CHIFFRES_CALIBRATION), arrondir(obtenu, CHIFFRES_CALIBRATION)
    comparer(relatif, attendu, obtenu)


def test_aucun_nouveau_fichier_persiste_n_apparait(fraiche: Path):
    """Un fichier que le code se met à écrire est un format de plus : il se déclare.

    Les fichiers bruts (`donnees/brut/`) sont les fichiers d'activité tels que
    la source les a donnés — FIT, GPX, TCX —, pas un format du projet ; seul
    leur rangement compte, et `index.sqlite` le fige (colonne `chemin` de la
    lecture).
    """
    ecrits = {
        p.relative_to(fraiche).as_posix()
        for p in fraiche.rglob("*")
        if p.is_file() and not p.relative_to(fraiche).as_posix().startswith("donnees/brut/")
    }
    assert ecrits == set(FICHIERS), (
        f"{MESSAGE} — fichiers en plus : {sorted(ecrits - set(FICHIERS))}, "
        f"en moins : {sorted(set(FICHIERS) - ecrits)}"
    )


# --- 1. relire ce que la version d'aujourd'hui a écrit --------------------------------


def _refus_reseau(requete: httpx.Request) -> httpx.Response:
    raise AssertionError(f"la relecture d'un cache ne doit pas appeler le réseau ({requete.url})")


def _entree(entree, racine: Path) -> dict:
    return {
        "identifiant": entree.identifiant,
        "source": entree.source,
        "id_externe": entree.id_externe,
        "debut": entree.debut.isoformat() if entree.debut else None,
        "duree_s": entree.duree_s,
        "distance_m": entree.distance_m,
        "puissance_moy_w": entree.puissance_moy_w,
        "sport": entree.sport,
        "appareil": entree.appareil,
        "equipement": entree.equipement,
        "meta": entree.meta,
        "extension": entree.extension,
        "chemin": entree.chemin.relative_to(racine).as_posix(),
    }


def lire_index(copie: Path) -> dict:
    racine = copie / "donnees"
    locale = Cache(racine)
    compte = Cache(racine, proprietaire=COMPTE)
    return {
        "local": [_entree(e, racine) for e in locale.lister()],
        "local_fevrier": [e.identifiant for e in locale.lister("2026-02-01", "2026-02-28")],
        COMPTE: [_entree(e, racine) for e in compte.lister()],
        "contient": compte.contient(source="intervals", id_externe="i-synthetique-1"),
    }


def lire_archive(copie: Path) -> dict:
    chemin = copie / "donnees" / "archive_meteo.sqlite"
    with sqlite3.connect(chemin) as cx:
        cles = cx.execute("SELECT lat, lon, jour FROM archive ORDER BY jour, lat, lon").fetchall()
    client = ClientArchive(
        http=httpx.Client(transport=httpx.MockTransport(_refus_reseau)), chemin_cache=chemin
    )
    lu = {}
    for lat, lon, jour in cles:
        heures = client.horaires(lat, lon, date.fromisoformat(jour), aujourd_hui=date(2026, 9, 8))
        valeurs = [
            [h.t.isoformat(), h.vent_kmh, h.vent_depuis_deg, h.temp_c, h.pression_hpa]
            for h in heures
        ]
        # Les 24 heures en entier, par leur empreinte (valeurs relues du JSON
        # rangé, donc exactes) ; la première et la dernière en clair.
        lu[f"{lat},{lon},{jour}"] = {
            "heures": len(valeurs),
            "premiere": valeurs[0],
            "derniere": valeurs[-1],
            "sha256": hashlib.sha256(json.dumps(valeurs).encode()).hexdigest(),
        }
    assert client.appels == 0 and client.lectures_cache == len(cles)
    return lu


def lire_routes(copie: Path) -> dict:
    chemin = copie / "donnees" / "routes_connues.sqlite"
    lu = {}
    for proprietaire in ("local", COMPTE):
        base = BaseRoutes(chemin, proprietaire=proprietaire)
        lu[proprietaire] = {
            "troncons": sorted(
                (dataclasses.asdict(t) for t in base.troncons()), key=lambda t: json.dumps(t)
            ),
            "sorties": base.sorties(),
            "sorties_apprises": sorted(base.sorties_apprises()),
            "statistiques": dataclasses.asdict(base.statistiques()),
            "part_connue": base.part_connue(trace_synthetique()),
        }
    return lu


def lire_calibrations(copie: Path) -> dict:
    chemin = copie / "donnees" / "calibration.json"
    lu = {}
    for velo in ("RCR", "BMC", "rcr", "Tandem"):
        calibration = lire_calibration(chemin, velo)
        lu[velo] = dataclasses.asdict(calibration) if calibration is not None else None
    return arrondir(_jsonable(lu), CHIFFRES_CALIBRATION)


def lire_poids_routes(copie: Path) -> dict | None:
    return lire_poids(copie / "donnees" / "poids_routes.json")


def lire_profil(copie: Path) -> dict:
    socle = ecrire_config(copie / "serveur.toml", copie / "cache_serveur")
    profils = DepotProfils(SocleTOML(socle, proprietaire=None), copie / "donnees" / "api")
    qui = Proprietaire(COMPTE)
    config = profils.config(qui)
    return {
        "surcharge": profils.surcharge(qui),
        "depart": dataclasses.asdict(config.depart),
        "cycliste": dataclasses.asdict(config.cycliste),
        "velos": [dataclasses.asdict(v) for v in config.velos],
        "position_zone": config.seance.position_zone,
        "sens": config.boucle.sens,
        "historique_depuis": config.historique_depuis.isoformat(),
    }


def lire_services(copie: Path) -> dict:
    journal = JournalServices(copie / "donnees" / "api")
    qui = Proprietaire(COMPTE)
    return {
        "tout": journal.tout(qui),
        "intervals": journal.dernier_succes(qui, "intervals"),
        "garmin": journal.dernier_succes(qui, "garmin"),
    }


def lire_fichiers(copie: Path) -> dict:
    depot = DepotFichiers(copie / "donnees" / "api")
    qui = Proprietaire(COMPTE)

    def fiche(f) -> dict:
        return {
            **f.json(),
            "type_contenu": f.type_contenu,
            "fichier": f.chemin.name,
            "sha256": hashlib.sha256(f.chemin.read_bytes()).hexdigest(),
        }

    return {
        "lister": [fiche(f) for f in depot.lister(qui)],
        "trouver": fiche(depot.trouver(qui, "00000000000000000000000000000002")),
    }


def lire_parcours(copie: Path) -> dict:
    trace = lire_gpx_trace(copie / "parcours.gpx.xml")
    return {
        "nom": trace.nom,
        "points": [[p.lat, p.lon, p.alt_m, p.dist_m] for p in trace.points],
        "distance_m": trace.distance_m,
        "denivele_m": trace.denivele_m,
        "meta": {cle: v for cle, v in trace.meta.items() if cle != "fichier"},
    }


def lire_secret(copie: Path) -> dict:
    charge = json.loads((copie / "secret_compte.json").read_text(encoding="utf-8"))
    return {
        "forme": bool(re.fullmatch(r"[0-9a-f]{32}\$[0-9a-f]{64}", charge["secret"])),
        "accepte_le_bon": verifier_mot_de_passe(charge["mot_de_passe"], charge["secret"]),
        "refuse_un_autre": not verifier_mot_de_passe("autre", charge["secret"]),
    }


LECTEURS = {
    "index.sqlite": lire_index,
    "archive_meteo.sqlite": lire_archive,
    "routes_connues.sqlite": lire_routes,
    "calibration.json": lire_calibrations,
    "poids_routes.json": lire_poids_routes,
    "profil.json": lire_profil,
    "services.json": lire_services,
    "fichiers_deposes": lire_fichiers,
    "parcours.gpx": lire_parcours,
    "secret_compte": lire_secret,
}


@pytest.mark.parametrize("format_", sorted(LECTEURS))
def test_le_code_actuel_relit_l_echantillon(format_: str, copie: Path, regenerer: bool):
    avant = {r: _empreinte(copie / r, n) for r, n in FICHIERS.items()}
    lu = LECTEURS[format_](copie)
    comparer_a_la_reference(LECTURE, format_, lu, regenerer)
    # Relire un fichier au schéma courant ne le réécrit pas (aucune migration
    # silencieuse, aucune ligne ajoutée).
    apres = {r: _empreinte(copie / r, n) for r, n in FICHIERS.items()}
    assert apres == avant, f"{format_} : la relecture a modifié un échantillon"


def _empreinte(chemin: Path, nature: str) -> str:
    return serialiser(contenu_comparable(chemin, nature))


# --- 3. versions de schéma et migrations Postgres -------------------------------------


def _constante(nom_qualifie: str) -> Any:
    module, _, attribut = nom_qualifie.rpartition(".")
    return getattr(importlib.import_module(module), attribut)


def _sql_sans_commentaires(sql: str) -> str:
    return "\n".join(ligne.split("--", 1)[0] for ligne in sql.splitlines())


def test_versions_de_schema_et_migrations_figees(fraiche: Path, regenerer: bool):
    versions = {
        "constantes": {nom: _constante(nom) for nom in CONSTANTES_DE_VERSION},
        "ecrites": {
            **{
                r: vider_sqlite(fraiche / r)["user_version"]
                for r, n in sorted(FICHIERS.items())
                if n == "sqlite"
            },
            **{
                r: json.loads((fraiche / r).read_text(encoding="utf-8"))["version"]
                for r in ("donnees/calibration.json", "donnees/poids_routes.json")
            },
        },
        "migrations_postgres": [
            {
                "numero": numero,
                "nom": nom,
                "sha256": hashlib.sha256(chemin.read_bytes()).hexdigest(),
            }
            for numero, nom, chemin in migrations_disponibles()
        ],
    }
    if regenerer:
        VERSIONS.write_text(serialiser(versions), encoding="utf-8")
        pytest.skip("versions.json régénéré")
    assert VERSIONS.is_file(), f"versions.json absent — {REGENERER}"
    comparer("versions.json", json.loads(VERSIONS.read_text(encoding="utf-8")), versions)


def test_les_versions_ecrites_sont_celles_des_constantes(fraiche: Path):
    """Le numéro rangé dans chaque fichier est bien celui que le code déclare."""
    ecrit = {
        "ourouler.activites.cache.VERSION_SCHEMA": "donnees/index.sqlite",
        "ourouler.apprentissage.routes.VERSION_SCHEMA": "donnees/routes_connues.sqlite",
        "ourouler.connecteurs.openmeteo_archive.VERSION_SCHEMA": "donnees/archive_meteo.sqlite",
    }
    for constante, relatif in ecrit.items():
        assert vider_sqlite(fraiche / relatif)["user_version"] == _constante(constante), relatif
    calibration = json.loads((fraiche / "donnees/calibration.json").read_text(encoding="utf-8"))
    assert calibration["version"] == _constante("ourouler.physique.commande.VERSION_CALIBRATION")


def test_aucune_migration_ne_detruit_ni_ne_renomme():
    """Plan §4, 0d : côté Postgres, on ajoute d'abord, on retire plus tard.

    Ni `DROP` ni `RENAME` dans une migration (commentaires exclus), sauf
    décision inscrite dans `MIGRATIONS_DESTRUCTIVES_ADMISES`.
    """
    fautives = []
    for _, nom, chemin in migrations_disponibles():
        sql = _sql_sans_commentaires(chemin.read_text(encoding="utf-8"))
        if re.search(r"\b(DROP|RENAME)\b", sql, re.IGNORECASE) and nom not in (
            MIGRATIONS_DESTRUCTIVES_ADMISES
        ):
            fautives.append(nom)
    assert fautives == [], f"{MESSAGE} — migration destructive : {fautives}"


def test_la_garde_des_migrations_saurait_voir_un_drop(tmp_path: Path):
    """Sans ce contrôle, la garde ci-dessus pourrait être verte en ne voyant rien."""
    (tmp_path / "0001_a.sql").write_text("-- DROP dans un commentaire\nCREATE TABLE t (x int);\n")
    (tmp_path / "0002_b.sql").write_text("ALTER TABLE t RENAME COLUMN x TO y;\n")
    vues = [
        nom
        for _, nom, chemin in migrations_disponibles(tmp_path)
        if re.search(r"\b(DROP|RENAME)\b", _sql_sans_commentaires(chemin.read_text()), re.I)
    ]
    assert vues == ["0002_b.sql"]


# --- ce qui se passe à la lecture d'une version plus récente --------------------------
#
# Comportement **actuel**, figé tel quel (le chantier 0e, « tolérer les formats
# futurs », a été retiré du plan) : ces tests disent ce qu'un retour arrière
# rencontre si un fichier a été écrit par une version plus récente.


def _poser_version(chemin: Path, version: int) -> None:
    with sqlite3.connect(chemin) as cx:
        cx.execute(f"PRAGMA user_version = {version}")


def test_un_index_plus_recent_est_refuse(copie: Path):
    index = copie / "donnees" / "index.sqlite"
    _poser_version(index, _constante("ourouler.activites.cache.VERSION_SCHEMA") + 1)
    with pytest.raises(ErreurUtilisateur, match="schéma"):
        Cache(copie / "donnees")


def test_une_base_de_routes_plus_recente_est_refusee(copie: Path):
    base = copie / "donnees" / "routes_connues.sqlite"
    _poser_version(base, _constante("ourouler.apprentissage.routes.VERSION_SCHEMA") + 1)
    with pytest.raises(ErreurUtilisateur, match="schéma"):
        BaseRoutes(base)


def test_une_archive_meteo_plus_recente_est_relue_quand_meme(copie: Path):
    """Commodité, pas source de vérité : un cache plus récent n'est pas refusé."""
    archive = copie / "donnees" / "archive_meteo.sqlite"
    version = _constante("ourouler.connecteurs.openmeteo_archive.VERSION_SCHEMA")
    _poser_version(archive, version + 1)
    client = ClientArchive(
        http=httpx.Client(transport=httpx.MockTransport(_refus_reseau)), chemin_cache=archive
    )
    assert client.chemin_cache is not None
    heures = client.horaires(0.0, 0.0, date(2026, 1, 1), aujourd_hui=date(2026, 9, 8))
    assert len(heures) == 24 and client.appels == 0
    # … et l'ouvrir le ramène au numéro que ce code connaît.
    assert vider_sqlite(archive)["user_version"] == version


def test_une_calibration_d_une_autre_version_est_ignoree(copie: Path):
    chemin = copie / "donnees" / "calibration.json"
    charge = json.loads(chemin.read_text(encoding="utf-8"))
    assert lire_calibration(chemin, "RCR") is not None
    charge["version"] = _constante("ourouler.physique.commande.VERSION_CALIBRATION") + 1
    chemin.write_text(json.dumps(charge), encoding="utf-8")
    assert lire_calibration(chemin, "RCR") is None


def test_des_poids_d_une_autre_version_sont_relus_quand_meme(copie: Path):
    """`lire_poids` ne lit pas le champ `version` : il ne relit que `poids`."""
    chemin = copie / "donnees" / "poids_routes.json"
    charge = json.loads(chemin.read_text(encoding="utf-8"))
    charge["version"] = charge["version"] + 1
    chemin.write_text(json.dumps(charge), encoding="utf-8")
    assert lire_poids(chemin) == {cle: float(v) for cle, v in charge["poids"].items()}


# --- aucune coordonnée réelle ----------------------------------------------------------


#: Tout point des échantillons est en mer, à moins d'un degré du point (0, 0) —
#: à des milliers de kilomètres de toute ville (voir `tests/test_invariants.py`).
RAYON_DEG = 1.0


def test_les_echantillons_ne_portent_aucune_coordonnee_reelle(copie: Path):
    points: list[tuple[float, float]] = []
    with sqlite3.connect(copie / "donnees" / "archive_meteo.sqlite") as cx:
        points += cx.execute("SELECT lat, lon FROM archive").fetchall()
    with sqlite3.connect(copie / "donnees" / "routes_connues.sqlite") as cx:
        points += [(a / 3000, b / 3000) for a, b in cx.execute("SELECT cle_lat, cle_lon FROM troncons")]
    profil = json.loads((copie / f"donnees/api/{COMPTE}/profil.json").read_text(encoding="utf-8"))
    points.append((profil["depart"]["latitude"], profil["depart"]["longitude"]))
    gpx = (copie / "parcours.gpx.xml").read_text(encoding="utf-8")
    points += [
        (float(a), float(b)) for a, b in re.findall(r'lat="([-0-9.]+)" lon="([-0-9.]+)"', gpx)
    ]
    assert len(points) > 20, "l'invariant ne mesurerait rien"
    loin = [p for p in points if abs(p[0]) > RAYON_DEG or abs(p[1]) > RAYON_DEG]
    assert loin == [], f"coordonnées hors de la zone synthétique : {loin[:5]}"
