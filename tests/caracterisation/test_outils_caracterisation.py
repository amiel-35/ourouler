"""Les outils des références se vérifient eux-mêmes : un filet qui accepte tout ne retient rien."""

from __future__ import annotations

from pathlib import Path

import pytest
from outils_caracterisation import (
    TOLERANCE_RELATIVE,
    _proches,
    arrondir,
    comparer_a_la_reference,
    normaliser,
)


def test_la_tolerance_absorbe_un_ulp_mais_pas_une_derive():
    assert _proches({"x": 1.0}, {"x": 1.0 + 2e-16})
    assert not _proches({"x": 1.0}, {"x": 1.0 + 1e-9}), "une dérive de 1e-9 doit se voir"
    assert not _proches({"x": 0.0}, {"x": 1e-300}), "un zéro reste un zéro"
    assert not _proches({"x": 1}, {"x": True}), "un booléen n'est pas un entier"
    assert not _proches([1.0, 2.0], [1.0]), "la structure compte"
    assert TOLERANCE_RELATIVE < 1e-9


def test_la_normalisation_remplace_chemins_et_aleas():
    brut = {
        "/tmp/abc/x.gpx": "/tmp/abc/cache/1b4e28ba-2fa1-11d2-883f-0016d3cca427.json",
        "jeton": "deadbeefdeadbeefdeadbeefdeadbeef",
    }
    assert normaliser(brut, {"/tmp/abc": "<TMP>"}) == {
        "<TMP>/x.gpx": "<TMP>/cache/<UUID>.json",
        "jeton": "<HEX>",
    }


def test_l_arrondi_garde_les_chiffres_significatifs():
    assert arrondir({"cda": 0.31217541234, "n": 8, "zero": 0.0}, 6) == {
        "cda": 0.312175,
        "n": 8,
        "zero": 0.0,
    }


def test_un_ecart_fait_echouer_avec_le_message_attendu(tmp_path: Path):
    reference = tmp_path / "r.json"
    reference.write_text('{\n  "x": 1\n}\n', encoding="utf-8")
    with pytest.raises(pytest.fail.Exception, match="changement de comportement.*--regenerer-golden"):
        comparer_a_la_reference({"x": 2}, reference, False, "--regenerer-golden")
    comparer_a_la_reference({"x": 1}, reference, False, "--regenerer-golden")
