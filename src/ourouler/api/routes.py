"""Les routes de l'API, déduites des vingt écrans des maquettes.

Toutes sont préfixées `/api/v1`. Toutes celles qui calculent rendent la même
enveloppe — `{donnees, avertissements, duree_ms, budget}` — et toutes celles
qui échouent rendent la même forme d'erreur (`erreurs.py`).

Le propriétaire traverse **chaque** requête : la dépendance `proprietaire`
le résout, et il est passé en premier argument à tout accès aux données
(doctrine §10.2). Aucune route ne lit un fichier de configuration
elle-même : elle demande sa `Config` au dépôt, pour ce propriétaire-là.

Ce qui n'est **pas** exposé, et pourquoi : `inventaire --importer` et
`--synchroniser`, `routes apprendre --appliquer`, `calibrer` écrivent dans le
cache du serveur et durent des minutes. Ce sont des gestes d'administration
que le mainteneur fait en ligne de commande ; aucun écran des maquettes ne
les demande, et les exposer ferait de l'API une console d'administration
avant qu'elle ait des comptes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, File, Query, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse

from ourouler import __version__
from ourouler.api import vues
from ourouler.api.adaptateur import Budgets, executer_commande, namespace
from ourouler.api.depots import DepotFichiers, DepotProfils, Fichier
from ourouler.api.erreurs import ErreurApi, classer, secrets_de
from ourouler.api.modeles import ApercuZones, DemandeBoucle, DemandeSimulation, DemandeSortie, Point
from ourouler.api.proprietaire import Proprietaire, resoudre
from ourouler.config import Config, Depart
from ourouler.erreurs import ErreurConfig, ErreurUtilisateur

routeur = APIRouter(prefix="/api/v1")

#: Taille maximale d'un fichier de séance déposé. Un `.ZWO` fait quelques
#: kilo-octets ; au-delà d'un mégaoctet, ce n'est plus une séance.
TAILLE_MAX_SEANCE = 1_000_000


@dataclass
class Clients:
    """Les clients externes, injectables — c'est ce qui rend l'API testable.

    `None` partout en service : chaque commande du cœur fabrique alors le
    sien, comme depuis la ligne de commande. Les tests passent des clients à
    transport bouchonné, et aucun test ne touche le réseau (règle absolue 3).
    """

    brouter: object | None = None
    meteo: object | None = None
    intervals: object | None = None
    ban: object | None = None
    nominatim: object | None = None


@dataclass
class Contexte:
    """Ce que l'application pose sur elle-même, et que les routes retrouvent."""

    profils: DepotProfils
    fichiers: DepotFichiers
    clients: Clients
    budgets: Budgets


def contexte(requete: Request) -> Contexte:
    return requete.app.state.ourouler


def proprietaire() -> Proprietaire:
    """Le propriétaire de la requête. F3 remplacera `resoudre` par la session."""
    return resoudre()


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


def _depart(point: Point | None) -> Depart | None:
    """Le point de départ de cette requête, déjà tranché par le front.

    L'API ne géocode jamais au vol : le front choisit dans la liste que rend
    `/geocodage`, et envoie des coordonnées (F0.7).
    """
    if point is None:
        return None
    return Depart(nom=point.nom, latitude=point.latitude, longitude=point.longitude)


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
    return {
        "proprietaire": str(qui),
        "version": __version__,
        "capacites": {
            "intervals": bool(config.intervals.renseigne),
            "brouter": bool(config.brouter.renseigne),
            "velos": [v.nom for v in config.velos],
        },
        "budgets": ctx.budgets.tous(),
    }


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
    """Le profil du cycliste : départ, poids, FTP, position dans la zone, vélos, services."""
    return {"proprietaire": str(qui), "donnees": vues.profil(_config(ctx, qui))}


@routeur.patch("/profil")
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
    return {"proprietaire": str(qui), "donnees": vues.profil(config)}


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


# --- géocodage ----------------------------------------------------------------


@routeur.get("/geocodage")
def geocoder(
    ctx: Ctx,
    qui: Qui,
    adresse: Annotated[str, Query(min_length=1, max_length=200)],
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
        ban=ctx.clients.ban,
        nominatim=ctx.clients.nominatim,
    )
    charge = resultat.enveloppe(ctx.budgets.budget("geocodage"), qui)
    if not resultat.donnees.get("candidats"):
        # Zéro candidat **n'est pas une panne** — les services ont répondu —
        # mais l'écran d'échec « adresse introuvable » a besoin d'une phrase,
        # et une liste vide n'en est pas une.
        charge["avertissements"] = [
            *charge["avertissements"],
            f"aucune adresse trouvée pour « {adresse} » — préciser la commune ou le code postal",
        ]
    return charge


# --- météo --------------------------------------------------------------------


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
        client=ctx.clients.meteo,
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
    resultat = executer_commande(
        seance_commande.executer,
        namespace(depuis=debut.isoformat(), jusqua=fin.isoformat()),
        config,
        secrets=secrets_de(config),
        operation="seances",
        budgets=ctx.budgets,
        client=ctx.clients.intervals,
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
    resultat = executer_commande(
        seance_commande.executer,
        namespace(jour=jour.isoformat()),
        config,
        secrets=secrets_de(config),
        operation="seance",
        budgets=ctx.budgets,
        client=ctx.clients.intervals,
    )
    return resultat.enveloppe(ctx.budgets.budget("seance"), qui)


@routeur.post("/seances/fichier")
async def deposer_seance(
    ctx: Ctx,
    qui: Qui,
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
        operation="seance",
        budgets=ctx.budgets,
        client=ctx.clients.intervals,
    )
    charge = resultat.enveloppe(ctx.budgets.budget("seance"), qui)
    charge["fichier"] = depose.json()
    return charge


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
    """
    from ourouler.sortie import commande as sortie_commande

    config = _config(ctx, qui)
    gpx = ctx.fichiers.reserver(qui, f"sortie_{demande.jour or date.today().isoformat()}.gpx")
    carte = ctx.fichiers.reserver(qui, f"sortie_{demande.jour or date.today().isoformat()}.html")
    seance = _chemin_seance(ctx, qui, demande.fichier_seance)
    resultat = executer_commande(
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
            sortie=str(gpx.chemin),
            carte=str(carte.chemin),
            ecraser=True,
        ),
        config,
        secrets=secrets_de(config),
        operation="sortie",
        budgets=ctx.budgets,
        client_brouter=ctx.clients.brouter,
        client_meteo=ctx.clients.meteo,
        client_intervals=ctx.clients.intervals,
        lieu_depart=_depart(demande.depart),
    )
    donnees = vues.avec_fichiers(
        resultat.donnees,
        gpx=_note(ctx, qui, gpx),
        carte=_note(ctx, qui, carte),
    )
    return _enveloppe_retouchee(resultat, donnees, ctx.budgets.budget("sortie"), qui)


@routeur.post("/boucles")
def generer_boucle(
    ctx: Ctx,
    qui: Qui,
    demande: DemandeBoucle,
) -> dict:
    """Une boucle libre, sans séance : candidates, coûts, météo le long du tracé, géométrie."""
    from ourouler.boucle import commande as boucle_commande

    config = _config(ctx, qui)
    gpx = ctx.fichiers.reserver(qui, f"boucle_{demande.direction}_{demande.distance_km:g}km.gpx")
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
        operation="boucle",
        budgets=ctx.budgets,
        client_brouter=ctx.clients.brouter,
        client_meteo=ctx.clients.meteo,
        lieu_depart=_depart(demande.depart),
    )
    donnees = vues.avec_fichiers(resultat.donnees, gpx=_note(ctx, qui, gpx))
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
        operation="simulation",
        budgets=ctx.budgets,
        client_meteo=ctx.clients.meteo,
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
    )
    return resultat.enveloppe(ctx.budgets.budget("inventaire"), qui)


@routeur.get("/routes/{action}")
def routes_connues(
    ctx: Ctx,
    qui: Qui,
    action: str,
) -> dict:
    """Ce que les sorties passées ont appris : `stats` ou `poids` (en lecture seule)."""
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
        client_brouter=ctx.clients.brouter,
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


# --- petits services ----------------------------------------------------------


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
