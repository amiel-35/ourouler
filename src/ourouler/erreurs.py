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


class ErreurHorsDomaine(ErreurConnecteur):
    """Open-Meteo ne rend rien pour ce point ou cette fenêtre (Q19).

    Distincte de `ErreurConnecteur` pour qu'un appelant puisse retenter avec
    un modèle de repli (`second_avis`) sans risquer de masquer une vraie
    panne réseau, un JSON illisible ou un service qui refuse la requête —
    ceux-là restent des `ErreurConnecteur` ordinaires, sur lesquels retenter
    ne changerait rien. Deux signatures mesurées sur le vrai service tombent
    dans cette catégorie : un corps HTTP 200 truffé de littéraux `nan`, et un
    bloc entièrement à `null` — la seconde étant **aussi** ce qu'Open-Meteo
    rend au-delà de la portée temporelle du modèle, pas seulement hors de sa
    grille géographique."""
