"""Modèle physique : quelle puissance pour quelle vitesse, et l'inverse.

Le bilan est celui de Martin & al. (1998), réduit à ce qui compte hors
montagne et **sans folie** (décision du mainteneur, 13/09) : roulement,
gravité, aérodynamique, rendement de transmission. Ni inertie, ni frottement
des roulements de roue, ni résistance du vent de travers.

    P = (1/η) · [ (Crr·m·g·cos θ + m·g·sin θ)·v + ½·ρ·CdA·v_air·|v_air|·v ]

avec θ = atan(pente) et `v_air = v + v_vent_face` (vent de face compté
positif). Le contrat de sprint §3 écrit ce dernier terme `(v + v_vent_face)²` ;
c'est la même chose tant que l'air vient de face, mais un vent arrière plus
rapide que le cycliste (`v_air < 0`) rendait alors une traînée **positive**,
c'est-à-dire un vent de dos qui freine. `v_air·|v_air|` garde le signe : la
poussée est une puissance négative. Écart au contrat assumé et signalé.

Le vent que ce bilan attend est celui **à hauteur de cycliste**, pas celui
des bulletins : `vent_au_cycliste` fait la conversion, une fois pour toutes,
pour l'archive comme pour la prévision.

Deux grandeurs sortent de ce module :

- `puissance_requise(v)` — directe, exacte ;
- `vitesse_regime(P)` — son inverse, par bissection sur [0, 30] m/s.

Et une simulation de parcours, `simuler`, qui donne un **temps en mouvement** :
les arrêts (feux, stops, ravitaillement, photo) ne sont pas modélisés. Sur
route ouverte, c'est la principale raison pour laquelle un temps simulé est
plus court qu'un temps réel.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from ourouler.activites.modele import moyenne_glissante
from ourouler.boucle.trace import PointTrace, Trace, cap_deg, distance_m
from ourouler.erreurs import ErreurUtilisateur

#: Accélération de la pesanteur (valeur normale, CGPM 1901).
G = 9.80665

#: Constante spécifique de l'air sec, en J/(kg·K).
R_AIR = 287.058

#: Masse volumique de l'air par défaut : 15 °C à 1013,25 hPa, au niveau de la mer.
RHO_DEFAUT = 1.226

#: Rendement de transmission par défaut (chaîne propre, valeur de Martin & al.).
RENDEMENT_DEFAUT = 0.976

#: Borne haute de la bissection, en m/s (108 km/h : au-delà, ce n'est plus du vélo).
V_MAX_BISSECTION_MS = 30.0

#: Vitesse plafond en descente, en km/h : le cycliste freine, le modèle ne le sait pas.
V_MAX_DESCENTE_KMH = 60.0

#: Pas de la simulation, en mètres.
PAS_M = 100.0

#: Nombre de pas de la moyenne glissante qui lisse l'altitude (7 pas = 700 m).
#: L'altimètre barométrique d'un compteur bruite de quelques dizaines de
#: centimètres ; sur 100 m, cela vaut des pentes fantômes de plusieurs pour
#: cent. On lisse avant de dériver.
FENETRE_ALTITUDE = 7

#: Sous cette vitesse, le modèle n'a plus de sens (le cycliste met pied à
#: terre). Les pas concernés sont comptés dans `Simulation.pas_bloques` et
#: leur temps est calculé à cette vitesse plancher : c'est un plancher
#: affiché, pas une mesure.
V_MIN_MS = 0.5

#: Facteur qui ramène un vent **météo** (mesuré ou prévu à 10 m du sol) au vent
#: que le cycliste subit réellement, à hauteur de buste.
#:
#: Le profil de vent en couche limite est logarithmique :
#: `v(z) = v* / k · ln(z / z₀)`, donc `v(z₁)/v(z₂) = ln(z₁/z₀) / ln(z₂/z₀)`.
#: Avec `z = 1,5 m` (buste d'un cycliste sur la route), `z₀ = 0,1 m`
#: (longueur de rugosité d'un bocage : haies, arbres, cultures hautes) et la
#: hauteur de référence de 10 m des modèles météo :
#:
#:     ln(1,5 / 0,1) / ln(10 / 0,1) = ln(15) / ln(100) ≈ 0,588
#:
#: soit **0,6** en chiffre rond. Ce n'est pas un réglage libre : c'est la
#: conversion d'une grandeur météo en la grandeur physique dont le modèle a
#: besoin. Elle s'applique des deux côtés — archive (calibration) et
#: prévision (simulation) — sans quoi le modèle serait calibré sur un vent et
#: utilisé sur un autre.
FACTEUR_VENT_HAUTEUR = 0.6

#: Tolérance de la bissection, en m/s. 10⁻¹⁰ m/s rend `puissance_requise(
#: vitesse_regime(P))` égale à P à bien mieux que 0,1 W sur toute la plage utile.
TOLERANCE_MS = 1e-10

#: Garde-fou d'itérations de la bissection. 30/2⁵⁰ ≈ 3·10⁻¹⁴ : la tolérance
#: est atteinte bien avant, cette borne n'existe que pour ne jamais boucler.
MAX_ITERATIONS = 200


@dataclass(frozen=True)
class Parametres:
    """Ce qu'il faut savoir du couple cycliste + vélo pour prédire une vitesse.

    `masse_totale_kg` est la masse **en mouvement** : cycliste habillé, vélo,
    bidons. `cda_m2` (m²) et `crr` (sans dimension) sortent de la calibration.
    """

    masse_totale_kg: float
    cda_m2: float
    crr: float
    rendement: float = RENDEMENT_DEFAUT
    rho: float = RHO_DEFAUT


@dataclass
class Simulation:
    """Le résultat de `simuler` : un temps **en mouvement**, pas un temps de sortie.

    `par_segment` donne, pour chaque pas : (distance cumulée en fin de pas,
    pente, vitesse en km/h, temps du pas en secondes).
    """

    temps_s: float
    distance_m: float
    vitesse_moy_kmh: float
    par_segment: list[tuple[float, float, float, float]] = field(default_factory=list)
    pas_plafonnes: int = 0
    """Pas où la vitesse a été ramenée à `V_MAX_DESCENTE_KMH` : le modèle
    descendait plus vite que ce qu'un humain accepte."""
    pas_bloques: int = 0
    """Pas où la vitesse calculée était sous `V_MIN_MS` (puissance nulle ou
    quasi nulle) : le temps de ces pas est un plancher, pas une mesure."""


def vent_au_cycliste(vent_10m: float) -> float:
    """Le vent vu par le cycliste, à partir d'un vent météo donné à 10 m.

    Une seule multiplication, et **une seule constante** :
    `FACTEUR_VENT_HAUTEUR`. La calibration passe par cette fonction ;
    `seance.vent.ChampVent` applique la même constante lui-même, parce qu'il
    expose un `facteur_hauteur` injectable que ses tests font varier. Les deux
    ne peuvent donc pas diverger numériquement, mais ce ne sont pas les mêmes
    lignes — la version antérieure de cette docstring disait « un seul
    endroit », et c'est devenu faux avec le lot L5.1.

    Le signe est conservé : un vent de dos (compté négatif en composante de
    face) reste un vent de dos. Une valeur non finie est rendue telle quelle —
    c'est à l'appelant de décider qu'un vent inconnu vaut zéro, pas à cette
    conversion de le masquer.
    """
    return vent_10m * FACTEUR_VENT_HAUTEUR


def masse_volumique_air(temp_c: float | None, pression_hpa: float | None) -> float:
    """ρ = p / (R·T), en kg/m³. Rend `RHO_DEFAUT` si l'une des deux manque.

    Entre 0 °C et 30 °C, ρ varie de 1,29 à 1,16 : 10 % sur la traînée, soit
    plusieurs minutes sur une sortie de trois heures. Cela vaut l'appel à
    l'archive.
    """
    if temp_c is None or pression_hpa is None:
        return RHO_DEFAUT
    if not (math.isfinite(temp_c) and math.isfinite(pression_hpa)):
        return RHO_DEFAUT
    kelvin = temp_c + 273.15
    if kelvin <= 0 or pression_hpa <= 0:
        return RHO_DEFAUT
    return (pression_hpa * 100.0) / (R_AIR * kelvin)


def puissance_requise(v_ms: float, pente: float, vent_face_ms: float, p: Parametres) -> float:
    """Puissance mécanique au pédalier, en watts, pour tenir `v_ms`.

    `pente` est une tangente (0,05 = 5 %), `vent_face_ms` le vent de face
    compté positif (un vent de dos est négatif). Le résultat peut être
    négatif : en descente, il faudrait freiner.

    Une entrée non finie est **refusée**. Rendre `nan` serait pire que lever :
    le NaN traverse les additions sans bruit, ressort en « temps estimé » vide
    ou en tri arbitraire, et personne ne sait d'où il vient.
    """
    _finis(v_ms=v_ms, pente=pente, vent_face_ms=vent_face_ms)
    theta = math.atan(pente)
    v_air = v_ms + vent_face_ms
    resistance = (
        p.crr * p.masse_totale_kg * G * math.cos(theta) + p.masse_totale_kg * G * math.sin(theta)
    )
    trainee = 0.5 * p.rho * p.cda_m2 * v_air * abs(v_air)
    return (resistance * v_ms + trainee * v_ms) / p.rendement


def _finis(**valeurs: float) -> None:
    """Refuse toute entrée non finie, en nommant le paramètre fautif."""
    fautifs = {nom: v for nom, v in valeurs.items() if not math.isfinite(v)}
    if fautifs:
        detail = ", ".join(f"{nom}={v!r}" for nom, v in fautifs.items())
        raise ErreurUtilisateur(f"modèle physique : {detail} — des nombres finis sont attendus")


def vitesse_regime(puissance_w: float, pente: float, vent_face_ms: float, p: Parametres) -> float:
    """Vitesse d'équilibre, en m/s, pour une puissance tenue — l'inverse de `puissance_requise`.

    Bissection sur [0, `V_MAX_BISSECTION_MS`]. Sur le plat et en montée,
    `puissance_requise` est strictement croissante en v et la racine est
    unique. En descente elle décroît d'abord (la gravité fournit), passe par
    un minimum négatif, puis croît : pour une puissance demandée ≥ 0, il n'y
    a là encore qu'une seule racine, celle qui suit le minimum — c'est la
    vitesse d'équilibre, et la bissection y va d'elle-même puisque
    `f(0) = −P ≤ 0`.

    Puissance nulle sur le plat → 0 m/s, sans division par zéro. Puissance
    nulle en descente → la vitesse limite de la descente. Puissance négative
    → 0 m/s : le modèle ne sait pas freiner.
    """
    # Puissance **nulle** n'est pas un cas à part : sur le plat la bissection
    # rend 0 m/s, en descente elle rend la vitesse limite. Seules une
    # puissance négative (le modèle ne sait pas freiner) et une valeur non
    # finie sont refusées d'entrée.
    if not math.isfinite(puissance_w) or puissance_w < 0:
        return 0.0
    _finis(pente=pente, vent_face_ms=vent_face_ms)

    def ecart(v: float) -> float:
        return puissance_requise(v, pente, vent_face_ms, p) - puissance_w

    haut = V_MAX_BISSECTION_MS
    if ecart(haut) <= 0:
        # Plus de puissance que ce que 108 km/h demande : on ne va pas au-delà.
        return haut
    bas = 0.0
    if ecart(bas) > 0:
        # Ne peut arriver qu'avec une puissance négative, déjà écartée.
        return 0.0
    for _ in range(MAX_ITERATIONS):
        if haut - bas <= TOLERANCE_MS:
            break
        milieu = (bas + haut) / 2
        if ecart(milieu) > 0:
            haut = milieu
        else:
            bas = milieu
    return (bas + haut) / 2


# --- à plat, sans vent, lancé -------------------------------------------------
#
# Les trois fonctions qui suivent ne sont que `puissance_requise` et
# `vitesse_regime` au cas particulier « pente nulle, vent nul », en km/h. Elles
# existent parce que **c'est ce cas-là que l'écran de FTP montre** (décision 7
# du cycle UX) : « la vitesse à plat, sans vent, lancé » est l'entrée de celui
# qui ne pense pas en watts, et éditer l'une doit recalculer l'autre. Écrire
# `vitesse_regime(p, 0.0, 0.0, params)` à chaque appel marchait, mais laissait
# à chaque appelant le soin de se rappeler lequel des deux zéros est la pente.
#
# **Ce n'est pas la moyenne du compteur.** Mesuré le 16/09/2026 sur les sorties
# extérieures du mainteneur (décision 8) : le compteur affiche 87 à 90 % de
# cette vitesse-là selon le vélo, le relief et le vent coûtant plus cher que
# les arrêts. Confondre les deux décale tout l'escalier des zones vers le bas.


def vitesse_a_plat_ms(puissance_w: float, p: Parametres) -> float:
    """Vitesse d'équilibre sur le plat, sans vent, en m/s."""
    return vitesse_regime(puissance_w, 0.0, 0.0, p)


def vitesse_a_plat_kmh(puissance_w: float, p: Parametres) -> float:
    """Vitesse d'équilibre sur le plat, sans vent, en km/h."""
    return vitesse_a_plat_ms(puissance_w, p) * 3.6


def force_a_plat_n(vitesse_kmh: float, p: Parametres) -> float:
    """La résistance totale à vaincre sur le plat, sans vent, en newtons.

    Roulement plus traînée, **sans** le rendement de transmission : c'est une
    force subie par le vélo, pas ce que le cycliste dépense pour la vaincre.

    Ce nombre est celui qui gouverne la durée prédite d'une boucle quand les
    paramètres ne sont pas mesurés (campagne du 17/09/2026, commit `b6114b2`) :
    à résistance totale égale à l'allure de croisière, le partage entre CdA et
    Crr ne déplace pas la durée d'une demi-minute sur 2 h, alors qu'un newton
    d'erreur en coûte de l'ordre de deux et demie. `physique.litterature` s'en
    sert pour choisir et pour justifier ses jeux génériques.
    """
    _finis(vitesse_kmh=vitesse_kmh)
    v = vitesse_kmh / 3.6
    return p.crr * p.masse_totale_kg * G + 0.5 * p.rho * p.cda_m2 * v * v


def puissance_a_plat_w(vitesse_kmh: float, p: Parametres) -> float:
    """Puissance à tenir pour rouler `vitesse_kmh` sur le plat, sans vent.

    L'inverse exact de `vitesse_a_plat_kmh` : c'est `puissance_requise`, pas
    une bissection, donc l'aller-retour ne coûte rien en précision. Une
    vitesse négative est refusée — reculer n'est pas un régime.
    """
    _finis(vitesse_kmh=vitesse_kmh)
    if vitesse_kmh < 0:
        raise ErreurUtilisateur(
            f"modèle physique : vitesse à plat négative ({vitesse_kmh} km/h)"
        )
    return puissance_requise(vitesse_kmh / 3.6, 0.0, 0.0, p)


# --- la moyenne du compteur ---------------------------------------------------
#
# La **troisième valeur** de l'écran de FTP (décision 8 du cycle UX,
# `docs/ux/cycle_ux_contrat.md`). Sans elle, quelqu'un tape dans le champ « à
# plat » la moyenne qu'il lit sur son compteur, et tout l'escalier des zones se
# décale vers le bas : la mesure du 16/09/2026 place alors le cycliste *sous*
# sa Z2, et cette position fausse se propage à toutes les autres zones.
#
# **Le facteur est un réglage par vélo** (`config.Velo.facteur_compteur`), pas
# une constante de module : il dépend de la masse du cycliste autant que de ses
# routes. Le mesurer sur son propre historique est le travail de
# `tests/validation/facteur_compteur_retrospectif.py` ; ce qui suit n'est que le
# défaut de celui qui n'a pas encore d'historique.
#
# **Le temps retenu est le temps écoulé**, du premier au dernier point, arrêts
# compris — pas le temps de mouvement. Les deux existent et ne donnent pas le
# même facteur (quatre points d'écart, mesurés le 16/09/2026). Trois raisons :
# le temps écoulé se lit sur n'importe quelle source, alors que le GPX et le TCX
# ne portent aucun temps de mouvement (`Activite.duree_mouvement_s` y vaut
# `None`) ; il ne dépend pas du réglage d'arrêt automatique du compteur, qui est
# une propriété de l'appareil et non du cycliste ; et c'est celui que le
# cycliste calcule de tête, « 70 km en 3 h ».

#: Dénivelé du profil de référence qui sert à dériver un facteur par défaut, en
#: mètres de montée par kilomètre parcouru. 10 m/km, c'est « 1 000 m pour
#: 100 km » : la sortie vallonnée telle qu'on la nomme couramment.
#:
#: **Ce n'est pas une mesure**, et le défaut qu'il produit est faux pour à peu
#: près tout le monde : trop sévère en plaine, très optimiste en montagne. Il
#: n'existe que pour donner un chiffre plausible à un vélo neuf, et il est fait
#: pour être remplacé par la mesure dès qu'il y a un historique.
DENIVELE_REFERENCE_M_PAR_KM = 10.0

#: Part du temps écoulé passée à l'arrêt sur la sortie de référence : 5 %, soit
#: trois minutes par heure — feux, carrefours, un bidon.
#:
#: C'est le seul morceau du défaut qui ne se dérive pas : le modèle physique
#: ignore les arrêts (docstring de `simuler`). Faux pour qui traverse une ville
#: à chaque sortie comme pour qui roule sur route déserte.
PART_ARRET_REFERENCE = 0.05


def facteur_compteur_defaut(
    puissance_w: float,
    p: Parametres,
    *,
    denivele_m_par_km: float = DENIVELE_REFERENCE_M_PAR_KM,
    part_arret: float = PART_ARRET_REFERENCE,
) -> float:
    """Le facteur d'un vélo dont personne n'a encore mesuré le sien.

    Le profil de référence est une alternance symétrique : la moitié de la
    distance en montée à `pente`, l'autre moitié en descente à `−pente`, avec
    `pente = denivele_m_par_km / 500` (monter 10 m par kilomètre parcouru quand
    la moitié seulement grimpe, c'est 2 %). À puissance constante, la vitesse
    moyenne sur une telle alternance est la **moyenne harmonique** des deux
    vitesses de régime — la moyenne se fait à distance égale, pas à temps égal.
    Elle est plus basse que la vitesse à plat parce que la relation
    puissance → vitesse est convexe : la côte coûte plus que la descente ne
    rend. La descente est plafonnée à `V_MAX_DESCENTE_KMH` comme dans
    `simuler` : le cycliste freine, le modèle ne le sait pas.

    **C'est là que la masse entre**, et c'est la raison d'être de cette
    dérivation. Un facteur écrit en dur serait celui d'un seul homme sur ses
    seules routes ; ici, 25 kg de plus font tomber le facteur de plusieurs
    points, parce qu'ils ne coûtent presque rien à plat et beaucoup en côte.

    Les arrêts, eux, ne se dérivent pas : `part_arret` est une convention
    (`PART_ARRET_REFERENCE`), pas une mesure. Le résultat entier est donc une
    **supposition**, et tout écran qui l'affiche doit le dire.
    """
    _finis(
        puissance_w=puissance_w,
        denivele_m_par_km=denivele_m_par_km,
        part_arret=part_arret,
    )
    if puissance_w <= 0:
        raise ErreurUtilisateur(
            f"modèle physique : puissance positive attendue, reçu {puissance_w!r} W"
        )
    if denivele_m_par_km < 0:
        raise ErreurUtilisateur(
            f"modèle physique : dénivelé de référence négatif ({denivele_m_par_km} m/km)"
        )
    if not 0.0 <= part_arret < 1.0:
        raise ErreurUtilisateur(
            f"modèle physique : part d'arrêt attendue dans [0, 1[, reçu {part_arret!r}"
        )

    v_plat = vitesse_a_plat_ms(puissance_w, p)
    if v_plat <= 0:
        raise ErreurUtilisateur(
            "modèle physique : vitesse à plat nulle — paramètres de vélo inexploitables"
        )
    pente = denivele_m_par_km / 500.0
    # Même plancher et même plafond que `simuler` : sous `V_MIN_MS` le cycliste
    # met pied à terre, au-dessus de `V_MAX_DESCENTE_KMH` il freine.
    v_montee = max(vitesse_regime(puissance_w, pente, 0.0, p), V_MIN_MS)
    v_descente = min(
        vitesse_regime(puissance_w, -pente, 0.0, p), V_MAX_DESCENTE_KMH / 3.6
    )
    v_mouvement = 2.0 / (1.0 / v_montee + 1.0 / v_descente)
    return (v_mouvement / v_plat) * (1.0 - part_arret)


def moyenne_compteur_kmh(
    puissance_w: float, p: Parametres, facteur: float | None = None
) -> float:
    """La moyenne que le compteur affichera, en km/h — la troisième valeur.

    `facteur` est le `facteur_compteur` du vélo, mesuré sur l'historique du
    cycliste. À `None`, `facteur_compteur_defaut` prend le relais : le chiffre
    rendu cesse alors d'être une mesure, et l'écran qui l'affiche doit le dire.

    Le résultat est plus bas que `vitesse_a_plat_kmh` dès que le facteur l'est,
    et c'est tout l'intérêt de l'afficher. Un facteur au-dessus de 1 n'est pas
    refusé ici — rouler en groupe abrite du vent et fait mieux que le modèle
    solo — il est simplement borné au chargement de la configuration.
    """
    if facteur is None:
        facteur = facteur_compteur_defaut(puissance_w, p)
    else:
        _finis(facteur=facteur)
        if facteur <= 0:
            raise ErreurUtilisateur(
                f"modèle physique : facteur compteur positif attendu, reçu {facteur!r}"
            )
    return vitesse_a_plat_kmh(puissance_w, p) * facteur


# --- temps écoulé, porte à porte ---------------------------------------------
#
# `simuler` rend un temps **en mouvement** (docstring plus bas) ; le cycliste,
# lui, mesure sa sortie porte à porte. Jusqu'au 25/09/2026, le porte à porte
# appliquait la moyenne compteur habituelle à la distance — une moyenne à
# plat, qui ignorait le relief de la boucle évaluée (« sinon en montagne ça va
# être débile », mainteneur, 21/09). Depuis L9.1, il part du temps simulé de
# CE tracé-ci, relief et vent compris, et le multiplie par ce que les vraies
# sorties du cycliste coûtent en plus : une **fourchette**, pas un chiffre,
# parce que l'erreur du modèle sur une sortie (3 à 5 %) est du même ordre que
# la correction elle-même (note du 23/09, tranché par le mainteneur).


@dataclass(frozen=True)
class FourchettePorteAPorte:
    """Le ratio temps écoulé réel / temps simulé d'un vélo : 25ᵉ, 50ᵉ et 75ᵉ centiles.

    `provenance` vaut `"mesure"` (centiles mesurés par `ourouler calibrer` sur
    les sorties de ce vélo roulées seul, `n` sorties) ou `"defaut"` (la
    convention de `physique.litterature.FOURCHETTE_PORTE_A_PORTE_DEFAUT`,
    mesurée sur un seul cycliste, `n` = 0). Tout écran qui l'affiche dit
    laquelle des deux (règle absolue 5).
    """

    bas: float
    mediane: float
    haut: float
    provenance: str = "defaut"
    n: int = 0

    def __post_init__(self) -> None:
        _finis(bas=self.bas, mediane=self.mediane, haut=self.haut)
        if not 0.0 < self.bas <= self.mediane <= self.haut:
            raise ErreurUtilisateur(
                "fourchette du porte à porte : 0 < bas ≤ médiane ≤ haut attendu, reçu "
                f"{self.bas!r}, {self.mediane!r}, {self.haut!r}"
            )
        if self.provenance not in ("mesure", "defaut"):
            raise ErreurUtilisateur(
                f"fourchette du porte à porte : provenance {self.provenance!r} inconnue"
            )


@dataclass(frozen=True)
class PorteAPorte:
    """Le temps porte à porte d'une boucle, en fourchette : `bas_s` ≤ `mediane_s` ≤ `haut_s`."""

    bas_s: float
    mediane_s: float
    haut_s: float
    provenance: str


def temps_ecoule(temps_estime_s: float, fourchette: FourchettePorteAPorte) -> PorteAPorte:
    """Le temps porte à porte, arrêts compris : `temps_estime_s × [bas, médiane, haut]`.

    `temps_estime_s` est le temps **en mouvement** d'une candidate (celui que
    `simuler` rend sur ce tracé-ci, relief et vent compris, ou son repli à
    vitesse moyenne). La fourchette est celle du vélo
    (`physique.commande.fourchette_du_velo`) : mesurée sur ses sorties, ou la
    convention par défaut.

    **La moyenne compteur n'entre plus ici.** Elle garde son rôle ailleurs —
    dimensionner la distance demandée (« 5 h à 23 km/h » → 115 km) — mais ce
    n'est plus elle qui chronomètre : elle est à plat, le temps simulé ne
    l'est pas. Plus besoin non plus du plancher « au moins le temps en
    mouvement plus 5 % d'arrêts » de l'ancienne formule : il n'existait que
    pour rattraper une moyenne à plat battue par une boucle vallonnée.

    Rend un `PorteAPorte` dont la `provenance` est celle de la fourchette.
    """
    _finis(temps_estime_s=temps_estime_s)
    if temps_estime_s < 0:
        raise ErreurUtilisateur(
            f"temps écoulé : temps en mouvement négatif ({temps_estime_s} s)"
        )
    return PorteAPorte(
        bas_s=temps_estime_s * fourchette.bas,
        mediane_s=temps_estime_s * fourchette.mediane,
        haut_s=temps_estime_s * fourchette.haut,
        provenance=fourchette.provenance,
    )


# --- simulation d'un parcours -------------------------------------------------


def simuler(
    trace: Trace,
    puissance_w: float | Callable[[float], float],
    p: Parametres,
    vent: Callable[[float, float], float] | None = None,
) -> Simulation:
    """Le temps **en mouvement** sur `trace`, par pas de `PAS_M` mètres.

    `puissance_w` est une constante ou une fonction de la distance cumulée
    (en mètres) — c'est ainsi qu'on rejoue le profil de puissance d'une
    sortie réelle. `vent(dist_m, cap_deg)` rend le vent de face en m/s au
    point courant ; sans lui, air calme.

    **Ce temps ignore les arrêts** : feux, stops, ravitaillements, photos,
    crevaisons. Sur route ouverte il est donc systématiquement plus court
    qu'un temps de sortie mesuré montre en montre, et l'écart n'est pas une
    erreur du modèle.

    Le profil d'altitude est rééchantillonné au pas de 100 m puis lissé
    (`FENETRE_ALTITUDE` pas) avant d'être dérivé en pente ; sans ce lissage,
    le bruit de l'altimètre fabriquerait des rampes qui n'existent pas.
    """
    points = trace.points
    if len(points) < 2:
        raise ErreurUtilisateur("simuler : tracé de moins de deux points, il n'y a rien à parcourir")
    distances = _distances_cumulees(points)
    total = distances[-1]
    if not (math.isfinite(total) and total > 0):
        raise ErreurUtilisateur("simuler : tracé de longueur nulle")

    bornes = _bornes_pas(total)
    altitudes = moyenne_glissante(
        [_altitude(points, distances, d) for d in bornes], FENETRE_ALTITUDE
    )
    puissance = puissance_w if callable(puissance_w) else (lambda _d, _p=float(puissance_w): _p)

    v_max_descente = V_MAX_DESCENTE_KMH / 3.6
    temps_total = 0.0
    par_segment: list[tuple[float, float, float, float]] = []
    plafonnes = bloques = 0
    for i in range(len(bornes) - 1):
        longueur = bornes[i + 1] - bornes[i]
        if longueur <= 0:
            continue
        pente = (altitudes[i + 1] - altitudes[i]) / longueur
        milieu = (bornes[i] + bornes[i + 1]) / 2
        cap = _cap_a(points, distances, milieu)
        vent_face = vent(milieu, cap) if vent is not None else 0.0
        if vent_face is None or not math.isfinite(vent_face):
            vent_face = 0.0
        v = vitesse_regime(float(puissance(milieu)), pente, vent_face, p)
        if pente < 0 and v > v_max_descente:
            v = v_max_descente
            plafonnes += 1
        if v < V_MIN_MS:
            v = V_MIN_MS
            bloques += 1
        t = longueur / v
        temps_total += t
        par_segment.append((bornes[i + 1], pente, v * 3.6, t))

    return Simulation(
        temps_s=temps_total,
        distance_m=total,
        vitesse_moy_kmh=(total / 1000.0) / (temps_total / 3600.0) if temps_total > 0 else 0.0,
        par_segment=par_segment,
        pas_plafonnes=plafonnes,
        pas_bloques=bloques,
    )


def _bornes_pas(total: float) -> list[float]:
    """Les bornes des pas de 100 m, le dernier pas absorbant le reste.

    Un reste minuscule (3 cm sur un tracé de 10 000,03 m) ferait un pas
    dégénéré : il est fondu dans le pas précédent plutôt que de produire une
    pente calculée sur trois centimètres d'altitude lissée.
    """
    bornes = [0.0]
    while bornes[-1] + PAS_M < total:
        bornes.append(bornes[-1] + PAS_M)
    if total - bornes[-1] < PAS_M / 10 and len(bornes) > 1:
        bornes[-1] = total
    else:
        bornes.append(total)
    return bornes


def _distances_cumulees(points: Sequence[PointTrace]) -> list[float]:
    """Les distances cumulées du tracé, recalculées si le tracé n'en porte pas.

    Même précaution que dans `boucle.meteo_trace` : un tracé importé dont les
    `dist_m` sont restées à zéro donnerait une simulation de longueur nulle.
    """
    if points[-1].dist_m > 0:
        valeurs = [float(p.dist_m) for p in points]
        if all(b >= a for a, b in zip(valeurs[:-1], valeurs[1:], strict=True)):
            return valeurs
    cumul = [0.0]
    for a, b in zip(points[:-1], points[1:], strict=True):
        cumul.append(cumul[-1] + distance_m(a, b))
    return cumul


def _index_avant(distances: Sequence[float], d: float) -> int:
    """Indice du dernier point dont la distance cumulée est ≤ `d` (recherche dichotomique)."""
    bas, haut = 0, len(distances) - 1
    while bas < haut:
        milieu = (bas + haut + 1) // 2
        if distances[milieu] <= d:
            bas = milieu
        else:
            haut = milieu - 1
    return bas


def _altitude(points: Sequence[PointTrace], distances: Sequence[float], d: float) -> float:
    """Altitude interpolée à la distance `d`. 0 si le tracé n'a aucune altitude.

    Un tracé sans altitude donne une pente nulle partout — c'est le terrain
    plat, faute de mieux, et c'est dit dans `Trace.denivele_m` qui vaut alors
    `None`.
    """
    i = _index_avant(distances, d)
    avant = points[i]
    apres = points[min(i + 1, len(points) - 1)]
    if avant.alt_m is None and apres.alt_m is None:
        return 0.0
    if avant.alt_m is None:
        return float(apres.alt_m)
    if apres.alt_m is None:
        return float(avant.alt_m)
    portee = distances[min(i + 1, len(distances) - 1)] - distances[i]
    f = (d - distances[i]) / portee if portee > 0 else 0.0
    return float(avant.alt_m) + (float(apres.alt_m) - float(avant.alt_m)) * f


def _cap_a(points: Sequence[PointTrace], distances: Sequence[float], d: float) -> float:
    """Le cap du tracé à la distance `d`, en degrés. 0 si les deux points coïncident."""
    i = _index_avant(distances, d)
    j = min(i + 1, len(points) - 1)
    if j == i:
        i = max(0, j - 1)
    if distance_m(points[i], points[j]) <= 0:
        return 0.0
    return cap_deg(points[i], points[j])
