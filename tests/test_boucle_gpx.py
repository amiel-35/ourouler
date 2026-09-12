"""Tests du GPX de parcours (L2.2) : écriture, import, aller-retour.

Aucune coordonnée réelle : les tracés viennent de la réponse BRouter
fabriquée (anneau autour du point fictif (0.0, 0.0)) ou sont construits ici.
"""

from __future__ import annotations

import random
from pathlib import Path
from xml.etree import ElementTree

import pytest
from test_brouter import client_fabrique  # même dossier : pytest y met le sys.path

from ourouler.boucle.gpx import _denivele, description, ecrire_gpx, lire_gpx_trace
from ourouler.boucle.trace import PointTrace, Trace
from ourouler.erreurs import ErreurLecture

GPX_ROUTE_SEULE = """<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="essai" xmlns="http://www.topografix.com/GPX/1/1">
  <rte>
    <name>Route sans piste</name>
    <rtept lat="0.000000" lon="0.000000"><ele>10.0</ele></rtept>
    <rtept lat="0.010000" lon="0.000000"><ele>20.0</ele></rtept>
    <rtept lat="0.010000" lon="0.010000"><ele>15.0</ele></rtept>
  </rte>
</gpx>
"""

GPX_SANS_ALTITUDE = """<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="essai" xmlns="http://www.topografix.com/GPX/1/1">
  <trk><name>Sans altitude</name><trkseg>
    <trkpt lat="0.000000" lon="0.000000"/>
    <trkpt lat="0.005000" lon="0.000000"/>
    <trkpt lat="0.010000" lon="0.000000"/>
  </trkseg></trk>
</gpx>
"""

GPX_PISTE_VIDE_PUIS_ROUTE = """<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="essai" xmlns="http://www.topografix.com/GPX/1/1">
  <trk><name>Piste vide</name><trkseg></trkseg></trk>
  <rte><name>La vraie</name>
    <rtept lat="0.000000" lon="0.000000"/>
    <rtept lat="0.010000" lon="0.000000"/>
  </rte>
</gpx>
"""


def trace_brouter() -> Trace:
    """Le tracé fabriqué, tel que le connecteur BRouter le construit."""
    client, _ = client_fabrique()
    return client.boucle((0.0, 0.0), azimut_deg=45, rayon_m=1500)


def trace_simple(altitudes: bool = True) -> Trace:
    points = [
        PointTrace(lat=0.0, lon=0.0, alt_m=10.0 if altitudes else None, dist_m=0.0),
        PointTrace(lat=0.01, lon=0.0, alt_m=30.0 if altitudes else None, dist_m=1111.0),
        PointTrace(lat=0.01, lon=0.01, alt_m=20.0 if altitudes else None, dist_m=2222.0),
    ]
    return Trace(
        nom="Essai",
        points=points,
        segments=[],
        distance_m=2222.0,
        denivele_m=20.0,
        temps_moteur_s=3665.0,
        meta={},
    )


def balises(xml: str) -> ElementTree.Element:
    return ElementTree.fromstring(xml)


def sans_espace(balise: str) -> str:
    return balise.rsplit("}", 1)[-1]


# --- écriture -----------------------------------------------------------------


def test_ecrire_gpx_produit_du_gpx_1_1_avec_une_piste_nommee():
    xml = ecrire_gpx(trace_simple(), "Boucle NE 60 km")
    racine = balises(xml)
    assert racine.get("version") == "1.1"
    noms = [sans_espace(n.tag) for n in racine.iter()]
    assert "trk" in noms and "trkseg" in noms and "trkpt" in noms
    piste = next(n for n in racine.iter() if sans_espace(n.tag) == "trk")
    assert next(n for n in piste if sans_espace(n.tag) == "name").text == "Boucle NE 60 km"


def test_la_description_reprend_distance_denivele_et_temps():
    xml = ecrire_gpx(trace_simple(), "Essai")
    racine = balises(xml)
    desc = next(n for n in racine.iter() if sans_espace(n.tag) == "desc").text
    assert "2,2 km" in desc
    assert "D+ 20 m" in desc
    assert "1 h 01" in desc


def test_la_description_omet_ce_que_le_moteur_n_a_pas_dit():
    trace = trace_simple()
    trace.denivele_m = None
    trace.temps_moteur_s = None
    assert description(trace) == "2,2 km"


def test_ce_que_le_seuil_de_denivele_fait_vraiment():
    """Point 17 de la relecture : le docstring affirmait un effet non mesuré.

    Il disait que sans filtre, « le bruit d'un altimètre barométrique double
    le dénivelé d'un parcours plat ». C'est une affirmation sans mesure
    (règle absolue 5), et elle décrit mal ce que fait le seuil : il efface le
    bruit strictement plus petit que lui, et rien d'autre. Ce test mesure les
    trois cas écrits dans le docstring de `_denivele`.
    """
    n = 1000

    def profil(base, amplitude: float) -> list[PointTrace]:
        alea = random.Random(12)
        return [
            PointTrace(lat=0.0, lon=i * 1e-4, alt_m=a + alea.uniform(-amplitude, amplitude), dist_m=i * 11.0)
            for i, a in enumerate(base)
        ]

    def brut(points: list[PointTrace]) -> float:
        return sum(max(0.0, b.alt_m - a.alt_m) for a, b in zip(points[:-1], points[1:], strict=True))

    plat = [50.0] * n
    montee = [50.0 + 20.0 * i / n for i in range(n)]

    plat_leger = profil(plat, 1.0)
    assert brut(plat_leger) > 300.0, "le bruit brut doit bien être massif"
    assert _denivele(plat_leger) == pytest.approx(0.0), (
        "sous le seuil, le bruit d'un parcours plat disparaît entièrement"
    )

    montee_legere = profil(montee, 1.0)
    assert brut(montee_legere) > 300.0
    assert _denivele(montee_legere) == pytest.approx(20.0, abs=2.0), (
        "et le vrai dénivelé, lui, survit"
    )

    plat_fort = profil(plat, 2.5)  # oscillation au-dessus du seuil de 2 m
    assert _denivele(plat_fort) > 400.0, (
        "au-delà du seuil, le filtre ne protège plus : c'est ce que le docstring doit dire"
    )


def test_la_description_dit_d_ou_vient_le_denivele():
    """Point 5 de la relecture : le `<desc>` portait le D+ du moteur sans le dire.

    Relire avec `--gpx` le fichier qu'on vient d'écrire donne un autre
    chiffre (recalculé sur les altitudes) : sans la provenance des deux
    côtés, l'écart est un mystère.
    """
    trace = trace_brouter()
    assert trace.meta["denivele_source"] == "moteur"
    assert "(moteur)" in description(trace)

    relue = lire_gpx_trace(ecrire_gpx(trace, trace.nom).encode("utf-8"))
    assert relue.meta["denivele_source"] == "gpx relu"
    assert "(gpx relu)" in description(relue)


def test_la_provenance_du_denivele_est_absente_quand_le_denivele_l_est():
    trace = trace_simple(altitudes=False)
    relue = lire_gpx_trace(ecrire_gpx(trace, "Sans altitude").encode("utf-8"))
    assert relue.denivele_m is None
    assert relue.meta["denivele_source"] is None
    assert "D+" not in description(relue)


def test_les_altitudes_sont_ecrites_quand_elles_existent():
    racine = balises(ecrire_gpx(trace_simple(), "Essai"))
    assert [n.text for n in racine.iter() if sans_espace(n.tag) == "ele"] == [
        "10.0",
        "30.0",
        "20.0",
    ]


def test_sans_altitude_aucune_balise_ele():
    racine = balises(ecrire_gpx(trace_simple(altitudes=False), "Essai"))
    assert not [n for n in racine.iter() if sans_espace(n.tag) == "ele"]


# --- import -------------------------------------------------------------------


def test_import_depuis_un_chemin(tmp_path: Path):
    fichier = tmp_path / "parcours.gpx"
    fichier.write_text(ecrire_gpx(trace_simple(), "Essai"), encoding="utf-8")
    trace = lire_gpx_trace(fichier)
    assert len(trace.points) == 3
    assert trace.nom == "Essai"
    assert trace.meta["fichier"] == str(fichier)


def test_import_depuis_des_octets():
    trace = lire_gpx_trace(ecrire_gpx(trace_simple(), "Essai").encode("utf-8"))
    assert len(trace.points) == 3
    assert trace.meta["fichier"] == ""


def test_un_gpx_importe_n_a_ni_segment_ni_temps_moteur():
    trace = lire_gpx_trace(GPX_SANS_ALTITUDE.encode("utf-8"))
    assert trace.segments == []
    assert trace.temps_moteur_s is None
    assert trace.meta["couts_partiels"] is True


def test_route_seule_acceptee():
    trace = lire_gpx_trace(GPX_ROUTE_SEULE.encode("utf-8"))
    assert trace.nom == "Route sans piste"
    assert len(trace.points) == 3
    assert trace.distance_m > 0


def test_une_piste_vide_ne_masque_pas_la_route_qui_suit():
    trace = lire_gpx_trace(GPX_PISTE_VIDE_PUIS_ROUTE.encode("utf-8"))
    assert trace.nom == "La vraie"
    assert len(trace.points) == 2


def test_sans_altitude_le_denivele_est_inconnu_pas_zero():
    trace = lire_gpx_trace(GPX_SANS_ALTITUDE.encode("utf-8"))
    assert trace.denivele_m is None
    assert all(p.alt_m is None for p in trace.points)


def test_le_denivele_ignore_le_bruit_d_altimetre():
    """Des oscillations de ±0,8 m ne sont pas du dénivelé."""
    points = [
        PointTrace(lat=0.0, lon=i / 1000, alt_m=50.0 + (0.8 if i % 2 else -0.8), dist_m=0.0)
        for i in range(40)
    ]
    trace = Trace("Bruit", points, [], 0.0, None, None, {})
    relue = lire_gpx_trace(ecrire_gpx(trace, "Bruit").encode("utf-8"))
    assert relue.denivele_m == 0.0


def test_le_denivele_compte_une_vraie_montee():
    points = [
        PointTrace(lat=0.0, lon=i / 1000, alt_m=50.0 + 5 * i, dist_m=0.0) for i in range(5)
    ]
    trace = Trace("Montée", points, [], 0.0, None, None, {})
    relue = lire_gpx_trace(ecrire_gpx(trace, "Montée").encode("utf-8"))
    assert relue.denivele_m == pytest.approx(20.0)


def test_le_nom_retombe_sur_celui_du_fichier(tmp_path: Path):
    fichier = tmp_path / "sans_nom.gpx"
    fichier.write_text(
        GPX_SANS_ALTITUDE.replace("<name>Sans altitude</name>", ""), encoding="utf-8"
    )
    assert lire_gpx_trace(fichier).nom == "sans_nom"


# --- aller-retour -------------------------------------------------------------


def test_aller_retour_sur_un_trace_brouter():
    depart = trace_brouter()
    relue = lire_gpx_trace(ecrire_gpx(depart, depart.nom).encode("utf-8"))
    assert relue.nom == depart.nom
    assert len(relue.points) == len(depart.points)
    for avant, apres in zip(depart.points, relue.points, strict=True):
        assert apres.lat == pytest.approx(avant.lat, abs=1e-7)
        assert apres.lon == pytest.approx(avant.lon, abs=1e-7)
        assert apres.alt_m == pytest.approx(avant.alt_m, abs=1e-3)
        assert apres.dist_m == pytest.approx(avant.dist_m, abs=0.5)
    assert relue.distance_m == pytest.approx(depart.points[-1].dist_m, abs=1.0)
    assert relue.bornee() == depart.bornee() is True


def test_l_aller_retour_perd_les_segments_et_le_dit():
    """Ce que le GPX ne sait pas porter doit se voir, pas se deviner."""
    depart = trace_brouter()
    assert depart.segments
    relue = lire_gpx_trace(ecrire_gpx(depart, depart.nom).encode("utf-8"))
    assert relue.segments == []
    assert relue.meta["couts_partiels"] is True


# --- cas dégradés -------------------------------------------------------------


@pytest.mark.parametrize(
    "contenu",
    [b"", b"   \n", b"<gpx>pas ferme", b"ni GPX ni XML", b"\x00\x01\x02"],
    ids=["vide", "blancs", "xml casse", "texte", "binaire"],
)
def test_fichier_illisible(contenu: bytes):
    with pytest.raises(ErreurLecture):
        lire_gpx_trace(contenu)


def test_gpx_valide_mais_sans_point():
    vide = """<?xml version="1.0"?><gpx version="1.1" creator="x"
        xmlns="http://www.topografix.com/GPX/1/1"><trk><trkseg/></trk></gpx>"""
    with pytest.raises(ErreurLecture, match="sans point"):
        lire_gpx_trace(vide.encode("utf-8"))


def test_fichier_absent(tmp_path: Path):
    with pytest.raises(ErreurLecture, match="lecture impossible"):
        lire_gpx_trace(tmp_path / "nexiste_pas.gpx")


def test_un_point_seul_reste_lisible():
    """Un parcours d'un point n'est pas utile, mais ce n'est pas une erreur de lecture."""
    un_point = """<?xml version="1.0"?><gpx version="1.1" creator="x"
        xmlns="http://www.topografix.com/GPX/1/1"><trk><trkseg>
        <trkpt lat="0.0" lon="0.0"/></trkseg></trk></gpx>"""
    trace = lire_gpx_trace(un_point.encode("utf-8"))
    assert len(trace.points) == 1
    assert trace.distance_m == 0.0
    assert trace.bornee() is False
