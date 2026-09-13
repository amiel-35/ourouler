"""Le client d'archive météo : lecture, tolérance aux trous, mémoïsation.

Aucun accès réseau : le service est un `MockTransport` qui rend des réponses
fabriquées. Aucune coordonnée réelle : les points sont au large de (0, 0).
"""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

import httpx
import pytest

from ourouler.connecteurs.openmeteo_archive import (
    VARIABLES_HORAIRES,
    ClientArchive,
    HeureArchive,
    arrondir,
)
from ourouler.erreurs import ErreurConnecteur, ErreurUtilisateur

JOUR = date(2026, 3, 15)
AUJOURD_HUI = date(2026, 9, 13)


def charge_complete(n: int = 24) -> dict:
    return {
        "latitude": 0.0,
        "longitude": 0.0,
        "hourly": {
            "time": [f"2026-03-15T{h:02d}:00" for h in range(n)],
            "wind_speed_10m": [10.0 + h for h in range(n)],
            "wind_direction_10m": [float(10 * h % 360) for h in range(n)],
            "temperature_2m": [5.0 + h * 0.5 for h in range(n)],
            "surface_pressure": [1010.0] * n,
        },
    }


def client(gestionnaire, chemin_cache: Path | None = None) -> ClientArchive:
    return ClientArchive(
        http=httpx.Client(transport=httpx.MockTransport(gestionnaire)),
        chemin_cache=chemin_cache,
    )


def reponse(charge: dict | str, code: int = 200):
    def gestionnaire(requete: httpx.Request) -> httpx.Response:
        if isinstance(charge, str):
            return httpx.Response(code, text=charge)
        return httpx.Response(code, json=charge)

    return gestionnaire


# --- lecture nominale ---------------------------------------------------------


def test_lit_les_vingt_quatre_heures():
    c = client(reponse(charge_complete()))
    heures = c.horaires(0.0, 0.0, JOUR, aujourd_hui=AUJOURD_HUI)
    assert len(heures) == 24
    assert heures[0] == HeureArchive(
        t=datetime.fromisoformat("2026-03-15T00:00+00:00"),
        vent_kmh=10.0,
        vent_depuis_deg=0.0,
        temp_c=5.0,
        pression_hpa=1010.0,
    )
    assert all(h.t.tzinfo is not None for h in heures)


def test_demande_bien_les_quatre_variables_et_le_point_arrondi():
    vues = {}

    def gestionnaire(requete: httpx.Request) -> httpx.Response:
        vues.update(dict(requete.url.params))
        return httpx.Response(200, json=charge_complete())

    client(gestionnaire).horaires(0.1234, -0.0678, JOUR, aujourd_hui=AUJOURD_HUI)
    assert vues["hourly"] == ",".join(VARIABLES_HORAIRES)
    assert vues["timezone"] == "UTC"
    assert vues["start_date"] == vues["end_date"] == "2026-03-15"
    assert float(vues["latitude"]) == pytest.approx(0.10)
    assert float(vues["longitude"]) == pytest.approx(-0.05)


def test_arrondir():
    assert arrondir(0.1234) == 0.1
    assert arrondir(-0.0678) == -0.05
    assert arrondir(0.0) == 0.0
    assert arrondir(0.1749) == 0.15
    assert arrondir(0.176) == 0.2
    # Pas de 0.15000000000000002 : la clé de cache doit être stable, sinon
    # deux exécutions écrivent deux lignes pour le même point.
    assert repr(arrondir(0.1499)) == "0.15"


# --- archives vides, partielles, nulles ---------------------------------------


def test_archive_sans_bloc_horaire():
    assert client(reponse({"latitude": 0.0})).horaires(0.0, 0.0, JOUR, aujourd_hui=AUJOURD_HUI) == []


def test_archive_entierement_nulle():
    """Point hors de la grille : 24 heures sans aucune valeur, pas une exception."""
    charge = charge_complete()
    for nom in VARIABLES_HORAIRES:
        charge["hourly"][nom] = [None] * 24
    heures = client(reponse(charge)).horaires(0.0, 0.0, JOUR, aujourd_hui=AUJOURD_HUI)
    assert len(heures) == 24
    assert all(h.vent_kmh is None and h.temp_c is None for h in heures)


def test_archive_partielle():
    """Une variable absente et une colonne trop courte : complétées par des absences."""
    charge = charge_complete()
    del charge["hourly"]["surface_pressure"]
    charge["hourly"]["temperature_2m"] = [5.0, 6.0]
    heures = client(reponse(charge)).horaires(0.0, 0.0, JOUR, aujourd_hui=AUJOURD_HUI)
    assert len(heures) == 24
    assert all(h.pression_hpa is None for h in heures)
    assert heures[0].temp_c == 5.0
    assert heures[5].temp_c is None
    assert heures[0].vent_kmh == 10.0  # les autres variables restent lues


def test_valeurs_non_finies_valent_absentes():
    """Le vrai service émet des littéraux `NaN`, que `json.loads` accepte."""
    charge = charge_complete()
    charge["hourly"]["wind_speed_10m"] = [float("nan")] * 24
    charge["hourly"]["wind_direction_10m"] = ["illisible"] * 24
    corps = json.dumps(charge)  # allow_nan par défaut : produit bien « NaN »
    assert "NaN" in corps
    heures = client(reponse(corps)).horaires(0.0, 0.0, JOUR, aujourd_hui=AUJOURD_HUI)
    assert all(h.vent_kmh is None and h.vent_depuis_deg is None for h in heures)
    assert heures[0].temp_c == 5.0


def test_horodatage_illisible_saute_l_heure():
    charge = charge_complete()
    charge["hourly"]["time"][3] = "pas une date"
    heures = client(reponse(charge)).horaires(0.0, 0.0, JOUR, aujourd_hui=AUJOURD_HUI)
    assert len(heures) == 23


# --- refus --------------------------------------------------------------------


def test_jour_futur_refuse_sans_appel():
    appels = []

    def gestionnaire(requete: httpx.Request) -> httpx.Response:
        appels.append(requete)
        return httpx.Response(200, json=charge_complete())

    c = client(gestionnaire)
    with pytest.raises(ErreurUtilisateur, match="futur"):
        c.horaires(0.0, 0.0, date(2027, 1, 1), aujourd_hui=AUJOURD_HUI)
    assert not appels


def test_point_illisible_refuse():
    with pytest.raises(ErreurUtilisateur):
        client(reponse(charge_complete())).horaires(float("nan"), 0.0, JOUR, aujourd_hui=AUJOURD_HUI)


def test_erreur_http():
    c = client(reponse({"error": True, "reason": "out of range"}, code=400))
    with pytest.raises(ErreurConnecteur, match="HTTP 400"):
        c.horaires(0.0, 0.0, JOUR, aujourd_hui=AUJOURD_HUI)


def test_refus_applicatif_en_200():
    c = client(reponse({"error": True, "reason": "hors plage"}))
    with pytest.raises(ErreurConnecteur, match="hors plage"):
        c.horaires(0.0, 0.0, JOUR, aujourd_hui=AUJOURD_HUI)


def test_reponse_non_json():
    c = client(reponse("<html>maintenance</html>"))
    with pytest.raises(ErreurConnecteur, match="non-JSON"):
        c.horaires(0.0, 0.0, JOUR, aujourd_hui=AUJOURD_HUI)


def test_service_injoignable():
    def gestionnaire(requete: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("injoignable")

    with pytest.raises(ErreurConnecteur, match="injoignable"):
        client(gestionnaire).horaires(0.0, 0.0, JOUR, aujourd_hui=AUJOURD_HUI)


# --- mémoïsation --------------------------------------------------------------


def test_memoisation_evite_le_second_appel(tmp_path: Path):
    appels = []

    def gestionnaire(requete: httpx.Request) -> httpx.Response:
        appels.append(requete)
        return httpx.Response(200, json=charge_complete())

    chemin = tmp_path / "archive_meteo.sqlite"
    c = client(gestionnaire, chemin)
    premier = c.horaires(0.0, 0.0, JOUR, aujourd_hui=AUJOURD_HUI)
    second = c.horaires(0.0, 0.0, JOUR, aujourd_hui=AUJOURD_HUI)
    assert len(appels) == 1
    assert premier == second
    assert c.appels == 1 and c.lectures_cache == 1

    # Un autre client sur le même fichier profite du même cache.
    autre = client(gestionnaire, chemin)
    assert autre.horaires(0.0, 0.0, JOUR, aujourd_hui=AUJOURD_HUI) == premier
    assert len(appels) == 1


def test_memoisation_par_point_arrondi(tmp_path: Path):
    """Deux départs distants de 100 m tombent sur la même clé : un seul appel."""
    appels = []

    def gestionnaire(requete: httpx.Request) -> httpx.Response:
        appels.append(requete)
        return httpx.Response(200, json=charge_complete())

    c = client(gestionnaire, tmp_path / "a.sqlite")
    c.horaires(0.1001, 0.1001, JOUR, aujourd_hui=AUJOURD_HUI)
    c.horaires(0.1009, 0.1009, JOUR, aujourd_hui=AUJOURD_HUI)
    assert len(appels) == 1


def test_une_archive_vide_est_aussi_memoisee(tmp_path: Path):
    """Un point hors grille ne doit pas être redemandé à chaque calibration."""
    appels = []

    def gestionnaire(requete: httpx.Request) -> httpx.Response:
        appels.append(requete)
        return httpx.Response(200, json={"latitude": 0.0})

    c = client(gestionnaire, tmp_path / "a.sqlite")
    assert c.horaires(0.0, 0.0, JOUR, aujourd_hui=AUJOURD_HUI) == []
    assert c.horaires(0.0, 0.0, JOUR, aujourd_hui=AUJOURD_HUI) == []
    assert len(appels) == 1


def test_cache_corrompu_ne_fait_pas_echouer(tmp_path: Path):
    chemin = tmp_path / "a.sqlite"
    client(reponse(charge_complete()), chemin).horaires(0.0, 0.0, JOUR, aujourd_hui=AUJOURD_HUI)
    # Contenu illisible dans la colonne mémoïsée : on rappelle le service.
    import sqlite3

    cx = sqlite3.connect(chemin)
    cx.execute("UPDATE archive SET heures = ?", ("{pas du json",))
    cx.commit()
    cx.close()
    neuf = client(reponse(charge_complete()), chemin)
    assert len(neuf.horaires(0.0, 0.0, JOUR, aujourd_hui=AUJOURD_HUI)) == 24


def test_un_fichier_de_cache_qui_n_est_pas_du_sqlite(tmp_path: Path, capsys):
    """Le fichier appartient à l'utilisateur : on s'en passe, on le dit, on continue."""
    chemin = tmp_path / "a.sqlite"
    chemin.write_bytes(b"ni sqlite ni json\x00\xff" * 50)
    c = client(reponse(charge_complete()), chemin)
    assert "inutilisable" in capsys.readouterr().err
    assert len(c.horaires(0.0, 0.0, JOUR, aujourd_hui=AUJOURD_HUI)) == 24


def test_coordonnees_hors_du_globe(tmp_path: Path):
    for lat, lon in ((91.0, 0.0), (-90.5, 0.0), (0.0, 180.5), (0.0, -181.0)):
        with pytest.raises(ErreurUtilisateur, match="globe"):
            client(reponse(charge_complete())).horaires(lat, lon, JOUR, aujourd_hui=AUJOURD_HUI)


def test_sans_cache_le_client_memorise_quand_meme_le_temps_du_processus():
    """Pas de fichier : la mémoire du client suffit à ne pas redemander deux fois.

    Un nouveau client, lui, repart de zéro — c'est bien la mémoïsation sur
    disque qui fait durer l'économie d'un appel d'une exécution à l'autre.
    """
    appels = []

    def gestionnaire(requete: httpx.Request) -> httpx.Response:
        appels.append(requete)
        return httpx.Response(200, json=charge_complete())

    c = client(gestionnaire, None)
    c.horaires(0.0, 0.0, JOUR, aujourd_hui=AUJOURD_HUI)
    c.horaires(0.0, 0.0, JOUR, aujourd_hui=AUJOURD_HUI)
    assert len(appels) == 1
    client(gestionnaire, None).horaires(0.0, 0.0, JOUR, aujourd_hui=AUJOURD_HUI)
    assert len(appels) == 2


def test_le_cache_conserve_les_absences(tmp_path: Path):
    charge = charge_complete()
    charge["hourly"]["surface_pressure"] = [None] * 24
    chemin = tmp_path / "a.sqlite"
    c = client(reponse(charge), chemin)
    avant = c.horaires(0.0, 0.0, JOUR, aujourd_hui=AUJOURD_HUI)
    apres = client(reponse({"error": True, "reason": "ne doit pas être appelé"}), chemin).horaires(
        0.0, 0.0, JOUR, aujourd_hui=AUJOURD_HUI
    )
    assert avant == apres
    assert all(h.pression_hpa is None for h in apres)


def test_le_cache_est_bien_un_sqlite_lisible(tmp_path: Path):
    import sqlite3

    chemin = tmp_path / "a.sqlite"
    client(reponse(charge_complete()), chemin).horaires(0.0, 0.0, JOUR, aujourd_hui=AUJOURD_HUI)
    cx = sqlite3.connect(chemin)
    lignes = cx.execute("SELECT lat, lon, jour, heures FROM archive").fetchall()
    cx.close()
    assert len(lignes) == 1
    assert lignes[0][:3] == (0.0, 0.0, "2026-03-15")
    assert len(json.loads(lignes[0][3])) == 24
