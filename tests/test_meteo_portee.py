"""`meteo.portee` — jusqu'à quand on demande une météo, et ce qu'on dit sinon.

Q40 (a) et (b). Le module est pur : aucune horloge, aucun réseau, aucun
fichier. Ce qui se vérifie ici est la **frontière** (inclusive) et la
**phrase** — les deux choses qu'un écran lit.
"""

from __future__ import annotations

from datetime import date

from ourouler.config import HORIZON_JOURS_DEFAUT, depuis_dict
from ourouler.meteo import portee

AUJOURDHUI = date(2026, 9, 17)


def test_le_dernier_jour_couvert_est_aujourd_hui_plus_l_horizon():
    assert portee.dernier_jour_couvert(7, aujourdhui=AUJOURDHUI) == date(2026, 9, 24)


def test_la_frontiere_est_inclusive():
    """Le dernier jour couvert l'est **vraiment** : on demande sa météo.

    Une borne exclusive retirerait un jour entier de prévision sans que rien
    ne le dise — le genre d'écart d'un qui ne se voit qu'en production.
    """
    assert not portee.hors_de_portee(date(2026, 9, 24), 7, aujourdhui=AUJOURDHUI)
    assert portee.hors_de_portee(date(2026, 9, 25), 7, aujourdhui=AUJOURDHUI)


def test_les_jours_du_repli_restent_couverts():
    """Le piège de Q19, en test : J+2 et J+3 ne perdent pas leur météo.

    AROME s'arrête en cours de J+2 ; c'est le modèle de repli qui fixe
    l'horizon, et E15 sert justement une séance à J+4 **avec** sa météo.
    """
    for avance in (2, 3, 4):
        jour = date(2026, 9, 17 + avance)
        assert not portee.hors_de_portee(jour, HORIZON_JOURS_DEFAUT, aujourdhui=AUJOURDHUI), (
            f"J+{avance} doit rester couvert par l'horizon par défaut"
        )


def test_le_message_hors_de_portee_dit_le_dernier_jour_couvert():
    absente = portee.constater(date(2036, 9, 17), date(2026, 9, 24))
    assert absente.hors_de_portee
    assert "pas de météo pour le 17 septembre 2036" in absente.message
    assert "24 septembre 2026" in absente.message


def test_le_message_ne_dit_jamais_pourquoi():
    """Q40 (b) : la distinction « hors du domaine » / « hors de portée » disparaît.

    Open-Meteo rend le même bloc vide dans les deux cas ; le cœur refuse de
    trancher (règle absolue 5), et le produit n'a pas besoin qu'il tranche.
    """
    for jour in (date(2036, 9, 17), date(2026, 9, 20)):
        message = portee.constater(jour, date(2026, 9, 24)).message
        for mot in ("domaine", "portée temporelle", "modèle", "AROME", "Open-Meteo"):
            assert mot not in message, f"« {mot} » explique pourquoi, et ce n'est pas demandé"


def test_dans_l_horizon_la_phrase_ne_promet_pas_une_fin_de_previsions():
    """Une panne dans l'horizon n'est pas une fin de prévisions.

    Dire « les prévisions s'arrêtent au 24 septembre » pour une sortie du 20
    serait faux : elles le couvrent, elles n'ont simplement rien rendu.
    """
    absente = portee.constater(date(2026, 9, 20), date(2026, 9, 24))
    assert not absente.hors_de_portee
    assert absente.message == "pas de météo pour le 20 septembre 2026"
    assert "s'arrêtent" not in absente.message


def test_le_json_porte_les_deux_dates_et_la_phrase():
    charge = portee.constater(date(2036, 9, 17), date(2026, 9, 24)).json()
    assert charge["jour"] == "2036-09-17"
    assert charge["dernier_jour_couvert"] == "2026-09-24"
    assert charge["message"]


#: Le minimum qu'une `Config` exige, en valeurs inventées (règle absolue 1).
CONFIG_MINIMALE = {
    "depart": {"nom": "Point zéro", "latitude": 0.0, "longitude": 0.0},
    "cycliste": {"masse_kg": 70.0, "ftp_w": 200.0},
    "velos": [{"nom": "Route", "usage": "route"}],
}


def test_l_horizon_est_un_parametre_de_configuration():
    """La portée appartient au modèle, pas au projet (règle absolue 6, même esprit)."""
    assert depuis_dict(CONFIG_MINIMALE).meteo.horizon_jours == HORIZON_JOURS_DEFAUT
    avec = depuis_dict({**CONFIG_MINIMALE, "meteo": {"horizon_jours": 2}})
    assert avec.meteo.horizon_jours == 2
