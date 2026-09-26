"""Ce que toutes les routes de l'API partagent : contexte, propriétaire, services.

Les routes elles-mêmes vivent dans les modules voisins, un par domaine, et
`api/routes/__init__.py` les assemble dans l'ordre d'enregistrement (lot 13).
Ici : les pannes déclarées sur toutes les routes, le routeur que chaque module
fabrique (même préfixe, mêmes pannes), les clients injectables, le contexte
de l'application, la résolution du propriétaire, et les petits services que
plusieurs domaines appellent (`_config`, `_cache`, quotas, journal).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from ourouler.api.adaptateur import Budgets
from ourouler.api.depots import DepotFichiers, DepotGenerations, DepotProfils, JournalServices
from ourouler.api.erreurs import ErreurApi, classer
from ourouler.api.modeles import Point, ReponseErreur
from ourouler.api.proprietaire import Proprietaire
from ourouler.api.quotas import Quotas
from ourouler.api.session import CODE_SANS_SESSION, MESSAGE_SANS_SESSION, MODE_PERSONNEL, FournisseurSession
from ourouler.config import Config
from ourouler.connecteurs.brouter import ClientBrouter
from ourouler.connecteurs.geocodage import ClientBAN, ClientNominatim
from ourouler.connecteurs.intervals import ClientIntervals
from ourouler.connecteurs.openmeteo_archive import ClientArchive
from ourouler.meteo.openmeteo import ClientOpenMeteo
from ourouler.noyau.profil import Depart
from ourouler.physique.commande import NOM_CACHE as NOM_CACHE_ARCHIVE

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
            "un calcul (`calcul_en_cours`), un import (`import_deja_en_cours`) ou une "
            "tâche lourde (`tache_lourde_en_cours`) occupe déjà le serveur",
        ),
        (413, "fichier trop gros (`fichier_trop_gros`)"),
        (422, "requête, fichier ou précondition refusés — voir `erreur.code`"),
        (429, "quota journalier atteint (`quota_atteint`)"),
        (500, "bug du serveur (`erreur_interne`) ou configuration invalide"),
        (502, "un service externe a répondu mal ou pas du tout — voir `erreur.code`"),
    )
}

#: Le préfixe de toutes les routes de l'API.
PREFIXE = "/api/v1"


def nouveau_routeur() -> APIRouter:
    """Le routeur d'un domaine : même préfixe et mêmes pannes déclarées pour tous.

    Chaque module de `api/routes/` porte le sien, avec le préfixe complet :
    ses routes ont ainsi le même chemin, le même `operationId` et les mêmes
    réponses déclarées que lorsqu'elles vivaient toutes dans un seul
    `api/routes.py`.
    """
    return APIRouter(prefix=PREFIXE, responses=PANNES_DECLAREES)


#: Taille maximale d'un fichier de séance déposé. Un `.ZWO` fait quelques
#: kilo-octets ; au-delà d'un mégaoctet, ce n'est plus une séance.
TAILLE_MAX_SEANCE = 1_000_000

#: Taille maximale d'un GPX déposé pour être analysé (L9.8) — un BRM de
#: 600 km, un point tous les 10 m, pèse environ 4 Mo. Ramené de 20 à 5 Mo
#: à la relecture : la lecture (gpxpy) coûte en mémoire environ 24 fois la
#: taille du fichier — mesuré le 25/09/2026, +465 Mo de pic pour 20 Mo,
#: +120 Mo pour 5 Mo (dépôt 0,8 s, analyse 1,1 s).
#: `physique.commande.DISTANCE_MAX_ANALYSE_M` borne ensuite le contenu lu.
TAILLE_MAX_PARCOURS = 5_000_000


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
    # L9.4 : l'archive météo de la calibration. Son cache sur disque est
    # **partagé** entre comptes (`PROPRIETAIRE_PARTAGE`, le vent d'un jour
    # passé est le même pour tous) et vit dans le dossier de cache du serveur.
    "archive": lambda config, http: ClientArchive(
        http=http, chemin_cache=config.cache.dossier / NOM_CACHE_ARCHIVE
    ),
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
    archive: object | None = None

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
    #: Quota journalier des calibrations (L9.4), une par jour par défaut.
    quotas_calibration: Quotas
    #: Quota journalier des imports d'historique (contre-lecture Fable du
    #: 25/09/2026) — cinq par jour par défaut, vérifié aussi **avant** la
    #: lecture du corps (`api/garde_avant_corps.py`).
    quotas_import: Quotas
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
    #: Par quel chemin les routes de calcul appellent le cœur (lot 11,
    #: `api/double_chemin.py`) : `ancien`, `nouveau` ou `double`.
    chemin_api: str = "ancien"


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
    """La `Config` de ce propriétaire — jamais « la » configuration du serveur.

    **Sa calibration est la sienne** (L9.4). En mode hébergé, le dossier de
    cache est celui du serveur, partagé : le fichier de calibration y serait
    le même pour tous les comptes, et la calibration d'un vélo nommé
    « Route » servirait à tous les « Route » du service. `fichier_calibration`
    la range donc dans le dossier du compte, à côté de son profil — et comme
    c'est cette `Config` que reçoivent `/boucles`, `/sorties`,
    `/simulations` et l'écran de FTP, c'est ce fichier-là, et lui seul,
    qu'ils relisent. En mode personnel, rien ne change : le fichier
    que `ourouler calibrer` écrit.
    """
    try:
        config = ctx.profils.config(qui)
    except Exception as e:
        raise classer(e) from e
    if ctx.session.mode == MODE_PERSONNEL:
        return config
    from ourouler.api.calibrations import fichier_du_compte

    fichier = fichier_du_compte(ctx.profils.dossier(qui))
    return replace(config, cache=replace(config.cache, fichier_calibration=fichier))


def _base_routes(config: Config, qui: Proprietaire):
    """La base des routes apprises **de ce propriétaire** ([[Q58]], 18/09/2026).

    Le seul endroit du service qui prononce le mot, avec `_cache` juste en
    dessous et `api/vie_privee.py` : doctrine §10.1, « le propriétaire entre
    au constructeur du dépôt, et nulle part ailleurs […] en hébergé, c'est la
    couche web qui construira le dépôt avec l'identifiant de l'utilisateur
    authentifié ».

    **Le fichier est ouvert même s'il n'existe pas encore**, contrairement à
    ce que font `apprentissage.commande.base_routes_existante` pour `boucle` et `sortie` —
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


def _message_occupe(nature: str | None) -> str:
    """Le refus quand une tâche lourde occupe le serveur — sans dire à qui elle appartient."""
    quoi = {"import": "un import d'historique", "calibration": "une calibration"}.get(
        nature or "", "un import ou une calibration"
    )
    return (
        f"{quoi} tourne déjà sur ce serveur, qui n'en fait qu'un à la fois — réessayez "
        "dans quelques minutes"
    )


def reponse_erreur(erreur: ErreurApi) -> JSONResponse:
    return JSONResponse(status_code=erreur.statut, content=erreur.charge())
