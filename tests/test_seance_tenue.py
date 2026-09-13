"""Tests de `seance.tenue` (sprint 4, lot L4.3).

Aucune coordonnée réelle : les échantillons sont posés en mer au large du
golfe de Guinée (0, 0), comme les autres tracés synthétiques du dépôt.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from ourouler.boucle.meteo_trace import Echantillon, MeteoTrace
from ourouler.config import ParametresTenue
from ourouler.seance.tenue import (
    CATEGORIES_PLUIE,
    CATEGORIES_TEMP,
    INCONNU,
    TENUES_DEFAUT,
    VESTE_PLUIE,
    VESTE_VENT,
    conseiller,
)

DEPART = datetime(2026, 9, 13, 8, 0, tzinfo=UTC)


def _meteo(*mesures: tuple[float, float | None, float | None, float | None]) -> MeteoTrace:
    """Une `MeteoTrace` à partir de (km, ressenti °C, pluie mm/h, vent km/h)."""
    echantillons = [
        Echantillon(
            dist_m=km * 1000.0,
            t=DEPART + timedelta(minutes=2 * i),
            lat=0.0,
            lon=0.0,
            cap_deg=90.0,
            pluie_mm=pluie,
            vent_kmh=vent,
            vent_relatif=None,
            ressenti_c=ressenti,
        )
        for i, (km, ressenti, pluie, vent) in enumerate(mesures)
    ]
    ressentis = [e.ressenti_c for e in echantillons if e.ressenti_c is not None]
    return MeteoTrace(
        echantillons=echantillons,
        pluie_cumulee_mm=0.0,
        minutes_pluie=0.0,
        part_vent_face=0.0,
        part_vent_dos=0.0,
        ressenti_min_c=min(ressentis) if ressentis else None,
        confiance="inconnu",
    )


P = ParametresTenue()


def test_categories_de_temperature_aux_bornes_exactes():
    # La borne appartient à la catégorie supérieure : 3,0 °C, c'est « froid ».
    attendus = [
        (2.99, "très froid"),
        (3.0, "froid"),
        (8.99, "froid"),
        (9.0, "frais"),
        (15.0, "modéré"),
        (22.0, "chaud"),
        (29.99, "chaud"),
        (30.0, "canicule"),
        (-10.0, "très froid"),
    ]
    for ressenti, categorie in attendus:
        tenue = conseiller(_meteo((0.0, ressenti, 0.0, 5.0)), P)
        assert tenue.categorie_temp == categorie, ressenti
    assert set(CATEGORIES_TEMP) == {c for _, c in attendus}


def test_categories_d_humidite_aux_bornes_exactes():
    attendus = [(0.0, "sec"), (0.19, "sec"), (0.2, "humide"), (0.5, "averses"), (1.0, "pluie")]
    for pluie, categorie in attendus:
        tenue = conseiller(_meteo((0.0, 18.0, pluie, 5.0)), P)
        assert tenue.categorie_humidite == categorie, pluie
    assert set(CATEGORIES_PLUIE) == {c for _, c in attendus}


def test_la_base_se_decide_au_depart_pas_sur_la_suite():
    # Départ froid, parcours qui se réchauffe : on part couvert, on prévoit d'enlever.
    tenue = conseiller(
        _meteo((0.0, 5.0, 0.0, 10.0), (20.0, 16.0, 0.0, 10.0), (40.0, 24.0, 0.0, 10.0)), P
    )
    assert tenue.categorie_temp == "froid"
    assert tenue.base == list(TENUES_DEFAUT["froid"])
    # « chaud » ne garde ni le collant, ni le gilet, ni les gants : à enlever.
    assert "gilet coupe-vent" in tenue.a_enlever
    assert "collant long" in tenue.a_enlever
    assert "maillot manches longues" in tenue.a_enlever
    assert any("monte à 24" in m for m in tenue.motifs)


def test_ressenti_qui_redescend_fait_emporter_et_garder():
    # Départ doux, fin de sortie franchement plus fraîche (retour tardif).
    tenue = conseiller(
        _meteo((0.0, 16.0, 0.0, 10.0), (30.0, 14.0, 0.0, 10.0), (60.0, 7.0, 0.0, 10.0)), P
    )
    assert tenue.categorie_temp == "modéré"
    assert "gants longs" in tenue.a_emporter
    assert any("redescend à 7" in m for m in tenue.motifs)


def test_pluie_au_dela_du_seuil_fait_emporter_la_veste():
    sec = conseiller(_meteo((0.0, 18.0, 0.19, 5.0), (30.0, 18.0, 0.1, 5.0)), P)
    assert VESTE_PLUIE not in sec.a_emporter

    # Pile sur la borne : « humide », et la veste part avec nous.
    humide = conseiller(_meteo((0.0, 18.0, 0.0, 5.0), (30.0, 18.0, 0.2, 5.0)), P)
    assert humide.categorie_humidite == "humide"
    assert VESTE_PLUIE in humide.a_emporter

    averse = conseiller(_meteo((0.0, 18.0, 0.0, 5.0), (30.0, 18.0, 0.6, 5.0)), P)
    assert VESTE_PLUIE in averse.a_emporter
    assert averse.categorie_humidite == "averses"
    assert any("km 30" in m for m in averse.motifs)


def test_le_vent_seul_declenche_la_veste():
    calme = conseiller(_meteo((0.0, 18.0, 0.0, 29.9)), P)
    assert VESTE_VENT not in calme.a_emporter

    vente = conseiller(_meteo((0.0, 18.0, 0.0, 20.0), (25.0, 18.0, 0.0, 30.0)), P)
    assert VESTE_VENT in vente.a_emporter
    assert any("vent jusqu'à 30" in m for m in vente.motifs)


def test_un_gilet_coupe_vent_ne_remplace_pas_la_veste():
    """À 35 km/h de vent, ce sont les bras qui prennent (contrat §3)."""
    tenue = conseiller(_meteo((0.0, 14.0, 0.0, 35.0)), P)
    assert "gilet coupe-vent" in tenue.base  # tenue « frais »
    assert VESTE_VENT in tenue.a_emporter
    assert any("emporter la veste coupe-vent" in m for m in tenue.motifs)


def test_la_veste_coupe_vent_deja_sur_le_dos_n_est_pas_a_emporter():
    """La tenue « très froid » en porte une : le motif le dit plutôt que de se taire."""
    tenue = conseiller(_meteo((0.0, 1.0, 0.0, 45.0)), P)
    assert tenue.categorie_temp == "très froid"
    assert VESTE_VENT in tenue.base
    assert tenue.a_emporter == []
    assert any("déjà dans la tenue de base" in m for m in tenue.motifs)


def test_aucun_echantillon():
    tenue = conseiller(_meteo(), P)
    assert tenue.categorie_temp == INCONNU
    assert tenue.categorie_humidite == INCONNU
    assert tenue.base == [] and tenue.a_emporter == [] and tenue.a_enlever == []
    assert tenue.motifs and "aucun échantillon" in tenue.motifs[0]


def test_ressenti_absent_ne_conseille_rien_mais_lit_la_pluie():
    tenue = conseiller(_meteo((0.0, None, 2.0, 10.0), (20.0, None, 2.0, 10.0)), P)
    assert tenue.categorie_temp == INCONNU
    assert tenue.base == []
    assert tenue.a_enlever == []
    assert VESTE_PLUIE in tenue.a_emporter  # la pluie, elle, est connue
    assert any("ressenti inconnu" in m for m in tenue.motifs)


def test_pluie_absente_ne_conseille_pas_de_veste():
    tenue = conseiller(_meteo((0.0, 12.0, None, 10.0), (20.0, 12.0, None, 10.0)), P)
    assert tenue.categorie_humidite == INCONNU
    assert VESTE_PLUIE not in tenue.a_emporter
    assert any("pluie inconnue" in m for m in tenue.motifs)


def test_les_tenues_de_la_configuration_remplacent_le_defaut():
    @dataclass(frozen=True)
    class TenueConfiguree(ParametresTenue):
        tenues: dict[str, tuple[str, ...]] = field(default_factory=dict)

    p = TenueConfiguree(tenues={"frais": ["maillot de laine", "casquette"]})
    tenue = conseiller(_meteo((0.0, 12.0, 0.0, 5.0)), p)
    assert tenue.base == ["maillot de laine", "casquette"]
    # Les autres catégories gardent le défaut.
    autre = conseiller(_meteo((0.0, 25.0, 0.0, 5.0)), p)
    assert autre.base == list(TENUES_DEFAUT["chaud"])


def test_bornes_inhabituelles_donnent_des_paliers_numerotes():
    p = ParametresTenue(bornes_c=(10.0,))
    tenue = conseiller(_meteo((0.0, 20.0, 0.0, 5.0)), p)
    assert tenue.categorie_temp == "palier 2 sur 2"
    assert tenue.base == []
    assert any("aucune tenue" in m for m in tenue.motifs)
