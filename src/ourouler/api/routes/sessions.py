"""Comptes et sessions : activer une invitation, se connecter, réinitialiser, sortir."""

from __future__ import annotations

from typing import Annotated

from fastapi import Query, Request
from fastapi.responses import Response

from ourouler.api import base_de_donnees
from ourouler.api.comptes import DepotComptes, ErreurInvitationRefusee
from ourouler.api.erreurs import ErreurApi, classer
from ourouler.api.modeles import DemandeConnexion, DemandeEntree, DemandeReinitialisation, TexteUtile
from ourouler.api.routes.commun import Contexte, Ctx, nouveau_routeur
from ourouler.api.session import NOM_COOKIE, SessionParCookie

routeur = nouveau_routeur()


# --- comptes et sessions (lot L7.2-C) ------------------------------------------
#
# Quatre routes qui **précèdent** l'existence d'une session : on ne peut pas
# leur demander la clause de propriétaire que `Qui` porte, puisque c'est
# justement ce qu'elles fabriquent (`/entrer`, `/connexion`) ou détruisent
# (`/sortir`) — ou qu'elles regardent sans rien ouvrir (`/invitation`). C'est
# la même frontière que `api/comptes.py` trace pour son dépôt : voir
# `tests/api/test_api_isolation_proprietaire.py` (`ROUTES_AVANT_SESSION`) pour
# l'exemption du balayage d'isolation, étroite, nommée, et sa contre-épreuve.
#
# Chacune ouvre sa **propre** connexion à la base des comptes, au lieu de
# passer par `ctx.session.ouvrir(requete)` : ce dernier *lit* une session déjà
# ouverte, il ne sait pas en fabriquer une. Ces routes n'existent donc que
# quand `ctx.session` est une `SessionParCookie` (mode hébergé, base
# configurée) — ailleurs, `_url_comptes` refuse proprement plutôt que de
# tenter une connexion à une base absente.


def _url_comptes(ctx: Contexte) -> str:
    """L'URL de la base des comptes de ce déploiement — ou un refus nommé.

    Ces quatre routes ne servent que sur un déploiement hébergé avec une base
    de comptes configurée (`SessionParCookie`). Ailleurs — mode personnel,
    hébergé sans base — il n'y a ni compte ni session à créer, et la bonne
    réponse est un refus explicite plutôt qu'une tentative de connexion à une
    base qui n'existe pas.
    """
    session = ctx.session
    if not isinstance(session, SessionParCookie):
        raise ErreurApi(
            code="comptes_indisponibles",
            message="ce déploiement ne gère pas de comptes — rien à activer, rien où se "
            "connecter, personne à qui dire au revoir",
            statut=404,
        )
    return session.url


def _poser_cookie(reponse: Response, jeton_session: str) -> None:
    """Pose le cookie de session — `HttpOnly`, `Secure`, `SameSite=Lax` (`api/session.py`).

    `max_age` reprend la durée de la session en base (`comptes.DUREE_SESSION`) :
    un cookie qui vivrait plus longtemps que la ligne qu'il désigne ne
    changerait rien à la sécurité (la session introuvable en base rend déjà
    401), un cookie plus court forcerait une reconnexion avant l'échéance
    réelle sans raison.
    """
    from ourouler.api.comptes import DUREE_SESSION

    reponse.set_cookie(
        NOM_COOKIE,
        jeton_session,
        max_age=int(DUREE_SESSION.total_seconds()),
        httponly=True,
        secure=True,
        samesite="lax",
        path="/",
    )


@routeur.get("/invitation")
def etat_invitation(ctx: Ctx, jeton: Annotated[TexteUtile, Query(min_length=1, max_length=255)]) -> dict:
    """L'état d'un jeton d'invitation, sans le consommer.

    Un jeton inconnu, périmé ou déjà consommé rendent la **même** réponse
    (404, `invitation_invalide`) : on ne dit pas à un inconnu lequel des
    trois il a rencontré — voir `DepotComptes.invitation_ouverte`, qui rend
    `None` dans les trois cas par la même requête.
    """
    url = _url_comptes(ctx)
    with base_de_donnees.ouvrir(url) as cx:
        etat = DepotComptes(cx).invitation_ouverte(jeton)
    if etat is None:
        raise ErreurApi(code="invitation_invalide", message=MESSAGE_LIEN_INVALIDE, statut=404)
    return {"donnees": {"email": etat.email, "expire_le": etat.expire_le.isoformat()}}


#: Ce que les trois routes qui consomment un jeton de la table `invitations`
#: répondent quand il ne vaut rien — **le même texte, quel que soit le
#: motif, et quel que soit le flux**. Distinguer « n'existe pas », « a
#: expiré le 02/09 » et « a déjà servi » renseigne qui tient un jeton périmé
#: sur le fait qu'il a bel et bien été émis, et sur sa date exacte. `GET
#: /invitation` avait été écrite ainsi ; `POST /entrer` laissait passer le
#: message détaillé de `comptes._invitation_refusee`, et rouvrait donc la
#: porte qu'on venait de fermer (relecture du 19/09/2026).
#:
#: **Neutre, pas « d'invitation »** (relecture du 25/09/2026, point 2) :
#: `POST /reinitialiser` consomme un jeton de la même table pour un usage
#: différent (choisir un nouveau mot de passe, pas créer un compte) — un
#: texte qui parle d'« invitation » à quelqu'un qui réinitialise son mot de
#: passe décrit le mauvais geste. Le code (`invitation_invalide`) ne change
#: pas : les deux flux restent indistinguables l'un de l'autre, seul le mot
#: choisi dans le message change.
#:
#: Les messages détaillés ne disparaissent pas pour autant : ils restent ce
#: que `DepotComptes` lève, et ce que la ligne de commande affiche au
#: mainteneur — qui a le droit de savoir *pourquoi*, puisque c'est lui qui a
#: émis le lien.
MESSAGE_LIEN_INVALIDE = "ce lien n'est plus valable — inconnu, expiré ou déjà utilisé"


@routeur.post("/entrer")
def entrer(ctx: Ctx, corps: DemandeEntree, reponse: Response) -> dict:
    """Active le compte invité, ouvre sa première session, pose le cookie.

    `DepotComptes.activer` pose le secret, active le compte et consomme
    l'invitation dans une seule transaction (`api/comptes.py`) ; le
    propriétaire qu'elle rend est celui que `inviter` a déjà rattaché au
    compte, dans `comptes_proprietaires` ([[Q46]]) — cette route n'a donc
    rien de plus à créer, elle ouvre la session qui en découle. Deux appels
    concurrents avec le même jeton : un seul passe l'activation (transaction
    atomique de `activer`), donc une seule session s'ouvre.
    """
    url = _url_comptes(ctx)
    with base_de_donnees.ouvrir(url) as cx:
        depot = DepotComptes(cx)
        try:
            acces = depot.activer(corps.jeton, corps.secret)
        except ErreurInvitationRefusee as e:
            # Le motif est perdu **exprès** : voir MESSAGE_LIEN_INVALIDE.
            raise ErreurApi(
                code="invitation_invalide", message=MESSAGE_LIEN_INVALIDE, statut=400
            ) from e
        except Exception as e:
            raise classer(e) from e
        jeton_session = depot.ouvrir_session(acces.compte.identifiant)
    _poser_cookie(reponse, jeton_session)
    return {"donnees": {"proprietaire": str(acces.proprietaire)}}


@routeur.post("/reinitialiser")
def reinitialiser(ctx: Ctx, corps: DemandeReinitialisation, reponse: Response) -> dict:
    """Consomme un jeton de réinitialisation : pose le nouveau mot de passe, ferme
    toutes les sessions déjà ouvertes du compte, en ouvre une neuve pour celle-ci.

    **Jamais atteinte sans un jeton déjà émis** — il n'existe aucune route qui en émette
    un depuis une simple adresse (« mot de passe oublié » en libre-service, exclu par
    décision du mainteneur : voir la note de module de `DepotComptes.reinitialiser`,
    `api/comptes.py`). Seul `ourouler reinitialiser`, en ligne de commande, en émet un ;
    cette route-ci ne fait que le consommer — même mécanique que `POST /entrer` pour un
    jeton d'invitation, même refus indistinguable (`MESSAGE_LIEN_INVALIDE`) pour un
    jeton inconnu, expiré ou déjà utilisé.
    """
    url = _url_comptes(ctx)
    with base_de_donnees.ouvrir(url) as cx:
        depot = DepotComptes(cx)
        try:
            acces = depot.changer_mot_de_passe_par_jeton(corps.jeton, corps.secret)
        except ErreurInvitationRefusee as e:
            raise ErreurApi(
                code="invitation_invalide", message=MESSAGE_LIEN_INVALIDE, statut=400
            ) from e
        except Exception as e:
            raise classer(e) from e
        jeton_session = depot.ouvrir_session(acces.compte.identifiant)
    _poser_cookie(reponse, jeton_session)
    return {"donnees": {"proprietaire": str(acces.proprietaire)}}


@routeur.post("/connexion")
def connexion(ctx: Ctx, corps: DemandeConnexion, reponse: Response) -> dict:
    """Revient sur un compte actif : vérifie le secret, ouvre une session.

    Une adresse sans compte actif et un mot de passe faux rendent la **même**
    réponse (401, `identifiants_refuses`), dans le même temps —
    `DepotComptes.authentifier` égalise aussi le calcul, pas seulement le
    message.
    """
    url = _url_comptes(ctx)
    with base_de_donnees.ouvrir(url) as cx:
        depot = DepotComptes(cx)
        compte = depot.authentifier(corps.email, corps.secret)
        if compte is None:
            raise ErreurApi(
                code="identifiants_refuses",
                message="adresse ou mot de passe refusés",
                statut=401,
            )
        jeton_session = depot.ouvrir_session(compte.identifiant)
        proprietaire = depot.proprietaire_du_compte(compte.identifiant)
    _poser_cookie(reponse, jeton_session)
    return {"donnees": {"proprietaire": str(proprietaire)}}


@routeur.post("/sortir")
def sortir(ctx: Ctx, requete: Request, reponse: Response) -> dict:
    """Détruit la session en cours et efface le cookie.

    Idempotente : appeler cette route sans cookie, ou avec un cookie déjà
    périmé ou déjà fermé, réussit tout autant
    (`DepotComptes.fermer_session`) — se déconnecter deux fois n'est pas un
    échec.
    """
    jeton_session = requete.cookies.get(NOM_COOKIE)
    if jeton_session:
        url = _url_comptes(ctx)
        with base_de_donnees.ouvrir(url) as cx:
            DepotComptes(cx).fermer_session(jeton_session)
    reponse.delete_cookie(NOM_COOKIE, path="/")
    return {"donnees": {}}
