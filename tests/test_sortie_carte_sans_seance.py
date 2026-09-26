"""Tests de la page « rien de prévu » (contrat de l'hébergé minimal, point 4) :
`carte.construire_page_sans_seance`.

Unitaires, sans réseau ni fichier — une page HTML autonome, aucune coordonnée
ni séance en jeu : rien qui ressemble à une donnée personnelle.
"""

from __future__ import annotations

from datetime import date, datetime

from ourouler.rendu import carte

JOUR = date(2026, 9, 16)


def test_dit_qu_il_n_y_a_rien_de_prevu():
    page = carte.construire_page_sans_seance(JOUR)
    assert "Rien de prévu" in page
    assert "Aucune séance vélo planifiée" in page


def test_dit_le_jour():
    page = carte.construire_page_sans_seance(JOUR)
    assert JOUR.isoformat() in page


def test_dit_quand_elle_a_ete_generee():
    """Contrat point 5 : une page qui ne dit pas de quand elle date, c'est pire que rien."""
    maintenant = datetime(2026, 9, 16, 6, 17)
    page = carte.construire_page_sans_seance(JOUR, maintenant=maintenant)
    assert "16/09/2026" in page
    assert "06:17" in page


def test_horloge_par_defaut_si_maintenant_omis():
    """`maintenant` est injectable, mais un appel sans lui ne doit pas lever."""
    page = carte.construire_page_sans_seance(JOUR)
    assert "généré" in page.lower()


def test_page_html_autonome_sans_reseau():
    """Ni Leaflet, ni tuile OSM, ni appel externe : rien à dessiner un jour sans boucle."""
    page = carte.construire_page_sans_seance(JOUR)
    assert "leaflet" not in page.lower()
    assert "openstreetmap.org" not in page.lower()
    assert page.startswith("<!doctype html>")


def test_aucune_injection_dans_le_titre():
    """`jour` est une `date` : `isoformat()` ne peut porter aucun caractère à échapper,
    mais un test de non-régression coûte peu si ce contrat change un jour."""
    page = carte.construire_page_sans_seance(JOUR)
    assert "<script>" not in page
