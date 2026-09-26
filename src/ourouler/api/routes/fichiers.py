"""Les fichiers d'un propriétaire, servis s'ils sont bien à lui."""

from __future__ import annotations

from fastapi.responses import FileResponse

from ourouler.api.erreurs import ErreurApi
from ourouler.api.routes.commun import Ctx, Qui, nouveau_routeur
from ourouler.noyau.erreurs import ErreurUtilisateur

routeur = nouveau_routeur()


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
