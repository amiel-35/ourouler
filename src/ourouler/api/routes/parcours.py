"""Un GPX déjà en main : simulé à puissance constante, ou déposé puis analysé."""

from __future__ import annotations

from typing import Annotated

from fastapi import File, Request, UploadFile

from ourouler.api import calculs
from ourouler.api.double_chemin import calculer
from ourouler.api.erreurs import ErreurApi, classer
from ourouler.api.modeles import DemandeAnalyse, DemandeSimulation
from ourouler.api.reponses import ReponseCalcul, reponse_de
from ourouler.api.routes.commun import (
    TAILLE_MAX_PARCOURS,
    Ctx,
    Qui,
    _config,
    _rembourser_quota,
    _service,
    _verifier_quota,
    nouveau_routeur,
)
from ourouler.noyau.erreurs import ErreurUtilisateur

routeur = nouveau_routeur()


@routeur.post("/simulations", **reponse_de(ReponseCalcul))
def simuler(
    ctx: Ctx,
    qui: Qui,
    demande: DemandeSimulation,
) -> dict:
    """Le temps d'un GPX du dépôt à puissance constante, avec le modèle calibré."""
    from ourouler.services import physique

    config = _config(ctx, qui)
    try:
        gpx = ctx.fichiers.trouver(qui, demande.gpx)
    except ErreurUtilisateur as e:
        raise ErreurApi(code="fichier_introuvable", message=str(e), statut=404) from e
    resultat = calculer(
        ctx.chemin_api,
        config,
        route="simulations",
        operation="simulation",
        ancien=physique.executer_simuler,
        nouveau=calculs.simuler,
        options={
            "gpx": str(gpx.chemin),
            "puissance": demande.puissance_w,
            "velo": demande.velo,
            "depart": demande.heure_depart,
        },
        clients={"client_meteo": _service(ctx, config, "meteo")},
        chemins={str(gpx.chemin): gpx.nom},
        budgets=ctx.budgets,
    )
    return resultat.enveloppe(ctx.budgets.budget("simulation"), qui)


# --- un parcours déjà en main, à analyser -------------------------------------


@routeur.post("/parcours/fichier")
async def deposer_parcours(
    ctx: Ctx,
    qui: Qui,
    requete: Request,
    fichier: Annotated[UploadFile, File(description=".GPX à analyser")],
) -> dict:
    """Dépose le GPX d'un parcours **déjà en main** (imposé d'un BRM, d'une Flèche, boucle
    de club) — l'identifiant rendu se repasse à `POST /parcours/analyser` dans `gpx`.

    Seul le `.GPX` est accepté : `DepotHistorique` sait déjà lire un `.FIT`/`.TCX`,
    mais pour des **sorties passées**, pas pour un parcours qu'on va rouler — deux usages
    du dépôt de fichier, deux routes, comme `/seances/fichier` et `/activites/import` sont
    déjà séparées pour la même raison.
    """
    nom = fichier.filename or "parcours"
    if not nom.lower().endswith(".gpx"):
        raise ErreurApi(
            code="format_non_lu",
            message="un parcours à analyser se dépose en .GPX — pour un .FIT ou un .TCX, "
            "voir « mes sorties passées »",
            statut=422,
        )
    _refuser_parcours_sur_la_taille_annoncee(requete, nom)
    contenu = await fichier.read()
    if len(contenu) > TAILLE_MAX_PARCOURS:
        raise ErreurApi(
            code="fichier_trop_gros",
            message=f"{nom} : {len(contenu)} octets — un parcours n'en fait pas plus de "
            f"{TAILLE_MAX_PARCOURS}",
            statut=413,
        )
    try:
        depose = ctx.fichiers.deposer(qui, nom, contenu)
    except ErreurUtilisateur as e:
        raise classer(e) from e
    # Le lecteur cite le chemin qu'on lui donne ; ce chemin est celui du
    # serveur, le cycliste reconnaît le nom de son fichier (même geste que
    # `/seances/fichier`, via `calculer(chemins=...)`).
    chemins = {str(depose.chemin): nom}
    # Lu tout de suite : un GPX mal formé ou trop long se dit au dépôt, pas
    # à l'analyse — même geste que `/seances/fichier`, qui lit la séance
    # déposée avant de rendre la main.
    from ourouler.boucle.gpx import lire_gpx_parcours
    from ourouler.services.physique import DISTANCE_MAX_ANALYSE_M

    try:
        trace, avertissements_trace = lire_gpx_parcours(depose.chemin)
    except ErreurUtilisateur as e:
        raise classer(e, chemins=chemins) from e
    if len(trace.points) < 2 or trace.distance_m <= 0:
        raise ErreurApi(
            code="fichier_illisible",
            message=f"{nom} : un seul point, ou des points tous au même endroit — il n'y a rien à parcourir",
            statut=422,
        )
    if trace.distance_m > DISTANCE_MAX_ANALYSE_M:
        raise ErreurApi(
            code="requete_invalide",
            message=f"{nom} : {trace.distance_m / 1000:.0f} km, au-delà des "
            f"{DISTANCE_MAX_ANALYSE_M / 1000:.0f} km qu'un parcours à analyser accepte",
            statut=422,
        )
    return {
        "fichier": depose.json(),
        "apercu": {
            "nom": trace.nom,
            "distance_km": round(trace.distance_m / 1000.0, 3),
            "denivele_m": trace.denivele_m,
            # « 3 traces enchaînées », « un trou de 12 km entre… » — dit dès
            # le dépôt, avant qu'on règle l'heure de départ.
            "avertissements": avertissements_trace,
        },
    }


@routeur.post("/parcours/analyser", **reponse_de(ReponseCalcul))
def analyser_parcours(
    ctx: Ctx,
    qui: Qui,
    demande: DemandeAnalyse,
) -> dict:
    """La météo et la durée porte à porte d'un parcours déjà en main.

    `ourouler simuler` retourné dans l'autre sens (voir la docstring
    d'`executer_analyser`) : le GPX n'est pas une candidate choisie par le moteur, c'est
    celui qu'on va rouler — l'imposé d'un brevet, une boucle de club. Compte dans les
    **consultations météo** (`ctx.quotas_meteo`), pas dans les générations.

    **Seule une météo rendue consomme la consultation** : fichier introuvable,
    GPX refusé, toute erreur — et aussi une réponse 200 **sans** météo (panne
    Open-Meteo, départ au-delà de l'horizon), où
    la durée est servie mais la consultation n'a rien rapporté — la rembourse.
    """
    from ourouler.services import physique

    _verifier_quota(ctx, qui, ctx.quotas_meteo)
    try:
        config = _config(ctx, qui)
        try:
            gpx = ctx.fichiers.trouver(qui, demande.gpx)
        except ErreurUtilisateur as e:
            raise ErreurApi(code="fichier_introuvable", message=str(e), statut=404) from e
        resultat = calculer(
            ctx.chemin_api,
            config,
            route="parcours-analyser",
            operation="analyse",
            ancien=physique.executer_analyser,
            nouveau=calculs.analyser,
            options={
                "gpx": str(gpx.chemin),
                "puissance": demande.puissance_w,
                "velo": demande.velo,
                "depart": demande.heure_depart,
            },
            clients={"client_meteo": _service(ctx, config, "meteo")},
            chemins={str(gpx.chemin): gpx.nom},
            budgets=ctx.budgets,
        )
    except Exception:
        _rembourser_quota(ctx, qui, ctx.quotas_meteo)
        raise
    if resultat.donnees.get("meteo") is None:
        _rembourser_quota(ctx, qui, ctx.quotas_meteo)
    return resultat.enveloppe(ctx.budgets.budget("analyse"), qui)


def _refuser_parcours_sur_la_taille_annoncee(requete: Request, nom: str) -> None:
    """Même garde que `_refuser_sur_la_taille_annoncee`, sur le plafond d'un parcours."""
    annoncee = requete.headers.get("content-length")
    if annoncee is None or not annoncee.isdigit():
        return
    if int(annoncee) > TAILLE_MAX_PARCOURS:
        raise ErreurApi(
            code="fichier_trop_gros",
            message=f"{nom} : {annoncee} octets annoncés — un parcours n'en fait pas plus "
            f"de {TAILLE_MAX_PARCOURS}, le dépôt est refusé sans être lu",
            statut=413,
        )
