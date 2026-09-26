"""Les séances : la semaine d'Intervals.icu, un jour, un fichier déposé."""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import File, Request, UploadFile

from ourouler.api import calculs
from ourouler.api.double_chemin import calculer
from ourouler.api.erreurs import ErreurApi, classer
from ourouler.api.routes.commun import (
    TAILLE_MAX_SEANCE,
    Ctx,
    Qui,
    _avec_journal,
    _config,
    _service,
    nouveau_routeur,
)
from ourouler.noyau.erreurs import ErreurUtilisateur

routeur = nouveau_routeur()


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
        lambda: calculer(
            ctx.chemin_api,
            config,
            route="seances",
            operation="seances",
            ancien=seance_commande.executer,
            nouveau=calculs.seance,
            options={"depuis": debut.isoformat(), "jusqua": fin.isoformat()},
            clients={"client": _service(ctx, config, "intervals")},
            budgets=ctx.budgets,
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
        lambda: calculer(
            ctx.chemin_api,
            config,
            route="seance",
            operation="seance",
            ancien=seance_commande.executer,
            nouveau=calculs.seance,
            options={"jour": jour.isoformat()},
            clients={"client": _service(ctx, config, "intervals")},
            budgets=ctx.budgets,
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
    resultat = calculer(
        ctx.chemin_api,
        config,
        route="seances-fichier",
        operation="seance",
        ancien=seance_commande.executer,
        nouveau=calculs.seance,
        options={
            "fichier_seance": str(depose.chemin),
            "jour": (jour or date.today()).isoformat(),
        },
        clients={"client": _service(ctx, config, "intervals")},
        # Le cœur cite le chemin qu'on lui donne (« … : fichier vide ») ; ce
        # chemin est celui du serveur, et le nom que le cycliste reconnaît est
        # celui de son fichier.
        chemins={str(depose.chemin): nom},
        budgets=ctx.budgets,
    )
    charge = resultat.enveloppe(ctx.budgets.budget("seance"), qui)
    charge["fichier"] = depose.json()
    return charge


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
