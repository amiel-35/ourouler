"""Trois propositions qui vont à des endroits différents — et ce qu'on en dit.

Le point dur du lot L5.3, dans les mots du mainteneur : **trois propositions
ne servent à rien si elles se ressemblent**, et les trois premières d'un même
classement se ressemblent presque toujours.

Le risque, nommé d'abord
------------------------

Trois candidates peuvent noter 1,93 / 2,30 / 4,72 et **paraître identiques sur
une carte**. Une note de placement n'est pas une différence perceptible. D'où
la règle qui porte ce module : **deux propositions ne sont contrastées que si
elles diffèrent sur quelque chose que le cycliste voit.**

La seule condition : le recouvrement de routes
----------------------------------------------

**Ce que le cycliste voit, c'est le tracé.** Deux boucles qui partagent moins
de `SEUIL_RECOUVREMENT` de leurs routes vont à des endroits différents, et la
carte le montre en une seconde. C'est le seul verrou.

Décision du mainteneur du 17/09/2026 ([[Q43]]), dans ses mots : *« oui, et en
fait le parcours lui-même est distinctif en soi »*.

Ce qui vient d'être retiré, et pourquoi
---------------------------------------

Jusqu'au 17/09/2026, il fallait **en plus** que chaque proposition soit la
meilleure des trois sur un axe mesuré, d'une marge perceptible. Cette exigence
visait les *descriptions*, pas les tracés, et elle finissait par interdire de
montrer trois routes franchement différentes sous prétexte qu'on ne savait pas
dire en une phrase ce qui les séparait.

**Mesuré deux fois, pas supposé.** Le lot [[Q44]] a produit quatre candidates
dont le recouvrement médian valait **1,4 %** — quasi disjointes, aussi
différentes qu'il est possible de l'être. L'exigence d'axe a absorbé tout le
gain : le produit n'en servait qu'une ou deux. Et la mesure de [[Q43]] disait
la même chose autrement : plus on génère de candidates, moins un trio passe —
à cinq candidates trois axes distinguaient encore, à huit un seul.

**Ce que ça coûte, et qui est assumé** : parfois, trois propositions porteront
presque la même phrase. Le mainteneur juge que la carte parle d'elle-même, ce
qu'elle ne faisait pas au sprint 5 — à l'époque la page du jour n'avait pas
encore la géométrie des trois tracés en JSON.

Les axes restent, comme description
-----------------------------------

On ne normalise pas sept grandeurs hétérogènes — des minutes, des millimètres,
un compte de demi-tours, des kilomètres équivalents — pour en tirer une
« distance » entre propositions. Il faudrait des poids arbitraires, et un
seuil sur cette distance serait infalsifiable. **Chaque axe se compare dans sa
propre unité**, et un écart compte quand il dépasse le pas nommé de cet axe
(les `PAS_*` ci-dessous).

Ce que les axes ne font plus, c'est **décider qui entre dans le trio**. Ils
décident seulement **ce qu'on écrit sous chaque proposition** : une
proposition qui est la meilleure du groupe sur un axe, d'un pas entier, porte
la phrase qui le dit ; les autres n'en portent pas, et c'est honnête. Une
phrase reste une affirmation : on n'en écrit jamais une qui soit fausse.

Et quand rien ne les sépare, on le dit ([[Q45]])
------------------------------------------------

Mots du mainteneur : *« s'il n'y a pas de pluie et peu de vent et que tout est
plat, à un moment rien ne change »*. Ces jours-là, aucun axe ne peut
distinguer quoi que ce soit, et chercher une différence reviendrait à en
fabriquer une. `Selection.motif_equivalence` porte alors la phrase qui le dit
— « ces trois boucles se valent, choisissez où vous voulez aller ».

C'est le pendant exact de `Selection.motif_deux_propositions`, qui explique
depuis le sprint 5 pourquoi il n'y en a que deux. Deux silences à ne pas
laisser : celui qui cache qu'il en manque une, et celui qui cache qu'elles se
valent.

Ce que ce module ne fait pas
----------------------------

Il ne **replace** rien et ne **retrie** rien. La première proposition reste
celle que le tri de `sortie.commande` a retenue : on ne change pas ce que
l'outil recommande, on ajoute ce à quoi le comparer. Les deux autres sont
cherchées parmi toutes les combinaisons possibles, et à validité égale on
prend celles que ce même tri classe le mieux — « les meilleures qui diffèrent
vraiment », et non « trois représentants pris n'importe où ».
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from itertools import combinations

from ourouler.apprentissage.routes import mailles_ponderees
from ourouler.boucle.marqueurs import compter
from ourouler.boucle.meteo_trace import MeteoTrace
from ourouler.seance.placement import MOTIF_SEANCE_AMPUTEE
from ourouler.seance.vent import (
    SEUIL_VENT_SENSIBLE_KMH,
    ChampVent,
    seuil_vent_sensible_ms,
)
from ourouler.sortie.orientation import (
    ORIENTATION_DEPART_DOS,
    ORIENTATION_FACE,
    ORIENTATION_RETOUR_DOS,
    ORIENTATION_TRAVERS,
)

# --- les axes ------------------------------------------------------------------

AXE_VENT = "vent"
AXE_DEMI_TOURS = "demi_tours"
AXE_DUREE = "duree"
AXE_VILLE = "ville"
AXE_TRAFIC = "trafic"
AXE_PLUIE = "pluie"
AXE_TERRAIN = "terrain"

#: Ordre de priorité des axes quand plusieurs attributions sont possibles.
#:
#: Ce n'est pas un classement de qualité, c'est l'ordre dans lequel le
#: mainteneur en a parlé : le **vent** est le seul axe qu'il ait demandé
#: explicitement (« vent dans le dos au départ de la sortie, ou à la fin, ou
#: plutôt vent latéral ? ») ; le **demi-tour** vient ensuite (« autorisé mais
#: pas forcément à mettre en avant… ça peut être un choix visuel ») ; la
#: **durée** est ce qu'il a reproché trois fois au tri (des dépassements de 29
#: à 43 min) ; la **ville** est ce qu'il décrit sous « des croisements, des
#: dos d'âne, des feux » ; le **trafic** est le reproche du contrat §3.1.3 a)
#: — « un bloc peut tomber sur une départementale rapide sans le moindre
#: malus », et §3.1.3 b) le chiffre : 24,1 km de routes à trafic sur 55,2 pour
#: la retenue contre 20,9 pour la quatrième ; la **pluie** et le **terrain**
#: sont déjà dans le tri et n'ont pas besoin d'une phrase pour exister.
ORDRE_AXES = (
    AXE_VENT,
    AXE_DEMI_TOURS,
    AXE_DUREE,
    AXE_VILLE,
    AXE_TRAFIC,
    AXE_PLUIE,
    AXE_TERRAIN,
)

# --- ce qui fait une différence perceptible ------------------------------------
#
# Chaque pas est dans l'unité de son axe. Aucun n'est un pourcentage de note.

#: Écart **à la durée prescrite** en dessous duquel deux propositions tiennent
#: la séance aussi bien l'une que l'autre. **Un arbitrage, pas une mesure** —
#: comme `sortie.commande.NOTE_BLOC_BIEN_PLACE`, et il faut le dire. Dix
#: minutes, parce que c'est l'unité dans laquelle le mainteneur parle de ses
#: sorties (« la retenue dépasse de 29 min ») et que sur une séance de 2 h
#: c'est 8 % du temps, soit l'ordre de grandeur d'un retour au calme entier.
#:
#: **Ce que l'axe compare, et pourquoi ce n'est pas la durée nue.** Le contrat
#: §3.3.2 écrit « durée tenue : écart entre `duree_totale_s` **et la séance** ».
#: La première rédaction comparait les durées brutes, et la plus courte
#: gagnait l'axe : une candidate dont le retour au calme était amputé de 60 %
#: — 2 905 s pour une séance de 7 200 — recevait la phrase « 71 minutes de
#: moins », présentée comme un avantage. Elle voulait dire « vous ne roulez
#: pas votre séance ». Une phrase est une affirmation, et celle-là était
#: fausse de la pire façon : le mensonge était flatteur.
#:
#: L'axe porte donc l'écart **en valeur absolue** — dépasser de 20 min et
#: amputer de 20 min sont deux façons de rater la cible de 20 min — et
#: **une séance amputée ne gagne jamais l'axe**, quelle que soit sa marge :
#: elle ne « tient » pas sa durée, et l'amputation est déjà lourdement payée
#: par `seance.placement.PENALITE_SEANCE_NON_TENUE`. La récompenser ici
#: serait la payer deux fois, en sens inverse.
#:
#: **Ce qui décide qu'une séance est amputée n'est pas un seuil inventé ici**,
#: c'est le verdict du placement lui-même
#: (`seance.placement.MOTIF_SEANCE_AMPUTEE`), rendu contre la fenêtre que le
#: mainteneur a fixée. Aucun seuil sur la durée totale ne séparerait
#: honnêtement une sortie 49 s plus courte que la prescription — un arrondi —
#: d'une sortie dont le retour au calme perd 60 % de sa durée.
PAS_DUREE_S = 600.0

#: Écart de pluie cumulée en dessous duquel deux propositions sont aussi
#: sèches l'une que l'autre, en mm. Repris de la configuration du mainteneur :
#: `ParametresTenue.bornes_pluie_mmh` place à 0,5 mm/h la frontière entre
#: « humide » et « averses ». C'est une transposition d'une intensité vers un
#: cumul, pas une mesure de cumul — mais elle vient de son fichier, pas d'un
#: chiffre inventé ici.
PAS_PLUIE_MM = 0.5

#: Écart de densité de marqueurs en dessous duquel deux propositions traversent
#: autant de village l'une que l'autre, en marqueurs par kilomètre.
#:
#: **Chiffré sur la mesure du 16/09/2026**
#: (`tests/validation/marqueurs_retrospectif.py`, 143 boucles proposées par le
#: moteur autour du départ du mainteneur) : q1 = 1,21, médiane = 1,50,
#: q3 = 2,01, soit un écart interquartile de 0,80. La moitié de cet écart,
#: 0,40, est l'oscillation ordinaire entre deux candidates ; 0,50 est
#: au-dessus. Et dans ses unités à lui : sur une boucle de 60 km, c'est
#: 30 marqueurs d'écart — un arrêt tous les deux kilomètres contre un arrêt
#: tous les kilomètres.
PAS_MARQUEURS_KM = 0.5

#: Écart de **part de la boucle passée sur des routes à trafic** en dessous
#: duquel deux propositions roulent autant l'une que l'autre sur les grands
#: axes. Une part et non des kilomètres : deux boucles n'ont pas la même
#: longueur, et 24 km de départementale sur 55 n'est pas la même sortie que
#: 24 km sur 100.
#:
#: **Chiffré sur la mesure du 16/09/2026** (35 boucles proposées par le moteur
#: autour du départ du mainteneur, à 40, 60 et 80 km) : q1 = 34,8 %,
#: médiane = 41,1 %, q3 = 49,5 %, soit un écart interquartile de 14,7 points
#: et un écart-type de 12,0. La moitié de l'écart interquartile, 7,4 points,
#: est l'oscillation ordinaire entre deux candidates ; 10 points est au-dessus.
#: Et dans ses unités à lui : sur une boucle de 60 km, 6 km de départementale
#: en plus ou en moins.
PAS_TRAFIC_PART = 0.10

#: Écart de note de terrain en dessous duquel deux couloirs se valent, en
#: kilomètres équivalents. Ce n'est pas un nouveau chiffre : c'est
#: `seance.terrain.POIDS_CARREFOUR`, ce que coûte **un feu rouge** sous un
#: bloc. Une différence de note qui ne vaut pas un feu ne vaut pas une phrase.
PAS_TERRAIN_KM_EQ = 1.0

#: Part de routes communes au-delà de laquelle deux propositions se
#: ressemblent sur la carte, quoi que disent leurs notes.
#:
#: **Mesuré le 16/09/2026**, sur les recouvrements deux à deux de boucles de
#: 60 km générées depuis le départ du mainteneur dans 12 directions :
#:
#: | écart d'azimut | recouvrement médian | max |
#: |---|---|---|
#: | 30° | 28,2 % | 52,7 % |
#: | 60° | 14,4 % | 23,3 % |
#: | 90° | 8,0 % | 20,0 % |
#: | 180° | 0,4 % | 1,0 % |
#:
#: Deux enseignements. **Il n'y a pas de plancher** : deux boucles opposées ne
#: partagent que 0,4 % de route, donc le couloir de départ ne fausse rien —
#: tout recouvrement mesuré est de la route vraiment commune. Et **le
#: recouvrement suit la direction** : à 30° d'écart les deux boucles vont au
#: même endroit (médiane 28 %), à 60° et au-delà non (médiane 14 %, max 23 %).
#: 25 % tombe donc juste au-dessus de ce que produisent deux directions
#: franchement différentes, et juste en dessous de ce que produisent deux
#: directions voisines. En absolu, sur une boucle de 60 km : 15 km de route
#: identique.
#:
#: **Depuis [[Q43]], c'est le seul verrou** : plus aucune autre condition ne
#: décide qui entre dans le trio. Ce seuil porte donc seul la promesse « trois
#: propositions qui ne se ressemblent pas », et il faut savoir ce qu'il
#: refuse.
#:
#: **Ce qu'il refuse, mesuré le 17/09/2026** ([[Q44]], contre le vrai BRouter
#: et le vrai Open-Meteo, quatre candidates par préférence de vent) :
#:
#: | préférence | azimuts ouverts | recouvrement médian |
#: |---|---|---|
#: | rentrer avec le vent | 235° | **33,2 %** |
#: | partir avec le vent | 55° | 8,6 % |
#: | de travers | 325° **et** 145° | 1,4 % |
#:
#: « Rentrer avec le vent » passe **au-dessus du seuil**, et cinq de ses six
#: paires le dépassent. Ce n'est pas un défaut du seuil, c'est son travail :
#: cette préférence n'ouvre qu'un azimut, et `boucle.candidates.azimuts`
#: élargit ce secteur de ±20° en ±20° sans jamais en ouvrir un second. Les
#: quatre candidates sont donc quatre variantes à 30° d'écart — très
#: exactement la famille que la mesure du 16/09 chiffre à 28 % de médiane, et
#: dont le mainteneur dit qu'elle « va au même endroit ». Trois d'entre elles
#: sur une carte seraient trois fois la même boucle.
#:
#: **La conséquence est donc voulue** : sur cette préférence, le produit rend
#: souvent moins de trois propositions, et `motif_deux_propositions` le dit.
#: Faire autrement demanderait de changer les *azimuts ouverts* — décision de
#: conception, pas de seuil, laissée au mainteneur en [[Q44]].
SEUIL_RECOUVREMENT = 0.25

# --- orientation au vent -------------------------------------------------------

# Les quatre orientations vivent dans `sortie.orientation`, un module sans
# dépendance que la ligne de commande peut importer sans payer httpx.

#: Part du tracé prise pour « le début » et pour « la fin ».
QUART = 0.25


@dataclass(frozen=True)
class Profil:
    """Ce qu'une proposition donne à voir ou à sentir, axe par axe.

    Toute valeur peut manquer, et `None` veut dire **on ne sait pas**, jamais
    zéro : une boucle relue d'un GPX ne porte aucun tag de nœud, ce qui n'est
    pas la même chose que n'avoir aucun feu (règle absolue 5). Un axe inconnu
    ne distingue rien et ne pénalise rien.
    """

    duree_s: float
    demi_tours: int
    note_terrain: float
    #: Durée roulée **moins** la durée prescrite, en secondes. Positif : on
    #: rentre plus tard, ce qui est normal (le retour au calme absorbe).
    #: Négatif : la séance est **amputée**, ce qui ne l'est pas. `None` quand
    #: la durée de la séance n'a pas été fournie — l'axe est alors inconnu, il
    #: ne distingue rien et ne pénalise personne.
    depassement_s: float | None = None
    #: Vrai quand le placement a dit que la séance **n'est pas roulée en
    #: entier** — son verdict, pas une comparaison de durées faite ici.
    seance_amputee: bool = False
    pluie_mm: float | None = None
    densite_marqueurs_km: float | None = None
    #: Feux et stops du parcours, en nombre absolu. Affiché tel quel : « 28
    #: feux, 20 stops ». Une densité au kilomètre invitait à multiplier —
    #: « 1,7 au km, donc 170 sur 100 km » — sur un composite dont 65 % étaient
    #: des passages piétons (mesuré le 16/09/2026).
    feux: int | None = None
    stops: int | None = None
    #: Part de la boucle en `highway=primary` seul (Q21 c) — plus le
    #: composite `boucle.couts.HIGHWAY_TRAFIC` (primary + secondary + trunk)
    #: d'avant ce correctif. Mesuré sur les vraies sorties du mainteneur :
    #: `trunk` vaut zéro sur 381 km dans huit directions (BRouter n'y envoie
    #: jamais un vélo), et `secondary` — une départementale ordinaire, pas
    #: une quatre-voies — portait deux tiers du chiffre composite « alors
    #: qu'il n'en a cure » (ses mots). Le nom du champ ne change pas : ce que
    #: `primary` mesure reste une route à trafic, la seule que le composite
    #: comptait à raison.
    part_trafic: float | None = None
    orientation: str | None = None

    @property
    def ecart_duree_s(self) -> float | None:
        """L'écart à la durée prescrite, en valeur absolue — la grandeur de l'axe."""
        return None if self.depassement_s is None else abs(self.depassement_s)

    @property
    def seance_tenue(self) -> bool:
        """Vrai si la séance est roulée en entier — le verdict du placement.

        On peut rentrer plus tard sans rien perdre (le retour au calme est là
        pour ça) ; on ne peut pas rouler moins que la séance.
        """
        return self.depassement_s is not None and not self.seance_amputee

    def valeur(self, axe: str):
        """La valeur de cet axe, ou `None` si elle est inconnue."""
        return {
            AXE_DUREE: self.ecart_duree_s,
            AXE_DEMI_TOURS: float(self.demi_tours),
            AXE_TERRAIN: self.note_terrain,
            AXE_PLUIE: self.pluie_mm,
            # L'axe compare des **arrêts au kilomètre** — comparable entre
            # boucles de longueurs différentes — là où l'affichage montre des
            # nombres absolus. Deux besoins, deux formes de la même mesure.
            AXE_VILLE: self.densite_marqueurs_km,
            AXE_TRAFIC: self.part_trafic,
            AXE_VENT: self.orientation,
        }.get(axe)


def profil(
    proposition, meteo: MeteoTrace | None = None, *, duree_seance_s: float | None = None
) -> Profil:
    """Le profil d'une `sortie.commande.Proposition`.

    `meteo` est celle de la proposition ; elle n'est prise en argument à part
    que pour que les tests puissent en fournir une sans construire une
    `Proposition` entière.

    `duree_seance_s` est la durée **prescrite** de la séance, celle dont on
    mesure l'écart. Sans elle, l'axe de la durée est inconnu plutôt que faux :
    on ne compare pas des durées nues, sans quoi la candidate qui ampute la
    séance gagne l'axe (voir `PAS_DUREE_S`).
    """
    meteo = meteo if meteo is not None else getattr(proposition, "meteo", None)
    marqueurs = compter(proposition.trace)
    duree_s = float(proposition.placement.duree_totale_s)
    return Profil(
        duree_s=duree_s,
        depassement_s=(
            None
            if duree_seance_s is None or not math.isfinite(duree_seance_s)
            else duree_s - float(duree_seance_s)
        ),
        seance_amputee=_seance_amputee(proposition.placement),
        demi_tours=int(proposition.demi_tours),
        note_terrain=float(proposition.placement.note_terrain),
        pluie_mm=(meteo.pluie_cumulee_mm if meteo is not None else None),
        densite_marqueurs_km=marqueurs.arrets_par_km,
        feux=(None if not marqueurs.connue else marqueurs.par_nature.get("traffic_signals", 0)),
        stops=(None if not marqueurs.connue else marqueurs.par_nature.get("stop", 0)),
        part_trafic=_part_trafic(proposition),
        orientation=orientation_au_vent(meteo),
    )


def _seance_amputee(placement) -> bool:
    """Le placement a-t-il dit que la séance n'est pas roulée en entier ?"""
    return any(
        MOTIF_SEANCE_AMPUTEE in avertissement
        for avertissement in getattr(placement, "avertissements", ())
    )


def _part_trafic(proposition) -> float | None:
    """Part de la boucle en `highway=primary`, ou `None` si les tags manquent (Q21 c).

    Avant ce correctif, la mesure était `couts.km_trafic` — le composite
    `boucle.couts.HIGHWAY_TRAFIC` (primary + secondary + trunk) que le score
    utilise pour router. Décision du mainteneur : la catégorie composite
    disparaît de l'affichage, `primary` seul reste. `couts.km_par_highway`
    porte déjà le détail par classe, il n'y avait rien à mesurer de plus.

    `trace.meta["couts_partiels"]` est vrai quand le tracé n'a pas de
    `segments` (un GPX importé) : les kilomètres par type de route valent
    alors 0 **faute de les connaître**, et les rendre tels quels ferait passer
    une ignorance pour une boucle sans la moindre route nationale.
    """
    if proposition.trace.meta.get("couts_partiels"):
        return None
    km = proposition.trace.distance_m / 1000.0
    if not math.isfinite(km) or km <= 0:
        return None
    return proposition.couts.km_par_highway.get("primary", 0.0) / km


def orientation_au_vent(meteo: MeteoTrace | None) -> str | None:
    """Comment le vent tombe sur le tracé : dos au retour, dos au départ, travers.

    On compare la composante de face **moyenne du premier quart** du tracé à
    celle du **dernier quart**, en m/s à hauteur de cycliste, contre
    `seance.vent.seuil_vent_sensible_ms()` — le même seuil que celui qui
    décide de dessiner une flèche sur la carte. Rend `None` quand le vent est
    inconnu ou trop faible pour qu'une orientation veuille dire quelque chose.

    **« Pas de vent » n'est pas « vent de travers ».** Les deux rendent une
    composante de face nulle, et la première rédaction les confondait : sur
    une journée à 5 km/h, les cinq candidates étaient annoncées « vent de
    travers », ce qui promet une sensation qui n'existe pas. On regarde donc
    d'abord la **vitesse** du vent le long du tracé : sous le seuil, il n'y a
    pas d'orientation à nommer, et l'axe du vent ne distingue plus rien — ce
    qui est exactement vrai.

    **Approximation assumée** : les quarts sont ceux du *tracé*, pas du
    parcours réellement roulé. Ils diffèrent après un demi-tour — mais un
    demi-tour se roule dans les deux sens sur la même route, et son exposition
    au vent s'annule pour l'essentiel. La reconstruction exacte demanderait de
    réinterroger le champ de vent le long de `trace_parcourue`, ce qui n'est
    pas dans ce lot.
    """
    if meteo is None or not meteo.echantillons:
        return None
    champ = ChampVent(meteo.echantillons)
    if not champ.positions:
        return None
    vitesses = [e.vent_kmh for e in meteo.echantillons if e.vent_kmh is not None]
    if not vitesses or sum(vitesses) / len(vitesses) < SEUIL_VENT_SENSIBLE_KMH:
        return None
    total = max(e.dist_m for e in meteo.echantillons)
    if not math.isfinite(total) or total <= 0:
        return None
    debut = _face_moyenne(champ, meteo, lambda d: d <= QUART * total)
    fin = _face_moyenne(champ, meteo, lambda d: d >= (1 - QUART) * total)
    if debut is None or fin is None:
        return None
    seuil = seuil_vent_sensible_ms()
    if fin <= -seuil:
        return ORIENTATION_RETOUR_DOS
    if debut <= -seuil:
        return ORIENTATION_DEPART_DOS
    if debut >= seuil and fin >= seuil:
        return ORIENTATION_FACE
    return ORIENTATION_TRAVERS


def _face_moyenne(champ: ChampVent, meteo: MeteoTrace, garde) -> float | None:
    valeurs = [
        champ.vent_face_ms(e.dist_m, e.cap_deg, 1)
        for e in meteo.echantillons
        if garde(e.dist_m) and e.vent_kmh is not None and e.vent_depuis_deg is not None
    ]
    return sum(valeurs) / len(valeurs) if valeurs else None


# --- la sélection ---------------------------------------------------------------


@dataclass
class Retenue:
    """Une proposition retenue, avec ce qui la distingue des autres."""

    proposition: object
    profil: Profil
    axe_distinctif: str
    distinction: str


@dataclass
class Selection:
    """Les propositions retenues, et ce qu'il y a d'honnête à dire dessus."""

    retenues: list[Retenue] = field(default_factory=list)
    #: Pourquoi il y en a moins de `combien`. `None` quand le compte y est.
    motif_deux_propositions: str | None = None
    #: La phrase de [[Q45]] : **aucune retenue ne se détache des autres**, et
    #: le dire vaut mieux que fabriquer une différence. `None` dès qu'au moins
    #: une porte une phrase de distinction — il y a alors quelque chose à dire,
    #: et c'est elle qui le dit.
    motif_equivalence: str | None = None
    #: Recouvrements deux à deux des retenues, pour l'affichage et le JSON.
    recouvrements: dict[tuple[int, int], float] = field(default_factory=dict)


def choisir(
    propositions: list,
    *,
    combien: int = 3,
    seuil_recouvrement: float = SEUIL_RECOUVREMENT,
    duree_seance_s: float | None = None,
) -> Selection:
    """Les `combien` propositions les mieux classées **qui vont ailleurs**.

    « Qui vont ailleurs » est tout le critère : leurs recouvrements deux à deux
    restent sous `seuil_recouvrement`. Depuis [[Q43]], rien d'autre n'est
    exigé — le tracé se distingue par lui-même, et la carte le montre.

    La première du tri — celle que l'outil recommande — fait toujours partie
    du groupe : on ne remet pas en cause ce qu'il recommande, on ajoute ce à
    quoi le comparer. Les autres sont cherchées **par recherche exhaustive**
    sur les combinaisons, et non en descendant le classement une à une : un
    parcours glouton s'engage sur une paire qui interdit tout troisième, et
    conclut « il n'y a pas de trio » alors qu'il n'avait pas regardé. Avec une
    dizaine de candidates et trois places, c'est une centaine de combinaisons
    dont les recouvrements sont déjà en cache : ça ne coûte rien.

    À égalité de validité, on préfère le groupe dont les candidates sont les
    mieux classées (rangs les plus bas) : « les meilleures qui diffèrent »,
    jamais « trois prises n'importe où ». **On ne départage pas sur le nombre
    de phrases qu'un groupe permettrait d'écrire** : ce serait réintroduire par
    la bande l'exigence que [[Q43]] a retirée, et préférer un groupe moins bien
    classé parce qu'il se raconte mieux.

    Si aucun groupe de `combien` ne tient, on redescend à `combien - 1`, et
    ainsi de suite — et `motif_deux_propositions` dit pourquoi.

    `duree_seance_s` est la durée **prescrite** de la séance : sans elle,
    l'axe de la durée ne distingue rien, parce qu'on ne compare pas des durées
    nues (voir `PAS_DUREE_S`).
    """
    if not propositions:
        return Selection(motif_deux_propositions="aucune candidate à proposer")
    profils = {id(p): profil(p, duree_seance_s=duree_seance_s) for p in propositions}
    mesure = _Recouvrements()

    groupe = _meilleur_groupe(propositions, mesure, combien, seuil_recouvrement)
    attribution = _attribuer([profils[id(p)] for p in groupe])

    retenues = [
        Retenue(
            proposition=p,
            profil=profils[id(p)],
            axe_distinctif=axe,
            distinction=phrase(axe, profils[id(p)], [profils[id(q)] for q in groupe if q is not p]),
        )
        for p, axe in zip(groupe, attribution, strict=True)
    ]
    selection = Selection(retenues=retenues)
    if len(retenues) < combien:
        selection.motif_deux_propositions = _motif(len(retenues), combien, len(propositions))
    selection.motif_equivalence = _motif_equivalence(retenues)
    for i in range(len(groupe)):
        for j in range(i + 1, len(groupe)):
            selection.recouvrements[(i, j)] = mesure.entre(groupe[i].trace, groupe[j].trace)
    return selection


def _meilleur_groupe(
    propositions: list,
    mesure: _Recouvrements,
    combien: int,
    seuil_recouvrement: float,
) -> list:
    """Le meilleur groupe de `combien` propositions assez disjointes, ou moins.

    Le seul refus possible est le recouvrement : il n'y a donc plus rien à
    collecter pour expliquer un groupe écarté, la raison est toujours la même.
    """
    tete, reste = propositions[0], propositions[1:]
    for taille in range(min(combien, len(propositions)), 1, -1):
        for indices in combinations(range(len(reste)), taille - 1):
            groupe = [tete, *(reste[i] for i in indices)]
            if _assez_disjointes(groupe, mesure, seuil_recouvrement):
                # `combinations` énumère les indices dans l'ordre croissant :
                # la première trouvée est déjà la mieux classée.
                return groupe
    return [tete]


def _assez_disjointes(groupe: list, mesure: _Recouvrements, seuil: float) -> bool:
    return all(
        mesure.entre(groupe[i].trace, groupe[j].trace) <= seuil
        for i in range(len(groupe))
        for j in range(i + 1, len(groupe))
    )


class _Recouvrements:
    """`recouvrement_max` avec les mailles de chaque tracé calculées une fois.

    Sans ce cache, choisir trois propositions parmi cinq redécoupait le même
    tracé de 60 km en mailles une dizaine de fois. Le résultat est
    identique à `apprentissage.routes.recouvrement_max`, dont c'est le calcul,
    recopié ici pour pouvoir réutiliser les découpages.
    """

    def __init__(self) -> None:
        self._mailles: dict[int, dict[tuple[int, int], float]] = {}
        self._totaux: dict[int, float] = {}

    def entre(self, a, b) -> float:
        return max(self._sens(a, b), self._sens(b, a))

    def _sens(self, a, b) -> float:
        metres_a, total = self._de(a)
        if total <= 0:
            return 0.0
        mailles_b = self._de(b)[0]
        return sum(m for cle, m in metres_a.items() if cle in mailles_b) / total

    def _de(self, trace) -> tuple[dict[tuple[int, int], float], float]:
        cle = id(trace)
        if cle not in self._mailles:
            metres = mailles_ponderees(trace)
            self._mailles[cle] = metres
            self._totaux[cle] = sum(metres.values())
        return self._mailles[cle], self._totaux[cle]


#: Les axes tels qu'on les nomme dans un message, **avec leur article** et
#: dans l'ordre de `ORDRE_AXES` : ils s'enchaînent dans des phrases, pas dans
#: une liste de colonnes.
_NOMS_AXES = {
    AXE_VENT: "l'orientation au vent",
    AXE_DEMI_TOURS: "les demi-tours",
    AXE_DUREE: "la durée",
    AXE_VILLE: "la ville",
    AXE_TRAFIC: "les nationales",
    AXE_PLUIE: "la pluie",
    AXE_TERRAIN: "le terrain sous les blocs",
}

#: Les axes dont le nom ci-dessus est un **pluriel**. Le verbe s'accorde avec
#: le nom, pas avec le nombre d'axes cités : « les nationales valaient » et non
#: « les nationales valait », même quand cet axe est le seul de la liste.
_NOMS_AXES_PLURIELS = frozenset({AXE_DEMI_TOURS, AXE_TRAFIC})


def _accorder(axes: list[str], singulier: str, pluriel: str) -> str:
    """Le verbe qui va avec « {les noms de ces axes} … ».

    Plusieurs axes énumérés font un sujet pluriel. Un seul s'accorde avec
    lui-même.
    """
    if len(axes) != 1:
        return pluriel
    return pluriel if axes[0] in _NOMS_AXES_PLURIELS else singulier


def axes_muets(profils: list[Profil]) -> tuple[list[str], list[str]]:
    """(axes qui ne distinguent rien, axes qui distinguent) sur ce lot de profils.

    Un axe est **muet** quand tous les profils y valent la même chose à moins
    d'un pas près, ou quand la mesure y est inconnue partout.

    C'est ce qui donne sa substance à la phrase de [[Q45]] : « ces trois
    boucles se valent » est vrai mais n'apprend rien, alors que « la pluie, le
    terrain, les demi-tours et le vent valaient la même chose sur les trois »
    dit au cycliste **ce qui manquait ce jour-là**, et donc qu'on ne lui cache
    rien (règle absolue 5 : ne rien affirmer sans mesure).
    """
    muets, vivants = [], []
    for axe in ORDRE_AXES:
        (vivants if _distingue(axe, profils) else muets).append(axe)
    return muets, vivants


def _distingue(axe: str, profils: list[Profil]) -> bool:
    """Cet axe sépare-t-il au moins deux candidates d'une marge perceptible ?"""
    valeurs = [p.valeur(axe) for p in profils]
    connues = [v for v in valeurs if v is not None]
    if len(connues) < 2:
        return False
    if axe == AXE_VENT:
        return len(set(connues)) > 1
    return max(connues) - min(connues) >= _PAS[axe]


def _motif(retenues: int, voulu: int, candidates: int) -> str:
    """Pourquoi il y en a moins de `voulu` — et depuis [[Q43]] il n'y a qu'une raison.

    Le recouvrement est le seul verrou : si un groupe a été écarté, c'est que
    deux de ses boucles allaient au même endroit. Plus besoin de dire « soit…
    soit… » : il n'y a plus de second motif à distinguer du premier.
    """
    if candidates <= retenues:
        return (
            f"{candidates} candidate(s) seulement portaient la séance : "
            f"il n'y a pas de quoi en contraster {voulu}"
        )
    return (
        f"{retenues} proposition(s) au lieu de {voulu}. Toutes les combinaisons des "
        f"{candidates} candidates ont été essayées : dans chacune, deux boucles empruntaient "
        f"plus de {SEUIL_RECOUVREMENT:.0%} des mêmes routes et seraient allées au même "
        "endroit. Mieux vaut en proposer moins et le dire que trois qui se ressemblent."
    )


#: « deux », « trois » — les comptes qu'une phrase de propositions peut porter.
_EN_LETTRES = {2: "deux", 3: "trois"}


def _motif_equivalence(retenues: list[Retenue]) -> str | None:
    """La phrase de [[Q45]] : ces boucles se valent, et voici ce qui le dit.

    Elle ne sort que si **aucune** retenue ne porte de phrase de distinction.
    Dès qu'une seule se détache, quelque chose distingue le lot, et c'est sa
    phrase à elle qui le dit : annoncer en même temps « elles se valent »
    serait faux.

    Avec une seule proposition, il n'y a rien à comparer et donc rien à dire :
    `motif_deux_propositions` couvre déjà ce cas-là.
    """
    if len(retenues) < 2 or any(r.axe_distinctif for r in retenues):
        return None
    combien = _EN_LETTRES.get(len(retenues), str(len(retenues)))
    return (
        f"Ces {combien} boucles se valent : {_ce_qui_les_egale([r.profil for r in retenues])} "
        "Choisissez où vous voulez aller."
    )


def _ce_qui_les_egale(profils: list[Profil]) -> str:
    """Ce qui, mesuré, ne sépare pas ces propositions — jamais une affirmation nue.

    Deux cas, et la nuance entre les deux est vraie. Ou bien les axes sont
    **muets** : les mesures valent la même chose partout. Ou bien certains
    varient sans que personne y prenne l'avantage d'un pas entier sur **tous**
    les autres — ce n'est pas « identique », c'est « personne ne s'en
    détache », et on l'écrit comme ça.

    La nuance n'est pas décorative. Sur une vraie sortie du 19/09/2026, les
    parts de nationales valaient 17 %, 5 % et 8 % : l'écart total dépasse le
    pas, mais les deux meilleures sont à trois points l'une de l'autre, et
    aucune ne peut se dire celle qui évite les nationales. Écrire « elles y
    roulent autant » serait faux ; écrire « l'une évite les nationales »
    aussi.
    """
    muets, vivants = axes_muets(profils)
    combien = _EN_LETTRES.get(len(profils), str(len(profils)))
    identiques = (
        f"{_et(_NOMS_AXES[axe] for axe in muets)} "
        f"{_accorder(muets, 'valait', 'valaient')} la même chose sur les {combien}"
    )
    if not vivants:
        return f"{identiques}."
    debut = (
        f"{_et(_NOMS_AXES[axe] for axe in vivants)} "
        f"{_accorder(vivants, 'varie', 'varient')} d'une boucle à l'autre, mais "
        # « aucune » désigne les boucles, pas les axes : rien à accorder ici.
        "aucune ne s'en détache d'une marge qui se dise"
    )
    return f"{debut}." if not muets else f"{debut}, et {identiques}."


def _et(noms) -> str:
    """« a, b et c » — la conjonction française, pas une liste à virgules."""
    noms = list(noms)
    if len(noms) <= 1:
        return noms[0] if noms else ""
    return f"{', '.join(noms[:-1])} et {noms[-1]}"


# --- attribution d'un axe à chaque proposition ----------------------------------


def _attribuer(profils: list[Profil]) -> list[str]:
    """L'axe sur lequel chaque profil se détache, ou `""` s'il ne se détache sur aucun.

    **Une attribution, plus un verdict.** Avant [[Q43]], cette fonction rendait
    `None` dès qu'un profil ne gagnait aucun axe, et le groupe entier était
    jeté. Elle ne juge plus : le recouvrement a tranché avant elle, et elle
    répond seulement à « qu'y a-t-il de vrai à écrire sous chacune ». Un `""`
    n'est plus un échec, c'est une proposition dont le tracé parle seul.

    Avec une seule proposition, il n'y a rien à distinguer, et `""` est encore
    ce qu'il y a de juste — elle est seule, pas contrastée.

    Le choix entre plusieurs axes gagnés suit `ORDRE_AXES`, du plus au moins
    parlant pour le mainteneur.

    **Les axes se répartissent d'eux-mêmes, sans arbitrage.** Deux profils ne
    peuvent pas gagner le même axe : sur un axe chiffré il faut être meilleur
    que *tous* les autres d'un pas entier, ce que deux profils ne peuvent pas
    être l'un envers l'autre ; et sur le vent il faut être le **seul** de son
    orientation. Chacun prend donc son meilleur axe sans se soucier des
    autres, et les axes attribués sont distincts par construction.

    **Le vent compte pour autant d'axes qu'il a d'orientations**, sous les
    clés `vent:retour-dos`, `vent:depart-dos`, `vent:travers`, `vent:face`.
    Sans cela, l'exemple que le contrat donne lui-même en §3.1 serait interdit
    — « vous rentrez avec le vent dans le dos », « vent dans le dos au
    départ », « vent de travers » sont trois propositions qui ne diffèrent
    *que* par le vent, et c'est très exactement ce que le mainteneur a
    demandé.
    """
    if len(profils) <= 1:
        return [""] * len(profils)
    return [_meilleur_axe(p, [q for q in profils if q is not p]) for p in profils]


def _meilleur_axe(sujet: Profil, autres: list[Profil]) -> str:
    """Le premier axe de `ORDRE_AXES` que `sujet` gagne, ou `""`."""
    gagnes = _axes_gagnes(sujet, autres)
    return min(gagnes, key=_priorite) if gagnes else ""


def axe_de_base(axe: str) -> str:
    """L'axe sans son orientation : `vent:travers` → `vent`, le reste inchangé."""
    return axe.split(":", 1)[0]


def _priorite(axe: str) -> int:
    return ORDRE_AXES.index(axe_de_base(axe))


def _axes_gagnes(sujet: Profil, autres: list[Profil]) -> list[str]:
    """Les axes sur lesquels `sujet` est meilleur que **tous** les `autres`, d'un pas entier.

    L'axe du vent est rendu sous la forme `vent:<orientation>` : voir
    `_attribuer` pour pourquoi une orientation est un axe à elle seule.
    """
    gagnes = []
    for axe in ORDRE_AXES:
        if not _gagne(axe, sujet, autres):
            continue
        gagnes.append(f"{AXE_VENT}:{sujet.orientation}" if axe == AXE_VENT else axe)
    return gagnes


def _gagne(axe: str, sujet: Profil, autres: list[Profil]) -> bool:
    valeur = sujet.valeur(axe)
    if valeur is None:
        return False
    if axe == AXE_VENT:  # noqa: SIM102 - lisibilité : chaque axe a sa clause
        # Le vent n'a pas de « meilleur » : le mainteneur a dit qu'il voulait
        # arbitrer lui-même entre rentrer avec, partir avec, ou du travers.
        # « Gagner » l'axe, c'est donc être la **seule** de son orientation —
        # c'est bien ce qui la distingue des deux autres, et c'est la marge
        # que le contrat demande pour un axe catégoriel.
        return all(autre.orientation != valeur for autre in autres)
    if axe == AXE_DUREE and not sujet.seance_tenue:
        # Une séance amputée ne « tient » pas sa durée : elle ne peut pas
        # gagner l'axe, même en étant la moins amputée du lot. L'amputation
        # est déjà payée par `PENALITE_SEANCE_NON_TENUE` ; la récompenser ici
        # serait la payer deux fois, en sens inverse.
        return False
    pas = _PAS[axe]
    for autre in autres:
        sienne = autre.valeur(axe)
        if sienne is None:
            return False  # on ne bat pas une inconnue : l'ignorance ne fait gagner personne
        if valeur > sienne - pas:
            return False
    return True


_PAS = {
    AXE_DUREE: PAS_DUREE_S,
    AXE_DEMI_TOURS: 1.0,
    AXE_PLUIE: PAS_PLUIE_MM,
    AXE_VILLE: PAS_MARQUEURS_KM,
    AXE_TRAFIC: PAS_TRAFIC_PART,
    AXE_TERRAIN: PAS_TERRAIN_KM_EQ,
}


# --- les phrases ----------------------------------------------------------------


def phrase(axe: str | None, sujet: Profil, autres: list[Profil]) -> str:
    """La phrase qui distingue `sujet` des `autres`, en langage de cycliste.

    Jamais en langage de note : « vous rentrez avec le vent dans le dos »,
    « aucun demi-tour », « la plus sèche », « 20 minutes de moins », « elle
    évite les villages ». Si la phrase n'est pas écrivable, la proposition
    n'existe pas — `choisir` ne la retient donc pas, et cette fonction ne rend
    la chaîne vide que pour une proposition seule.
    """
    if not axe or not autres:
        return ""
    if axe_de_base(axe) == AXE_VENT:
        return _PHRASES_VENT.get(sujet.orientation or "", "")
    if axe == AXE_DEMI_TOURS:
        if sujet.demi_tours == 0:
            return "aucun demi-tour"
        if sujet.demi_tours == 1:
            return "un seul demi-tour"
        return f"{sujet.demi_tours} demi-tours seulement"
    if axe == AXE_DUREE:
        # Deux branches, et toutes deux vraies par construction. Le sujet
        # tient sa séance (`_gagne` l'a vérifié) et il est le plus proche de
        # la durée prescrite. Ou bien il est aussi le plus court du groupe, et
        # « X minutes de moins » est un fait doublé d'un avantage ; ou bien
        # une autre est plus courte que lui — elle ampute donc la séance —, et
        # la seule chose vraie à dire est qu'il vise le mieux.
        plus_courte = min(a.duree_s for a in autres)
        if sujet.duree_s <= plus_courte:
            return f"{(plus_courte - sujet.duree_s) / 60:.0f} minutes de moins"
        return "la plus proche de la durée prévue"
    if axe == AXE_PLUIE:
        return "au sec" if (sujet.pluie_mm or 0.0) <= 0.0 else "la plus sèche"
    if axe == AXE_VILLE:
        return "elle évite les villages"
    if axe == AXE_TRAFIC:
        return "elle évite les nationales"
    if axe == AXE_TERRAIN:
        return "c'est là que les blocs tombent le mieux"
    return ""


_PHRASES_VENT = {
    ORIENTATION_RETOUR_DOS: "vous rentrez avec le vent dans le dos",
    ORIENTATION_DEPART_DOS: "vent dans le dos au départ, vous rentrez dans le dur",
    ORIENTATION_TRAVERS: "vent de travers, ni répit ni mur",
    ORIENTATION_FACE: "du vent de face au départ comme au retour",
}
