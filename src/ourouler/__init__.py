"""ourouler — où rouler ? Météo par direction, tracé et séance pour cyclistes.

Pour un cycliste équipé d'un capteur de puissance : où il va pleuvoir selon
la direction, puis une boucle de la bonne durée, cohérente avec la séance du
jour et la tenue. Une bibliothèque Python, une ligne de commande (`cli/`)
et une API HTTP (`api/`) que sert une interface web (`front/`). La carte des
paquets est dans `ARCHITECTURE.md`.
"""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("ourouler")
except PackageNotFoundError:
    # Paquet non installé (ex. exécution depuis les sources sans `pip install -e`
    # ni `uv sync`) : repli explicite, jamais un numéro figé qui prétendrait
    # être la vraie version.
    __version__ = "0.0.0+inconnue"
