"""Les options de la ligne de commande partagées par plusieurs sous-commandes."""

from __future__ import annotations

import argparse


def parent_json() -> argparse.ArgumentParser:
    """Parseur parent qui rend `--json` acceptable **après** la sous-commande.

    On écrit naturellement `ourouler meteo [...] [--json]` ; avec l'option en
    global seulement, `ourouler meteo --json` répondrait « unrecognized
    arguments », et la seule forme qui marche (`ourouler --json meteo`) ne
    serait écrite nulle part.

    Deux précautions :
    - `add_help=False`, sinon le parent redéclare `-h` et argparse refuse ;
    - `default=argparse.SUPPRESS`, sinon le sous-parseur écrirait
      `json=False` par-dessus la valeur posée par l'option globale et
      casserait `ourouler --json meteo`. Avec SUPPRESS, l'attribut n'est
      touché que si l'option est vraiment passée.

    Le `dest` reste `json` des deux côtés : les commandes lisent un seul champ.
    """
    parent = argparse.ArgumentParser(add_help=False)
    parent.add_argument(
        "--json",
        action="store_true",
        default=argparse.SUPPRESS,
        help="sortie JSON au lieu du texte (accepté avant ou après la sous-commande)",
    )
    return parent


#: Les anciens noms de l'heure de départ, acceptés et **non documentés**.
#:
#: L'heure de départ s'appelle `--heure-depart` et le lieu de départ
#: `--adresse-depart` (décision Q15, `docs/journal/questions/questions_mainteneur.md`). `--depart`
#: seul serait ambigu à côté du lieu ; `--heure` est un ancien nom provisoire.
#:
#: Les deux restent acceptés pour ne rien casser — des scripts et des
#: habitudes s'en servent — mais ils ne figurent plus dans l'aide : un nom déprécié
#: qu'on documente est un nom qu'on enseigne encore.
ANCIENS_NOMS_HEURE_DEPART = ("--depart", "--heure")


def ajouter_heure_depart(p: argparse.ArgumentParser, aide: str) -> None:
    """Ajoute `--heure-depart` à une sous-commande, plus ses anciens noms.

    Deux déclarations et non une seule liste d'alias, parce qu'argparse ne
    sait pas masquer un alias dans l'aide : il les imprime tous ou aucun. La
    seconde déclaration, sous `argparse.SUPPRESS`, écrit dans le même `dest`
    que la première — `depart`, inchangé, pour que les commandes continuent de
    lire un seul champ.
    """
    p.add_argument("--heure-depart", dest="depart", metavar="HEURE", help=aide)
    p.add_argument(
        *ANCIENS_NOMS_HEURE_DEPART,
        dest="depart",
        metavar="HEURE",
        help=argparse.SUPPRESS,
    )


def ajouter_adresse_depart(p: argparse.ArgumentParser) -> None:
    """Ajoute `--adresse-depart` : partir d'ailleurs **cette fois**, sans rien réécrire.

    Le nom est celui de la décision Q15, et il est long exprès : `--depart`
    disait « heure », `--adresse-depart` dit « lieu ». Les deux options
    cohabitent sur la même ligne de commande sans se marcher dessus, elles
    n'écrivent pas dans le même `dest` (`depart` pour l'heure,
    `adresse_depart` pour le lieu).
    """
    p.add_argument(
        "--adresse-depart",
        dest="adresse_depart",
        metavar="ADRESSE",
        help="partir d'une autre adresse que celle de la configuration, cette fois seulement "
        "(géocodée ; la configuration n'est pas modifiée). Ne pas confondre avec "
        "--heure-depart, qui est une heure.",
    )
