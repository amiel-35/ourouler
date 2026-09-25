"""Tests de `ourouler seance` (lot L4.1).

Aucun réseau : le client Intervals est un `ClientIntervals` branché sur un
`httpx.MockTransport`. Aucune donnée réelle : la configuration part du point
(0, 0) et les `workout_doc` sont ceux de `tests/fixtures/workouts.py`.
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import date
from pathlib import Path

import httpx
import pytest
from test_seance_intervals import ATHLETE, CLE, W

from ourouler.config import Config, depuis_dict
from ourouler.connecteurs.intervals import ClientIntervals
from ourouler.erreurs import ErreurUtilisateur
from ourouler.physique.commande import VERSION_CALIBRATION, chemin_calibration
from ourouler.physique.modele import Parametres, vitesse_regime
from ourouler.seance.commande import executer, longueurs, rendre_json, rendre_texte
from ourouler.seance.intervals import depuis_workout_doc
from ourouler.seance.modele import Etape, Seance

JOUR = date(2026, 9, 8)
FTP = 200.0

#: Paramètres physiques inventés, proches d'un vélo de route.
PARAMETRES = Parametres(masse_totale_kg=85.0, cda_m2=0.32, crr=0.005)


def config_de_test(dossier: Path, **sections) -> Config:
    brute = {
        "depart": {"nom": "Point zéro", "latitude": 0.0, "longitude": 0.0},
        "cycliste": {"masse_kg": 76.5, "ftp_w": FTP},
        "velos": [{"nom": "Route", "usage": "route"}],
        "cache": {"dossier": str(dossier)},
        "boucle": {"vitesse_moyenne_kmh": 27.0},
        "intervals": {"athlete_id": ATHLETE, "api_key": CLE},
    }
    return depuis_dict({**brute, **sections})


def client_bouchon(evenements: list[dict]) -> ClientIntervals:
    def gestionnaire(requete: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=evenements)

    return ClientIntervals(
        ATHLETE, CLE, http=httpx.Client(transport=httpx.MockTransport(gestionnaire))
    )


def args(**champs) -> argparse.Namespace:
    return argparse.Namespace(**{"jour": JOUR.isoformat(), "json": False, **champs})


def ecrire_calibration_de_test(dossier: Path, velo: str = "Route") -> None:
    chemin = dossier / "calibration.json"
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text(
        json.dumps(
            {
                "version": VERSION_CALIBRATION,
                "velos": {
                    velo: {
                        "masse_totale_kg": PARAMETRES.masse_totale_kg,
                        "cda_m2": PARAMETRES.cda_m2,
                        "crr": PARAMETRES.crr,
                        "date": "2026-09-01",
                        "n_sorties": 12,
                        "mae": 0.03,
                    }
                },
            }
        ),
        encoding="utf-8",
    )


def seance_4x8() -> Seance:
    return depuis_workout_doc(
        W.groupes_watts(), nom="4x8 fabriquée", jour=JOUR, ftp_w=FTP
    )


# --- longueurs ----------------------------------------------------------------


def test_la_longueur_d_un_bloc_est_la_vitesse_du_modele_fois_la_duree():
    seance = seance_4x8()
    mesures = longueurs(seance, parametres=PARAMETRES)
    bloc = mesures[1]
    attendue = vitesse_regime(250.0, 0.0, 0.0, PARAMETRES)  # 240-260 W → cible 250 W
    assert bloc.vitesse_ms == pytest.approx(attendue)
    assert bloc.longueur_m == pytest.approx(attendue * 480.0)


def test_la_route_au_dela_vaut_la_moitie_de_la_recuperation():
    mesures = longueurs(seance_4x8(), parametres=PARAMETRES)
    bloc = mesures[1]
    v_recup = vitesse_regime(110.0, 0.0, 0.0, PARAMETRES)
    assert bloc.recup_s == 240.0
    assert bloc.au_dela_m == pytest.approx(v_recup * 240.0 / 2)
    # C'est bien la moitié, pas la totalité : l'autre moitié ramène sur le segment.
    assert bloc.au_dela_m < v_recup * 240.0


def test_seuls_les_blocs_ont_une_route_au_dela():
    mesures = longueurs(seance_4x8(), parametres=PARAMETRES)
    avec = [m.indice for m in mesures if m.au_dela_m is not None]
    assert avec == [1, 3, 5, 7]


def test_le_dernier_bloc_suivi_d_un_calme_n_a_pas_de_demi_tour():
    """Sans récupération derrière, la question du demi-tour ne se pose pas."""
    etapes = [
        Etape("bloc", 480.0, 240.0, 260.0),
        Etape("calme", 300.0, 100.0, 120.0, elastique=True),
    ]
    seance = Seance("sans récup", JOUR, etapes, 780.0, {})
    mesures = longueurs(seance, parametres=PARAMETRES)
    assert mesures[0].au_dela_m is None
    assert mesures[0].recup_s is None


def test_une_etape_sans_puissance_n_a_pas_de_longueur_avec_le_modele():
    seance = depuis_workout_doc(W.plat_et_groupes(), nom="mixte", jour=JOUR, ftp_w=FTP)
    mesures = longueurs(seance, parametres=PARAMETRES)
    sans = [m for m in mesures if m.etape.puissance_cible_w is None]
    assert sans and all(m.longueur_m is None and m.vitesse_ms is None for m in sans)


def test_en_mode_vitesse_constante_toutes_les_etapes_ont_une_longueur():
    seance = depuis_workout_doc(W.plat_et_groupes(), nom="mixte", jour=JOUR, ftp_w=FTP)
    mesures = longueurs(seance, vitesse_ms=7.5)
    assert all(m.vitesse_ms == 7.5 for m in mesures)
    assert all(m.longueur_m == pytest.approx(7.5 * m.etape.duree_s) for m in mesures)


def test_vitesse_constante_et_parametres_ensemble_sont_refuses():
    with pytest.raises(ErreurUtilisateur, match="pas les deux"):
        longueurs(seance_4x8(), parametres=PARAMETRES, vitesse_ms=7.0)


def test_ni_l_un_ni_l_autre_est_refuse():
    with pytest.raises(ErreurUtilisateur, match="pas les deux"):
        longueurs(seance_4x8())


def test_une_seance_sans_etape_donne_une_liste_vide():
    seance = depuis_workout_doc({}, nom="vide", jour=JOUR, ftp_w=FTP)
    assert longueurs(seance, parametres=PARAMETRES) == []


def test_vitesse_kmh_est_la_conversion_de_la_vitesse_ms():
    mesures = longueurs(seance_4x8(), vitesse_ms=10.0)
    assert mesures[0].vitesse_kmh == pytest.approx(36.0)


# --- la commande, de bout en bout ---------------------------------------------


def test_la_commande_affiche_la_seance_et_les_longueurs(tmp_path, capsys):
    ecrire_calibration_de_test(tmp_path)
    config = config_de_test(tmp_path)
    evenements = [W.evenement(W.groupes_watts(), nom="4x8 fabriquée")]
    assert executer(args(), config, client=client_bouchon(evenements)) == 0
    sortie = capsys.readouterr().out
    assert "4x8 fabriquée" in sortie
    assert "2026-09-08" in sortie
    assert "4 bloc(s)" in sortie
    assert "modèle calibré" in sortie
    assert "km" in sortie


def test_sans_seance_ce_jour_la_message_clair_et_code_zero(tmp_path, capsys):
    config = config_de_test(tmp_path)
    assert executer(args(jour="2026-09-09"), config, client=client_bouchon([])) == 0
    sortie = capsys.readouterr().out
    assert "Aucune séance vélo planifiée le 2026-09-09" in sortie


def test_sans_seance_en_json(tmp_path, capsys):
    config = config_de_test(tmp_path)
    assert executer(args(json=True), config, client=client_bouchon([])) == 0
    assert json.loads(capsys.readouterr().out) == {"jour": "2026-09-08", "seance": None}


def test_sans_calibration_la_vitesse_de_config_est_utilisee_et_dite(tmp_path, capsys):
    config = config_de_test(tmp_path)  # aucun calibration.json écrit
    evenements = [W.evenement(W.groupes_watts(), nom="4x8 fabriquée")]
    assert executer(args(), config, client=client_bouchon(evenements)) == 0
    sortie = capsys.readouterr().out
    assert "27,0 km/h" in sortie
    assert "n'est pas calibré" in sortie
    assert "modèle calibré" not in sortie


def test_avec_calibration_la_provenance_est_dite(tmp_path, capsys):
    ecrire_calibration_de_test(tmp_path)
    config = config_de_test(tmp_path)
    evenements = [W.evenement(W.groupes_watts(), nom="4x8 fabriquée")]
    executer(args(json=True), config, client=client_bouchon(evenements))
    charge = json.loads(capsys.readouterr().out)
    assert charge["vitesses"]["provenance"] == "calibration"
    assert charge["vitesses"]["calibree"] is True
    assert charge["vitesses"]["velo"] == "Route"


def test_le_json_porte_chaque_etape(tmp_path, capsys):
    ecrire_calibration_de_test(tmp_path)
    config = config_de_test(tmp_path)
    evenements = [W.evenement(W.groupes_watts(), nom="4x8 fabriquée")]
    executer(args(json=True), config, client=client_bouchon(evenements))
    charge = json.loads(capsys.readouterr().out)
    assert charge["nom"] == "4x8 fabriquée"
    assert charge["n_blocs"] == 4
    assert len(charge["etapes"]) == 10
    bloc = charge["etapes"][1]
    assert bloc["type"] == "bloc"
    assert bloc["puissance_cible_w"] == 250
    assert bloc["route_au_dela_m"] > 0
    assert charge["etapes"][0]["elastique"] is True
    assert charge["etapes"][0]["route_au_dela_m"] is None


def test_la_puissance_approximee_est_annoncee(tmp_path, capsys):
    ecrire_calibration_de_test(tmp_path)
    config = config_de_test(tmp_path)
    evenements = [W.evenement(W.groupes_hr_zone(), nom="HIT fabriquée")]
    executer(args(), config, client=client_bouchon(evenements))
    sortie = capsys.readouterr().out
    assert "approximées" in sortie
    assert "fréquence cardiaque" in sortie


def test_une_seance_sans_approximation_ne_le_dit_pas(tmp_path, capsys):
    ecrire_calibration_de_test(tmp_path)
    config = config_de_test(tmp_path)
    evenements = [W.evenement(W.groupes_watts(), nom="4x8 fabriquée")]
    executer(args(), config, client=client_bouchon(evenements))
    assert "approximées" not in capsys.readouterr().out


def test_les_etapes_sans_puissance_sont_signalees(tmp_path, capsys):
    ecrire_calibration_de_test(tmp_path)
    config = config_de_test(tmp_path)
    evenements = [W.evenement(W.plat_et_groupes(), nom="mixte")]
    executer(args(), config, client=client_bouchon(evenements))
    sortie = capsys.readouterr().out
    assert "sans consigne de puissance" in sortie
    assert "hors 2 étape(s) sans puissance" in sortie


def test_une_seance_vide_le_dit(tmp_path, capsys):
    ecrire_calibration_de_test(tmp_path)
    config = config_de_test(tmp_path)
    evenements = [W.evenement({}, nom="Séance creuse")]
    assert executer(args(), config, client=client_bouchon(evenements)) == 0
    assert "aucune étape exploitable" in capsys.readouterr().out


def test_les_autres_seances_du_jour_sont_nommees(tmp_path, capsys):
    ecrire_calibration_de_test(tmp_path)
    config = config_de_test(tmp_path)
    evenements = [
        W.evenement(W.groupes_watts(), nom="Vélo A", identifiant=1),
        W.evenement(W.groupes_watts(), nom="Vélo B", identifiant=2),
    ]
    executer(args(), config, client=client_bouchon(evenements))
    sortie = capsys.readouterr().out
    assert "Vélo B" in sortie
    assert "ignorée(s) au profit de la plus longue" in sortie


def test_jour_absent_vaut_aujourd_hui(tmp_path, capsys):
    config = config_de_test(tmp_path)
    assert executer(args(jour=None), config, client=client_bouchon([])) == 0
    assert date.today().isoformat() in capsys.readouterr().out


@pytest.mark.parametrize("mauvais", ["hier", "2026-13-01", "08/09/2026", ""])
def test_un_jour_illisible_est_refuse_en_nommant_l_option(tmp_path, mauvais):
    config = config_de_test(tmp_path)
    if mauvais == "":
        # Chaîne vide = option non renseignée : c'est aujourd'hui, pas une erreur.
        assert executer(args(jour=""), config, client=client_bouchon([])) == 0
        return
    with pytest.raises(ErreurUtilisateur, match="--jour"):
        executer(args(jour=mauvais), config, client=client_bouchon([]))


def test_sans_cle_intervals_le_message_nomme_la_section(tmp_path):
    config = config_de_test(tmp_path, intervals={"athlete_id": "", "api_key": ""})
    with pytest.raises(ErreurUtilisateur, match=r"\[intervals\]"):
        executer(args(), config)


def test_la_cle_n_apparait_jamais_dans_la_sortie(tmp_path, capsys):
    ecrire_calibration_de_test(tmp_path)
    config = config_de_test(tmp_path)
    evenements = [W.evenement(W.groupes_watts(), nom="4x8 fabriquée")]
    executer(args(json=True), config, client=client_bouchon(evenements))
    capture = capsys.readouterr()
    assert CLE not in capture.out and CLE not in capture.err


# --- rendus -------------------------------------------------------------------


def test_le_tableau_a_une_ligne_par_etape(tmp_path):
    ecrire_calibration_de_test(tmp_path)
    seance = seance_4x8()
    mesures = longueurs(seance, parametres=PARAMETRES)
    from ourouler.seance.commande import SourceVitesse

    source = SourceVitesse("calibration", "Route", PARAMETRES, None)
    texte = rendre_texte(seance, mesures, source)
    lignes = [ligne for ligne in texte.splitlines() if re.match(r"^ +\d+ ", ligne)]
    assert len(lignes) == 10
    assert lignes[0].split()[1] == "échauffement"
    # Une consigne déjà donnée en watts n'est pas répétée deux fois.
    assert "130 W 130 W" not in texte


def test_le_json_est_serialisable_et_complet():
    from ourouler.seance.commande import SourceVitesse

    seance = depuis_workout_doc(W.groupes_hr_zone(), nom="HIT", jour=JOUR, ftp_w=FTP)
    mesures = longueurs(seance, vitesse_ms=7.5)
    source = SourceVitesse("configuration", "Route", None, 7.5)
    charge = json.loads(json.dumps(rendre_json(seance, mesures, source), ensure_ascii=False))
    assert charge["meta"]["puissance_approximee"] is True
    assert charge["vitesses"]["vitesse_kmh"] == 27.0
    assert charge["duree_s"] == 3780


def test_chemin_calibration_reste_dans_le_cache(tmp_path):
    config = config_de_test(tmp_path)
    assert chemin_calibration(config) == tmp_path / "calibration.json"


# --- zones de FC et étapes libres dans le rendu (Q11) --------------------------


def test_le_message_d_approximation_distingue_zones_basses_et_hautes(tmp_path, capsys):
    ecrire_calibration_de_test(tmp_path)
    config = config_de_test(tmp_path)
    evenements = [W.evenement(W.groupes_hr_zone(), nom="HIT fabriquée")]
    executer(args(), config, client=client_bouchon(evenements))
    sortie = capsys.readouterr().out
    assert "Zones basses" in sortie
    assert "60 % de FTP" in sortie
    assert "puissance d'endurance mesurée" in sortie
    assert "Zones hautes" in sortie


def test_une_seance_en_pourcent_ftp_n_affiche_aucun_avertissement(tmp_path, capsys):
    """Le cas nominal : rien à approximer, donc rien à dire."""
    ecrire_calibration_de_test(tmp_path)
    config = config_de_test(tmp_path)
    evenements = [W.evenement(W.groupes_pourcent_ftp(), nom="Séance en %FTP")]
    executer(args(), config, client=client_bouchon(evenements))
    sortie = capsys.readouterr().out
    assert "approximées" not in sortie
    assert "Zones basses" not in sortie


def test_la_part_de_ftp_de_la_configuration_est_utilisee(tmp_path, capsys):
    ecrire_calibration_de_test(tmp_path)
    config = config_de_test(tmp_path, seance={"puissance_endurance_pct": 0.70})
    evenements = [W.evenement(W.groupes_hr_zone(), nom="HIT fabriquée")]
    executer(args(json=True), config, client=client_bouchon(evenements))
    charge = json.loads(capsys.readouterr().out)
    assert charge["meta"]["puissance_endurance_pct"] == 0.70
    assert charge["etapes"][0]["puissance_cible_w"] == 140  # 70 % de 200 W


def test_une_endurance_en_zone_de_fc_donne_une_distance_plausible(tmp_path, capsys):
    """2 h en Z1 de FC : une EF, pas du pédalage à vide."""
    ecrire_calibration_de_test(tmp_path)
    config = config_de_test(tmp_path)
    evenements = [W.evenement(W.sortie_libre(), nom="EF fabriquée")]
    executer(args(json=True), config, client=client_bouchon(evenements))
    charge = json.loads(capsys.readouterr().out)
    etape = charge["etapes"][0]
    assert etape["puissance_cible_w"] == 120  # 60 % de 200 W
    assert 24.0 < etape["vitesse_kmh"] < 34.0


def test_les_etapes_libres_reclassees_sont_dites(tmp_path, capsys):
    ecrire_calibration_de_test(tmp_path)
    config = config_de_test(tmp_path)
    evenements = [W.evenement(W.plat_et_groupes(), nom="mixte")]
    executer(args(), config, client=client_bouchon(evenements))
    sortie = capsys.readouterr().out
    assert "ce ne sont pas des blocs" in sortie
    assert "#1 → échauffement" in sortie
    assert "5 bloc(s)" in sortie


# --- cascade de typage, de bout en bout ---------------------------------------


def test_une_seance_de_coach_sans_marqueur_a_ses_blocs_et_ses_recups(tmp_path, capsys):
    ecrire_calibration_de_test(tmp_path)
    config = config_de_test(tmp_path)
    evenements = [W.evenement(W.coach_sans_marqueur(), nom="2x20' fabriquée")]
    executer(args(json=True), config, client=client_bouchon(evenements))
    charge = json.loads(capsys.readouterr().out)
    assert charge["n_blocs"] == 2
    assert charge["etapes"][0]["type"] == "echauffement"
    assert charge["etapes"][0]["elastique"] is True
    assert charge["etapes"][-1]["type"] == "calme"
    assert charge["etapes"][-1]["elastique"] is True
    # Chaque bloc est suivi d'une récup, donc chacun a sa route au-delà.
    assert all(e["route_au_dela_m"] > 0 for e in charge["etapes"] if e["type"] == "bloc")


def test_une_seance_muette_est_typee_par_la_puissance(tmp_path, capsys):
    ecrire_calibration_de_test(tmp_path)
    config = config_de_test(tmp_path)
    evenements = [W.evenement(W.coach_muet(), nom="4x8 fabriquée")]
    executer(args(json=True), config, client=client_bouchon(evenements))
    charge = json.loads(capsys.readouterr().out)
    assert charge["n_blocs"] == 4
    assert charge["meta"]["seuil_recuperation_w"] == 150.0
    assert charge["meta"]["typage_source"][2] == "puissance"


def test_le_seuil_de_la_configuration_est_utilise(tmp_path, capsys):
    ecrire_calibration_de_test(tmp_path)
    config = config_de_test(tmp_path, seance={"seuil_recuperation_pct": 0.90})
    evenements = [W.evenement(W.coach_sans_marqueur(), nom="2x20' fabriquée")]
    executer(args(json=True), config, client=client_bouchon(evenements))
    charge = json.loads(capsys.readouterr().out)
    # 80-85 % de FTP passe sous un seuil à 90 % : plus aucun bloc.
    assert charge["meta"]["seuil_recuperation_pct"] == 0.90
    assert charge["n_blocs"] == 0


# --- plage --depuis/--jusqua (F0.3) --------------------------------------------


def test_plage_json_couvre_chaque_jour_seance_ou_non(tmp_path, capsys):
    ecrire_calibration_de_test(tmp_path)
    config = config_de_test(tmp_path)
    evenements = [
        W.evenement(W.groupes_watts(), nom="Lundi", identifiant=1, jour="2026-09-07"),
        W.evenement(W.groupes_watts(), nom="Mercredi", identifiant=2, jour="2026-09-09"),
    ]
    code = executer(
        args(jour=None, depuis="2026-09-07", jusqua="2026-09-09", json=True),
        config,
        client=client_bouchon(evenements),
    )
    assert code == 0
    charge = json.loads(capsys.readouterr().out)
    assert charge["depuis"] == "2026-09-07"
    assert charge["jusqua"] == "2026-09-09"
    jours = {j["jour"]: j["seance"] for j in charge["jours"]}
    assert list(jours) == ["2026-09-07", "2026-09-08", "2026-09-09"]
    assert jours["2026-09-07"]["nom"] == "Lundi"
    assert jours["2026-09-08"] is None  # jour demandé, sans séance : distinct d'un jour absent
    assert jours["2026-09-09"]["nom"] == "Mercredi"
    # La séance de la plage a la même forme que celle de `seance --jour`.
    assert "etapes" in jours["2026-09-07"] and "distance_estimee_m" in jours["2026-09-07"]


def test_plage_texte_dit_les_jours_vides(tmp_path, capsys):
    config = config_de_test(tmp_path)
    evenements = [W.evenement(W.groupes_watts(), nom="Mercredi", jour="2026-09-09")]
    executer(
        args(jour=None, depuis="2026-09-07", jusqua="2026-09-09"),
        config,
        client=client_bouchon(evenements),
    )
    sortie = capsys.readouterr().out
    assert "2026-09-07 — aucune séance vélo planifiée." in sortie
    assert "2026-09-08 — aucune séance vélo planifiée." in sortie
    assert "Mercredi" in sortie


def test_plage_un_seul_appel_reseau(tmp_path, capsys):
    config = config_de_test(tmp_path)
    urls: list[httpx.URL] = []

    def gestionnaire(requete: httpx.Request) -> httpx.Response:
        urls.append(requete.url)
        return httpx.Response(200, json=[])

    client = ClientIntervals(
        ATHLETE, CLE, http=httpx.Client(transport=httpx.MockTransport(gestionnaire))
    )
    executer(args(jour=None, depuis="2026-09-07", jusqua="2026-09-13"), config, client=client)
    assert len(urls) == 1
    assert urls[0].params["oldest"] == "2026-09-07"
    assert urls[0].params["newest"] == "2026-09-13"


def test_jour_et_plage_ensemble_sont_refuses(tmp_path):
    config = config_de_test(tmp_path)
    with pytest.raises(ErreurUtilisateur, match="exclusifs"):
        executer(
            args(depuis="2026-09-07", jusqua="2026-09-13"), config, client=client_bouchon([])
        )


def test_depuis_sans_jusqua_est_refuse(tmp_path):
    config = config_de_test(tmp_path)
    with pytest.raises(ErreurUtilisateur, match="ensemble"):
        executer(args(jour=None, depuis="2026-09-07"), config, client=client_bouchon([]))


def test_plage_inversee_est_refusee(tmp_path):
    config = config_de_test(tmp_path)
    with pytest.raises(ErreurUtilisateur):
        executer(
            args(jour=None, depuis="2026-09-13", jusqua="2026-09-07"),
            config,
            client=client_bouchon([]),
        )


# --- --fichier-seance (F1, C1 de docs/journal/ux/relecture_f0.md) ---------------------

ZWO_FABRIQUE = (
    "<?xml version='1.0'?>\n<workout_file>\n<name>4x8 fabriquée (fichier)</name>\n"
    '<workout><SteadyState Duration="480" Power="0.9"/></workout>\n'
    "</workout_file>\n"
)


def _ecrire_zwo(tmp_path: Path) -> Path:
    chemin = tmp_path / "seance.zwo"
    chemin.write_text(ZWO_FABRIQUE, encoding="utf-8")
    return chemin


def test_fichier_seance_ne_touche_jamais_intervals(tmp_path):
    """Un `client` est donné mais ne doit jamais être sollicité : la preuve
    qu'un fichier remplace vraiment Intervals.icu, pas seulement en apparence."""

    def gestionnaire(requete: httpx.Request) -> httpx.Response:
        raise AssertionError("Intervals.icu appelé alors qu'un fichier était donné")

    client = ClientIntervals(
        ATHLETE, CLE, http=httpx.Client(transport=httpx.MockTransport(gestionnaire))
    )
    chemin = _ecrire_zwo(tmp_path)
    config = config_de_test(tmp_path)
    code = executer(args(jour=None, fichier_seance=str(chemin)), config, client=client)
    assert code == 0


def test_fichier_seance_affiche_la_seance_lue(tmp_path, capsys):
    chemin = _ecrire_zwo(tmp_path)
    config = config_de_test(tmp_path)
    executer(args(jour=None, fichier_seance=str(chemin)), config)
    sortie = capsys.readouterr().out
    assert "4x8 fabriquée (fichier)" in sortie
    assert "8 min" in sortie or "8:00" in sortie


def test_fichier_seance_dit_la_conversion_en_watts(tmp_path, capsys):
    """C1 + E17 : la conversion pourcentage → watts est visible en texte."""
    chemin = _ecrire_zwo(tmp_path)
    config = config_de_test(tmp_path)
    executer(args(jour=None, fichier_seance=str(chemin)), config)
    sortie = capsys.readouterr().out
    assert f"FTP de {FTP:g} W" in sortie


def test_fichier_seance_json_porte_la_conversion_dans_meta(tmp_path, capsys):
    chemin = _ecrire_zwo(tmp_path)
    config = config_de_test(tmp_path)
    executer(args(jour=None, json=True, fichier_seance=str(chemin)), config)
    charge = json.loads(capsys.readouterr().out)
    assert charge["meta"]["source"] == "zwo"
    assert "convertis en watts" in charge["meta"]["conversion"]


def test_fichier_seance_utilise_le_jour_donne(tmp_path, capsys):
    chemin = _ecrire_zwo(tmp_path)
    config = config_de_test(tmp_path)
    executer(args(jour="2026-01-05", fichier_seance=str(chemin), json=True), config)
    charge = json.loads(capsys.readouterr().out)
    assert charge["jour"] == "2026-01-05"


def test_fichier_seance_sans_jour_vaut_aujourd_hui(tmp_path, capsys):
    chemin = _ecrire_zwo(tmp_path)
    config = config_de_test(tmp_path)
    executer(args(jour=None, fichier_seance=str(chemin), json=True), config)
    charge = json.loads(capsys.readouterr().out)
    assert charge["jour"] == date.today().isoformat()


def test_fichier_seance_utilise_le_modele_calibre_comme_les_autres_modes(tmp_path, capsys):
    ecrire_calibration_de_test(tmp_path)
    chemin = _ecrire_zwo(tmp_path)
    config = config_de_test(tmp_path)
    executer(args(jour=None, fichier_seance=str(chemin), json=True), config)
    charge = json.loads(capsys.readouterr().out)
    assert charge["vitesses"]["provenance"] == "calibration"


def test_fichier_seance_exclusif_de_depuis_jusqua(tmp_path):
    chemin = _ecrire_zwo(tmp_path)
    config = config_de_test(tmp_path)
    with pytest.raises(ErreurUtilisateur, match="exclusif"):
        executer(
            args(
                jour=None,
                fichier_seance=str(chemin),
                depuis="2026-09-07",
                jusqua="2026-09-13",
            ),
            config,
        )


def test_fichier_seance_inexistant_est_une_erreur_utilisateur(tmp_path):
    config = config_de_test(tmp_path)
    with pytest.raises(ErreurUtilisateur):
        executer(args(jour=None, fichier_seance=str(tmp_path / "absent.zwo")), config)


def test_fichier_seance_extension_inconnue_nomme_l_extension(tmp_path):
    chemin = tmp_path / "seance.fit"
    chemin.write_text("peu importe", encoding="utf-8")
    config = config_de_test(tmp_path)
    with pytest.raises(ErreurUtilisateur, match="inconnue"):
        executer(args(jour=None, fichier_seance=str(chemin)), config)
