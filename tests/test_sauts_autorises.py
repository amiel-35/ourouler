"""La liste blanche des sauts (`tests/sauts_autorises.py`) et sa garde en CI."""

from __future__ import annotations

import re

import pytest
from sauts_autorises import SAUTS_AUTORISES, saut_autorise


@pytest.mark.parametrize("saut", SAUTS_AUTORISES, ids=lambda s: s.exemple[:40])
def test_chaque_motif_couvre_son_exemple(saut):
    assert re.fullmatch(saut.motif, saut.exemple), saut
    assert saut.pourquoi.strip(), "un motif autorisé dit pourquoi"


@pytest.mark.parametrize(
    "raison",
    [
        "motif inconnu",
        "PostgreSQL local indisponible : le démon Docker ne répond pas — le démarrer",
        "could not import 'ourouler.physique.modele': No module named 'ourouler.physique.modele'",
        # un motif ne vaut que pour la raison entière, pas pour un morceau
        "puissance au-delà de la borne de bissection, et autre chose",
        "GET /api/v1/nouvelle_route : pas de modèle déclaré",
    ],
)
def test_un_motif_hors_liste_n_est_pas_autorise(raison):
    assert not saut_autorise(raison)
