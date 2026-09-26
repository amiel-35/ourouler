"""Couronne de directions, client Open-Meteo, rapport, mis à l'épreuve.

Tous les points de départ sont fictifs : (0.0, 0.0) en mer, (0.0, 179.9) au
milieu du Pacifique pour le passage de l'antiméridien, (89.9, 0.0) pour le
franchissement du pôle.

Le changement d'heure est traité là où il fait mal : la fenêtre du dernier
dimanche d'octobre 2026, calculée en UTC et rendue en heure locale de Paris,
où 02:00 existe deux fois.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import outils
import pytest

from ourouler.config import Depart
from ourouler.meteo import couronne as module_couronne
from ourouler.meteo import openmeteo as module_openmeteo
from ourouler.meteo import rapport as module_rapport
from ourouler.noyau.erreurs import ErreurConnecteur, ErreurUtilisateur

DEPART = Depart(nom="Point fictif", latitude=0.0, longitude=0.0)
DEBUT = datetime(2026, 4, 12, 9, 0, tzinfo=UTC)
VARIABLES = (
    "precipitation",
    "rain",
    "wind_speed_10m",
    "wind_direction_10m",
    "wind_gusts_10m",
    "apparent_temperature",
    "temperature_2m",
)
# Dernier dimanche d'octobre 2026 : 03:00 CEST redevient 02:00 CET.
HEURES_CHANGEMENT = [datetime(2026, 10, 24, 23, 0, tzinfo=UTC) + timedelta(hours=n) for n in range(5)]


# =============================================================================
# Couronne
# =============================================================================


def test_noms_des_directions():
    module = module_couronne
    assert module.NOMS_DIRECTIONS == ("N", "NE", "E", "SE", "S", "SO", "O", "NO"), (
        "noms français, sens horaire (contrat §4)"
    )


def _verifier_couronne(points, *, directions: int, distances: list[float]) -> None:
    assert len(points) == 1 + directions * len(distances), (
        f"{len(points)} points pour {directions} directions × {len(distances)} distances + « ici »"
    )
    ici = [p for p in points if p.distance_km == 0]
    assert len(ici) == 1, "le point de départ doit figurer une fois et une seule"
    assert ici[0].nom == "ici", f"le point de départ se nomme « ici », reçu {ici[0].nom!r}"
    for point in points:
        assert -90.0 <= point.lat <= 90.0, f"{point.nom} : latitude hors bornes ({point.lat})"
        assert -180.0 <= point.lon <= 180.0, f"{point.nom} : longitude hors bornes ({point.lon})"
        assert 0.0 <= point.azimut_deg < 360.0, f"{point.nom} : azimut {point.azimut_deg}"
    for distance in distances:
        noms = [p.nom for p in points if p.distance_km == distance]
        assert len(noms) == directions, f"{distance} km : {len(noms)} points"
        assert len(set(noms)) == directions, f"{distance} km : noms en double ({noms})"


def test_couronne_nominale():
    module = module_couronne
    points = module.couronne(DEPART, 8, [15.0, 25.0, 40.0])
    _verifier_couronne(points, directions=8, distances=[15.0, 25.0, 40.0])
    ici = next(p for p in points if p.distance_km == 0)
    assert (ici.lat, ici.lon) == (DEPART.latitude, DEPART.longitude)
    for point in points:
        if point.distance_km == 0:
            continue
        mesure = outils.distance_km(DEPART.latitude, DEPART.longitude, point.lat, point.lon)
        assert mesure == pytest.approx(point.distance_km, rel=0.002), (
            f"{point.nom} à {point.distance_km} km : mesuré {mesure:.3f} km"
        )
        azimut = outils.azimut_deg(DEPART.latitude, DEPART.longitude, point.lat, point.lon)
        ecart = min(abs(azimut - point.azimut_deg), 360 - abs(azimut - point.azimut_deg))
        assert ecart < 0.5, f"{point.nom} : azimut annoncé {point.azimut_deg}, mesuré {azimut:.2f}"


def test_azimuts_des_huit_directions():
    module = module_couronne
    points = module.couronne(DEPART, 8, [20.0])
    azimuts = {p.nom: p.azimut_deg for p in points if p.distance_km == 20.0}
    attendus = {nom: 45.0 * i for i, nom in enumerate(module.NOMS_DIRECTIONS)}
    assert azimuts == pytest.approx(attendus), f"azimuts {azimuts}"


def test_couronne_a_seize_directions():
    module = module_couronne
    points = module.couronne(DEPART, 16, [20.0])
    _verifier_couronne(points, directions=16, distances=[20.0])


def test_point_couronne_est_immuable():
    module = module_couronne
    point = module.couronne(DEPART, 8, [20.0])[0]
    with pytest.raises(Exception):  # noqa: B017 — FrozenInstanceError est un ValueError-like
        point.lat = 1.0


def test_franchissement_de_l_antimeridien():
    """Départ à 179,9° E, 40 km vers l'est : la longitude doit revenir dans [-180, 180]."""
    module = module_couronne
    depart = Depart(nom="Pacifique fictif", latitude=0.0, longitude=179.9)
    points = module.couronne(depart, 8, [40.0])
    _verifier_couronne(points, directions=8, distances=[40.0])
    est = next(p for p in points if p.nom == "E")
    assert est.lon < 0, f"le point à l'est doit basculer en longitude négative, reçu {est.lon}"
    mesure = outils.distance_km(depart.latitude, depart.longitude, est.lat, est.lon)
    assert mesure == pytest.approx(40.0, rel=0.002), f"distance mesurée {mesure:.3f} km"


def test_franchissement_du_pole():
    module = module_couronne
    depart = Depart(nom="Presque le pôle", latitude=89.9, longitude=0.0)
    points = module.couronne(depart, 8, [40.0])
    _verifier_couronne(points, directions=8, distances=[40.0])


@pytest.mark.parametrize("directions", [0, 1, 3, -4, 360])
def test_nombre_de_directions_inattendu(directions):
    """Le contrat prévoit 8, « 16 si demandé » : le reste doit refuser ou rester cohérent."""
    module = module_couronne
    points, erreur = outils.robuste(
        lambda: module.couronne(DEPART, directions, [20.0]),
        quoi=f"couronne(directions={directions})",
        erreurs_acceptees=(ErreurUtilisateur, ValueError),
    )
    if points is not None and directions > 0:
        _verifier_couronne(points, directions=directions, distances=[20.0])


def test_sans_distance_il_reste_le_point_de_depart():
    module = module_couronne
    points = module.couronne(DEPART, 8, [])
    assert len(points) == 1 and points[0].nom == "ici", f"reçu {points}"


@pytest.mark.parametrize("distances", [[0.0], [-10.0], [20000.0], [15.0, 15.0]])
def test_distances_inattendues(distances):
    module = module_couronne
    points, _ = outils.robuste(
        lambda: module.couronne(DEPART, 8, distances),
        quoi=f"couronne(distances={distances})",
        erreurs_acceptees=(ErreurUtilisateur, ValueError),
    )
    if points is not None:
        for point in points:
            assert -90.0 <= point.lat <= 90.0, f"{point.nom} : latitude {point.lat}"
            assert -180.0 <= point.lon <= 180.0, f"{point.nom} : longitude {point.lon}"
            assert point.distance_km >= 0.0, f"{point.nom} : distance négative"


# =============================================================================
# Client Open-Meteo
# =============================================================================


def _heures_json(nb: int = 3, *, debut: datetime = DEBUT, **surcharges) -> dict:
    horaire = {
        "time": [(debut + timedelta(hours=n)).strftime("%Y-%m-%dT%H:%M") for n in range(nb)],
        "precipitation": [0.0] * nb,
        "rain": [0.0] * nb,
        "wind_speed_10m": [12.0] * nb,
        "wind_direction_10m": [180.0] * nb,
        "wind_gusts_10m": [25.0] * nb,
        "apparent_temperature": [11.0] * nb,
        "temperature_2m": [13.0] * nb,
    }
    horaire.update(surcharges)
    return horaire


def _bloc(lat: float, lon: float, horaire: dict | None = None) -> dict:
    return {
        "latitude": lat,
        "longitude": lon,
        "utc_offset_seconds": 0,
        "timezone": "GMT",
        "hourly_units": {"precipitation": "mm"},
        "hourly": horaire if horaire is not None else _heures_json(),
    }


def _client_om(module, reponse, **kwargs):
    requetes: list[httpx.Request] = []

    def gestionnaire(requete: httpx.Request) -> httpx.Response:
        requetes.append(requete)
        return reponse(requete) if callable(reponse) else reponse

    http = httpx.Client(transport=httpx.MockTransport(gestionnaire))
    return module.ClientOpenMeteo(http=http, **kwargs), requetes


POINTS_TROIS = [(0.0, 0.0), (0.2, 0.0), (0.0, 0.2)]


def test_un_seul_appel_pour_tous_les_points():
    module = module_openmeteo
    corps = [_bloc(lat, lon) for lat, lon in POINTS_TROIS]
    client, requetes = _client_om(module, httpx.Response(200, json=corps))
    previsions = client.previsions(POINTS_TROIS, modele="modele_fictif", debut=DEBUT, horizon_h=3)
    assert len(requetes) == 1, f"{len(requetes)} appels HTTP pour un seul jeu de points"
    params = requetes[0].url.params
    assert params["latitude"].count(",") == 2, f"latitudes envoyées : {params['latitude']!r}"
    assert params["longitude"].count(",") == 2
    assert params["models"] == "modele_fictif"
    assert params["timezone"].upper() == "UTC"
    variables = params["hourly"]
    for attendue in VARIABLES:
        assert attendue in variables, f"variable horaire {attendue} absente de la requête"
    assert len(previsions) == 3


def test_un_seul_point_renvoye_comme_objet():
    """Open-Meteo renvoie un objet, et non un tableau, quand on ne demande qu'un point."""
    module = module_openmeteo
    client, _ = _client_om(module, httpx.Response(200, json=_bloc(0.0, 0.0)))
    previsions = client.previsions([(0.0, 0.0)], modele="m", debut=DEBUT, horizon_h=3)
    assert isinstance(previsions, list), "la signature annonce list[PrevisionPoint]"
    assert len(previsions) == 1, f"un point demandé, {len(previsions)} rendu(s)"
    assert len(previsions[0].heures) == 3


def test_les_horodatages_reviennent_conscients_du_fuseau():
    """L'API répond « 2026-04-12T09:00 » sans fuseau alors que timezone=UTC."""
    module = module_openmeteo
    client, _ = _client_om(module, httpx.Response(200, json=_bloc(0.0, 0.0)))
    (prevision,) = client.previsions([(0.0, 0.0)], modele="m", debut=DEBUT, horizon_h=3)
    for i, heure in enumerate(prevision.heures):
        outils.verifier_utc(heure.t, f"PrevisionHeure[{i}].t")
    assert [h.t for h in prevision.heures] == [DEBUT + timedelta(hours=n) for n in range(3)]


def test_valeurs_nulles_deviennent_none():
    module = module_openmeteo
    horaire = _heures_json(3, precipitation=[None, 0.4, None], wind_speed_10m=[None, None, None])
    client, _ = _client_om(module, httpx.Response(200, json=_bloc(0.0, 0.0, horaire)))
    (prevision,) = client.previsions([(0.0, 0.0)], modele="m", debut=DEBUT, horizon_h=3)
    assert [h.pluie_mm for h in prevision.heures] == [None, pytest.approx(0.4), None]
    assert all(h.vent_kmh is None for h in prevision.heures)


def test_tableaux_de_longueurs_differentes():
    """`time` fait foi : les séries plus courtes se complètent en None, pas en IndexError."""
    module = module_openmeteo
    horaire = _heures_json(6)
    horaire["precipitation"] = [0.1, 0.2]
    horaire["wind_speed_10m"] = [5.0] * 9
    del horaire["wind_gusts_10m"]
    client, _ = _client_om(module, httpx.Response(200, json=_bloc(0.0, 0.0, horaire)))
    resultat, erreur = outils.robuste(
        lambda: client.previsions([(0.0, 0.0)], modele="m", debut=DEBUT, horizon_h=6),
        quoi="previsions() sur des séries de longueurs différentes",
        erreurs_acceptees=(ErreurConnecteur,),
    )
    if erreur is not None:
        return
    (prevision,) = resultat
    assert len(prevision.heures) == 6, "autant d'heures que d'entrées dans `time`"
    assert [h.pluie_mm for h in prevision.heures[2:]] == [None] * 4, "série tronquée → None"
    assert all(h.rafales_kmh is None for h in prevision.heures), "série absente → None"


def test_serie_time_vide():
    module = module_openmeteo
    client, _ = _client_om(module, httpx.Response(200, json=_bloc(0.0, 0.0, _heures_json(0))))
    resultat, erreur = outils.robuste(
        lambda: client.previsions([(0.0, 0.0)], modele="m", debut=DEBUT, horizon_h=3),
        quoi="previsions() sur une série vide",
        erreurs_acceptees=(ErreurConnecteur,),
    )
    if erreur is None:
        assert resultat[0].heures == []


@pytest.mark.parametrize("valeur", ["3,2", "abc", True, [0.2], {"x": 1}], ids=str)
def test_valeurs_de_type_inattendu(valeur):
    """Ni la valeur brute ni un plantage : soit un refus, soit None."""
    module = module_openmeteo
    horaire = _heures_json(2, precipitation=[valeur, 0.1])
    client, _ = _client_om(module, httpx.Response(200, json=_bloc(0.0, 0.0, horaire)))
    resultat, erreur = outils.robuste(
        lambda: client.previsions([(0.0, 0.0)], modele="m", debut=DEBUT, horizon_h=2),
        quoi=f"previsions() avec precipitation={valeur!r}",
        erreurs_acceptees=(ErreurConnecteur,),
    )
    if erreur is None:
        premiere = resultat[0].heures[0].pluie_mm
        assert premiere is None or isinstance(premiere, float), (
            f"pluie_mm = {premiere!r} : le contrat annonce float | None"
        )


@pytest.mark.parametrize(
    "corps",
    [b"", b"   ", b"null", b"{}", b'{"latitude": 0.0}', b"<html>503</html>", b"{"],
    ids=["vide", "blancs", "null", "objet vide", "sans hourly", "html", "json casse"],
)
def test_reponse_inexploitable(corps):
    module = module_openmeteo
    client, _ = _client_om(module, httpx.Response(200, content=corps))
    with pytest.raises(ErreurConnecteur):
        client.previsions([(0.0, 0.0)], modele="m", debut=DEBUT, horizon_h=3)


@pytest.mark.parametrize("code", [400, 401, 429, 500, 503])
def test_erreur_http(code):
    module = module_openmeteo
    reponse = httpx.Response(code, json={"error": True, "reason": "modèle inconnu"})
    client, _ = _client_om(module, reponse)
    with pytest.raises(ErreurConnecteur) as capture:
        client.previsions([(0.0, 0.0)], modele="m", debut=DEBUT, horizon_h=3)
    assert str(code) in str(capture.value), f"le code HTTP doit être nommé : {capture.value}"


def test_enveloppe_d_erreur_en_200():
    """Open-Meteo répond parfois 200 avec `{"error": true, "reason": …}`."""
    module = module_openmeteo
    client, _ = _client_om(module, httpx.Response(200, json={"error": True, "reason": "bad model"}))
    with pytest.raises(ErreurConnecteur):
        client.previsions([(0.0, 0.0)], modele="m", debut=DEBUT, horizon_h=3)


def test_moins_de_points_que_demande():
    """Deux points demandés, un seul rendu : refus, ou alignement explicite."""
    module = module_openmeteo
    client, _ = _client_om(module, httpx.Response(200, json=[_bloc(0.0, 0.0)]))
    resultat, erreur = outils.robuste(
        lambda: client.previsions(POINTS_TROIS[:2], modele="m", debut=DEBUT, horizon_h=3),
        quoi="previsions() avec moins de points que demandé",
        erreurs_acceptees=(ErreurConnecteur,),
    )
    if erreur is None:
        assert len(resultat) == 2, (
            "sans refus, la liste doit rester alignée sur les points demandés "
            f"(reçu {len(resultat)} pour 2 demandés)"
        )


def test_sans_point_aucun_appel():
    module = module_openmeteo
    client, requetes = _client_om(module, httpx.Response(200, json=[]))
    resultat, _ = outils.robuste(
        lambda: client.previsions([], modele="m", debut=DEBUT, horizon_h=3),
        quoi="previsions([])",
        erreurs_acceptees=(ErreurUtilisateur, ValueError),
    )
    if resultat is not None:
        assert resultat == []
        assert requetes == [], "aucun point à demander : inutile d'appeler le service"


def test_fenetre_du_changement_d_heure_reste_monotone_en_utc():
    module = module_openmeteo
    horaire = _heures_json(5, debut=HEURES_CHANGEMENT[0])
    client, _ = _client_om(module, httpx.Response(200, json=_bloc(0.0, 0.0, horaire)))
    (prevision,) = client.previsions([(0.0, 0.0)], modele="m", debut=HEURES_CHANGEMENT[0], horizon_h=5)
    instants = [h.t for h in prevision.heures]
    assert instants == HEURES_CHANGEMENT, f"instants rendus : {instants}"
    assert instants == sorted(instants) and len(set(instants)) == 5


# =============================================================================
# Rapport
# =============================================================================


def _prevision(module, lat: float, lon: float, heures: list[dict]):
    objets = [
        outils.fabriquer(
            module.PrevisionHeure,
            {
                "t": h["t"],
                "pluie_mm": h.get("pluie_mm", 0.0),
                "vent_kmh": h.get("vent_kmh", 15.0),
                "rafales_kmh": h.get("rafales_kmh", 25.0),
                "vent_depuis_deg": h.get("vent_depuis_deg", 180.0),
                "ressenti_c": h.get("ressenti_c", 10.0),
                "temp_c": h.get("temp_c", 12.0),
            },
        )
        for h in heures
    ]
    return outils.fabriquer(module.PrevisionPoint, {"lat": lat, "lon": lon, "heures": objets})


def _rapport(
    *,
    pluie_principale: dict[str, list[float | None]] | None = None,
    pluie_second: dict[str, list[float | None]] | None = None,
    vent_depuis_deg: float = 180.0,
    instants: list[datetime] | None = None,
    distances: list[float] | None = None,
    second_avis_absent: bool = False,
):
    """Construit un RapportMeteo complet à partir de valeurs par direction."""
    couronne_module = module_couronne
    openmeteo = module_openmeteo
    rapport_module = module_rapport
    instants = instants or [DEBUT]
    distances = distances if distances is not None else [20.0]
    points = couronne_module.couronne(DEPART, 8, distances)

    def _heures(nom: str, pluies: dict | None) -> list[dict]:
        serie = (pluies or {}).get(nom, [0.0] * len(instants))
        return [
            {"t": t, "pluie_mm": serie[i], "vent_depuis_deg": vent_depuis_deg} for i, t in enumerate(instants)
        ]

    principale = [_prevision(openmeteo, p.lat, p.lon, _heures(p.nom, pluie_principale)) for p in points]
    if second_avis_absent:
        second = []
    else:
        second = [_prevision(openmeteo, p.lat, p.lon, _heures(p.nom, pluie_second)) for p in points]
    rapport = rapport_module.construire(DEPART, points, principale, second, instants[0], len(instants))
    return rapport_module, rapport


def _cellule(rapport, nom: str, *, distance: float = 20.0, index: int = 0):
    cellules = [
        c for c in rapport.cellules if c.direction == nom and c.distance_km == pytest.approx(distance)
    ]
    assert cellules, (
        f"aucune cellule pour {nom} à {distance} km "
        f"(directions : {sorted({c.direction for c in rapport.cellules})})"
    )
    cellules.sort(key=lambda c: c.t)
    return cellules[index]


@pytest.mark.parametrize(
    "direction, vent_depuis_deg, attendu",
    [
        ("N", 0.0, "face"),
        ("N", 10.0, "face"),
        ("N", 350.0, "face"),
        ("N", 180.0, "dos"),
        ("N", 170.0, "dos"),
        ("N", 190.0, "dos"),
        ("N", 90.0, "travers"),
        ("N", 270.0, "travers"),
        ("N", 100.0, "travers"),
        ("E", 90.0, "face"),
        ("E", 270.0, "dos"),
        ("E", 0.0, "travers"),
        ("SO", 225.0, "face"),
        ("SO", 200.0, "face"),
        ("SO", 45.0, "dos"),
        ("SO", 300.0, "travers"),
        ("NO", 350.0, "face"),
        ("NO", 20.0, "travers"),
        ("NO", 315.0, "face"),
        ("NO", 135.0, "dos"),
    ],
)
def test_vent_relatif(direction, vent_depuis_deg, attendu):
    """« face » pour qui s'éloigne du départ dans cette direction."""
    _, rapport = _rapport(vent_depuis_deg=vent_depuis_deg)
    cellule = _cellule(rapport, direction)
    assert cellule.vent_relatif == attendu, (
        f"direction {direction} (azimut ≈ {cellule.direction}), vent venant de "
        f"{vent_depuis_deg}° : attendu {attendu}, reçu {cellule.vent_relatif!r}"
    )


@pytest.mark.parametrize(
    "principale, second, attendu",
    [
        (0.5, 0.0, "desaccord"),
        (0.0, 0.5, "desaccord"),
        (0.3, 0.09, "desaccord"),
        (0.09, 0.3, "desaccord"),
        (0.3, 0.1, "accord"),
        (0.3, 0.2, "accord"),
        (0.0, 0.0, "accord"),
        (1.0, 0.9, "accord"),
        (0.29, 0.0, "accord"),
        (None, 0.0, "inconnu"),
        (0.5, None, "inconnu"),
        (None, None, "inconnu"),
    ],
)
def test_confiance(principale, second, attendu):
    """Seuils littéraux du contrat : désaccord si l'un ≥ 0,3 et l'autre < 0,1."""
    _, rapport = _rapport(pluie_principale={"N": [principale]}, pluie_second={"N": [second]})
    cellule = _cellule(rapport, "N")
    assert cellule.confiance == attendu, (
        f"pluie {principale} / {second} : attendu {attendu}, reçu {cellule.confiance!r}"
    )
    assert cellule.pluie_mm == (None if principale is None else pytest.approx(principale))
    assert cellule.pluie_second_avis_mm == (None if second is None else pytest.approx(second))


def test_second_avis_absent_donne_inconnu():
    _, rapport = _rapport(second_avis_absent=True)
    assert all(c.confiance == "inconnu" for c in rapport.cellules), (
        "sans second avis, la confiance est « inconnu », jamais « accord »"
    )


def test_meilleure_direction_choisit_le_moins_arrose():
    module, rapport = _rapport(
        pluie_principale={
            "N": [0.0],
            "NE": [3.0],
            "E": [3.0],
            "SE": [3.0],
            "S": [3.0],
            "SO": [3.0],
            "O": [3.0],
            "NO": [3.0],
            "ici": [3.0],
        },
        pluie_second={
            "N": [0.0],
            "NE": [3.0],
            "E": [3.0],
            "SE": [3.0],
            "S": [3.0],
            "SO": [3.0],
            "O": [3.0],
            "NO": [3.0],
            "ici": [3.0],
        },
    )
    nom, motif = rapport.meilleure_direction()
    assert nom == "N", f"direction conseillée {nom!r} alors que seul le nord est sec"
    assert isinstance(motif, str) and motif.strip(), "le motif doit être une phrase"


def test_meilleure_direction_egalite_prefere_le_vent_de_face_a_l_aller():
    """N (0,15 mm) et S (0,10 mm) : écart < 0,2 mm, donc égalité.

    Le minimum brut est au sud ; le vent vient du nord, donc partir au nord
    c'est l'avoir de face à l'aller. Le contrat tranche : c'est le nord.
    """
    _, rapport = _rapport(
        vent_depuis_deg=0.0,
        pluie_principale={
            "N": [0.15],
            "S": [0.10],
            "NE": [3.0],
            "E": [3.0],
            "SE": [3.0],
            "SO": [3.0],
            "O": [3.0],
            "NO": [3.0],
            "ici": [3.0],
        },
        pluie_second={
            "N": [0.15],
            "S": [0.10],
            "NE": [3.0],
            "E": [3.0],
            "SE": [3.0],
            "SO": [3.0],
            "O": [3.0],
            "NO": [3.0],
            "ici": [3.0],
        },
    )
    nom, _ = rapport.meilleure_direction()
    assert nom == "N", f"à égalité, le vent de face à l'aller doit l'emporter, reçu {nom!r}"


def test_meilleure_direction_sans_donnee():
    module, rapport = _rapport(
        pluie_principale=dict.fromkeys(("ici", "N", "NE", "E", "SE", "S", "SO", "O", "NO"), [None]),
        pluie_second=dict.fromkeys(("ici", "N", "NE", "E", "SE", "S", "SO", "O", "NO"), [None]),
    )
    resultat, _ = outils.robuste(
        rapport.meilleure_direction,
        quoi="meilleure_direction() sans aucune valeur de pluie",
        erreurs_acceptees=(ErreurUtilisateur,),
    )
    if resultat is not None:
        nom, motif = resultat
        assert isinstance(nom, str) and isinstance(motif, str)


def test_rapport_reduit_au_point_de_depart():
    """Aucune distance demandée : il ne reste que « ici », les rendus doivent tenir."""
    module, rapport = _rapport(distances=[])
    outils.robuste(
        rapport.meilleure_direction,
        quoi="meilleure_direction() sur un rapport sans couronne",
        erreurs_acceptees=(ErreurUtilisateur, LookupError),
    )
    texte, _ = outils.robuste(
        lambda: module.rendre_texte(rapport),
        quoi="rendre_texte() sur un rapport sans couronne",
        erreurs_acceptees=(ErreurUtilisateur,),
    )
    if texte is not None:
        assert isinstance(texte, str)


def test_rendre_json_serialisable():
    module, rapport = _rapport(distances=[15.0, 25.0])
    donnees = module.rendre_json(rapport)
    assert isinstance(donnees, dict)
    outils.verifier_json(donnees, "rendre_json(rapport)")


def test_rendre_texte_annonce_la_direction_conseillee():
    module, rapport = _rapport(
        pluie_principale={"N": [0.0], "S": [4.0]}, pluie_second={"N": [0.0], "S": [0.0]}
    )
    texte = module.rendre_texte(rapport)
    assert isinstance(texte, str) and texte.strip()
    assert "Direction conseill" in texte, f"ligne « Direction conseillée » attendue :\n{texte}"
    assert "?" in texte, "un désaccord de modèles doit être marqué d'un « ? » (contrat §4)"


def test_rendre_texte_filtre_sur_une_distance_absente():
    module, rapport = _rapport(distances=[15.0])
    texte, _ = outils.robuste(
        lambda: module.rendre_texte(rapport, 999.0),
        quoi="rendre_texte(distance inexistante)",
        erreurs_acceptees=(ErreurUtilisateur,),
    )
    if texte is not None:
        assert isinstance(texte, str)


@pytest.fixture
def fuseau_paris(monkeypatch):
    """Fixe le fuseau du processus à Europe/Paris et le restaure vraiment.

    `monkeypatch.setenv` remet la variable mais pas l'état de la libc : sans
    le `tzset()` final, tous les tests suivants hériteraient de Paris.
    """
    monkeypatch.setenv("TZ", "Europe/Paris")
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


def test_rapport_sur_le_changement_d_heure(fuseau_paris):
    """Cinq heures UTC consécutives dont deux tombent sur 02:00 heure de Paris.

    En UTC elles restent distinctes et ordonnées ; c'est le rendu local qui
    doit se débrouiller, sans fusionner ni perdre une colonne.
    """
    module, rapport = _rapport(instants=HEURES_CHANGEMENT)
    for cellule in rapport.cellules:
        outils.verifier_utc(cellule.t, "Cellule.t")
    nord = [c for c in rapport.cellules if c.direction == "N"]
    instants = sorted(c.t for c in nord)
    assert len(instants) == 5, f"5 heures attendues pour une direction, reçu {len(instants)}"
    assert len(set(instants)) == 5, "aucune heure ne doit être écrasée par le changement d'heure"
    assert instants == HEURES_CHANGEMENT
    locales = [c.t.astimezone() for c in nord]
    assert len({t.hour for t in locales}) == 4, (
        f"02:00 locale existe deux fois ce jour-là, heures rendues : {sorted(t.hour for t in locales)}"
    )
    texte = module.rendre_texte(rapport)
    assert texte.strip()
    outils.verifier_json(module.rendre_json(rapport), "rendre_json(changement d'heure)")


def test_rapport_meteo_expose_les_champs_du_contrat():
    module, rapport = _rapport()
    for nom in ("depart", "debut", "horizon_h", "modele", "second_avis", "cellules"):
        assert hasattr(rapport, nom), f"RapportMeteo.{nom} manquant (contrat §4)"
    outils.verifier_utc(rapport.debut, "RapportMeteo.debut")


# =============================================================================
# CLI
# =============================================================================


@pytest.mark.parametrize("depart", ["pas une heure", "25:00", "2026-13-45T10:00", "10h30", ""])
def test_cli_heure_de_depart_invalide(ecrire_config, capsys, depart):
    """L'heure doit être validée avant tout appel réseau : sinon la fixture le montre."""
    from ourouler.cli import main

    chemin = ecrire_config()
    code, erreur = outils.robuste(
        lambda: main(["--config", str(chemin), "meteo", "--depart", depart]),
        quoi=f"ourouler meteo --depart {depart!r}",
        erreurs_acceptees=(SystemExit,),
    )
    if erreur is not None:
        assert erreur.code == 2, f"sortie argparse avec le code {erreur.code}"
    else:
        assert code == 2, "une heure de départ illisible est une erreur utilisateur (code 2)"
    assert capsys.readouterr().err.strip(), "le motif du refus doit être dit sur stderr"


def _valeurs_de_cellule(cellule: Any) -> dict[str, Any]:
    return {
        nom: getattr(cellule, nom)
        for nom in (
            "direction",
            "distance_km",
            "t",
            "pluie_mm",
            "pluie_second_avis_mm",
            "vent_kmh",
            "vent_depuis_deg",
            "vent_relatif",
            "ressenti_c",
            "confiance",
        )
    }


def test_cellule_expose_les_champs_du_contrat():
    _, rapport = _rapport()
    for cellule in rapport.cellules:
        valeurs = _valeurs_de_cellule(cellule)
        assert valeurs["confiance"] in ("accord", "desaccord", "inconnu")
        assert valeurs["vent_relatif"] in (None, "face", "dos", "travers")
        assert isinstance(valeurs["direction"], str) and valeurs["direction"]
