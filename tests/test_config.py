"""Tests du chargement de configuration (L1.1)."""

from datetime import date
from pathlib import Path

import pytest

from ourouler.config import Periode, charger, depuis_dict
from ourouler.erreurs import ErreurConfig

# Point fictif en mer, loin de toute ville : jamais une coordonnée réelle.
BASE = {
    "depart": {"nom": "Test", "latitude": 0.0, "longitude": 0.0},
    "cycliste": {"masse_kg": 80, "ftp_w": 250},
}


def test_config_minimale():
    c = depuis_dict(BASE)
    assert c.depart.latitude == 0.0
    assert c.cycliste.ftp_w == 250
    assert [v.nom for v in c.velos] == ["Route"]
    assert c.meteo.directions == 8
    assert c.historique_depuis == date(2023, 12, 1)
    assert not c.intervals.renseigne


def test_velos_et_periodes():
    d = dict(BASE)
    d["velos"] = [
        {"nom": "Route", "usage": "route", "masse_kg": 9, "intervals_gear": "rcr",
         "periodes": [{"debut": "2024-01-01", "fin": "2024-06-30"}, {"debut": "2025-01-01"}]},
        {"nom": "CLM", "usage": "clm"},
    ]
    c = depuis_dict(d)
    assert c.velo("route").intervals_gear == "rcr"
    assert c.velo("Route").periodes[1] == Periode(date(2025, 1, 1), None)
    assert c.velo("Route").periodes[0].contient(date(2024, 3, 1))
    assert not c.velo("Route").periodes[0].contient(date(2024, 7, 1))
    assert c.velo("Route").periodes[1].contient(date(2030, 1, 1))
    with pytest.raises(ErreurConfig, match="aucun vélo"):
        c.velo("Gravel")


@pytest.mark.parametrize(
    "casse, message",
    [
        ({"cycliste": BASE["cycliste"]}, r"\[depart\] manquante"),
        ({"depart": {"nom": "x", "latitude": 0}, "cycliste": BASE["cycliste"]}, "longitude manquant"),
        ({"depart": {"latitude": 95, "longitude": 0}, "cycliste": BASE["cycliste"]}, "hors de"),
        ({"depart": {"latitude": "nord", "longitude": 0}, "cycliste": BASE["cycliste"]}, "nombre attendu"),
        ({**BASE, "velos": [{"nom": "X", "usage": "vtt"}]}, "usage"),
        ({**BASE, "velos": [{"usage": "route"}]}, "nom manquant"),
        ({**BASE, "historique_depuis": "hier"}, "AAAA-MM-JJ"),
    ],
)
def test_erreurs_nommees(casse, message):
    with pytest.raises(ErreurConfig, match=message):
        depuis_dict(casse)


def test_charger_fichier(tmp_path: Path):
    f = tmp_path / "c.toml"
    f.write_text(
        '[depart]\nnom="Test"\nlatitude=0.0\nlongitude=0.0\n[cycliste]\nmasse_kg=80\nftp_w=250\n'
        '[cache]\ndossier="~/x"\n',
        encoding="utf-8",
    )
    c = charger(f)
    assert c.cache.dossier.is_absolute(), "le cœur doit recevoir un chemin déjà développé"


def test_charger_absent_ou_invalide(tmp_path: Path):
    with pytest.raises(ErreurConfig, match="introuvable"):
        charger(tmp_path / "absent.toml")
    f = tmp_path / "c.toml"
    f.write_text("[depart\n", encoding="utf-8")
    with pytest.raises(ErreurConfig, match="TOML invalide"):
        charger(f)


# --- invariant de sécurité : la clé d'API ne s'imprime jamais ---------------

CLE_FACTICE = "cle-factice-ne-jamais-imprimer-0123456789"


def _config_avec_cle():
    return depuis_dict({**BASE, "intervals": {"athlete_id": "i000000", "api_key": CLE_FACTICE}})


def test_la_cle_intervals_n_apparait_ni_dans_repr_ni_dans_str():
    """Ce test est l'invariant qui aurait attrapé A2 : `repr(Config)` imprimait la clé en clair."""
    c = _config_avec_cle()
    assert c.intervals.api_key == CLE_FACTICE, "la clé reste lisible par le code qui en a besoin"
    for rendu in (
        repr(c),
        str(c),
        f"{c}",
        repr(c.intervals),
        str(c.intervals),
        f"{c.intervals}",
        str(vars(c)),
        repr(list(vars(c).values())),
        repr({"config": c}),
    ):
        assert CLE_FACTICE not in rendu, f"la clé fuit dans {rendu!r}"
    assert "***" in repr(c.intervals), "le repr doit dire que la clé est renseignée"
    assert "i000000" in repr(c.intervals), "l'identifiant d'athlète n'est pas un secret"


def test_le_repr_sans_cle_ne_pretend_pas_qu_il_y_en_a_une():
    c = depuis_dict(BASE)
    assert "***" not in repr(c.intervals)
    assert not c.intervals.renseigne
