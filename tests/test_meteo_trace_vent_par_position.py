"""Tests de `boucle.meteo_trace.vent_par_position` (lot d'affordance, 20/09/2026).

Échantillons **fabriqués** autour de (0.0, 0.0), en pleine mer dans le golfe
de Guinée : aucune coordonnée réelle, aucun réseau (règles absolues 1 et 3).
`Echantillon` est construit directement, sans passer par `evaluer` ni par un
client météo — même socle que `test_meteo_trace_fleches.py`.
"""

from __future__ import annotations

from datetime import UTC, datetime

from ourouler.boucle.meteo_trace import (
    SEUIL_VENT_SENSIBLE_KMH,
    Echantillon,
    MeteoTrace,
    vent_par_position,
)
from ourouler.meteo.rapport import CONFIANCE_INCONNUE, VENT_DOS, VENT_FACE, VENT_TRAVERS

T0 = datetime(2026, 9, 17, 8, 0, tzinfo=UTC)


def echantillon(
    *,
    dist_m: float = 0.0,
    vent_kmh: float | None = 20.0,
    vent_depuis_deg: float | None = 90.0,
    vent_relatif: str | None = VENT_FACE,
) -> Echantillon:
    """Un échantillon au golfe de Guinée, sans rien qui ressemble à une vraie sortie."""
    return Echantillon(
        dist_m=dist_m,
        t=T0,
        lat=0.0,
        lon=dist_m / 111_000.0,
        cap_deg=0.0,
        pluie_mm=0.0,
        vent_kmh=vent_kmh,
        vent_relatif=vent_relatif,
        ressenti_c=18.0,
        vent_depuis_deg=vent_depuis_deg,
    )


def meteo(echantillons: list[Echantillon]) -> MeteoTrace:
    """Une `MeteoTrace` minimale : seuls les échantillons comptent pour `vent_par_position`."""
    return MeteoTrace(
        echantillons=echantillons,
        pluie_cumulee_mm=0.0,
        minutes_pluie=0.0,
        part_vent_face=0.0,
        part_vent_dos=0.0,
        ressenti_min_c=None,
        confiance=CONFIANCE_INCONNUE,
    )


def test_meteo_none_rend_une_liste_vide():
    assert vent_par_position(None) == []


def test_une_position_par_echantillon_meme_liste_vide_de_fleches():
    """Contrairement à `fleches_vent`, rien n'est écarté : ni le seuil de
    sensibilité, ni l'absence de direction."""
    m = meteo(
        [
            echantillon(dist_m=0.0, vent_kmh=SEUIL_VENT_SENSIBLE_KMH - 5, vent_relatif=VENT_TRAVERS),
            echantillon(dist_m=1000.0, vent_kmh=None, vent_relatif=None),
        ]
    )
    positions = vent_par_position(m)
    assert len(positions) == 2


def test_sous_le_seuil_de_sensibilite_est_garde_contrairement_aux_flesches():
    """Le point qui distingue cette fonction de `fleches_vent` : un vent
    faible mais de face reste « face », pour ne pas laisser un trou muet sur
    le tracé colorié."""
    m = meteo([echantillon(vent_kmh=2.0, vent_relatif=VENT_FACE)])
    positions = vent_par_position(m)
    assert positions == [{"dist_m": 0, "relatif": VENT_FACE}]


def test_relatif_est_recopie_tel_quel_jamais_recalcule():
    m = meteo([echantillon(vent_relatif=VENT_DOS)])
    assert vent_par_position(m)[0]["relatif"] == VENT_DOS


def test_relatif_absent_reste_none_jamais_une_categorie_inventee():
    m = meteo([echantillon(vent_relatif=None)])
    assert vent_par_position(m)[0]["relatif"] is None


def test_dist_m_est_arrondie_et_dans_l_ordre_des_echantillons():
    m = meteo(
        [
            echantillon(dist_m=0.4, vent_relatif=VENT_FACE),
            echantillon(dist_m=5000.6, vent_relatif=VENT_DOS),
        ]
    )
    positions = vent_par_position(m)
    assert [p["dist_m"] for p in positions] == [0, 5001]


def test_forme_exacte_de_chaque_position():
    m = meteo([echantillon()])
    assert set(vent_par_position(m)[0]) == {"dist_m", "relatif"}
