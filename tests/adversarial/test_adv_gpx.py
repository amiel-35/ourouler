"""Écriture et import GPX, mis à l'épreuve.

`ecrire_gpx` doit produire un GPX 1.1 valide même quand le nom du tracé
contient des caractères XML ; `lire_gpx_trace` doit refuser proprement
(`ErreurLecture`) ce qui n'est pas lisible, et ne jamais laisser remonter une
exception « bug » : la CLI l'afficherait en trace.

Les fichiers écrits vivent dans `tmp_path` : rien de binaire ni de traçable
n'est déposé à côté des tests (règle absolue 1, `.gitignore` ne réintègre
nommément que les fixtures de `tests/fixtures/activites/`).
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import fabriques
import pytest
from outils import robuste

from ourouler.boucle import gpx as module_gpx
from ourouler.noyau.erreurs import ErreurLecture, ErreurUtilisateur

GPX_MINIMAL_TRK = """<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="test" xmlns="http://www.topografix.com/GPX/1/1">
  <trk><name>essai</name><trkseg>
    <trkpt lat="0.0011" lon="0.0017"><ele>10.0</ele></trkpt>
    <trkpt lat="0.0020" lon="0.0017"><ele>12.0</ele></trkpt>
    <trkpt lat="0.0029" lon="0.0017"><ele>11.0</ele></trkpt>
  </trkseg></trk>
</gpx>
"""

GPX_ROUTE_SEULE = """<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="test" xmlns="http://www.topografix.com/GPX/1/1">
  <rte><name>itinéraire</name>
    <rtept lat="0.0011" lon="0.0017"/>
    <rtept lat="0.0020" lon="0.0017"/>
    <rtept lat="0.0029" lon="0.0022"/>
  </rte>
</gpx>
"""

GPX_SANS_ALTITUDE = """<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="test" xmlns="http://www.topografix.com/GPX/1/1">
  <trk><trkseg>
    <trkpt lat="0.0011" lon="0.0017"/>
    <trkpt lat="0.0020" lon="0.0017"/>
  </trkseg></trk>
</gpx>
"""

GPX_TRACE_VIDE = """<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="test" xmlns="http://www.topografix.com/GPX/1/1">
  <trk><name>rien</name><trkseg></trkseg></trk>
</gpx>
"""

#: Entité XML non définie : `xml.etree` la refuse, gpxpy aussi. Ce qu'on
#: vérifie, c'est qu'aucune entité externe n'est allée chercher un fichier.
GPX_ENTITE = """<?xml version="1.0"?>
<!DOCTYPE gpx [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>
<gpx version="1.1" creator="test" xmlns="http://www.topografix.com/GPX/1/1">
  <trk><name>&xxe;</name><trkseg>
    <trkpt lat="0.0011" lon="0.0017"/>
  </trkseg></trk>
</gpx>
"""


def _lire(module, entree):
    return robuste(
        lambda: module.lire_gpx_trace(entree),
        quoi=f"lire_gpx_trace({type(entree).__name__})",
        erreurs_acceptees=(ErreurUtilisateur,),
    )


def _points_xml(texte: str) -> list[tuple[float, float]]:
    racine = ET.fromstring(texte)
    espace = "{http://www.topografix.com/GPX/1/1}"
    points = racine.iter(f"{espace}trkpt")
    return [(float(p.get("lat")), float(p.get("lon"))) for p in points]


# --- écriture ----------------------------------------------------------------


def test_ecrire_gpx_produit_un_gpx_1_1_analysable():
    module = module_gpx
    trace = fabriques.trace_fictive(fabriques.ligne(6, pas_m=250.0, cap_deg=30.0))
    texte = module.ecrire_gpx(trace, "boucle d'essai")

    assert isinstance(texte, str), "ecrire_gpx rend une chaîne (contrat §2)"
    racine = ET.fromstring(texte)
    assert racine.tag.endswith("gpx"), f"racine {racine.tag!r} inattendue"
    assert racine.get("version") == "1.1", "le contrat demande du GPX 1.1"
    assert _points_xml(texte), "aucun <trkpt> écrit"
    assert "boucle d'essai" in texte, "<name> doit reprendre le nom demandé"


def test_le_nom_est_echappe_et_ne_casse_pas_le_xml():
    """Un nom de fichier vient de la CLI : `&`, `<` et `"` doivent être échappés."""
    module = module_gpx
    trace = fabriques.trace_fictive(fabriques.ligne(3))
    hostile = 'Nord & <Sud> "test"'
    texte = module.ecrire_gpx(trace, hostile)
    racine = ET.fromstring(texte)  # planterait si l'échappement manquait
    noms = [e.text for e in racine.iter() if e.tag.endswith("name")]
    assert hostile in noms, f"le nom doit se relire tel quel, noms trouvés : {noms}"


def test_la_description_reprend_distance_denivele_et_temps():
    module = module_gpx
    trace = fabriques.trace_fictive(
        fabriques.ligne(11, pas_m=1000.0), denivele_m=250.0, temps_moteur_s=3600.0
    )
    texte = module.ecrire_gpx(trace, "avec description")
    racine = ET.fromstring(texte)
    descriptions = [e.text or "" for e in racine.iter() if e.tag.endswith("desc")]
    assert descriptions, "<desc> attendu (contrat §2)"
    desc = " ".join(descriptions)
    assert "10" in desc, f"la distance (10 km) doit figurer dans la description : {desc!r}"
    assert "250" in desc, f"le D+ doit figurer dans la description : {desc!r}"


def test_les_altitudes_absentes_ne_cassent_pas_l_ecriture():
    module = module_gpx
    coords = [(lat, lon, None) for lat, lon, _ in fabriques.ligne(4)]
    trace = fabriques.trace_fictive(coords, denivele_m=None)
    texte = module.ecrire_gpx(trace, "sans altitude")
    racine = ET.fromstring(texte)
    altitudes = [e.text for e in racine.iter() if e.tag.endswith("ele")]
    assert not altitudes, f"aucune altitude n'est connue, <ele> ne devrait pas être écrit : {altitudes}"
    assert "None" not in texte, "« None » ne doit jamais être écrit dans un GPX"


def test_une_trace_sans_point_ne_produit_pas_un_gpx_mensonger():
    module = module_gpx
    trace = fabriques.trace_fictive([])
    texte, erreur = robuste(
        lambda: module.ecrire_gpx(trace, "vide"),
        quoi="ecrire_gpx(trace vide)",
        erreurs_acceptees=(ErreurUtilisateur,),
    )
    if erreur is None:
        racine = ET.fromstring(texte)
        assert not list(racine.iter("{http://www.topografix.com/GPX/1/1}trkpt")), (
            "une trace sans point ne doit pas engendrer de <trkpt>"
        )


# --- aller-retour ------------------------------------------------------------


def test_aller_retour_conserve_les_points_dans_l_ordre():
    module = module_gpx
    coords = fabriques.ligne(8, pas_m=350.0, cap_deg=115.0)
    trace = fabriques.trace_fictive(coords)
    relue, erreur = _lire(module, module.ecrire_gpx(trace, "aller-retour").encode("utf-8"))
    assert erreur is None, f"le GPX que l'on vient d'écrire doit se relire : {erreur}"

    fabriques.verifier_trace(relue, quoi="aller-retour", distance_max_km=50.0)
    assert len(relue.points) == len(coords), "tous les points doivent survivre"
    for i, (attendu, obtenu) in enumerate(zip(coords, relue.points, strict=True)):
        assert obtenu.lat == pytest.approx(attendu[0], abs=1e-6), f"points[{i}] : latitude perdue"
        assert obtenu.lon == pytest.approx(attendu[1], abs=1e-6), f"points[{i}] : longitude perdue"
        assert obtenu.alt_m == pytest.approx(attendu[2], abs=0.5), f"points[{i}] : altitude perdue"
    assert relue.distance_m == pytest.approx(trace.distance_m, rel=0.01), (
        "la distance doit se retrouver à 1 % près après un aller-retour"
    )
    assert relue.segments == [], "un GPX importé n'a pas de tronçon décrit (contrat §2)"


def test_aller_retour_d_une_boucle_reste_borne():
    module = module_gpx
    trace = fabriques.trace_fictive(fabriques.cercle(16, rayon_m=1200.0))
    assert trace.bornee(), "le cercle de départ est fermé"
    relue, erreur = _lire(module, module.ecrire_gpx(trace, "boucle").encode("utf-8"))
    assert erreur is None, f"relecture impossible : {erreur}"
    assert relue.bornee(), "une boucle écrite puis relue doit rester bornée"


# --- import ------------------------------------------------------------------


@pytest.mark.parametrize(
    "contenu, quoi",
    [
        (b"", "fichier vide"),
        (b"   \n", "fichier blanc"),
        (b"ceci n'est pas du XML", "texte brut"),
        (b"<gpx>", "XML tronqué"),
        (b"<?xml version='1.0'?><autre/>", "XML qui n'est pas du GPX"),
        (b"\x00\x01\x02binaire", "octets binaires"),
    ],
)
def test_un_gpx_illisible_donne_une_erreur_de_lecture(contenu, quoi):
    module = module_gpx
    _, erreur = _lire(module, contenu)
    assert erreur is not None, f"{quoi} : une ErreurLecture était attendue"
    assert isinstance(erreur, ErreurLecture), (
        f"{quoi} : le contrat demande ErreurLecture, reçu {type(erreur).__name__}"
    )
    assert str(erreur).strip(), f"{quoi} : message vide"


def test_un_fichier_absent_donne_une_erreur_utilisateur(tmp_path: Path):
    module = module_gpx
    _, erreur = _lire(module, tmp_path / "inexistant.gpx")
    assert erreur is not None, (
        "un chemin inexistant doit devenir une erreur utilisateur, pas un FileNotFoundError brut"
    )


def test_lire_accepte_un_chemin_et_des_octets(tmp_path: Path):
    module = module_gpx
    chemin = tmp_path / "essai.gpx"
    chemin.write_text(GPX_MINIMAL_TRK, encoding="utf-8")

    par_chemin, erreur_chemin = _lire(module, chemin)
    par_octets, erreur_octets = _lire(module, GPX_MINIMAL_TRK.encode("utf-8"))
    assert erreur_chemin is None and erreur_octets is None, (
        f"contrat §2 : `chemin_ou_bytes` ({erreur_chemin or erreur_octets})"
    )
    assert len(par_chemin.points) == len(par_octets.points) == 3


def test_une_route_seule_est_importee():
    """L'import lit la première `<trk>` ou, à défaut, la première `<rte>`."""
    module = module_gpx
    trace, erreur = _lire(module, GPX_ROUTE_SEULE.encode("utf-8"))
    assert erreur is None, f"une <rte> seule doit s'importer : {erreur}"
    assert len(trace.points) == 3, "les trois <rtept> attendus"
    fabriques.verifier_trace(trace, quoi="route seule", distance_max_km=50.0)


def test_un_gpx_sans_altitude_donne_des_altitudes_nulles():
    module = module_gpx
    trace, erreur = _lire(module, GPX_SANS_ALTITUDE.encode("utf-8"))
    assert erreur is None, f"l'altitude est facultative : {erreur}"
    assert all(p.alt_m is None for p in trace.points), (
        "sans <ele>, l'altitude vaut None — surtout pas 0, qui serait le niveau de la mer"
    )
    assert trace.denivele_m in (None, 0, 0.0), (
        f"aucun dénivelé ne peut être calculé sans altitude, reçu {trace.denivele_m!r}"
    )


def test_un_gpx_sans_point_ne_devient_pas_une_trace_fantome():
    module = module_gpx
    trace, erreur = _lire(module, GPX_TRACE_VIDE.encode("utf-8"))
    if erreur is None:
        assert trace.points == [], "une <trkseg> vide ne contient aucun point"
        assert trace.distance_m == 0, "une trace sans point mesure zéro"
        assert not trace.bornee(), "une trace sans point n'est pas une boucle"


def test_une_entite_externe_n_est_pas_resolue():
    """Un GPX peut venir d'un tiers : aucune entité ne doit ouvrir un fichier local."""
    module = module_gpx
    trace, erreur = _lire(module, GPX_ENTITE.encode("utf-8"))
    if erreur is None:
        assert "root:" not in (trace.nom or ""), "le contenu d'un fichier système a été injecté"


def test_les_distances_cumulees_sont_croissantes_et_coherentes():
    module = module_gpx
    trace, erreur = _lire(module, GPX_MINIMAL_TRK.encode("utf-8"))
    assert erreur is None, f"GPX minimal illisible : {erreur}"
    assert trace.points[0].dist_m == 0, "le premier point est à l'origine des distances"
    assert trace.points[-1].dist_m == pytest.approx(trace.distance_m, rel=0.01, abs=1.0), (
        "la distance cumulée du dernier point est la distance du tracé"
    )
