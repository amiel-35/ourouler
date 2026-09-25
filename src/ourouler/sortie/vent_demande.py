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
from ourouler.meteo.openmeteo import ClientOpenMeteo
from ourouler.noyau.erreurs import ErreurConnecteur, ErreurHorsDomaine, ErreurUtilisateur
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
#: la direction d'où vient le vent**. Une réponse rend **un ou deux** azimuts.
#:
#: Une boucle part et revient au même endroit : pour rentrer avec le vent dans
#: le dos, il faut **partir vers lui**, c'est-à-dire viser la direction d'où il
#: vient (décalage 0). Pour partir avec, viser l'opposé (180).
#:
#: **Le travers en ouvre deux, opposés** (Q44, 17/09/2026). Le vent latéral ne
#: nomme pas un côté : à 90° comme à 270° de la direction d'où souffle le vent,
#: il vient du flanc, et les deux sont également valables. Jusqu'ici on n'en
#: gardait qu'un, en comptant sur les azimuts voisins de
#: `boucle.candidates.azimuts` (±20°, ±40°…) pour explorer l'autre — or ils
#: n'atteignent jamais 180° d'écart : ils élargissent un secteur, ils n'en
#: ouvrent pas un second.
#:
#: Et c'est la préférence la plus intéressante pour qui veut trois propositions
#: différentes : deux directions séparées de 180° ne partagent que **0,4 %** de
#: leurs routes (médiane, boucles de 60 km, mesure du 16/09/2026 documentée
#: sous `contraste.SEUIL_RECOUVREMENT`), contre 28 % à 30° d'écart. La
#: préférence qui contraint le moins l'azimut est celle qui produit les
#: propositions les moins ressemblantes — réponse par la conception à Q43 et
#: Q45.
DECALAGE_AZIMUT_DEG: dict[str, tuple[float, ...]] = {
    ORIENTATION_RETOUR_DOS: (0.0,),
    ORIENTATION_DEPART_DOS: (180.0,),
    ORIENTATION_TRAVERS: (90.0, 270.0),
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

    def azimuts_pour(self, reponse: str) -> tuple[float, ...]:
        """Les azimuts de recherche qu'impose `reponse`. Vide si aucune contrainte.

        **Un ou deux**, jamais plus : « rentrer avec » et « partir avec » en
        fixent un, « de travers » en ouvre deux opposés (Q44). Le tuple vide
        veut dire « cherchez partout » — c'est ce que rend « peu importe », et
        aussi ce que rend une question non posée, vent trop faible ou trop
        lointain : on ne dirige pas une recherche sur un vent qu'on ne sait pas
        prévoir (règle absolue 5).

        Il n'existe **pas** de variante qui n'en rendrait qu'un : un appelant
        qui prendrait le premier et jetterait le second entasserait toutes les
        candidates du travers sur un seul côté, ce qui est précisément le
        défaut que Q44 demande d'éviter.
        """
        if not self.posee or self.vent_depuis_deg is None:
            return ()
        decalages = DECALAGE_AZIMUT_DEG.get(reponse)
        if decalages is None:
            return ()
        azimuts = tuple((self.vent_depuis_deg + d) % 360.0 for d in decalages)
        # Dernière barrière avant BRouter : `interroger` refuse déjà une
        # direction non finie, mais `QuestionVent` est un objet public qu'un
        # appelant peut construire lui-même, et `nan % 360` vaut `nan`. Un
        # azimut non fini partirait tel quel dans `roundTripStartDirection`.
        # Un seul azimut non fini disqualifie toute la réponse : rendre la
        # moitié d'un couple d'opposés serait pire que de ne rien rendre.
        return azimuts if all(math.isfinite(a) for a in azimuts) else ()


def interroger(
    client: ClientOpenMeteo,
    depart_lieu: Depart,
    *,
    depart_heure: datetime,
    jour: date,
    modele: str,
    modele_repli: str = "",
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
    def _demander(nom: str):
        return client.previsions(
            [(depart_lieu.latitude, depart_lieu.longitude)],
            modele=nom,
            debut=depart_heure,
            horizon_h=1,
        )

    try:
        points = _demander(modele)
    except ErreurHorsDomaine:
        # Même repli que la météo du tracé (Q19) : le modèle régional ne couvre
        # pas la fenêtre, le modèle global la couvre. Sans ce repli, la page
        # affichait le vent dans son tableau **et** « vent indisponible » dans
        # la question d'orientation, sur la même sortie — une contradiction que
        # le mainteneur aurait vue avant nous.
        if not modele_repli:
            return QuestionVent(
                vent_kmh=None, vent_depuis_deg=None, posee=False,
                motif=f"{modele} ne couvre pas cette fenêtre et aucun modèle de repli n'est configuré",
            )
        try:
            points = _demander(modele_repli)
        except (ErreurConnecteur, ErreurUtilisateur) as e:
            return QuestionVent(
                vent_kmh=None, vent_depuis_deg=None, posee=False,
                motif=f"vent au départ indisponible, repli {modele_repli} compris ({e})",
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
    # `_fini` des deux côtés, et pas seulement de la vitesse : une direction
    # `nan` passait les deux gardes, ressortait en `azimuts_pour` (`nan % 360`
    # vaut `nan`), traversait `boucle.candidates.azimuts` et partait chez
    # BRouter en `roundTripStartDirection=nan`. Un nombre non fini est une
    # **ignorance**, exactement comme une valeur absente — c'est déjà la règle
    # de `seance.vent._utilisable`, et il n'y a pas deux façons de la tenir.
    if not _fini(vitesse) or not _fini(direction):
        return QuestionVent(
            vent_kmh=vitesse if _fini(vitesse) else None,
            vent_depuis_deg=direction if _fini(direction) else None,
            posee=False,
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


def _fini(valeur: object) -> bool:
    """Vrai si la valeur est un nombre exploitable : présente **et** finie.

    Même règle que `seance.vent._utilisable`, dont c'est le pendant côté
    prévision : un NaN ou un infini reçu d'Open-Meteo est une ignorance, pas
    une mesure.
    """
    return isinstance(valeur, (int, float)) and math.isfinite(valeur)
