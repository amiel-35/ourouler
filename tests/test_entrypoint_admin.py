"""`deploiement/api/entrypoint.py` : l'administration ne doit jamais écouter ailleurs
que sur 127.0.0.1, même lancée en arrière-plan par l'entrypoint du conteneur.

Ce script vit **hors** de `src/ourouler/` (c'est la couche d'exploitation du
paquetage, pas le cœur) : il est importé ici par son chemin de fichier,
comme n'importe quel script qu'on veut tester sans en faire un paquet.

Ce test ne touche ni fichier ni réseau réels : `base_de_donnees.ouvrir` et
`services.demandes.purger_demandes_perimees` sont bouchonnés (la purge au
démarrage a son test dédié, contre une vraie base, dans
`tests/comptes/test_demandes_invitation.py`), et les lecteurs de
`service.toml` sont remplacés par des valeurs fixes — rien de tout cela
n'a besoin d'un vrai fichier ni d'une vraie base pour vérifier **où**
uvicorn se met à écouter.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

CHEMIN_ENTRYPOINT = Path(__file__).resolve().parents[1] / "deploiement" / "api" / "entrypoint.py"


def _charger_entrypoint():
    """Importe `entrypoint.py` par son chemin — il n'appartient à aucun paquet."""
    spec = importlib.util.spec_from_file_location("ourouler_entrypoint_test", CHEMIN_ENTRYPOINT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def entrypoint():
    module = _charger_entrypoint()
    yield module
    sys.modules.pop("ourouler_entrypoint_test", None)


class _ConnexionBouchon:
    """Un `with base_de_donnees.ouvrir(...)` qui ne touche à aucune vraie base."""

    def __enter__(self):
        return self

    def __exit__(self, *exc: object) -> bool:
        return False


def _app_bouchon():
    """Une application FastAPI factice : juste assez de `state.ourouler` pour que
    `_lancer_administration_en_arriere_plan` construise ses quotas."""
    quota = SimpleNamespace(plafond=1)
    contexte = SimpleNamespace(
        quotas=quota, quotas_meteo=quota, quotas_calibration=quota, quotas_import=quota
    )
    return SimpleNamespace(state=SimpleNamespace(ourouler=contexte))


def test_administration_absente_sans_section_admin(entrypoint, monkeypatch: pytest.MonkeyPatch):
    """Sans `[admin]`, rien n'est lancé — pas d'appel à `uvicorn.Config`."""
    from ourouler.api import exploitation

    monkeypatch.setattr(exploitation, "parametres_admin", lambda: None)
    appele = []
    monkeypatch.setattr("uvicorn.Config", lambda *a, **k: appele.append((a, k)))

    entrypoint._lancer_administration_en_arriere_plan(_app_bouchon())

    assert appele == []


def test_administration_ecoute_toujours_sur_127_0_0_1(entrypoint, monkeypatch: pytest.MonkeyPatch):
    """`[admin]` posée : l'administration démarre, et **uvicorn.Config** ne reçoit
    jamais un autre hôte que `127.0.0.1` — jamais `0.0.0.0`, jamais un nom de domaine."""
    from ourouler.api import base_de_donnees, exploitation
    from ourouler.api.exploitation import ParametresAdmin
    from ourouler.services import demandes as service_demandes

    monkeypatch.setattr(
        exploitation, "parametres_admin", lambda: ParametresAdmin(identifiant="amiel", secret="un-secret")
    )
    monkeypatch.setattr(exploitation, "url_base_de_donnees", lambda: "postgresql://exemple.invalid/db")
    monkeypatch.setattr(exploitation, "parametres_brevo_service", lambda: None)
    monkeypatch.setattr(exploitation, "port_admin", lambda: 8001)
    monkeypatch.setenv("OUROULER_URL_PUBLIQUE", "https://exemple.invalid")
    monkeypatch.setattr(base_de_donnees, "ouvrir", lambda url: _ConnexionBouchon())
    monkeypatch.setattr(service_demandes, "purger_demandes_perimees", lambda **_k: 0)

    configs: list[dict] = []

    class _ServeurBouchon:
        def __init__(self, config):
            configs.append(config)

        def run(self) -> None:
            return None

    monkeypatch.setattr("uvicorn.Config", lambda app, **kwargs: {"app": app, **kwargs})
    monkeypatch.setattr("uvicorn.Server", _ServeurBouchon)

    entrypoint._lancer_administration_en_arriere_plan(_app_bouchon())

    assert len(configs) == 1
    assert configs[0]["host"] == "127.0.0.1"
    assert configs[0]["host"] != "0.0.0.0"
    assert configs[0]["port"] == 8001


def test_api_publique_active_le_transfert_des_en_tetes_de_proxy(entrypoint):
    """`main()` doit passer `proxy_headers=True, forwarded_allow_ips="*"` à `uvicorn.run` —
    sans ça, `Request.client.host` verrait toujours l'IP de Traefik, jamais celle du
    visiteur, et le débit par adresse IP du formulaire public fermerait la porte à tout
    le monde en même temps (voir `api/routes/demandes.py`).

    Lu directement dans le code source du script plutôt que rejoué (`main()` a
    d'autres effets de bord — écrire des fichiers, démarrer un vrai serveur — qu'un
    test unitaire ne doit pas déclencher) : ce test échoue si quelqu'un retire un
    jour ces deux arguments sans le remarquer.
    """
    source = CHEMIN_ENTRYPOINT.read_text(encoding="utf-8")
    assert "proxy_headers=True" in source
    assert 'forwarded_allow_ips="*"' in source


def test_le_demarrage_applique_les_migrations_puis_survit_a_une_panne_de_l_admin(
    entrypoint, monkeypatch: pytest.MonkeyPatch
):
    """Les migrations passent avant tout, et une administration qui échoue
    n'emporte pas l'API (constaté en préproduction le 28/09/2026 : une table
    absente faisait redémarrer le conteneur en boucle)."""
    import uvicorn

    ordre: list[str] = []
    monkeypatch.setattr(entrypoint, "_ecrire_config_depuis_environnement", lambda: None)
    monkeypatch.setattr(entrypoint, "_ecrire_service_depuis_environnement", lambda: None)
    monkeypatch.setattr("ourouler.api.application.application", lambda: _app_bouchon())
    monkeypatch.setattr(entrypoint, "_appliquer_migrations", lambda: ordre.append("migrations"))

    def admin_en_panne(app):
        ordre.append("admin")
        raise RuntimeError("table absente")

    monkeypatch.setattr(entrypoint, "_lancer_administration_en_arriere_plan", admin_en_panne)
    monkeypatch.setattr(uvicorn, "run", lambda *a, **k: ordre.append("api"))

    entrypoint.main()

    assert ordre == ["migrations", "admin", "api"]


def test_les_migrations_se_posent_sur_la_base_de_l_environnement(entrypoint, monkeypatch: pytest.MonkeyPatch):
    from ourouler.api import base_de_donnees

    vues: list[str] = []
    monkeypatch.setenv("OUROULER_DATABASE_URL", "postgresql://base-de-test")
    monkeypatch.setattr(base_de_donnees, "ouvrir", lambda url: vues.append(url) or _ConnexionBouchon())
    monkeypatch.setattr(base_de_donnees, "appliquer_migrations", lambda cx: ["0003_demandes_invitation.sql"])

    entrypoint._appliquer_migrations()

    assert vues == ["postgresql://base-de-test"]


def test_sans_base_aucune_migration(entrypoint, monkeypatch: pytest.MonkeyPatch):
    from ourouler.api import base_de_donnees

    monkeypatch.delenv("OUROULER_DATABASE_URL", raising=False)
    monkeypatch.setattr(base_de_donnees, "ouvrir", lambda url: pytest.fail("aucune base à ouvrir"))

    entrypoint._appliquer_migrations()
