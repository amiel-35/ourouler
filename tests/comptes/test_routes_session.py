"""Les quatre routes de session, contre le **service réel** (lot L7.2-C).

`test_sessions.py` prouve les propriétés au niveau du dépôt ; ce fichier
rejoue les mêmes propriétés par HTTP, à travers `creer_application`, les
routes de `api/routes.py` et un **vrai** PostgreSQL en conteneur — pas un
bouchon. C'est la différence entre « le dépôt isole bien » et « le fil qui va
du cookie du navigateur au dépôt isole bien », et [[Q58]] est justement une
fuite qui vivait dans ce second fil, pas dans le premier.

**Sans client de test partagé avec `tests/api/`** : `tests/api/conftest.py`
coupe toute connexion réseau pour son dossier (règle absolue 3 appliquée aux
bouchons), et ces tests-ci ont besoin de l'inverse — une vraie connexion TCP
vers le PostgreSQL jetable de `tests/comptes/conftest.py`. D'où un petit
client ASGI local plutôt qu'un import inter-dossiers, que ce dépôt évite déjà
ailleurs pour la même raison (`outils_api.py`, note de module).
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import httpx
import pytest

pytest.importorskip("fastapi", reason="extra « api » absent — uv sync --all-extras")

from ourouler.api.application import creer_application  # noqa: E402
from ourouler.api.base_de_donnees import ouvrir  # noqa: E402
from ourouler.api.comptes import DepotComptes  # noqa: E402
from ourouler.api.depots import SocleVide  # noqa: E402
from ourouler.api.session import (  # noqa: E402
    NOM_COOKIE,
    SessionHebergee,
    SessionParCookie,
    SessionPersonnelle,
)

PREFIXE = "/api/v1"

#: Même mot de passe partout, choisi comme dans les autres fichiers du dossier.
MOT_DE_PASSE = "grenat-poulie-silex-marmotte"


def _app(url_base: str, tmp_path):
    return creer_application(
        socle=SocleVide(),
        dossier_donnees=tmp_path / "donnees",
        session=SessionParCookie(url_base),
    )


def requete(
    app, methode: str, chemin: str, *, cookies: dict[str, str] | None = None, **kwargs
) -> httpx.Response:
    """Un appel HTTP synchrone contre l'application ASGI, sans jamais toucher un socket réel.

    `cookies` se pose sur le **client**, pas sur la requête : httpx déprécie
    la seconde forme (persistance ambiguë), et un client neuf à chaque appel
    garde de toute façon chaque appel isolé des autres — pas de jar partagé
    d'un test à l'autre.
    """

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


# --- GET /invitation : indistinguable, les trois cas ---------------------------


def test_get_invitation_rend_l_adresse_et_l_echeance_d_un_jeton_valide(url_base, tmp_path):
    with ouvrir(url_base) as cx:
        emise = DepotComptes(cx).inviter("get-invitation@exemple.invalid")

    reponse = requete(
        _app(url_base, tmp_path), "GET", f"{PREFIXE}/invitation", params={"jeton": emise.jeton}
    )

    assert reponse.status_code == 200, reponse.text
    donnees = reponse.json()["donnees"]
    assert donnees["email"] == "get-invitation@exemple.invalid"


def test_get_invitation_rend_la_meme_reponse_pour_inconnu_expire_ou_consomme(url_base, tmp_path):
    with ouvrir(url_base) as cx:
        depot = DepotComptes(cx)
        depart = datetime(2026, 9, 1, tzinfo=UTC)
        expiree = depot.inviter(
            "expiree-route@exemple.invalid", duree=timedelta(days=1), maintenant=depart
        )
        consommee = depot.inviter("consommee-route@exemple.invalid")
        depot.activer(consommee.jeton, MOT_DE_PASSE)

    app = _app(url_base, tmp_path)
    reponses = {
        "inconnu": requete(app, "GET", f"{PREFIXE}/invitation", params={"jeton": "jeton-invente"}),
        "expire": requete(app, "GET", f"{PREFIXE}/invitation", params={"jeton": expiree.jeton}),
        "consomme": requete(app, "GET", f"{PREFIXE}/invitation", params={"jeton": consommee.jeton}),
    }
    for nom, reponse in reponses.items():
        assert reponse.status_code == 404, f"{nom} : {reponse.status_code} {reponse.text}"
        assert reponse.json()["erreur"]["code"] == "invitation_invalide", nom

    messages = {r.json()["erreur"]["message"] for r in reponses.values()}
    assert len(messages) == 1, f"les trois cas se distinguent par le message : {messages}"


# --- POST /entrer ---------------------------------------------------------------


def test_entrer_active_le_compte_ouvre_une_session_et_pose_le_cookie(url_base, tmp_path):
    with ouvrir(url_base) as cx:
        emise = DepotComptes(cx).inviter("entrer-route@exemple.invalid")

    app = _app(url_base, tmp_path)
    reponse = requete(
        app, "POST", f"{PREFIXE}/entrer", json={"jeton": emise.jeton, "secret": MOT_DE_PASSE}
    )

    assert reponse.status_code == 200, reponse.text
    proprietaire = reponse.json()["donnees"]["proprietaire"]
    assert proprietaire

    jeton_session = reponse.cookies.get(NOM_COOKIE)
    assert jeton_session, "aucun cookie de session posé"
    assert emise.jeton not in reponse.text, "le jeton d'invitation fuit dans le corps JSON"
    assert jeton_session not in reponse.text, "le jeton de session fuit dans le corps JSON"

    # Le cookie retrouve bien le même propriétaire — directement, sans repasser
    # par une route qui exigerait un profil complet.
    fournisseur = SessionParCookie(url_base)
    retrouve = fournisseur.ouvrir(_RequeteAvecCookies({NOM_COOKIE: jeton_session}))
    assert str(retrouve) == proprietaire


def test_deux_entrer_avec_le_meme_jeton_le_second_est_refuse(url_base, tmp_path):
    """Preuve **HTTP** de l'usage unique — la course elle-même est prouvée au dépôt."""
    with ouvrir(url_base) as cx:
        emise = DepotComptes(cx).inviter("rejoue-entrer@exemple.invalid")

    app = _app(url_base, tmp_path)
    corps = {"jeton": emise.jeton, "secret": MOT_DE_PASSE}
    premiere = requete(app, "POST", f"{PREFIXE}/entrer", json=corps)
    seconde = requete(app, "POST", f"{PREFIXE}/entrer", json=corps)

    assert premiere.status_code == 200, premiere.text
    assert seconde.status_code >= 400, seconde.text
    assert emise.jeton not in seconde.text


def test_entrer_avec_un_jeton_invente_est_refuse_proprement(url_base, tmp_path):
    reponse = requete(
        _app(url_base, tmp_path),
        "POST",
        f"{PREFIXE}/entrer",
        json={"jeton": "jeton-completement-invente", "secret": MOT_DE_PASSE},
    )
    assert 400 <= reponse.status_code < 500, reponse.text
    assert "jeton-completement-invente" not in reponse.text


def test_entrer_rend_la_meme_reponse_pour_inconnu_expire_ou_consomme(url_base, tmp_path):
    """Le miroir du test de `GET /invitation`, et il manquait.

    Fermer la fuite sur une route et la laisser ouverte sur l'autre ne ferme
    rien : qui tient un jeton périmé n'a qu'à basculer sur `POST /entrer` pour
    apprendre qu'il a bien été émis, et sa date exacte d'expiration. Relevé en
    relecture le 19/09/2026, sur du code dont les trois cas étaient déjà
    couverts côté `GET` — c'est la **couverture** qui était trouée, autant que
    le code.
    """
    with ouvrir(url_base) as cx:
        depot = DepotComptes(cx)
        expiree = depot.inviter(
            "expiree-entrer@exemple.invalid",
            duree=timedelta(days=1),
            maintenant=datetime(2026, 9, 1, tzinfo=UTC),
        )
        consommee = depot.inviter("consommee-entrer@exemple.invalid")
        depot.activer(consommee.jeton, MOT_DE_PASSE)

    app = _app(url_base, tmp_path)
    reponses = {
        "inconnu": requete(
            app, "POST", f"{PREFIXE}/entrer", json={"jeton": "jeton-invente", "secret": MOT_DE_PASSE}
        ),
        "expire": requete(
            app, "POST", f"{PREFIXE}/entrer", json={"jeton": expiree.jeton, "secret": MOT_DE_PASSE}
        ),
        "consomme": requete(
            app, "POST", f"{PREFIXE}/entrer", json={"jeton": consommee.jeton, "secret": MOT_DE_PASSE}
        ),
    }
    for nom, reponse in reponses.items():
        assert 400 <= reponse.status_code < 500, f"{nom} : {reponse.status_code} {reponse.text}"

    distinctifs = {
        (r.status_code, r.json()["erreur"]["code"], r.json()["erreur"]["message"])
        for r in reponses.values()
    }
    assert len(distinctifs) == 1, f"les trois cas se distinguent : {distinctifs}"

    # Et aucune date ne doit fuir par la bande.
    for nom, reponse in reponses.items():
        assert "2026" not in reponse.text, f"{nom} laisse passer une date : {reponse.text}"


def test_entrer_et_get_invitation_disent_exactement_la_meme_chose(url_base, tmp_path):
    """Deux routes, un seul message — sinon la comparaison des deux renseigne."""
    app = _app(url_base, tmp_path)
    par_get = requete(app, "GET", f"{PREFIXE}/invitation", params={"jeton": "jeton-invente"})
    par_post = requete(
        app, "POST", f"{PREFIXE}/entrer", json={"jeton": "jeton-invente", "secret": MOT_DE_PASSE}
    )
    assert par_get.json()["erreur"]["message"] == par_post.json()["erreur"]["message"]
    assert par_get.json()["erreur"]["code"] == par_post.json()["erreur"]["code"]


# --- POST /connexion : indistinguable ------------------------------------------


def test_connexion_ouvre_une_session_sur_un_compte_actif(url_base, tmp_path):
    with ouvrir(url_base) as cx:
        depot = DepotComptes(cx)
        emise = depot.inviter("connexion-route@exemple.invalid")
        depot.activer(emise.jeton, MOT_DE_PASSE)

    reponse = requete(
        _app(url_base, tmp_path),
        "POST",
        f"{PREFIXE}/connexion",
        json={"email": "connexion-route@exemple.invalid", "secret": MOT_DE_PASSE},
    )
    assert reponse.status_code == 200, reponse.text
    assert reponse.cookies.get(NOM_COOKIE)


def test_connexion_refuse_une_adresse_inconnue_et_un_mauvais_mot_de_passe_de_la_meme_facon(
    url_base, tmp_path
):
    with ouvrir(url_base) as cx:
        depot = DepotComptes(cx)
        emise = depot.inviter("connexion-refusee@exemple.invalid")
        depot.activer(emise.jeton, MOT_DE_PASSE)

    app = _app(url_base, tmp_path)
    inconnue = requete(
        app,
        "POST",
        f"{PREFIXE}/connexion",
        json={"email": "personne-nulle-part@exemple.invalid", "secret": MOT_DE_PASSE},
    )
    mauvais = requete(
        app,
        "POST",
        f"{PREFIXE}/connexion",
        json={"email": "connexion-refusee@exemple.invalid", "secret": "un-mauvais-mot-de-passe"},
    )

    for nom, reponse in (("inconnue", inconnue), ("mauvais mot de passe", mauvais)):
        assert reponse.status_code == 401, f"{nom} : {reponse.status_code} {reponse.text}"
        assert reponse.json()["erreur"]["code"] == "identifiants_refuses", nom
        assert not reponse.cookies.get(NOM_COOKIE), f"{nom} : un cookie a été posé malgré le refus"

    assert inconnue.json()["erreur"]["message"] == mauvais.json()["erreur"]["message"], (
        "les deux refus se distinguent par le message — un oracle pour qui cherche une "
        "adresse valide"
    )


# --- POST /sortir : le cookie devient inutilisable -----------------------------


def test_sortir_revoque_la_session_en_base_pas_seulement_le_cookie(url_base, tmp_path):
    """Le point qui compte : un cookie **copié** avant `sortir` ne doit plus rien ouvrir."""
    with ouvrir(url_base) as cx:
        emise = DepotComptes(cx).inviter("sortir-route@exemple.invalid")

    app = _app(url_base, tmp_path)
    entree = requete(
        app, "POST", f"{PREFIXE}/entrer", json={"jeton": emise.jeton, "secret": MOT_DE_PASSE}
    )
    jeton_session = entree.cookies.get(NOM_COOKIE)
    assert jeton_session

    sortie = requete(app, "POST", f"{PREFIXE}/sortir", cookies={NOM_COOKIE: jeton_session})
    assert sortie.status_code == 200, sortie.text

    # Le cookie que `sortir` a renvoyé n'ouvre plus rien...
    fournisseur = SessionParCookie(url_base)
    assert fournisseur.ouvrir(_RequeteAvecCookies({NOM_COOKIE: jeton_session})) is None
    # ... et ce n'est pas parce que le navigateur l'a oublié : la ligne n'existe
    # plus en base, un exemplaire **copié** du cookie avant `sortir` ne
    # marcherait pas non plus (même vérification, la copie n'a pas de vie
    # séparée puisque c'est la même chaîne).
    with ouvrir(url_base) as cx:
        restantes = cx.execute(
            "SELECT count(*) FROM sessions WHERE jeton = %s", (jeton_session,)
        ).fetchone()[0]
    assert restantes == 0


def test_sortir_sans_cookie_ou_avec_un_cookie_deja_mort_reussit_quand_meme(url_base, tmp_path):
    app = _app(url_base, tmp_path)
    assert requete(app, "POST", f"{PREFIXE}/sortir").status_code == 200
    assert (
        requete(
            app, "POST", f"{PREFIXE}/sortir", cookies={NOM_COOKIE: "jeton-invente"}
        ).status_code
        == 200
    )


# --- le mode personnel et l'hébergé sans base restent hors jeu -----------------


def test_les_routes_de_session_refusent_proprement_sans_base_de_comptes(tmp_path):
    """Mode hébergé, mais sans `OUROULER_DATABASE_URL` : `SessionHebergee`, pas de comptes."""
    app = creer_application(
        socle=SocleVide(), dossier_donnees=tmp_path / "donnees", session=SessionHebergee()
    )
    reponse = requete(app, "GET", f"{PREFIXE}/invitation", params={"jeton": "peu-importe"})
    assert reponse.status_code == 404
    assert reponse.json()["erreur"]["code"] == "comptes_indisponibles"


def test_le_mode_personnel_n_est_pas_touche_par_ces_routes(tmp_path):
    """`ourouler api` (mode personnel) : ces routes existent mais refusent, rien de plus.

    Ce n'est pas une régression du mode personnel — il n'a jamais eu de
    comptes — c'est la même réponse « pas de base de comptes ici » que le
    test ci-dessus, avec `SessionPersonnelle` au lieu de `SessionHebergee`.
    """
    app = creer_application(
        socle=SocleVide(), dossier_donnees=tmp_path / "donnees", session=SessionPersonnelle()
    )
    reponse = requete(app, "POST", f"{PREFIXE}/sortir")
    # `/sortir` sans cookie ne regarde même pas la base : elle réussit toujours.
    assert reponse.status_code == 200

    reponse = requete(app, "GET", f"{PREFIXE}/invitation", params={"jeton": "peu-importe"})
    assert reponse.status_code == 404
    assert reponse.json()["erreur"]["code"] == "comptes_indisponibles"
