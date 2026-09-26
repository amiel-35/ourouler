"""`ourouler sortie` : la carte HTML.

Bouchons partagés : `outils_sortie_commande.py`.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from outils_sortie_commande import (
    _Compteur,
    carte_produite,
)

from ourouler.rendu import carte
from ourouler.rendu.carte import COULEURS_BLOCS

# Le fuseau que les bouchons Open-Meteo de ce module supposent (voir
# `fuseau_de_paris` dans conftest.py) : dit ici, pas emprunté à la machine.
pytestmark = pytest.mark.usefixtures("fuseau_de_paris")


def test_la_carte_se_parse_en_html_et_porte_le_nom_de_la_seance(
    tmp_path: Path, monkeypatch, capsys
):
    page = carte_produite(tmp_path, monkeypatch)
    capsys.readouterr()
    donnees = json.loads(re.search(r"^const D = (\{.*\});$", page, re.M).group(1))
    compteur = _Compteur()
    compteur.feed(page)
    assert compteur.desequilibres == []
    assert compteur.pile == []
    assert "4x8 fabriquée" in compteur.titre
    # Lot L5.4 : la page du jour porte un profil d'altitude **par proposition**
    # contrastée, chacun un vrai `<svg>` statique — un seul visible à la fois
    # (`hidden` posé par `_page_jour`, pas absent du HTML), c'est ce qui permet
    # de changer de proposition sans redemander de calcul au serveur.
    assert compteur.balises.get("svg") == len(donnees["propositions"])
    assert compteur.balises.get("script") == 2  # Leaflet, puis le script de la page


def test_la_carte_porte_les_quatre_blocs_avec_leur_note(tmp_path: Path, monkeypatch, capsys):
    page = carte_produite(tmp_path, monkeypatch)
    capsys.readouterr()
    donnees = json.loads(re.search(r"^const D = (\{.*\});$", page, re.M).group(1))
    # Lot L5.4 : la page porte une liste `propositions`, chacune avec ses
    # propres blocs — la première est celle que le tri a retenue.
    premiere = donnees["propositions"][0]
    assert len(premiere["blocs"]) == 4
    for numero, bloc in enumerate(premiere["blocs"], start=1):
        assert bloc["couleur"] == COULEURS_BLOCS[numero - 1]
        assert bloc["etiquette"].startswith(f"{numero} ·")
        assert "Bloc" in bloc["infobulle"]
        assert len(bloc["pts"]) >= 2
    # Les liaisons (échauffement, récups, calme) sont là et ne portent pas de note.
    assert premiere["liaisons"]


def test_la_carte_ne_contient_que_la_geometrie_du_trace(tmp_path: Path, monkeypatch, capsys):
    """Aucune coordonnée ne vient du générateur : tout sort du tracé passé en paramètre."""
    page = carte_produite(tmp_path, monkeypatch)
    capsys.readouterr()
    donnees = json.loads(re.search(r"^const D = (\{.*\});$", page, re.M).group(1))
    premiere = donnees["propositions"][0]
    points = {tuple(p) for p in premiere["trace"]}
    assert tuple(premiere["depart"]) in points
    for bloc in premiere["blocs"]:
        # Les extrémités d'un bloc sont interpolées ; le reste vient du tracé.
        assert sum(1 for p in bloc["pts"] if tuple(p) in points) >= len(bloc["pts"]) - 2
    lat_max = max(abs(lat) for lat, _ in points)
    assert lat_max < 0.2  # le point fictif (0, 0), rien d'autre


def test_la_carte_utilise_le_cdn_autorise_et_osm(tmp_path: Path, monkeypatch, capsys):
    page = carte_produite(tmp_path, monkeypatch)
    capsys.readouterr()
    assert "https://cdnjs.cloudflare.com/ajax/libs/leaflet/" in page
    assert "tile.openstreetmap.org" in page
    externes = set(re.findall(r"https?://[a-z0-9.\-]+", page))
    # `www.openstreetmap.org` n'est pas une ressource chargée : c'est le lien
    # d'attribution que l'ODbL impose (C4), et il ne part que si l'on clique.
    assert externes <= {
        "https://cdnjs.cloudflare.com",
        "https://tile.openstreetmap.org",
        "https://www.openstreetmap.org",
    }, externes


def test_l_attribution_openstreetmap_est_un_lien_vers_la_licence(tmp_path: Path, monkeypatch, capsys):
    """C4 : l'ODbL demande une attribution qui **pointe** vers la page de licence."""
    page = carte_produite(tmp_path, monkeypatch)
    capsys.readouterr()
    donnees = json.loads(re.search(r"^const D = (\{.*\});$", page, re.M).group(1))
    attribution = donnees["tuiles"]["attribution"]
    assert "OpenStreetMap" in attribution
    assert 'href="https://www.openstreetmap.org/copyright"' in attribution, (
        f"attribution sans lien vers la licence : {attribution!r}"
    )


def test_la_charge_json_de_la_carte_ne_peut_pas_fermer_le_script(
    tmp_path: Path, monkeypatch, capsys
):
    """C3 : `<` est neutralisé à la sérialisation, pas seulement en amont.

    Rien aujourd'hui ne fait entrer `</script>` dans la charge — tout le texte
    libre passe par `html.escape`. La garantie tenait donc à ce chemin-là et
    non à la sérialisation : le jour où un champ arrive sans échappement, la
    page devient injectable. On mesure la sérialisation elle-même.
    """
    charge = carte._charge_json({"motif": "</script><img src=x onerror=alert(1)>"})
    assert "<" not in charge and ">" not in charge, charge
    assert json.loads(charge)["motif"] == "</script><img src=x onerror=alert(1)>"

    page = carte_produite(tmp_path, monkeypatch)
    capsys.readouterr()
    script = re.search(r"^const D = (\{.*\});$", page, re.M).group(1)
    assert "<" not in script and ">" not in script


def test_la_carte_dessine_le_profil_d_altitude(tmp_path: Path, monkeypatch, capsys):
    page = carte_produite(tmp_path, monkeypatch)
    capsys.readouterr()
    profil = re.search(r"<svg .*?</svg>", page, re.S).group(0)
    assert profil.count("<polyline") >= 5  # le tracé, plus un par bloc
    for couleur in COULEURS_BLOCS[:4]:
        assert couleur in profil
