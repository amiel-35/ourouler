"""Les générations coûteuses : une sortie, le GPX d'une de ses propositions, une boucle."""

from __future__ import annotations

from datetime import date

from fastapi.responses import Response

from ourouler.api import calculs, vues
from ourouler.api.depots import Fichier
from ourouler.api.double_chemin import calculer
from ourouler.api.erreurs import ErreurApi
from ourouler.api.modeles import DemandeBoucle, DemandeSortie
from ourouler.api.proprietaire import Proprietaire
from ourouler.api.reponses import ReponseBoucle, ReponseSortie, reponse_de
from ourouler.api.routes.commun import (
    Contexte,
    Ctx,
    Qui,
    _avec_journal,
    _base_routes,
    _config,
    _depart,
    _rembourser_quota,
    _service,
    _verifier_quota,
    nouveau_routeur,
)
from ourouler.noyau.erreurs import ErreurUtilisateur

routeur = nouveau_routeur()


# --- parcours -----------------------------------------------------------------


@routeur.post("/sorties", **reponse_de(ReponseSortie))
def generer_sortie(
    ctx: Ctx,
    qui: Qui,
    demande: DemandeSortie,
) -> dict:
    """La séance du jour posée sur une boucle : propositions, géométrie, blocs, tenue.

    **Semi-synchrone** : le calcul se fait pendant la requête (4 à 6 secondes
    mesurées), et la réponse porte `duree_ms` — ce que ça a réellement pris —
    à côté de `budget` — ce que le front avait annoncé. Voir
    `docs/journal/ux/api_contrat.md` pour ce que ce choix implique côté écran.

    **Deux propositions au lieu de trois n'est pas une panne** :
    `motif_deux_propositions` porte l'explication, et la réponse reste un 200.

    **Trois propositions qui se valent n'en est pas une non plus** :
    `motif_equivalence` porte alors « ces trois boucles se valent, choisissez
    où vous voulez aller », avec ce qui, mesuré, ne les sépare pas.
    """
    from ourouler.sortie import commande as sortie_commande

    _verifier_quota(ctx, qui, ctx.quotas)
    try:
        config = _config(ctx, qui)
        carte = ctx.fichiers.reserver(qui, f"sortie_{demande.jour or date.today().isoformat()}.html")
        seance = _chemin_seance(ctx, qui, demande.fichier_seance)
        # **Aucun GPX n'est écrit ici** (décision Q40 g). Le cœur remet les trois
        # textes à `recueil_gpx` (aucun `sortie=` ne lui est passé, donc
        # aucun fichier), et c'est la route `…/propositions/{n}/gpx` qui en
        # servira un — celui que le cycliste aura choisi, et pas celui du
        # classement.
        recueillis: list[object] = []
        resultat = _avec_journal(
            ctx,
            qui,
            ("brouter", "openmeteo", "intervals"),
            lambda: calculer(
                ctx.chemin_api,
                config,
                route="sorties",
                operation="sortie",
                ancien=sortie_commande.executer,
                nouveau=calculs.sortie,
                options={
                    "jour": demande.jour,
                    "depart": demande.heure_depart,
                    "distance": demande.distance_km,
                    "direction": demande.direction,
                    "candidates": demande.candidates,
                    "vent": demande.vent,
                    "velo": demande.velo,
                    "profil": demande.profil,
                    "fichier_seance": seance,
                    "carte": str(carte.chemin),
                    "ecraser": True,
                },
                clients={
                    "client_brouter": _service(ctx, config, "brouter"),
                    "client_meteo": _service(ctx, config, "meteo"),
                    "client_intervals": _service(ctx, config, "intervals"),
                    "lieu_depart": _depart(demande.depart),
                    "recueil_gpx": recueillis.extend,
                    # Même raison que `POST /boucles`.
                    "base_routes": _base_routes(config, qui),
                },
                chemins={str(carte.chemin): carte.nom},
                budgets=ctx.budgets,
                # En `double`, le nouveau chemin dépose ses GPX à part : ils
                # sont comparés à ceux de l'ancien, jamais servis.
                recueils=("recueil_gpx",),
            ),
        )
        donnees = vues.avec_fichiers(resultat.donnees, carte=_note(ctx, qui, carte))
        if recueillis:
            donnees = vues.avec_gpx_par_proposition(
                donnees,
                generation=ctx.generations.retenir(qui, recueillis),
                noms={int(g.numero): str(g.nom_fichier) for g in recueillis},
                prefixe=routeur.prefix,
            )
    except Exception:
        # Seul un succès consomme le crédit décompté ci-dessus — une
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

    Rien n'est écrit à la génération — deux des trois traces
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


@routeur.post("/boucles", **reponse_de(ReponseBoucle))
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
        # Sans direction, la recherche balaie tout l'horizon (comme
        # `sortie`) plutôt que de refuser — le nom réservé le dit en clair
        # plutôt que de porter un `None` littéral.
        direction_nom = demande.direction or "toutes-directions"
        gpx = ctx.fichiers.reserver(qui, f"boucle_{direction_nom}_{demande.distance_km:g}km.gpx")
        resultat = calculer(
            ctx.chemin_api,
            config,
            route="boucles",
            operation="boucle",
            ancien=boucle_commande.executer,
            nouveau=calculs.boucle,
            options={
                "distance": demande.distance_km,
                "direction": demande.direction,
                "depart": demande.heure_depart,
                "candidates": demande.candidates,
                "profil": demande.profil,
                "velo": demande.velo,
                "puissance": demande.puissance_w,
                "sortie": str(gpx.chemin),
                "ecraser": True,
            },
            clients={
                "client_brouter": _service(ctx, config, "brouter"),
                "client_meteo": _service(ctx, config, "meteo"),
                "lieu_depart": _depart(demande.depart),
                # La colonne « connu % » est calculée contre les routes
                # que **ce** cycliste a roulées, pas contre celles du
                # propriétaire local.
                "base_routes": _base_routes(config, qui),
            },
            chemins={str(gpx.chemin): gpx.nom},
            budgets=ctx.budgets,
        )
        donnees = vues.avec_fichiers(resultat.donnees, gpx=_note(ctx, qui, gpx))
    except Exception:
        # Même remboursement que `POST /sorties` — voir sa docstring.
        _rembourser_quota(ctx, qui, ctx.quotas)
        raise
    return _enveloppe_retouchee(resultat, donnees, ctx.budgets.budget("boucle"), qui)


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
