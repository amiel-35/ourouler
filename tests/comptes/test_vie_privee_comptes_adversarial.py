"""Ce qu'on essaie de casser dans `DELETE /moi` une fois qu'il ferme le compte.

`test_vie_privee_comptes.py`, à côté, prouve le chemin heureux : inviter,
activer, semer des données, `DELETE /moi`, tout a disparu. Ce fichier-ci ne
rejoue pas ce chemin — il attaque les bords que le chemin heureux ne
rencontre jamais :

1. **deux suppressions en vol en même temps** sur le même propriétaire ;
2. **réinviter la même adresse après coup** — le compte neuf ne doit rien
   hériter de l'ancien ;
3. **un effacement à moitié fait** : une étape lève, que reste-t-il ?
4. **le mode personnel** (`comptes=None`), qui ne doit pas avoir bougé ;
5. **deux propriétaires côte à côte**, un seul supprimé ;
6. **un propriétaire sans compte**, ou dont le compte est déjà parti ;
7. **la portée de la cascade**, lue en SQL nu et pas à travers l'API — une
   API qui répond 401 ne prouve pas qu'il ne reste aucune ligne.

**Pourquoi dans `tests/comptes/`** : mêmes raisons que ses voisins, dites
dans `conftest.py` — ces tests ont besoin d'un vrai PostgreSQL local, que
`tests/api/conftest.py` interdit à son propre dossier. La boucle locale
n'est pas Internet (règle absolue 3), et aucune de ces fixtures ne porte de
donnée réelle (règle absolue 1) : adresses en `.invalid`, coordonnées au
large du golfe de Guinée, mots de passe inventés sur place.
"""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path

import httpx
import pytest

from ourouler.api import vie_privee
from ourouler.api.application import creer_application
from ourouler.api.base_de_donnees import ouvrir
from ourouler.api.comptes import (
    DepotComptes,
    ErreurInvitationRefusee,
)
from ourouler.api.depots import SocleTOML
from ourouler.api.proprietaire import Proprietaire
from ourouler.api.session import (
    NOM_COOKIE,
    SessionHebergee,
    SessionParCookie,
    SessionPersonnelle,
)

PREFIXE = "/api/v1"

#: Inventé sur place, jamais un vrai mot de passe (règle absolue 1).
MOT_DE_PASSE = "grelot-marmotte-oseille-brique"

#: Toutes les adresses de ce fichier sont en `.invalid` — réservé par la
#: RFC 2606, donc jamais routable et jamais celle de quelqu'un.
ADRESSE_A = "adversarial-a@exemple.invalid"
ADRESSE_B = "adversarial-b@exemple.invalid"


# --------------------------------------------------------------------------
# le décor : une application réelle, et de quoi l'interroger
# --------------------------------------------------------------------------


def _toml_minimal(tmp_path: Path) -> str:
    """Juste de quoi valider une `Config`, sans rien de réel.

    Départ au large du golfe de Guinée (aucune coordonnée française, règle
    absolue 1) et `[cache]` **dans `tmp_path`** : sans ça, `config.cache.dossier`
    retomberait sur le cache réel de la machine, ce qu'un test n'a pas à
    toucher.
    """
    return (
        "[depart]\n"
        'nom = "Départ d\'essai"\n'
        "latitude = 0.0009\nlongitude = 0.0004\n"
        "\n[cycliste]\nmasse_kg = 70.0\nftp_w = 200\n"
        f'\n[cache]\ndossier = "{tmp_path / "cache"}"\n'
    )


def _app_avec_session(session, tmp_path: Path):
    """L'application réelle, sur le fournisseur de session qu'on lui donne."""
    chemin = tmp_path / "config.toml"
    chemin.write_text(_toml_minimal(tmp_path), encoding="utf-8")
    return creer_application(
        socle=SocleTOML(chemin, proprietaire=None),
        dossier_donnees=tmp_path / "donnees",
        session=session,
    )


def _app(url_base: str, tmp_path: Path):
    """L'application réelle, branchée sur une vraie base de comptes."""
    return _app_avec_session(SessionParCookie(url_base), tmp_path)


def _requete(
    app, methode: str, chemin: str, *, cookies: dict[str, str] | None = None, **kwargs
) -> httpx.Response:
    """Un appel HTTP synchrone contre l'application ASGI, sans réseau."""

    async def _aller() -> httpx.Response:
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://api.test", cookies=cookies
        ) as client:
            return await client.request(methode, chemin, **kwargs)

    return asyncio.run(_aller())


def _inscrire(app, url_base: str, adresse: str) -> tuple[str, str, dict[str, str]]:
    """Invite puis active `adresse` ; rend (compte, proprietaire, cookies).

    Passe par les vraies routes pour l'activation, comme le ferait quelqu'un
    qui clique le lien — c'est ce qui pose un vrai cookie de session.
    """
    with ouvrir(url_base) as cx:
        emise = DepotComptes(cx).inviter(adresse)
    reponse = _requete(app, "POST", f"{PREFIXE}/entrer", json={"jeton": emise.jeton, "secret": MOT_DE_PASSE})
    assert reponse.status_code == 200, reponse.text
    proprietaire = reponse.json()["donnees"]["proprietaire"]
    jeton_session = reponse.cookies.get(NOM_COOKIE)
    assert jeton_session, "aucun cookie de session posé par /entrer"
    with ouvrir(url_base) as cx:
        compte = cx.execute(
            "SELECT compte FROM comptes_proprietaires WHERE proprietaire = %s",
            (proprietaire,),
        ).fetchone()[0]
    return compte, proprietaire, {NOM_COOKIE: jeton_session}


def _restes(url_base: str, compte: str) -> dict[str, int]:
    """Ce qui reste en base pour ce compte, lu en SQL nu, table par table.

    Volontairement pas à travers l'API : une route qui répond 401 prouve
    qu'on ne peut plus entrer, pas qu'il ne reste plus rien. La portée de la
    cascade se vérifie là où elle s'applique.
    """
    with ouvrir(url_base) as cx:
        return {
            "comptes": cx.execute("SELECT count(*) FROM comptes WHERE id = %s", (compte,)).fetchone()[0],
            "sessions": cx.execute("SELECT count(*) FROM sessions WHERE compte = %s", (compte,)).fetchone()[
                0
            ],
            "invitations": cx.execute(
                "SELECT count(*) FROM invitations WHERE compte = %s", (compte,)
            ).fetchone()[0],
            "comptes_proprietaires": cx.execute(
                "SELECT count(*) FROM comptes_proprietaires WHERE compte = %s", (compte,)
            ).fetchone()[0],
        }


# --------------------------------------------------------------------------
# 1. deux suppressions concurrentes
# --------------------------------------------------------------------------


def test_deux_suppressions_concurrentes_une_seule_gagne(url_base):
    """Deux `DELETE` en vol sur le même propriétaire : une réussit, l'autre dit faux.

    Le scénario réel : quelqu'un clique deux fois, ou le front réémet la
    requête sur un timeout. Les deux appels partent sur **deux connexions
    distinctes**, comme deux requêtes HTTP — une seule connexion partagée ne
    prouverait rien, elle sérialiserait toute seule.

    Ce qu'on refuse : une exception qui remonterait en 500, ou deux `True`
    (qui voudraient dire que la suppression a compté deux fois quelque chose).
    """
    with ouvrir(url_base) as cx:
        depot = DepotComptes(cx)
        emise = depot.inviter(ADRESSE_A)
        acces = depot.activer(emise.jeton, MOT_DE_PASSE)
        qui = acces.proprietaire
        compte = acces.compte.identifiant
        depot.ouvrir_session(compte)
        depot.ouvrir_session(compte)

    resultats: list[bool] = []
    erreurs: list[BaseException] = []
    verrou = threading.Lock()
    # Les deux fils s'attendent connexion déjà ouverte : ce qu'on veut faire
    # se chevaucher est le `DELETE`, pas l'établissement de la connexion.
    depart = threading.Barrier(2)

    def supprimer() -> None:
        try:
            with ouvrir(url_base) as cx:
                depot = DepotComptes(cx)
                depart.wait(timeout=30)
                efface = depot.supprimer_compte_du_proprietaire(qui)
            with verrou:
                resultats.append(efface)
        except BaseException as e:  # noqa: BLE001 - on veut *voir* ce qui casse
            with verrou:
                erreurs.append(e)

    fils = [threading.Thread(target=supprimer) for _ in range(2)]
    for f in fils:
        f.start()
    for f in fils:
        f.join(timeout=60)
    assert not any(f.is_alive() for f in fils), (
        "une suppression concurrente ne s'est jamais terminée — interblocage probable"
    )

    assert erreurs == [], f"une suppression concurrente a levé : {erreurs!r}"
    assert sorted(resultats) == [False, True], (
        f"deux suppressions simultanées devraient donner exactement un vrai et un faux, pas {resultats!r}"
    )
    assert _restes(url_base, compte) == {
        "comptes": 0,
        "sessions": 0,
        "invitations": 0,
        "comptes_proprietaires": 0,
    }, "la course a laissé un état à moitié effacé"


# --------------------------------------------------------------------------
# 2. réinviter la même adresse après la suppression
# --------------------------------------------------------------------------


def test_reinviter_la_meme_adresse_repart_de_zero(url_base, tmp_path):
    """Après suppression, la même adresse peut revenir — sans rien hériter.

    Le risque produit, s'il y avait un résidu : un compte neuf rattaché à
    l'**ancien** propriétaire relirait les données du précédent — exactement
    la fuite que `comptes_proprietaires` est censée empêcher (doctrine §10.2).

    On vérifie donc trois choses distinctes : l'invitation repart (pas
    d'`ErreurCompteExistant` sur un fantôme), le compte est **un autre**, et
    surtout le propriétaire est **un autre** — la clé pseudonyme ne se
    recycle pas.
    """
    app = _app(url_base, tmp_path)
    compte_1, proprietaire_1, cookies_1 = _inscrire(app, url_base, ADRESSE_A)

    marque = "sentinelle-avant-suppression"
    # Q35, tiers 3 : le socle partagé ne fournit plus `depart`/`cycliste`
    # (fuite fermée le 21/09/2026) — le propriétaire écrit les deux.
    profil = _requete(
        app,
        "PATCH",
        f"{PREFIXE}/profil",
        cookies=cookies_1,
        json={
            "depart": {"nom": marque, "latitude": 0.0007, "longitude": 0.0003},
            "cycliste": {"masse_kg": 70.0},
        },
    )
    assert profil.status_code == 200, profil.text

    suppression = _requete(app, "DELETE", f"{PREFIXE}/moi", cookies=cookies_1)
    assert suppression.status_code == 200, suppression.text
    assert suppression.json()["donnees"]["supprime"]["compte"] is True

    # --- la même adresse revient ---

    compte_2, proprietaire_2, cookies_2 = _inscrire(app, url_base, ADRESSE_A)

    assert compte_2 != compte_1, "la réinvitation a ressuscité l'ancien compte"
    assert proprietaire_2 != proprietaire_1, (
        "le compte neuf hérite du propriétaire de l'ancien : ses données seraient "
        "relues par quelqu'un d'autre"
    )
    assert cookies_2[NOM_COOKIE] != cookies_1[NOM_COOKIE]

    # Rien de l'ancien ne transparaît dans le neuf.
    nouveau_profil = _requete(app, "GET", f"{PREFIXE}/profil", cookies=cookies_2)
    assert nouveau_profil.status_code == 200, nouveau_profil.text
    assert marque not in nouveau_profil.text, "le profil du compte neuf porte la sentinelle de l'ancien"

    # Et l'ancien cookie ne redevient pas valable parce qu'un compte existe
    # à nouveau sur cette adresse.
    assert _requete(app, "GET", f"{PREFIXE}/profil", cookies=cookies_1).status_code == 401, (
        "le cookie de l'ancien compte revit après réinvitation de la même adresse"
    )

    assert _restes(url_base, compte_1) == {
        "comptes": 0,
        "sessions": 0,
        "invitations": 0,
        "comptes_proprietaires": 0,
    }, "des lignes de l'ancien compte survivent à la réinvitation"


# --------------------------------------------------------------------------
# 3. l'effacement à moitié fait
# --------------------------------------------------------------------------


class _FichiersQuiTombent:
    """Un dépôt de fichiers qui échoue — le stockage d'objets qui ne répond pas.

    `effacer_donnees` parle à cinq dépôts hétérogènes (profil sur disque,
    fichiers, journal, cache, générations en mémoire) puis à PostgreSQL :
    aucune transaction ne peut couvrir les six. Ce bouchon rend cette
    frontière observable au lieu de la supposer.
    """

    def __init__(self, vrai) -> None:
        self._vrai = vrai

    def __getattr__(self, nom):
        return getattr(self._vrai, nom)

    def supprimer_tout(self, qui):
        raise OSError("le stockage d'objets ne répond pas")


def test_un_effacement_interrompu_laisse_le_compte_ouvert(url_base, tmp_path):
    """Si une étape d'effacement lève, le compte n'est pas fermé — et on le dit.

    Ce test **documente l'ordre**, il ne réclame pas de transaction globale :
    le compte est effacé **en dernier**, donc une panne en amont laisse le
    compte vivant et une partie des données déjà parties. C'est le moins
    mauvais des deux sens — l'inverse (compte fermé, données restées)
    enfermerait la personne dehors avec ses données dedans, sans porte pour
    réessayer.

    Ce qu'il fige, pour que personne ne réordonne le dict de `effacer_donnees`
    sans s'en apercevoir : après l'échec, (a) le compte et sa session
    répondent encore, donc `DELETE /moi` est **rejouable**, et (b) le second
    passage finit le travail.
    """
    app = _app(url_base, tmp_path)
    compte, proprietaire, cookies = _inscrire(app, url_base, ADRESSE_A)
    qui = Proprietaire(proprietaire)
    ctx = app.state.ourouler

    ctx.journal.noter_succes(qui, "openmeteo")
    assert ctx.journal.tout(qui), "le semis du journal n'a pas pris"

    with ouvrir(url_base) as cx:
        with pytest.raises(OSError):
            vie_privee.effacer_donnees(
                qui,
                profils=ctx.profils,
                fichiers=_FichiersQuiTombent(ctx.fichiers),
                journal=ctx.journal,
                generations=ctx.generations,
                dossier_cache=tmp_path / "cache",
                comptes=DepotComptes(cx),
            )

    # (a) le compte a survécu à l'échec, et c'est ce qui rend l'appel rejouable.
    assert _restes(url_base, compte)["comptes"] == 1, (
        "le compte a été fermé alors que l'effacement des données a échoué : "
        "la personne se retrouve dehors avec ses données encore dedans"
    )
    assert _requete(app, "GET", f"{PREFIXE}/profil", cookies=cookies).status_code == 200, (
        "la session a été révoquée par un effacement qui a échoué — plus aucune porte pour réessayer"
    )
    # Ce qui était passé avant la panne est bien parti : l'état est partiel,
    # pas intact. C'est le prix assumé de l'absence de transaction globale.
    assert ctx.journal.tout(qui) == {}, "le journal aurait dû être effacé avant l'étape qui a levé"

    # (b) rejouer finit le travail.
    seconde = _requete(app, "DELETE", f"{PREFIXE}/moi", cookies=cookies)
    assert seconde.status_code == 200, seconde.text
    assert seconde.json()["donnees"]["supprime"]["compte"] is True
    assert _restes(url_base, compte) == {
        "comptes": 0,
        "sessions": 0,
        "invitations": 0,
        "comptes_proprietaires": 0,
    }


# --------------------------------------------------------------------------
# 4. le mode personnel, qui ne doit pas avoir bougé
# --------------------------------------------------------------------------


def test_mode_personnel_sans_base_de_comptes(tmp_path):
    """`comptes=None` : pas de clé « compte », aucune erreur, deux fois de suite.

    C'est le mode d'un seul cycliste (`SessionPersonnelle`), celui du
    mainteneur. Le lot RGPD-compte ne doit rien y changer : la clé `"compte"`
    n'apparaît pas — il n'y a pas de compte à fermer, et annoncer
    `"compte": False` laisserait croire qu'il y en avait un.

    Aucun PostgreSQL ici : sans base de comptes, il n'y a rien à interroger.
    """
    from ourouler.api.depots import (
        DepotFichiers,
        DepotGenerations,
        DepotProfils,
        JournalServices,
    )

    chemin = tmp_path / "config.toml"
    chemin.write_text(_toml_minimal(tmp_path), encoding="utf-8")
    donnees = tmp_path / "donnees"

    qui = Proprietaire("personnel")
    profils = DepotProfils(SocleTOML(chemin, proprietaire=None), donnees)
    fichiers = DepotFichiers(donnees)
    journal = JournalServices(donnees)
    generations = DepotGenerations()
    dossier_cache = tmp_path / "cache"

    # Q35, tiers 3 (fuite fermée le 21/09/2026) : le socle partagé ne fournit
    # plus `depart`/`cycliste` — `qui` doit désormais écrire les deux, pas
    # seulement le nom du départ, pour que sa `Config` se construise.
    profils.enregistrer(
        qui,
        {
            "depart": {"nom": "sentinelle-personnelle", "latitude": 0.0007, "longitude": 0.0003},
            "cycliste": {"masse_kg": 70.0},
        },
    )
    assert profils.surcharge(qui), "le semis du profil n'a pas pris"

    premier = vie_privee.effacer_donnees(
        qui,
        profils=profils,
        fichiers=fichiers,
        journal=journal,
        generations=generations,
        dossier_cache=dossier_cache,
    )
    assert "compte" not in premier["supprime"], (
        "le mode personnel annonce une clé « compte » alors qu'il n'a pas de comptes"
    )
    assert premier["supprime"]["profil"] is True

    # Deux fois de suite : l'idempotence ne dépend pas de la base de comptes.
    second = vie_privee.effacer_donnees(
        qui,
        profils=profils,
        fichiers=fichiers,
        journal=journal,
        generations=generations,
        dossier_cache=dossier_cache,
    )
    assert "compte" not in second["supprime"]
    assert second["supprime"]["profil"] is False
    assert profils.surcharge(qui) == {}


def test_route_moi_en_mode_personnel_ne_cherche_aucune_base_de_comptes(tmp_path):
    """`DELETE /moi` par la **vraie route**, en mode personnel, deux fois de suite.

    Le test au-dessus appelle `effacer_donnees` directement ; celui-ci passe
    par `routes.supprimer_mes_donnees`, donc par `_comptes_du_deploiement` —
    la branche `isinstance(ctx.session, SessionParCookie)` qui décide de ne
    **pas** ouvrir de connexion. C'est là que le lot pouvait régresser : ce
    déploiement n'a pas d'URL de base, et une tentative de connexion
    échouerait, ou pire chercherait une configuration là où le cœur n'a pas
    le droit d'aller (règle absolue 2).

    Aucun PostgreSQL n'est demandé par ce test : s'il en ouvrait un
    malgré tout, il échouerait ici plutôt que de passer inaperçu.
    """
    app = _app_avec_session(SessionPersonnelle(), tmp_path)

    # Q35, tiers 3 : le socle partagé ne fournit plus `depart`/`cycliste`.
    profil = _requete(
        app,
        "PATCH",
        f"{PREFIXE}/profil",
        json={
            "depart": {"nom": "chez-moi", "latitude": 0.0007, "longitude": 0.0003},
            "cycliste": {"masse_kg": 70.0},
        },
    )
    assert profil.status_code == 200, profil.text

    premier = _requete(app, "DELETE", f"{PREFIXE}/moi")
    assert premier.status_code == 200, premier.text
    supprime = premier.json()["donnees"]["supprime"]
    assert "compte" not in supprime, (
        "le mode personnel annonce une clé « compte » : il n'a pourtant aucun compte"
    )
    assert supprime["profil"] is True

    second = _requete(app, "DELETE", f"{PREFIXE}/moi")
    assert second.status_code == 200, (
        f"un second DELETE /moi en mode personnel ne passe plus : {second.text[:300]}"
    )
    assert second.json()["donnees"]["supprime"]["profil"] is False


def test_route_moi_en_heberge_sans_comptes_reste_fermee(tmp_path):
    """Hébergé sans méthode d'authentification : 401, et surtout pas un 500.

    `SessionHebergee.ouvrir` rend `None` — personne n'est reconnu. La route
    ne doit donc jamais arriver jusqu'à `_comptes_du_deploiement`. Le garde
    est le même qu'avant ce lot ; ce test le fige, parce que c'est le mode
    dans lequel une erreur d'`isinstance` se verrait le moins.
    """
    app = _app_avec_session(SessionHebergee(), tmp_path)
    reponse = _requete(app, "DELETE", f"{PREFIXE}/moi")
    assert reponse.status_code == 401, (
        f"un déploiement hébergé sans comptes a laissé passer DELETE /moi : "
        f"{reponse.status_code} {reponse.text[:300]}"
    )


# --------------------------------------------------------------------------
# 5. deux propriétaires côte à côte
# --------------------------------------------------------------------------


def test_supprimer_a_ne_touche_pas_b(url_base, tmp_path):
    """A et B plantés côte à côte ; on supprime A ; B ne bouge pas d'un pouce.

    L'isolation entre propriétaires est l'invariant que la doctrine §10.2
    pose comme non négociable (« aucune requête sans clause de
    propriétaire »). Une suppression est justement le geste qui, mal écrit
    (un `DELETE` sans clause, une sous-requête qui rend plusieurs lignes),
    emporte le voisin.

    B garde deux sessions ouvertes au moment où A part : c'est le cas qui
    attraperait un `DELETE FROM sessions` trop large.
    """
    app = _app(url_base, tmp_path)
    compte_a, proprietaire_a, cookies_a = _inscrire(app, url_base, ADRESSE_A)
    compte_b, proprietaire_b, cookies_b = _inscrire(app, url_base, ADRESSE_B)

    marque_b = "sentinelle-de-b"
    # Q35, tiers 3 : le socle partagé ne fournit plus `depart`/`cycliste`.
    profil_b = _requete(
        app,
        "PATCH",
        f"{PREFIXE}/profil",
        cookies=cookies_b,
        json={
            "depart": {"nom": marque_b, "latitude": 0.0007, "longitude": 0.0003},
            "cycliste": {"masse_kg": 70.0},
        },
    )
    assert profil_b.status_code == 200, profil_b.text

    with ouvrir(url_base) as cx:
        DepotComptes(cx).ouvrir_session(compte_b)
    avant_b = _restes(url_base, compte_b)
    assert avant_b["sessions"] == 2, f"B devrait avoir deux sessions, pas {avant_b}"

    suppression = _requete(app, "DELETE", f"{PREFIXE}/moi", cookies=cookies_a)
    assert suppression.status_code == 200, suppression.text

    assert _restes(url_base, compte_a) == {
        "comptes": 0,
        "sessions": 0,
        "invitations": 0,
        "comptes_proprietaires": 0,
    }, "A n'est pas parti en entier"
    assert _restes(url_base, compte_b) == avant_b, (
        "la suppression de A a modifié des lignes de B — fuite entre propriétaires"
    )

    apres_b = _requete(app, "GET", f"{PREFIXE}/profil", cookies=cookies_b)
    assert apres_b.status_code == 200, (
        f"la session de B est tombée avec la suppression de A : {apres_b.text[:200]}"
    )
    assert marque_b in apres_b.text, "le profil de B a été emporté par la suppression de A"

    # Et B peut toujours se connecter par mot de passe.
    connexion_b = _requete(
        app, "POST", f"{PREFIXE}/connexion", json={"email": ADRESSE_B, "secret": MOT_DE_PASSE}
    )
    assert connexion_b.status_code == 200, (
        f"B ne peut plus se connecter après la suppression de A : {connexion_b.text[:200]}"
    )

    ctx = app.state.ourouler
    assert ctx.profils.surcharge(Proprietaire(proprietaire_b)), "le profil de B a disparu"
    assert ctx.profils.surcharge(Proprietaire(proprietaire_a)) == {}


# --------------------------------------------------------------------------
# 6. le compte qui n'existe pas, ou plus
# --------------------------------------------------------------------------


def test_supprimer_un_proprietaire_sans_compte_ne_leve_rien(url_base):
    """Jamais invité, déjà supprimé, forme inhabituelle : faux, jamais une exception.

    Si l'un de ces appels levait, la route le classerait en 500 alors que la
    bonne réponse produit est « il n'y avait rien à effacer ». Le chemin
    d'`effacer_donnees` passe par là à chaque mode personnel devenu hébergé.
    """
    with ouvrir(url_base) as cx:
        depot = DepotComptes(cx)

        assert depot.supprimer_compte_du_proprietaire(Proprietaire("jamais-invite")) is False

        emise = depot.inviter(ADRESSE_A)
        acces = depot.activer(emise.jeton, MOT_DE_PASSE)
        qui = acces.proprietaire

        assert depot.supprimer_compte_du_proprietaire(qui) is True
        assert depot.supprimer_compte_du_proprietaire(qui) is False, (
            "la seconde suppression prétend avoir effacé quelque chose"
        )
        assert depot.supprimer_compte_du_proprietaire(qui) is False

    # Une chaîne malformée ne peut de toute façon jamais atteindre le SQL :
    # `Proprietaire` refuse la forme à la construction, avant tout dépôt. La
    # sous-requête de `supprimer_compte_du_proprietaire` n'a donc jamais à se
    # défendre elle-même — mais c'est ce type-là qui le garantit, et si
    # quelqu'un relâchait `FORME_IDENTIFIANT`, c'est ici que ça se verrait.
    from ourouler.api.proprietaire import ErreurProprietaire

    with pytest.raises(ErreurProprietaire):
        Proprietaire("PAS/UN/ID")


def test_supprimer_un_compte_invite_mais_jamais_active(url_base):
    """Un compte inactif part aussi, et son lien d'invitation meurt avec lui.

    Le cas oublié : quelqu'un est invité, ne va jamais au bout, et demande
    l'effacement (ou le mainteneur le fait pour lui). Le compte existe, la
    correspondance aussi, l'invitation court encore. Après suppression, le
    jeton encore dans sa boîte aux lettres ne doit plus ouvrir de compte —
    et doit être **refusé proprement**, pas planter.
    """
    with ouvrir(url_base) as cx:
        depot = DepotComptes(cx)
        emise = depot.inviter(ADRESSE_A)
        compte = cx.execute("SELECT compte FROM invitations WHERE jeton = %s", (emise.jeton,)).fetchone()[0]
        qui = depot.proprietaire_du_compte(compte)

        assert depot.supprimer_compte_du_proprietaire(qui) is True

        with pytest.raises(ErreurInvitationRefusee):
            depot.activer(emise.jeton, MOT_DE_PASSE)

    assert _restes(url_base, compte) == {
        "comptes": 0,
        "sessions": 0,
        "invitations": 0,
        "comptes_proprietaires": 0,
    }, "l'invitation d'un compte inactif supprimé traîne encore"


# --------------------------------------------------------------------------
# 7. la portée de la cascade, en SQL nu
# --------------------------------------------------------------------------


def test_la_cascade_ne_laisse_aucune_ligne_orpheline(url_base):
    """Plusieurs sessions, une invitation consommée : tout part, vérifié table par table.

    L'API répond 401 après la suppression, mais 401 ne dit rien des lignes
    restées en base : une session orpheline qui traîne est une donnée
    personnelle conservée (RGPD), même si plus rien ne la sert. On compte
    donc **avant** — pour être sûr que le décor est planté — puis après, sur
    les trois tables que `ON DELETE CASCADE` est censé emporter.
    """
    with ouvrir(url_base) as cx:
        depot = DepotComptes(cx)
        emise = depot.inviter(ADRESSE_A)
        acces = depot.activer(emise.jeton, MOT_DE_PASSE)
        compte = acces.compte.identifiant
        qui = acces.proprietaire
        for _ in range(3):
            depot.ouvrir_session(compte)

    avant = _restes(url_base, compte)
    assert avant == {
        "comptes": 1,
        "sessions": 3,
        # L'invitation est *consommée*, pas effacée, par `activer` : elle reste
        # donc en base, et c'est bien la cascade qui doit l'emporter.
        "invitations": 1,
        "comptes_proprietaires": 1,
    }, f"le décor n'est pas celui qu'on croit : {avant}"

    with ouvrir(url_base) as cx:
        assert DepotComptes(cx).supprimer_compte_du_proprietaire(qui) is True

    assert _restes(url_base, compte) == {
        "comptes": 0,
        "sessions": 0,
        "invitations": 0,
        "comptes_proprietaires": 0,
    }, "la cascade a laissé des lignes orphelines"

    # Aucune ligne ne doit non plus subsister *ailleurs* que sous ce compte :
    # la base entière doit être vide de ces trois tables, puisqu'un seul
    # compte y a jamais existé. C'est ce qui attraperait une ligne dont la
    # clé étrangère aurait été mise à NULL au lieu d'être effacée.
    with ouvrir(url_base) as cx:
        for table in ("comptes", "sessions", "invitations", "comptes_proprietaires"):
            restant = cx.execute(f"SELECT count(*) FROM {table}").fetchone()[0]  # noqa: S608
            assert restant == 0, f"{restant} ligne(s) orpheline(s) dans {table}"
