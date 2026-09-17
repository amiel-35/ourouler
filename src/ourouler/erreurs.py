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


class ErreurDistanceInatteignable(ErreurConnecteur):
    """Le moteur rend bien des boucles, mais toutes trop loin de la distance voulue.

    Distincte de la panne : le serveur a répondu, les tracés sont bornés, ils
    sont simplement d'une autre longueur que celle demandée. C'est un fait de
    terrain, pas un incident, et l'écran a besoin de le distinguer pour dire
    *de combien* il aurait fallu élargir au lieu d'un « réessayez » (Q41 d).

    Les mesures qui justifient le refus voyagent avec l'exception — cible,
    meilleure distance obtenue, écart, tolérance, élargissement qu'il aurait
    fallu et plafond — pour que personne n'ait à les recalculer plus haut.
    Sous-classe d'`ErreurConnecteur` pour que tout ce qui l'attrapait déjà
    (code de sortie de la CLI, code d'erreur de l'API) continue de marcher.
    """

    def __init__(
        self,
        message: str,
        *,
        distance_cible_km: float,
        distance_obtenue_km: float,
        ecart_relatif: float,
        tolerance: float,
        elargissement_requis: float,
        elargissement_max: float,
    ) -> None:
        super().__init__(message)
        self.distance_cible_km = distance_cible_km
        self.distance_obtenue_km = distance_obtenue_km
        self.ecart_relatif = ecart_relatif
        self.tolerance = tolerance
        self.elargissement_requis = elargissement_requis
        self.elargissement_max = elargissement_max


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
