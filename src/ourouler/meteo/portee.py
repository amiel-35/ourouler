"""Jusqu'à quand la météo répond, et ce qu'on dit quand elle ne répond plus.

**Q40 (a) et (b), tranché par le mainteneur le 17/09/2026** : « pour le
jusqu'à quand : aucune limite. Juste, si on demande trop loin, ben pas de
météo. Donc si la personne donne une date hors de portée de la météo, lui
dire direct "pas de météo" et hop. »

Une date lointaine **ne se refuse pas**. Le parcours est servi, et la météo
est déclarée absente : c'est exactement l'état dégradé que les maquettes
dessinent (E14 · dégradé), où la boucle reste là et où disparaissent les
affirmations qu'on ne peut plus soutenir — la pluie, le vent et la tenue.

**Le message dit quel jour est le dernier couvert, jamais pourquoi il ne
l'est pas.** Open-Meteo rend le *même* bloc vide pour un point hors du
domaine d'un modèle et pour une fenêtre hors de sa portée ; le cœur refuse de
trancher, et il a raison (règle absolue 5). Côté produit la distinction ne
sert à rien : dans les deux cas on lit « pas de météo pour ce jour-là », et
le parcours arrive quand même. C'est ce qui referme (b) du même geste.

**Ce qui n'est pas touché, et qui ne doit pas l'être** : le repli de modèle
de Q19. AROME s'arrête en cours de J+2 ; sans repli, une sortie à J+2 ou J+3
perdait *toute* sa météo avec un message trompeur. L'horizon publié ici est
celui du modèle de repli, justement pour que ces jours-là restent couverts —
et E15 sert une séance à J+4 avec sa météo, sans son orientation au vent
(voir `sortie.vent_demande.HORIZON_ORIENTATION_J`, qui est un autre horizon,
plus court, et qui ne concerne que la **direction** du vent).

Ce module ne lit ni configuration ni horloge : il reçoit l'horizon, le jour
demandé et la date du jour (règle absolue 2).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from ourouler.meteo.rapport import jour_en_francais


def dernier_jour_couvert(horizon_jours: int, *, aujourdhui: date) -> date:
    """Le dernier jour pour lequel on accepte de demander une météo."""
    return aujourdhui + timedelta(days=max(int(horizon_jours), 0))


def hors_de_portee(jour: date, horizon_jours: int, *, aujourdhui: date) -> bool:
    """Vrai quand `jour` est au-delà de l'horizon — on n'appellera pas Open-Meteo."""
    return jour > dernier_jour_couvert(horizon_jours, aujourdhui=aujourdhui)


@dataclass(frozen=True)
class MeteoAbsente:
    """L'état « pas de météo », dit une fois, en toutes lettres.

    Le front branche l'écran E14 · dégradé dessus : `message` s'affiche tel
    quel, et `dernier_jour_couvert` lui donne de quoi griser un calendrier
    sans recalculer l'horizon lui-même.
    """

    #: Le jour demandé.
    jour: date
    #: Le dernier jour pour lequel le produit accepte d'interroger la météo.
    dernier_jour_couvert: date
    #: La phrase à afficher. Voir `constater` pour ce qu'elle dit, et surtout
    #: ce qu'elle ne dit pas.
    message: str

    @property
    def hors_de_portee(self) -> bool:
        """Vrai quand le jour demandé est au-delà du dernier jour couvert."""
        return self.jour > self.dernier_jour_couvert

    def json(self) -> dict:
        return {
            "jour": self.jour.isoformat(),
            "dernier_jour_couvert": self.dernier_jour_couvert.isoformat(),
            "message": self.message,
        }


def constater(jour: date, dernier_jour: date) -> MeteoAbsente:
    """La phrase de l'absence de météo — le dernier jour couvert, pas le motif.

    Deux cas, une seule forme :

    - le jour demandé est **au-delà** du dernier jour couvert : on le dit, et
      on dit jusqu'où on va, parce que c'est la seule information qui aide
      (« revenez dans quatre jours » se déduit, « hors du domaine » non) ;
    - le jour est dans l'horizon et la météo a quand même manqué (service en
      panne, point non couvert) : on dit qu'il n'y a pas de météo, et rien de
      plus. Ajouter « les prévisions s'arrêtent au … » ici serait faux : elles
      couvrent ce jour-là, elles n'ont simplement rien rendu.
    """
    debut = f"pas de météo pour le {jour_en_francais(jour)}"
    absente = MeteoAbsente(jour=jour, dernier_jour_couvert=dernier_jour, message=debut)
    if not absente.hors_de_portee:
        return absente
    return MeteoAbsente(
        jour=jour,
        dernier_jour_couvert=dernier_jour,
        message=f"{debut} — les prévisions s'arrêtent au {jour_en_francais(dernier_jour)}",
    )


__all__ = [
    "MeteoAbsente",
    "constater",
    "dernier_jour_couvert",
    "hors_de_portee",
]
