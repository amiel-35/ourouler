"""Le compte de la session et la vie privée : adresse, mot de passe, export, suppression."""

from __future__ import annotations

from contextlib import contextmanager

from fastapi.responses import Response

from ourouler.api import base_de_donnees, vie_privee
from ourouler.api.comptes import DepotComptes, ErreurMotDePasseActuelRefuse
from ourouler.api.erreurs import ErreurApi, classer
from ourouler.api.modeles import DemandeChangementMotDePasse
from ourouler.api.routes.commun import Contexte, Ctx, Qui, nouveau_routeur
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
