"""Tests du lot F0.7 : partir d'ailleurs — `--adresse-depart` et le cœur qui reçoit un `Depart`.

Deux choses distinctes sont vérifiées ici :

1. **Le cœur accepte un point de départ en paramètre.** `meteo`, `boucle` et
   `sortie` interrogent bien le point qu'on leur donne, et non celui de la
   configuration — la couronne météo et les appels BRouter se déplacent
   entièrement.
2. **`cli.py` géocode et tranche**, lui seul : l'adresse ambiguë (le cas
   normal), l'adresse introuvable qui ne retombe jamais sur le départ
   configuré, et l'heure de départ qui n'est pas le lieu.

Aucun accès réseau : les clients de géocodage sont injectés avec un
`httpx.MockTransport`, les réponses viennent de `tests/fixtures/geocodage/`.
Aucune adresse réelle : les fixtures nomment des communes inventées
(« Vallombreuse », « Hautbocage ») et le point zéro du golfe de Guinée.
"""

from __future__ import annotations

import argparse
import io
import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from test_brouter import reponse_fabriquee  # même dossier : pytest y met le sys.path

from ourouler import cli
from ourouler.config import Config, Depart, depuis_dict
from ourouler.connecteurs.brouter import ClientBrouter
from ourouler.connecteurs.geocodage import ClientBAN, ClientNominatim
from ourouler.erreurs import ErreurUtilisateur
from ourouler.meteo.openmeteo import ClientOpenMeteo

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "geocodage"

#: Un point de départ « ailleurs » : toujours fictif, à quelques degrés du
#: point zéro de la configuration de test, donc mesurable sans jamais nommer
#: un lieu réel (règle absolue 1).
AILLEURS = Depart(nom="Place inventée 44999 Vallombreuse", latitude=0.123456, longitude=0.234567)

CONFIG_BRUTE: dict[str, Any] = {
    "depart": {"nom": "Point zéro", "latitude": 0.0, "longitude": 0.0},
    "cycliste": {"masse_kg": 80, "ftp_w": 250},
    "meteo": {
        "directions": 8,
        "distances_km": [15],
        "modele": "modele_principal_test",
        "second_avis": "modele_principal_test",  # un seul appel : pas de second avis
        "horizon_h": 3,
    },
    "brouter": {
        "url": "https://brouter.exemple.test",
        "profil": "fastbike",
        "timeout_s": 5.0,
    },
    "boucle": {"vitesse_moyenne_kmh": 27.0, "sens": "horaire", "candidates": 1},
}


def config_de_test(**sections: Any) -> Config:
    return depuis_dict({**CONFIG_BRUTE, **sections})


def _charge(nom: str) -> Any:
    return json.loads((FIXTURES / nom).read_text(encoding="utf-8"))


# --- clients bouchonnés --------------------------------------------------------


def ban_repondant(charge: Any) -> ClientBAN:
    def gestionnaire(requete: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=charge)

    return ClientBAN(http=httpx.Client(transport=httpx.MockTransport(gestionnaire)))


def nominatim_repondant(charge: Any) -> ClientNominatim:
    def gestionnaire(requete: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=charge)

    return ClientNominatim(http=httpx.Client(transport=httpx.MockTransport(gestionnaire)))


def meteo_qui_note_les_points(vus: list[tuple[float, float]]) -> ClientOpenMeteo:
    """Client Open-Meteo bouchonné qui enregistre chaque coordonnée interrogée."""

    def gestionnaire(requete: httpx.Request) -> httpx.Response:
        lats = requete.url.params["latitude"].split(",")
        lons = requete.url.params["longitude"].split(",")
        vus.extend((float(a), float(o)) for a, o in zip(lats, lons, strict=True))
        heures = [f"2026-09-13T{8 + i:02d}:00" for i in range(6)]
        return httpx.Response(
            200,
            json=[
                {
                    "latitude": float(a),
                    "longitude": float(o),
                    "hourly": {
                        "time": heures,
                        "precipitation": [0.0] * len(heures),
                        "rain": [0.0] * len(heures),
                        "wind_speed_10m": [12.0] * len(heures),
                        "wind_direction_10m": [0.0] * len(heures),
                        "wind_gusts_10m": [20.0] * len(heures),
                        "apparent_temperature": [12.0] * len(heures),
                        "temperature_2m": [14.0] * len(heures),
                    },
                }
                for a, o in zip(lats, lons, strict=True)
            ],
        )

    return ClientOpenMeteo(http=httpx.Client(transport=httpx.MockTransport(gestionnaire)))


def brouter_qui_note_les_departs(vus: list[tuple[float, float]]) -> ClientBrouter:
    """BRouter bouchonné qui enregistre le `lonlats` de chaque demande de boucle."""

    def gestionnaire(requete: httpx.Request) -> httpx.Response:
        lon, lat = requete.url.params["lonlats"].split(",")
        vus.append((float(lat), float(lon)))
        return httpx.Response(200, json=reponse_fabriquee())

    return ClientBrouter(
        config_de_test().brouter,
        http=httpx.Client(transport=httpx.MockTransport(gestionnaire)),
    )


def args_geocodage(adresse: str | None) -> argparse.Namespace:
    return argparse.Namespace(adresse_depart=adresse)


# --- 1. le cœur reçoit un départ -----------------------------------------------


def test_meteo_interroge_la_couronne_autour_du_depart_recu():
    """Le vrai livrable : un départ en paramètre déplace **toute** la grille.

    La couronne part du point de départ et regarde à 15 km dans huit
    directions. Si un seul de ces points restait calé sur la configuration, la
    commande rendrait la météo de chez soi pour une adresse ailleurs.
    """
    config = config_de_test()
    vus: list[tuple[float, float]] = []
    args = argparse.Namespace(
        depart="2026-09-13T08:00", horizon=None, distance=None, modele=None,
        second_avis=None, json=False,
    )

    from ourouler.meteo.commande import executer

    assert executer(args, config, meteo_qui_note_les_points(vus), lieu_depart=AILLEURS) == 0

    assert vus, "aucun point interrogé"
    # 1 point « ici » + 8 directions × 1 distance.
    assert len(vus) == 9
    # `abs=1e-3` : le client Open-Meteo arrondit les coordonnées qu'il envoie
    # (la maille d'AROME HD fait 1,3 km), l'égalité stricte ne veut rien dire ici.
    assert vus[0] == pytest.approx((AILLEURS.latitude, AILLEURS.longitude), abs=1e-3)
    for lat, lon in vus:
        assert abs(lat - AILLEURS.latitude) < 0.2 and abs(lon - AILLEURS.longitude) < 0.2, (
            f"le point ({lat}, {lon}) est resté près du départ configuré"
        )

    # La `Config` de l'appelant n'a pas été modifiée au passage.
    assert config.depart == Depart(nom="Point zéro", latitude=0.0, longitude=0.0)


def test_meteo_sans_depart_recu_reste_sur_celui_de_la_configuration():
    """Le paramètre est optionnel : sans lui, rien ne change pour l'usage existant."""
    vus: list[tuple[float, float]] = []
    args = argparse.Namespace(
        depart="2026-09-13T08:00", horizon=None, distance=None, modele=None,
        second_avis=None, json=False,
    )

    from ourouler.meteo.commande import executer

    assert executer(args, config_de_test(), meteo_qui_note_les_points(vus)) == 0
    assert vus[0] == pytest.approx((0.0, 0.0), abs=1e-9)


def test_le_rapport_meteo_nomme_le_depart_recu():
    """Le lieu retenu se lit dans le rendu, pas seulement dans le message d'annonce."""
    vus: list[tuple[float, float]] = []
    args = argparse.Namespace(
        depart="2026-09-13T08:00", horizon=None, distance=None, modele=None,
        second_avis=None, json=True,
    )

    from ourouler.meteo.commande import executer

    sortie = io.StringIO()
    import contextlib

    with contextlib.redirect_stdout(sortie):
        executer(args, config_de_test(), meteo_qui_note_les_points(vus), lieu_depart=AILLEURS)
    charge = json.loads(sortie.getvalue())
    assert charge["depart"]["nom"] == AILLEURS.nom
    assert charge["depart"]["latitude"] == pytest.approx(AILLEURS.latitude)
    assert charge["depart"]["longitude"] == pytest.approx(AILLEURS.longitude)


def test_boucle_demande_ses_candidates_depuis_le_depart_recu(tmp_path: Path):
    """BRouter doit recevoir le point fourni, pas celui de la configuration."""
    config = config_de_test(cache={"dossier": str(tmp_path / "cache")})
    departs: list[tuple[float, float]] = []
    points_meteo: list[tuple[float, float]] = []
    args = argparse.Namespace(
        distance=60.0, direction="NE", depart="2026-09-13T09:00", candidates=1,
        profil=None, sortie=None, ecraser=False, gpx=None, json=False, velo=None,
        puissance=None,
    )

    from ourouler.boucle.commande import executer

    code = executer(
        args,
        config,
        brouter_qui_note_les_departs(departs),
        meteo_qui_note_les_points(points_meteo),
        lieu_depart=AILLEURS,
    )
    assert code == 0
    assert departs, "aucune boucle demandée au moteur"
    for lat, lon in departs:
        assert (lat, lon) == pytest.approx((AILLEURS.latitude, AILLEURS.longitude), abs=1e-6)


# --- 2. la CLI géocode et tranche ----------------------------------------------


def test_sans_l_option_le_depart_est_celui_de_la_configuration():
    config = config_de_test()
    assert cli.lieu_depart(args_geocodage(None), config) is config.depart


def test_une_adresse_ambigue_retient_le_premier_candidat_et_le_dit():
    """Le cas **normal** : plusieurs communes portent la même rue.

    La CLI tranche — une ligne de commande doit bien partir de quelque part —
    mais elle l'annonce avant tout travail, avec le nombre de candidats
    écartés et de quoi les voir.
    """
    flux = io.StringIO()
    retenu = cli.lieu_depart(
        args_geocodage("7 rue du if"),
        config_de_test(),
        ban=ban_repondant(_charge("ban_ambigu.json")),
        flux=flux,
    )
    assert retenu.nom == "7 Rue du If 44999 Vallombreuse"
    assert retenu.latitude == pytest.approx(0.123456)
    assert retenu.longitude == pytest.approx(0.234567)

    message = flux.getvalue()
    assert "7 Rue du If 44999 Vallombreuse" in message, "le lieu retenu n'est pas annoncé"
    assert "1 autre" in message, "le candidat écarté n'est pas signalé"
    assert "ourouler geocoder" in message, "rien ne dit où voir la liste complète"
    # Le second candidat n'a pas été retenu en silence.
    assert "Hautbocage" not in message.split("ourouler geocoder")[0]


def test_un_resultat_nominatim_porte_l_attribution_openstreetmap():
    """Exigée par la licence ODbL dès qu'un résultat Nominatim est affiché."""
    flux = io.StringIO()
    retenu = cli.lieu_depart(
        args_geocodage("une adresse hors de France"),
        config_de_test(),
        ban=ban_repondant(_charge("ban_vide.json")),
        nominatim=nominatim_repondant(_charge("nominatim_un_candidat.json")),
        flux=flux,
    )
    assert retenu.nom
    assert cli.ATTRIBUTION_NOMINATIM in flux.getvalue()


def test_une_adresse_introuvable_est_une_erreur_et_ne_retombe_pas_sur_la_configuration():
    """Le piège nommé par le lot : une réponse fausse est pire qu'une erreur.

    Qui demande un parcours depuis une autre ville et reçoit une boucle autour
    de chez lui n'a pas reçu une erreur, il a reçu une réponse fausse.
    """
    config = config_de_test()
    with pytest.raises(ErreurUtilisateur) as echec:
        cli.lieu_depart(
            args_geocodage("adresse totalement introuvable"),
            config,
            ban=ban_repondant(_charge("ban_vide.json")),
            nominatim=nominatim_repondant([]),
            flux=io.StringIO(),
        )
    message = str(echec.value)
    assert "--adresse-depart" in message
    assert "aucune adresse trouvée" in message
    assert config.depart.nom in message and "n'a pas servi" in message, (
        "l'erreur doit dire en toutes lettres que le départ configuré n'a pas remplacé l'adresse"
    )


def test_une_adresse_vide_est_refusee_avant_tout_appel():
    """`--adresse-depart ''` est une valeur fournie et illisible, pas « pas d'option ».

    Même traitement que `--heure-depart ''` : refus avant le moindre appel, et
    sans client de géocodage — s'il en fallait un, ce test échouerait par
    `AttributeError` plutôt que par `ErreurUtilisateur`.
    """
    with pytest.raises(ErreurUtilisateur, match="valeur vide"):
        cli.lieu_depart(args_geocodage("   "), config_de_test(), ban=None, nominatim=None)


def test_une_adresse_de_depart_avec_un_gpx_importe_est_refusee(tmp_path, monkeypatch, capsys):
    """`boucle --gpx` lit une boucle qui porte déjà son départ.

    Géocoder une adresse pour l'annoncer ensuite comme point de départ d'un
    tracé qu'elle n'a pas produit serait faux ; l'ignorer en silence le serait
    autant. On refuse, et on dit pourquoi.
    """
    monkeypatch.setattr(
        cli,
        "chercher_adresse",
        lambda *a, **k: pytest.fail("aucun géocodage ne doit avoir lieu"),
    )
    config = tmp_path / "config.toml"
    config.write_text(
        '[depart]\nnom = "Point zéro"\nlatitude = 0.0\nlongitude = 0.0\n'
        "[cycliste]\nmasse_kg = 80.0\nftp_w = 250\n",
        encoding="utf-8",
    )
    code = cli.main(
        [
            "--config", str(config), "boucle",
            "--gpx", str(tmp_path / "importe.gpx"),
            "--adresse-depart", "Place du Test",
        ]
    )
    assert code == 2
    erreur = capsys.readouterr().err
    assert "--adresse-depart et --gpx" in erreur
    assert "Traceback" not in erreur


def test_l_adresse_introuvable_sort_en_code_2_sans_trace_python(tmp_path, monkeypatch, capsys):
    """De bout en bout : `main` affiche une ligne et rend 2, jamais une trace.

    Le géocodage est remplacé dans `cli` (aucun réseau) ; ce qui est mesuré
    ici est le chemin d'erreur de la ligne de commande, pas le connecteur.
    """
    monkeypatch.setattr(cli, "chercher_adresse", lambda *a, **k: [])
    config = tmp_path / "config.toml"
    config.write_text(
        '[depart]\nnom = "Point zéro"\nlatitude = 0.0\nlongitude = 0.0\n'
        "[cycliste]\nmasse_kg = 80.0\nftp_w = 250\n",
        encoding="utf-8",
    )
    code = cli.main(
        ["--config", str(config), "meteo", "--adresse-depart", "adresse totalement introuvable"]
    )
    assert code == 2
    capture = capsys.readouterr()
    assert "Traceback" not in capture.err
    assert "aucune adresse trouvée" in capture.err
    assert capture.out == "", "rien ne doit avoir été rendu sur la sortie standard"


def test_la_mise_en_garde_sur_les_routes_connues_suit_l_existence_du_cache(tmp_path: Path):
    """Le cache des routes apprises est mesuré autour du départ configuré.

    Il ne suit pas un départ ponctuel : `connu %` tombera à zéro loin de chez
    soi, sans que le tracé soit pour autant inédit. On le dit quand la base
    existe, on se tait quand elle n'existe pas — le piège du lot est de casser
    ça en silence.
    """
    from ourouler.apprentissage.commande import NOM_BASE

    dossier = tmp_path / "cache"
    dossier.mkdir()
    config = config_de_test(cache={"dossier": str(dossier)})

    flux = io.StringIO()
    cli.lieu_depart(
        args_geocodage("7 rue du if"),
        config,
        ban=ban_repondant(_charge("ban_ambigu.json")),
        avertir_routes=True,
        flux=flux,
    )
    assert "routes connues" not in flux.getvalue(), "rien à dire tant que la base n'existe pas"

    (dossier / NOM_BASE).write_bytes(b"")
    flux = io.StringIO()
    cli.lieu_depart(
        args_geocodage("7 rue du if"),
        config,
        ban=ban_repondant(_charge("ban_ambigu.json")),
        avertir_routes=True,
        flux=flux,
    )
    assert "routes connues" in flux.getvalue()
    assert "n'entre dans aucun score" in flux.getvalue()


def test_meteo_ne_previent_pas_des_routes_connues():
    """`meteo` n'affiche aucune part de kilomètres connus : l'avertissement y serait du bruit."""
    flux = io.StringIO()
    cli.lieu_depart(
        args_geocodage("7 rue du if"),
        config_de_test(),
        ban=ban_repondant(_charge("ban_ambigu.json")),
        flux=flux,
    )
    assert "routes connues" not in flux.getvalue()
