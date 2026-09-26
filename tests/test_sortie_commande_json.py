"""`ourouler sortie --json` : le document publié.

Bouchons partagés : `outils_sortie_commande.py`.
"""

from __future__ import annotations

import json
import types
from pathlib import Path

import pytest
from outils_sortie_commande import (
    JOUR,
    PARAMETRES,
    config_de_test,
    lancer,
)

from ourouler.noyau.seance import Etape, Seance
from ourouler.sortie.commande import (
    _distance,
)

# Le fuseau que les bouchons Open-Meteo de ce module supposent (voir
# `fuseau_de_paris` dans conftest.py) : dit ici, pas emprunté à la machine.
pytestmark = pytest.mark.usefixtures("fuseau_de_paris")


# --- JSON ----------------------------------------------------------------------


def test_le_json_est_valide_et_complet(tmp_path: Path, monkeypatch, capsys):
    code = lancer(tmp_path, monkeypatch, json=True)
    charge = json.loads(capsys.readouterr().out)
    assert code == 0
    assert charge["jour"] == JOUR.isoformat()
    assert charge["seance"]["n_blocs"] == 4
    assert charge["gpx"].endswith(".gpx")
    assert charge["carte"].endswith(".html")
    assert charge["tenue"]["base"]
    candidate = charge["candidates"][0]
    assert candidate["retenue"] is True
    # Depuis le lot L5.2 (Q13), `emplacements` porte toutes les étapes, pas
    # seulement les blocs : échauffement, 4 blocs, 4 récupérations, retour au
    # calme — 10 étapes pour 4 blocs.
    assert len(candidate["placement"]["emplacements"]) == 10
    for emplacement in candidate["placement"]["emplacements"]:
        assert emplacement["longueur_m"] > 0
        if emplacement["note"] is None:
            assert emplacement["motifs"] is None, (
                "une étape sans note ne doit pas porter de motifs inventés"
            )
        else:
            assert isinstance(emplacement["motifs"], list)
    # Lot L5.3 : `km_non_classe` manquait côté sortie alors qu'il existait déjà
    # côté boucle libre — sans lui, un tracé partiellement classé s'annonce
    # aussi calme qu'un tracé entièrement classé.
    assert "km_non_classe" in candidate["couts"]
    # Les flèches de vent (mêmes que la carte HTML) sont aussi dans ce JSON ;
    # le vent bouchonné par défaut (14 km/h) dépasse le seuil sensible.
    fleches = candidate["meteo"]["fleches_vent"]
    assert fleches, "un vent bouchonné à 14 km/h doit produire des flèches"
    for fleche in fleches:
        assert set(fleche) == {"pt", "depuis_deg", "vent_kmh", "rafale_kmh", "relatif"}
    # Le tracé entier, pour le colorer (lot d'affordance, 20/09/2026) : une
    # position par échantillon, sans le filtre de sensibilité de `fleches_vent`
    # — donc au moins autant de positions que de flèches.
    positions = candidate["meteo"]["vent_par_position"]
    assert len(positions) >= len(fleches)
    for position in positions:
        assert set(position) == {"dist_m", "relatif"}


def test_une_etape_libre_compte_dans_le_dimensionnement(tmp_path: Path):
    """Une étape sans puissance prescrite n'est pas une étape de longueur nulle.

    Faute trouvée le 16/09/2026 sur la séance de référence « 4x8 SV1 outdoor »
    du 22/04 : 22 étapes, dont trois « libres » — échauffement 20 min,
    récupération 12 min, retour au calme 40 min. `_distance` ne sommait que
    les longueurs chiffrées, donc **63 min sur 135 seulement comptaient** :
    le moteur demandait une boucle de 35 km pour une sortie de 67, puis
    rattrapait en roulant la boucle presque deux fois avec des demi-tours
    dont personne n'avait besoin.

    Le test compare deux séances de même durée : l'une entièrement chiffrée,
    l'autre dont la moitié est libre. Les distances demandées doivent rester
    du même ordre — sans le repli à l'allure d'endurance, la seconde tombe à
    la moitié de la première.
    """
    config = config_de_test(tmp_path)
    parametres = PARAMETRES
    chiffree = Seance(
        nom="chiffrée",
        jour=JOUR,
        duree_s=3600.0,
        etapes=[
            Etape("echauffement", 1800.0, 150.0, 150.0, "Z2"),
            Etape("bloc", 1800.0, 150.0, 150.0, "Z2"),
        ],
    )
    moitie_libre = Seance(
        nom="moitié libre",
        jour=JOUR,
        duree_s=3600.0,
        etapes=[
            Etape("echauffement", 1800.0, None, None, "libre"),
            Etape("bloc", 1800.0, 150.0, 150.0, "Z2"),
        ],
    )
    demande = types.SimpleNamespace(distance_km=None)
    km_chiffree, _ = _distance(demande, chiffree, parametres, config)
    km_libre, _ = _distance(demande, moitie_libre, parametres, config)
    assert km_libre > km_chiffree * 0.7, (
        f"une séance à moitié libre est dimensionnée à {km_libre} km contre "
        f"{km_chiffree} km pour la même durée entièrement chiffrée : les étapes "
        "libres comptent encore pour zéro"
    )


def test_une_etape_libre_sans_ftp_retombe_sur_la_vitesse_moyenne(tmp_path: Path):
    """Point 4 (T5) : `pct * ftp_w` avec `ftp_w=None` levait `TypeError`.

    Sans FTP renseignée, les minutes des étapes libres ne peuvent plus être
    converties en distance par le modèle physique — repli silencieux sur
    `config.boucle.vitesse_moyenne_kmh`, la même vitesse assumée que le repli
    « aucune étape chiffrée du tout » déjà présent dans `_distance`.
    """
    config = config_de_test(tmp_path, cycliste={"masse_kg": 76.5})
    assert config.cycliste.ftp_w is None
    parametres = PARAMETRES
    moitie_libre = Seance(
        nom="moitié libre",
        jour=JOUR,
        duree_s=3600.0,
        etapes=[
            Etape("echauffement", 1800.0, None, None, "libre"),
            Etape("bloc", 1800.0, 150.0, 150.0, "Z2"),
        ],
    )
    demande = types.SimpleNamespace(distance_km=None)
    km, source = _distance(demande, moitie_libre, parametres, config)
    assert km > 0
    assert "faute de FTP renseignée" in source
