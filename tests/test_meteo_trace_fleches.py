"""Tests de `boucle.meteo_trace.fleches_vent` et de la constante de seuil (lot L5.3).

Échantillons **fabriqués** autour de (0.0, 0.0), en pleine mer dans le golfe
de Guinée : aucune coordonnée réelle, aucun réseau (règles absolues 1 et 3).
`Echantillon` est construit directement, sans passer par `evaluer` ni par un
client météo.
"""

from __future__ import annotations

from datetime import UTC, datetime

import ourouler.rendu.carte as carte
import ourouler.seance.vent as seance_vent
from ourouler.boucle.meteo_trace import (
    SEUIL_VENT_SENSIBLE_KMH,
    Echantillon,
    MeteoTrace,
    fleches_vent,
)
from ourouler.meteo.rapport import CONFIANCE_INCONNUE, VENT_FACE

T0 = datetime(2026, 9, 17, 8, 0, tzinfo=UTC)


def echantillon(
    *,
    dist_m: float = 0.0,
    vent_kmh: float | None = 20.0,
    vent_depuis_deg: float | None = 90.0,
    rafales_kmh: float | None = None,
    vent_relatif: str | None = VENT_FACE,
) -> Echantillon:
    """Un échantillon au golfe de Guinée, sans rien qui ressemble à une vraie sortie."""
    return Echantillon(
        dist_m=dist_m,
        t=T0,
        lat=0.0,
        lon=dist_m / 111_000.0,  # quelques centièmes de degré tout au plus
        cap_deg=0.0,
        pluie_mm=0.0,
        vent_kmh=vent_kmh,
        vent_relatif=vent_relatif,
        ressenti_c=18.0,
        vent_depuis_deg=vent_depuis_deg,
        rafales_kmh=rafales_kmh,
    )


def meteo(echantillons: list[Echantillon]) -> MeteoTrace:
    """Une `MeteoTrace` minimale : seuls les échantillons comptent pour `fleches_vent`."""
    return MeteoTrace(
        echantillons=echantillons,
        pluie_cumulee_mm=0.0,
        minutes_pluie=0.0,
        part_vent_face=0.0,
        part_vent_dos=0.0,
        ressenti_min_c=None,
        confiance=CONFIANCE_INCONNUE,
    )


# --- coordonnées, garde-fou adversarial ---------------------------------------


def test_invariant_aucune_coordonnee_reelle():
    """Garde-fou : les échantillons de ce fichier restent au golfe de Guinée."""
    e = echantillon()
    assert abs(e.lat) < 1.0
    assert abs(e.lon) < 1.0


# --- None en entrée -------------------------------------------------------------


def test_meteo_none_rend_une_liste_vide():
    assert fleches_vent(None) == []


# --- la borne du seuil, dans les deux sens --------------------------------------


def test_juste_sous_le_seuil_est_ecarte():
    m = meteo([echantillon(vent_kmh=SEUIL_VENT_SENSIBLE_KMH - 0.1)])
    assert fleches_vent(m) == []


def test_exactement_au_seuil_est_garde():
    m = meteo([echantillon(vent_kmh=SEUIL_VENT_SENSIBLE_KMH)])
    fleches = fleches_vent(m)
    assert len(fleches) == 1
    assert fleches[0]["vent_kmh"] == round(SEUIL_VENT_SENSIBLE_KMH)


# --- vent ou direction manquants ------------------------------------------------


def test_vent_inconnu_est_ecarte():
    m = meteo([echantillon(vent_kmh=None)])
    assert fleches_vent(m) == []


def test_direction_inconnue_est_ecartee_meme_avec_un_vent_fort():
    """Le point qui compte : sans direction, on n'invente pas 0°, jamais de flèche nord."""
    m = meteo([echantillon(vent_kmh=80.0, vent_depuis_deg=None)])
    assert fleches_vent(m) == []


# --- rafale : None reste None, jamais 0 -----------------------------------------


def test_rafale_absente_reste_none_jamais_zero():
    m = meteo([echantillon(rafales_kmh=None)])
    fleches = fleches_vent(m)
    assert len(fleches) == 1
    assert fleches[0]["rafale_kmh"] is None


def test_rafale_presente_est_arrondie():
    m = meteo([echantillon(rafales_kmh=32.6)])
    fleches = fleches_vent(m)
    assert fleches[0]["rafale_kmh"] == 33


# --- relatif recopié, jamais recalculé ------------------------------------------


def test_relatif_est_recopie_tel_quel():
    m = meteo([echantillon(vent_relatif="travers")])
    fleches = fleches_vent(m)
    assert fleches[0]["relatif"] == "travers"


def test_relatif_absent_reste_none():
    m = meteo([echantillon(vent_relatif=None)])
    fleches = fleches_vent(m)
    assert fleches[0]["relatif"] is None


# --- l'invariant qui compte le plus : une seule règle, deux points d'entrée -----


def test_sortie_carte_et_boucle_meteo_trace_sont_la_meme_fonction():
    """`sortie.carte._vent_fleches` est l'alias historique de `fleches_vent` : même objet."""
    assert carte._vent_fleches is fleches_vent


def test_sortie_carte_et_boucle_meteo_trace_rendent_le_meme_resultat():
    """Même en passant par les deux noms, la sortie ne diverge jamais."""
    m = meteo(
        [
            echantillon(dist_m=0.0, vent_kmh=20.0, vent_depuis_deg=90.0, rafales_kmh=35.0),
            echantillon(dist_m=5000.0, vent_kmh=5.0, vent_depuis_deg=180.0),  # sous le seuil
            echantillon(dist_m=10000.0, vent_kmh=40.0, vent_depuis_deg=None),  # direction absente
        ]
    )
    assert carte._vent_fleches(m) == fleches_vent(m)


# --- une seule constante, pas deux qui se ressemblent ---------------------------


def test_une_seule_constante_de_seuil_partagee():
    assert seance_vent.SEUIL_VENT_SENSIBLE_KMH is SEUIL_VENT_SENSIBLE_KMH
