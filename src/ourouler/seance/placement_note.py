"""La note d'un placement : pénalité des extrémités élastiques et note de terrain pondérée.

Sorti de `seance/placement.py`. Mêmes calculs, même
ordre des sommes et des comparaisons qu'avant le déplacement.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from ourouler.noyau.seance import Etape
from ourouler.seance.placement_resultat import Emplacement

#: Pénalité de séance non tenue, en kilomètres équivalents par unité d'écart
#: relatif hors de la fenêtre d'élasticité, pour une étape élastique
#: **raccourcie**. Un retour au calme tombé à 0 min au lieu des 20 prescrites
#: (écart −100 %, soit 0,95 hors d'une fenêtre qui descend à −5 %) coûte ainsi
#: 19 kilomètres équivalents.
#:
#: Elle doit rester **au-dessus d'un bloc mutilé** — `terrain.PENALITE_BLOC_TRONQUE`
#: vaut 10 — parce que c'est tout son objet : empêcher qu'une séance tronquée
#: gagne. Mesuré le 13/09 sur les quatre candidates des deux sorties réelles :
#: à 20, aucun placement retenu ne tronque la séance sur le 08/02, et celui du
#: 22/04 qui tronque (retour au calme à 20 min au lieu de 40) paie 8,9 et finit
#: dernier. Le même calcul avec la pénalité à 0 fait aussitôt gagner des
#: placements amputés : le 08/02, une candidate bascule sur un placement à
#: 0 min de retour au calme (−98 %) et remonte de la 4ᵉ à la 3ᵉ place ; le
#: 22/04, une autre bascule sur 12 min au lieu de 40 (−69 %) et passe devant.
PENALITE_SEANCE_NON_TENUE = 20.0

#: Ce que coûte une **heure** de retour au calme en plus de la prescription, en
#: kilomètres équivalents. **Q14, close le 13/09/2026 par le mainteneur :** « le
#: retour au calme en fait peut dépasser de plus, c'est souvent ce que je fais
#: car c'est incontrôlable de faire parfait, et c'est du kilomètre facile. Faut
#: réduire le dépassement au max. »
#:
#: Deux conséquences, et c'est tout le dessin de cette constante :
#:
#: 1. **Aucun seuil.** Le coût court dès la première minute en trop, au
#:    prorata. L'ancien `PENALITE_SEANCE_ALLONGEE` ne s'appliquait qu'au-delà
#:    de la fenêtre d'élasticité : en deçà deux placements de terrain égal
#:    étaient à égalité parfaite, et le plus long pouvait gagner. Maintenant,
#:    à terrain égal, la boucle la plus juste gagne toujours.
#: 2. **Faible.** Un dépassement n'est pas une faute, c'est la façon normale
#:    de refermer une boucle dont la longueur n'est jamais exacte. Ce qu'il
#:    coûte, aux trois durées qui parlent :
#:
#:      * 10 min de plus → **0,10** km équivalent
#:      * 20 min de plus → **0,20**
#:      * 40 min de plus → **0,40**
#:
#:    à comparer à un défaut de terrain franc sous un bloc : 1 km de village
#:    traversé pendant un bloc de 20 min de la séance du 08/02 coûte
#:    `POIDS_KM_BATI` × 1200/3120 = **1,15** après pondération par la durée des
#:    blocs. Rentrer 20 min plus tard est donc près de six fois moins cher que
#:    de faire traverser un bourg pendant un 20' — ce qui est l'ordre voulu.
#:    Pour le dire dans l'autre sens : 20 min de retour au calme en plus, c'est
#:    environ 9 km de vrai bitume à allure facile, facturés 0,20.
#:
#: Le **raccourcissement**, lui, garde `PENALITE_SEANCE_NON_TENUE` : amputer
#: une séance reste un vrai défaut, et les deux ne sont pas le même défaut.
PENALITE_CALME_ALLONGE_KM_PAR_H = 0.6


@dataclass(frozen=True)
class _EcartElastique:
    """Une étape élastique telle qu'elle a été placée, pour `_penalite_seance`.

    `ecart` est relatif — durée placée contre durée prescrite, `−1.0` pour un
    retour au calme tombé à zéro. `depassement_s` est le même écart vu en
    secondes, et seulement vers le haut : il vaut 0 dès que l'étape tient sa
    prescription ou reste en deçà. Les deux coexistent parce que les deux
    défauts ne se mesurent pas dans la même unité — amputer une séance se juge
    en part de ce qui manque, dépasser se juge en minutes de plus (Q14).
    """

    ecart: float
    depassement_s: float
    absorbe: bool  # le retour au calme, qui referme la boucle


def _penalite_seance(
    ecarts: Sequence[_EcartElastique],
    elasticite: tuple[float, float],
    elasticite_calme: tuple[float, float] = (-0.05, 1.5),
) -> float:
    """Ce que coûtent les extrémités élastiques, en kilomètres équivalents.

    Deux défauts, deux traitements — c'est toute la décision de Q14 (13/09).

    **Raccourcir ampute la séance.** Une étape élastique tombée sous sa fenêtre
    coûte `PENALITE_SEANCE_NON_TENUE` au prorata de ce qui l'en sépare, et non
    de l'écart entier : une minute de moins que la borne ne doit pas coûter
    d'un coup une note entière. Mesuré sur la vérification réelle du 08/02 : le
    placement qui faisait demi-tour au bloc 2, repartait à l'envers et rentrait
    au km 0 avec 0 min de retour au calme au lieu de 20 notait 1,81 — le
    meilleur de tous. Il paie 19,0 de pénalité et se retrouve dernier.

    **Dépasser referme la boucle.** Le mainteneur : « le retour au calme en
    fait peut dépasser de plus […] c'est du kilomètre facile. Faut réduire le
    dépassement au max. » Le dépassement se paie donc, mais peu, et **dès la
    première minute** : `PENALITE_CALME_ALLONGE_KM_PAR_H` par heure de trop,
    sans fenêtre franchie ni marche. C'est ce qui fait qu'à terrain égal la
    boucle la plus juste gagne — avec un seuil, les deux étaient à égalité
    parfaite et le tri retombait sur l'ordre des candidates.

    La fenêtre haute du retour au calme ne sert donc plus à facturer, seulement
    à dire (voir `_fermer`). La Z2 d'ouverture, elle, garde sa fenêtre : elle
    est le levier de placement, et l'utiliser dans les bornes fixées par le
    mainteneur ne coûte rien — c'est à cela qu'elle sert.
    """
    total = 0.0
    for element in ecarts:
        if not math.isfinite(element.ecart):
            continue
        fenetre = elasticite_calme if element.absorbe else elasticite
        bas = min(fenetre)
        if element.ecart < bas:
            total += PENALITE_SEANCE_NON_TENUE * (bas - element.ecart)
        if element.absorbe and math.isfinite(element.depassement_s):
            total += PENALITE_CALME_ALLONGE_KM_PAR_H * max(0.0, element.depassement_s) / 3600.0
    return total


def _note_ponderee(emplacements: Sequence[Emplacement], etapes: Sequence[Etape]) -> float:
    """Moyenne des notes de couloir, pondérée par la durée de chaque bloc.

        note_totale = Σ (note_i × duree_i) / Σ duree_i

    Décision du superviseur du 13/09 (Q12). Les quatre activations de 40 s à
    375 W de la séance du 22/04 sont des blocs au sens de la séance, et c'est
    juste. Mais chercher un couloir propre pour 40 s n'a pas de sens, et la
    validation rétrospective montre que les blocs courts ne se discriminent
    pas : leur note est du bruit. Plutôt qu'un seuil arbitraire qui les
    exclurait, on pondère — un bloc de 20 min pèse trente fois un bloc de
    40 s, et c'est le rapport de leurs durées, pas une constante de plus.

    Le résultat reste une note en kilomètres équivalents, comparable d'une
    séance à l'autre, ce qu'une somme brute n'était pas : elle grandissait
    avec le nombre de blocs. La pondération seule ne change pas quel décalage
    gagne — les durées des blocs ne dépendent pas du décalage, donc diviser par
    leur somme ne peut pas renverser un classement. La pénalité de séance non
    tenue, elle, en dépend et le renverse : c'est tout son objet.

    Un jeu de blocs sans durée positive n'a pas de pondération possible : la
    moyenne simple prend le relais plutôt que d'effacer les pénalités.
    """
    if not emplacements:
        return 0.0
    poids = [max(0.0, float(etapes[e.etape_idx].duree_s)) for e in emplacements]
    total = sum(poids)
    if total <= 0.0:
        return sum(e.note.note for e in emplacements) / len(emplacements)
    return sum(e.note.note * p for e, p in zip(emplacements, poids, strict=True)) / total
