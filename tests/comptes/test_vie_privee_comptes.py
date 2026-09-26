"""RGPD et comptes : `DELETE /moi` ferme aussi le compte, pas seulement les données.

`tests/api/test_api_vie_privee.py` prouve déjà l'effacement du profil, des
fichiers, du cache et du journal — contre le service réel, mais avec
`SessionDEssai` (un fournisseur de session **de test**, sans base de comptes,
`x-essai-proprietaire` en en-tête). Ce que ce fichier-ci ajoute est ce que
`SessionDEssai` ne peut pas éprouver : un **vrai** compte, une **vraie**
invitation, une **vraie** session par cookie (`api/comptes.py`,
`api/session.py`, `migrations/0001_comptes.sql`, `migrations/0002_sessions.sql`)
— et la preuve que `DELETE /moi` referme cette porte-là aussi. Avant ce lot,
`comptes_proprietaires` existait déjà mais `effacer_donnees` ne la regardait
jamais : un compte « supprimé » restait pleinement utilisable après coup.

**Pourquoi ici et pas dans `tests/api/`.** `tests/api/conftest.py` coupe toute
connexion réseau pour son dossier (règle absolue 3, appliquée aux bouchons) ;
ces tests-ci ont besoin de l'inverse, une vraie connexion TCP vers le
PostgreSQL jetable de `tests/comptes/conftest.py`, qui explique pourquoi une
base locale ne l'enfreint pas (« la règle refuse Internet, pas la boucle
locale »). Même choix, même raison, que `tests/comptes/test_routes_session.py`.

**Sans client de test partagé avec `tests/api/`**, pour la même raison que
`test_routes_session.py` : un petit client ASGI local (`_requete`), au lieu
d'un import inter-dossiers qui rouvrirait la coupure réseau pour ce dossier.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
from test_apprentissage_routes import LUNDI, droite

from ourouler.api import vie_privee
from ourouler.api.application import creer_application
from ourouler.api.base_de_donnees import ouvrir
from ourouler.api.comptes import DepotComptes
from ourouler.api.depots import SocleTOML
from ourouler.api.proprietaire import Proprietaire
from ourouler.api.session import NOM_COOKIE, SessionParCookie
from ourouler.apprentissage.commande import NOM_BASE
from ourouler.apprentissage.routes import BaseRoutes

PREFIXE = "/api/v1"

#: Même mot de passe partout dans ce dossier — voir `test_routes_session.py`.
MOT_DE_PASSE = "brique-oseille-grelot-marmotte"

#: L'adresse synthétique de ce fichier (règle absolue 1 : aucune donnée réelle).
COURRIEL = "rgpd-compte@exemple.invalid"

#: La sentinelle plantée dans le profil et le nom du fichier déposé — repérable
#: à l'œil nu, ni nom réel ni coordonnée (règle absolue 1).
MARQUE = "sentinelle-rgpd-compte-4q8"


def _toml_minimal(tmp_path: Path) -> str:
    """Le fond commun du serveur : juste de quoi valider une `Config`.

    Départ au large du golfe de Guinée (aucune coordonnée française), et un
    `[cache]` qui pointe **dans `tmp_path`** — sans lui, `Config.cache.dossier`
    retombe sur le défaut de la machine, ce que la règle absolue 1 interdit
    même en test.
    """
    return (
        "[depart]\n"
        'nom = "Départ d\'essai"\n'
        "latitude = 0.0009\nlongitude = 0.0004\n"
        "\n[cycliste]\nmasse_kg = 70.0\nftp_w = 200\n"
        f'\n[cache]\ndossier = "{tmp_path / "cache"}"\n'
    )


def _app(url_base: str, tmp_path: Path):
    """L'application réelle, avec une vraie base de comptes (`SessionParCookie`).

    Aucun client externe injecté : ce fichier ne seme ni boucle ni sortie
    (déjà couvertes par `_planter` dans `tests/api/`), seulement un profil,
    un fichier et une entrée de journal — de quoi prouver que `DELETE /moi`
    les vide comme avant ce lot, en plus de fermer le compte.
    """
    chemin = tmp_path / "config.toml"
    chemin.write_text(_toml_minimal(tmp_path), encoding="utf-8")
    return creer_application(
        socle=SocleTOML(chemin, proprietaire=None),
        dossier_donnees=tmp_path / "donnees",
        session=SessionParCookie(url_base),
    )


def _requete(
    app, methode: str, chemin: str, *, cookies: dict[str, str] | None = None, **kwargs
) -> httpx.Response:
    """Un appel HTTP synchrone contre l'application ASGI — voir `test_routes_session.py`."""

    async def _aller() -> httpx.Response:
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://api.test", cookies=cookies
        ) as client:
            return await client.request(methode, chemin, **kwargs)

    return asyncio.run(_aller())


class _RequeteAvecCookies:
    """Juste assez pour `SessionParCookie.ouvrir` : un attribut `cookies`."""

    def __init__(self, cookies: dict[str, str]) -> None:
        self.cookies = cookies


def _zwo(nom: str) -> bytes:
    """Un `.ZWO` minimal et valide, dont le nom porte la sentinelle."""
    return (
        "<?xml version='1.0'?>\n<workout_file>\n"
        f"<name>{nom}</name>\n<description>Fabriquée pour les tests</description>\n"
        '<workout><SteadyState Duration="600" Power="0.7"/></workout>\n'
        "</workout_file>\n"
    ).encode()


def _entrer(app, jeton: str) -> tuple[str, dict[str, str]]:
    """Active l'invitation, ouvre la session, rend (proprietaire, cookies)."""
    reponse = _requete(
        app, "POST", f"{PREFIXE}/entrer", json={"jeton": jeton, "secret": MOT_DE_PASSE}
    )
    assert reponse.status_code == 200, reponse.text
    proprietaire = reponse.json()["donnees"]["proprietaire"]
    jeton_session = reponse.cookies.get(NOM_COOKIE)
    assert jeton_session, "aucun cookie de session posé par /entrer"
    return proprietaire, {NOM_COOKIE: jeton_session}


def test_supprimer_mes_donnees_ferme_le_compte_et_revoque_la_session(url_base, tmp_path):
    """Le test de bout en bout : un vrai compte, invité puis activé, effacé pour de vrai.

    Ordre du test, et il compte (le piège déjà rencontré une fois dans ce
    sprint, voir `tests/api/test_api_vie_privee.py`) : on prouve d'abord que
    profil, fichier, journal et routes apprises **existent**, puis qu'après
    `DELETE /moi` (a) profil/fichiers/journal ont disparu, (b) le mot de passe
    et le cookie de la session déjà ouverte ne rouvrent plus rien, et (d) les
    routes apprises n'ont pas bougé (doctrine §10.2, collectives).
    """
    with ouvrir(url_base) as cx:
        emise = DepotComptes(cx).inviter(COURRIEL)

    app = _app(url_base, tmp_path)
    proprietaire_id, cookies = _entrer(app, emise.jeton)
    qui = Proprietaire(proprietaire_id)

    # --- on plante un peu de profil, de fichier, et une entrée de journal ---

    profil = _requete(
        app,
        "PATCH",
        f"{PREFIXE}/profil",
        cookies=cookies,
        json={
            "depart": {"nom": f"depart-{MARQUE}"},
            "velos": [
                {"nom": f"velo-{MARQUE}", "usage": "route", "masse_kg": 9.0, "cda_m2": 0.3}
            ],
        },
    )
    assert profil.status_code == 200, f"le profil n'a pas pu s'écrire : {profil.text[:300]}"

    depot_fichier = _requete(
        app,
        "POST",
        f"{PREFIXE}/seances/fichier",
        cookies=cookies,
        files={"fichier": (f"seance-{MARQUE}.zwo", _zwo(MARQUE), "application/xml")},
    )
    assert depot_fichier.status_code == 200, (
        f"le fichier n'a pas pu se déposer : {depot_fichier.text[:300]}"
    )
    id_fichier = depot_fichier.json()["fichier"]["id"]

    # Pas de route qui écrit le journal sans un service externe bouchonné
    # (`GET /seances`, `POST /sorties`…) — déjà couvert côté profil/fichier
    # par ce test-ci, et côté services par `tests/api/test_api_isolation_proprietaire.py`.
    # On pose donc l'entrée directement sur le même dépôt que la route
    # utilise vraiment (`app.state.ourouler.journal`), pas un double.
    journal = app.state.ourouler.journal
    journal.noter_succes(qui, "openmeteo", "intervals", "brouter")
    assert journal.tout(qui), "le semis du journal n'a pas pris : le test ne prouverait rien"

    # Les routes apprises : jamais exposées en écriture par l'API, donc
    # plantées directement sur le dépôt, comme le fait déjà
    # `tests/api/test_api_vie_privee.py` pour la même raison.
    chemin_base = tmp_path / "cache" / NOM_BASE
    base = BaseRoutes(chemin_base, proprietaire=proprietaire_id)
    base.ajouter_trace(droite(5), jour=LUNDI, id_sortie="sortie-rgpd-compte")
    assert base.troncons(), "le semis des routes apprises n'a pas pris"
    assert base.sorties()

    # --- la donnée était bien là avant qu'on l'efface ---

    avant_profil = _requete(app, "GET", f"{PREFIXE}/profil", cookies=cookies)
    assert MARQUE in avant_profil.text, "le semis du profil n'a pas pris"
    avant_fichier = _requete(app, "GET", f"{PREFIXE}/fichiers/{id_fichier}", cookies=cookies)
    assert avant_fichier.status_code == 200

    with ouvrir(url_base) as cx:
        compte_avant = cx.execute(
            "SELECT compte FROM comptes_proprietaires WHERE proprietaire = %s",
            (proprietaire_id,),
        ).fetchone()
    assert compte_avant is not None, "aucun compte rattaché : le test ne prouverait rien"

    # --- l'effacement ---

    suppression = _requete(app, "DELETE", f"{PREFIXE}/moi", cookies=cookies)
    assert suppression.status_code == 200, suppression.text
    supprime = suppression.json()["donnees"]["supprime"]
    assert supprime["profil"] is True
    assert supprime["fichiers"] >= 1
    assert supprime["journal_services"] is True
    assert supprime["compte"] is True, (
        "« compte » doit apparaître et valoir vrai : c'est le trou que ce lot ferme"
    )

    # --- (a) profil, fichiers, journal sont vidés comme avant ce lot ---
    #
    # Vérifié **au dépôt**, pas par une nouvelle requête HTTP : la session
    # utilisée pour poser les données vient d'être révoquée par la cascade
    # (voir (b) ci-dessous), donc plus aucune requête authentifiée ne peut
    # relire l'état de ce propriétaire — ce qui est précisément ce que (b)
    # prouve. C'est la même contrainte que `tests/api/test_api_vie_privee.py`
    # rencontre déjà pour le cache et les routes apprises, qu'aucune route ne
    # sert : ici la route existe, mais son accès a disparu avec le compte.
    ourouler_ctx = app.state.ourouler
    assert ourouler_ctx.profils.surcharge(qui) == {}, "le profil de A survit à sa suppression"
    assert ourouler_ctx.fichiers.lister(qui) == [], "des fichiers de A survivent"
    assert ourouler_ctx.journal.tout(qui) == {}, "le journal de A survit à sa suppression"

    # --- (b) le mot de passe et la session déjà ouverte ne rouvrent plus rien ---

    connexion_refusee = _requete(
        app,
        "POST",
        f"{PREFIXE}/connexion",
        json={"email": COURRIEL, "secret": MOT_DE_PASSE},
    )
    assert connexion_refusee.status_code == 401, connexion_refusee.text
    assert connexion_refusee.json()["erreur"]["code"] == "identifiants_refuses"

    apres_profil = _requete(app, "GET", f"{PREFIXE}/profil", cookies=cookies)
    assert apres_profil.status_code == 401, (
        "le cookie de la session ouverte avant la suppression rouvre encore une route : "
        f"{apres_profil.status_code} {apres_profil.text[:200]}"
    )
    assert apres_profil.json()["erreur"]["code"] == "session_absente"

    fournisseur = SessionParCookie(url_base)
    assert fournisseur.ouvrir(_RequeteAvecCookies(cookies)) is None, (
        "le cookie retrouve encore un propriétaire après la suppression du compte"
    )

    with ouvrir(url_base) as cx:
        compte_apres = cx.execute(
            "SELECT compte FROM comptes_proprietaires WHERE proprietaire = %s",
            (proprietaire_id,),
        ).fetchone()
        sessions_restantes = cx.execute(
            "SELECT count(*) FROM sessions WHERE jeton = %s", (cookies[NOM_COOKIE],)
        ).fetchone()[0]
    assert compte_apres is None, "la correspondance compte/propriétaire survit à la suppression"
    assert sessions_restantes == 0, "la session de A survit en base à sa propre suppression"

    # --- (c) rappeler l'effacement une seconde fois ne casse rien ---
    #
    # Impossible de rejouer **le même appel HTTP** : la session qui
    # authentifiait la première requête n'existe plus, et c'est justement ce
    # que (b) vient de prouver — il n'y a plus de porte par laquelle
    # ré-appeler `DELETE /moi` pour ce propriétaire. L'idempotence s'éprouve
    # donc là où `effacer_donnees` et `DepotComptes.supprimer_compte_du_proprietaire`
    # vivent réellement : rappelés directement sur le même propriétaire, ils
    # ne doivent lever aucune exception et ne plus rien trouver à effacer.
    with ouvrir(url_base) as cx:
        depot = DepotComptes(cx)
        assert depot.supprimer_compte_du_proprietaire(qui) is False, (
            "un second effacement du compte devrait rendre faux — rien à effacer"
        )
        rejoue = vie_privee.effacer_donnees(
            qui,
            profils=ourouler_ctx.profils,
            fichiers=ourouler_ctx.fichiers,
            journal=ourouler_ctx.journal,
            generations=ourouler_ctx.generations,
            dossier_cache=tmp_path / "cache",
            comptes=depot,
        )
    assert rejoue["supprime"] == {
        "profil": False,
        "calibration": False,
        "journal_services": False,
        "fichiers": 0,
        "activites": 0,
        "generations_en_memoire": 0,
        "compte": False,
    }

    # --- (d) les routes apprises restent intactes : elles sont collectives ---

    apres_routes = BaseRoutes(chemin_base, proprietaire=proprietaire_id)
    assert apres_routes.troncons(), "les tronçons de A ont disparu à la suppression du compte"
    assert apres_routes.sorties(), "les sorties de A ont disparu à la suppression du compte"
