"""Structure d'une séance : des étapes à plat, avec une fourchette de puissance.

Le cœur du sprint 4 ne manipule que ces deux objets. Une séance lue chez
Intervals.icu (`seance.intervals`) et une séance écrite à la main dans un
test ont exactement la même forme : **les répétitions sont développées**, il
n'y a plus de groupe ni de `reps`, seulement une liste d'étapes dans l'ordre
où on les roule.

Quatre types d'étapes, et un seul est contraignant pour le terrain :

- `echauffement` et `calme` — les deux zones 2 des extrémités. Ce sont les
  **seules** étapes élastiques (décision du mainteneur du 13/09) : on peut
  les allonger ou les raccourcir pour faire coulisser les blocs jusqu'à un
  bon couloir.
- `bloc` — la prescription : durée et puissance ne bougent pas, et c'est sous
  ces étapes-là que le terrain compte.
- `recuperation` — fixe elle aussi, courte ou longue : elle fait partie de la
  prescription. On ne lui demande rien d'autre que d'exister.

Ce module ne lit aucun fichier et ne connaît ni configuration, ni réseau.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date

from ourouler.erreurs import ErreurUtilisateur

#: Les quatre types d'étape. L'ordre est celui du contrat de sprint 4 §1.
TYPES = ("echauffement", "bloc", "recuperation", "calme")

#: Types dont la durée est élastique quand ils sont en tête ou en queue de séance.
TYPES_ELASTIQUES = ("echauffement", "calme")

#: Bornes des zones de puissance, en **fraction de la FTP**, de Z1 à Z7.
#:
#: C'est la table de Coggan, et c'est aussi, au pourcent près, celle que le
#: compte Intervals.icu du mainteneur renvoie dans `zoneTimes`
#: (Z1 0-55 %, Z2 56-75 %, Z3 76-90 %, Z4 91-105 %, Z5 106-120 %, Z6
#: 121-150 %, Z7 151 % et plus). Le contrat de sprint écrit « ex. Z4 =
#: 105-120 % » : c'est la Z5 de cette table, l'exemple du contrat ne
#: correspond pas aux données réelles et c'est la table observée qui est
#: retenue. Écart signalé.
#:
#: Elle sert deux fois : pour traduire une consigne donnée en zone de
#: puissance (traduction exacte) et pour **approximer** une consigne donnée en
#: zone de fréquence cardiaque **haute** (approximation, toujours annoncée
#: comme telle ; les zones de FC basses passent par
#: `PUISSANCE_ENDURANCE_PCT_DEFAUT`).
ZONES_PUISSANCE_DEFAUT: tuple[tuple[float, float], ...] = (
    (0.00, 0.55),
    (0.56, 0.75),
    (0.76, 0.90),
    (0.91, 1.05),
    (1.06, 1.20),
    (1.21, 1.50),
    (1.51, 2.00),
)

#: Numéro de la plus haute zone de **fréquence cardiaque** considérée comme
#: basse. Jusqu'à Z2 incluse, la table des zones de puissance ne sait pas
#: traduire une consigne de FC (voir `PUISSANCE_ENDURANCE_PCT_DEFAUT`).
ZONE_FC_BASSE_MAX = 2

#: Puissance d'endurance par défaut, en fraction de la FTP.
#:
#: C'est la cible d'une étape prescrite en zone de FC **basse**. Traduire une
#: telle consigne par la table des zones de puissance donne un résultat faux
#: d'un facteur deux : la Z1 de puissance s'étend de 0 à 55 % de FTP, son
#: milieu vaut 27,5 % de FTP — du pédalage à vide — et une zone ouverte vers
#: le bas n'a de toute façon pas de milieu qui veuille dire quelque chose. Une
#: zone de FC n'est pas non plus la zone de puissance de même numéro : un plan
#: qui écrit « Z1 de FC » pour une endurance désigne en pratique une
#: puissance d'endurance franche.
#:
#: 0,60 est la **médiane mesurée** sur les 96 sorties extérieures de plus
#: d'une heure du mainteneur depuis 2025 (154 W pour 258 W de FTP ; 59 % sur
#: toutes les sorties extérieures confondues). Question Q11, close le
#: 13/09/2026. C'est une valeur de cycliste, donc un paramètre de
#: configuration (`[seance] puissance_endurance_pct`), pas une constante du
#: modèle : celle-ci n'est que le défaut.
#:
#: C'est un **garde-fou pour un cas minoritaire**, pas une règle centrale :
#: les séances sont prescrites en pourcentage de FTP dans plus de huit cas
#: sur dix, et celles-là se traduisent exactement.
PUISSANCE_ENDURANCE_PCT_DEFAUT = 0.60

#: Sous cette part de FTP, une étape n'est pas un bloc.
#:
#: C'est le **dernier recours** du typage : quand la séance ne porte ni
#: marqueur (`warmup`, `cooldown`, `intensity`) ni mot reconnaissable dans son
#: texte, il ne reste que la puissance pour distinguer un bloc du reste. Les
#: séances de coach du mainteneur sont dans ce cas : « 4x8 SV1 outdoor » du
#: 22/04/2026 n'a aucun marqueur et aucun texte, ses récupérations ne se
#: reconnaissent qu'à leurs 50 % de FTP entre des efforts à 98 et 145 %.
#:
#: 0,75 est la frontière Z2/Z3 de la table des zones : au-dessus, on est dans
#: l'effort prescrit ; en dessous, on roule. Vérifié sur les deux séances de
#: référence avec 258 W de FTP, soit un seuil à 193 W — 08/02 : 155 W en
#: dessous (échauffement, récups, calme), 212 et 258 W au-dessus (blocs) ;
#: 22/04 : 129 et 134 W en dessous, 253 et 375 W au-dessus.
SEUIL_RECUPERATION_PCT_DEFAUT = 0.75


@dataclass(frozen=True)
class Etape:
    """Un morceau de séance : une durée, un type, et une fourchette de puissance.

    `puissance_min_w` et `puissance_max_w` valent `None` quand la consigne ne
    dit rien de la puissance (étape libre, unité non reconnue, FTP inconnue).
    Une étape sans puissance n'est pas une erreur : elle se roule quand même,
    mais aucune vitesse ne peut en être déduite et aucune longueur de route
    ne lui est attribuée.

    Les deux bornes sont remises dans l'ordre à la construction : une rampe
    descendante (« de 70 % à 40 % ») arrive avec `start > end`, et une
    fourchette dont le minimum serait au-dessus du maximum n'aurait pas de sens
    ailleurs dans le code.
    """

    type: str
    duree_s: float
    puissance_min_w: float | None
    puissance_max_w: float | None
    libelle: str = ""
    elastique: bool = False

    def __post_init__(self) -> None:
        if self.type not in TYPES:
            raise ErreurUtilisateur(
                f"séance : type d'étape {self.type!r} inconnu, attendu un de {TYPES}"
            )
        duree = _fini(self.duree_s, "duree_s")
        if duree < 0:
            raise ErreurUtilisateur(f"séance : durée négative ({duree} s)")
        object.__setattr__(self, "duree_s", float(duree))
        bas = _puissance_valide(self.puissance_min_w, "puissance_min_w")
        haut = _puissance_valide(self.puissance_max_w, "puissance_max_w")
        if bas is not None and haut is not None and bas > haut:
            bas, haut = haut, bas
        object.__setattr__(self, "puissance_min_w", bas)
        object.__setattr__(self, "puissance_max_w", haut)
        if self.elastique and self.type not in TYPES_ELASTIQUES:
            raise ErreurUtilisateur(
                f"séance : une étape de type {self.type!r} n'est jamais élastique "
                f"(seuls {TYPES_ELASTIQUES} le sont)"
            )

    @property
    def puissance_cible_w(self) -> float | None:
        """Le milieu de la fourchette. Une seule borne connue suffit, aucune donne `None`."""
        bornes = [b for b in (self.puissance_min_w, self.puissance_max_w) if b is not None]
        if not bornes:
            return None
        return sum(bornes) / len(bornes)

    @property
    def libelle_court(self) -> str:
        """Le dernier morceau du libellé : la consigne, sans le nom du groupe.

        `libelle` accumule le chemin — « Main Set 4x (2/4) · Z4 (FC) » ; un
        tableau n'a la place que de la fin.
        """
        return self.libelle.rsplit(" · ", 1)[-1].strip()

    @property
    def contraignante(self) -> bool:
        """Vrai pour un bloc : la seule étape sous laquelle le terrain compte."""
        return self.type == "bloc"


@dataclass
class Seance:
    """Une séance planifiée, étapes développées et à plat.

    `duree_s` est la somme des durées des étapes retenues — pas forcément ce
    que la source annonce, puisque les étapes de durée nulle sont écartées.
    L'écart, s'il y en a un, est dans `meta`.

    `meta` porte tout ce que le rendu doit pouvoir dire à l'utilisateur :
    `puissance_approximee`, les unités non reconnues, le nombre d'étapes sans
    consigne de puissance, la FTP utilisée.
    """

    nom: str
    jour: date
    etapes: list[Etape]
    duree_s: float
    meta: dict = field(default_factory=dict)

    def blocs(self) -> list[tuple[int, Etape]]:
        """Les étapes de type « bloc », avec leur indice dans `etapes`."""
        return [(i, e) for i, e in enumerate(self.etapes) if e.type == "bloc"]

    def recuperation_apres(self, indice: int) -> Etape | None:
        """La récupération qui suit immédiatement l'étape `indice`, s'il y en a une.

        C'est elle, et elle seule, qui peut payer un demi-tour : sa première
        moitié sert à dépasser le bout du segment, la seconde à revenir
        dessus (mécanique fixée par le mainteneur le 13/09).
        """
        suivante = indice + 1
        if 0 <= suivante < len(self.etapes) and self.etapes[suivante].type == "recuperation":
            return self.etapes[suivante]
        return None

    @property
    def duree_blocs_s(self) -> float:
        return sum(e.duree_s for _, e in self.blocs())


def _fini(valeur: float, nom: str) -> float:
    try:
        nombre = float(valeur)
    except (TypeError, ValueError) as e:
        raise ErreurUtilisateur(f"séance : {nom} — nombre attendu, reçu {valeur!r}") from e
    if not math.isfinite(nombre):
        raise ErreurUtilisateur(f"séance : {nom} — nombre fini attendu, reçu {valeur!r}")
    return nombre


def _puissance_valide(valeur: float | None, nom: str) -> float | None:
    if valeur is None:
        return None
    nombre = _fini(valeur, nom)
    if nombre < 0:
        raise ErreurUtilisateur(f"séance : {nom} — puissance négative ({nombre} W)")
    return nombre


__all__ = [
    "PUISSANCE_ENDURANCE_PCT_DEFAUT",
    "SEUIL_RECUPERATION_PCT_DEFAUT",
    "TYPES",
    "TYPES_ELASTIQUES",
    "ZONE_FC_BASSE_MAX",
    "ZONES_PUISSANCE_DEFAUT",
    "Etape",
    "Seance",
]
