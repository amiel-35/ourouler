"""Tests du rapport météo (L1.5) : vent relatif, confiance, meilleure direction, rendus."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from ourouler.config import Depart
from ourouler.meteo.couronne import NOMS_DIRECTIONS, couronne
from ourouler.meteo.openmeteo import PrevisionHeure, PrevisionPoint
from ourouler.meteo.rapport import (
    CONFIANCE_ACCORD,
    CONFIANCE_DESACCORD,
    CONFIANCE_INCONNUE,
    LARGEUR_CELLULE,
    LARGEUR_LIBELLE,
    VENT_DOS,
    VENT_FACE,
    VENT_TRAVERS,
    Cellule,
    RapportMeteo,
    _case,
    confiance,
    construire,
    date_en_francais,
    rendre_json,
    rendre_texte,
    vent_relatif,
)

DEPART = Depart(nom="Point zéro", latitude=0.0, longitude=0.0)
DEBUT = datetime(2026, 9, 13, 8, 0, tzinfo=UTC)


# --- vent relatif -----------------------------------------------------------


@pytest.mark.parametrize(
    ("azimut", "vent_depuis", "attendu"),
    [
        # Quadrant 1 : le vent vient d'où l'on va → face.
        (0.0, 0.0, VENT_FACE),
        (90.0, 90.0, VENT_FACE),
        (180.0, 200.0, VENT_FACE),
        (270.0, 250.0, VENT_FACE),
        # Quadrant 2 : le vent vient d'où l'on vient → dos.
        (0.0, 180.0, VENT_DOS),
        (90.0, 270.0, VENT_DOS),
        (180.0, 10.0, VENT_DOS),
        (270.0, 100.0, VENT_DOS),
        # Quadrants 3 et 4 : travers.
        (0.0, 90.0, VENT_TRAVERS),
        (0.0, 270.0, VENT_TRAVERS),
        (45.0, 135.0, VENT_TRAVERS),
        (315.0, 80.0, VENT_TRAVERS),
    ],
)
def test_vent_relatif_quatre_quadrants(azimut: float, vent_depuis: float, attendu: str):
    assert vent_relatif(azimut, vent_depuis) == attendu


@pytest.mark.parametrize(
    ("azimut", "vent_depuis", "attendu"),
    [
        # Bornes du secteur de face : ±45° inclus.
        (0.0, 45.0, VENT_FACE),
        (0.0, 315.0, VENT_FACE),
        (0.0, 45.001, VENT_TRAVERS),
        (0.0, 314.999, VENT_TRAVERS),
        # Bornes du secteur de dos : ±45° de l'opposé, inclus.
        (0.0, 135.0, VENT_DOS),
        (0.0, 225.0, VENT_DOS),
        (0.0, 134.999, VENT_TRAVERS),
        (0.0, 225.001, VENT_TRAVERS),
        # Passage par 0/360.
        (350.0, 30.0, VENT_FACE),
        (10.0, 330.0, VENT_FACE),
    ],
)
def test_vent_relatif_aux_bornes(azimut: float, vent_depuis: float, attendu: str):
    assert vent_relatif(azimut, vent_depuis) == attendu


def test_vent_relatif_inconnu_si_direction_absente():
    assert vent_relatif(0.0, None) is None


# --- confiance --------------------------------------------------------------


@pytest.mark.parametrize(
    ("a", "b", "attendu"),
    [
        (0.0, 0.0, CONFIANCE_ACCORD),
        (0.5, 0.4, CONFIANCE_ACCORD),
        (0.2, 0.05, CONFIANCE_ACCORD),  # 0,2 < 0,3 : pas de désaccord
        (0.29, 0.0, CONFIANCE_ACCORD),
        (0.3, 0.0, CONFIANCE_DESACCORD),  # borne : ≥ 0,3 contre < 0,1
        (0.0, 0.3, CONFIANCE_DESACCORD),  # symétrique
        (1.5, 0.09, CONFIANCE_DESACCORD),
        (0.3, 0.1, CONFIANCE_ACCORD),  # 0,1 n'est pas « < 0,1 »
        (None, 0.0, CONFIANCE_INCONNUE),
        (0.0, None, CONFIANCE_INCONNUE),
        (None, None, CONFIANCE_INCONNUE),
    ],
)
def test_confiance(a: float | None, b: float | None, attendu: str):
    assert confiance(a, b) == attendu


# --- construction -----------------------------------------------------------


def heures(pluies, vents_depuis=None, vents=None, ressentis=None) -> list[PrevisionHeure]:
    n = len(pluies)
    vents_depuis = vents_depuis if vents_depuis is not None else [0.0] * n
    vents = vents if vents is not None else [14.0] * n
    ressentis = ressentis if ressentis is not None else [12.0] * n
    return [
        PrevisionHeure(
            t=DEBUT.replace(hour=8 + i),
            pluie_mm=pluies[i],
            vent_kmh=vents[i],
            rafales_kmh=None if vents[i] is None else vents[i] * 1.8,
            vent_depuis_deg=vents_depuis[i],
            ressenti_c=ressentis[i],
            temp_c=None if ressentis[i] is None else ressentis[i] + 2,
        )
        for i in range(n)
    ]


def previsions(points, pluies_par_point, **kw) -> list[PrevisionPoint]:
    return [
        PrevisionPoint(lat=p.lat, lon=p.lon, heures=heures(pluies, **kw))
        for p, pluies in zip(points, pluies_par_point, strict=True)
    ]


def rapport_simple(
    pluies_principales=None, pluies_second=None, vents_depuis=None, distances=(15.0,)
) -> RapportMeteo:
    points = couronne(DEPART, 8, distances)
    n = len(points)
    p1 = pluies_principales if pluies_principales is not None else [[0.0, 0.0]] * n
    p2 = pluies_second
    return construire(
        DEPART,
        points,
        previsions(points, p1, vents_depuis=vents_depuis),
        previsions(points, p2, vents_depuis=vents_depuis) if p2 is not None else None,
        DEBUT,
        2,
        modele="principal_test",
        second_avis="second_test",
    )


def test_construire_une_cellule_par_point_et_par_heure():
    r = rapport_simple()
    assert len(r.cellules) == (1 + 8) * 2
    assert {c.direction for c in r.cellules} == {"ici", *NOMS_DIRECTIONS}
    assert r.distances() == [0.0, 15.0]
    assert r.heures() == [DEBUT, DEBUT.replace(hour=9)]


def test_construire_sans_second_avis_donne_confiance_inconnue():
    r = rapport_simple()
    assert all(c.confiance == CONFIANCE_INCONNUE for c in r.cellules)
    assert all(c.pluie_second_avis_mm is None for c in r.cellules)


@pytest.mark.parametrize("second", [None, []], ids=["None", "liste vide"])
def test_construire_second_avis_absent_donne_confiance_inconnue(second):
    """Une liste vide vaut `None` : second avis absent, pas incohérent.

    `[]` levait `ValueError` (« 0 prévision(s) pour 9 point(s) ») là où `None`
    passait : un second modèle hors domaine finissait donc en trace et code 1
    au lieu d'une table entière en « inconnu ».
    """
    points = couronne(DEPART, 8, [15.0])
    r = construire(
        DEPART, points, previsions(points, [[0.0, 0.0]] * len(points)), second, DEBUT, 2
    )
    assert len(r.cellules) == (1 + 8) * 2
    assert all(c.confiance == CONFIANCE_INCONNUE for c in r.cellules)
    assert all(c.pluie_second_avis_mm is None for c in r.cellules)


def test_construire_avec_second_avis_en_accord():
    n = 9
    r = rapport_simple([[0.0, 0.0]] * n, [[0.0, 0.05]] * n)
    assert all(c.confiance == CONFIANCE_ACCORD for c in r.cellules)


def test_construire_repere_le_desaccord():
    n = 9
    r = rapport_simple([[0.0, 1.0]] * n, [[0.0, 0.0]] * n)
    par_heure = {c.t for c in r.cellules if c.confiance == CONFIANCE_DESACCORD}
    assert par_heure == {DEBUT.replace(hour=9)}


def test_construire_apparie_le_second_avis_par_horodatage():
    """Un second modèle décalé d'une heure ne doit pas être lu par position."""
    points = couronne(DEPART, 8, [15.0])
    principale = previsions(points, [[0.0, 1.0]] * len(points))
    second = [
        PrevisionPoint(
            lat=p.lat,
            lon=p.lon,
            heures=[
                PrevisionHeure(
                    t=DEBUT.replace(hour=9),
                    pluie_mm=0.0,
                    vent_kmh=None,
                    rafales_kmh=None,
                    vent_depuis_deg=None,
                    ressenti_c=None,
                    temp_c=None,
                )
            ],
        )
        for p in points
    ]
    r = construire(DEPART, points, principale, second, DEBUT, 2)
    a_8h = [c for c in r.cellules if c.t == DEBUT]
    a_9h = [c for c in r.cellules if c.t == DEBUT.replace(hour=9)]
    assert all(c.confiance == CONFIANCE_INCONNUE for c in a_8h)  # pas de second avis à 8 h
    assert all(c.confiance == CONFIANCE_DESACCORD for c in a_9h)  # 1,0 contre 0,0


def test_construire_refuse_des_longueurs_incoherentes():
    points = couronne(DEPART, 8, [15.0])
    with pytest.raises(ValueError):
        construire(DEPART, points, previsions(points[:3], [[0.0]] * 3), None, DEBUT, 1)
    with pytest.raises(ValueError):
        construire(
            DEPART,
            points,
            previsions(points, [[0.0]] * len(points)),
            previsions(points[:2], [[0.0]] * 2),
            DEBUT,
            1,
        )


def test_vent_relatif_par_direction_dans_les_cellules():
    """Vent du nord (0°) : on a le vent de face en allant au N, de dos au S."""
    n = 9
    r = rapport_simple([[0.0, 0.0]] * n, vents_depuis=[0.0, 0.0])
    relatifs = {c.direction: c.vent_relatif for c in r.cellules if c.distance_km == 15.0}
    assert relatifs["N"] == VENT_FACE
    assert relatifs["S"] == VENT_DOS
    assert relatifs["E"] == VENT_TRAVERS
    assert relatifs["O"] == VENT_TRAVERS
    assert relatifs["NE"] == VENT_FACE  # 45° = borne incluse
    assert relatifs["SO"] == VENT_DOS  # 225° = borne incluse


# --- meilleure direction ----------------------------------------------------


def cellule(direction: str, pluie: float, relatif: str | None = None, heure: int = 8) -> Cellule:
    return Cellule(
        direction=direction,
        distance_km=15.0,
        t=DEBUT.replace(hour=heure),
        pluie_mm=pluie,
        pluie_second_avis_mm=pluie,
        vent_kmh=14.0,
        vent_depuis_deg=0.0,
        vent_relatif=relatif,
        ressenti_c=12.0,
        confiance=CONFIANCE_ACCORD,
    )


def rapport_de(cellules: list[Cellule]) -> RapportMeteo:
    return RapportMeteo(
        depart=DEPART, debut=DEBUT, horizon_h=1, modele="m", second_avis="s", cellules=cellules
    )


def test_meilleure_direction_cumul_minimal():
    r = rapport_de([cellule("N", 5.0), cellule("E", 0.4), cellule("S", 2.0)])
    nom, motif = r.meilleure_direction()
    assert nom == "E"
    assert "pluie" in motif


def test_meilleure_direction_cumule_toutes_les_distances_et_heures():
    cellules = [
        cellule("N", 0.0, heure=8),
        cellule("N", 3.0, heure=9),
        cellule("E", 1.0, heure=8),
        cellule("E", 1.0, heure=9),
    ]
    assert rapport_de(cellules).meilleure_direction()[0] == "E"  # 2,0 contre 3,0


def test_meilleure_direction_ignore_le_point_ici():
    r = rapport_de([cellule("ici", 0.0), cellule("N", 1.0), cellule("E", 2.0)])
    assert r.meilleure_direction()[0] == "N"


def test_meilleure_direction_a_egalite_prefere_le_vent_de_face():
    cellules = [
        cellule("N", 0.0, VENT_DOS),
        cellule("E", 0.1, VENT_FACE),
        cellule("S", 0.05, VENT_TRAVERS),
    ]
    nom, motif = rapport_de(cellules).meilleure_direction()
    assert nom == "E"
    assert "égalité" in motif and "face" in motif


def test_meilleure_direction_egalite_stricte_a_02_mm():
    """0,2 mm d'écart n'est pas une égalité : le seuil est strict."""
    cellules = [cellule("N", 0.0, VENT_DOS), cellule("E", 0.2, VENT_FACE)]
    assert rapport_de(cellules).meilleure_direction()[0] == "N"
    cellules = [cellule("N", 0.0, VENT_DOS), cellule("E", 0.19, VENT_FACE)]
    assert rapport_de(cellules).meilleure_direction()[0] == "E"


def test_meilleure_direction_egalite_sans_vent_de_face():
    cellules = [cellule("N", 0.0, VENT_DOS), cellule("E", 0.0, VENT_TRAVERS)]
    nom, motif = rapport_de(cellules).meilleure_direction()
    assert nom == "N"  # première de la couronne, choix déterministe
    assert "aucun vent de face" in motif


def test_meilleure_direction_sans_cellule():
    nom, motif = rapport_de([]).meilleure_direction()
    assert nom == ""
    assert "aucune" in motif


# --- directions incomplètes -------------------------------------------------
#
# Tests qui auraient attrapé D7 : une cellule de pluie à None n'ajoutait rien
# au cumul, donc une direction sans aucune donnée affichait 0,0 mm et était
# conseillée avec le motif « cumul de pluie le plus faible ».


def test_meilleure_direction_ecarte_une_direction_sans_donnee():
    """N n'a aucune pluie connue : elle ne doit pas passer pour la plus sèche."""
    sans_donnee = cellule("N", 0.0)
    sans_donnee.pluie_mm = None
    r = rapport_de([sans_donnee, cellule("E", 1.0)])
    nom, motif = r.meilleure_direction()
    assert nom == "E", "E est mouillée mais mesurée ; N n'est pas mesurée du tout"
    assert "écartée" in motif and "1 direction" in motif


def test_une_seule_heure_manquante_suffit_a_ecarter_une_direction():
    """Le contrat ne tolère pas un cumul partiel comparé à un cumul complet."""
    partielle = [cellule("N", 0.0, heure=8), cellule("N", 0.0, heure=9)]
    partielle[1].pluie_mm = None
    completes = [cellule("E", 0.3, heure=8), cellule("E", 0.3, heure=9)]
    nom, motif = rapport_de(partielle + completes).meilleure_direction()
    assert nom == "E"
    assert "écartée" in motif


def test_meilleure_direction_le_dit_quand_aucune_direction_n_est_complete():
    """Plus aucune direction mesurée de bout en bout : on conseille, mais on le dit."""
    cellules = []
    for nom_direction, pluie in (("N", 2.0), ("E", 0.5)):
        c1 = cellule(nom_direction, pluie, heure=8)
        c2 = cellule(nom_direction, 0.0, heure=9)
        c2.pluie_mm = None
        cellules += [c1, c2]
    nom, motif = rapport_de(cellules).meilleure_direction()
    assert nom == "E"
    assert "sans donnée" in motif, motif
    assert "1 h sans donnée" in motif


def test_la_direction_la_moins_trouee_est_preferee_si_toutes_sont_incompletes():
    cellules = []
    # N : deux heures manquantes ; E : une seule, mais plus de pluie mesurée.
    for heure in (8, 9):
        c = cellule("N", 0.0, heure=heure)
        c.pluie_mm = None
        cellules.append(c)
    manquante = cellule("E", 0.0, heure=8)
    manquante.pluie_mm = None
    cellules += [manquante, cellule("E", 5.0, heure=9)]
    nom, motif = rapport_de(cellules).meilleure_direction()
    assert nom == "E", "une seule heure manquante vaut mieux que deux, même sous la pluie"
    assert "1 h sans donnée" in motif


def test_pas_de_reserve_quand_toutes_les_directions_sont_completes():
    r = rapport_de([cellule("N", 5.0), cellule("E", 0.4)])
    _, motif = r.meilleure_direction()
    assert "écartée" not in motif and "sans donnée" not in motif


def test_une_direction_incomplete_ne_plante_pas_le_rendu_texte():
    sans_donnee = cellule("N", 0.0)
    sans_donnee.pluie_mm = None
    rendu = rendre_texte(rapport_de([sans_donnee, cellule("E", 1.0)]))
    assert "Direction conseillée : E" in rendu


# --- rendu texte ------------------------------------------------------------


def test_rendu_texte_contient_les_huit_directions_et_les_heures():
    n = 9
    texte = rendre_texte(rapport_simple([[0.0, 0.0]] * n))
    for direction in NOMS_DIRECTIONS:
        assert any(ligne.startswith(direction) for ligne in texte.splitlines())
    assert "ici" in texte
    assert "15 km" in texte
    assert "Direction conseillée" in texte
    assert "Cellule :" in texte


def test_rendu_texte_marqueur_de_desaccord():
    n = 9
    texte = rendre_texte(rapport_simple([[0.0, 1.0]] * n, [[0.0, 0.0]] * n))
    assert "?" in texte
    # Une seule heure sur deux en désaccord : le marqueur n'est pas partout.
    cases = [ligne for ligne in texte.splitlines() if ligne.startswith(("ici", *NOMS_DIRECTIONS))]
    assert sum(ligne.count("?") for ligne in cases) == n


def test_rendu_texte_sans_desaccord_sans_marqueur():
    n = 9
    texte = rendre_texte(rapport_simple([[0.0, 0.0]] * n, [[0.0, 0.0]] * n))
    lignes_table = [ligne for ligne in texte.splitlines() if ligne.startswith(("N", "S", "E", "O", "i"))]
    assert not any("?" in ligne for ligne in lignes_table)


def test_rendu_texte_cellule_compacte():
    points = couronne(DEPART, 8, [15.0])
    r = construire(
        DEPART,
        points,
        previsions(points, [[0.0]] * len(points), vents_depuis=[0.0], vents=[14.0], ressentis=[12.0]),
        None,
        DEBUT,
        1,
        modele="m",
    )
    ligne_n = next(ligne for ligne in rendre_texte(r).splitlines() if ligne.startswith("N "))
    assert "0.0 14f 12°" in ligne_n


def test_rendu_texte_tient_en_110_colonnes():
    """8 directions × 6 heures doivent rester lisibles sur un terminal de 110 colonnes."""
    points = couronne(DEPART, 8, [15.0, 25.0, 40.0])
    pluies = [[0.1 * i for i in range(6)]] * len(points)
    r = construire(
        DEPART,
        points,
        previsions(points, pluies, vents_depuis=[10.0] * 6, vents=[14.0] * 6, ressentis=[12.0] * 6),
        previsions(
            points, [[0.0] * 6] * len(points), vents_depuis=[10.0] * 6, vents=[14.0] * 6, ressentis=[12.0] * 6
        ),
        DEBUT,
        6,
        modele="principal",
        second_avis="second",
    )
    for ligne in rendre_texte(r).splitlines():
        assert len(ligne) <= 110, ligne


def test_rendu_texte_valeurs_absentes():
    points = couronne(DEPART, 8, [15.0])
    p = previsions(points, [[None]] * len(points), vents_depuis=[None], vents=[None], ressentis=[None])
    r = construire(DEPART, points, p, None, DEBUT, 1, modele="m")
    ligne_n = next(ligne for ligne in rendre_texte(r).splitlines() if ligne.startswith("N "))
    assert "- - -" in ligne_n


def test_rendu_texte_filtre_une_distance():
    n = 1 + 8 * 3
    r = rapport_simple([[0.0, 0.0]] * n, distances=(15.0, 25.0, 40.0))
    texte = rendre_texte(r, distance_km=25.0)
    assert "25 km" in texte
    assert "── 15 km" not in texte and "── 40 km" not in texte


def test_rendu_texte_distance_inconnue_le_dit():
    n = 9
    texte = rendre_texte(rapport_simple([[0.0, 0.0]] * n), distance_km=99.0)
    assert "Aucune couronne à 99 km" in texte


def test_rendu_texte_nomme_les_deux_modeles():
    n = 9
    texte = rendre_texte(rapport_simple([[0.0, 0.0]] * n))
    assert "principal_test" in texte and "second_test" in texte


def test_date_en_francais_independante_de_la_locale():
    assert date_en_francais(datetime(2026, 9, 13, 8, 0)) == "dimanche 13 septembre 2026 à 08h00"


# --- rendu JSON -------------------------------------------------------------


def test_rendu_json():
    n = 9
    d = rendre_json(rapport_simple([[0.0, 1.0]] * n, [[0.0, 0.0]] * n))
    assert d["depart"]["nom"] == "Point zéro"
    assert d["debut"] == DEBUT.isoformat()
    assert d["horizon_h"] == 2
    assert d["modele"] == "principal_test" and d["second_avis"] == "second_test"
    assert set(d["meilleure_direction"]) == {"nom", "motif"}
    assert len(d["cellules"]) == n * 2
    c = d["cellules"][0]
    assert set(c) == {
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
    }


def test_rendu_json_serialisable():
    import json

    n = 9
    json.dumps(rendre_json(rapport_simple([[0.0, 0.0]] * n)), ensure_ascii=False)


# --- la ligne « ici » n'a pas de vent relatif -------------------------------
#
# Test qui aurait attrapé D8 : le point de départ est créé avec un azimut de
# 0°, donc son vent relatif était calculé comme si l'on partait plein nord.
# La table affichait « ici 0.0 16f 23° », ce « f » laissant croire à un vent
# de face sur place.


def ligne_de(rendu: str, libelle: str) -> str:
    lignes = [ligne for ligne in rendu.splitlines() if ligne.startswith(libelle)]
    assert len(lignes) == 1, f"ligne « {libelle} » introuvable ou dupliquée dans :\n{rendu}"
    return lignes[0]


@pytest.mark.parametrize("vent_depuis", [0.0, 45.0, 90.0, 180.0, 225.0, 315.0])
def test_la_ligne_ici_n_affiche_aucune_lettre_de_vent_relatif(vent_depuis: float):
    """Quel que soit le vent, « ici » ne dit ni face, ni dos, ni travers."""
    n = len(couronne(DEPART, 8, (15.0,)))
    rendu = rendre_texte(rapport_simple([[0.0, 0.0]] * n, vents_depuis=[vent_depuis] * n))
    ligne_ici = ligne_de(rendu, "ici")
    assert "f" not in ligne_ici and "d" not in ligne_ici and "t" not in ligne_ici, ligne_ici


def test_la_ligne_ici_garde_la_vitesse_du_vent_et_le_ressenti():
    """On enlève la lettre, pas l'information : la vitesse reste utile sur place."""
    n = len(couronne(DEPART, 8, (15.0,)))
    rendu = rendre_texte(rapport_simple([[0.0, 0.0]] * n, vents_depuis=[0.0] * n))
    ligne_ici = ligne_de(rendu, "ici")
    assert "14" in ligne_ici, ligne_ici  # la vitesse de vent des fixtures
    assert "°" in ligne_ici, ligne_ici  # le ressenti


def test_les_directions_gardent_bien_leur_lettre():
    """Le correctif ne doit pas vider la table de son information utile."""
    n = len(couronne(DEPART, 8, (15.0,)))
    rendu = rendre_texte(rapport_simple([[0.0, 0.0]] * n, vents_depuis=[0.0] * n))
    ligne_nord = ligne_de(rendu, "N ")
    assert "f" in ligne_nord, ligne_nord  # vent du nord, on part au nord : face
    ligne_sud = ligne_de(rendu, "S ")
    assert "d" in ligne_sud, ligne_sud  # même vent, on part au sud : dos


# --- largeur de cellule ------------------------------------------------------
#
# Dette notée en relecture (D10) : LARGEUR_CELLULE = 12 suffisait pour
# « 0.0 14f 12°? » mais pas pour une pluie à deux chiffres, qui décalait la
# colonne suivante.


def rapport_pluvieux(pluie: float, vent_kmh: float, ressenti: float) -> RapportMeteo:
    """Un rapport dont toutes les cellules portent les valeurs les plus larges."""
    cellules = []
    for nom in ("ici", "N", "SO"):
        for heure in (8, 9):
            c = cellule(nom, pluie, VENT_FACE, heure=heure)
            c.vent_kmh = vent_kmh
            c.ressenti_c = ressenti
            cellules.append(c)
    return rapport_de(cellules)


@pytest.mark.parametrize(
    "pluie, vent, ressenti",
    [
        (0.0, 14.0, 12.0),  # le cas courant
        (12.5, 14.0, 12.0),  # la pluie à deux chiffres du rapport de relecture
        (12.5, 100.0, -10.0),  # le pire réaliste : tout à sa largeur maximale
    ],
)
def test_les_colonnes_restent_alignees(pluie: float, vent: float, ressenti: float):
    """Toutes les lignes de la table doivent avoir leurs colonnes au même endroit."""
    rendu = rendre_texte(rapport_pluvieux(pluie, vent, ressenti))
    lignes_table = [
        ligne
        for ligne in rendu.splitlines()
        if ligne.startswith(("ici", "N ", "SO ")) or ligne.lstrip().startswith("08h")
    ]
    assert len(lignes_table) >= 3, rendu
    # La deuxième colonne commence après le libellé et une cellule entière.
    debuts = {len(ligne) - len(ligne[LARGEUR_LIBELLE + LARGEUR_CELLULE :]) for ligne in lignes_table}
    assert len(debuts) == 1, f"colonnes désalignées :\n{rendu}"


def test_une_cellule_pluvieuse_tient_dans_la_largeur():
    """La mesure directe : la cellule la plus large ne doit pas dépasser."""
    c = cellule("N", 12.5, VENT_FACE)
    c.vent_kmh = 100.0
    c.ressenti_c = -10.0
    c.confiance = CONFIANCE_DESACCORD
    case = _case(c)
    assert len(case) <= LARGEUR_CELLULE, f"« {case} » fait {len(case)} > {LARGEUR_CELLULE}"
    assert "12.5" in case, "la pluie doit rester lisible en entier"
    assert case.endswith("?")
