"""Lot 11 : le choix du chemin, et ce que la comparaison du mode `double` dit (et tait).

Les références de caractérisation, rejouées sur les trois chemins, sont dans
`test_caracterisation_api.py` ; ici, les pièces du mécanisme une à une.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from outils_caracterisation import (
    DOSSIER,
    JOUR,
    comparer_a_la_reference,
    preparer,
    serialiser,
)
from test_caracterisation_api import REGENERER, Serveur

from ourouler.api import exploitation
from ourouler.api.adaptateur import Avertissement, Resultat
from ourouler.api.application import creer_application
from ourouler.api.double_chemin import (
    CHEMIN_ANCIEN,
    ecart_entre,
    executer_service,
)
from ourouler.api.erreurs import ErreurApi
from ourouler.noyau.erreurs import ErreurUtilisateur

# --- la variable ----------------------------------------------------------------


def test_sans_variable_le_chemin_est_le_defaut():
    from ourouler.api import double_chemin

    assert exploitation.chemin_api({}) == double_chemin.CHEMIN_DEFAUT
    assert exploitation.chemin_api({"OUROULER_API_CHEMIN": "  "}) == double_chemin.CHEMIN_DEFAUT


def test_le_defaut_de_ce_lot_est_l_ancien_chemin():
    """La bascule se fait en préproduction, par `double` d'abord — pas dans le code.

    Lu dans la source et non sur le module : `OUROULER_API_CHEMIN` posée pour
    rejouer `tests/api/` change le défaut le temps des tests (`conftest.py`).
    """
    from ourouler.api import double_chemin

    source = Path(double_chemin.__file__).read_text(encoding="utf-8")
    assert "\nCHEMIN_DEFAUT = CHEMIN_ANCIEN\n" in source
    assert CHEMIN_ANCIEN == "ancien"


@pytest.mark.parametrize("valeur", ["ancien", "nouveau", "double", " Double "])
def test_les_trois_chemins_sont_lus(valeur: str):
    assert exploitation.chemin_api({"OUROULER_API_CHEMIN": valeur}) == valeur.strip().lower()


def test_un_chemin_inconnu_refuse_le_demarrage():
    from ourouler.noyau.erreurs import ErreurConfig

    with pytest.raises(ErreurConfig, match="OUROULER_API_CHEMIN"):
        exploitation.chemin_api({"OUROULER_API_CHEMIN": "les-deux"})


def test_la_fabrique_refuse_un_chemin_inconnu():
    with pytest.raises(ValueError, match="chemin_api"):
        creer_application(chemin_api="les-deux")


# --- le nouveau chemin, sans processus ------------------------------------------


def test_les_avertissements_du_nouveau_chemin_sont_ceux_de_l_ancien():
    """Préfixe retiré, secret masqué, ligne multiple découpée : comme sur la sortie d'erreur."""

    def travail(avertir):
        avertir("ourouler : second avis indisponible (clé-secrète)")
        avertir("ourouler : première ligne\nourouler : seconde ligne")
        return {"a": (1, 2), 3: "clé entière"}

    resultat = executer_service(travail, secrets=["clé-secrète"])
    # Repassé par JSON, comme l'ancien chemin le lisait : tuple → liste, clé → chaîne.
    assert resultat.donnees == {"a": [1, 2], "3": "clé entière"}
    messages = [a.message for a in resultat.avertissements]
    assert messages[1:] == ["première ligne", "seconde ligne"]
    assert "clé-secrète" not in messages[0] and messages[0].startswith("second avis")


def test_une_erreur_du_nouveau_chemin_est_traduite():
    def travail(avertir):
        raise ErreurUtilisateur("/serveur/fichier.gpx : fichier vide")

    with pytest.raises(ErreurApi) as erreur:
        executer_service(travail, chemins={"/serveur/fichier.gpx": "ma_boucle.gpx"})
    assert "ma_boucle.gpx" in erreur.value.message
    assert "/serveur/" not in erreur.value.message


# --- la comparaison ---------------------------------------------------------------


def _resultat(donnees, *avertissements: str) -> Resultat:
    return Resultat(
        donnees=donnees,
        avertissements=tuple(Avertissement(code="c", message=m) for m in avertissements),
        duree_ms=1,
    )


def test_deux_reponses_identiques_ne_font_pas_d_ecart():
    assert ecart_entre(_resultat({"a": 1}), Resultat({"a": 1}, (), 999)) is None


def test_un_entier_devenu_flottant_est_un_ecart():
    ecart = ecart_entre(_resultat({"distance_km": 30}), _resultat({"distance_km": 30.0}))
    assert ecart is not None and ecart["cles"] == [".donnees.distance_km"]


def test_un_statut_different_est_un_ecart_de_statut():
    erreur = ErreurApi(code="service_indisponible", message="Rue du Moulin", statut=502)
    ecart = ecart_entre(_resultat({"a": 1}), erreur)
    assert ecart["nature"] == "statut"
    assert ecart["nouveau"] == {"statut": 502, "code": "service_indisponible"}
    assert "Moulin" not in json.dumps(ecart, ensure_ascii=False)


def test_l_ecart_ne_cite_aucune_valeur_ni_cle_de_donnee():
    """Une clé qui est une donnée (un nom de vélo, une date) sort en `*`, une valeur jamais."""
    ancien = _resultat({"velos": {"Mon Vélo": {"km": 12.5}, "2026-09-08": "pluie"}}, "12 rue X")
    nouveau = _resultat({"velos": {"Mon Vélo": {"km": 13.0}, "2026-09-08": "sec"}}, "14 rue Y")
    texte = json.dumps(ecart_entre(ancien, nouveau), ensure_ascii=False)
    for secret in ("Mon Vélo", "2026-09-08", "12.5", "13.0", "pluie", "sec", "rue"):
        assert secret not in texte, secret
    assert ".donnees.velos.*.km" in texte
    assert ".avertissements[0].message" in texte


@pytest.fixture
def rejeu(monkeypatch: pytest.MonkeyPatch, fuseau_de_paris):
    """Le réseau rejoué et l'horloge figée du filet (`outils_caracterisation.preparer`)."""
    return preparer(monkeypatch)


# --- mutation de contrôle, sur les références de caractérisation ------------------
#
# Sans ce contrôle, trois modes verts pourraient vouloir dire que le nouveau
# chemin ne tourne jamais, ou que la comparaison du mode `double` ne voit
# rien. Le nouveau chemin de `GET /meteo` est faussé : la référence doit
# passer au rouge en `nouveau`, et une ligne d'écart apparaître en `double`
# — où la réponse, servie par l'ancien, reste celle de la référence.

VALEUR_FAUSSEE = "faussé par la mutation de contrôle"


@pytest.fixture
def meteo_faussee(monkeypatch: pytest.MonkeyPatch) -> None:
    from ourouler.api import calculs

    vraie = calculs.meteo

    def faussee(*args: Any, **kwargs: Any) -> dict:
        donnees = vraie(*args, **kwargs)
        donnees[next(iter(donnees))] = VALEUR_FAUSSEE
        return donnees

    monkeypatch.setattr(calculs, "meteo", faussee)


def _appel_meteo(tmp_path: Path, rejeu, chemin_api: str) -> dict[str, Any]:
    dossier = tmp_path / chemin_api
    dossier.mkdir()
    return Serveur(dossier, rejeu, chemin_api).appel(
        "GET", "/api/v1/meteo", params={"heure_depart": f"{JOUR}T09:00"}
    )


def _comparer_au_scenario_meteo(obtenu: dict[str, Any], tmp_path: Path) -> None:
    """Compare au scénario `meteo` de `api_meteo.json`, par la comparaison du filet."""
    import json

    scenario = json.loads((DOSSIER / "api_meteo.json").read_text(encoding="utf-8"))["meteo"]
    reference = tmp_path / "api_meteo_scenario.json"
    reference.write_text(serialiser(scenario), encoding="utf-8")
    comparer_a_la_reference(obtenu, reference, False, REGENERER)


def test_la_mutation_du_nouveau_chemin_rougit_la_reference_en_nouveau(
    tmp_path: Path, rejeu, meteo_faussee
):
    obtenu = _appel_meteo(tmp_path, rejeu, "nouveau")
    with pytest.raises(pytest.fail.Exception, match="changement de comportement"):
        _comparer_au_scenario_meteo(obtenu, tmp_path)


@pytest.mark.ecart_attendu
def test_la_mutation_du_nouveau_chemin_est_journalisee_en_double(
    tmp_path: Path, rejeu, meteo_faussee, caplog: pytest.LogCaptureFixture
):
    with caplog.at_level("WARNING", logger="ourouler.api.double_chemin"):
        obtenu = _appel_meteo(tmp_path, rejeu, "double")
    # L'ancien répond : la réponse reste celle de la référence…
    _comparer_au_scenario_meteo(obtenu, tmp_path)
    # … et l'écart est dit, en une ligne structurée, sans aucune valeur.
    lignes = [r.getMessage() for r in caplog.records if r.name == "ourouler.api.double_chemin"]
    assert len(lignes) == 1, lignes
    assert lignes[0].startswith("ecart_double_chemin {"), lignes[0]
    assert '"route": "meteo"' in lignes[0] and '"nature": "corps"' in lignes[0], lignes[0]
    assert VALEUR_FAUSSEE not in lignes[0], "une valeur de la réponse est sortie dans le journal"
