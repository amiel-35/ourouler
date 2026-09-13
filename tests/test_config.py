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


# --- validations manquantes (point 13 de la relecture) ----------------------


@pytest.mark.parametrize(
    "distances",
    [[-3, 0], [0], [15, -1, 40], [15, 0.0, 40]],
)
def test_distances_km_negatives_ou_nulles_refusees(distances):
    """Elles étaient silencieusement ignorées par `couronne` : table sans couronne, sans mot."""
    with pytest.raises(ErreurConfig) as e:
        depuis_dict({**BASE, "meteo": {"distances_km": distances}})
    message = str(e.value)
    assert "distances_km" in message, "le message doit nommer le champ fautif"
    assert "[meteo]" in message


def test_distances_km_valides_acceptees():
    c = depuis_dict({**BASE, "meteo": {"distances_km": [5, 12.5, 60]}})
    assert c.meteo.distances_km == (5.0, 12.5, 60.0)


def test_distances_km_de_type_inattendu_nommee():
    with pytest.raises(ErreurConfig, match="distances_km"):
        depuis_dict({**BASE, "meteo": {"distances_km": ["quinze"]}})
    with pytest.raises(ErreurConfig, match="distances_km"):
        depuis_dict({**BASE, "meteo": {"distances_km": 15}})


# --- champs numériques : refus nommé plutôt que trace ------------------------
#
# Tous ces cas donnaient une `ValueError` / `TypeError` / `AttributeError`
# brute, donc une trace et le code de sortie 1, là où le contrat de sprint
# demande une `ErreurConfig` nommant le champ (code 2, une ligne).


@pytest.mark.parametrize("valeur", ["huit", "", None, [8], {"n": 8}, 8.5])
def test_directions_de_type_inattendu_nommee(valeur):
    with pytest.raises(ErreurConfig) as e:
        depuis_dict({**BASE, "meteo": {"directions": valeur}})
    assert "directions" in str(e.value) and "[meteo]" in str(e.value)


@pytest.mark.parametrize("valeur", [0, 1, 5, 7, 9, 12, 17, 32, -8])
def test_directions_hors_des_valeurs_acceptees(valeur):
    """Le contrat ne connaît que 8 et 16 secteurs : le reste est refusé au chargement."""
    if valeur in (8, 16):  # garde-fou si le contrat évolue
        return
    with pytest.raises(ErreurConfig, match="directions"):
        depuis_dict({**BASE, "meteo": {"directions": valeur}})


@pytest.mark.parametrize("valeur", [8, 16])
def test_directions_acceptees(valeur):
    assert depuis_dict({**BASE, "meteo": {"directions": valeur}}).meteo.directions == valeur


@pytest.mark.parametrize("valeur", ["deux", "", None, [2], 2.5])
def test_horizon_h_de_type_inattendu_nomme(valeur):
    with pytest.raises(ErreurConfig) as e:
        depuis_dict({**BASE, "meteo": {"horizon_h": valeur}})
    assert "horizon_h" in str(e.value) and "[meteo]" in str(e.value)


@pytest.mark.parametrize("valeur", [0, -1, 49, 1000])
def test_horizon_h_hors_bornes(valeur):
    """Entre 1 et 48 h : au-delà, AROME HD n'a plus rien à dire."""
    with pytest.raises(ErreurConfig, match="horizon_h"):
        depuis_dict({**BASE, "meteo": {"horizon_h": valeur}})


@pytest.mark.parametrize("valeur", [1, 6, 24, 48])
def test_horizon_h_dans_les_bornes(valeur):
    assert depuis_dict({**BASE, "meteo": {"horizon_h": valeur}}).meteo.horizon_h == valeur


@pytest.mark.parametrize("champ", ["masse_kg", "cda_m2"])
def test_velo_champ_numerique_de_type_inattendu(champ):
    with pytest.raises(ErreurConfig) as e:
        depuis_dict({**BASE, "velos": [{"nom": "Route", champ: "leger"}]})
    message = str(e.value)
    assert champ in message and "velos[0]" in message, f"le champ fautif doit être nommé : {message}"


def test_velo_masse_kg_valide_acceptee():
    c = depuis_dict({**BASE, "velos": [{"nom": "Route", "masse_kg": 7.8, "cda_m2": 0.32}]})
    assert c.velo("Route").masse_kg == 7.8 and c.velo("Route").cda_m2 == 0.32


@pytest.mark.parametrize(
    "section, champ",
    [
        ("depart", "latitude"),
        ("depart", "longitude"),
        ("cycliste", "masse_kg"),
        ("cycliste", "ftp_w"),
    ],
)
@pytest.mark.parametrize("valeur", [True, False])
def test_un_booleen_n_est_pas_un_nombre(section, champ, valeur):
    """`latitude = true` valait 1.0 : `bool` hérite de `int`, donc `float(True) == 1.0`.

    La commande partait interroger Open-Meteo à une latitude de 1° sans un mot.
    """
    d = {**BASE, section: {**BASE[section], champ: valeur}}
    with pytest.raises(ErreurConfig) as e:
        depuis_dict(d)
    assert champ in str(e.value) and "booléen" in str(e.value)


def test_un_booleen_n_est_pas_un_entier():
    for champ in ("directions", "horizon_h"):
        with pytest.raises(ErreurConfig) as e:
            depuis_dict({**BASE, "meteo": {champ: True}})
        assert champ in str(e.value) and "booléen" in str(e.value)


@pytest.mark.parametrize("valeur", [None, [], ["depart"], "texte", 42, 3.5, True])
def test_depuis_dict_d_autre_chose_qu_un_dict(valeur):
    """Une liste finissait en `AttributeError: 'list' object has no attribute 'get'`."""
    with pytest.raises(ErreurConfig, match="dictionnaire attendu"):
        depuis_dict(valeur)


def test_historique_depuis_en_datetime_toml_accepte(tmp_path: Path):
    """`historique_depuis = 2023-12-01T00:00:00` est du TOML légal : il donnait un `datetime`.

    La première comparaison de période levait alors
    `TypeError: '<=' not supported between date and datetime` — trace et code
    1 pour une faute de frappe de configuration.
    """
    f = tmp_path / "c.toml"
    f.write_text(
        '[depart]\nnom="Test"\nlatitude=0.0\nlongitude=0.0\n'
        "[cycliste]\nmasse_kg=80\nftp_w=250\n"
        "historique_depuis = 2023-12-01T00:00:00\n",
        encoding="utf-8",
    )
    c = charger(f)
    assert c.historique_depuis == date(2023, 12, 1)
    assert type(c.historique_depuis) is date, "un datetime casse la comparaison de périodes"


def test_historique_depuis_en_datetime_comparable_a_une_periode():
    """Le vrai symptôme : la comparaison qui levait `TypeError`."""
    from datetime import datetime as _datetime

    c = depuis_dict({**BASE, "historique_depuis": _datetime(2023, 12, 1, 0, 0)})
    assert Periode(debut=date(2024, 1, 1)).contient(date(2024, 6, 1))
    # La comparaison directe est celle qui plantait.
    assert c.historique_depuis <= date(2024, 1, 1)


@pytest.mark.parametrize(
    "valeur, attendu",
    [
        ("2024-02-29", date(2024, 2, 29)),
        (date(2024, 3, 1), date(2024, 3, 1)),
        ("2024-03-01T06:30:00", date(2024, 3, 1)),
    ],
)
def test_historique_depuis_formes_acceptees(valeur, attendu):
    c = depuis_dict({**BASE, "historique_depuis": valeur})
    assert c.historique_depuis == attendu
    assert type(c.historique_depuis) is date


def test_periodes_en_datetime_toml_aussi(tmp_path: Path):
    """Même piège dans les périodes de vélo, même correction."""
    f = tmp_path / "c.toml"
    f.write_text(
        '[depart]\nnom="Test"\nlatitude=0.0\nlongitude=0.0\n'
        "[cycliste]\nmasse_kg=80\nftp_w=250\n"
        '[[velos]]\nnom="Route"\n'
        "periodes = [{ debut = 2024-01-01T00:00:00, fin = 2024-06-30T23:59:59 }]\n",
        encoding="utf-8",
    )
    periode = charger(f).velo("Route").periodes[0]
    assert (periode.debut, periode.fin) == (date(2024, 1, 1), date(2024, 6, 30))
    assert periode.contient(date(2024, 3, 15))


def test_brouter_et_boucle():
    d = dict(BASE)
    d["brouter"] = {"url": "https://exemple.invalid/", "utilisateur": "u", "mot_de_passe": "secret-xyz"}
    d["boucle"] = {"vitesse_moyenne_kmh": 30, "sens": "antihoraire", "candidates": 3}
    d["velos"] = [{"nom": "Route", "capteur_puissance": "CAPTEUR 0001", "intervals_gear_id": "b1"}]
    c = depuis_dict(d)
    assert c.brouter.renseigne and c.brouter.url == "https://exemple.invalid"
    assert "secret-xyz" not in repr(c) and "secret-xyz" not in repr(c.brouter)
    assert c.boucle.sens == "antihoraire" and c.boucle.candidates == 3
    assert c.velo("Route").capteur_puissance == "CAPTEUR 0001"
    assert not depuis_dict(BASE).brouter.renseigne
    with pytest.raises(ErreurConfig, match=r"\[boucle\] sens"):
        depuis_dict({**BASE, "boucle": {"sens": "gauche"}})


def test_calibration_et_evitements():
    d = dict(BASE)
    d["calibration"] = {"mots_groupe": ["Club", "sortie groupe"], "part_validation": 0.3}
    d["evitements"] = [{"nom": "carrefour", "latitude": 0.5, "longitude": 0.5, "rayon_m": 150}]
    d["velos"] = [{"nom": "Route", "crr": 0.004}]
    c = depuis_dict(d)
    assert c.calibration.mots_groupe == ("club", "sortie groupe") and c.calibration.part_validation == 0.3
    assert c.evitements[0].rayon_m == 150 and c.evitements[0].nom == "carrefour"
    assert c.velo("Route").crr == 0.004
    assert depuis_dict(BASE).calibration.mots_groupe == ("club", "groupe", "peloton")
    with pytest.raises(ErreurConfig, match=r"evitements\[0\]\] latitude"):
        depuis_dict({**BASE, "evitements": [{"longitude": 0}]})


def test_mots_groupe_chaine_nue_refusee():
    with pytest.raises(ErreurConfig, match="mots_groupe"):
        depuis_dict({**BASE, "calibration": {"mots_groupe": "club"}})
    c = depuis_dict({**BASE, "calibration": {"mots_groupe": [" Club ", ""]}})
    assert c.calibration.mots_groupe == ("club",)
