"""Ce qu'un cas d'usage reçoit de son appelant, en plus de la demande.

La `Demande` porte ce que le
cycliste a demandé, déjà interprété ; le `Contexte` porte **où** et **pour
qui** le service travaille — le profil du cycliste, le dossier de cache et le
fichier de calibration déjà résolus, et la façon de faire part d'un
avertissement. Les clients HTTP et les dépôts, eux, restent des paramètres
nommés du service, injectables un par un comme avant.

Le service ne lit donc ni `Config.cache` ni le répertoire de l'utilisateur :
c'est l'entrée (`cli/`, l'API) qui résout les chemins, une fois.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from ourouler.noyau.profil import Profil


def _taire(ligne: str) -> None:
    """L'avertissement par défaut : on ne le montre à personne."""


@dataclass(frozen=True)
class Contexte:
    """Le profil, les chemins résolus et le canal des avertissements d'un service.

    `avertir` reçoit une ligne complète, préfixe « ourouler : » compris, **au
    moment où** le service la produit : la ligne de commande l'imprime sur la
    sortie d'erreur, l'API la capture et la rend dans `avertissements`. Le
    service ne sait pas lequel des deux l'écoute.
    """

    profil: Profil
    dossier_cache: Path
    fichier_calibration: Path
    avertir: Callable[[str], None] = _taire
