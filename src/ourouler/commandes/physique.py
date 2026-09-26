"""`ourouler calibrer`, `simuler` et `analyser` : les demandes, les services, les rendus imprimés."""

from __future__ import annotations

import argparse
from pathlib import Path

from ourouler.activites.cache import Cache
from ourouler.boucle.horaire import analyser_pause
from ourouler.commandes.commun import contexte, imprimer_json
from ourouler.config import Config
from ourouler.connecteurs.openmeteo_archive import ClientArchive
from ourouler.meteo.commande import heure_depart
from ourouler.meteo.openmeteo import ClientOpenMeteo
from ourouler.noyau.erreurs import ErreurUtilisateur
from ourouler.physique import commande as service
from ourouler.physique.commande import (
    DemandeAnalyse,
    DemandeCalibration,
    DemandeSimulation,
    ResultatAnalyse,
    ResultatSimulation,
    date_option,
    velo_demande,
)
from ourouler.rendu import physique as rendu

# --- calibrer -----------------------------------------------------------------


def options_calibration(args: argparse.Namespace, config: Config) -> DemandeCalibration:
    """Le vélo d'abord (un vélo inconnu se refuse avant tout), puis les options."""
    velo = velo_demande(config, getattr(args, "velo", None))
    return DemandeCalibration(
        velo=velo,
        depuis=date_option(getattr(args, "depuis", None), config.historique_depuis),
        maximum=getattr(args, "max", None),
        crr_libre=bool(getattr(args, "crr_libre", False)),
    )


def calibrer_depuis_namespace(
    args: argparse.Namespace,
    config: Config,
    client_archive: ClientArchive | None = None,
    cache: Cache | None = None,
) -> int:
    """Exécute `ourouler calibrer`. Code de sortie 0 si ça a marché."""
    ecrite = service.executer_calibrer(
        options_calibration(args, config), contexte(config), client_archive=client_archive, cache=cache
    )
    resultat = ecrite.resultat
    options = {
        "depuis": config.historique_depuis,
        "fichier": ecrite.fichier,
        "archives_appels": ecrite.archives_appels,
        "archives_cache": ecrite.archives_cache,
        "motifs": resultat.motifs,
        "n_calibrables": resultat.n_calibrables,
        "crr_source": resultat.crr_source,
    }
    if getattr(args, "json", False):
        imprimer_json(rendu.rendre_json_calibration(resultat.rapport, ecrite.velo, **options))
    else:
        print(rendu.rendre_texte_calibration(resultat.rapport, ecrite.velo, **options))
    return 0


# --- simuler et analyser ------------------------------------------------------


def _gpx_obligatoire(gpx: str | None, commande: str) -> Path:
    """`--gpx` : donné, et un fichier qui existe — refusé avant toute lecture sinon."""
    if not gpx:
        raise ErreurUtilisateur(f"{commande} : --gpx FICHIER.GPX est obligatoire")
    chemin_gpx = Path(gpx)
    if not chemin_gpx.is_file():
        raise ErreurUtilisateur(f"--gpx {chemin_gpx} : fichier introuvable")
    return chemin_gpx


def options_simulation(args: argparse.Namespace) -> DemandeSimulation:
    return interpreter_simulation(
        gpx=getattr(args, "gpx", None),
        velo=getattr(args, "velo", None),
        puissance=getattr(args, "puissance", None),
        vitesse_a_plat=getattr(args, "vitesse_a_plat", None),
        pauses=getattr(args, "pause", None),
        depart=getattr(args, "depart", None),
    )


def interpreter_simulation(
    *,
    gpx: str | None,
    velo: str | None = None,
    puissance: float | None = None,
    vitesse_a_plat: float | None = None,
    pauses: list[str] | None = None,
    depart: str | None = None,
) -> DemandeSimulation:
    """La demande de `simuler`, depuis les valeurs brutes des options."""
    chemin_gpx = _gpx_obligatoire(gpx, "simuler")
    return DemandeSimulation(
        gpx=chemin_gpx,
        velo=velo,
        puissance_w=puissance,
        vitesse_a_plat_kmh=vitesse_a_plat,
        pauses=tuple(analyser_pause(p) for p in pauses or []),
        depart=heure_depart(depart) if depart else None,
    )


def json_simulation(r: ResultatSimulation) -> dict:
    """Le JSON de `ourouler simuler --json`."""
    return rendu.rendre_json_simulation(
        r.simulation,
        r.trace,
        r.velo,
        r.parametres,
        r.provenance,
        r.puissance_w,
        meteo=r.meteo,
        pauses=r.pauses,
        arrivee=r.arrivee,
        alerte=r.alerte,
    )


def simuler_depuis_namespace(
    args: argparse.Namespace, config: Config, client_meteo: ClientOpenMeteo | None = None
) -> int:
    """Exécute `ourouler simuler`. Code de sortie 0 si la simulation a eu lieu."""
    r = service.executer_simuler(options_simulation(args), contexte(config), client_meteo=client_meteo)
    if getattr(args, "json", False):
        imprimer_json(json_simulation(r))
    else:
        positionnels = (r.simulation, r.trace, r.velo, r.parametres, r.provenance, r.puissance_w)
        options = {"meteo": r.meteo, "pauses": r.pauses, "arrivee": r.arrivee, "alerte": r.alerte}
        print(rendu.rendre_texte_simulation(*positionnels, **options))
    return 0


def options_analyse(args: argparse.Namespace) -> DemandeAnalyse:
    return interpreter_analyse(
        gpx=getattr(args, "gpx", None),
        depart=getattr(args, "depart", None),
        velo=getattr(args, "velo", None),
        puissance=getattr(args, "puissance", None),
        vitesse_a_plat=getattr(args, "vitesse_a_plat", None),
    )


def interpreter_analyse(
    *,
    gpx: str | None,
    depart: str | None,
    velo: str | None = None,
    puissance: float | None = None,
    vitesse_a_plat: float | None = None,
) -> DemandeAnalyse:
    """La demande d'`analyser`, depuis les valeurs brutes des options."""
    chemin_gpx = _gpx_obligatoire(gpx, "analyser")
    if not depart:
        raise ErreurUtilisateur(
            "analyser : --heure-depart est obligatoire (sans elle, rien à caler dans le "
            "temps — ni la météo, ni l'heure d'arrivée)"
        )
    return DemandeAnalyse(
        gpx=chemin_gpx,
        depart=heure_depart(depart),
        velo=velo,
        puissance_w=puissance,
        vitesse_a_plat_kmh=vitesse_a_plat,
    )


def json_analyse(r: ResultatAnalyse) -> dict:
    """Le JSON d'`ourouler analyser --json`."""
    return rendu.rendre_json_analyse(
        r.simulation,
        r.trace,
        r.velo,
        r.parametres,
        r.provenance,
        r.puissance_w,
        meteo=r.meteo,
        ecoule=r.ecoule,
        depart=r.depart,
        arrivee_bas=r.arrivee_bas,
        arrivee_mediane=r.arrivee_mediane,
        arrivee_haut=r.arrivee_haut,
        alerte=r.alerte,
        meteo_absente=r.meteo_absente,
        fourchette=r.fourchette,
        panne=r.panne,
        avertissements_trace=r.avertissements_trace,
        vitesse_a_vent_nul_kmh=r.vitesse_a_vent_nul_kmh,
    )


def analyser_depuis_namespace(
    args: argparse.Namespace, config: Config, client_meteo: ClientOpenMeteo | None = None
) -> int:
    """Exécute `ourouler analyser`. Code de sortie 0 si l'analyse a eu lieu."""
    r = service.executer_analyser(options_analyse(args), contexte(config), client_meteo=client_meteo)
    if getattr(args, "json", False):
        imprimer_json(json_analyse(r))
    else:
        print(
            rendu.rendre_texte_analyse(
                r.simulation,
                r.trace,
                r.velo,
                r.parametres,
                r.provenance,
                r.puissance_w,
                meteo=r.meteo,
                ecoule=r.ecoule,
                depart=r.depart,
                arrivee_mediane=r.arrivee_mediane,
                alerte=r.alerte,
                meteo_absente=r.meteo_absente,
                panne=r.panne,
            )
        )
    return 0
