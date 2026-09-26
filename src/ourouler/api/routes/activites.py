"""L'historique déposé : l'import en tâche de fond et son état."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Annotated

from fastapi import File, Request, UploadFile

from ourouler.api.erreurs import ErreurApi
from ourouler.api.routes.commun import (
    Ctx,
    Qui,
    _cache,
    _config,
    _message_occupe,
    _rembourser_quota,
    _verifier_quota,
    nouveau_routeur,
)

routeur = nouveau_routeur()


# --- historique déposé -------------------------------------------------------


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
    capteur y trouve aussi son niveau (décision Q48, `docs/journal/questions/questions_mainteneur.md`).

    **202, pas 200** : une archive
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
    déposée est identifiée par son contenu.

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

    _verifier_quota(ctx, qui, ctx.quotas_import)
    try:
        depots = _copier_en_temporaires(fichiers)
    except Exception:
        _rembourser_quota(ctx, qui, ctx.quotas_import)
        raise
    try:
        job = imports_fond.lancer(
            cache,
            str(qui),
            depots,
            au_echec=lambda: _rembourser_quota(ctx, qui, ctx.quotas_import),
        )
    except imports_fond.ErreurImportEnCours as occupe:
        _rembourser_quota(ctx, qui, ctx.quotas_import)
        for _, chemin in depots:
            chemin.unlink(missing_ok=True)
        raise ErreurApi(
            code="import_deja_en_cours",
            message=_message_occupe(occupe.nature),
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
    from ourouler.api.imports_fond import PREFIXE_TEMPORAIRE

    chemins: list[Path] = []
    total = 0
    try:
        for fichier in fichiers:
            # Fermé tout de suite : `mkstemp` laissait son descripteur ouvert,
            # un par fichier déposé, jusqu'à la fin du processus.
            with tempfile.NamedTemporaryFile(
                prefix=PREFIXE_TEMPORAIRE, suffix=".bin", delete=False
            ) as vide:
                destination = Path(vide.name)
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


def _refuser_import_sur_la_taille_annoncee(requete: Request) -> None:
    """Même garde que `_refuser_sur_la_taille_annoncee`, sur le plafond de l'import.

    Une archive Strava réelle pèse 665 Mo (`docs/services_externes.md`) : le
    plafond n'est donc pas celui d'une séance, mais le principe est le même.

    **Limite, dite** : FastAPI a déjà reçu tout le
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
