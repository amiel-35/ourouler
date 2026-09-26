"""Lot 11 : les modèles de réponse publiés disent vrai, et ne touchent pas aux corps.

`api/reponses.py` décrit les réponses réussies **sans les filtrer** : rien,
à l'exécution, ne vérifie qu'une réponse ressemble à son modèle. Ce test le
fait, sur les réponses de référence du filet (`tests/caracterisation/
api_*.json`) : chaque 200 d'une route qui déclare un modèle doit s'y valider.
Et le schéma publié ne doit porter, pour ces routes, que la référence au
modèle (`reponses.publier_modeles`).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
from outils_api import client_api, schema_openapi

pytest.importorskip("fastapi", reason="extra « api » absent — uv sync --all-extras")

from ourouler.api import reponses  # noqa: E402

REFERENCES = Path(__file__).resolve().parents[1] / "caracterisation"

#: Route (méthode et chemin, paramètres de chemin en motif) → modèle déclaré.
MODELES: list[tuple[str, type]] = [
    (r"GET /api/v1/systeme", reponses.ReponseSysteme),
    (r"GET /api/v1/profil", reponses.ReponseProfil),
    (r"PATCH /api/v1/profil", reponses.ReponseProfil),
    (r"GET /api/v1/profil/zones", reponses.ReponseZones),
    (r"POST /api/v1/profil/zones/apercu", reponses.ReponseZones),
    (r"GET /api/v1/profil/intervals", reponses.ReponseProfilIntervals),
    (r"GET /api/v1/geocodage", reponses.ReponseGeocodage),
    (r"GET /api/v1/meteo", reponses.ReponseMeteo),
    (r"GET /api/v1/vent-depart", reponses.ReponseVentDepart),
    (r"GET /api/v1/seances", reponses.ReponseSemaine),
    (r"GET /api/v1/seances/[^/]+", reponses.ReponseSeance),
    (r"POST /api/v1/sorties", reponses.ReponseSortie),
    (r"POST /api/v1/boucles", reponses.ReponseBoucle),
    (r"GET /api/v1/inventaire", reponses.ReponseInventaire),
    (r"GET /api/v1/calibrations", reponses.ReponseCalibrations),
]


def _scenarios() -> list[tuple[str, dict[str, Any]]]:
    """Chaque réponse 200 des références, nommée `fichier:scénario`."""
    trouves = []
    for fichier in sorted(REFERENCES.glob("api_*.json")):
        contenu = json.loads(fichier.read_text(encoding="utf-8"))
        scenarios = {"": contenu} if "requete" in contenu else contenu
        for nom, scenario in scenarios.items():
            if isinstance(scenario, dict) and scenario.get("statut") == 200:
                trouves.append((f"{fichier.stem}:{nom}", scenario))
    return trouves


def _modele(requete: str) -> type | None:
    for motif, modele in MODELES:
        if re.fullmatch(motif, requete.split("?")[0]):
            return modele
    return None


def _sans_chronos(valeur: Any) -> Any:
    """`<CHRONO>` (une durée mesurée, masquée par le filet) redevient un entier."""
    if isinstance(valeur, dict):
        return {cle: _sans_chronos(sous) for cle, sous in valeur.items()}
    if isinstance(valeur, list):
        return [_sans_chronos(sous) for sous in valeur]
    return 0 if valeur == "<CHRONO>" else valeur


@pytest.mark.parametrize(("nom", "scenario"), _scenarios(), ids=[n for n, _ in _scenarios()])
def test_chaque_reponse_de_reference_se_valide_dans_son_modele(nom: str, scenario: dict):
    modele = _modele(scenario["requete"])
    if modele is None:
        pytest.skip(f"{scenario['requete']} : pas de modèle déclaré")
    modele.model_validate(_sans_chronos(scenario["corps"]))


def test_chaque_modele_est_verifie_par_au_moins_une_reference():
    verifies = {_modele(s["requete"]) for _, s in _scenarios()}
    assert {m for _, m in MODELES} <= verifies


def test_le_schema_ne_porte_que_la_reference_au_modele():
    """Pas l'objet vide de `response_model=dict` à côté du `$ref` (`publier_modeles`)."""
    schema = schema_openapi(client_api())
    declares = 0
    for operations in schema["paths"].values():
        for operation in operations.values():
            forme = operation["responses"].get("200", {}).get("content", {})
            forme = forme.get("application/json", {}).get("schema", {})
            if "$ref" in forme:
                declares += 1
                assert set(forme) == {"$ref"}, forme
    assert declares >= len(MODELES)
