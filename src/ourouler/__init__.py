"""ourouler — où rouler ? Météo par direction, tracé et séance pour cyclistes.

Nom de travail (voir doctrine_architecture.md §1). Bibliothèque + CLI.
"""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("ourouler")
except PackageNotFoundError:
    # Paquet non installé (ex. exécution depuis les sources sans `pip install -e`
    # ni `uv sync`) : repli explicite, jamais un numéro figé qui prétendrait
    # être la vraie version.
    __version__ = "0.0.0+inconnue"
