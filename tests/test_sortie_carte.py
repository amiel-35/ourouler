"""Tests des flèches de vent sur la carte (lot du 16/09/2026).

`meteo` est optionnel de bout en bout : une carte sans météo doit continuer
de se construire exactement comme avant les flèches — c'est ce que
`test_construire_sans_meteo_ne_change_rien` vérifie. Le reste porte sur
`_vent_fleches`, qui décide quel échantillon devient une flèche.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, date, datetime

import pytest

from ourouler.boucle.meteo_trace import Echantillon, MeteoTrace
from ourouler.boucle.trace import PointTrace, Trace
from ourouler.seance.modele import Seance
from ourouler.seance.placement import Placement
from ourouler.sortie import carte

T0 = datetime(2026, 9, 16, 8, 0, tzinfo=UTC)


def echantillon(
    dist_m: float = 0.0,
    vent_kmh: float | None = 20.0,
    vent_depuis_deg: float | None = 90.0,
    rafales_kmh: float | None = 30.0,
    vent_relatif: str | None = "face",
    lat: float = 1.0,
    lon: float = 2.0,
) -> Echantillon:
    return Echantillon(
        dist_m=dist_m,
        t=T0,
        lat=lat,
        lon=lon,
        cap_deg=90.0,
        pluie_mm=0.0,
        vent_kmh=vent_kmh,
        vent_relatif=vent_relatif,
        ressenti_c=15.0,
        vent_depuis_deg=vent_depuis_deg,
        rafales_kmh=rafales_kmh,
    )


def meteo(*echantillons: Echantillon) -> MeteoTrace:
    return MeteoTrace(
        echantillons=list(echantillons),
        pluie_cumulee_mm=0.0,
        minutes_pluie=0.0,
        part_vent_face=0.0,
        part_vent_dos=0.0,
        ressenti_min_c=None,
        confiance="inconnu",
    )


# --- _vent_fleches : ce qui filtre --------------------------------------------


def test_vent_fleches_meteo_absente_rend_liste_vide():
    assert carte._vent_fleches(None) == []


def test_vent_fleches_sous_le_seuil_est_ecarte():
    m = meteo(echantillon(vent_kmh=carte.SEUIL_AFFICHAGE_VENT_KMH - 0.1))
    assert carte._vent_fleches(m) == []


def test_vent_fleches_au_seuil_pile_est_garde():
    """Le seuil filtre strictement en dessous, pas au ras du seuil lui-même."""
    m = meteo(echantillon(vent_kmh=carte.SEUIL_AFFICHAGE_VENT_KMH))
    assert len(carte._vent_fleches(m)) == 1


def test_vent_fleches_vent_absent_est_ecarte():
    m = meteo(echantillon(vent_kmh=None))
    assert carte._vent_fleches(m) == []


def test_vent_fleches_direction_absente_est_ecartee():
    """Sans direction, aucune rotation n'a de sens : on n'en invente pas une (règle 5)."""
    m = meteo(echantillon(vent_kmh=25.0, vent_depuis_deg=None))
    assert carte._vent_fleches(m) == []


# --- _vent_fleches : ce qui est transporté ------------------------------------


def test_vent_fleches_transporte_position_direction_vitesse_et_relatif():
    m = meteo(echantillon(vent_kmh=17.6, vent_depuis_deg=123.4, lat=3.5, lon=-1.25, vent_relatif="dos"))
    fleches = carte._vent_fleches(m)
    assert len(fleches) == 1
    f = fleches[0]
    assert f["pt"] == [3.5, -1.25]
    assert f["depuis_deg"] == pytest.approx(123.4)
    assert f["vent_kmh"] == 18  # arrondi à l'entier
    assert f["relatif"] == "dos"


def test_vent_fleches_arrondit_vitesse_et_rafale_a_l_entier():
    m = meteo(echantillon(vent_kmh=14.49, rafales_kmh=22.5))
    f = carte._vent_fleches(m)[0]
    assert f["vent_kmh"] == 14
    assert f["rafale_kmh"] == round(22.5)


def test_vent_fleches_rafale_absente_reste_absente_jamais_zero():
    m = meteo(echantillon(vent_kmh=20.0, rafales_kmh=None))
    f = carte._vent_fleches(m)[0]
    assert f["rafale_kmh"] is None


def test_vent_fleches_un_point_par_echantillon_au_dessus_du_seuil():
    m = meteo(
        echantillon(dist_m=0.0, vent_kmh=5.0),  # sous le seuil
        echantillon(dist_m=5000.0, vent_kmh=25.0),
        echantillon(dist_m=10_000.0, vent_kmh=30.0),
    )
    assert len(carte._vent_fleches(m)) == 2


# --- intégration dans construire() --------------------------------------------


def _trace_droite(longueur_m: float = 10_000.0) -> Trace:
    """Une droite fictive, avec de l'altitude : `_profil_svg` dessine alors un `<svg>`."""
    n = 11
    pas = longueur_m / (n - 1)
    points = [
        PointTrace(lat=0.0, lon=i * pas / 111_194.9, alt_m=10.0 + i, dist_m=i * pas) for i in range(n)
    ]
    return Trace(
        nom="droite", points=points, segments=[], distance_m=longueur_m, denivele_m=None, temps_moteur_s=None
    )


def _seance_vide() -> Seance:
    return Seance(nom="essai", jour=date(2026, 9, 16), etapes=[], duree_s=0.0)


def _placement_vide() -> Placement:
    return Placement(
        decalage_z2_s=0.0, emplacements=[], note_totale=0.0, duree_totale_s=0.0, distance_totale_m=0.0
    )


def _charge(page: str) -> dict:
    return json.loads(re.search(r"^const D = (\{.*\});$", page, re.M).group(1))


def test_construire_sans_meteo_ne_change_rien():
    """`meteo=None` (le défaut) : pas de flèche, pas de section « Vent »."""
    page = carte.construire(_trace_droite(), _seance_vide(), _placement_vide())
    assert _charge(page)["vent"] == []
    assert "<h3>Vent</h3>" not in page


def test_construire_avec_meteo_ajoute_les_fleches_et_la_legende():
    m = meteo(echantillon(dist_m=0.0, vent_kmh=20.0, lat=0.0, lon=0.0))
    page = carte.construire(_trace_droite(), _seance_vide(), _placement_vide(), meteo=m)
    donnees = _charge(page)
    assert len(donnees["vent"]) == 1
    assert "<h3>Vent</h3>" in page


def test_construire_avec_meteo_mais_tout_sous_le_seuil_garde_la_legende_sans_fleche():
    """`meteo` non `None` mais rien d'assez venté : la légende explique pourquoi, elle ne disparaît pas."""
    m = meteo(echantillon(vent_kmh=1.0))
    page = carte.construire(_trace_droite(), _seance_vide(), _placement_vide(), meteo=m)
    assert _charge(page)["vent"] == []
    assert "<h3>Vent</h3>" in page


def test_construire_ne_dessine_toujours_qu_un_seul_vrai_svg():
    """Les glyphes de la légende du vent ne sont pas des `<svg>` : un seul dans le
    HTML statique, celui du profil d'altitude — les flèches de la carte sont
    construites par le script, à l'exécution, pas dans le HTML de la page.

    `HTMLParser` et non un comptage de sous-chaîne : le texte `<svg` apparaît
    aussi dans le `<script>`, où il fait partie d'une chaîne JavaScript et
    n'est pas une vraie balise — `HTMLParser` traite ce bloc comme du texte
    brut (CDATA), exactement comme un navigateur.
    """
    from html.parser import HTMLParser

    class _Compteur(HTMLParser):
        def __init__(self) -> None:
            super().__init__(convert_charrefs=True)
            self.svg = 0

        def handle_starttag(self, tag, attrs):
            if tag == "svg":
                self.svg += 1

    m = meteo(echantillon(vent_kmh=20.0))
    page = carte.construire(_trace_droite(), _seance_vide(), _placement_vide(), meteo=m)
    compteur = _Compteur()
    compteur.feed(page)
    assert compteur.svg == 1
