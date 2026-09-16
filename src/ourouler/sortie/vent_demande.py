"""La question d'orientation au vent, posée **avant** la recherche.

Idée du mainteneur, et elle réduit aussi l'espace de recherche : « pour moi ça
peut être une question avant de lancer la recherche » plutôt que de contraster
après coup. Forme retenue : une option, dont **« peu importe » est une réponse
valable et le défaut** — elle retombe alors sur les propositions contrastées.
Quand il répond, on cherche dans cette direction.

Deux gardes, tous deux mesurés
------------------------------

**On ne pose la question que si le vent a un effet.** Sous
`seance.vent.SEUIL_VENT_SENSIBLE_KMH` (8 km/h, le haut de la force 1 de
Beaufort), l'orientation ne change rien de perceptible et la question
n'apprend qu'à cliquer sans lire. C'est **la même constante** que celle qui
décide de dessiner les flèches de vent sur la carte : si le vent ne mérite pas
d'être montré, il ne mérite pas qu'on demande son orientation.

**On ne la pose pas au-delà de trois jours.** Mesuré le 16/09/2026 sur
2 064 heures à Rennes, référence archive ERA5 : la direction tombe dans le bon
secteur de ±45° neuf fois sur dix à 1-3 jours (93 %, 92 %, 88 %) et plus
qu'une fois sur cinq à 5 jours (78 %) ; AROME France HD, notre modèle
principal, s'arrête de toute façon à 67 h. **Trois jours inclus**, quatre non :
88 % reste utile, la suite ne l'est plus. Au-delà, l'outil dit qu'il ne sait
pas plutôt que de promettre « vous rentrerez avec le vent dans le dos »
(règle absolue 5).

Ce module ne lit ni configuration ni chemin : il reçoit le client météo et le
point de départ (règle absolue 2).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime

from ourouler.config import Depart
from ourouler.erreurs import ErreurConnecteur, ErreurUtilisateur
from ourouler.meteo.openmeteo import ClientOpenMeteo
from ourouler.seance.vent import SEUIL_VENT_SENSIBLE_KMH
from ourouler.sortie.orientation import (
    ORIENTATION_DEPART_DOS,
    ORIENTATION_RETOUR_DOS,
    ORIENTATION_TRAVERS,
)

#: Horizon au-delà duquel on ne propose plus d'orientation au vent, en jours.
#: **Inclusif** : à 3 jours la direction tombe dans le bon secteur 88 % du
#: temps, à 4 jours 85 % et AROME est déjà sorti du jeu (67 h).
HORIZON_ORIENTATION_J = 3

#: Ce que chaque réponse fait de l'azimut de recherche, en degrés **ajoutés à
#: la direction d'où vient le vent**.
#:
#: Une boucle part et revient au même endroit : pour rentrer avec le vent dans
#: le dos, il faut **partir vers lui**, c'est-à-dire viser la direction d'où il
#: vient (décalage 0). Pour partir avec, viser l'opposé (180). Pour le
#: travers, viser à 90° — un seul des deux côtés, le moteur explorera l'autre
#: par ses azimuts voisins (`boucle.candidates.azimuts` balaie ±20°, ±40°…).
DECALAGE_AZIMUT_DEG = {
    ORIENTATION_RETOUR_DOS: 0.0,
    ORIENTATION_DEPART_DOS: 180.0,
    ORIENTATION_TRAVERS: 90.0,
}


@dataclass(frozen=True)
class QuestionVent:
    """Le vent au départ, et ce qu'on a le droit d'en dire."""

    #: Vent moyen au point de départ à l'heure de départ, en km/h.
    vent_kmh: float | None
    #: Direction d'où vient le vent, en degrés.
    vent_depuis_deg: float | None
    #: Vrai quand les deux gardes passent : c'est alors qu'on pose la question.
    posee: bool
    #: Pourquoi on ne la pose pas, en clair. Vide quand elle est posée.
    motif: str = ""

    def azimut_pour(self, reponse: str) -> float | None:
        """L'azimut de recherche qu'impose `reponse`, ou `None` si aucune contrainte."""
        if not self.posee or self.vent_depuis_deg is None:
            return None
        decalage = DECALAGE_AZIMUT_DEG.get(reponse)
        if decalage is None:
            return None
        return (self.vent_depuis_deg + decalage) % 360.0


def interroger(
    client: ClientOpenMeteo,
    depart_lieu: Depart,
    *,
    depart_heure: datetime,
    jour: date,
    modele: str,
    aujourdhui: date | None = None,
) -> QuestionVent:
    """Le vent au départ, et si la question de l'orientation mérite d'être posée.

    **Un seul appel Open-Meteo, sur un seul point et une seule heure** : c'est
    le poste le moins cher de la commande, et il tombe avant les appels
    BRouter, donc avant ce qui coûte.

    Une panne d'Open-Meteo ne fait pas perdre la sortie : la question n'est
    pas posée, le motif le dit, et la recherche part sans contrainte.
    """
    aujourdhui = aujourdhui or date.today()
    avance = (jour - aujourdhui).days
    if avance > HORIZON_ORIENTATION_J:
        return QuestionVent(
            vent_kmh=None,
            vent_depuis_deg=None,
            posee=False,
            motif=(
                f"séance dans {avance} jours : au-delà de {HORIZON_ORIENTATION_J}, la direction "
                "du vent se trompe de secteur plus d'une fois sur cinq et AROME ne répond plus "
                "— on ne promet pas une orientation qu'on ne sait pas prévoir"
            ),
        )
    try:
        points = client.previsions(
            [(depart_lieu.latitude, depart_lieu.longitude)],
            modele=modele,
            debut=depart_heure,
            horizon_h=1,
        )
    except (ErreurConnecteur, ErreurUtilisateur) as e:
        return QuestionVent(
            vent_kmh=None, vent_depuis_deg=None, posee=False,
            motif=f"vent au départ indisponible ({e})",
        )
    heures = points[0].heures if points else []
    heure = heures[0] if heures else None
    vitesse = heure.vent_kmh if heure is not None else None
    direction = heure.vent_depuis_deg if heure is not None else None
    if vitesse is None or not math.isfinite(vitesse) or direction is None:
        return QuestionVent(
            vent_kmh=vitesse, vent_depuis_deg=direction, posee=False,
            motif="vent au départ inconnu : la prévision ne le donne pas",
        )
    if vitesse < SEUIL_VENT_SENSIBLE_KMH:
        return QuestionVent(
            vent_kmh=vitesse, vent_depuis_deg=direction, posee=False,
            motif=(
                f"{vitesse:.0f} km/h au départ, sous les {SEUIL_VENT_SENSIBLE_KMH:.0f} km/h "
                "à partir desquels on sent le vent sur le visage : l'orientation ne change "
                "rien de perceptible"
            ),
        )
    return QuestionVent(vent_kmh=vitesse, vent_depuis_deg=direction, posee=True)
