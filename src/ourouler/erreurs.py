"""Exceptions communes.

`ErreurUtilisateur` : une erreur que l'utilisateur peut corriger (fichier
illisible, configuration incomplète, API injoignable). La CLI l'affiche en
une ligne et sort avec le code 2. Toute autre exception est un bug.
"""


class ErreurUtilisateur(Exception):
    """Erreur destinée à l'utilisateur, affichée sans trace."""


class ErreurConfig(ErreurUtilisateur, ValueError):
    """Configuration absente, incomplète ou invalide. Le message nomme le champ."""


class ErreurLecture(ErreurUtilisateur):
    """Fichier d'activité illisible (vide, tronqué, format inconnu)."""


class ErreurConnecteur(ErreurUtilisateur):
    """Échec d'un appel à un service externe. Ne contient jamais de clé."""
