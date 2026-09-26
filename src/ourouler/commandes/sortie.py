"""`ourouler sortie` : la demande, le service, la page du jour, le rendu imprimé.

`lire_options` valide tout ce qui peut l'être **avant** le premier appel
réseau et construit la `Demande` du service (`sortie/commande.py`). Le
service cherche, place, mesure et écrit le GPX ; ce module écrit la page du
jour (construite par `rendu.sortie`) puis imprime le tableau ou le JSON.
"""

from __future__ import annotations

import argparse
import math
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from ourouler.apprentissage.routes import BaseRoutes
from ourouler.boucle.commande import direction_en_azimut
from ourouler.commandes.commun import contexte, imprimer_json
from ourouler.config import Config
from ourouler.connecteurs.brouter import ClientBrouter
from ourouler.connecteurs.intervals import ClientIntervals
from ourouler.meteo.openmeteo import ClientOpenMeteo
from ourouler.noyau.erreurs import ErreurUtilisateur
from ourouler.noyau.profil import Depart, Profil
from ourouler.noyau.seance import Seance
from ourouler.rendu import sortie as rendu
from ourouler.rendu.sortie import page_jour, page_sans_seance
from ourouler.services.contexte import Contexte
from ourouler.sortie import commande as service
from ourouler.sortie import contraste, orientation
from ourouler.sortie.commande import (
    Demande,
    DemandeVent,
    GpxPropose,
    SansSeance,
    chemin_carte_par_defaut,
    chemin_gpx_par_defaut,
    heure_depart_du_jour,
    jour_option,
    verifier_ecriture,
)


def executer_depuis_namespace(
    args: argparse.Namespace,
    config: Config,
    client_brouter: ClientBrouter | None = None,
    client_meteo: ClientOpenMeteo | None = None,
    client_intervals: ClientIntervals | None = None,
    *,
    lieu_depart: Depart | None = None,
    recueil_gpx: Callable[[list[GpxPropose]], None] | None = None,
    base_routes: BaseRoutes | None = None,
) -> int:
    """Exécute `ourouler sortie`. 0 = succès (y compris « aucune séance ce jour-là »).

    `lieu_depart` est le **point de départ de cette exécution**, déjà tranché
    par l'appelant (`cli.py` quand `--adresse-depart` a été géocodée, une
    requête d'API). Il remplace celui de la configuration dans le profil que
    reçoit le service : la question du vent, la génération des candidates,
    les en-têtes de texte, la carte et le JSON lisent tous ce départ-là.

    `recueil_gpx` : voir `sortie.commande.executer` (Q40 g).
    """
    ctx = contexte(config, lieu_depart=lieu_depart)
    demande = lire_options(args, config)
    resultat = service.executer(
        demande,
        ctx,
        client_brouter,
        client_meteo,
        client_intervals,
        recueil_gpx=recueil_gpx,
        base_routes=base_routes,
    )
    donnees, texte = terminer(
        demande,
        ctx,
        resultat,
        en_json=getattr(args, "json", False),
        carte_sans_seance=bool(getattr(args, "carte_sans_seance", False)),
    )
    if donnees is not None:
        imprimer_json(donnees)
    else:
        print(texte)
    return 0


def terminer(
    demande: Demande,
    ctx: Contexte,
    resultat: object,
    *,
    en_json: bool,
    carte_sans_seance: bool = False,
) -> tuple[dict | None, str | None]:
    """Après le service : la page du jour écrite, l'avertissement dit, le JSON ou le texte.

    Rend `(json, None)` si `en_json`, `(None, texte)` sinon. L'avertissement
    météo part par `ctx.avertir` : sur la sortie d'erreur pour la ligne de
    commande, dans `avertissements` pour l'API.
    """
    if isinstance(resultat, SansSeance):
        # Service planifié (contrat de l'hébergé minimal, périmètre point 4) :
        # un jour sans séance doit produire une page qui le dit, jamais rien
        # ni la page de la veille. Par défaut (`--carte-sans-seance` absent),
        # rien n'est écrit — comportement inchangé pour l'usage interactif,
        # où un fichier à chaque essai sans séance serait du bruit.
        chemin_carte = None
        if carte_sans_seance:
            chemin_carte = ecrire_page_sans_seance(demande, ctx.dossier_cache)
        if en_json:
            return rendu.json_sans_seance(demande.jour, chemin_carte), None
        return None, rendu.texte_sans_seance(demande.jour, chemin_carte)

    pour_le_rendu = resultat.contexte
    chemin_carte = ecrire_page_jour(
        pour_le_rendu.seance,
        demande,
        ctx.profil,
        ctx.dossier_cache,
        pour_le_rendu.selection,
        resultat.gpx_propositions,
    )
    pour_le_rendu = replace(pour_le_rendu, carte=chemin_carte)
    avertissement = rendu.avertissement_meteo(resultat.panne, pour_le_rendu.meteo_absente)
    if avertissement is not None:
        ctx.avertir(avertissement)
    if en_json:
        return rendu.rendre_json(resultat.propositions, pour_le_rendu), None
    return None, rendu.rendre_texte(resultat.propositions, pour_le_rendu)


def vent_depuis_namespace(
    args: argparse.Namespace,
    config: Config,
    client_meteo: ClientOpenMeteo | None = None,
    *,
    lieu_depart: Depart | None = None,
) -> int:
    """Le vent au départ, **avant** de chercher quoi que ce soit (Q44) : toujours en JSON."""
    demande = interpreter_vent(jour=getattr(args, "jour", None), depart=getattr(args, "depart", None))
    r = service.executer_vent(demande, contexte(config, lieu_depart=lieu_depart), client_meteo=client_meteo)
    imprimer_json(rendu.vent_depart_json(r.question, r.jour, r.depart))
    return 0


def interpreter_vent(*, jour: str | None = None, depart: str | None = None) -> DemandeVent:
    """Le jour, puis l'heure de départ de ce jour-là."""
    jour_lu = jour_option(jour)
    return DemandeVent(jour=jour_lu, depart=heure_depart_du_jour(depart, jour_lu))


# --- options ------------------------------------------------------------------


def lire_options(args: argparse.Namespace, config: Config) -> Demande:
    """Les options de la ligne de commande, passées à `interpreter`."""
    return interpreter(
        config,
        jour=getattr(args, "jour", None),
        distance=getattr(args, "distance", None),
        direction=getattr(args, "direction", None),
        candidates=getattr(args, "candidates", None),
        velo=getattr(args, "velo", None),
        vent=getattr(args, "vent", None),
        profil=getattr(args, "profil", None),
        depart=getattr(args, "depart", None),
        sortie=getattr(args, "sortie", None),
        carte=getattr(args, "carte", None),
        ecraser=bool(getattr(args, "ecraser", False)),
        fichier_seance=getattr(args, "fichier_seance", None),
    )


def interpreter(
    config: Config,
    *,
    jour: str | None = None,
    distance: float | None = None,
    direction: str | None = None,
    candidates: int | None = None,
    velo: str | None = None,
    vent: str | None = None,
    profil: str | None = None,
    depart: str | None = None,
    sortie: str | None = None,
    carte: str | None = None,
    ecraser: bool = False,
    fichier_seance: str | None = None,
) -> Demande:
    """Valide tout ce qui peut l'être **avant** le premier appel réseau.

    Une date illisible, une distance négative, une direction inconnue, un vélo
    absent de la configuration ou un dossier de sortie où l'on ne peut pas
    écrire doivent coûter un message immédiat — pas un aller-retour chez
    Intervals, puis chez BRouter, puis chez Open-Meteo. `profil` est le
    profil **BRouter** (`--profil`), `config` celle du cycliste.
    """
    jour_lu = jour_option(jour)

    distance_km = distance
    if distance_km is not None and (not math.isfinite(distance_km) or distance_km <= 0):
        raise ErreurUtilisateur(
            f"--distance {distance_km} : une distance en kilomètres strictement positive est "
            "attendue (omettre l'option pour la déduire de la séance)"
        )

    libelle, azimut = ("", None)
    if direction is not None:
        libelle, azimut = direction_en_azimut(direction)

    nb = config.boucle.candidates if candidates is None else int(candidates)
    if nb < 1:
        raise ErreurUtilisateur(f"--candidates {nb} : au moins une candidate est attendue")

    if velo:
        config.velo(velo)  # lève ErreurConfig si le vélo n'existe pas

    if not config.brouter.renseigne:
        raise ErreurUtilisateur(
            "sortie : [brouter] url n'est pas renseigné dans la configuration — "
            "y mettre l'adresse du serveur BRouter"
        )

    vent_lu = orientation.valider(vent)
    # Q44 : les deux réglages fixaient le même azimut, et rien ne disait lequel
    # gagnait. `--direction` l'emportait en silence, ce qui laissait le
    # cycliste croire que son orientation au vent avait été honorée. On ne
    # choisit plus un gagnant : on refuse la contradiction, et le message dit
    # les deux formulations possibles. « Peu importe » n'est pas une
    # contradiction — c'est l'absence de demande.
    if azimut is not None and vent_lu != orientation.PEU_IMPORTE:
        raise ErreurUtilisateur(
            f"--direction {libelle} et --vent {vent_lu} demandent tous deux une direction de "
            "recherche, et rien ne dit laquelle devrait l'emporter : choisir sa direction "
            "**ou** la laisser déduire du vent, pas les deux"
        )

    lue = Demande(
        jour=jour_lu,
        distance_km=float(distance_km) if distance_km is not None else None,
        direction=libelle,
        azimut_deg=azimut,
        nb_candidates=nb,
        profil=profil or config.brouter.profil,
        depart=heure_depart_du_jour(depart, jour_lu),
        velo=velo,
        sortie=Path(sortie) if sortie else None,
        carte=Path(carte) if carte else None,
        ecraser=ecraser,
        vent=vent_lu,
        fichier=Path(fichier_seance) if fichier_seance else None,
    )
    for chemin, demande_explicite in (
        (chemin_gpx_par_defaut(lue, config.cache.dossier), lue.sortie is not None),
        (chemin_carte_par_defaut(lue, config.cache.dossier), lue.carte is not None),
    ):
        verifier_ecriture(chemin, explicite=demande_explicite, ecraser=lue.ecraser)
    return lue


# --- la page du jour ------------------------------------------------------------


def ecrire_page_sans_seance(demande: Demande, dossier_cache: Path) -> Path:
    """La page du jour quand rien n'est planifié (contrat de l'hébergé minimal, périmètre point 4).

    Réutilise l'emplacement standard de la carte (`--carte`, ou le nom daté
    par défaut `chemin_carte_par_defaut`) : le serveur statique qui sert le
    dossier n'a besoin de rien savoir de plus qu'un jour ouvré. Le contenu
    dit qu'il n'y a rien à rouler et quand la page a été produite (point 5) —
    une page qui le dit vaut mieux qu'aucune page, jamais une erreur ni la
    page de la veille servie en silence.
    """
    chemin = chemin_carte_par_defaut(demande, dossier_cache)
    try:
        chemin.write_text(page_sans_seance(demande.jour, maintenant=datetime.now()), encoding="utf-8")
    except OSError as e:
        raise ErreurUtilisateur(f"écriture impossible dans {chemin} ({e})") from e
    return chemin


def ecrire_page_jour(
    seance: Seance,
    demande: Demande,
    profil: Profil,
    dossier_cache: Path,
    selection: contraste.Selection,
    gpx_propositions: list[GpxPropose],
) -> Path:
    """La page du jour (lot L5.4) : les propositions contrastées, superposées.

    La page elle-même est construite par `rendu.sortie.page_jour` ; ce module
    ne fait que l'écrire à l'emplacement de la carte (`--carte`, ou le nom
    daté par défaut). Les GPX qu'elle embarque sont ceux de
    `sortie.commande._gpx_propositions`, déjà en mémoire : jamais écrits sur disque, ils
    partent en base64 dans la page (§4.2 du contrat — « le fichier suit le
    choix du cycliste, pas le classement »).
    """
    chemin = chemin_carte_par_defaut(demande, dossier_cache)
    page = page_jour(seance, demande, profil, selection, gpx_propositions, maintenant=datetime.now())
    try:
        chemin.write_text(page, encoding="utf-8")
    except OSError as e:
        raise ErreurUtilisateur(f"écriture impossible dans {chemin} ({e})") from e
    return chemin
