"""Fabrique des échantillons de compatibilité (filet 0d du plan d'ouverture).

Chaque format que le code écrit sur disque et relit plus tard est produit ici
**par le code actuel**, avec ses propres fonctions d'écriture, sur des
données synthétiques : départ en mer près du point (0, 0), sorties TCX
fabriquées par le modèle physique (`donnees_synthetiques`), clés et comptes
inventés. Rien d'une personne réelle.

La fabrique est **déterministe** : horloge figée et réseau rejoué par
`outils_caracterisation.preparer` (le même gel que le filet 0b), identifiants
de fichier tirés d'un compteur, sel du mot de passe fixé. Deux passages
écrivent donc le même contenu, et `test_compatibilite.py` peut comparer une
fabrication fraîche aux échantillons figés dans `echantillons/`.

Ce module importe les fonctions d'écriture et de lecture là où elles vivent
aujourd'hui. Un lot de restructuration qui les déplace met ces imports à jour
(ou garde un réexport) ; il ne touche **jamais** les échantillons.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import sys
import uuid
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest

DOSSIER = Path(__file__).resolve().parent
CARACTERISATION = DOSSIER.parent / "caracterisation"
if str(CARACTERISATION) not in sys.path:
    sys.path.insert(0, str(CARACTERISATION))

import donnees_synthetiques as synth  # noqa: E402
from outils_caracterisation import ecrire_config, preparer  # noqa: E402

from ourouler.activites.cache import Cache  # noqa: E402
from ourouler.api.comptes import hacher_mot_de_passe  # noqa: E402
from ourouler.api.depots import DepotFichiers, DepotProfils, JournalServices, SocleTOML  # noqa: E402
from ourouler.api.proprietaire import Proprietaire  # noqa: E402
from ourouler.apprentissage.routes import BaseRoutes  # noqa: E402
from ourouler.boucle.gpx import ecrire_gpx  # noqa: E402
from ourouler.cli import main  # noqa: E402
from ourouler.noyau.trace import PointTrace, Segment, Trace, distance_m  # noqa: E402

#: Où vivent les échantillons figés.
ECHANTILLONS = DOSSIER / "echantillons"

#: Le propriétaire d'un compte hébergé, inventé (forme de `FORME_IDENTIFIANT`).
COMPTE = "compte-synthetique"

#: Le mot de passe synthétique dont l'empreinte est rangée dans `comptes.secret`.
MOT_DE_PASSE = "mot-de-passe-invente-pour-le-filet"

#: Le sel fixé pour que l'empreinte scrypt soit reproductible (16 octets).
SEL_FIXE = bytes(range(16))

#: Ce qu'on range à la main dans le dépôt de fichiers : une séance ZWO et une
#: MRC minimales, inventées. Le dépôt garde les octets tels quels.
ZWO = (
    '<workout_file><name>Filet 0d</name><sportType>bike</sportType><workout>'
    '<SteadyState Duration="600" Power="0.6"/><SteadyState Duration="300" Power="0.9"/>'
    "</workout></workout_file>\n"
)
MRC = (
    "[COURSE HEADER]\nVERSION = 2\nUNITS = ENGLISH\nDESCRIPTION = Filet 0d\n"
    "FILE NAME = filet\nMINUTES PERCENT\n[END COURSE HEADER]\n[COURSE DATA]\n"
    "0.00\t60\n10.00\t60\n10.00\t90\n15.00\t90\n[END COURSE DATA]\n"
)

#: Chaque fichier d'échantillon, par chemin relatif sous `echantillons/`, et
#: sa nature — ce qui décide comment on le compare (`contenu_comparable`).
FICHIERS = {
    "donnees/index.sqlite": "sqlite",
    "donnees/archive_meteo.sqlite": "sqlite",
    "donnees/routes_connues.sqlite": "sqlite",
    "donnees/calibration.json": "json",
    "donnees/poids_routes.json": "json",
    f"donnees/api/{COMPTE}/profil.json": "json",
    f"donnees/api/{COMPTE}/services.json": "json",
    f"donnees/api/{COMPTE}/fichiers/00000000000000000000000000000001.zwo": "octets",
    f"donnees/api/{COMPTE}/fichiers/00000000000000000000000000000001.nom": "octets",
    f"donnees/api/{COMPTE}/fichiers/00000000000000000000000000000002.mrc": "octets",
    f"donnees/api/{COMPTE}/fichiers/00000000000000000000000000000002.nom": "octets",
    "parcours.gpx.xml": "octets",
    "secret_compte.json": "json",
}


# --- la fabrication ------------------------------------------------------------


def fabriquer(racine: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Écrit tous les échantillons sous `racine/sortie`, et rend ce dossier.

    `racine` sert aussi de dossier de travail (configuration, historique TCX,
    fichiers bruts) : seuls les fichiers de `FICHIERS` sont des échantillons.
    """
    preparer(monkeypatch)
    compteur = iter(range(1, 1000))
    monkeypatch.setattr(uuid, "uuid4", lambda: uuid.UUID(int=next(compteur)))
    sortie = racine / "sortie"
    cache = sortie / "donnees"
    config = ecrire_config(racine / "config.toml", cache)

    _fabriquer_cache_cli(racine, cache, config)
    _fabriquer_compte_heberge(cache, config)
    _fabriquer_routes(cache, config)
    _fabriquer_gpx(sortie / "parcours.gpx.xml")
    _fabriquer_secret(sortie / "secret_compte.json", monkeypatch)
    return sortie


def _lancer(config: Path, *argv: str) -> None:
    code = main(["--config", str(config), *argv])
    assert code == 0, f"ourouler {' '.join(argv)} : code {code}"


def _fabriquer_cache_cli(racine: Path, cache: Path, config: Path) -> None:
    """`index.sqlite`, `archive_meteo.sqlite` et `calibration.json`, par la ligne
    de commande elle-même : `inventaire --importer`, puis `calibrer`.

    Deux vélos calibrés pour que `calibration.json` porte deux entrées (la
    seconde écriture relit la première et la garde).
    """
    historique = synth.ecrire_historique(racine / "historique")
    # Huit sorties de RCR de plus, et la moitié gardée pour la validation :
    # assez de sorties de validation pour que la fourchette du porte à porte
    # soit mesurée (`SORTIES_MIN_FOURCHETTE`), donc écrite dans le fichier.
    for jour in range(9, 17):
        quand = date(2026, 1, jour)
        (historique / f"sortie_{quand.isoformat()}.tcx").write_bytes(
            synth.tcx_synthetique(synth.ROUTE, quand)
        )
    with config.open("a", encoding="utf-8") as fichier:
        fichier.write("\n[calibration]\npart_validation = 0.5\n")
    _lancer(config, "inventaire", "--importer", str(historique))
    _lancer(config, "calibrer", "--velo", "RCR")
    _lancer(config, "calibrer", "--velo", "BMC")
    # Une activité d'un compte hébergé : la colonne `proprietaire` et le
    # rangement `brut/comptes/<propriétaire>/` du schéma 3.
    compte = Cache(cache, proprietaire=COMPTE)
    compte.ajouter(
        synth.tcx_synthetique(synth.ROUTE, date(2026, 3, 2), duree_s=600),
        source="intervals",
        id_externe="i-synthetique-1",
        extension="tcx",
        meta={"sport": "Ride", "equipement": "Route", "puissance_moy_w": 180.0},
    )
    compte.mettre_a_jour_meta(
        source="intervals",
        id_externe="i-synthetique-1",
        meta={"sport": "Ride", "appareil": "Compteur inventé"},
        equipement="Route",
    )


def _fabriquer_compte_heberge(cache: Path, config: Path) -> None:
    """`api/<propriétaire>/` : `profil.json`, `services.json`, fichiers déposés."""
    dossier_donnees = cache / "api"
    qui = Proprietaire(COMPTE)
    profils = DepotProfils(SocleTOML(config, proprietaire=None), dossier_donnees)
    # Deux écritures, comme l'assistant d'embarquement : la seconde se fusionne.
    profils.enregistrer(qui, {"cycliste": {"prenom": "Anne", "nom": "Onyme"}})
    profils.enregistrer(
        qui,
        {
            "depart": {"nom": "Point en mer", "latitude": 0.01, "longitude": 0.02},
            "cycliste": {"masse_kg": 72.5, "ftp_w": 215},
            "velos": [
                {"nom": "Route", "usage": "route", "masse_kg": 8.4, "pneu": "course_rapide"},
                {"nom": "Chrono", "usage": "clm", "cda_m2": 0.24},
            ],
            "seance": {"position_zone": 0.25},
            "boucle": {"sens": "antihoraire"},
            "historique_depuis": "2026-01-01",
        },
    )
    journal = JournalServices(dossier_donnees)
    journal.noter_succes(qui, "intervals", quand=datetime(2026, 9, 7, 18, 30, tzinfo=UTC))
    journal.noter_succes(qui, "meteo")  # horloge figée
    fichiers = DepotFichiers(dossier_donnees)
    fichiers.deposer(qui, "Séance filet.zwo", ZWO.encode("utf-8"))
    fichiers.deposer(qui, "../seance.MRC", MRC.encode("utf-8"))


def trace_synthetique() -> Trace:
    """Un tracé de ~1,5 km vers l'est, au large du point (0, 0), en deux tronçons."""
    points: list[PointTrace] = []
    cumul = 0.0
    for i in range(14):
        point = PointTrace(lat=0.01, lon=round(0.001 * i, 6), alt_m=10.0 + (i % 4), dist_m=cumul)
        if points:
            cumul += distance_m(points[-1], point)
            point = PointTrace(lat=point.lat, lon=point.lon, alt_m=point.alt_m, dist_m=cumul)
        points.append(point)
    segments = [
        Segment(0, 6, points[6].dist_m, {"highway": "tertiary", "surface": "asphalt"}, cout_km=1.2),
        Segment(
            6,
            13,
            cumul - points[6].dist_m,
            {"highway": "primary", "surface": "asphalt", "maxspeed": "80"},
            cout_km=2.5,
            node_tags={"highway": "traffic_signals"},
        ),
    ]
    return Trace(
        nom="Tracé synthétique",
        points=points,
        segments=segments,
        distance_m=cumul,
        denivele_m=6.0,
        temps_moteur_s=240.0,
        meta={"denivele_source": "moteur"},
    )


def _fabriquer_routes(cache: Path, config: Path) -> None:
    """`routes_connues.sqlite` (deux propriétaires), puis `poids_routes.json`
    par la ligne de commande (`routes poids --appliquer`, BRouter rejoué)."""
    trace = trace_synthetique()
    locale = BaseRoutes(cache / "routes_connues.sqlite")
    locale.ajouter_trace(trace, jour=date(2026, 9, 7), id_sortie="sortie-lundi")  # semaine
    locale.ajouter_trace(trace, jour=date(2026, 9, 6), id_sortie="sortie-dimanche")
    compte = BaseRoutes(cache / "routes_connues.sqlite", proprietaire=COMPTE)
    compte.ajouter_trace(trace, jour=date(2026, 9, 8), id_sortie="i-synthetique-1")
    _lancer(config, "routes", "poids", "--appliquer")


def _fabriquer_gpx(chemin: Path) -> None:
    """Le GPX qu'écrivent `boucle` et `sortie`, et que relit `/simulations`."""
    chemin.write_text(ecrire_gpx(trace_synthetique(), "Parcours synthétique"), encoding="utf-8")


def _fabriquer_secret(chemin: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """La forme de `comptes.secret` (Postgres) : `<sel hex>$<empreinte scrypt hex>`."""
    import ourouler.api.comptes as comptes

    monkeypatch.setattr(comptes.secrets, "token_bytes", lambda n: SEL_FIXE[:n])
    secret = hacher_mot_de_passe(MOT_DE_PASSE)
    chemin.write_text(
        json.dumps({"mot_de_passe": MOT_DE_PASSE, "secret": secret}, indent=2) + "\n",
        encoding="utf-8",
    )


# --- ce qu'on compare ----------------------------------------------------------


def vider_sqlite(chemin: Path) -> dict[str, Any]:
    """Le contenu d'un SQLite, indépendant de sa mise en page sur disque.

    `user_version` (la version de schéma), le SQL de chaque table et index
    (espaces normalisés), et toutes les lignes de chaque table, triées.
    """
    cx = sqlite3.connect(f"file:{chemin}?mode=ro", uri=True)
    try:
        version = cx.execute("PRAGMA user_version").fetchone()[0]
        objets = cx.execute(
            "SELECT type, name, tbl_name, sql FROM sqlite_master "
            "WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name"
        ).fetchall()
        tables = {}
        for type_, nom, _, _ in objets:
            if type_ != "table":
                continue
            colonnes = [ligne[1] for ligne in cx.execute(f"PRAGMA table_info({nom})")]
            lignes = cx.execute(f"SELECT * FROM {nom}").fetchall()
            tables[nom] = {
                "colonnes": colonnes,
                "lignes": sorted(
                    ([_valeur(v) for v in ligne] for ligne in lignes), key=json.dumps
                ),
            }
    finally:
        cx.close()
    return {
        "user_version": version,
        "schema": [
            {"type": t, "nom": n, "table": tb, "sql": " ".join((sql or "").split())}
            for t, n, tb, sql in objets
        ],
        "tables": tables,
    }


def _valeur(v: Any) -> Any:
    if isinstance(v, bytes):
        return "octets:" + hashlib.sha256(v).hexdigest()
    return v


def contenu_comparable(chemin: Path, nature: str) -> Any:
    """Ce qui se compare d'un échantillon : lignes d'un SQLite, JSON relu, octets."""
    if nature == "sqlite":
        return vider_sqlite(chemin)
    if nature == "json":
        return json.loads(chemin.read_text(encoding="utf-8"))
    return chemin.read_text(encoding="utf-8")


def copier_echantillons(source: Path, destination: Path) -> None:
    """Copie les fichiers de `FICHIERS` de `source` vers `destination`."""
    for relatif in FICHIERS:
        cible = destination / relatif
        cible.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / relatif, cible)
