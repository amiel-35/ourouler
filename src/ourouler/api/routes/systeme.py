"""Ce que le serveur sait faire pour ce cycliste, et ses budgets de durée."""

from __future__ import annotations

from ourouler import __version__
from ourouler.api.routes.commun import Ctx, Qui, _config, nouveau_routeur
from ourouler.api.session import MODE_PERSONNEL

routeur = nouveau_routeur()


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
    charge: dict = {
        "proprietaire": str(qui),
        "version": __version__,
        "capacites": {
            "intervals": bool(config.intervals.renseigne),
            "brouter": bool(config.brouter.renseigne),
            "velos": [v.nom for v in config.velos],
        },
        "budgets": ctx.budgets.tous(),
    }
    if ctx.session.mode != MODE_PERSONNEL:
        # Le quota est **celui de ce compte** — sa propre donnée, jamais
        # celle d'un voisin. Sans objet en mode personnel (`_verifier_quota`).
        charge["quotas"] = {
            "generations": {"plafond": ctx.quotas.plafond, "restant": ctx.quotas.restant(qui)},
            "consultations_meteo": {
                "plafond": ctx.quotas_meteo.plafond,
                "restant": ctx.quotas_meteo.restant(qui),
            },
            "calibrations": {
                "plafond": ctx.quotas_calibration.plafond,
                "restant": ctx.quotas_calibration.restant(qui),
            },
            "imports": {
                "plafond": ctx.quotas_import.plafond,
                "restant": ctx.quotas_import.restant(qui),
            },
        }
    # **Les compteurs du cache météo ne sortent plus ici** (relecture
    # Opus, L9.3) : `appels_reels`/`appels_servis_cache` sont globaux au
    # processus, pas au compte qui interroge — les publier à n'importe quel
    # compte authentifié laisse deviner l'activité de tous les autres (une
    # fuite de voisinage, même sans identifiant nominatif dans le nombre
    # lui-même). `ctx.clients.meteo.stats()` (`ClientOpenMeteoCache`) reste
    # accessible côté serveur pour qui a la main sur le processus — journal
    # ou une future route d'administration, jamais `/systeme`.
    return charge


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
