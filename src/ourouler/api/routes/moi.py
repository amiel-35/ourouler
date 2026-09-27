"""Le compte de la session et la vie privée : adresse, mot de passe, export, suppression."""

from __future__ import annotations

from contextlib import contextmanager

from fastapi.responses import JSONResponse, Response

from ourouler.api import base_de_donnees, vie_privee
from ourouler.api.comptes import DepotComptes, ErreurCompte, ErreurMotDePasseActuelRefuse
from ourouler.api.erreurs import ErreurApi, classer
from ourouler.api.modeles import DemandeChangementMotDePasse, DemandeConservationFichiers
from ourouler.api.proprietaire import Proprietaire
from ourouler.api.routes.commun import (
    Contexte,
    Ctx,
    Qui,
    _cache,
    _client_archive,
    _config,
    _message_occupe,
    nouveau_routeur,
)
from ourouler.api.session import SessionParCookie

routeur = nouveau_routeur()


# --- vie privée : export et suppression ----------------------------------------
#
# Un propriétaire récupère ce qui le concerne, et peut en demander l'effacement. La frontière — le tracé est
# collectif, le lien est personnel — et ce qui en découle sont expliqués dans
# `api/vie_privee.py`, qui fait le travail ; ces deux routes ne font que
# résoudre le propriétaire et sa `Config`, comme toutes les autres.


@routeur.get("/moi/export")
def exporter_mes_donnees(ctx: Ctx, qui: Qui):
    """Toutes les données personnelles de ce propriétaire, dans une archive ZIP.

    Un fichier `LISEZ-MOI.txt` à la racine dit ce qu'est chaque entrée — un
    export que seul le code sait lire ne remplit pas son office. L'archive n'est **pas compressée** : voir
    `api/vie_privee.py` pour pourquoi (c'est ce qui garde le balayage
    d'isolation capable de la couvrir).

    **Pas de `_config(ctx, qui)` ici** : cette route doit rester utilisable
    par un propriétaire qui n'a encore rien écrit — exiger sa `Config` entière
    échouerait sur un profil incomplet, puisque les sections personnelles ne
    s'héritent pas du socle partagé. `dossier_cache()` est le seul réglage
    dont `vie_privee.construire_export` se sert, et c'est un réglage serveur,
    pas un profil.
    """
    with _comptes_du_deploiement(ctx) as comptes:
        choix = comptes.choix_conservation_du_proprietaire(qui) if comptes is not None else None
    try:
        archive = vie_privee.construire_export(
            qui,
            profils=ctx.profils,
            fichiers=ctx.fichiers,
            journal=ctx.journal,
            dossier_cache=ctx.dossier_cache,
            choix_conservation=choix,
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


@routeur.get("/moi")
def mon_compte(ctx: Ctx, qui: Qui) -> dict:
    """L'adresse du compte de la session en cours — pour l'écran « Mon compte » du front.

    `email` vaut `None` sur un déploiement sans base de comptes (mode personnel, ou
    hébergé sans `SessionParCookie`) : il n'y a alors aucun compte à décrire, ce n'est
    pas une panne — même parti pris que `_comptes_du_deploiement` pour `DELETE /moi`.
    """
    with _comptes_du_deploiement(ctx) as comptes:
        compte = comptes.compte_du_proprietaire(qui) if comptes is not None else None
    return {
        "proprietaire": str(qui),
        "donnees": {"email": compte.email if compte is not None else None},
    }


def _sans_comptes() -> ErreurApi:
    return ErreurApi(
        code="comptes_indisponibles",
        message="ce déploiement ne gère pas de comptes — rien à changer",
        statut=404,
    )


@routeur.get("/moi/fichiers-origine")
def etat_conservation_fichiers(ctx: Ctx, qui: Qui) -> dict:
    """Le choix de ce compte : garde-t-il ses fichiers d'origine, et combien en a-t-il ?

    Pour Réglages → Mon compte : « Vous gardez vos fichiers d'origine
    (N fichiers) » ou « Vous ne gardez pas vos fichiers d'origine ». `garder`
    vaut `True` par défaut sur un déploiement sans base de comptes (mode
    personnel) — il n'y a alors pas de choix à faire, les fichiers bruts du
    cache local ne sont jamais effacés d'office.
    """
    from ourouler.api import taches_fond

    with _comptes_du_deploiement(ctx) as comptes:
        choix = comptes.choix_conservation_du_proprietaire(qui) if comptes is not None else None
    garder = choix.garder if choix is not None else True
    config = _config(ctx, qui)
    nombre = _cache(config, qui, conserver_brut=garder).nombre_bruts()
    tache = taches_fond.dernier(str(qui), taches_fond.NATURE_CONSERVATION)
    return {
        "proprietaire": str(qui),
        "donnees": {
            "garder": garder,
            "depuis": choix.depuis.isoformat() if choix is not None and choix.depuis is not None else None,
            "nombre_fichiers": nombre,
            # Un rechargement de page pendant l'effacement ne doit pas
            # perdre le suivi : `tache` n'est rendue que tant qu'elle tourne
            # encore, `FichiersOrigineVolet` reprend son interrogation dès
            # qu'elle la voit — sinon l'écran proposerait de nouveau
            # « Garder » alors que la purge efface encore.
            "tache": tache.json() if tache is not None and tache.statut == "en_cours" else None,
        },
    }


def _tache_conservation_en_cours(qui: Proprietaire):
    """Le job d'effacement de ce compte, s'il tourne encore — sinon `None`."""
    from ourouler.api import taches_fond

    tache = taches_fond.dernier(str(qui), taches_fond.NATURE_CONSERVATION)
    return tache if tache is not None and tache.statut == "en_cours" else None


@routeur.put("/moi/fichiers-origine")
def definir_conservation_fichiers(ctx: Ctx, qui: Qui, corps: DemandeConservationFichiers):
    """Change le choix de ce compte.

    **Revenir à « garder »** (`corps.garder` vrai) ne vaut que pour les
    imports suivants — rien à faire de plus, la réponse est immédiate (200).
    Refusée (409) tant que la tâche d'effacement de ce compte tourne encore :
    sans ce refus, le choix repasserait à « garder » pendant que la purge
    dérive et efface encore ses fichiers, sous le nez de la personne.

    **Passer à « ne pas garder »** pose le choix tout de suite, puis lance
    une tâche de fond (202, comme un import) : chaque sortie qu'une
    calibration pourrait retenir est dérivée — l'archive météo est encore
    appelable, le fichier est encore là — puis tous les fichiers d'origine
    du compte disparaissent d'un coup (`services.derive.purger_avec_derivation`).
    Dériver avant d'effacer est ce qui tient la promesse de l'écran : sans
    lui, toutes les sorties passeraient « à redéposer » — l'inverse de ce
    que ce choix promet. `GET /moi/fichiers-origine/{id_job}` suit son
    avancement, et `GET /moi/fichiers-origine` la retrouve après un
    rechargement.

    Si la tâche ne peut pas être lancée (verrou serveur entier déjà tenu par
    un import, une calibration ou un autre effacement — 409
    `tache_lourde_en_cours` —, ou toute autre panne au lancement), le choix
    posé juste avant est **rétabli** : un refus est un refus complet, jamais
    à moitié appliqué.

    L'écran doit avoir fait confirmer le coût avant d'appeler cette route ;
    elle-même ne redemande rien.

    404 `comptes_indisponibles` sur un déploiement sans base de comptes : ce
    choix n'a de sens que pour un compte du service.
    """
    if corps.garder:
        return _revenir_a_garder(ctx, qui)
    return _passer_a_ne_pas_garder(ctx, qui)


def _revenir_a_garder(ctx: Contexte, qui: Proprietaire) -> dict:
    """`corps.garder` vrai : rien à dériver ni à effacer, le choix se pose directement."""
    from ourouler.api import taches_fond

    if _tache_conservation_en_cours(qui) is not None:
        raise ErreurApi(
            code="tache_lourde_en_cours",
            message=_message_occupe(taches_fond.NATURE_CONSERVATION),
            statut=409,
        )
    with _comptes_du_deploiement(ctx) as comptes:
        if comptes is None:
            raise _sans_comptes()
        try:
            choix = comptes.definir_conservation_du_proprietaire(qui, garder=True)
        except ErreurCompte as e:
            raise _sans_comptes() from e
    assert choix.depuis is not None  # toujours posé à `now()` par l'appel ci-dessus
    return {
        "proprietaire": str(qui),
        "donnees": {"garder": True, "depuis": choix.depuis.isoformat(), "tache": None},
    }


def _passer_a_ne_pas_garder(ctx: Contexte, qui: Proprietaire):
    """`corps.garder` faux : pose le choix, puis lance la tâche de fond — voir le module."""
    from ourouler.api import taches_fond
    from ourouler.services import derive

    # Le choix se pose tout de suite, avant de lancer la tâche — c'est ce qui
    # permet à `GET` de dire aussitôt le bon état pendant que la tâche
    # démarre. `ancien` garde de quoi rétablir si le lancement échoue (verrou
    # tenu, panne) : un refus ne doit rien changer.
    with _comptes_du_deploiement(ctx) as comptes:
        if comptes is None:
            raise _sans_comptes()
        if comptes.compte_du_proprietaire(qui) is None:
            raise _sans_comptes()
        ancien = comptes.choix_conservation_du_proprietaire(qui)
        try:
            choix = comptes.definir_conservation_du_proprietaire(qui, garder=False)
        except ErreurCompte as e:
            raise _sans_comptes() from e
    assert choix.depuis is not None

    config = _config(ctx, qui)
    cache = _cache(config, qui, conserver_brut=False)
    client_archive = _client_archive(ctx, config)

    def travailler(job):
        return derive.purger_avec_derivation(
            cache,
            client_archive,
            verifier=job.verifier_annulation,
            avancer=lambda traites, total: job.avancer(traites, total),
        )

    def retablir() -> None:
        garder_avant = ancien.garder if ancien is not None else True
        with _comptes_du_deploiement(ctx) as comptes:
            if comptes is not None:
                comptes.definir_conservation_du_proprietaire(qui, garder=garder_avant)

    try:
        job = taches_fond.lancer(str(qui), taches_fond.NATURE_CONSERVATION, travailler)
    except taches_fond.ErreurTacheEnCours as occupe:
        retablir()
        raise ErreurApi(
            code="tache_lourde_en_cours",
            message=_message_occupe(occupe.nature),
            statut=409,
        ) from None
    except Exception as e:
        retablir()
        raise classer(e) from e

    return JSONResponse(
        status_code=202,
        content={
            "proprietaire": str(qui),
            "donnees": {"garder": False, "depuis": choix.depuis.isoformat(), "tache": job.json()},
        },
    )


@routeur.get("/moi/fichiers-origine/{id_job}")
def etat_job_conservation_fichiers(ctx: Ctx, qui: Qui, id_job: str) -> dict:
    """Où en est l'effacement lancé par `PUT /moi/fichiers-origine` — à interroger périodiquement.

    Même cloisonnement que `GET /activites/import/{id}` : l'identifiant d'un
    autre propriétaire, ou d'une tâche d'une autre nature, rend
    `fichier_introuvable`.
    """
    from ourouler.api import taches_fond

    job = taches_fond.trouver(str(qui), id_job, taches_fond.NATURE_CONSERVATION)
    if job is None:
        raise ErreurApi(
            code="fichier_introuvable",
            message=f"effacement {id_job} : introuvable, ou appartenant à quelqu'un d'autre",
            statut=404,
        )
    return {"proprietaire": str(qui), "donnees": job.json()}


@routeur.post("/moi/mot-de-passe")
def changer_mon_mot_de_passe(ctx: Ctx, qui: Qui, corps: DemandeChangementMotDePasse) -> dict:
    """Change le mot de passe du compte de la session en cours — l'ancien doit être vérifié.

    Refuse `comptes_indisponibles` (404) sur un déploiement sans base de comptes ou sans
    compte lié à cette session — même code que les quatre routes de comptes et sessions
    pour la même situation. Contrairement à `POST /reinitialiser`, les autres sessions
    ouvertes de ce compte ne sont **pas** fermées : voir `DepotComptes.changer_mot_de_passe`.
    """
    with _comptes_du_deploiement(ctx) as comptes:
        if comptes is None:
            raise ErreurApi(
                code="comptes_indisponibles",
                message="ce déploiement ne gère pas de comptes — rien à changer",
                statut=404,
            )
        compte = comptes.compte_du_proprietaire(qui)
        if compte is None:
            raise ErreurApi(
                code="comptes_indisponibles",
                message="aucun compte lié à cette session",
                statut=404,
            )
        try:
            comptes.changer_mot_de_passe(
                compte.identifiant, corps.mot_de_passe_actuel, corps.nouveau_mot_de_passe
            )
        except ErreurMotDePasseActuelRefuse as e:
            raise ErreurApi(
                code="mot_de_passe_actuel_refuse", message="mot de passe actuel refusé", statut=401
            ) from e
    return {"proprietaire": str(qui), "donnees": {}}


@routeur.delete("/moi")
def supprimer_mes_donnees(ctx: Ctx, qui: Qui) -> dict:
    """Efface les données personnelles de ce propriétaire.

    Idempotent : appeler cette route sur un propriétaire qui n'a rien laissé
    rend des compteurs à zéro, pas une erreur. Ce qui n'est **pas** effacé —
    les routes apprises, collectives — est nommé dans `donnees.conserve`,
    jamais tu.

    **Ferme aussi le compte, quand ce déploiement en a un** (`SessionParCookie`) :
    `DepotComptes.supprimer_compte_du_proprietaire` efface la ligne `comptes`
    liée, et la cascade du schéma révoque du même coup ses invitations et ses
    sessions ouvertes — le mot de passe ne rouvre plus rien après cet appel.
    En mode personnel ou hébergé sans base de comptes, il n'y a pas de compte
    à fermer et `donnees.supprime` ne porte alors pas la clé `"compte"`.

    **Pas de `_config(ctx, qui)` ici non plus**, même
    raison qu'à l'export ci-dessus : l'idempotence promise par ce docstring
    casserait sur un profil incomplet si cette route exigeait la `Config`
    entière du propriétaire pour obtenir un seul réglage serveur.
    """
    from ourouler.api import taches_fond

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
    except (vie_privee.TacheNonArretee, taches_fond.SuppressionDejaEnCours) as refus:
        raise ErreurApi(code=refus.code, message=refus.message, statut=409) from None
    except Exception as e:
        raise classer(e) from e
    return {"proprietaire": str(qui), "donnees": donnees}
