"""`ourouler boucle` : la demande, le service, le rendu imprimé.

`lire_options` valide tout ce qui peut l'être **avant** la moindre
connexion (contrat §6) et construit la `Demande` du service
(`boucle/commande.py`) ; le rendu est `rendu/boucle.py`.
"""

from __future__ import annotations

import argparse
import math
from pathlib import Path

from ourouler.apprentissage.routes import BaseRoutes
from ourouler.boucle import commande as service
from ourouler.boucle.commande import Demande, ResultatBoucle, direction_en_azimut, verifier_sortie
from ourouler.boucle.horaire import analyser_pause, valider_pauses
from ourouler.commandes.commun import contexte, imprimer_json
from ourouler.config import Config
from ourouler.connecteurs.brouter import ClientBrouter
from ourouler.meteo.commande import heure_depart
from ourouler.meteo.openmeteo import ClientOpenMeteo
from ourouler.noyau.erreurs import ErreurUtilisateur
from ourouler.noyau.profil import Depart, Profil
from ourouler.rendu.boucle import avertissement_meteo, rendre_json, rendre_texte
from ourouler.services.contexte import Contexte


def executer_depuis_namespace(
    args: argparse.Namespace,
    config: Config,
    client_brouter: ClientBrouter | None = None,
    client_meteo: ClientOpenMeteo | None = None,
    *,
    lieu_depart: Depart | None = None,
    base_routes: BaseRoutes | None = None,
) -> int:
    """Exécute `ourouler boucle`. Renvoie le code de sortie (0 = succès).

    `lieu_depart` est le **point de départ de cette exécution**, déjà tranché
    par l'appelant (`cli.py` quand `--adresse-depart` a été géocodée, une
    requête d'API). Il remplace celui de la configuration **avant** la
    lecture des options, comme avant le lot 10 : la génération des candidates,
    les en-têtes de texte et le JSON lisent tous le départ du profil, et un
    seul de ces points oublié rendrait une boucle autour de la maison pour une
    adresse à 400 km.
    """
    ctx = contexte(config, lieu_depart=lieu_depart)
    demande = lire_options(args, ctx.profil)
    r = service.executer(demande, ctx, client_brouter, client_meteo, base_routes=base_routes)

    avertir_meteo(r, ctx)
    if getattr(args, "json", False):
        imprimer_json(json_boucle(r))
    else:
        print(
            rendre_texte(
                r.evaluations, r.demande, r.profil, r.chemin, r.modele,
                poids=r.poids, compteur_info=r.compteur_info,
            )
        )
    return 0


def avertir_meteo(r: ResultatBoucle, ctx: Contexte) -> None:
    """La météo absente ou en panne, dite par le canal des avertissements du contexte."""
    avertissement = avertissement_meteo(r.panne, r.meteo_absente)
    if avertissement is not None:
        ctx.avertir(avertissement)


def json_boucle(r: ResultatBoucle) -> dict:
    """Le JSON de `ourouler boucle --json`."""
    return rendre_json(
        r.evaluations,
        r.demande,
        r.profil,
        r.chemin,
        r.modele,
        poids=r.poids,
        meteo_absente=r.meteo_absente,
        compteur_info=r.compteur_info,
    )


def lire_options(args: argparse.Namespace, config: Profil) -> Demande:
    """Les options de la ligne de commande, passées à `demande`."""
    return demande(
        config,
        gpx=getattr(args, "gpx", None),
        puissance=getattr(args, "puissance", None),
        vitesse_a_plat=getattr(args, "vitesse_a_plat", None),
        distance=getattr(args, "distance", None),
        direction=getattr(args, "direction", None),
        candidates=getattr(args, "candidates", None),
        profil=getattr(args, "profil", None),
        pauses=getattr(args, "pause", None),
        depart=getattr(args, "depart", None),
        sortie=getattr(args, "sortie", None),
        ecraser=bool(getattr(args, "ecraser", False)),
        velo=getattr(args, "velo", None),
    )


def demande(
    config: Profil,
    *,
    gpx: str | None = None,
    puissance: float | None = None,
    vitesse_a_plat: float | None = None,
    distance: float | None = None,
    direction: str | None = None,
    candidates: int | None = None,
    profil: str | None = None,
    pauses: list[str] | None = None,
    depart: str | None = None,
    sortie: str | None = None,
    ecraser: bool = False,
    velo: str | None = None,
) -> Demande:
    """Valide les options **avant** toute connexion. Lève `ErreurUtilisateur` sinon.

    L'ordre compte : une distance négative ou une direction illisible doivent
    coûter un message immédiat, pas un aller-retour sur le serveur du
    mainteneur (contrat §6). `profil` est le profil **BRouter** (`--profil`),
    `config` le profil du cycliste.
    """
    chemin_gpx = Path(gpx) if gpx else None
    if chemin_gpx is not None and not chemin_gpx.is_file():
        raise ErreurUtilisateur(f"--gpx {gpx} : fichier introuvable")

    # `--puissance` et `--vitesse-a-plat` sont exclusives : le refus se dit
    # ici, avant tout appel à BRouter ou à Open-Meteo (contrat §6). La
    # conversion, elle, a besoin du vélo et attend `boucle.commande._modele_temps`.
    if puissance is not None and vitesse_a_plat is not None:
        raise ErreurUtilisateur(
            "--puissance et --vitesse-a-plat disent la même chose de deux façons "
            "(la seconde se convertit en watts par le modèle du vélo) : n'en donner qu'une."
        )

    distance_km = distance
    # Sans `--direction`, la recherche balaie tout l'horizon plutôt que de
    # refuser (Q47) — même défaut que `sortie` : « peu importe » est une
    # demande valable, pas une omission à corriger.
    libelle, azimut = ("", None)
    if direction is not None:
        libelle, azimut = direction_en_azimut(direction)

    if chemin_gpx is None:
        if distance_km is None:
            raise ErreurUtilisateur(
                "boucle : --distance KM est obligatoire (ou --gpx pour évaluer un fichier existant)"
            )
        if not math.isfinite(distance_km) or distance_km <= 0:
            raise ErreurUtilisateur(
                f"--distance {distance_km} : une distance en kilomètres strictement positive est attendue"
            )

    nb = config.boucle.candidates if candidates is None else candidates
    if nb < 1:
        raise ErreurUtilisateur(f"--candidates {nb} : au moins une candidate est attendue")

    profil = profil or config.brouter.profil
    if chemin_gpx is None and not config.brouter.renseigne:
        raise ErreurUtilisateur(
            "boucle : [brouter] url n'est pas renseigné dans la configuration — "
            "y mettre l'adresse du serveur BRouter, ou passer --gpx pour évaluer un fichier"
        )

    pauses_lues = tuple(analyser_pause(p) for p in pauses or [])
    # Sans `--gpx`, `distance_km` (la distance **demandée**) est la seule
    # longueur connue avant tout appel BRouter — les candidates réellement
    # générées peuvent différer dans la tolérance du contrat, mais une pause
    # au-delà de ce qui a été demandé est déjà une erreur d'entrée. Avec
    # `--gpx`, la longueur réelle du tracé n'est connue qu'après lecture du
    # fichier : le service revalide alors contre elle.
    valider_pauses(pauses_lues, distance_m=distance_km * 1000.0 if distance_km is not None else None)

    lue = Demande(
        gpx=chemin_gpx,
        distance_km=float(distance_km) if distance_km is not None else None,
        direction=libelle,
        azimut_deg=azimut,
        nb_candidates=int(nb),
        profil=profil,
        depart=heure_depart(depart),
        sortie=Path(sortie) if sortie else None,
        ecraser=ecraser,
        pauses=pauses_lues,
        velo=velo,
        puissance_w=puissance,
        vitesse_a_plat_kmh=vitesse_a_plat,
    )
    if lue.gpx is None:
        verifier_sortie(lue)
    return lue
