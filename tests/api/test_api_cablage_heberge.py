"""Câblage du cache météo mutualisé et des quotas en mode hébergé (lot L9.3).

Deux choses que `tests/api/test_api_quotas.py` et `tests/test_meteo_cache_previsions.py`
ne peuvent pas prouver, parce qu'ils construisent l'application avec
`creer_application(...)` et injectent tout à la main : que la fabrique de
**service**, `application()` (celle que lit vraiment `deploiement/api/entrypoint.py`
et `ourouler api`), branche elle-même le cache et les deux quotas quand le
mode est hébergé, et lit leurs plafonds dans `service.toml` — via
`api/exploitation.py`, sans jamais toucher au réseau ni au vrai
`~/.config/ourouler` (`OUROULER_CONFIG`/`OUROULER_SERVICE` pointent tous
deux sous `tmp_path`).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ourouler.api import exploitation
from ourouler.api.quotas import (
    CONSULTATIONS_METEO_PAR_JOUR_DEFAUT,
    GENERATIONS_PAR_JOUR_DEFAUT,
)
from ourouler.noyau.erreurs import ErreurConfig


def _toml_de_serveur_heberge(tmp_path: Path) -> Path:
    """Même geste que `test_api_paquetage._toml_de_serveur_heberge` : aucune
    section perso pur, `[cache]` sous `tmp_path`."""
    fichier = tmp_path / "serveur.toml"
    fichier.write_text(f'[cache]\ndossier="{tmp_path / "cache"}"\n', encoding="utf-8")
    return fichier


def _service_toml(tmp_path: Path, contenu: str) -> Path:
    fichier = tmp_path / "service.toml"
    fichier.write_text(contenu, encoding="utf-8")
    return fichier


# --- application() branche le cache et les deux quotas en mode hébergé -----


def test_en_heberge_application_branche_le_cache_et_les_quotas(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OUROULER_MODE", "heberge")
    monkeypatch.setenv("OUROULER_CONFIG", str(_toml_de_serveur_heberge(tmp_path)))
    monkeypatch.setenv("OUROULER_DATABASE_URL", "postgres://personne@127.0.0.1:1/absente")
    monkeypatch.setenv(
        "OUROULER_SERVICE",
        str(
            _service_toml(
                tmp_path,
                "[quotas]\ngenerations_par_jour = 5\nconsultations_meteo_par_jour = 7\n",
            )
        ),
    )
    from ourouler.api.application import application
    from ourouler.meteo.cache_previsions import ClientOpenMeteoCache

    ctx = application().state.ourouler

    assert isinstance(ctx.clients.meteo, ClientOpenMeteoCache), (
        "en mode hébergé, le connecteur météo doit être le cache mutualisé"
    )
    assert ctx.quotas.plafond == 5
    assert ctx.quotas_meteo.plafond == 7
    assert ctx.quotas_meteo.libelle == "consultations météo"


def test_en_heberge_sans_service_toml_les_defauts_s_appliquent(tmp_path: Path, monkeypatch):
    """`service.toml` absent : le cache et les deux quotas existent quand même, à leur défaut."""
    monkeypatch.setenv("OUROULER_MODE", "heberge")
    monkeypatch.setenv("OUROULER_CONFIG", str(_toml_de_serveur_heberge(tmp_path)))
    monkeypatch.setenv("OUROULER_DATABASE_URL", "postgres://personne@127.0.0.1:1/absente")
    monkeypatch.setenv("OUROULER_SERVICE", str(tmp_path / "n-existe-pas.toml"))
    from ourouler.api.application import application
    from ourouler.meteo.cache_previsions import ClientOpenMeteoCache

    ctx = application().state.ourouler

    assert isinstance(ctx.clients.meteo, ClientOpenMeteoCache)
    assert ctx.quotas.plafond == GENERATIONS_PAR_JOUR_DEFAUT
    assert ctx.quotas_meteo.plafond == CONSULTATIONS_METEO_PAR_JOUR_DEFAUT


def test_en_personnel_ni_cache_ni_quota_n_est_branche(tmp_path: Path, monkeypatch):
    """La contre-épreuve : en mode personnel, le cœur fabrique son propre client, comme avant L9.3."""
    monkeypatch.setenv("OUROULER_MODE", "personnel")
    fichier = tmp_path / "serveur.toml"
    fichier.write_text(
        '[depart]\nnom="Nulle part"\nlatitude=1.0\nlongitude=2.0\n[cycliste]\nmasse_kg=75\nftp_w=250\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("OUROULER_CONFIG", str(fichier))
    from ourouler.api.application import application
    from ourouler.meteo.cache_previsions import ClientOpenMeteoCache

    ctx = application().state.ourouler

    assert ctx.clients.meteo is None, "le mode personnel n'a pas de cache mutualisé"
    assert not isinstance(ctx.clients.meteo, ClientOpenMeteoCache)
    assert ctx.quotas.plafond == GENERATIONS_PAR_JOUR_DEFAUT  # posé, mais jamais consulté
    assert ctx.quotas_meteo.plafond == CONSULTATIONS_METEO_PAR_JOUR_DEFAUT


# --- lecture des plafonds par api/exploitation.py ---------------------------


def test_generations_par_jour_absente_vaut_le_defaut(tmp_path: Path):
    environ = {"OUROULER_SERVICE": str(tmp_path / "n-existe-pas.toml")}
    assert exploitation.generations_par_jour(environ) == GENERATIONS_PAR_JOUR_DEFAUT


def test_generations_par_jour_sans_section_quotas_vaut_le_defaut(tmp_path: Path):
    chemin = _service_toml(tmp_path, '[brevo]\nserveur = "exemple.test"\n')
    environ = {"OUROULER_SERVICE": str(chemin)}
    assert exploitation.generations_par_jour(environ) == GENERATIONS_PAR_JOUR_DEFAUT


def test_generations_par_jour_invalide_refuse(tmp_path: Path):
    chemin = _service_toml(tmp_path, '[quotas]\ngenerations_par_jour = "beaucoup"\n')
    environ = {"OUROULER_SERVICE": str(chemin)}
    with pytest.raises(ErreurConfig, match="generations_par_jour"):
        exploitation.generations_par_jour(environ)


def test_generations_par_jour_booleen_refuse(tmp_path: Path):
    """`True` est un `int` en Python : sans garde, `generations_par_jour = true`
    deviendrait un plafond de 1 au lieu d'un TOML manifestement mal écrit."""
    chemin = _service_toml(tmp_path, "[quotas]\ngenerations_par_jour = true\n")
    environ = {"OUROULER_SERVICE": str(chemin)}
    with pytest.raises(ErreurConfig, match="generations_par_jour"):
        exploitation.generations_par_jour(environ)


@pytest.mark.parametrize("valeur", [0, -1, -100])
def test_generations_par_jour_sous_un_refuse(tmp_path: Path, valeur: int):
    chemin = _service_toml(tmp_path, f"[quotas]\ngenerations_par_jour = {valeur}\n")
    environ = {"OUROULER_SERVICE": str(chemin)}
    with pytest.raises(ErreurConfig, match="au moins 1"):
        exploitation.generations_par_jour(environ)


def test_consultations_meteo_par_jour_absente_vaut_le_defaut(tmp_path: Path):
    environ = {"OUROULER_SERVICE": str(tmp_path / "n-existe-pas.toml")}
    assert exploitation.consultations_meteo_par_jour(environ) == CONSULTATIONS_METEO_PAR_JOUR_DEFAUT


def test_consultations_meteo_par_jour_invalide_refuse(tmp_path: Path):
    chemin = _service_toml(tmp_path, '[quotas]\nconsultations_meteo_par_jour = "beaucoup"\n')
    environ = {"OUROULER_SERVICE": str(chemin)}
    with pytest.raises(ErreurConfig, match="consultations_meteo_par_jour"):
        exploitation.consultations_meteo_par_jour(environ)


@pytest.mark.parametrize("valeur", [0, -5])
def test_consultations_meteo_par_jour_sous_un_refuse(tmp_path: Path, valeur: int):
    chemin = _service_toml(tmp_path, f"[quotas]\nconsultations_meteo_par_jour = {valeur}\n")
    environ = {"OUROULER_SERVICE": str(chemin)}
    with pytest.raises(ErreurConfig, match="au moins 1"):
        exploitation.consultations_meteo_par_jour(environ)


def test_les_deux_plafonds_cohabitent_dans_le_meme_fichier(tmp_path: Path):
    chemin = _service_toml(tmp_path, "[quotas]\ngenerations_par_jour = 3\nconsultations_meteo_par_jour = 9\n")
    environ = {"OUROULER_SERVICE": str(chemin)}
    assert exploitation.generations_par_jour(environ) == 3
    assert exploitation.consultations_meteo_par_jour(environ) == 9


# --- sprint 12 : [admin] et [demandes] ----------------------------------------


def test_parametres_admin_absente_vaut_none(tmp_path: Path):
    environ = {"OUROULER_SERVICE": str(tmp_path / "n-existe-pas.toml")}
    assert exploitation.parametres_admin(environ) is None


def test_parametres_admin_incomplete_vaut_none(tmp_path: Path):
    chemin = _service_toml(tmp_path, '[admin]\nidentifiant = "amiel"\n')  # secret manquant
    environ = {"OUROULER_SERVICE": str(chemin)}
    assert exploitation.parametres_admin(environ) is None


def test_parametres_admin_complete_est_rendue(tmp_path: Path):
    chemin = _service_toml(tmp_path, '[admin]\nidentifiant = "amiel"\nsecret = "un-secret"\n')
    environ = {"OUROULER_SERVICE": str(chemin)}
    parametres = exploitation.parametres_admin(environ)
    assert parametres is not None
    assert parametres.identifiant == "amiel"
    assert parametres.secret == "un-secret"
    assert "un-secret" not in repr(parametres)  # le repr masque le secret


def test_port_admin_absente_vaut_le_defaut(tmp_path: Path):
    from ourouler.api.admin import PORT_ADMIN_DEFAUT

    environ = {"OUROULER_SERVICE": str(tmp_path / "n-existe-pas.toml")}
    assert exploitation.port_admin(environ) == PORT_ADMIN_DEFAUT


def test_port_admin_lue_dans_le_fichier(tmp_path: Path):
    chemin = _service_toml(tmp_path, "[admin]\nport = 9123\n")
    environ = {"OUROULER_SERVICE": str(chemin)}
    assert exploitation.port_admin(environ) == 9123


def test_port_admin_invalide_refuse(tmp_path: Path):
    chemin = _service_toml(tmp_path, '[admin]\nport = "beaucoup"\n')
    environ = {"OUROULER_SERVICE": str(chemin)}
    with pytest.raises(ErreurConfig, match="port"):
        exploitation.port_admin(environ)


def test_adresse_alerte_demandes_absente_vaut_none(tmp_path: Path):
    environ = {"OUROULER_SERVICE": str(tmp_path / "n-existe-pas.toml")}
    assert exploitation.adresse_alerte_demandes(environ) is None


def test_adresse_alerte_demandes_lue_dans_le_fichier(tmp_path: Path):
    chemin = _service_toml(tmp_path, '[demandes]\nalerte_destinataire = "mainteneur@exemple.invalid"\n')
    environ = {"OUROULER_SERVICE": str(chemin)}
    assert exploitation.adresse_alerte_demandes(environ) == "mainteneur@exemple.invalid"


def test_parametres_brevo_service_absente_vaut_none(tmp_path: Path):
    environ = {"OUROULER_SERVICE": str(tmp_path / "n-existe-pas.toml")}
    assert exploitation.parametres_brevo_service(environ) is None


def test_parametres_brevo_service_incomplete_vaut_none_sans_lever(tmp_path: Path):
    """Contrairement à `ourouler inviter`, ce lecteur ne doit jamais lever : une section
    [brevo] incomplète signifie « pas d'alerte », jamais un refus de démarrage de la route
    publique de demande d'invitation."""
    chemin = _service_toml(tmp_path, '[brevo]\nserveur = "exemple.invalid"\n')  # incomplète
    environ = {"OUROULER_SERVICE": str(chemin)}
    assert exploitation.parametres_brevo_service(environ) is None


def test_parametres_brevo_service_complete_est_rendue(tmp_path: Path):
    chemin = _service_toml(
        tmp_path,
        '[brevo]\nserveur = "smtp.exemple.invalid"\nport = 587\nutilisateur = "u"\n'
        'mot_de_passe = "p"\nexpediteur = "e@exemple.invalid"\nnom_expediteur = "où rouler"\n',
    )
    environ = {"OUROULER_SERVICE": str(chemin)}
    parametres = exploitation.parametres_brevo_service(environ)
    assert parametres is not None
    assert parametres.serveur == "smtp.exemple.invalid"
