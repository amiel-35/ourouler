"""Ancien chemin de `ourouler.services.comparer` (lot 10)."""

# Réexport temporaire, retiré au lot final. `executer_comparer` n'y est plus :
# lire les options est l'affaire de `commandes/comparer.py`.
from ourouler.services.comparer import (
    CAP_MAX_DEG_SUGGERE,
    LONGUEUR_MIN_M_DEFAUT,
    NB_BANDES,
    PENTE_MAX_DEFAUT,
    SERIES_MIN_BANDE,
    SERIES_MIN_REGRESSION,
    ZONE_DEFAUT,
    Bande,
    Comparaison,
    DemandeComparaison,
    Regression,
    ResultatComparaison,
    ResultatVelo,
    Serie,
    bornes_bandes,
    comparer,
    regresser,
    series_droites,
)

__all__ = [
    "CAP_MAX_DEG_SUGGERE",
    "LONGUEUR_MIN_M_DEFAUT",
    "NB_BANDES",
    "PENTE_MAX_DEFAUT",
    "SERIES_MIN_BANDE",
    "SERIES_MIN_REGRESSION",
    "ZONE_DEFAUT",
    "Bande",
    "Comparaison",
    "DemandeComparaison",
    "Regression",
    "ResultatComparaison",
    "ResultatVelo",
    "Serie",
    "bornes_bandes",
    "comparer",
    "regresser",
    "series_droites",
]
