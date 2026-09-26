"""Géocodage d'un départ, vent au départ et météo par direction."""

from __future__ import annotations

from typing import Annotated

from fastapi import Query

from ourouler.api import calculs
from ourouler.api.adaptateur import Avertissement
from ourouler.api.double_chemin import calculer
from ourouler.api.erreurs import ErreurApi, classer_avertissement
from ourouler.api.modeles import TexteUtile
from ourouler.api.reponses import ReponseGeocodage, ReponseMeteo, ReponseVentDepart, reponse_de
from ourouler.api.routes.commun import (
    Ctx,
    Qui,
    _avec_journal,
    _config,
    _service,
    _verifier_quota,
    nouveau_routeur,
)
from ourouler.config import Depart

routeur = nouveau_routeur()


# --- géocodage ----------------------------------------------------------------


@routeur.get("/geocodage", **reponse_de(ReponseGeocodage))
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
    resultat = calculer(
        ctx.chemin_api,
        config,
        route="geocodage",
        operation="geocodage",
        ancien=geocodage.executer,
        nouveau=calculs.geocoder,
        options={"adresse": adresse, "max": max},
        clients={
            "ban": _service(ctx, config, "ban"),
            "nominatim": _service(ctx, config, "nominatim"),
        },
        budgets=ctx.budgets,
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


@routeur.get("/vent-depart", **reponse_de(ReponseVentDepart))
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
        lambda: calculer(
            ctx.chemin_api,
            config,
            route="vent-depart",
            operation="vent-depart",
            ancien=sortie_commande.executer_vent,
            nouveau=calculs.vent_depart,
            options={"jour": jour, "depart": heure_depart},
            clients={"client_meteo": _service(ctx, config, "meteo"), "lieu_depart": lieu},
            budgets=ctx.budgets,
        ),
    )
    return resultat.enveloppe(ctx.budgets.budget("vent-depart"), qui)


@routeur.get("/meteo", **reponse_de(ReponseMeteo))
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
    resultat = calculer(
        ctx.chemin_api,
        config,
        route="meteo",
        operation="meteo",
        ancien=meteo_commande.executer,
        nouveau=calculs.meteo,
        options={
            "depart": heure_depart,
            "horizon": horizon,
            "distance": distance,
            "modele": modele,
            "second_avis": second_avis,
        },
        clients={"client": _service(ctx, config, "meteo"), "lieu_depart": lieu},
        budgets=ctx.budgets,
    )
    return resultat.enveloppe(ctx.budgets.budget("meteo"), qui)
