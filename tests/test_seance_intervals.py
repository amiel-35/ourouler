"""Tests de `seance.intervals` (lot L4.1) : `workout_doc` → `Seance`.

Aucun accès réseau : `ClientIntervals` reçoit un `httpx.MockTransport` qui
rend des réponses **fabriquées**. Les `workout_doc` viennent de
`tests/fixtures/workouts.py` — structure observée, valeurs inventées.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import date
from pathlib import Path

import httpx
import pytest

from ourouler.connecteurs.intervals import ClientIntervals
from ourouler.seance.intervals import (
    PROFONDEUR_MAX,
    REPS_MAX,
    SEUIL_FRACTION_FTP,
    depuis_workout_doc,
    seance_du_jour,
)
from ourouler.seance.modele import ZONES_PUISSANCE_DEFAUT

FIXTURES = Path(__file__).resolve().parent / "fixtures"
JOUR = date(2026, 9, 8)

# Identifiant d'athlète et clé entièrement inventés.
ATHLETE = "i000000"
CLE = "cle-de-test-inventee"


def _workouts():
    """Charge `tests/fixtures/workouts.py` par chemin (hors paquet)."""
    if "workouts" in sys.modules:
        return sys.modules["workouts"]
    chemin = FIXTURES / "workouts.py"
    spec = importlib.util.spec_from_file_location("workouts", chemin)
    module = importlib.util.module_from_spec(spec)
    sys.modules["workouts"] = module
    spec.loader.exec_module(module)
    return module


W = _workouts()
FTP = W.FTP_TEST  # 200 W, inventée


def lire(doc: dict, *, ftp=FTP, nom="Séance fabriquée", zones=ZONES_PUISSANCE_DEFAUT):
    return depuis_workout_doc(doc, nom=nom, jour=JOUR, ftp_w=ftp, zones_puissance=zones)


def client_bouchon(evenements: list[dict], *, code: int = 200) -> ClientIntervals:
    """Un client dont `evenements` rend la liste donnée, sans toucher au réseau."""

    def gestionnaire(requete: httpx.Request) -> httpx.Response:
        assert "/events" in requete.url.path
        return httpx.Response(code, json=evenements)

    return ClientIntervals(
        ATHLETE, CLE, http=httpx.Client(transport=httpx.MockTransport(gestionnaire))
    )


# --- la forme de référence, dans les trois unités ------------------------------


@pytest.mark.parametrize(
    "fabrique", ["groupes_hr_zone", "groupes_pourcent_ftp", "groupes_watts"]
)
def test_la_forme_de_reference_donne_dix_etapes(fabrique):
    """1 échauffement + 4 × (bloc + récup) + 1 calme = 10 étapes développées."""
    seance = lire(getattr(W, fabrique)())
    assert len(seance.etapes) == 10
    types = [e.type for e in seance.etapes]
    assert types[0] == "echauffement"
    assert types[1:9] == ["bloc", "recuperation"] * 4
    assert types[9] == "calme"


@pytest.mark.parametrize(
    "fabrique", ["groupes_hr_zone", "groupes_pourcent_ftp", "groupes_watts"]
)
def test_quatre_blocs_et_leurs_indices(fabrique):
    seance = lire(getattr(W, fabrique)())
    assert [i for i, _ in seance.blocs()] == [1, 3, 5, 7]


@pytest.mark.parametrize(
    "fabrique", ["groupes_hr_zone", "groupes_pourcent_ftp", "groupes_watts"]
)
def test_seules_les_deux_extremites_sont_elastiques(fabrique):
    seance = lire(getattr(W, fabrique)())
    assert [i for i, e in enumerate(seance.etapes) if e.elastique] == [0, 9]


@pytest.mark.parametrize(
    "fabrique", ["groupes_hr_zone", "groupes_pourcent_ftp", "groupes_watts"]
)
def test_la_duree_est_la_somme_des_etapes(fabrique):
    seance = lire(getattr(W, fabrique)())
    assert seance.duree_s == sum(e.duree_s for e in seance.etapes)
    assert seance.duree_s == seance.meta["duree_doc_s"]
    assert "ecart_duree_doc_s" not in seance.meta


def test_la_recuperation_apres_chaque_bloc_dure_quatre_minutes():
    seance = lire(W.groupes_hr_zone())
    for indice, _ in seance.blocs():
        recup = seance.recuperation_apres(indice)
        assert recup is not None and recup.duree_s == 240.0


# --- traduction des consignes -------------------------------------------------


def test_watts_sont_repris_tels_quels():
    seance = lire(W.groupes_watts())
    bloc = seance.etapes[1]
    assert (bloc.puissance_min_w, bloc.puissance_max_w) == (240.0, 260.0)
    assert bloc.puissance_cible_w == 250.0
    assert seance.meta["puissance_approximee"] is False


def test_pourcent_ftp_est_multiplie_par_la_ftp():
    seance = lire(W.groupes_pourcent_ftp())
    bloc = seance.etapes[1]  # 100 % de 200 W
    assert bloc.puissance_min_w == bloc.puissance_max_w == 200.0
    recup = seance.etapes[2]  # 50 %
    assert recup.puissance_cible_w == 100.0
    assert seance.meta["puissance_approximee"] is False


def test_une_rampe_devient_une_fourchette_ordonnee():
    seance = lire(W.groupes_pourcent_ftp())
    echauffement = seance.etapes[0]  # 55 % → 70 %
    assert (echauffement.puissance_min_w, echauffement.puissance_max_w) == (110.0, 140.0)
    calme = seance.etapes[9]  # 60 % → 40 %, rampe descendante
    assert (calme.puissance_min_w, calme.puissance_max_w) == (80.0, 120.0)


def test_hr_zone_est_approximee_par_la_zone_de_puissance_de_meme_numero():
    seance = lire(W.groupes_hr_zone())
    bloc = seance.etapes[1]  # Z4 = 91-105 % de 200 W
    assert (bloc.puissance_min_w, bloc.puissance_max_w) == (182.0, 210.0)
    assert seance.meta["puissance_approximee"] is True
    assert "fréquence cardiaque" in seance.meta["approximation"]


def test_l_approximation_se_lit_dans_le_libelle():
    seance = lire(W.groupes_hr_zone())
    assert "Z4 (FC)" in seance.etapes[1].libelle


def test_power_zone_n_est_pas_une_approximation():
    doc = {"steps": [{"power": {"units": "power_zone", "value": 2}, "duration": 3600}]}
    seance = lire(doc)
    etape = seance.etapes[0]
    assert (etape.puissance_min_w, etape.puissance_max_w) == (0.56 * FTP, 0.75 * FTP)
    assert seance.meta["puissance_approximee"] is False
    assert etape.libelle == "Z2"


def test_power_zone_en_intervalle_de_zones():
    doc = {"steps": [{"power": {"units": "power_zone", "start": 2, "end": 4}, "duration": 600}]}
    etape = lire(doc).etapes[0]
    assert (etape.puissance_min_w, etape.puissance_max_w) == (0.56 * FTP, 1.05 * FTP)
    assert etape.libelle == "Z2-Z4"


def test_une_zone_hors_table_est_ramenee_dans_les_bornes():
    doc = {
        "steps": [
            {"power": {"units": "power_zone", "value": 99}, "duration": 60},
            {"power": {"units": "power_zone", "value": 0}, "duration": 60},
        ]
    }
    etapes = lire(doc).etapes
    assert etapes[0].libelle == "Z7"
    assert etapes[1].libelle == "Z1"


def test_zones_personnalisees_sont_respectees():
    zones = ((0.0, 0.50), (0.50, 0.80), (0.80, 2.0))
    doc = {"steps": [{"power": {"units": "power_zone", "value": 2}, "duration": 60}]}
    etape = lire(doc, zones=zones).etapes[0]
    assert (etape.puissance_min_w, etape.puissance_max_w) == (100.0, 160.0)


def test_une_table_de_zones_invalide_retombe_sur_celle_par_defaut():
    doc = {"steps": [{"power": {"units": "power_zone", "value": 2}, "duration": 60}]}
    for mauvaise in ([], "Z2", [(1,)], [(None, 2)], [(-1, 2)]):
        etape = lire(doc, zones=mauvaise).etapes[0]
        assert (etape.puissance_min_w, etape.puissance_max_w) == (0.56 * FTP, 0.75 * FTP)


# --- cas du §5 du contrat -----------------------------------------------------


def test_document_vide():
    seance = lire({})
    assert seance.etapes == []
    assert seance.duree_s == 0.0
    assert seance.meta["vide"] is True


def test_steps_absent_ou_de_mauvais_type():
    for doc in ({"steps": None}, {"steps": "4x8"}, {"steps": 42}, {"autre": 1}):
        seance = lire(doc)
        assert seance.etapes == []
        assert seance.meta["vide"] is True


def test_un_document_qui_n_est_pas_un_dictionnaire():
    seance = lire([])  # type: ignore[arg-type]
    assert seance.etapes == []


def test_elements_non_dictionnaires_ignores_et_comptes():
    doc = {"steps": ["texte", None, 3, {"power": {"units": "watts", "value": 200}, "duration": 60}]}
    seance = lire(doc)
    assert len(seance.etapes) == 1
    assert seance.meta["elements_illisibles"] == 3


def test_reps_a_zero_supprime_le_groupe_et_le_compte():
    doc = {
        "steps": [
            {
                "reps": 0,
                "text": "4x",
                "steps": [{"duration": 480, "power": {"units": "watts", "value": 250}}],
            },
            {"duration": 300, "power": {"units": "watts", "value": 120}},
        ]
    }
    seance = lire(doc)
    assert len(seance.etapes) == 1
    assert seance.meta["groupes_ignores"] == 1


def test_reps_negatif_supprime_le_groupe():
    doc = {"steps": [{"reps": -3, "steps": [{"duration": 60, "power": {"units": "watts", "value": 1}}]}]}
    seance = lire(doc)
    assert seance.etapes == []
    assert seance.meta["groupes_ignores"] == 1


def test_reps_absent_vaut_une_repetition():
    doc = {"steps": [{"steps": [{"duration": 60, "power": {"units": "watts", "value": 100}}]}]}
    assert len(lire(doc).etapes) == 1


def test_reps_illisible_vaut_une_repetition():
    sous = [{"duration": 60, "power": {"units": "watts", "value": 1}}]
    doc = {"steps": [{"reps": "quatre", "steps": sous}]}
    assert len(lire(doc).etapes) == 1


def test_reps_demesure_est_borne():
    doc = {"steps": [{"reps": 10_000, "steps": [{"duration": 1, "power": {"units": "watts", "value": 1}}]}]}
    assert len(lire(doc).etapes) == REPS_MAX


def test_durees_nulles_ou_absentes_ecartees_et_comptees():
    doc = {
        "steps": [
            {"duration": 0, "power": {"units": "watts", "value": 200}},
            {"power": {"units": "watts", "value": 200}},
            {"duration": -60, "power": {"units": "watts", "value": 200}},
            {"duration": 600, "power": {"units": "watts", "value": 200}},
        ]
    }
    seance = lire(doc)
    assert len(seance.etapes) == 1
    assert seance.meta["etapes_nulles"] == 3


def test_ni_power_ni_hr_donne_une_etape_sans_puissance():
    doc = {"steps": [{"duration": 1200, "freeride": True}]}
    seance = lire(doc)
    etape = seance.etapes[0]
    assert etape.puissance_cible_w is None
    assert etape.libelle == "libre"
    assert seance.meta["etapes_sans_puissance"] == 1


def test_units_inconnue_ne_donne_aucune_puissance_et_se_dit():
    doc = {"steps": [{"duration": 600, "power": {"units": "furlongs", "value": 3}}]}
    seance = lire(doc)
    assert seance.etapes[0].puissance_cible_w is None
    assert seance.meta["unites_inconnues"] == ["furlongs"]
    assert seance.meta["etapes_sans_puissance"] == 1


def test_units_absente_est_signalee():
    doc = {"steps": [{"duration": 600, "power": {"value": 3}}]}
    assert lire(doc).meta["unites_inconnues"] == ["(absente)"]


# --- les deux écritures d'une consigne `%ftp` ---------------------------------


def _une_consigne(valeur, **bornes):
    consigne = {"units": "%ftp"}
    consigne.update({"value": valeur} if not bornes else bornes)
    return {"steps": [{"duration": 600, "power": consigne}]}


@pytest.mark.parametrize(
    ("valeur", "attendu"),
    [
        (80, 0.80 * FTP),  # l'entier des séances du mainteneur : 80 % de FTP
        (105, 1.05 * FTP),
        (0.80, 0.80 * FTP),  # la fraction : la même consigne, l'autre écriture
        (1.05, 1.05 * FTP),
        (3.0, 3.0 * FTP),  # seuil inclus : 3 × FTP, un sprint
        (3.5, 0.035 * FTP),  # juste au-dessus : 3,5 % de FTP
    ],
)
def test_les_deux_ecritures_de_pourcent_ftp_sont_acceptees(valeur, attendu):
    """`80` et `0.80` désignent la même chose ; `SEUIL_FRACTION_FTP` tranche."""
    etape = lire(_une_consigne(valeur)).etapes[0]
    assert etape.puissance_cible_w == pytest.approx(attendu)


def test_une_rampe_est_lue_d_apres_sa_borne_haute():
    """`{start: 0, end: 80}` est un pourcentage bien que son début vaille 0."""
    etape = lire(_une_consigne(None, start=0, end=80)).etapes[0]
    assert (etape.puissance_min_w, etape.puissance_max_w) == (0.0, 0.80 * FTP)
    fraction = lire(_une_consigne(None, start=0.5, end=0.75)).etapes[0]
    assert (fraction.puissance_min_w, fraction.puissance_max_w) == (0.50 * FTP, 0.75 * FTP)


@pytest.mark.parametrize(
    ("valeur", "lecture"), [(80, "pourcentage"), (0.80, "fraction")]
)
def test_l_interpretation_retenue_est_ecrite_dans_meta(valeur, lecture):
    meta = lire(_une_consigne(valeur)).meta
    assert meta["convention_pourcent_ftp"]["lecture"] == lecture
    assert meta["convention_pourcent_ftp"]["seuil"] == SEUIL_FRACTION_FTP


def test_une_seance_qui_melange_les_deux_ecritures_le_dit():
    doc = {
        "steps": [
            {"duration": 600, "power": {"units": "%ftp", "value": 60}},
            {"duration": 600, "power": {"units": "%ftp", "value": 1.05}},
        ]
    }
    seance = lire(doc)
    assert [e.puissance_cible_w for e in seance.etapes] == [0.60 * FTP, 1.05 * FTP]
    convention = seance.meta["convention_pourcent_ftp"]
    assert convention["lecture"] == "mixte"
    assert (convention["etapes_en_pourcentage"], convention["etapes_en_fraction"]) == (1, 1)


def test_sans_consigne_en_pourcent_ftp_la_convention_ne_figure_pas_dans_meta():
    seance = lire(W.groupes_watts())
    assert "convention_pourcent_ftp" not in seance.meta


def test_pourcent_ftp_sans_ftp_ne_devine_pas_de_watts():
    doc = W.groupes_pourcent_ftp()
    seance = lire(doc, ftp=None)
    assert all(e.puissance_cible_w is None for e in seance.etapes)
    assert seance.meta["etapes_sans_ftp"] == len(seance.etapes)
    assert seance.meta["ftp_w"] is None
    # La consigne d'origine reste lisible, même sans FTP pour la traduire.
    assert "100 % FTP" in seance.etapes[1].libelle


@pytest.mark.parametrize("ftp", [0, -10, "beaucoup", float("nan"), True, None])
def test_une_ftp_inutilisable_vaut_une_ftp_absente(ftp):
    seance = lire({"steps": [{"duration": 60, "power": {"units": "%ftp", "value": 100}}]}, ftp=ftp)
    assert seance.etapes[0].puissance_cible_w is None


def test_hr_zone_sans_ftp_garde_le_nom_de_zone():
    seance = lire(W.groupes_hr_zone(), ftp=None)
    assert seance.etapes[1].puissance_cible_w is None
    assert "Z4 (FC)" in seance.etapes[1].libelle


def test_groupes_imbriques_sur_trois_niveaux():
    doc = {
        "steps": [
            {
                "reps": 2,
                "text": "A",
                "steps": [
                    {
                        "reps": 3,
                        "text": "B",
                        "steps": [
                            {
                                "reps": 2,
                                "text": "C",
                                "steps": [
                                    {"duration": 60, "power": {"units": "watts", "value": 250}}
                                ],
                            }
                        ],
                    }
                ],
            }
        ]
    }
    seance = lire(doc)
    assert len(seance.etapes) == 2 * 3 * 2
    assert seance.duree_s == 12 * 60
    assert "A (1/2) · B (1/3) · C (1/2)" in seance.etapes[0].libelle


def test_imbrication_demesuree_est_coupee_et_signalee():
    doc = {"duration": 60, "power": {"units": "watts", "value": 200}}
    for _ in range(PROFONDEUR_MAX + 3):
        doc = {"reps": 1, "steps": [doc]}
    seance = lire({"steps": [doc]})
    assert seance.etapes == []
    assert seance.meta["groupes_trop_profonds"] >= 1


def test_un_groupe_vide_ne_produit_rien():
    assert lire({"steps": [{"reps": 4, "steps": []}]}).etapes == []


def test_l_ecart_avec_la_duree_annoncee_est_signale():
    doc = W.groupes_watts()
    doc["duration"] = 9999
    seance = lire(doc)
    assert seance.meta["ecart_duree_doc_s"] == pytest.approx(9999 - seance.duree_s)


# --- typage des étapes --------------------------------------------------------


@pytest.mark.parametrize(
    ("step", "attendu"),
    [
        ({"warmup": True}, "echauffement"),
        ({"intensity": "warmup"}, "echauffement"),
        ({"cooldown": True}, "calme"),
        ({"intensity": "cooldown"}, "calme"),
        ({"intensity": "recovery"}, "recuperation"),
        ({"intensity": "rest"}, "recuperation"),
        ({"intensity": "RECOVERY"}, "recuperation"),
        ({}, "bloc"),
        ({"intensity": "active"}, "bloc"),
        ({"warmup": False}, "bloc"),
        ({"warmup": "oui"}, "bloc"),
    ],
)
def test_type_d_une_etape(step, attendu):
    """L'étape testée est encadrée de deux blocs : les extrémités ont leurs propres
    règles (une récupération en bout de séance est un échauffement ou un calme)."""
    bloc = {"duration": 600, "power": {"units": "watts", "value": 200}}
    milieu = {"duration": 60, "power": {"units": "watts", "value": 200}, **step}
    doc = {"steps": [dict(bloc), milieu, dict(bloc)]}
    assert lire(doc).etapes[1].type == attendu


def test_warmup_l_emporte_sur_recovery():
    doc = {"steps": [{"duration": 60, "warmup": True, "intensity": "recovery"}]}
    assert lire(doc).etapes[0].type == "echauffement"


def test_une_recuperation_en_fin_de_seance_devient_un_retour_au_calme():
    """Les séances de coach nomment « Récupération » jusqu'au retour à la maison."""
    doc = {
        "steps": [
            {"duration": 600, "power": {"units": "watts", "value": 220}},
            {"duration": 300, "intensity": "recovery", "power": {"units": "watts", "value": 120}},
            {"duration": 1200, "intensity": "recovery", "power": {"units": "watts", "value": 120}},
        ]
    }
    seance = lire(doc)
    assert [e.type for e in seance.etapes] == ["bloc", "recuperation", "calme"]
    assert seance.etapes[-1].elastique is True
    assert seance.meta["typage_source"] == ["defaut", "marqueur", "position"]


def test_une_recuperation_en_tete_de_seance_devient_un_echauffement():
    doc = {
        "steps": [
            {"duration": 600, "intensity": "recovery", "power": {"units": "watts", "value": 120}},
            {"duration": 600, "power": {"units": "watts", "value": 220}},
        ]
    }
    seance = lire(doc)
    assert seance.etapes[0].type == "echauffement" and seance.etapes[0].elastique is True


def test_une_recuperation_au_milieu_garde_son_type():
    doc = {
        "steps": [
            {"duration": 600, "power": {"units": "watts", "value": 220}},
            {"duration": 300, "intensity": "recovery", "power": {"units": "watts", "value": 120}},
            {"duration": 600, "power": {"units": "watts", "value": 220}},
        ]
    }
    assert lire(doc).etapes[1].type == "recuperation"


def test_un_echauffement_qui_n_est_pas_en_tete_n_est_pas_elastique():
    doc = {
        "steps": [
            {"duration": 600, "power": {"units": "watts", "value": 200}},
            {"duration": 600, "warmup": True, "power": {"units": "watts", "value": 120}},
        ]
    }
    seance = lire(doc)
    assert [e.elastique for e in seance.etapes] == [False, False]


def test_une_seance_entierement_marquee_echauffement():
    """Forme réelle d'une sortie d'endurance : élastique, et aucun bloc."""
    seance = lire(W.sortie_libre())
    assert len(seance.etapes) == 1
    assert seance.etapes[0].type == "echauffement"
    assert seance.etapes[0].elastique is True
    assert seance.blocs() == []


def test_etapes_plates_et_groupes_melanges():
    seance = lire(W.plat_et_groupes())
    # 1 libre + 4 × (bloc + récup) + 1 bloc + 1 libre
    assert len(seance.etapes) == 11
    assert seance.meta["etapes_sans_puissance"] == 2
    assert seance.meta["description"] == "Seance fabriquee pour les tests."


# --- seance_du_jour -----------------------------------------------------------


def test_seance_du_jour_retient_le_velo_et_nomme_les_autres():
    evenements = [
        W.evenement(W.groupes_hr_zone(), nom="Vélo fabriqué", identifiant=1),
        W.evenement(W.sortie_libre(), nom="Nage fabriquée", sport="Swim", identifiant=2),
    ]
    seance = seance_du_jour(client_bouchon(evenements), JOUR, ftp_w=FTP)
    assert seance is not None
    assert seance.nom == "Vélo fabriqué"
    assert seance.meta["source"] == "intervals"
    assert seance.meta["evenement_id"] == 1
    assert seance.meta["sport"] == "Ride"
    assert "autres_seances" not in seance.meta


def test_deux_seances_velo_le_meme_jour():
    evenements = [
        W.evenement(W.groupes_watts(), nom="Vélo A", identifiant=1),
        W.evenement(W.groupes_watts(), nom="Vélo B", identifiant=2),
    ]
    seance = seance_du_jour(client_bouchon(evenements), JOUR, ftp_w=FTP)
    assert seance is not None and seance.nom == "Vélo A"
    assert seance.meta["autres_seances"] == ["Vélo B"]


def test_aucune_seance_ce_jour_la():
    assert seance_du_jour(client_bouchon([]), JOUR, ftp_w=FTP) is None


def test_seule_une_seance_de_nage_ce_jour_la():
    evenements = [W.evenement(W.sortie_libre(), nom="Nage", sport="Swim")]
    assert seance_du_jour(client_bouchon(evenements), JOUR, ftp_w=FTP) is None


def test_une_note_de_calendrier_n_est_pas_une_seance():
    note = {"id": 7, "name": "Repos", "type": "Ride", "category": "NOTE", "workout_doc": {}}
    assert seance_du_jour(client_bouchon([note]), JOUR, ftp_w=FTP) is None


def test_un_evenement_sans_workout_doc_est_ignore():
    evenements = [
        {"id": 1, "name": "Course", "type": "Ride", "category": "WORKOUT"},
        {"id": 2, "name": "Doc nul", "type": "Ride", "category": "WORKOUT", "workout_doc": None},
    ]
    assert seance_du_jour(client_bouchon(evenements), JOUR, ftp_w=FTP) is None


def test_un_evenement_sans_categorie_compte_comme_une_seance():
    evenement = W.evenement(W.groupes_watts(), nom="Sans catégorie")
    del evenement["category"]
    assert seance_du_jour(client_bouchon([evenement]), JOUR, ftp_w=FTP) is not None


def test_un_evenement_sans_nom_reste_lisible():
    evenement = W.evenement(W.groupes_watts(), nom="")
    seance = seance_du_jour(client_bouchon([evenement]), JOUR, ftp_w=FTP)
    assert seance is not None and seance.nom == "séance sans nom"


def test_la_reponse_du_service_est_bien_appelee_sur_le_bon_jour():
    """Le connecteur borne sa fenêtre au jour demandé : un seul appel, deux bornes."""
    urls: list[httpx.URL] = []

    def gestionnaire(requete: httpx.Request) -> httpx.Response:
        urls.append(requete.url)
        return httpx.Response(200, json=[])

    client = ClientIntervals(
        ATHLETE, CLE, http=httpx.Client(transport=httpx.MockTransport(gestionnaire))
    )
    assert seance_du_jour(client, JOUR, ftp_w=FTP) is None
    assert len(urls) == 1
    assert urls[0].params["oldest"] == urls[0].params["newest"] == "2026-09-08"


def test_une_seance_est_serialisable_en_json():
    """`meta` doit rester un dictionnaire de types simples (rendu `--json`)."""
    seance = lire(W.groupes_hr_zone())
    assert json.loads(json.dumps(seance.meta))["puissance_approximee"] is True


# --- zones de FC basses : la puissance d'endurance mesurée (Q11) ---------------


def test_le_cas_nominal_pourcent_ftp_n_est_pas_une_approximation():
    """Huit séances sur dix sont en `%ftp` : rien à approximer, rien à avertir."""
    seance = lire(W.groupes_pourcent_ftp())
    assert seance.meta["puissance_approximee"] is False
    assert "approximation" not in seance.meta
    assert "etapes_fc_basses" not in seance.meta
    assert "etapes_fc_hautes" not in seance.meta


@pytest.mark.parametrize("zone", [1, 2])
def test_une_zone_de_fc_basse_vise_la_puissance_d_endurance(zone):
    doc = {"steps": [{"hr": {"units": "hr_zone", "value": zone}, "duration": 3600}]}
    etape = lire(doc).etapes[0]
    # 60 % de 200 W, une valeur et non une fourchette : le milieu de Z1
    # (0-55 % de FTP) vaudrait 55 W, soit du pédalage à vide.
    assert etape.puissance_min_w == etape.puissance_max_w == 120.0
    assert etape.puissance_cible_w == 120.0


@pytest.mark.parametrize("zone", [3, 4, 5])
def test_une_zone_de_fc_haute_garde_la_table_des_zones(zone):
    doc = {"steps": [{"hr": {"units": "hr_zone", "value": zone}, "duration": 480}]}
    etape = lire(doc).etapes[0]
    bas, haut = ZONES_PUISSANCE_DEFAUT[zone - 1]
    assert (etape.puissance_min_w, etape.puissance_max_w) == (bas * FTP, haut * FTP)


def test_la_zone_quatre_de_fc_reste_plausible_pour_du_seuil():
    doc = {"steps": [{"hr": {"units": "hr_zone", "value": 4}, "duration": 480}]}
    etape = lire(doc, ftp=258.0).etapes[0]
    assert (round(etape.puissance_min_w), round(etape.puissance_max_w)) == (235, 271)


def test_un_intervalle_de_zones_de_fc_qui_deborde_vers_le_haut_reste_haut():
    doc = {"steps": [{"hr": {"units": "hr_zone", "start": 1, "end": 4}, "duration": 600}]}
    etape = lire(doc).etapes[0]
    assert etape.puissance_max_w == 1.05 * FTP


def test_les_deux_familles_sont_comptees_dans_meta():
    seance = lire(W.groupes_hr_zone())
    # échauffement Z2 + 4 récups Z1 + 1 calme Z1 = 6 basses ; 4 blocs Z4 = 4 hautes.
    assert seance.meta["etapes_fc_basses"] == 6
    assert seance.meta["etapes_fc_hautes"] == 4
    assert "zones basses" in seance.meta["approximation"]


def test_la_part_de_ftp_visee_est_reglable():
    doc = {"steps": [{"hr": {"units": "hr_zone", "value": 1}, "duration": 60}]}
    seance = depuis_workout_doc(
        doc, nom="EF", jour=JOUR, ftp_w=FTP, puissance_endurance_pct=0.70
    )
    assert seance.etapes[0].puissance_cible_w == 140.0
    assert seance.meta["puissance_endurance_pct"] == 0.70


@pytest.mark.parametrize("mauvais", [0.0, -0.5, 3.0, "beaucoup", None, True])
def test_une_part_de_ftp_inutilisable_revient_au_defaut(mauvais):
    doc = {"steps": [{"hr": {"units": "hr_zone", "value": 1}, "duration": 60}]}
    seance = depuis_workout_doc(
        doc, nom="EF", jour=JOUR, ftp_w=FTP, puissance_endurance_pct=mauvais
    )
    assert seance.etapes[0].puissance_cible_w == 0.60 * FTP


def test_une_zone_de_puissance_basse_n_est_pas_concernee():
    """`power_zone` est une consigne de puissance : la table s'applique telle quelle."""
    doc = {"steps": [{"power": {"units": "power_zone", "value": 1}, "duration": 60}]}
    etape = lire(doc).etapes[0]
    assert (etape.puissance_min_w, etape.puissance_max_w) == (0.0, 0.55 * FTP)
    assert lire(doc).meta["puissance_approximee"] is False


def test_une_zone_de_fc_basse_sans_ftp_ne_devine_rien():
    doc = {"steps": [{"hr": {"units": "hr_zone", "value": 1}, "duration": 60}]}
    assert lire(doc, ftp=None).etapes[0].puissance_cible_w is None


# --- étapes libres : pas des blocs ---------------------------------------------


def test_une_etape_libre_seule_devient_un_echauffement():
    seance = lire({"steps": [{"duration": 1200, "freeride": True}]})
    assert seance.etapes[0].type == "echauffement"
    assert seance.etapes[0].elastique is True
    assert seance.blocs() == []
    assert seance.meta["etapes_libres_reclassees"] == [{"indice": 0, "type": "echauffement"}]


def test_une_etape_libre_au_milieu_devient_une_recuperation():
    doc = {
        "steps": [
            {"duration": 600, "power": {"units": "watts", "value": 150}},
            {"duration": 900, "freeride": True},
            {"duration": 600, "power": {"units": "watts", "value": 150}},
        ]
    }
    assert [e.type for e in lire(doc).etapes] == ["bloc", "recuperation", "bloc"]


def test_une_etape_libre_en_fin_devient_un_retour_au_calme():
    doc = {
        "steps": [
            {"duration": 600, "power": {"units": "watts", "value": 150}},
            {"duration": 900, "freeride": True},
        ]
    }
    etapes = lire(doc).etapes
    assert etapes[1].type == "calme" and etapes[1].elastique is True


def test_une_etape_libre_gardee_marquee_par_la_source_garde_son_type():
    doc = {
        "steps": [
            {"duration": 600, "power": {"units": "watts", "value": 150}},
            {"duration": 900, "intensity": "recovery"},
            {"duration": 600, "warmup": True},
        ]
    }
    seance = lire(doc)
    assert [e.type for e in seance.etapes] == ["bloc", "recuperation", "echauffement"]
    # Aucune reclassification : les deux étaient déjà typées par la source.
    assert "etapes_libres_reclassees" not in seance.meta


def test_une_consigne_illisible_n_est_pas_du_roulage_libre():
    """Une unité inconnue reste une consigne : la source a voulu dire quelque chose."""
    doc = {
        "steps": [
            {"duration": 600, "power": {"units": "watts", "value": 150}},
            {"duration": 480, "power": {"units": "furlongs", "value": 3}},
            {"duration": 600, "power": {"units": "watts", "value": 150}},
        ]
    }
    seance = lire(doc)
    assert seance.etapes[1].type == "bloc"
    assert "etapes_libres_reclassees" not in seance.meta


def test_les_deux_etapes_libres_d_une_seance_mixte_sont_reclassees():
    seance = lire(W.plat_et_groupes())
    assert seance.etapes[0].type == "echauffement"
    assert seance.etapes[-1].type == "calme"
    assert len(seance.blocs()) == 5  # 4 sprints + 1 bloc de 5 min, les libres en moins
    assert len(seance.meta["etapes_libres_reclassees"]) == 2


# --- cascade de typage : marqueurs, puis texte, puis puissance -----------------


def test_regle_2_les_mots_du_texte_typent_une_seance_sans_marqueur():
    seance = lire(W.coach_sans_marqueur())
    assert [e.type for e in seance.etapes] == [
        "echauffement",
        "bloc",
        "recuperation",
        "bloc",
        "recuperation",
        "calme",
    ]
    assert seance.meta["typage_source"] == [
        "texte",
        "defaut",
        "texte",
        "defaut",
        "texte",
        "position",
    ]


@pytest.mark.parametrize(
    ("texte", "attendu"),
    [
        ("RPE cible 2,  Échauffement", "echauffement"),
        ("echauffement", "echauffement"),
        ("Warm up", "echauffement"),
        ("WARMUP", "echauffement"),
        ("RPE cible 2,  Récupération", "recuperation"),
        ("recup 3'", "recuperation"),
        ("Recovery spin", "recuperation"),
        ("Retour au calme", "calme"),
        ("Cool down", "calme"),
        ("Bloc seuil", None),
        ("", None),
    ],
)
def test_les_mots_reconnus_dans_le_texte(texte, attendu):
    """Le mot est cherché sans accents ni casse, au milieu d'un texte libre."""
    bloc = {"duration": 600, "power": {"units": "watts", "value": 200}}
    milieu = {"duration": 300, "power": {"units": "watts", "value": 200}, "text": texte}
    seance = lire({"steps": [dict(bloc), milieu, dict(bloc)]})
    assert seance.etapes[1].type == (attendu or "bloc")


def test_un_marqueur_l_emporte_sur_le_texte():
    doc = {
        "steps": [
            {"duration": 600, "power": {"units": "watts", "value": 200}},
            {
                "duration": 300,
                "power": {"units": "watts", "value": 200},
                "text": "Récupération",
                "warmup": True,
            },
            {"duration": 600, "power": {"units": "watts", "value": 200}},
        ]
    }
    seance = lire(doc)
    assert seance.etapes[1].type == "echauffement"
    assert seance.meta["typage_source"][1] == "marqueur"


def test_le_texte_du_groupe_sert_quand_l_etape_se_tait():
    doc = {
        "steps": [
            {"duration": 600, "power": {"units": "watts", "value": 200}},
            {
                "reps": 1,
                "text": "Récupération longue",
                "steps": [{"duration": 900, "power": {"units": "watts", "value": 200}}],
            },
            {"duration": 600, "power": {"units": "watts", "value": 200}},
        ]
    }
    assert lire(doc).etapes[1].type == "recuperation"


def test_regle_3_la_puissance_type_une_seance_muette():
    """« 4x8 SV1 outdoor » : ni marqueur ni texte, seulement 50 % contre 98 %."""
    seance = lire(W.coach_muet())
    types = [e.type for e in seance.etapes]
    assert types[0] == "echauffement"
    assert types[1:9] == ["bloc", "recuperation"] * 4
    assert types[9] == "calme"
    assert seance.meta["typage_source"][1] == "defaut"  # le bloc n'a pas été reclassé
    assert seance.meta["typage_source"][2] == "puissance"


def test_le_seuil_est_la_part_de_ftp_configuree():
    seance = lire(W.coach_muet())
    assert seance.meta["seuil_recuperation_pct"] == 0.75
    assert seance.meta["seuil_recuperation_w"] == 150.0  # 75 % de 200 W
    assert "seuil_recuperation_replie" not in seance.meta


def test_un_seuil_plus_haut_fait_basculer_des_blocs_en_recuperation():
    doc = {
        "steps": [
            {"power": {"units": "%ftp", "value": 50}, "duration": 600},
            {"power": {"units": "%ftp", "value": 85}, "duration": 600},
            {"power": {"units": "%ftp", "value": 50}, "duration": 600},
        ]
    }
    normal = depuis_workout_doc(doc, nom="s", jour=JOUR, ftp_w=FTP)
    assert normal.etapes[1].type == "bloc"
    haut = depuis_workout_doc(doc, nom="s", jour=JOUR, ftp_w=FTP, seuil_recuperation_pct=0.90)
    assert haut.etapes[1].type == "recuperation"


@pytest.mark.parametrize("mauvais", [0.0, -1.0, 5.0, "haut", None])
def test_un_seuil_inutilisable_revient_au_defaut(mauvais):
    seance = depuis_workout_doc(
        W.coach_muet(), nom="s", jour=JOUR, ftp_w=FTP, seuil_recuperation_pct=mauvais
    )
    assert seance.meta["seuil_recuperation_pct"] == 0.75


def test_sans_ftp_le_seuil_est_tire_de_la_seance_et_le_dit():
    doc = {
        "steps": [
            {"power": {"units": "watts", "value": 100}, "duration": 600},
            {"power": {"units": "watts", "value": 250}, "duration": 600},
            {"power": {"units": "watts", "value": 100}, "duration": 600},
        ]
    }
    seance = lire(doc, ftp=None)
    assert seance.meta["seuil_recuperation_replie"] is True
    assert seance.meta["seuil_recuperation_w"] == 175.0  # mi-chemin entre 100 et 250
    assert [e.type for e in seance.etapes] == ["echauffement", "bloc", "calme"]


def test_sans_ftp_et_sans_contraste_on_ne_devine_rien():
    doc = {"steps": [{"power": {"units": "watts", "value": 150}, "duration": 600}] * 3}
    seance = lire(doc, ftp=None)
    assert "seuil_recuperation_w" not in seance.meta
    assert [e.type for e in seance.etapes] == ["bloc", "bloc", "bloc"]


def test_une_sortie_uniforme_n_a_aucun_bloc_et_c_est_correct():
    """Toutes les étapes du même côté du seuil : on ne fabrique pas de bloc."""
    doc = {
        "steps": [
            {"power": {"units": "%ftp", "value": 60}, "duration": 1800},
            {"power": {"units": "%ftp", "value": 62}, "duration": 1800},
            {"power": {"units": "%ftp", "value": 58}, "duration": 1800},
        ]
    }
    seance = lire(doc)
    assert seance.blocs() == []
    assert [e.type for e in seance.etapes] == ["echauffement", "recuperation", "calme"]


def test_une_seance_entierement_au_dessus_du_seuil_reste_en_blocs():
    doc = {"steps": [{"power": {"units": "%ftp", "value": 95}, "duration": 600}] * 3}
    seance = lire(doc)
    assert len(seance.blocs()) == 3


def test_typage_source_a_une_entree_par_etape():
    for fabrique in ("groupes_hr_zone", "groupes_watts", "coach_sans_marqueur", "coach_muet"):
        seance = lire(getattr(W, fabrique)())
        assert len(seance.meta["typage_source"]) == len(seance.etapes)
        assert set(seance.meta["typage_source"]) <= {
            "marqueur",
            "texte",
            "puissance",
            "libre",
            "position",
            "defaut",
        }
