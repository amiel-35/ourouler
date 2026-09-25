"""Tests du chargement de configuration (L1.1)."""

from datetime import date
from pathlib import Path

import pytest

from ourouler.config import (
    CACHE_DEFAUT,
    Depart,
    ParametresCache,
    Periode,
    charger,
    depuis_dict,
)
from ourouler.erreurs import ErreurConfig
from ourouler.seance.modele import ZONES_PUISSANCE_DEFAUT
from ourouler.seance.zones import POSITION_ENDURANCE_DEFAUT

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


def test_cycliste_prenom_nom_absents_se_chargent_vides():
    """Une configuration écrite avant ce lot n'a ni prénom ni nom — elle continue de se charger.

    C'est l'obligation qui est nouvelle (assistant), pas le chargement : voir
    la docstring de `Cycliste.prenom`. Inventer un nom à la place violerait la
    règle absolue 1 ; refuser le chargement casserait toute configuration
    existante, y compris celle du mainteneur.
    """
    c = depuis_dict(BASE)
    assert c.cycliste.prenom == ""
    assert c.cycliste.nom == ""


def test_cycliste_prenom_nom_fournis_se_chargent():
    c = depuis_dict({**BASE, "cycliste": {**BASE["cycliste"], "prenom": "Camille", "nom": "Ruiz"}})
    assert c.cycliste.prenom == "Camille"
    assert c.cycliste.nom == "Ruiz"


def test_cycliste_ftp_w_absente_se_charge_a_none():
    """Facultative depuis le 19/09/2026 — un profil qui n'a pas encore franchi
    T3/T4 de l'accueil, pas une configuration fautive."""
    sans_ftp = {**BASE, "cycliste": {"masse_kg": BASE["cycliste"]["masse_kg"]}}
    c = depuis_dict(sans_ftp)
    assert c.cycliste.ftp_w is None
    assert c.cycliste.masse_kg == 80


def test_cycliste_ftp_w_chaine_vide_se_charge_a_none():
    """Ce qu'un profil JSON écrit pour « je corrige, sans avoir encore tapé de
    chiffre » (`api/depots.py`) — traité comme une absence, pas comme `0`."""
    c = depuis_dict({**BASE, "cycliste": {"masse_kg": 80, "ftp_w": ""}})
    assert c.cycliste.ftp_w is None


def test_cycliste_ftp_w_fournie_reste_bornee():
    """L'absence devient possible, mais une valeur donnée garde ses bornes d'avant."""
    with pytest.raises(ErreurConfig, match="ftp_w"):
        depuis_dict({**BASE, "cycliste": {"masse_kg": 80, "ftp_w": 10}})
    with pytest.raises(ErreurConfig, match="ftp_w"):
        depuis_dict({**BASE, "cycliste": {"masse_kg": 80, "ftp_w": 2000}})
    c = depuis_dict({**BASE, "cycliste": {"masse_kg": 80, "ftp_w": 250}})
    assert c.cycliste.ftp_w == 250


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


# --- environnement (contrat de l'hébergé minimal) ---------------------------
#
# Le contrat (docs/heberge_minimal_contrat.md, § « Les secrets ») fait venir
# de l'environnement le point de départ, la clé Intervals et le serveur
# BRouter — jamais commités, jamais dans une image. `environ=` est injectable
# pour ne jamais dépendre de ce qui traîne sur la machine qui exécute le test
# (règle absolue 3 : pas de réseau, et par extension pas de dépendance à un
# état extérieur non maîtrisé).


def _toml_minimal(tmp_path: Path, extra: str = "") -> Path:
    f = tmp_path / "c.toml"
    f.write_text(
        '[depart]\nnom="Test"\nlatitude=1.0\nlongitude=2.0\n'
        "[cycliste]\nmasse_kg=80\nftp_w=250\n" + extra,
        encoding="utf-8",
    )
    return f


def test_environnement_complete_depart_intervals_brouter(tmp_path: Path):
    f = _toml_minimal(tmp_path)
    environ = {
        "OUROULER_DEPART_LATITUDE": "10.0",
        "OUROULER_DEPART_LONGITUDE": "-30.0",
        "OUROULER_INTERVALS_API_KEY": "cle-factice-test",
        "OUROULER_INTERVALS_ATHLETE_ID": "i999999",
        "OUROULER_BROUTER_URL": "https://brouter.exemple.invalid",
        "OUROULER_BROUTER_UTILISATEUR": "amiel",
        "OUROULER_BROUTER_MOT_DE_PASSE": "secret-factice",
    }
    c = charger(f, environ=environ)
    assert (c.depart.latitude, c.depart.longitude) == (10.0, -30.0)
    assert c.depart.nom == "Test", "la variable DEPART_NOM n'est pas posée : le TOML décide"
    assert c.intervals.api_key == "cle-factice-test"
    assert c.intervals.athlete_id == "i999999"
    assert c.brouter.url == "https://brouter.exemple.invalid"
    assert c.brouter.utilisateur == "amiel"
    assert c.brouter.mot_de_passe == "secret-factice"


def test_environnement_absent_laisse_le_toml_inchange(tmp_path: Path):
    f = _toml_minimal(tmp_path, '[intervals]\napi_key="depuis-toml"\n')
    c = charger(f, environ={})
    assert c.depart.latitude == 1.0
    assert c.intervals.api_key == "depuis-toml"


def test_environnement_present_ecrase_le_toml(tmp_path: Path):
    f = _toml_minimal(tmp_path, '[intervals]\napi_key="depuis-toml"\n')
    c = charger(f, environ={"OUROULER_INTERVALS_API_KEY": "depuis-env"})
    assert c.intervals.api_key == "depuis-env"
    assert c.depart.latitude == 1.0, "non touché : seule la variable posée l'emporte"


def test_variable_vide_vaut_variable_absente(tmp_path: Path):
    """Le piège du compose : l'hébergeur transmet toutes les variables déclarées,
    vides comprises. Une chaîne vide ne doit pas écraser un TOML valide —
    sinon le conteneur meurt au démarrage sur sa propre configuration."""
    f = _toml_minimal(tmp_path, '[intervals]\napi_key="depuis-toml"\n')
    c = charger(
        f,
        environ={
            "OUROULER_DEPART_NOM": "",
            "OUROULER_DEPART_LATITUDE": "",
            "OUROULER_DEPART_LONGITUDE": "",
            "OUROULER_INTERVALS_API_KEY": "",
            "OUROULER_BROUTER_URL": "",
        },
    )
    assert (c.depart.nom, c.depart.latitude, c.depart.longitude) == ("Test", 1.0, 2.0)
    assert c.intervals.api_key == "depuis-toml"


def test_environnement_peut_construire_depart_sans_section_toml(tmp_path: Path):
    """Cas du conteneur : aucune coordonnée dans le fichier, tout vient de l'environnement."""
    f = tmp_path / "c.toml"
    f.write_text("[cycliste]\nmasse_kg=80\nftp_w=250\n", encoding="utf-8")
    c = charger(
        f,
        environ={
            "OUROULER_DEPART_NOM": "Conteneur",
            "OUROULER_DEPART_LATITUDE": "10.0",
            "OUROULER_DEPART_LONGITUDE": "-30.0",
        },
    )
    assert c.depart == Depart(nom="Conteneur", latitude=10.0, longitude=-30.0)


def test_charger_lit_os_environ_par_defaut(tmp_path: Path, monkeypatch):
    """Sans `environ=`, `charger()` lit bien `os.environ` — le paramètre par
    défaut n'est pas mort code."""
    monkeypatch.setenv("OUROULER_INTERVALS_API_KEY", "depuis-os-environ")
    f = _toml_minimal(tmp_path)
    assert charger(f).intervals.api_key == "depuis-os-environ"


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
    # Les quatre valeurs du contrat de sprint §0. « sortie club » est
    # redondante avec « club » (la recherche est par sous-chaîne), mais le
    # défaut doit dire ce que le contrat écrit.
    assert depuis_dict(BASE).calibration.mots_groupe == (
        "club",
        "groupe",
        "peloton",
        "sortie club",
    )
    with pytest.raises(ErreurConfig, match=r"evitements\[0\]\] latitude"):
        depuis_dict({**BASE, "evitements": [{"longitude": 0}]})


def test_mots_groupe_chaine_nue_refusee():
    with pytest.raises(ErreurConfig, match="mots_groupe"):
        depuis_dict({**BASE, "calibration": {"mots_groupe": "club"}})
    c = depuis_dict({**BASE, "calibration": {"mots_groupe": [" Club ", ""]}})
    assert c.calibration.mots_groupe == ("club",)


def test_seance_et_tenue():
    d = dict(BASE)
    d["seance"] = {
        "elasticite_z2_max": 0.3,
        "elasticite_calme_max": 2.0,
        "demi_tour_penalite": 2.5,
    }
    d["tenue"] = {"bornes_c": [2, 8, 14, 21, 29], "vent_veste_kmh": 25}
    c = depuis_dict(d)
    assert c.seance.elasticite_z2_max == 0.3 and c.seance.demi_tour_penalite == 2.5
    assert c.seance.elasticite_calme_max == 2.0
    assert c.tenue.bornes_c == (2.0, 8.0, 14.0, 21.0, 29.0) and c.tenue.vent_veste_kmh == 25
    defauts = depuis_dict(BASE)
    assert defauts.seance.elasticite_z2_min == -0.05
    # Q14 : le retour au calme absorbe, sa fenêtre est bien plus large que
    # celle de la Z2 d'ouverture, qui est un levier de placement.
    assert defauts.seance.elasticite_calme_max == 1.5
    assert defauts.seance.elasticite_calme_min == -0.05
    assert defauts.seance.elasticite_calme_max > defauts.seance.elasticite_z2_max
    assert defauts.seance.puissance_endurance_pct == 0.60
    assert defauts.seance.seuil_recuperation_pct == 0.75
    assert defauts.tenue.bornes_pluie_mmh == (0.2, 0.5, 1.0)
    with pytest.raises(ErreurConfig, match="croissantes"):
        depuis_dict({**BASE, "tenue": {"bornes_c": [9, 3]}})
    with pytest.raises(ErreurConfig, match="bornes_c"):
        depuis_dict({**BASE, "tenue": {"bornes_c": "froid"}})


def test_tenues_configurees():
    d = {**BASE, "tenue": {"tenues": {"froid": ["collant", "veste"], "chaud": ["cuissard"]}}}
    c = depuis_dict(d)
    assert c.tenue.tenue_de("froid") == ("collant", "veste")
    assert c.tenue.tenue_de("canicule") is None, "une catégorie absente garde le défaut du code"
    assert depuis_dict(BASE).tenue.tenues == ()
    with pytest.raises(ErreurConfig, match="tenues.froid"):
        depuis_dict({**BASE, "tenue": {"tenues": {"froid": "collant"}}})

def test_puissance_endurance_pct_est_lue_et_bornee():
    """L'ancienne clé reste lisible, et rend **exactement** la même puissance.

    Depuis la décision 7 elle n'est plus stockée : elle est convertie en
    position à la lecture puis redérivée. Une configuration existante ne doit
    rien voir de ce changement — c'est la règle absolue 5 appliquée à une
    valeur mesurée (Q11).
    """
    d = dict(BASE)
    d["seance"] = {"puissance_endurance_pct": 0.65}
    assert depuis_dict(d).seance.puissance_endurance_pct == 0.65
    for hors_bornes in (0.2, 0.39, 0.81, 1.5):
        d["seance"] = {"puissance_endurance_pct": hors_bornes}
        with pytest.raises(ErreurConfig, match="puissance_endurance_pct"):
            depuis_dict(d)
    d["seance"] = {"puissance_endurance_pct": "beaucoup"}
    with pytest.raises(ErreurConfig, match="puissance_endurance_pct"):
        depuis_dict(d)


@pytest.mark.parametrize("ancienne", [0.40, 0.55, 0.60, 0.655, 0.70, 0.80])
def test_toute_ancienne_puissance_endurance_se_convertit_a_l_identique(ancienne):
    """Aucune valeur acceptable hier n'est écrêtée aujourd'hui.

    Les bornes de la position ([−1, 2]) ont été choisies pour couvrir
    exactement l'ancienne plage ([0,40 ; 0,80]) : la migration ne perd rien.
    """
    c = depuis_dict({**BASE, "seance": {"puissance_endurance_pct": ancienne}})
    assert c.seance.puissance_endurance_pct == ancienne
    assert -1.0 <= c.seance.position_zone <= 2.0


def test_la_position_est_ce_qui_est_stocke_et_l_endurance_en_decoule():
    c = depuis_dict({**BASE, "seance": {"position_zone": 0.5}})
    assert c.seance.position_zone == 0.5
    # Milieu de la Z2 par défaut : (0,56 + 0,75) / 2.
    assert c.seance.puissance_endurance_pct == pytest.approx(0.655)


def test_position_zone_l_emporte_sur_l_ancienne_cle():
    """Les deux clés dans le même fichier : la nouvelle décide, sans erreur.

    Refuser le chargement pour une clé oubliée serait la pire des réponses —
    la seule chose qui compte est qu'il n'y ait plus deux sources de vérité.
    """
    c = depuis_dict({**BASE, "seance": {"position_zone": 0.0, "puissance_endurance_pct": 0.80}})
    assert c.seance.position_zone == 0.0
    assert c.seance.puissance_endurance_pct == pytest.approx(0.56)


@pytest.mark.parametrize("hors_bornes", [-1.5, 2.5])
def test_position_zone_hors_bornes_est_refusee(hors_bornes):
    with pytest.raises(ErreurConfig, match="position_zone"):
        depuis_dict({**BASE, "seance": {"position_zone": hors_bornes}})


def test_une_position_hors_bande_reste_lisible_et_n_est_pas_ecretee():
    """Décision 8 : hors de [0, 1] se voit, ça ne se corrige pas en douce."""
    c = depuis_dict({**BASE, "seance": {"position_zone": -0.2737}})
    assert c.seance.position_zone == -0.2737
    assert c.seance.puissance_endurance_pct == pytest.approx(0.508, abs=1e-4)


def test_les_zones_de_puissance_sont_editables():
    zones = [[0.0, 0.50], [0.51, 0.70], [0.71, 0.85], [0.86, 1.0], [1.01, 2.0]]
    c = depuis_dict({**BASE, "seance": {"zones": zones, "position_zone": 0.5}})
    assert c.seance.zones_pct == tuple(tuple(z) for z in zones)
    # L'endurance suit la table éditée, sans qu'on ait rien d'autre à toucher.
    assert c.seance.puissance_endurance_pct == pytest.approx((0.51 + 0.70) / 2)


def test_une_ancienne_puissance_endurance_se_situe_dans_la_table_editee():
    """La conversion lit la Z2 **configurée**, pas celle de Coggan."""
    zones = [[0.0, 0.50], [0.51, 0.70], [0.71, 0.85], [0.86, 1.0], [1.01, 2.0]]
    c = depuis_dict({**BASE, "seance": {"zones": zones, "puissance_endurance_pct": 0.60}})
    assert c.seance.puissance_endurance_pct == 0.60
    assert c.seance.position_zone == pytest.approx((0.60 - 0.51) / (0.70 - 0.51))


def test_les_zones_par_defaut_sont_la_table_du_code():
    assert depuis_dict(BASE).seance.zones_pct == ZONES_PUISSANCE_DEFAUT
    assert depuis_dict(BASE).seance.position_zone == POSITION_ENDURANCE_DEFAUT


@pytest.mark.parametrize(
    ("zones", "motif"),
    [
        ("Coggan", "zones"),
        ([[0.0, 0.55], [0.56, 0.75]], "trois zones"),
        ([[0.0, 0.55], [0.56, 0.75], [0.70, 0.90]], "chevauchent"),
        ([[0.0, 0.55], [0.60, 0.60], [0.76, 2.0]], "haut doit"),
        ([[0.0, 0.55], [0.56], [0.76, 2.0]], "paire"),
        ([[0.0, 0.55], [0.56, "haut"], [0.76, 2.0]], "haut"),
        ([[0.0, 0.55], [0.56, 9.0], [0.76, 2.0]], "hors de"),
    ],
)
def test_une_table_de_zones_fautive_est_refusee_en_nommant_le_champ(zones, motif):
    """Une table de configuration fausse se dit ; elle ne se remplace pas en silence.

    `seance.intervals._zones` se rabat, lui, sur la table par défaut — mais il
    traite des données d'API, qu'on ne contrôle pas. Ici c'est le cycliste qui
    a écrit le fichier.
    """
    with pytest.raises(ErreurConfig, match=motif):
        depuis_dict({**BASE, "seance": {"zones": zones}})


def test_seuil_recuperation_pct_est_lu_et_borne():
    """Sous cette part de FTP, une étape n'est pas un bloc (cascade de typage L4.1)."""
    d = dict(BASE)
    d["seance"] = {"seuil_recuperation_pct": 0.8}
    assert depuis_dict(d).seance.seuil_recuperation_pct == 0.8
    for hors_bornes in (0.1, 0.49, 0.91, 2.0):
        d["seance"] = {"seuil_recuperation_pct": hors_bornes}
        with pytest.raises(ErreurConfig, match="seuil_recuperation_pct"):
            depuis_dict(d)


def test_tolerance_egalite_est_lue_et_bornee():
    """Préférence du cycliste (L5.1) : vent contre pluie à note de placement égale.

    0.0 = le vent tranche toujours ; le défaut du code (0.15) doit rester
    accessible sans qu'aucune configuration ne le touche (`test_seance_et_tenue`
    le vérifie déjà indirectement en ne passant pas ce champ).
    """
    d = dict(BASE)
    d["seance"] = {"tolerance_egalite": 0.05}
    assert depuis_dict(d).seance.tolerance_egalite == 0.05
    d["seance"] = {"tolerance_egalite": 0.0}
    assert depuis_dict(d).seance.tolerance_egalite == 0.0, "0 = le vent tranche toujours"
    assert depuis_dict(BASE).seance.tolerance_egalite == 0.15
    for hors_bornes in (-0.01, 0.51):
        d["seance"] = {"tolerance_egalite": hors_bornes}
        with pytest.raises(ErreurConfig, match="tolerance_egalite"):
            depuis_dict(d)


def test_config_example_tient_la_promesse_de_sa_position():
    """`config.example.toml` est le contrat écrit : sa position rend bien 0,60.

    Le fichier est commité, lui : si quelqu'un y retouche `position_zone` sans
    voir ce qu'elle vaut en puissance d'endurance, ce test le lui dit.
    """
    c = charger(Path(__file__).resolve().parents[1] / "config.example.toml", environ={})
    assert c.seance.zones_pct == ZONES_PUISSANCE_DEFAUT
    assert c.seance.puissance_endurance_pct == 0.60


# --- facteur compteur par vélo (lot F0.6) ------------------------------------


def test_velo_sans_facteur_compteur_le_laisse_absent():
    """`None` et non un chiffre : c'est ce qui laisse le cœur dériver le défaut
    du modèle et de la masse, et l'écran dire que ce n'est pas une mesure."""
    assert depuis_dict(BASE).velo("Route").facteur_compteur is None


def test_velo_facteur_compteur_lu_tel_quel():
    c = depuis_dict({**BASE, "velos": [{"nom": "Route", "facteur_compteur": 0.83}]})
    assert c.velo("Route").facteur_compteur == 0.83


def test_facteur_compteur_est_par_velo_et_non_par_cycliste():
    """Le chrono et la route n'ont ni la même aérodynamique ni les mêmes
    parcours : deux vélos portent deux facteurs indépendants."""
    c = depuis_dict(
        {
            **BASE,
            "velos": [
                {"nom": "Route", "facteur_compteur": 0.83},
                {"nom": "Chrono", "usage": "clm", "facteur_compteur": 0.90},
            ],
        }
    )
    assert c.velo("Route").facteur_compteur == 0.83
    assert c.velo("Chrono").facteur_compteur == 0.90


@pytest.mark.parametrize("valeur", [0.0, 0.39, 1.21, 87])
def test_facteur_compteur_hors_bornes(valeur):
    """87 au lieu de 0,87 est la faute qu'on attend : elle doit nommer le champ
    plutôt que de sortir une moyenne compteur dix fois trop haute."""
    with pytest.raises(ErreurConfig) as e:
        depuis_dict({**BASE, "velos": [{"nom": "Route", "facteur_compteur": valeur}]})
    message = str(e.value)
    assert "facteur_compteur" in message and "velos[0]" in message, message


def test_facteur_compteur_de_type_inattendu():
    with pytest.raises(ErreurConfig, match="facteur_compteur"):
        depuis_dict({**BASE, "velos": [{"nom": "Route", "facteur_compteur": "rapide"}]})


def test_le_cache_par_defaut_est_un_chemin_absolu():
    """Le `~` se développe dans `config.py`, et nulle part ailleurs.

    Il était écrit `Path("~/.cache/ourouler")` et n'était jamais résolu : tout
    appelant qui oubliait `.expanduser()` créait un dossier **littéral** nommé
    `~` dans le répertoire courant. La suite de tests en fabriquait un à la
    racine du dépôt à chaque exécution, et personne ne le voyait.

    La règle absolue 2 fait de `config.py` le seul endroit du cœur autorisé à
    résoudre un chemin utilisateur : ce test tient cette frontière.
    """
    assert CACHE_DEFAUT.is_absolute()
    assert "~" not in str(CACHE_DEFAUT)
    assert ParametresCache().dossier == CACHE_DEFAUT


def test_un_tilde_ecrit_a_la_main_dans_le_toml_est_developpe(tmp_path: Path):
    """Un TOML écrit à la main porte presque toujours un `~`."""
    chemin = tmp_path / "c.toml"
    chemin.write_text(
        '[depart]\nnom = "Ailleurs"\nlatitude = 0.0\nlongitude = 0.0\n'
        '[cycliste]\nmasse_kg = 70\nftp_w = 200\n'
        '[cache]\ndossier = "~/ailleurs/cache"\n',
        encoding="utf-8",
    )
    config = charger(chemin)
    assert config.cache.dossier.is_absolute()
    assert "~" not in str(config.cache.dossier)
    assert config.cache.dossier == Path("~/ailleurs/cache").expanduser()


# --- catégorie de pneu par vélo (L9.1) ----------------------------------------


def test_velo_sans_pneu_le_laisse_absent():
    """`None` : le Crr reste celui du jeu de l'usage, comme avant L9.1."""
    assert depuis_dict(BASE).velo("Route").pneu is None


def test_velo_pneu_lu_et_normalise():
    c = depuis_dict({**BASE, "velos": [{"nom": "Route", "pneu": " Course_Rapide "}]})
    assert c.velo("Route").pneu == "course_rapide"


@pytest.mark.parametrize("vide", ["", "   ", None])
def test_velo_pneu_vide_vaut_absent(vide):
    c = depuis_dict({**BASE, "velos": [{"nom": "Route", "pneu": vide}]})
    assert c.velo("Route").pneu is None


def test_velo_pneu_inconnu_est_refuse_et_nomme():
    with pytest.raises(ErreurConfig, match="pneu"):
        depuis_dict({**BASE, "velos": [{"nom": "Route", "pneu": "slick de piste"}]})


def test_les_categories_de_pneu_de_la_config_sont_celles_de_la_litterature():
    """Deux listes, une vérité : la configuration valide sans importer le
    modèle physique, la littérature porte les Crr — elles ne divergent pas."""
    from ourouler.config import PNEUS_VELO
    from ourouler.physique.litterature import PNEUS

    assert set(PNEUS_VELO) == set(PNEUS)


def test_l_exemple_de_configuration_documente_le_pneu():
    texte = (Path(__file__).parent.parent / "config.example.toml").read_text(encoding="utf-8")
    assert "# pneu = " in texte
    from ourouler.config import PNEUS_VELO

    for categorie in PNEUS_VELO:
        assert categorie in texte
