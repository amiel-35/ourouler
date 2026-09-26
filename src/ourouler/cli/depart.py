"""Le point de départ de la ligne de commande : `--adresse-depart` géocodée, ou la configuration."""

from __future__ import annotations

import argparse
import sys

from ourouler.config import Config
from ourouler.connecteurs.geocodage import (
    LIMITE_DEFAUT,
    Candidat,
    ClientBAN,
    ClientNominatim,
    ambiguite,
    chercher_adresse,
)
from ourouler.noyau.erreurs import ErreurUtilisateur
from ourouler.noyau.profil import Depart

#: Mention exigée par la licence ODbL quand un résultat Nominatim est affiché
#: (politique d'usage du service, voir la docstring du connecteur).
ATTRIBUTION_NOMINATIM = "© contributeurs OpenStreetMap"


def lieu_depart(
    args: argparse.Namespace,
    config: Config,
    *,
    ban: ClientBAN | None = None,
    nominatim: ClientNominatim | None = None,
    avertir_routes: bool = False,
    flux: object = None,
) -> Depart:
    """Le point de départ de cette exécution : `--adresse-depart` géocodée, ou la configuration.

    C'est **ici**, dans le paquet `cli/`, que l'adresse devient un `Depart` : le cœur
    ne géocode rien et ne connaît aucune adresse (le cœur ne lit ni configuration ni environnement). Les deux
    clients sont injectables pour que les tests ne touchent jamais le réseau.

    **Une adresse ambiguë est la normale, pas l'exception**, et le connecteur
    (`connecteurs/geocodage.py`) ne tranche jamais : il rend une liste ordonnée. Une ligne de
    commande, elle, doit bien partir de quelque part — elle ne peut pas rendre
    une liste à qui a tapé `ourouler boucle --adresse-depart "…"`.

    **Dans le doute, on refuse** (décision Q34, `docs/journal/questions/questions_mainteneur.md`). Une
    adresse ambiguë n'est pas tranchée au hasard, elle est **refusée**, avec
    ses candidats affichés pour que l'utilisateur précise et relance. C'est en
    ligne de commande que ce refus a le plus de sens : personne n'y confirme un
    point sur une carte, et le seul échec qui coûte cher est de rouler depuis
    un point qu'on croyait être un autre.

    **Ce qu'« ambigu » veut dire ici, et ce qu'il ne veut pas dire.** Pas un
    écart de score : la mesure sur la vraie BAN montre que
    l'écart entre les deux premiers candidats vaut 0,0020 quand la réponse est
    juste et 0,0016 à 0,0024 quand elle est arbitraire — aucun seuil ne les
    sépare. C'est `geocodage.ambiguite()` qui décide, sur la **commune** :
    plusieurs communes en présence, ou pas de commune du tout, et l'on refuse.
    Le raisonnement complet et les quinze requêtes qui le fondent sont dans sa
    docstring.

    Ce qui n'est **pas** ambigu, et reste donc tranché sans un mot de plus :
    plusieurs candidats dans la même commune. La BAN en rend presque toujours
    plusieurs (le numéro voisin, la rue sans numéro), et deux numéros de la
    même rue ne changent pas où l'on part à vélo. Le premier est retenu et
    annoncé en toutes lettres sur la sortie d'erreur avant tout appel coûteux ;
    `ourouler geocoder` montre la liste complète.

    **Ce que l'API fait, et qui est l'inverse.** Une requête d'API n'a
    pas de sortie d'erreur que quelqu'un lise, et le front, lui, *peut*
    montrer une liste, et une carte, et demander la commune dans un champ à
    part. L'API expose donc le géocodage comme une route à part (la forme de
    `ourouler geocoder --json`, écrite pour ça), rend **tous** les candidats au
    front avec leur score, leur source **et leur commune**, et les routes de
    parcours reçoivent ensuite des **coordonnées déjà tranchées** — jamais une
    adresse à géocoder au vol. Là où la CLI refuse, l'API ne refuse pas et fait
    choisir sur une carte : deux façons de tenir la même décision, chacune avec
    ce que sa surface permet.

    Une adresse introuvable lève `ErreurUtilisateur` — affichée en une ligne,
    code de sortie 2, aucune trace Python. Elle ne retombe **jamais** sur le
    départ configuré : rendre une boucle autour de la maison à qui a demandé
    une autre ville serait une réponse fausse, ce qui est pire qu'une erreur.

    **Ordre assumé** : le géocodage a lieu **avant** que la sous-commande
    valide ses autres options, donc `boucle --adresse-depart X --distance -5`
    interroge le géocodeur avant de refuser la distance. Les commandes tiennent
    par ailleurs à refuser une option fautive avant tout appel réseau, et cette
    ligne y déroge : c'est un appel unique, sans clé et gratuit, contre la
    complication qu'il faudrait pour le repousser après une validation qui vit
    dans le cœur. Le contrat vaut pour BRouter, Open-Meteo et Intervals — les
    postes qui coûtent — et il est intact.
    """
    adresse = getattr(args, "adresse_depart", None)
    if adresse is None:
        return config.depart
    if not adresse.strip():
        raise ErreurUtilisateur(
            f"--adresse-depart {adresse!r} : valeur vide, attendu une adresse — "
            "omettre l'option pour partir du point de la configuration"
        )

    candidats = chercher_adresse(adresse, ban=ban, nominatim=nominatim, limite=LIMITE_DEFAUT)
    if not candidats:
        raise ErreurUtilisateur(
            f"--adresse-depart {adresse!r} : aucune adresse trouvée — préciser la commune "
            "ou le code postal, `ourouler geocoder` montre ce que les services rendent. "
            f"Le départ de la configuration ({config.depart.nom}) n'a pas servi à la place."
        )

    flux = flux if flux is not None else sys.stderr

    trouble = ambiguite(candidats)
    if trouble is not None:
        # Les candidats d'abord, l'erreur ensuite : c'est la liste qui permet
        # de préciser, et `ErreurUtilisateur` s'affiche en une seule ligne.
        print(
            f"ourouler : candidats pour « {adresse} » — {trouble.phrase} :",
            file=flux,
        )
        for i, c in enumerate(candidats, start=1):
            print(f"  {i}. {_ligne_candidat(c)}", file=flux)
        raise ErreurUtilisateur(
            f"--adresse-depart {adresse!r} : adresse ambiguë, rien n'est retenu — "
            "réécrire l'adresse avec sa commune et son code postal, puis relancer. "
            f"Le départ de la configuration ({config.depart.nom}) n'a pas servi à la place."
        )

    retenu = candidats[0]
    ligne = (
        f"ourouler : départ « {retenu.label} » ({retenu.latitude:.5f}, {retenu.longitude:.5f}), "
        f"source {retenu.source}, score {retenu.score:.2f}"
    )
    if len(candidats) > 1:
        ligne += (
            f" — {len(candidats) - 1} autre(s) candidat(s) écarté(s) ; "
            f'`ourouler geocoder "{adresse}"` les montre tous'
        )
    if retenu.source == "nominatim":
        ligne += f" [{ATTRIBUTION_NOMINATIM}]"
    print(ligne, file=flux)

    if avertir_routes and _routes_connues_existent(config):
        print(
            "ourouler : les routes connues et les poids appris ont été mesurés autour du "
            "départ de la configuration — loin de là, « connu % » tombe à zéro sans que le "
            "tracé soit pour autant inédit (la part connue n'entre dans aucun score).",
            file=flux,
        )

    return Depart(nom=retenu.label, latitude=retenu.latitude, longitude=retenu.longitude)


def _ligne_candidat(candidat: Candidat) -> str:
    """Un candidat sur une ligne, commune en évidence — c'est elle qui les distingue."""
    ou = candidat.commune or "commune inconnue"
    if candidat.code_postal:
        ou += f" {candidat.code_postal}"
    return (
        f"{candidat.label} — {ou} — {candidat.latitude:.5f}, {candidat.longitude:.5f} "
        f"(score {candidat.score:.4f}, {candidat.source})"
    )


def _routes_connues_existent(config: Config) -> bool:
    """Vrai si le cache porte déjà une base de routes apprises. Lecture de fichier : `cli/` a le droit."""
    from ourouler.services.apprentissage import NOM_BASE

    try:
        return (config.cache.dossier / NOM_BASE).exists()
    except OSError:
        return False
