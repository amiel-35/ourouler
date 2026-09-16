"""Tests de la page du jour (lot L5.4) : `carte.construire_page_jour`.

Unitaires, sans réseau ni fichier — les mêmes fabriques que
`test_sortie_carte.py` (importées, pas dupliquées), une `PropositionCarte`
par proposition fictive. `sortie.commande` a ses propres tests d'intégration
(`test_sortie_commande.py::carte_produite`, `::test_la_carte_*`) ; ici on
vérifie le module `carte` seul : ce qu'il dessine à partir de ce qu'on lui
donne, sans reconstruire une vraie séance placée.
"""

from __future__ import annotations

import base64
import json
import re
from html.parser import HTMLParser

import pytest
from test_sortie_carte import _placement_vide, _seance_vide, _trace_droite, echantillon, meteo

from ourouler.sortie import carte

GPX_TEXTE = (
    '<?xml version="1.0"?>\n'
    '<gpx xmlns="http://www.topografix.com/GPX/1/1" creator="ourouler">\n'
    "<trk><name>essai</name><trkseg></trkseg></trk></gpx>\n"
)


def _prop(
    numero: int,
    *,
    distinction: str = "",
    chiffres: str = "",
    sous_titre: str = "",
    notes=(),
    meteo_=None,
    gpx_texte: str = GPX_TEXTE,
) -> carte.PropositionCarte:
    return carte.PropositionCarte(
        numero=numero,
        trace=_trace_droite(),
        placement=_placement_vide(),
        meteo=meteo_,
        distinction=distinction,
        chiffres=chiffres,
        sous_titre=sous_titre,
        notes=notes,
        gpx_nom=f"sortie_n{numero}.gpx",
        gpx_texte=gpx_texte,
    )


def _charge(page: str) -> dict:
    return json.loads(re.search(r"^const D = (\{.*\});$", page, re.M).group(1))


# --- garde-fous ------------------------------------------------------------


def test_construire_page_jour_refuse_une_liste_vide():
    with pytest.raises(ValueError):
        carte.construire_page_jour(_seance_vide(), [])


def test_construire_page_jour_accepte_une_seule_proposition():
    """Une candidate seule est un cas normal (contrat §3.3.6 e) : pas de plantage,
    pas de sélecteur à comparer inutilement — juste rien à contraster."""
    page = carte.construire_page_jour(_seance_vide(), [_prop(1, distinction="")])
    donnees = _charge(page)
    assert len(donnees["propositions"]) == 1


# --- plusieurs propositions --------------------------------------------------


def test_page_jour_porte_une_entree_par_proposition():
    props = [
        _prop(1, distinction="vous rentrez avec le vent dans le dos"),
        _prop(2, distinction="aucun demi-tour"),
        _prop(3, distinction="la plus sèche"),
    ]
    page = carte.construire_page_jour(_seance_vide(), props)
    donnees = _charge(page)
    assert [p["n"] for p in donnees["propositions"]] == [1, 2, 3]


def test_page_jour_seule_la_premiere_proposition_est_visible_au_chargement():
    """Pas d'onglet, mais un défaut : la première (celle du tri) est active,
    les autres portent `hidden` — elles restent dans le HTML, prêtes à
    s'afficher sans redemander de calcul au serveur (contrat §4.1)."""
    props = [_prop(1), _prop(2), _prop(3)]
    page = carte.construire_page_jour(_seance_vide(), props)
    assert '<div class="panneau-prop" data-prop="1">' in page
    assert '<div class="panneau-prop" data-prop="2" hidden>' in page
    assert '<div class="panneau-prop" data-prop="3" hidden>' in page


def test_page_jour_couleur_grise_distincte_de_la_couleur_active():
    """« Les deux autres retombent en trait gris fin » (contrat §4.1) : deux
    teintes différentes, pas la même, sans quoi rien ne distinguerait la
    sélection sur la carte."""
    page = carte.construire_page_jour(_seance_vide(), [_prop(1), _prop(2)])
    donnees = _charge(page)
    assert donnees["couleurs"]["autre"] != donnees["couleurs"]["trace"]


# --- un seul vrai <svg> par profil, exactement 2 <script> -------------------


def test_page_jour_un_svg_par_proposition_deux_scripts_leaflet_et_page():
    class _Compteur(HTMLParser):
        def __init__(self) -> None:
            super().__init__(convert_charrefs=True)
            self.balises: dict[str, int] = {}

        def handle_starttag(self, tag, attrs):
            self.balises[tag] = self.balises.get(tag, 0) + 1

    props = [_prop(1), _prop(2), _prop(3)]
    page = carte.construire_page_jour(_seance_vide(), props)
    compteur = _Compteur()
    compteur.feed(page)
    assert compteur.balises.get("svg") == 3
    assert compteur.balises.get("script") == 2


# --- échappement -------------------------------------------------------------


def test_page_jour_echappe_la_distinction_les_chiffres_et_le_motif():
    import html as _html

    charge_utile = "</script><img src=x onerror=alert(1)>"
    echappe = _html.escape(charge_utile)
    props = [
        _prop(
            1,
            distinction=charge_utile,
            chiffres=charge_utile,
            sous_titre=charge_utile,
            notes=[charge_utile],
        ),
        _prop(2),
    ]
    page = carte.construire_page_jour(_seance_vide(), props, motif_deux_propositions=charge_utile)
    assert "<img src=x onerror" not in page
    assert charge_utile not in page
    assert page.count(echappe) >= 4  # distinction, chiffres, sous-titre/note, motif


# --- le GPX : base64, pas d'URL en clair, décodable ---------------------------


def test_page_jour_encode_le_gpx_en_base64_sans_url_topografix_en_clair():
    """Le GPX porte `xmlns="http://www.topografix.com/GPX/1/1"` : en clair
    dans la page, cette URL romprait la promesse « seules cdnjs et OSM sont
    chargées » (même si ce n'est qu'une charge JSON, pas une ressource
    récupérée) — d'où le passage par base64."""
    page = carte.construire_page_jour(_seance_vide(), [_prop(1, gpx_texte=GPX_TEXTE)])
    assert "topografix.com" not in page
    donnees = _charge(page)
    b64 = donnees["propositions"][0]["gpx_b64"]
    assert base64.b64decode(b64).decode("utf-8") == GPX_TEXTE


def test_page_jour_gpx_nom_attendu_pour_le_telechargement():
    props = [_prop(1), _prop(2)]
    page = carte.construire_page_jour(_seance_vide(), props)
    donnees = _charge(page)
    assert [p["gpx_nom"] for p in donnees["propositions"]] == ["sortie_n1.gpx", "sortie_n2.gpx"]
    assert 'download="sortie_n1.gpx"' in page
    assert 'download="sortie_n2.gpx"' in page


# --- le motif à deux propositions --------------------------------------------


def test_page_jour_affiche_le_motif_quand_il_y_a_deux_propositions():
    page = carte.construire_page_jour(
        _seance_vide(),
        [_prop(1), _prop(2)],
        motif_deux_propositions="2 proposition(s) au lieu de 3 : aucune ne se distinguait.",
    )
    assert "2 proposition(s) au lieu de 3" in page


def test_page_jour_pas_de_motif_pas_de_paragraphe_motif():
    page = carte.construire_page_jour(_seance_vide(), [_prop(1), _prop(2)])
    assert 'class="note motif"' not in page


# --- le vent, par proposition -------------------------------------------------


def test_page_jour_vent_present_seulement_pour_la_proposition_qui_a_une_meteo():
    m = meteo(echantillon(vent_kmh=25.0))
    props = [_prop(1, meteo_=m), _prop(2, meteo_=None)]
    page = carte.construire_page_jour(_seance_vide(), props)
    donnees = _charge(page)
    assert len(donnees["propositions"][0]["vent"]) == 1
    assert donnees["propositions"][1]["vent"] == []


# --- CDN et OSM, comme la carte simple ---------------------------------------


def test_page_jour_utilise_le_cdn_autorise_et_osm_seulement():
    page = carte.construire_page_jour(_seance_vide(), [_prop(1), _prop(2), _prop(3)])
    externes = set(re.findall(r"https?://[a-z0-9.\-]+", page))
    assert externes <= {
        "https://cdnjs.cloudflare.com",
        "https://tile.openstreetmap.org",
        "https://www.openstreetmap.org",
    }, externes
