"""Sous-commande `ourouler geocoder ADRESSE` : rend les candidats, sans trancher.

Ce module est appelé par `cli.py` et ne lit rien : il reçoit `args` et
`config`. Les clients sont injectables pour que les tests ne touchent jamais
le réseau. `config` n'est pas encore utilisé (le connecteur n'a besoin
d'aucun réglage utilisateur), mais reste au contrat pour que toutes les
sous-commandes s'appellent de la même façon depuis `cli.py`.
"""

from __future__ import annotations

import argparse
import json

from ourouler.config import Config
from ourouler.connecteurs.geocodage import (
    LIMITE_DEFAUT,
    Candidat,
    ClientBAN,
    ClientNominatim,
    chercher_adresse,
)


def executer(
    args: argparse.Namespace,
    config: Config,
    ban: ClientBAN | None = None,
    nominatim: ClientNominatim | None = None,
) -> int:
    """Exécute `ourouler geocoder`. Renvoie le code de sortie (0 = succès)."""
    del config  # non utilisé ici, gardé pour la même signature que les autres sous-commandes
    adresse = args.adresse
    limite = getattr(args, "max", None) or LIMITE_DEFAUT

    candidats = chercher_adresse(adresse, ban=ban, nominatim=nominatim, limite=limite)

    if getattr(args, "json", False):
        print(json.dumps(rendre_json(adresse, candidats), ensure_ascii=False, indent=2))
    else:
        print(rendre_texte(adresse, candidats))
    return 0


def rendre_json(adresse: str, candidats: list[Candidat]) -> dict:
    return {
        "adresse": adresse,
        "candidats": [
            {
                "label": c.label,
                "latitude": c.latitude,
                "longitude": c.longitude,
                "score": c.score,
                "source": c.source,
            }
            for c in candidats
        ],
    }


def rendre_texte(adresse: str, candidats: list[Candidat]) -> str:
    if not candidats:
        return f"aucune adresse trouvée pour « {adresse} »"
    lignes = [f"{len(candidats)} candidat(s) pour « {adresse} » :"]
    for i, c in enumerate(candidats, start=1):
        lignes.append(
            f"  {i}. {c.label} — {c.latitude:.5f}, {c.longitude:.5f} "
            f"(score {c.score:.2f}, {c.source})"
        )
    return "\n".join(lignes)
