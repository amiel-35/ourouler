"""`python -m ourouler.cli` : le même point d'entrée que la commande `ourouler`."""

import sys

from ourouler.cli import main

if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
