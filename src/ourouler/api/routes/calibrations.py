"""La calibration d'un vélo depuis l'écran (L9.4), en tâche de fond.

Le travail est dans `api/calibrations.py` ; ces routes résolvent le
propriétaire, sa `Config`, son quota et le verrou des tâches lourdes.
"""

from __future__ import annotations

from ourouler.api.erreurs import ErreurApi, classer
from ourouler.api.modeles import DemandeCalibration
from ourouler.api.proprietaire import Proprietaire
from ourouler.api.routes.commun import (
    Contexte,
    Ctx,
    Qui,
    _cache,
    _config,
    _message_occupe,
    _rembourser_quota,
    _service,
    _verifier_quota,
    nouveau_routeur,
)
from ourouler.api.session import MODE_PERSONNEL
from ourouler.connecteurs.openmeteo_archive import ClientArchive
from ourouler.physique.commande import NOM_CACHE as NOM_CACHE_ARCHIVE

routeur = nouveau_routeur()


# --- calibration depuis l'écran (L9.4) ------------------------------------------


@routeur.get("/calibrations")
def etat_calibrations(ctx: Ctx, qui: Qui) -> dict:
    """Pour chaque vélo : sa calibration en mots simples, de quoi la lancer, la tâche récente.

    L'écran s'en sert pour dessiner la fiche vélo sans rien lancer : combien
    de sorties exploitables il y a (et combien il en faut), si un pneu est
    déclaré, la dernière calibration de ce vélo (en cours ou terminée — c'est
    ce qui permet de reprendre l'avancement après un rechargement de page).
    Rien de tout ça ne coûte d'appel externe : l'index des sorties seul.
    """
    from ourouler.api import calibrations

    config = _config(ctx, qui)
    donnees = calibrations.etat(config, _cache(config, qui), str(qui))
    if ctx.session.mode != MODE_PERSONNEL:
        donnees["quota"] = {
            "plafond": ctx.quotas_calibration.plafond,
            "restant": ctx.quotas_calibration.restant(qui),
        }
    return {"proprietaire": str(qui), "donnees": donnees}


@routeur.get("/calibrations/{id_job}")
def etat_job_calibration(ctx: Ctx, qui: Qui, id_job: str) -> dict:
    """Où en est une calibration lancée par `POST /calibrations` — à interroger périodiquement.

    Même cloisonnement que `GET /activites/import/{id}` : l'identifiant d'un
    autre propriétaire — ou celui d'un import — rend `fichier_introuvable`.
    """
    from ourouler.api import taches_fond

    job = taches_fond.trouver(str(qui), id_job, taches_fond.NATURE_CALIBRATION)
    if job is None:
        raise ErreurApi(
            code="fichier_introuvable",
            message=f"calibration {id_job} : introuvable, ou appartenant à quelqu'un d'autre",
            statut=404,
        )
    return {"proprietaire": str(qui), "donnees": job.json()}


@routeur.post("/calibrations", status_code=202)
def lancer_calibration(ctx: Ctx, qui: Qui, demande: DemandeCalibration) -> dict:
    """Lance en tâche de fond la calibration d'un vélo sur les sorties de **ce** compte.

    Crr fixé par le pneu (ou, `sans_pneu`, par l'usage — dit comme tel), CdA
    cherché, fourchette du porte à porte mesurée hors échantillon : le calcul
    de `ourouler calibrer` (L9.1), sur les sorties importées (L9.2) ou
    synchronisées depuis Intervals. Voir `api/calibrations.py` pour le choix
    des sorties quand le profil a plusieurs vélos.

    Dans l'ordre, et c'est voulu : les **préconditions** d'abord (pas de
    vélo, pas de FTP, pas assez de sorties, pas de pneu — chacune avec son
    code et ce qu'il faut faire), puis le **quota** (une par jour et par
    compte, remboursée si la calibration échoue), puis le **verrou** des
    tâches lourdes (un import ou une calibration à la fois pour tout le
    serveur, `tache_lourde_en_cours`). Un refus à l'une de ces étapes ne
    coûte rien au compte.

    202 et un identifiant tout de suite ; `GET /calibrations/{id}` dit où
    elle en est, puis rend le résultat en mots simples.
    """
    from ourouler.api import calibrations, taches_fond

    config = _config(ctx, qui)
    cache = _cache(config, qui)
    velo = calibrations.verifier(
        config,
        demande.velo,
        cache,
        sans_pneu=demande.sans_pneu,
        velos_declares=_velos_declares(ctx, qui),
    )
    client_archive = _service(ctx, config, "archive") or ClientArchive(
        chemin_cache=config.cache.dossier / NOM_CACHE_ARCHIVE
    )
    _verifier_quota(ctx, qui, ctx.quotas_calibration)
    try:
        job = calibrations.lancer(
            config,
            velo,
            cache,
            client_archive,
            str(qui),
            sans_pneu=demande.sans_pneu,
            chemins={
                str(ctx.profils.dossier(qui)): "(votre dossier)",
                str(config.cache.dossier): "(cache du serveur)",
            },
            au_echec=lambda: _rembourser_quota(ctx, qui, ctx.quotas_calibration),
        )
    except taches_fond.ErreurTacheEnCours as occupe:
        _rembourser_quota(ctx, qui, ctx.quotas_calibration)
        raise ErreurApi(
            code="tache_lourde_en_cours",
            message=_message_occupe(occupe.nature),
            statut=409,
        ) from None
    return {"proprietaire": str(qui), "donnees": job.json()}


def _velos_declares(ctx: Contexte, qui: Proprietaire) -> bool:
    """Le compte a-t-il déclaré ses vélos ? Voir `calibrations.verifier`.

    En mode hébergé, `velos` est du tiers 3 (Q35) : jamais hérité du socle,
    donc absent de la surcharge tant que le cycliste ne l'a pas écrit. En
    mode personnel, les vélos sont ceux du TOML du mainteneur.
    """
    if ctx.session.mode == MODE_PERSONNEL:
        return True
    try:
        return bool(ctx.profils.surcharge(qui).get("velos"))
    except Exception as e:
        raise classer(e) from e
