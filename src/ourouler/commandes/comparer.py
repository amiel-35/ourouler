"""`ourouler comparer` : la demande, le service, le rendu imprimé.

Les options (`--velos`, `--zone`, `--pente-max`, `--cap-max`,
`--longueur-min`, `--depuis`) sont lues et bornées ici, **avant** la moindre
lecture du cache ; le service (`services/comparer.py`) reçoit des valeurs.
"""

from __future__ import annotations

import argparse

from ourouler.commandes.commun import contexte, imprimer_json
from ourouler.config import Config
from ourouler.noyau.erreurs import ErreurUtilisateur
from ourouler.physique import calibration as calib
from ourouler.physique.commande import date_option
from ourouler.rendu.physique import rendre_json_comparaison, rendre_texte_comparaison
from ourouler.services import comparer as service
from ourouler.services.comparer import (
    LONGUEUR_MIN_M_DEFAUT,
    PENTE_MAX_DEFAUT,
    ZONE_DEFAUT,
    DemandeComparaison,
)


def lire_options(args: argparse.Namespace, config: Config) -> DemandeComparaison:
    """Les deux vélos, la FTP, puis les filtres — dans cet ordre, avant tout accès au cache."""
    noms = list(getattr(args, "velos", None) or [])
    if len(noms) != 2:
        raise ErreurUtilisateur(
            "comparer : --velos attend exactement deux noms de vélo, par exemple "
            "`--velos RCR BMC`"
        )
    if noms[0].casefold() == noms[1].casefold():
        raise ErreurUtilisateur(
            f"comparer : {noms[0]} et {noms[1]} sont le même vélo — il n'y a rien à comparer"
        )
    premier, second = (config.velo(nom) for nom in noms)
    if config.cycliste.ftp_w is None:
        raise ErreurUtilisateur(
            "comparer : FTP non renseignée dans la configuration — cette commande compare "
            "des sorties par zone de puissance relative à la FTP, il en faut une"
        )
    return DemandeComparaison(
        velos=(premier, second),
        zone_ftp=_zone(getattr(args, "zone", None)),
        pente_max=_pente_max(getattr(args, "pente_max", None)),
        cap_max=_cap_max(getattr(args, "cap_max", None)),
        longueur_min=_longueur_min(getattr(args, "longueur_min", None)),
        depuis=date_option(getattr(args, "depuis", None), config.historique_depuis),
    )


def executer_depuis_namespace(args: argparse.Namespace, config: Config) -> int:
    """Exécute `ourouler comparer`. Code de sortie 0 si la comparaison a eu lieu."""
    resultat = service.executer(lire_options(args, config), contexte(config))
    if getattr(args, "json", False):
        imprimer_json(rendre_json_comparaison(resultat.comparaison, resultat.depuis))
    else:
        print(rendre_texte_comparaison(resultat.comparaison, resultat.depuis))
    return 0


# --- options ------------------------------------------------------------------


def _pente_max(valeur) -> float:
    return _fraction(valeur, PENTE_MAX_DEFAUT, "--pente-max", "0.008 = 0,8 %")


def _attendu(option: str, valeur, exemple: str) -> str:
    return f"{option} {valeur!r} : une valeur entre 0 et 1 est attendue ({exemple})"


def _fraction(valeur, defaut: float, option: str, exemple: str) -> float:
    if valeur is None:
        return defaut
    try:
        fraction = float(valeur)
    except (TypeError, ValueError) as e:
        raise ErreurUtilisateur(_attendu(option, valeur, exemple)) from e
    if not (0 <= fraction <= 1):
        raise ErreurUtilisateur(_attendu(option, valeur, exemple))
    return fraction


def _zone(valeur) -> tuple[float, float]:
    if not valeur:
        return ZONE_DEFAUT
    bornes = list(valeur)
    if len(bornes) != 2:
        raise ErreurUtilisateur(
            "--zone attend deux fractions de la FTP, par exemple `--zone 0.56 0.75`"
        )
    bas = _fraction(bornes[0], ZONE_DEFAUT[0], "--zone", "0.56 = 56 % de la FTP")
    haut = _fraction(bornes[1], ZONE_DEFAUT[1], "--zone", "0.75 = 75 % de la FTP")
    if not (bas < haut):
        raise ErreurUtilisateur(
            f"--zone {bornes[0]} {bornes[1]} : la borne basse doit être sous la borne haute"
        )
    return (bas, haut)


def _cap_max(valeur) -> float | None:
    """`None` quand l'option n'est pas posée : aucun filtre de cap."""
    if valeur is None:
        return None
    try:
        cap = float(valeur)
    except (TypeError, ValueError) as e:
        raise ErreurUtilisateur(f"--cap-max {valeur!r} : un angle en degrés est attendu") from e
    if not (0 <= cap <= 180):
        raise ErreurUtilisateur(f"--cap-max {valeur!r} : un angle entre 0 et 180 degrés est attendu")
    return cap


def _longueur_min(valeur) -> float:
    if valeur is None:
        return LONGUEUR_MIN_M_DEFAUT
    try:
        longueur = float(valeur)
    except (TypeError, ValueError) as e:
        raise ErreurUtilisateur(f"--longueur-min {valeur!r} : une longueur en mètres est attendue") from e
    if longueur < calib.LONGUEUR_ECHANTILLON_M:
        raise ErreurUtilisateur(
            f"--longueur-min {valeur!r} : au moins la longueur d'un tronçon "
            f"({calib.LONGUEUR_ECHANTILLON_M:.0f} m) est attendue"
        )
    return longueur
