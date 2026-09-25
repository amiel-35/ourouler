"""La question d'orientation au vent, ses deux gardes et l'azimut qu'elle impose.

Le client météo est un double : aucun appel réseau (règle absolue 3), et le
point de départ est fictif (0, 0), en pleine mer (règle absolue 1).
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from ourouler.config import Depart
from ourouler.meteo.openmeteo import PrevisionHeure, PrevisionPoint
from ourouler.noyau.erreurs import ErreurConnecteur, ErreurUtilisateur
from ourouler.seance.vent import SEUIL_VENT_SENSIBLE_KMH
from ourouler.sortie.orientation import (
    CHOIX,
    ORIENTATION_DEPART_DOS,
    ORIENTATION_RETOUR_DOS,
    ORIENTATION_TRAVERS,
    PEU_IMPORTE,
    valider,
)
from ourouler.sortie.vent_demande import (
    HORIZON_ORIENTATION_J,
    QuestionVent,
    interroger,
)

DEPART = Depart(nom="Fictif", latitude=0.0, longitude=0.0)
AUJOURDHUI = date(2026, 9, 16)
HEURE = datetime(2026, 9, 16, 9, 0, tzinfo=UTC)
MODELE = "modele_de_test"


class ClientDouble:
    """Rend une prévision imposée, ou lève. Compte ses appels."""

    def __init__(self, vent_kmh=None, depuis_deg=None, erreur=None, vide=False):
        self.vent_kmh, self.depuis_deg = vent_kmh, depuis_deg
        self.erreur, self.vide = erreur, vide
        self.appels = 0

    def previsions(self, points, *, modele, debut, horizon_h):
        self.appels += 1
        assert len(points) == 1, "un seul point : c'est le poste le moins cher"
        assert horizon_h == 1, "une seule heure"
        if self.erreur is not None:
            raise self.erreur
        if self.vide:
            return []
        heure = PrevisionHeure(
            t=debut,
            pluie_mm=0.0,
            vent_kmh=self.vent_kmh,
            rafales_kmh=None,
            vent_depuis_deg=self.depuis_deg,
            ressenti_c=None,
            temp_c=None,
        )
        return [PrevisionPoint(lat=points[0][0], lon=points[0][1], heures=[heure])]


def demander(jour: date, **kw):
    client = ClientDouble(**kw)
    question = interroger(
        client,
        DEPART,
        depart_heure=HEURE,
        jour=jour,
        modele=MODELE,
        aujourdhui=AUJOURDHUI,
    )
    return question, client


# --- le garde de l'horizon ----------------------------------------------------


def test_au_dela_de_trois_jours_la_question_ne_se_pose_pas():
    question, client = demander(
        date(2026, 9, 16 + HORIZON_ORIENTATION_J + 1), vent_kmh=30.0, depuis_deg=270.0
    )
    assert question.posee is False
    assert "jours" in question.motif
    assert client.appels == 0, "le refus tombe avant l'appel réseau"


def test_trois_jours_est_inclus():
    """88 % de directions dans le bon secteur, c'est encore utile."""
    question, _ = demander(
        date(2026, 9, 16 + HORIZON_ORIENTATION_J), vent_kmh=30.0, depuis_deg=270.0
    )
    assert question.posee is True


def test_une_seance_passee_ne_declenche_pas_le_garde():
    question, _ = demander(date(2026, 9, 10), vent_kmh=30.0, depuis_deg=270.0)
    assert question.posee is True


# --- le garde du vent ---------------------------------------------------------


def test_sous_le_seuil_de_vent_la_question_ne_se_pose_pas():
    question, _ = demander(AUJOURDHUI, vent_kmh=SEUIL_VENT_SENSIBLE_KMH - 0.1, depuis_deg=270.0)
    assert question.posee is False
    assert "km/h" in question.motif


def test_au_seuil_de_vent_la_question_se_pose():
    question, _ = demander(AUJOURDHUI, vent_kmh=SEUIL_VENT_SENSIBLE_KMH, depuis_deg=270.0)
    assert question.posee is True


# --- pannes -------------------------------------------------------------------


def test_une_panne_meteo_ne_fait_pas_perdre_la_sortie():
    question, _ = demander(AUJOURDHUI, erreur=ErreurConnecteur("Open-Meteo : HTTP 429"))
    assert question.posee is False
    assert "429" in question.motif
    assert question.azimuts_pour(ORIENTATION_RETOUR_DOS) == ()


def test_un_vent_absent_de_la_prevision_est_une_ignorance_pas_un_zero():
    question, _ = demander(AUJOURDHUI, vent_kmh=None, depuis_deg=None)
    assert question.posee is False
    assert "inconnu" in question.motif


def test_une_reponse_vide_ne_leve_pas():
    question, _ = demander(AUJOURDHUI, vide=True)
    assert question.posee is False


def test_une_direction_absente_empeche_la_question_meme_avec_du_vent():
    question, _ = demander(AUJOURDHUI, vent_kmh=30.0, depuis_deg=None)
    assert question.posee is False


# --- l'azimut de recherche ----------------------------------------------------


@pytest.mark.parametrize(
    ("reponse", "attendu"),
    [
        # Vent d'ouest (il vient de 270°). Pour rentrer avec, on part vers lui.
        (ORIENTATION_RETOUR_DOS, (270.0,)),
        (ORIENTATION_DEPART_DOS, (90.0,)),
        # Q44 : le travers ouvre les **deux** flancs, 0° et 180°.
        (ORIENTATION_TRAVERS, (0.0, 180.0)),
        (PEU_IMPORTE, ()),
    ],
)
def test_chaque_reponse_dirige_la_recherche(reponse, attendu):
    question, _ = demander(AUJOURDHUI, vent_kmh=25.0, depuis_deg=270.0)
    assert question.azimuts_pour(reponse) == attendu


def test_sans_question_posee_aucune_reponse_ne_dirige_la_recherche():
    """Sinon on chercherait dans une direction dictée par un vent qu'on ne sent pas."""
    question, _ = demander(AUJOURDHUI, vent_kmh=1.0, depuis_deg=270.0)
    assert question.azimuts_pour(ORIENTATION_RETOUR_DOS) == ()


# --- la validation de l'option ------------------------------------------------


def test_peu_importe_est_le_defaut():
    assert valider(None) == PEU_IMPORTE


@pytest.mark.parametrize("valeur", CHOIX)
def test_chaque_choix_est_accepte(valeur):
    assert valider(valeur) == valeur


def test_le_tiret_bas_est_accepte_comme_le_tiret():
    assert valider("retour_dos") == ORIENTATION_RETOUR_DOS


def test_une_reponse_inconnue_nomme_les_reponses_possibles():
    with pytest.raises(ErreurUtilisateur) as erreur:
        valider("plein-nord")
    assert all(choix in str(erreur.value) for choix in CHOIX)


# --- un nombre non fini est une ignorance, jamais une mesure -------------------
#
# Défaut relevé par les tests adversariaux du 17/09/2026 : la vitesse était
# filtrée par `math.isfinite`, la direction par le seul `is None`. Une
# direction `nan` passait les deux gardes, ressortait de `azimuts_pour`
# (`nan % 360` vaut `nan`) et partait chez BRouter en
# `roundTripStartDirection=nan`.


@pytest.mark.parametrize("valeur", [float("nan"), float("inf"), float("-inf")])
def test_une_direction_de_vent_non_finie_ne_pose_pas_la_question(valeur):
    question, _ = demander(AUJOURDHUI, vent_kmh=25.0, depuis_deg=valeur)
    assert question.posee is False
    assert question.vent_depuis_deg is None
    assert question.azimuts_pour(ORIENTATION_RETOUR_DOS) == ()


@pytest.mark.parametrize("valeur", [float("nan"), float("inf"), float("-inf")])
def test_une_vitesse_de_vent_non_finie_ne_pose_pas_la_question(valeur):
    question, _ = demander(AUJOURDHUI, vent_kmh=valeur, depuis_deg=270.0)
    assert question.posee is False
    assert question.vent_kmh is None


def test_aucun_azimut_non_fini_ne_sort_jamais_d_azimuts_pour():
    """`QuestionVent` est un objet public : la barrière tient même quand on le
    construit à la main, sans passer par `interroger`."""
    question = QuestionVent(vent_kmh=25.0, vent_depuis_deg=float("nan"), posee=True)
    for reponse in CHOIX:
        assert question.azimuts_pour(reponse) == ()


# --- Q44 : le travers ouvre deux azimuts opposés ------------------------------
#
# La trouvaille du mainteneur (17/09/2026) et la raison pour laquelle elle
# compte : deux directions séparées de 180° ne partagent que 0,4 % de leurs
# routes, contre 28 % à 30° d'écart. La préférence qui contraint le moins
# l'azimut est celle qui produit les propositions les moins ressemblantes.


@pytest.mark.parametrize("depuis_deg", [0.0, 45.0, 180.0, 270.0, 315.0])
def test_le_travers_ouvre_deux_azimuts_opposes(depuis_deg):
    question, _ = demander(AUJOURDHUI, vent_kmh=25.0, depuis_deg=depuis_deg)
    azimuts = question.azimuts_pour(ORIENTATION_TRAVERS)
    assert len(azimuts) == 2
    ecart = abs(azimuts[0] - azimuts[1]) % 360.0
    assert ecart == pytest.approx(180.0), f"{azimuts} ne sont pas opposés"


@pytest.mark.parametrize(
    "reponse", [ORIENTATION_RETOUR_DOS, ORIENTATION_DEPART_DOS]
)
def test_dos_au_depart_et_dos_au_retour_n_en_fixent_qu_un(reponse):
    """Une seule direction remplit la condition : on n'en invente pas une seconde."""
    question, _ = demander(AUJOURDHUI, vent_kmh=25.0, depuis_deg=270.0)
    assert len(question.azimuts_pour(reponse)) == 1


def test_dos_au_depart_et_dos_au_retour_sont_opposes_l_un_a_l_autre():
    """Le tableau de Q44 : « un azimut » et « un azimut, l'opposé »."""
    question, _ = demander(AUJOURDHUI, vent_kmh=25.0, depuis_deg=123.0)
    (retour,) = question.azimuts_pour(ORIENTATION_RETOUR_DOS)
    (depart,) = question.azimuts_pour(ORIENTATION_DEPART_DOS)
    assert abs(retour - depart) % 360.0 == pytest.approx(180.0)


def test_tout_azimut_rendu_reste_dans_le_tour_de_l_horizon():
    """`roundTripStartDirection` reçoit un azimut, pas 450°."""
    question, _ = demander(AUJOURDHUI, vent_kmh=25.0, depuis_deg=350.0)
    for reponse in CHOIX:
        for azimut in question.azimuts_pour(reponse):
            assert 0.0 <= azimut < 360.0
