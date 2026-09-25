"""Les routes de l'API, déduites des vingt écrans des maquettes.

Toutes sont préfixées `/api/v1`. Toutes celles qui calculent rendent la même
enveloppe — `{donnees, avertissements, duree_ms, budget}` — et toutes celles
qui échouent rendent la même forme d'erreur (`erreurs.py`).

Le propriétaire traverse **chaque** requête : la dépendance `proprietaire`
le résout, et il est passé en premier argument à tout accès aux données
(doctrine §10.2). Aucune route ne lit un fichier de configuration
elle-même : elle demande sa `Config` au dépôt, pour ce propriétaire-là.

Ce qui n'est **pas** exposé, et pourquoi : `--synchroniser`, `routes
apprendre --appliquer`, `calibrer` écrivent dans le cache du serveur et
durent des minutes — ce sont des gestes d'administration que le mainteneur
fait en ligne de commande, et aucun écran des maquettes ne les demande.
`inventaire --importer DOSSIER` reste lui aussi hors API : c'est une lecture
d'un chemin sur le **système de fichiers du serveur**, pas un dépôt du
cycliste — l'exposer ferait de l'API une console d'administration.

**Ce que L9.2 expose, `POST /activites/import`, est différent** : un
cycliste sans Intervals dépose **ses propres octets** — fichiers isolés ou
archive d'export Strava/Garmin — jamais un chemin. C'est le mécanisme que
`Cache.indexer_dossier` appelle en CLI (`activites/import_archive.py`),
rejoué ici sur des octets reçus par HTTP et bornés (taille, nombre de
fichiers, décompression, chemins), pas sur un dossier du serveur
(`docs/sprint9_contrat.md`, lot L9.2).
"""

from __future__ import annotations

import tempfile
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, File, Query, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response

from ourouler import __version__
from ourouler.api import base_de_donnees, vie_privee, vues
from ourouler.api.adaptateur import Avertissement, Budgets, executer_commande, namespace
from ourouler.api.comptes import DepotComptes, ErreurInvitationRefusee
from ourouler.api.depots import (
    DepotFichiers,
    DepotGenerations,
    DepotProfils,
    Fichier,
    JournalServices,
    schema_des_modifications,
)
from ourouler.api.erreurs import ErreurApi, classer, classer_avertissement, secrets_de
from ourouler.api.modeles import (
    ApercuZones,
    DemandeBoucle,
    DemandeConnexion,
    DemandeEntree,
    DemandeSimulation,
    DemandeSortie,
    DemandeVitesseCompteur,
    Point,
    ReponseErreur,
    TexteUtile,
)
from ourouler.api.proprietaire import Proprietaire
from ourouler.api.quotas import Quotas
from ourouler.api.session import (
    CODE_SANS_SESSION,
    MESSAGE_SANS_SESSION,
    MODE_PERSONNEL,
    NOM_COOKIE,
    FournisseurSession,
    SessionParCookie,
)
from ourouler.config import Config, Depart
from ourouler.connecteurs.brouter import ClientBrouter
from ourouler.connecteurs.geocodage import ClientBAN, ClientNominatim
from ourouler.connecteurs.intervals import ClientIntervals
from ourouler.erreurs import ErreurConfig, ErreurUtilisateur
from ourouler.meteo.openmeteo import ClientOpenMeteo

#: Les pannes déclarées sur **toutes** les routes, et non route par route.
#:
#: Les quatre écrans d'échec des maquettes ne sont pas rattachés à une route
#: mais à un code (`erreurs.CODES_PANNE`), et n'importe quelle route de calcul
#: peut rendre n'importe lequel : une liste par route se périmerait sans
#: bruit. Déclarer la forme une fois, avec l'énumération complète des codes,
#: donne à F2 de quoi brancher ses écrans sans lire le code de F1.
PANNES_DECLAREES: dict[int | str, dict] = {
    code: {
        "model": ReponseErreur,
        "description": libelle,
    }
    for code, libelle in (
        (400, "requête refusée — voir `erreur.code`"),
        (401, "aucune session ouverte (`session_absente`) — se connecter, ne pas réessayer"),
        (404, "route ou fichier introuvable — voir `erreur.code`"),
        (
            409,
            "un calcul (`calcul_en_cours`) ou un import (`import_deja_en_cours`) occupe "
            "déjà le serveur",
        ),
        (413, "fichier trop gros (`fichier_trop_gros`)"),
        (422, "requête ou fichier refusés — voir `erreur.code`"),
        (429, "quota journalier de générations atteint (`quota_atteint`)"),
        (500, "bug du serveur (`erreur_interne`) ou configuration invalide"),
        (502, "un service externe a répondu mal ou pas du tout — voir `erreur.code`"),
    )
}

routeur = APIRouter(prefix="/api/v1", responses=PANNES_DECLAREES)

#: Taille maximale d'un fichier de séance déposé. Un `.ZWO` fait quelques
#: kilo-octets ; au-delà d'un mégaoctet, ce n'est plus une séance.
TAILLE_MAX_SEANCE = 1_000_000


#: **La convention d'injection de l'API, tranchée le 17/09/2026.**
#:
#: Ce qu'on injecte est un **transport** — un `httpx.Client`, à transport
#: bouchonné dans un test — et l'API l'habille du connecteur qui va avec, au
#: moment de l'appel, avec l'URL et les identifiants du **profil du
#: propriétaire de la requête**. Un connecteur déjà construit est accepté
#: aussi, et pris tel quel.
#:
#: **Aucune exception par service.** La règle précédente en faisait deux, pour
#: BRouter et Intervals, au motif que leur connecteur veut en plus une URL et
#: une clé. Mais ces deux valeurs sont dans le profil : la *fabrique* ne le
#: connaît pas (elle est appelée avant toute requête), la *route* si. Habiller
#: ici et non là-bas supprime le cas particulier — `client_brouter=` veut dire
#: exactement ce que veut dire `client_meteo=`, et un appelant n'a plus à
#: savoir lequel des cinq connecteurs a besoin de quoi.
#:
#: Habiller au moment de l'appel a un second effet, voulu : le connecteur est
#: construit **par propriétaire**, avec sa clé à lui. Une clé habillée une fois
#: pour toutes dans la fabrique serait celle du premier venu servie à tous —
#: la fuite que `depots.py` refuse déjà pour le socle.
FABRIQUES_CONNECTEUR: dict[str, Callable[[Config, httpx.Client], object]] = {
    "brouter": lambda config, http: ClientBrouter(
        config.brouter, http=http, evitements=config.evitements
    ),
    "meteo": lambda config, http: ClientOpenMeteo(http=http),
    "intervals": lambda config, http: ClientIntervals(
        config.intervals.athlete_id, config.intervals.api_key, http=http
    ),
    "ban": lambda config, http: ClientBAN(http=http),
    "nominatim": lambda config, http: ClientNominatim(http=http),
}


@dataclass
class Clients:
    """Les clients externes, injectables — c'est ce qui rend l'API testable.

    `None` partout en service : chaque commande du cœur fabrique alors le
    sien, comme depuis la ligne de commande. Les tests passent un transport
    bouchonné, et aucun test ne touche le réseau (règle absolue 3).

    Chaque champ porte, au choix, un `httpx.Client` — habillé par
    `connecteur()`, voir `FABRIQUES_CONNECTEUR` — ou un connecteur déjà
    construit. C'est la **même** règle pour les cinq.
    """

    brouter: object | None = None
    meteo: object | None = None
    intervals: object | None = None
    ban: object | None = None
    nominatim: object | None = None

    def connecteur(self, service: str, config: Config) -> object | None:
        """Le connecteur de ce service pour **ce** propriétaire, ou `None`.

        `None` veut dire « la commande du cœur fabriquera le sien », ce qui est
        le comportement de service. Un `httpx.Client` est habillé ici, avec le
        profil du propriétaire de la requête.
        """
        donne = getattr(self, service)
        if not isinstance(donne, httpx.Client):
            return donne
        return FABRIQUES_CONNECTEUR[service](config, donne)


@dataclass
class Contexte:
    """Ce que l'application pose sur elle-même, et que les routes retrouvent."""

    profils: DepotProfils
    fichiers: DepotFichiers
    #: Les GPX des propositions d'une génération, en mémoire (Q40 g).
    generations: DepotGenerations
    clients: Clients
    budgets: Budgets
    #: Quota journalier de générations coûteuses par compte (L9.3) —
    #: `POST /sorties`, `POST /boucles`. Le mode personnel n'est pas
    #: concerné — voir `_verifier_quota`.
    quotas: Quotas
    #: Quota journalier séparé pour `GET /meteo` (L9.3, poste distinct :
    #: ~50 appels par consultation contre ~150 par génération).
    quotas_meteo: Quotas
    journal: JournalServices
    #: **Comment cette application sait qui parle** (`api/session.py`). Injecté
    #: par la fabrique ; les routes ne le choisissent pas, elles l'utilisent.
    session: FournisseurSession
    #: Le dossier de cache du **serveur** — `[cache]`, un réglage commun
    #: (Q35), pas le profil d'un propriétaire : à la différence de tout ce
    #: qui précède, il n'a donc pas de clause. Ajouté le 21/09/2026 pour
    #: `GET /moi/export` et `DELETE /moi` (`api/vie_privee.py`), qui n'ont
    #: jamais eu besoin que de ce chemin et exigeaient jusque-là la `Config`
    #: entière d'un propriétaire rien que pour l'obtenir — ce qui échoue
    #: maintenant, à raison, pour qui n'a pas encore écrit son tiers 3.
    dossier_cache: Path


def contexte(requete: Request) -> Contexte:
    return requete.app.state.ourouler


def proprietaire(requete: Request) -> Proprietaire:
    """Le propriétaire de la requête — ou un refus, jamais un défaut.

    **Le point du lot L7.A.** Cette fonction rendait `PROPRIETAIRE_LOCAL` quoi
    qu'il arrive : une requête anonyme obtenait les données du mainteneur, et
    le commentaire annonçait qu'« F3 remplacera `resoudre` par la session ».
    C'est fait. Ce qui la remplace n'est pas une méthode d'authentification —
    aucune n'est choisie, ce serait un arbitrage du mainteneur — mais
    l'**interface** derrière laquelle elle se branchera : le fournisseur de
    session, injecté dans le contexte.

    Deux issues, et deux seulement :

    - une session est ouverte → son propriétaire, et les dépôts sont servis
      pour lui ;
    - aucune session → **401**. Jamais un profil par défaut, jamais le
      propriétaire local en silence. Le refus est la seule réponse qui ne
      fabrique pas de fuite quand on ignore qui parle.

    Rien de ce que le client envoie ne désigne le propriétaire : c'est le
    fournisseur qui tranche, et `tests/api/test_api_isolation_proprietaire.py`
    vérifie qu'aucune route n'offre le contraire dans son contrat publié.
    """
    qui = contexte(requete).session.ouvrir(requete)
    if qui is None:
        raise ErreurApi(
            code=CODE_SANS_SESSION,
            message=MESSAGE_SANS_SESSION,
            statut=401,
        )
    return qui


#: Les deux dépendances que **toute** route reçoit : ce que le serveur sait
#: faire, et pour qui il le fait. Écrites en `Annotated` pour que la clause de
#: propriétaire tienne en un mot dans chaque signature — une clause qu'on
#: oublie parce qu'elle est longue à écrire n'est pas une clause.
Ctx = Annotated[Contexte, Depends(contexte)]
Qui = Annotated[Proprietaire, Depends(proprietaire)]


def _config(ctx: Contexte, qui: Proprietaire) -> Config:
    """La `Config` de ce propriétaire — jamais « la » configuration du serveur."""
    try:
        return ctx.profils.config(qui)
    except Exception as e:
        raise classer(e) from e


def _base_routes(config: Config, qui: Proprietaire):
    """La base des routes apprises **de ce propriétaire** ([[Q58]], 18/09/2026).

    Le seul endroit du service qui prononce le mot, avec `_cache` juste en
    dessous et `api/vie_privee.py` : doctrine §10.1, « le propriétaire entre
    au constructeur du dépôt, et nulle part ailleurs […] en hébergé, c'est la
    couche web qui construira le dépôt avec l'identifiant de l'utilisateur
    authentifié ».

    **Le fichier est ouvert même s'il n'existe pas encore**, contrairement à
    ce que font `boucle/commande._base_routes` et son jumeau de `sortie` —
    eux s'abstiennent pour ne pas fabriquer un SQLite vide dans le cache d'un
    cycliste qui n'a rien appris. Ici il le faut : passer `None` ferait
    retomber la commande sur son propre constructeur, donc sur le
    propriétaire local, et rouvrirait exactement la fuite qu'on ferme.
    `GET /routes/{action}` l'ouvrait déjà sans condition, le fichier n'est
    donc pas une nouveauté de ce service.
    """
    from ourouler.apprentissage.commande import NOM_BASE
    from ourouler.apprentissage.routes import BaseRoutes

    try:
        return BaseRoutes(config.cache.dossier / NOM_BASE, proprietaire=str(qui))
    except Exception as e:
        raise classer(e) from e


def _cache(config: Config, qui: Proprietaire):
    """Le cache d'activités **de ce propriétaire**. Même règle que `_base_routes`."""
    from ourouler.activites.cache import Cache

    try:
        return Cache(config.cache.dossier, proprietaire=str(qui))
    except Exception as e:
        raise classer(e) from e


def _service(ctx: Contexte, config: Config, nom: str) -> object | None:
    """Le connecteur d'un service pour cette requête (voir `Clients`).

    Résolu service par service, et **à l'usage** : une route qui n'a pas
    besoin de BRouter ne doit pas échouer parce que le profil n'a pas d'URL
    de serveur BRouter.
    """
    try:
        return ctx.clients.connecteur(nom, config)
    except Exception as e:
        raise classer(e) from e


def _verifier_quota(ctx: Contexte, qui: Proprietaire, quotas: Quotas) -> None:
    """Décompte un crédit pour ce compte sur ce poste — ou refuse (L9.3).

    **Rien en mode personnel** : `ourouler api` sur la machine du mainteneur
    sert toujours `PROPRIETAIRE_LOCAL` par `SessionPersonnelle`
    (`api/session.py`), qui appelle Open-Meteo et BRouter depuis sa propre
    adresse — aucun poste partagé à protéger (doctrine §10.1). Le test porte
    sur le **mode**, pas sur l'identifiant : c'est `ctx.session.mode` qui dit
    quel produit ce processus sert, l'identifiant ne fait que suivre.

    Appelée **avant** tout travail (réservation de fichier, appel au cœur) :
    un compte au plafond ne doit rien coûter au serveur pour se l'entendre
    dire. `quotas` distingue le poste (`ctx.quotas` pour une génération,
    `ctx.quotas_meteo` pour `GET /meteo`) — deux compteurs séparés, un seul
    code de refus (`quota_atteint`).
    """
    if ctx.session.mode == MODE_PERSONNEL:
        return
    quotas.consommer(qui)


def _rembourser_quota(ctx: Contexte, qui: Proprietaire, quotas: Quotas) -> None:
    """Annule le décompte de `_verifier_quota` quand le travail a échoué (L9.3).

    **Seul un succès consomme réellement le crédit.** Une panne BRouter ou
    Open-Meteo, un `calcul_en_cours` (409, un autre calcul occupait déjà le
    serveur), ou n'importe quelle autre exception : le compte n'a rien reçu,
    il ne doit rien payer. Sans effet en mode personnel, symétrique de
    `_verifier_quota`, qui n'y a rien décompté.
    """
    if ctx.session.mode == MODE_PERSONNEL:
        return
    quotas.rembourser(qui)


def _avec_journal(ctx: Contexte, qui: Proprietaire, services: tuple[str, ...], appel):
    """Appelle une commande, retient ses succès, et rappelle la date au premier échec.

    E15 · échec, deuxième ligne de l'encart : « "Plus lues depuis le
    12 septembre" dit à quelqu'un ce qu'il a manqué ; "erreur de connexion" ne
    dit rien. » Le front ne peut pas calculer cette date, le cœur ne sait pas
    qu'il a un appelant : elle se tient ici, par propriétaire
    (`depots.JournalServices`).

    Les services sont **déclarés par la route** plutôt que devinés : une
    réponse rendue prouve que ceux dont elle dépend ont répondu, et rien de
    plus. Deviner à partir de l'erreur donnerait le contraire — on ne saurait
    que celui qui a échoué.
    """
    try:
        resultat = appel()
    except ErreurApi as erreur:
        if erreur.service is None:
            raise
        quand = ctx.journal.dernier_succes(qui, erreur.service)
        raise replace(erreur, details={**erreur.details, "dernier_succes": quand}) from erreur
    ctx.journal.noter_succes(qui, *services)
    return resultat


def _depart(point: Point | None) -> Depart | None:
    """Le point de départ de cette requête, déjà tranché par le front.

    L'API ne géocode jamais au vol : le front choisit dans la liste que rend
    `/geocodage`, et envoie des coordonnées (F0.7).
    """
    if point is None:
        return None
    return Depart(nom=point.nom, latitude=point.latitude, longitude=point.longitude)


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
        raise ErreurApi(code="invitation_invalide", message=MESSAGE_INVITATION_REFUSEE, statut=404)
    return {"donnees": {"email": etat.email, "expire_le": etat.expire_le.isoformat()}}


#: Ce que les deux routes du jeton d'invitation répondent quand il ne vaut
#: rien — **le même texte, quel que soit le motif**. Distinguer « n'existe
#: pas », « a expiré le 02/09 » et « a déjà servi » renseigne qui tient un
#: jeton périmé sur le fait qu'il a bel et bien été émis, et sur sa date
#: exacte. `GET /invitation` avait été écrite ainsi ; `POST /entrer` laissait
#: passer le message détaillé de `comptes._invitation_refusee`, et rouvrait
#: donc la porte qu'on venait de fermer (relecture du 19/09/2026).
#:
#: Les messages détaillés ne disparaissent pas pour autant : ils restent ce
#: que `DepotComptes` lève, et ce que la ligne de commande affiche au
#: mainteneur — qui a le droit de savoir *pourquoi*, puisque c'est lui qui a
#: émis le lien.
MESSAGE_INVITATION_REFUSEE = "ce lien d'invitation n'est plus valable — inconnu, expiré ou déjà utilisé"


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
            # Le motif est perdu **exprès** : voir MESSAGE_INVITATION_REFUSEE.
            raise ErreurApi(
                code="invitation_invalide", message=MESSAGE_INVITATION_REFUSEE, statut=400
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


# --- système ------------------------------------------------------------------


@routeur.get("/systeme")
def systeme(
    ctx: Ctx,
    qui: Qui,
) -> dict:
    """De quoi le front peut se servir, et combien de temps ça prend.

    Les capacités disent ce qui est renseigné — sans jamais dire avec quoi :
    le front sait qu'il peut proposer « ma semaine » si Intervals est
    renseigné, il n'a pas besoin de la clé pour ça.
    """
    config = _config(ctx, qui)
    charge: dict = {
        "proprietaire": str(qui),
        "version": __version__,
        "capacites": {
            "intervals": bool(config.intervals.renseigne),
            "brouter": bool(config.brouter.renseigne),
            "velos": [v.nom for v in config.velos],
        },
        "budgets": ctx.budgets.tous(),
    }
    if ctx.session.mode != MODE_PERSONNEL:
        # Le quota est **celui de ce compte** — sa propre donnée, jamais
        # celle d'un voisin. Sans objet en mode personnel (`_verifier_quota`).
        charge["quotas"] = {
            "generations": {"plafond": ctx.quotas.plafond, "restant": ctx.quotas.restant(qui)},
            "consultations_meteo": {
                "plafond": ctx.quotas_meteo.plafond,
                "restant": ctx.quotas_meteo.restant(qui),
            },
        }
    # **Les compteurs du cache météo ne sortent plus ici** (relecture
    # Opus, L9.3) : `appels_reels`/`appels_servis_cache` sont globaux au
    # processus, pas au compte qui interroge — les publier à n'importe quel
    # compte authentifié laisse deviner l'activité de tous les autres (une
    # fuite de voisinage, même sans identifiant nominatif dans le nombre
    # lui-même). `ctx.clients.meteo.stats()` (`ClientOpenMeteoCache`) reste
    # accessible côté serveur pour qui a la main sur le processus — journal
    # ou une future route d'administration, jamais `/systeme`.
    return charge


@routeur.get("/systeme/budgets")
def budgets(ctx: Ctx, qui: Qui) -> dict:
    """Combien de temps chaque opération prend **sur ce serveur**, et d'où vient le chiffre.

    Décision 6 du cycle UX : le front annonce une durée, et cette durée doit
    être mesurée. `source` vaut `defaut` tant que ce serveur n'a rien mesuré,
    `mesure` ensuite — un écran ne doit jamais présenter l'une pour l'autre.

    Les budgets sont ceux du **serveur**, pas d'un cycliste : cette route
    résout quand même son propriétaire et le nomme. Dispenser la seule route
    qui n'en a pas besoin ouvrirait une liste d'exceptions, et une liste
    d'exceptions se remplit toute seule (doctrine §10.1).
    """
    return {"proprietaire": str(qui), "budgets": ctx.budgets.tous()}


# --- profil -------------------------------------------------------------------


@routeur.get("/profil")
def lire_profil(
    ctx: Ctx,
    qui: Qui,
) -> dict:
    """Le profil du cycliste : départ, poids, FTP, position dans la zone, vélos, services.

    `donnees.assistant_recommande` dit si ce propriétaire n'a **jamais**
    enregistré de surcharge (`DepotProfils.surcharge` vide) — un compte
    activé mais jamais passé par l'assistant, quel qu'ait été le socle qu'il
    a lu au démarrage. Corrige le défaut constaté en vrai le 19/09/2026 : un
    compte neuf atterrissait sur l'écran du jour, qui réclame Intervals et
    échoue, au lieu de l'assistant qui construit le profil. Le premier
    `PATCH /profil` fait passer ce booléen à faux — pas un drapeau à part à
    tenir à jour, juste la conséquence de ce qui est déjà écrit sur le disque.
    """
    return {"proprietaire": str(qui), "donnees": _profil_avec_flags(ctx, qui, _config(ctx, qui))}


@routeur.patch(
    "/profil",
    # Le corps est lu à la main (`await requete.json()`) et validé par
    # `depots.valider` : il n'a donc pas de modèle Pydantic, et FastAPI ne
    # publierait rien. Ce qu'il accepte est engendré de la liste blanche
    # elle-même — voir `depots.schema_des_modifications`.
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {"application/json": {"schema": schema_des_modifications()}},
        }
    },
)
async def modifier_profil(
    ctx: Ctx,
    qui: Qui,
    requete: Request,
) -> dict:
    """Modifie ce que l'assistant demande, et rend le profil qui en résulte.

    Corps : les sections à modifier, telles qu'elles se lisent
    (`{"cycliste": {"ftp_w": 262}}`). Ce qu'un cycliste n'a pas le droit de
    modifier est **refusé** et nommé, jamais ignoré (`depots.valider`).

    Rien n'est écrit si la configuration résultante est invalide : le profil
    précédent reste, et le front reçoit le champ fautif.
    """
    try:
        corps = await requete.json()
    except Exception as e:
        raise ErreurApi(code="requete_invalide", message="corps JSON illisible", statut=400) from e
    try:
        config = ctx.profils.enregistrer(qui, corps)
    except ErreurConfig as e:
        # Ici, et seulement ici, une configuration invalide est la faute de
        # ce que le cycliste vient d'écrire : 422 et non 500.
        raise ErreurApi(code="profil_invalide", message=str(e), statut=422) from e
    except Exception as e:
        raise classer(e) from e
    return {"proprietaire": str(qui), "donnees": _profil_avec_flags(ctx, qui, config)}


def _profil_avec_flags(ctx: Contexte, qui: Proprietaire, config: Config) -> dict:
    """Le profil rendu par `vues.profil`, plus `assistant_recommande` (voir `lire_profil`).

    Factorisé pour que `GET /profil` et `PATCH /profil` rendent exactement le
    même calcul : sans ça, le front qui met à jour son état local depuis la
    réponse d'un `PATCH` (`Assistant.tsx`, `enregistrer()`) verrait le
    drapeau se figer jusqu'au prochain `GET`, alors qu'un premier `PATCH`
    est précisément ce qui doit le faire tomber.
    """
    donnees = vues.profil(config)
    donnees["assistant_recommande"] = not bool(ctx.profils.surcharge(qui))
    return donnees


@routeur.get("/profil/zones")
def lire_zones(
    ctx: Ctx,
    qui: Qui,
    velo: str | None = None,
    position: Annotated[float | None, Query(ge=-2, le=3)] = None,
) -> dict:
    """L'échelle des zones en watts, et les trois valeurs liées de l'écran de FTP.

    La troisième — la moyenne compteur attendue — dit toujours si son facteur
    est **mesuré** sur l'historique du cycliste ou **supposé** par le modèle
    (`facteur_mesure`, décision 8).
    """
    from ourouler.seance import ecran_ftp

    config = _config(ctx, qui)
    try:
        return {"proprietaire": str(qui), "donnees": ecran_ftp.rendu(config, velo, position=position)}
    except Exception as e:
        raise classer(e) from e


@routeur.post("/profil/zones/apercu")
def apercu_zones(
    ctx: Ctx,
    qui: Qui,
    demande: ApercuZones,
) -> dict:
    """Recalcule les trois valeurs liées **sans rien stocker**.

    C'est le geste de l'écran de FTP : on tape des watts ou une vitesse à
    plat, les autres valeurs suivent, et rien n'est enregistré tant que le
    cycliste n'a pas validé — auquel cas le front envoie la **position**
    obtenue ici à `PATCH /profil` (`seance.position_zone`), jamais les watts.
    """
    from ourouler.seance import ecran_ftp

    config = _config(ctx, qui)
    donnes = [
        demande.position_zone is not None,
        demande.puissance_w is not None,
        demande.vitesse_a_plat_kmh is not None,
    ]
    if sum(donnes) != 1:
        raise ErreurApi(
            code="requete_invalide",
            message="aperçu des zones : donner exactement une valeur — position_zone, "
            "puissance_w ou vitesse_a_plat_kmh (la moyenne compteur n'est pas éditable)",
            statut=400,
        )
    try:
        if demande.position_zone is not None:
            position = demande.position_zone
        else:
            position = ecran_ftp.position_pour(
                config,
                demande.velo,
                puissance_w=demande.puissance_w,
                vitesse_kmh=demande.vitesse_a_plat_kmh,
            )
        return {"proprietaire": str(qui), "donnees": ecran_ftp.rendu(config, demande.velo, position=position)}
    except Exception as e:
        raise classer(e) from e


@routeur.get("/profil/intervals")
def profil_intervals(ctx: Ctx, qui: Qui) -> dict:
    """Ce qu'Intervals.icu sait de l'athlète — FTP, poids — **pour confirmation, sans rien écrire**.

    L'étage T1 de l'accueil (`docs/ux/parcours_accueil.md` §4), une fois la
    clé Intervals posée : « on a trouvé ceci, c'est toujours d'actualité ? »
    plutôt que remplacer en silence ou reposer une question dont Intervals
    connaît déjà la réponse ([[Q64]]). Le front confirme ou corrige, puis
    envoie la valeur retenue à `PATCH /profil` comme n'importe quelle FTP ou
    masse déclarée — cette route ne fait que lire.

    401 nommé `intervals_absent` si la clé n'est pas encore posée : ce n'est
    ni une panne ni une faute, c'est un compte qui n'en est pas encore là.
    """
    from ourouler.connecteurs.intervals import ClientIntervals
    from ourouler.erreurs import ErreurIntervalsAbsent

    config = _config(ctx, qui)
    try:
        if not config.intervals.renseigne:
            raise ErreurIntervalsAbsent(
                "profil Intervals : la clé n'est pas encore renseignée pour ce compte"
            )
        client = _service(ctx, config, "intervals")
        if client is None:
            client = ClientIntervals(config.intervals.athlete_id, config.intervals.api_key)
        donnees = client.profil_athlete()
    except Exception as e:
        raise classer(e, secrets=secrets_de(config)) from e
    return {"proprietaire": str(qui), "donnees": donnees}


@routeur.post("/profil/ftp/apercu")
def apercu_ftp_depuis_terrain(
    ctx: Ctx,
    qui: Qui,
    demande: DemandeVitesseCompteur,
) -> dict:
    """T4 de l'accueil : une FTP à partir d'une vitesse au compteur et d'un terrain, **sans rien stocker**.

    Même geste que `POST /profil/zones/apercu` : la FTP rendue est un aperçu,
    le front l'affiche et l'envoie à `PATCH /profil` (`cycliste.ftp_w`) si le
    cycliste confirme. Elle est calculée à la `position_zone` déjà en
    vigueur dans la configuration — c'est établir une FTP là où il n'y en
    avait pas, pas déplacer une position (`seance.ecran_ftp.
    ftp_pour_vitesse_compteur`).
    """
    from ourouler.seance import ecran_ftp

    config = _config(ctx, qui)
    try:
        ftp_w = ecran_ftp.ftp_pour_vitesse_compteur(
            config,
            demande.velo,
            vitesse_compteur_kmh=demande.vitesse_kmh,
            denivele_m_par_km=demande.denivele_m_par_km,
        )
        config_avec_ftp = replace(config, cycliste=replace(config.cycliste, ftp_w=ftp_w))
        return {
            "proprietaire": str(qui),
            "donnees": ecran_ftp.rendu(config_avec_ftp, demande.velo),
        }
    except Exception as e:
        raise classer(e) from e


@routeur.get("/profil/ftp/generique")
def ftp_generique(ctx: Ctx, qui: Qui, velo: str | None = None) -> dict:
    """T5 de l'accueil, le fond du tunnel : une FTP à partir du seul poids, **sans rien stocker**.

    Ne peut pas échouer — `physique.litterature.ftp_defaut` ne demande que
    `cycliste.masse_kg`, qui n'est jamais facultative. C'est la garantie que
    l'entonnoir de `docs/ux/parcours_accueil.md` promet à l'étage T5 : « rien
    à demander, jamais rien [en échec] ». Même geste que les deux routes
    d'aperçu voisines : le front affiche, et envoie `cycliste.ftp_w` à
    `PATCH /profil` si la personne continue.
    """
    from ourouler.physique.litterature import ftp_defaut
    from ourouler.seance import ecran_ftp

    config = _config(ctx, qui)
    try:
        ftp_w = ftp_defaut(config.cycliste.masse_kg)
        config_avec_ftp = replace(config, cycliste=replace(config.cycliste, ftp_w=ftp_w))
        return {"proprietaire": str(qui), "donnees": ecran_ftp.rendu(config_avec_ftp, velo)}
    except Exception as e:
        raise classer(e) from e


# --- géocodage ----------------------------------------------------------------


@routeur.get("/geocodage")
def geocoder(
    ctx: Ctx,
    qui: Qui,
    # `TexteUtile` et non `str` : une adresse d'espaces ou d'octets de
    # contrôle passe `min_length` sans être une adresse. Elle partait alors
    # chez la BAN, y consommait un appel et revenait en 502 — une panne de
    # service affichée pour une saisie vide (E10).
    adresse: Annotated[TexteUtile, Query(min_length=1, max_length=200)],
    max: Annotated[int | None, Query(ge=1, le=20)] = None,
) -> dict:
    """Tous les candidats d'une adresse, notés — **l'API ne tranche jamais**.

    C'est l'inverse de la ligne de commande, et c'est écrit dans F0.7 : une
    commande doit bien partir de quelque part, donc elle retient le premier
    candidat et le dit ; un front, lui, peut montrer la liste et faire
    choisir. Les coordonnées choisies reviennent ensuite dans `depart`.
    """
    from ourouler.geocodage import commande as geocodage

    config = _config(ctx, qui)
    resultat = executer_commande(
        geocodage.executer,
        namespace(adresse=adresse, max=max),
        config,
        secrets=secrets_de(config),
        operation="geocodage",
        budgets=ctx.budgets,
        ban=_service(ctx, config, "ban"),
        nominatim=_service(ctx, config, "nominatim"),
    )
    charge = resultat.enveloppe(ctx.budgets.budget("geocodage"), qui)
    if not resultat.donnees.get("candidats"):
        # Zéro candidat **n'est pas une panne** — les services ont répondu —
        # mais l'écran d'échec « adresse introuvable » a besoin d'une phrase,
        # et une liste vide n'en est pas une.
        phrase = (
            f"aucune adresse trouvée pour « {adresse} » — préciser la commune ou le code postal"
        )
        charge["avertissements"] = [
            *charge["avertissements"],
            Avertissement(code=classer_avertissement(phrase), message=phrase).charge(),
        ]
    return charge


# --- météo --------------------------------------------------------------------


@routeur.get("/vent-depart")
def vent_depart(
    ctx: Ctx,
    qui: Qui,
    jour: str | None = None,
    heure_depart: str | None = None,
    latitude: Annotated[float | None, Query(ge=-90, le=90)] = None,
    longitude: Annotated[float | None, Query(ge=-180, le=180)] = None,
    nom: str = "Départ",
) -> dict:
    """D'où vient le vent au départ, et ce que chaque préférence donnerait (Q44).

    L'écran de demande appelle cette route **pendant** que le cycliste choisit,
    pas après : on ne demande pas une direction sans donner l'information qui
    permet de la choisir. Un point, une heure, un appel Open-Meteo — sans
    commune mesure avec `/meteo`, qui interroge toute une couronne.

    `azimuts_par_choix` porte des listes : « de travers » en rend **deux**,
    opposés. Un front qui n'en afficherait qu'un mentirait sur ce qui sera
    exploré.

    `latitude`/`longitude` remplacent le départ du profil pour cette requête
    seulement — toutes deux ou aucune, comme pour `/meteo`.
    """
    from ourouler.sortie import commande as sortie_commande

    config = _config(ctx, qui)
    if (latitude is None) != (longitude is None):
        raise ErreurApi(
            code="requete_invalide",
            message="vent au départ : latitude et longitude se donnent ensemble",
            statut=400,
        )
    lieu = (
        None if latitude is None else Depart(nom=nom, latitude=latitude, longitude=longitude)
    )
    resultat = _avec_journal(
        ctx,
        qui,
        ("openmeteo",),
        lambda: executer_commande(
            sortie_commande.executer_vent,
            namespace(jour=jour, depart=heure_depart),
            config,
            secrets=secrets_de(config),
            operation="vent-depart",
            budgets=ctx.budgets,
            client_meteo=_service(ctx, config, "meteo"),
            lieu_depart=lieu,
        ),
    )
    return resultat.enveloppe(ctx.budgets.budget("vent-depart"), qui)


@routeur.get("/meteo")
def meteo(
    ctx: Ctx,
    qui: Qui,
    heure_depart: str | None = None,
    horizon: Annotated[int | None, Query(ge=1, le=48)] = None,
    distance: Annotated[float | None, Query(gt=0)] = None,
    modele: str | None = None,
    second_avis: str | None = None,
    latitude: Annotated[float | None, Query(ge=-90, le=90)] = None,
    longitude: Annotated[float | None, Query(ge=-180, le=180)] = None,
    nom: str = "Départ",
) -> dict:
    """Pluie, vent et ressenti par direction et par heure, autour d'un point.

    `latitude`/`longitude` remplacent le départ du profil pour cette requête
    seulement — toutes deux ou aucune.
    """
    from ourouler.meteo import commande as meteo_commande

    # L9.3 : quota séparé de celui des générations — ~50 appels Open-Meteo
    # par consultation (une couronne, deux modèles), contre ~150 pour une
    # sortie ou une boucle. Pas de remboursement ici (à la différence de
    # `POST /sorties`/`POST /boucles`) : ce n'est pas demandé, et une
    # consultation ratée coûte de toute façon moins cher.
    _verifier_quota(ctx, qui, ctx.quotas_meteo)
    config = _config(ctx, qui)
    if (latitude is None) != (longitude is None):
        raise ErreurApi(
            code="requete_invalide",
            message="météo : latitude et longitude se donnent ensemble",
            statut=400,
        )
    lieu = (
        None
        if latitude is None
        else Depart(nom=nom, latitude=latitude, longitude=longitude)
    )
    resultat = executer_commande(
        meteo_commande.executer,
        namespace(
            depart=heure_depart,
            horizon=horizon,
            distance=distance,
            modele=modele,
            second_avis=second_avis,
        ),
        config,
        secrets=secrets_de(config),
        operation="meteo",
        budgets=ctx.budgets,
        client=_service(ctx, config, "meteo"),
        lieu_depart=lieu,
    )
    return resultat.enveloppe(ctx.budgets.budget("meteo"), qui)


# --- séances ------------------------------------------------------------------


@routeur.get("/seances")
def seances(
    ctx: Ctx,
    qui: Qui,
    depuis: date | None = None,
    jusqua: date | None = None,
) -> dict:
    """La semaine depuis Intervals.icu : un jour sans séance est `null`, pas une absence.

    Sans plage, les sept jours à partir d'aujourd'hui — ce que demande
    l'écran « Ma semaine ».
    """
    from ourouler.seance import commande as seance_commande

    config = _config(ctx, qui)
    debut = depuis or date.today()
    fin = jusqua or date.fromordinal(debut.toordinal() + 6)
    resultat = _avec_journal(
        ctx,
        qui,
        ("intervals",),
        lambda: executer_commande(
            seance_commande.executer,
            namespace(depuis=debut.isoformat(), jusqua=fin.isoformat()),
            config,
            secrets=secrets_de(config),
            operation="seances",
            budgets=ctx.budgets,
            client=_service(ctx, config, "intervals"),
        ),
    )
    return resultat.enveloppe(ctx.budgets.budget("seances"), qui)


@routeur.get("/seances/{jour}")
def seance_du_jour(
    ctx: Ctx,
    qui: Qui,
    jour: date,
) -> dict:
    """La séance d'un jour, étape par étape, avec la route que chaque bloc demande.

    Pas de séance ce jour-là **n'est pas une erreur** : la réponse vaut 200 et
    porte `seance: null`, comme la ligne de commande sort en 0.
    """
    from ourouler.seance import commande as seance_commande

    config = _config(ctx, qui)
    resultat = _avec_journal(
        ctx,
        qui,
        ("intervals",),
        lambda: executer_commande(
            seance_commande.executer,
            namespace(jour=jour.isoformat()),
            config,
            secrets=secrets_de(config),
            operation="seance",
            budgets=ctx.budgets,
            client=_service(ctx, config, "intervals"),
        ),
    )
    return resultat.enveloppe(ctx.budgets.budget("seance"), qui)


@routeur.post("/seances/fichier")
async def deposer_seance(
    ctx: Ctx,
    qui: Qui,
    requete: Request,
    fichier: Annotated[UploadFile, File(description=".ZWO ou .MRC")],
    jour: date | None = None,
) -> dict:
    """Dépose un `.ZWO` ou un `.MRC` et rend la séance qu'on y a lue.

    Le `.FIT` n'est pas accepté, et le dit (décision 5 du cycle UX : « V1 :
    `.ZWO` et `.MRC`. `.FIT` attend, et son absence se dit à l'écran plutôt
    que de se découvrir au moment du dépôt »).

    L'identifiant rendu se repasse à `POST /sorties` dans `fichier_seance` :
    le fichier reste chez son propriétaire, le front ne le renvoie pas.
    """
    from ourouler.seance import commande as seance_commande

    config = _config(ctx, qui)
    nom = fichier.filename or "seance"
    if nom.lower().endswith(".fit"):
        raise ErreurApi(
            code="format_non_lu",
            message="les fichiers .FIT de séance ne sont pas encore lus — déposer un "
            ".ZWO (Zwift) ou un .MRC, ou laisser la séance venir d'Intervals.icu",
            statut=422,
        )
    _refuser_sur_la_taille_annoncee(requete, nom)
    contenu = await fichier.read()
    if len(contenu) > TAILLE_MAX_SEANCE:
        raise ErreurApi(
            code="fichier_trop_gros",
            message=f"{nom} : {len(contenu)} octets — une séance n'en fait pas plus de "
            f"{TAILLE_MAX_SEANCE}",
            statut=413,
        )
    try:
        depose = ctx.fichiers.deposer(qui, nom, contenu)
    except ErreurUtilisateur as e:
        raise classer(e) from e
    resultat = executer_commande(
        seance_commande.executer,
        namespace(
            fichier_seance=str(depose.chemin),
            jour=(jour or date.today()).isoformat(),
        ),
        config,
        secrets=secrets_de(config),
        # Le cœur cite le chemin qu'on lui donne (« … : fichier vide ») ; ce
        # chemin est celui du serveur, et le nom que le cycliste reconnaît est
        # celui de son fichier.
        chemins={str(depose.chemin): nom},
        operation="seance",
        budgets=ctx.budgets,
        client=_service(ctx, config, "intervals"),
    )
    charge = resultat.enveloppe(ctx.budgets.budget("seance"), qui)
    charge["fichier"] = depose.json()
    return charge


# --- historique déposé (L9.2) --------------------------------------------------


@routeur.get("/activites/import")
def etat_import(ctx: Ctx, qui: Qui) -> dict:
    """Combien de sorties ce cycliste a déjà déposées, et sur quelle période.

    Pour l'écran « Mes sorties passées » (`front/src/ecrans/Importer.tsx`) :
    lui dire s'il a déjà déposé quelque chose avant de lui remontrer le
    dépôt. Voir `import_archive.etat` pour ce qui est compté.
    """
    from ourouler.activites import import_archive

    config = _config(ctx, qui)
    return {"proprietaire": str(qui), "donnees": import_archive.etat(_cache(config, qui))}


@routeur.get("/activites/import/{id_job}")
def etat_job_import(ctx: Ctx, qui: Qui, id_job: str) -> dict:
    """Où en est un import lancé par `POST /activites/import` — à interroger périodiquement.

    Cloisonné par propriétaire comme tout le reste : un identifiant qui
    n'appartient pas à ce propriétaire rend `fichier_introuvable`, exactement
    comme un fichier de séance qu'on n'a pas soi-même déposé — pour ne
    renseigner personne sur l'existence d'un import qu'il n'a pas lancé.
    """
    from ourouler.api import imports_fond

    job = imports_fond.trouver(str(qui), id_job)
    if job is None:
        raise ErreurApi(
            code="fichier_introuvable",
            message=f"import {id_job} : introuvable, ou appartenant à quelqu'un d'autre",
            statut=404,
        )
    return {"proprietaire": str(qui), "donnees": job.json()}


@routeur.post("/activites/import", status_code=202)
def importer_activites(
    ctx: Ctx,
    qui: Qui,
    requete: Request,
    fichiers: Annotated[
        list[UploadFile],
        File(description=".fit/.gpx/.tcx, éventuellement .gz, ou une archive .zip Strava/Garmin"),
    ],
) -> dict:
    """Lance en tâche de fond le dépôt de l'historique d'un cycliste sans Intervals
    — un invité sans capteur y trouve déjà de la valeur (routes), un porteur de
    capteur y trouve aussi son niveau ([[Q48]]).

    **202, pas 200** (suite de la relecture du 25/09/2026) : une archive
    Strava réelle (≈2 900 sorties) prend environ 16 minutes à 0,33 s/fichier,
    bien au-delà des 180 s où le front abandonne. La route rend tout de
    suite un identifiant de tâche ; `GET /activites/import/{id}` dit où elle
    en est (`en_cours`/`fini`/`echoue`, `traites`/`total`, et le rapport une
    fois finie).

    Accepte un ou plusieurs fichiers en un seul appel — `.fit`/`.gpx`/`.tcx`
    isolés, leurs `.gz`, ou une archive d'export Strava ou Garmin — et les
    indexe dans le cache de **ce** propriétaire uniquement
    (`activites/import_archive.py`, bornes de sécurité en constantes
    nommées). Réimporter la même archive ne duplique rien : une sortie
    déposée est identifiée par son contenu ([[Q62]]).

    **Un seul import à la fois, pour le serveur entier** (`api/imports_fond.py`) :
    un second demandeur, propriétaire ou pas, reçoit `import_deja_en_cours`
    (409) plutôt qu'une attente silencieuse — le serveur est petit et
    partagé avec BRouter, deux imports simultanés doubleraient le pic
    mémoire.

    **Les fichiers reçus sont recopiés dans des fichiers temporaires à nous**
    avant de rendre la main : ceux de Starlette (`UploadFile.file`) ne
    survivent pas à la fin de la requête, alors que la tâche de fond continue
    après le 202. La copie est bornée par bloc (`_copier_borne`), en plus de
    `LimiteTailleCorps` (`api/limite_corps.py`) qui a déjà refusé tout corps
    au-delà du plafond avant que Starlette n'en écrive un octet.
    """
    from ourouler.api import imports_fond

    _refuser_import_sur_la_taille_annoncee(requete)
    if not fichiers:
        raise ErreurApi(code="requete_invalide", message="aucun fichier déposé", statut=400)

    config = _config(ctx, qui)
    cache = _cache(config, qui)

    depots = _copier_en_temporaires(fichiers)
    try:
        job = imports_fond.lancer(cache, str(qui), depots)
    except imports_fond.ErreurImportEnCours:
        for _, chemin in depots:
            chemin.unlink(missing_ok=True)
        raise ErreurApi(
            code="import_deja_en_cours",
            message="un import tourne déjà sur ce serveur — réessayer une fois celui-ci "
            "terminé (GET /activites/import/{id} pour le suivre)",
            statut=409,
        ) from None
    return {"proprietaire": str(qui), "donnees": job.json()}


def _copier_en_temporaires(fichiers: list[UploadFile]) -> list[tuple[str, Path]]:
    """Recopie chaque dépôt dans un fichier temporaire propre à ce job, borné par bloc.

    Défense en profondeur : `LimiteTailleCorps` a déjà refusé tout corps de
    requête au-delà de `TAILLE_MAX_REQUETE` avant que Starlette n'écrive quoi
    que ce soit ; cette seconde borne, posée pendant la copie elle-même,
    protège des mêmes octets une seconde fois plutôt que de faire confiance à
    un seul étage. En cas de dépassement, tout ce qui a déjà été copié pour
    cet appel est effacé — un import ne part jamais à moitié écrit.
    """
    from ourouler.activites.import_archive import TAILLE_MAX_REQUETE

    chemins: list[Path] = []
    total = 0
    try:
        for fichier in fichiers:
            destination = Path(tempfile.mkstemp(prefix="ourouler-import-", suffix=".bin")[1])
            chemins.append(destination)
            with destination.open("wb") as sortie:
                while True:
                    bloc = fichier.file.read(1 << 20)
                    if not bloc:
                        break
                    total += len(bloc)
                    if total > TAILLE_MAX_REQUETE:
                        raise ErreurApi(
                            code="fichier_trop_gros",
                            message=f"{total} octets reçus — un import ne prend pas plus de "
                            f"{TAILLE_MAX_REQUETE} octets à la fois",
                            statut=413,
                        )
                    sortie.write(bloc)
    except Exception:
        for chemin in chemins:
            chemin.unlink(missing_ok=True)
        raise
    return [
        (fichier.filename or "(sans nom)", chemin) for fichier, chemin in zip(fichiers, chemins, strict=True)
    ]


# --- parcours -----------------------------------------------------------------


@routeur.post("/sorties")
def generer_sortie(
    ctx: Ctx,
    qui: Qui,
    demande: DemandeSortie,
) -> dict:
    """La séance du jour posée sur une boucle : propositions, géométrie, blocs, tenue.

    **Semi-synchrone** : le calcul se fait pendant la requête (4 à 6 secondes
    mesurées), et la réponse porte `duree_ms` — ce que ça a réellement pris —
    à côté de `budget` — ce que le front avait annoncé. Voir
    `docs/ux/api_contrat.md` pour ce que ce choix implique côté écran.

    **Deux propositions au lieu de trois n'est pas une panne** :
    `motif_deux_propositions` porte l'explication, et la réponse reste un 200.

    **Trois propositions qui se valent n'en est pas une non plus** (Q45) :
    `motif_equivalence` porte alors « ces trois boucles se valent, choisissez
    où vous voulez aller », avec ce qui, mesuré, ne les sépare pas.
    """
    from ourouler.sortie import commande as sortie_commande

    _verifier_quota(ctx, qui, ctx.quotas)
    try:
        config = _config(ctx, qui)
        carte = ctx.fichiers.reserver(
            qui, f"sortie_{demande.jour or date.today().isoformat()}.html"
        )
        seance = _chemin_seance(ctx, qui, demande.fichier_seance)
        # Q40 (g) : **aucun GPX n'est écrit ici**. Le cœur remet les trois
        # textes à `recueil_gpx` (aucun `sortie=` ne lui est passé, donc
        # aucun fichier), et c'est la route `…/propositions/{n}/gpx` qui en
        # servira un — celui que le cycliste aura choisi, et pas celui du
        # classement.
        recueillis: list[object] = []
        resultat = _avec_journal(
            ctx,
            qui,
            ("brouter", "openmeteo", "intervals"),
            lambda: executer_commande(
                sortie_commande.executer,
                namespace(
                    jour=demande.jour,
                    depart=demande.heure_depart,
                    distance=demande.distance_km,
                    direction=demande.direction,
                    candidates=demande.candidates,
                    vent=demande.vent,
                    velo=demande.velo,
                    profil=demande.profil,
                    fichier_seance=seance,
                    carte=str(carte.chemin),
                    ecraser=True,
                ),
                config,
                secrets=secrets_de(config),
                chemins={str(carte.chemin): carte.nom},
                operation="sortie",
                budgets=ctx.budgets,
                client_brouter=_service(ctx, config, "brouter"),
                client_meteo=_service(ctx, config, "meteo"),
                client_intervals=_service(ctx, config, "intervals"),
                lieu_depart=_depart(demande.depart),
                recueil_gpx=recueillis.extend,
                # Q58, même raison que `POST /boucles`.
                base_routes=_base_routes(config, qui),
            ),
        )
        donnees = vues.avec_fichiers(resultat.donnees, carte=_note(ctx, qui, carte))
        if recueillis:
            donnees = vues.avec_gpx_par_proposition(
                donnees,
                generation=ctx.generations.retenir(qui, recueillis),
                noms={int(g.numero): str(g.nom_fichier) for g in recueillis},  # type: ignore[attr-defined]
                prefixe=routeur.prefix,
            )
    except Exception:
        # L9.3 : seul un succès consomme le crédit décompté ci-dessus — une
        # panne (BRouter, Open-Meteo, calcul_en_cours, ou tout autre échec)
        # le rend.
        _rembourser_quota(ctx, qui, ctx.quotas)
        raise
    return _enveloppe_retouchee(resultat, donnees, ctx.budgets.budget("sortie"), qui)


@routeur.get("/sorties/{generation}/propositions/{numero}/gpx")
def gpx_de_proposition(
    ctx: Ctx,
    qui: Qui,
    generation: str,
    numero: int,
):
    """Le GPX **de cette proposition-là**, fabriqué au moment où on le demande.

    Q40 (g) : rien n'est écrit à la génération — deux des trois traces
    seraient jetées — et rien n'est écrit ici non plus : la réponse *est* le
    fichier. Le nom proposé au navigateur est celui que le cœur a donné
    (`sortie_20260918_n2.gpx`), pour qu'un dossier de téléchargements dise
    laquelle des trois a été emportée.

    Une génération qui n'est plus en mémoire rend 404 `generation_introuvable`
    et non 500 : l'écran redemande une recherche.
    """
    try:
        nom, texte = ctx.generations.gpx(qui, generation, numero)
    except ErreurUtilisateur as e:
        raise ErreurApi(code="generation_introuvable", message=str(e), statut=404) from e
    return Response(
        content=texte,
        media_type="application/gpx+xml",
        headers={"Content-Disposition": f'attachment; filename="{nom}"'},
    )


@routeur.post("/boucles")
def generer_boucle(
    ctx: Ctx,
    qui: Qui,
    demande: DemandeBoucle,
) -> dict:
    """Une boucle libre, sans séance : candidates, coûts, météo le long du tracé, géométrie."""
    from ourouler.boucle import commande as boucle_commande

    _verifier_quota(ctx, qui, ctx.quotas)
    try:
        config = _config(ctx, qui)
        # Q47 : sans direction, la recherche balaie tout l'horizon (comme
        # `sortie`) plutôt que de refuser — le nom réservé le dit en clair
        # plutôt que de porter un `None` littéral.
        direction_nom = demande.direction or "toutes-directions"
        gpx = ctx.fichiers.reserver(qui, f"boucle_{direction_nom}_{demande.distance_km:g}km.gpx")
        resultat = executer_commande(
            boucle_commande.executer,
            namespace(
                distance=demande.distance_km,
                direction=demande.direction,
                depart=demande.heure_depart,
                candidates=demande.candidates,
                profil=demande.profil,
                velo=demande.velo,
                puissance=demande.puissance_w,
                sortie=str(gpx.chemin),
                ecraser=True,
            ),
            config,
            secrets=secrets_de(config),
            chemins={str(gpx.chemin): gpx.nom},
            operation="boucle",
            budgets=ctx.budgets,
            client_brouter=_service(ctx, config, "brouter"),
            client_meteo=_service(ctx, config, "meteo"),
            lieu_depart=_depart(demande.depart),
            # Q58 : la colonne « connu % » est calculée contre les routes
            # que **ce** cycliste a roulées, pas contre celles du
            # propriétaire local.
            base_routes=_base_routes(config, qui),
        )
        donnees = vues.avec_fichiers(resultat.donnees, gpx=_note(ctx, qui, gpx))
    except Exception:
        # L9.3 : même remboursement que `POST /sorties` — voir sa docstring.
        _rembourser_quota(ctx, qui, ctx.quotas)
        raise
    return _enveloppe_retouchee(resultat, donnees, ctx.budgets.budget("boucle"), qui)


@routeur.post("/simulations")
def simuler(
    ctx: Ctx,
    qui: Qui,
    demande: DemandeSimulation,
) -> dict:
    """Le temps d'un GPX du dépôt à puissance constante, avec le modèle calibré."""
    from ourouler.physique import commande as physique

    config = _config(ctx, qui)
    try:
        gpx = ctx.fichiers.trouver(qui, demande.gpx)
    except ErreurUtilisateur as e:
        raise ErreurApi(code="fichier_introuvable", message=str(e), statut=404) from e
    resultat = executer_commande(
        physique.executer_simuler,
        namespace(
            gpx=str(gpx.chemin),
            puissance=demande.puissance_w,
            velo=demande.velo,
            depart=demande.heure_depart,
        ),
        config,
        secrets=secrets_de(config),
        chemins={str(gpx.chemin): gpx.nom},
        operation="simulation",
        budgets=ctx.budgets,
        client_meteo=_service(ctx, config, "meteo"),
    )
    return resultat.enveloppe(ctx.budgets.budget("simulation"), qui)


# --- inventaire et routes connues ---------------------------------------------


@routeur.get("/inventaire")
def inventaire(
    ctx: Ctx,
    qui: Qui,
    depuis: date | None = None,
) -> dict:
    """L'inventaire des sorties par vélo et par mois, **sans synchroniser**.

    La synchronisation avec Intervals.icu et l'import d'un dossier restent des
    gestes de ligne de commande : ils écrivent dans le cache du serveur et
    durent des minutes.

    **Le cache est construit ici, avec le propriétaire de la session** (Q58,
    18/09/2026). Jusque-là cette route recevait bien `qui` — le balayage
    d'isolation la voyait donc conforme — mais la commande construisait son
    `Cache` toute seule, avec le défaut `PROPRIETAIRE_LOCAL` : quel que soit
    le demandeur, elle servait l'inventaire du mainteneur. C'est la couche web
    qui nomme le propriétaire, et elle seule (doctrine §10.1).
    """
    from ourouler.activites import commande as activites

    config = _config(ctx, qui)
    resultat = executer_commande(
        activites.executer,
        namespace(depuis=depuis.isoformat() if depuis else None),
        config,
        secrets=secrets_de(config),
        operation="inventaire",
        budgets=ctx.budgets,
        cache=_cache(config, qui),
    )
    return resultat.enveloppe(ctx.budgets.budget("inventaire"), qui)


@routeur.get("/routes/{action}")
def routes_connues(
    ctx: Ctx,
    qui: Qui,
    action: str,
) -> dict:
    """Ce que les sorties passées ont appris : `stats` ou `poids` (en lecture seule).

    **La base est construite ici, avec le propriétaire de la session** (Q58,
    18/09/2026) — même correctif et même raison que `GET /inventaire`
    juste au-dessus.
    """
    from ourouler.apprentissage import commande as apprentissage

    if action not in ("stats", "poids"):
        raise ErreurApi(
            code="requete_invalide",
            message=f"routes : action « {action} » inconnue — attendu stats ou poids "
            "(apprendre reste une commande d'administration)",
            statut=404,
        )
    config = _config(ctx, qui)
    resultat = executer_commande(
        apprentissage.executer,
        namespace(action=action, appliquer=False),
        config,
        secrets=secrets_de(config),
        operation="routes",
        budgets=ctx.budgets,
        client_brouter=_service(ctx, config, "brouter"),
        base=_base_routes(config, qui),
    )
    return resultat.enveloppe(ctx.budgets.budget("routes"), qui)


# --- fichiers -----------------------------------------------------------------


@routeur.get("/fichiers/{identifiant}")
def servir_fichier(
    ctx: Ctx,
    qui: Qui,
    identifiant: str,
):
    """Le GPX (ou la carte) d'une proposition, s'il appartient à ce propriétaire.

    La vérification est faite **côté serveur**, en cherchant le fichier dans
    le dossier de ce propriétaire et nulle part ailleurs : un identifiant
    valable pour quelqu'un d'autre est introuvable ici, sans que la réponse
    dise s'il existe (doctrine §10.2).
    """
    try:
        fichier = ctx.fichiers.trouver(qui, identifiant)
    except ErreurUtilisateur as e:
        raise ErreurApi(code="fichier_introuvable", message=str(e), statut=404) from e
    return FileResponse(
        fichier.chemin,
        media_type=fichier.type_contenu,
        filename=fichier.nom,
    )


# --- vie privée : export et suppression ----------------------------------------
#
# Lot L7.B (`docs/sprint7_contrat.md`) : un propriétaire récupère ce qui le
# concerne, et peut en demander l'effacement. La frontière — le tracé est
# collectif, le lien est personnel — et ce qui en découle sont expliqués dans
# `api/vie_privee.py`, qui fait le travail ; ces deux routes ne font que
# résoudre le propriétaire et sa `Config`, comme toutes les autres.


@routeur.get("/moi/export")
def exporter_mes_donnees(ctx: Ctx, qui: Qui):
    """Toutes les données personnelles de ce propriétaire, dans une archive ZIP.

    Un fichier `LISEZ-MOI.txt` à la racine dit ce qu'est chaque entrée — un
    export que seul le code sait lire ne remplit pas son office (contrat
    sprint 7 §L7.B). L'archive n'est **pas compressée** : voir
    `api/vie_privee.py` pour pourquoi (c'est ce qui garde le balayage
    d'isolation capable de la couvrir).

    **Pas de `_config(ctx, qui)` ici** (changé le 21/09/2026) : cette route
    doit rester utilisable par un propriétaire qui n'a encore rien écrit —
    exiger sa `Config` entière échouerait sur un profil incomplet depuis que
    le tiers 3 de Q35 ne s'hérite plus du socle partagé. `dossier_cache()`
    est le seul réglage dont `vie_privee.construire_export` se sert, et c'est
    un réglage serveur (Q35), pas un profil.
    """
    try:
        archive = vie_privee.construire_export(
            qui,
            profils=ctx.profils,
            fichiers=ctx.fichiers,
            journal=ctx.journal,
            dossier_cache=ctx.dossier_cache,
        )
    except Exception as e:
        raise classer(e) from e
    return Response(
        content=archive,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="export_ourouler_{qui}.zip"'},
    )


@contextmanager
def _comptes_du_deploiement(ctx: Contexte):
    """Le dépôt des comptes de ce déploiement, ou `None` — pour `effacer_donnees`.

    `SessionParCookie` est la seule session qui porte une base de comptes
    (`api/session.py`) : `SessionPersonnelle` (un seul cycliste, pas de
    compte) et `SessionHebergee` (hébergé sans base de comptes configurée)
    n'en ouvrent jamais. `vie_privee.effacer_donnees` traite `comptes=None`
    comme « rien à fermer de ce côté », pas comme une erreur.
    """
    if not isinstance(ctx.session, SessionParCookie):
        yield None
        return
    with base_de_donnees.ouvrir(ctx.session.url) as cx:
        yield DepotComptes(cx)


@routeur.delete("/moi")
def supprimer_mes_donnees(ctx: Ctx, qui: Qui) -> dict:
    """Efface les données personnelles de ce propriétaire.

    Idempotent : appeler cette route sur un propriétaire qui n'a rien laissé
    rend des compteurs à zéro, pas une erreur. Ce qui n'est **pas** effacé —
    les routes apprises, collectives par décision du mainteneur — est nommé
    dans `donnees.conserve`, jamais tu.

    **Ferme aussi le compte, quand ce déploiement en a un** (`SessionParCookie`,
    lot RGPD-compte) : `DepotComptes.supprimer_compte_du_proprietaire` efface
    la ligne `comptes` liée, et la cascade du schéma révoque du même coup ses
    invitations et ses sessions ouvertes — le mot de passe ne rouvre plus rien
    après cet appel. En mode personnel ou hébergé sans base de comptes, il n'y
    a pas de compte à fermer et `donnees.supprime` ne porte alors pas la clé
    `"compte"`.

    **Pas de `_config(ctx, qui)` ici non plus** (changé le 21/09/2026), même
    raison qu'à l'export ci-dessus : l'idempotence promise par ce docstring
    casserait sur un profil incomplet si cette route exigeait la `Config`
    entière du propriétaire pour obtenir un seul réglage serveur.
    """
    try:
        with _comptes_du_deploiement(ctx) as comptes:
            donnees = vie_privee.effacer_donnees(
                qui,
                profils=ctx.profils,
                fichiers=ctx.fichiers,
                journal=ctx.journal,
                generations=ctx.generations,
                dossier_cache=ctx.dossier_cache,
                comptes=comptes,
            )
    except Exception as e:
        raise classer(e) from e
    return {"proprietaire": str(qui), "donnees": donnees}


# --- petits services ----------------------------------------------------------


def _refuser_sur_la_taille_annoncee(requete: Request, nom: str) -> None:
    """Refuse un envoi trop gros **sur sa taille annoncée**, avant de le lire.

    Un `.ZWO` fait quelques kilo-octets ; deux cents méga-octets sont un
    dossier de photos déposé par erreur, ou un déni de service. Lire d'abord
    et juger ensuite marche pour un dépôt et tombe au troisième simultané.

    La borne reste vérifiée après lecture : `Content-Length` vient du client,
    donc un client qui ment passe ici — c'est une garde, pas une preuve.
    """
    annoncee = requete.headers.get("content-length")
    if annoncee is None or not annoncee.isdigit():
        return
    if int(annoncee) > TAILLE_MAX_SEANCE:
        raise ErreurApi(
            code="fichier_trop_gros",
            message=f"{nom} : {annoncee} octets annoncés — une séance n'en fait pas plus de "
            f"{TAILLE_MAX_SEANCE}, le dépôt est refusé sans être lu",
            statut=413,
        )


def _refuser_import_sur_la_taille_annoncee(requete: Request) -> None:
    """Même garde que `_refuser_sur_la_taille_annoncee`, sur le plafond de l'import.

    Une archive Strava réelle pèse 665 Mo (`docs/services_externes.md`) : le
    plafond n'est donc pas celui d'une séance, mais le principe est le même.

    **Limite, dite (relecture du 25/09/2026)** : FastAPI a déjà reçu tout le
    formulaire, dans des fichiers temporaires sur disque, avant d'appeler la
    route — cette garde évite le traitement, pas la réception. Borner la
    réception demande une limite de taille de corps en amont (proxy ou
    intergiciel), comme pour `/seances/fichier`.
    """
    from ourouler.activites.import_archive import TAILLE_MAX_REQUETE

    annoncee = requete.headers.get("content-length")
    if annoncee is None or not annoncee.isdigit():
        return
    if int(annoncee) > TAILLE_MAX_REQUETE:
        raise ErreurApi(
            code="fichier_trop_gros",
            message=f"{annoncee} octets annoncés — un import ne prend pas plus de "
            f"{TAILLE_MAX_REQUETE}, le dépôt est refusé sans être traité",
            statut=413,
        )


def _note(ctx: Contexte, qui: Proprietaire, fichier: Fichier) -> Fichier | None:
    """Enregistre le fichier si le cœur l'a bien écrit, sinon `None`."""
    if not fichier.chemin.exists():
        return None
    return ctx.fichiers.enregistrer(qui, fichier)


def _chemin_seance(ctx: Contexte, qui: Proprietaire, identifiant: str | None) -> str | None:
    """Le chemin du `.ZWO`/`.MRC` déposé, ou `None` pour la séance d'Intervals."""
    if not identifiant:
        return None
    try:
        return str(ctx.fichiers.trouver(qui, identifiant).chemin)
    except ErreurUtilisateur as e:
        raise ErreurApi(code="fichier_introuvable", message=str(e), statut=404) from e


def _enveloppe_retouchee(resultat, donnees: dict, budget: dict, qui: Proprietaire) -> dict:
    """L'enveloppe d'un résultat dont les données ont été retouchées (fichiers)."""
    charge = resultat.enveloppe(budget, qui)
    charge["donnees"] = donnees
    return charge


def reponse_erreur(erreur: ErreurApi) -> JSONResponse:
    return JSONResponse(status_code=erreur.statut, content=erreur.charge())


__all__ = ["Clients", "Contexte", "reponse_erreur", "routeur"]
