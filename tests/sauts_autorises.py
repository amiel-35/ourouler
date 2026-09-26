"""Les seuls motifs pour lesquels un test a le droit d'être sauté en CI.

Un test sauté ne prouve rien, et un saut ne se voit pas : `uv run pytest -q`
l'affiche en un `s` perdu dans une ligne de points. En CI (variable
d'environnement `CI`, posée par GitHub Actions), `tests/conftest.py` fait donc
échouer la session si un test est sauté pour un motif qui ne figure pas
ci-dessous. Hors CI, rien ne change : un contributeur sans Docker voit ses
tests de comptes sautés, la CI, elle, les exige.

Chaque motif est une expression régulière qui doit couvrir **toute** la raison
du saut (`re.fullmatch`), avec un exemple réel et la raison pour laquelle ce
saut est légitime. Un motif s'ajoute ici, dans la PR qui introduit le saut, et
jamais par commodité : un saut qui cache une panne (module absent, service
indisponible) n'y a pas sa place.

Absents exprès :

- « PostgreSQL local indisponible » : la CI lance PostgreSQL, un test de
  comptes sauté y est une panne ;
- les `pytest.importorskip` des tests adversariaux : un module de production
  absent est une régression, pas une raison de sauter.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import pytest


@dataclass(frozen=True)
class SautAutorise:
    motif: str
    exemple: str
    pourquoi: str


SAUTS_AUTORISES: tuple[SautAutorise, ...] = (
    SautAutorise(
        motif=r"puissance au-delà de la borne de bissection",
        exemple="puissance au-delà de la borne de bissection",
        pourquoi=(
            "tests/test_physique_modele.py, grille puissance × pente × vent : aux "
            "combinaisons où la vitesse d'équilibre dépasse la borne de la "
            "bissection, l'aller-retour vitesse ↔ puissance n'a pas de sens"
        ),
    ),
    SautAutorise(
        motif=r"vitesse saturée \([-+0-9.e]+ m/s\) : la réciprocité ne s'applique pas",
        exemple="vitesse saturée (30.0 m/s) : la réciprocité ne s'applique pas",
        pourquoi=(
            "tests/adversarial/test_adv_physique.py, même réciprocité vue en "
            "adversarial : une vitesse bornée (0 ou V_MAX) ne se renverse pas"
        ),
    ),
    SautAutorise(
        motif=r"GET /api/v1/activites/import/<HEX> : pas de modèle déclaré",
        exemple="GET /api/v1/activites/import/<HEX> : pas de modèle déclaré",
        pourquoi=(
            "tests/api/test_reponses_openapi.py : l'état d'un import n'a pas de "
            "modèle de réponse déclaré, il n'y a rien à valider"
        ),
    ),
    SautAutorise(
        motif=r"GET /api/v1/sorties/<HEX>/propositions/1/gpx : pas de modèle déclaré",
        exemple="GET /api/v1/sorties/<HEX>/propositions/1/gpx : pas de modèle déclaré",
        pourquoi="tests/api/test_reponses_openapi.py : la route rend un fichier GPX, pas du JSON",
    ),
)


def saut_autorise(raison: str) -> bool:
    """La raison d'un saut est-elle couverte par l'un des motifs autorisés ?"""
    return any(re.fullmatch(s.motif, raison) for s in SAUTS_AUTORISES)


def raison_du_saut(rapport: pytest.CollectReport | pytest.TestReport) -> str:
    """La raison lisible d'un rapport sauté, sans le préfixe « Skipped: »."""
    longrepr = rapport.longrepr
    if isinstance(longrepr, tuple) and len(longrepr) == 3:
        raison = str(longrepr[2])
    else:
        raison = str(longrepr)
    return raison.removeprefix("Skipped: ")
