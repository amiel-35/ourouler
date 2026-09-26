"""Candidates de boucle : plusieurs propositions autour d'une direction voulue.

BRouter ne sait pas produire « une boucle de 60 km » : il prend un *rayon*
(`roundTripDistance`) et rend la boucle qu'il trouve. Mesuré sur le serveur
réel : rayon 8 000 m → 40,4 km ; rayon 22 000 m → 103 km, soit un rapport
d'environ 5 — mais qui dépend du terrain, donc jamais codé en dur au-delà
d'un point de départ : on **ajuste par proportion** sur ce que le moteur a
vraiment rendu.

Le client est injectable : ce module ne connaît ni l'URL ni les identifiants.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace

from ourouler.boucle.antennes import detecter, elaguer
from ourouler.noyau.erreurs import ErreurConnecteur, ErreurDistanceInatteignable, ErreurUtilisateur
from ourouler.noyau.ports import Routeur
from ourouler.noyau.profil import Depart
from ourouler.noyau.trace import Trace

#: Rapport de départ entre la longueur d'une boucle et le rayon demandé.
#: Point d'entrée de l'ajustement, pas une constante de vérité.
RAPPORT_RAYON_DEFAUT = 5.0

#: Écart entre deux azimuts essayés, de part et d'autre de la direction voulue.
PAS_AZIMUT_DEG = 20.0

#: Nombre d'ajustements de rayon par azimut, après le premier essai.
#:
#: Trois et non deux, sur vérification réelle : l'élagage des antennes retire
#: des centaines de mètres à la boucle rendue par le moteur, la distance
#: mesurée oscille alors d'une itération à l'autre — 53,6 km puis 65,4 km pour
#: 60 km demandés — et deux corrections s'arrêtent au milieu de l'oscillation. Une
#: itération de plus affine sans coûter cher, à condition que le plafond
#: d'appels suive la demande — c'est ce que fait `appels_pour`.
AJUSTEMENTS_MAX = 3

#: Bornes du facteur de correction d'une itération à la suivante. Diviser ou
#: multiplier le rayon par plus de 4 d'un coup, c'est croire une réponse que
#: le moteur ne sait manifestement pas rattacher au rayon demandé (boucle de
#: 100 m pour une cible de 60 km).
FACTEUR_MIN, FACTEUR_MAX = 0.25, 4.0

#: Bornes du rayon lui-même. En dessous de 500 m, aucun moteur ne rend une
#: boucle exploitable ; au-delà de 200 km, on demande à un serveur
#: auto-hébergé un calcul qui n'a plus de sens pour une sortie à vélo.
RAYON_MIN_M, RAYON_MAX_M = 500.0, 200_000.0

#: Pas d'élargissement de la tolérance de distance, en écart relatif.
#:
#: Quand aucune boucle ne tient dans les contraintes, on le dit : « on a élargi
#: de X % », par paliers de 5 % (décision Q41 d, `docs/journal/questions/questions_mainteneur.md`).
#:
#: Ce pas n'est pas un seuil : aucune boucle n'est acceptée ou refusée parce
#: qu'il vaut 5 %. Il ne fait qu'arrondir le chiffre qu'on montre, pour que
#: l'écran dise « élargi de 10 % » plutôt que « élargi de 7,3 % ».
PAS_ELARGISSEMENT = 0.05


def palier(ecart_relatif: float, tolerance: float) -> float:
    """De combien il a fallu élargir `tolerance` pour accepter `ecart_relatif`.

    Le plus petit multiple de `PAS_ELARGISSEMENT` qui, ajouté à `tolerance`,
    contient l'écart mesuré — `0.0` si l'écart tenait déjà dans la tolérance.
    Tolérance 10 %, écart −17 % : il manque 7 points, deux paliers de 5 %
    suffisent, la réponse est `0.10` (bande atteinte : ±20 %).

    **Un élargissement ne relance pas la recherche**, et c'est une mesure, pas
    une opinion. Dans `_explorer_azimut`, `tolerance` ne sert qu'à décider quand
    *arrêter* d'affiner le rayon (`if abs(ecart) <= tolerance: break`) : elle
    ne filtre rien et n'oriente rien. Une tolérance plus large arrête donc
    l'affinage **plus tôt**, et ne peut rendre qu'une boucle égale ou pire.
    Élargir puis réessayer dépenserait des appels au serveur BRouter
    pour un résultat qu'on a déjà en main. Le palier se **lit** sur la
    candidate trouvée au réglage le plus serré ; il ne se cherche pas.
    `test_elargir_la_tolerance_ne_rend_jamais_une_meilleure_boucle` le vérifie
    sur un moteur qui ne converge pas.
    """
    manque = abs(ecart_relatif) - tolerance
    if manque <= 0:
        return 0.0
    # Le `- 1e-9` évite qu'un 0,05 flottant (0,050000000000000003) réclame un
    # palier de plus que celui qu'un humain compterait.
    marches = math.ceil(manque / PAS_ELARGISSEMENT - 1e-9)
    return round(marches * PAS_ELARGISSEMENT, 10)


def elargissement_max(tolerance: float) -> float:
    """Le plus grand élargissement qu'on s'autorise à servir : `tolerance` elle-même.

    Il faut bien s'arrêter : servir 40 km à qui en demande 150 n'explique plus
    rien, ça substitue une autre sortie à celle qui était demandée. Mais on
    n'invente pas de seuil pour le dire (décision Q41 d) : un seuil inventé
    est un chiffre qu'on passe sa vie à défendre.

    **Le plafond retenu n'est donc pas un chiffre, c'est une unité** : la
    bande acceptée peut au plus **doubler**. Tolérance de 10 % configurée,
    20 % servis au maximum ; l'élargissement s'arrête quand il a consommé
    autant que la contrainte d'origine.

    Pourquoi ça se défend là où un chiffre rond ne se défendrait pas :
    `tolerance_distance` est **la seule chose que l'utilisateur ait dite** sur
    l'écart de distance qu'il accepte. Tant qu'on reste en deçà du double, on
    desserre sa contrainte à lui, dans son unité à lui, et on lui dit de
    combien ; au-delà, on ne desserre plus rien, on substitue une contrainte
    prise ailleurs que chez lui. Et ce plafond **suit sa configuration** :
    qui règle 5 % s'arrête à 10 %, qui règle 20 % s'arrête à 40 %. Un seuil
    arbitraire ne fait pas ça — il reste où on l'a posé, quoi que dise la
    configuration. C'est à ça qu'on les distingue.

    Un plancher d'un palier, et lui non plus n'est pas un chiffre choisi :
    `config` accepte des tolérances jusqu'à 1 %, et sous 5 % le double
    resterait plus étroit que le pas d'élargissement lui-même — le mécanisme
    n'aurait jamais lieu d'être. **On ne refuse
    personne sans lui avoir offert au moins un palier**, sinon l'escalier
    n'a pas de première marche.

    Conséquence voulue : il n'y a **aucune** valeur en dur ici, et le palier
    ne peut pas monter indéfiniment. Il est lu sur un ensemble fini de
    candidates déjà calculées, et borné par un réglage que l'utilisateur peut
    lire et changer.
    """
    return max(tolerance, PAS_ELARGISSEMENT)


@dataclass
class Candidate:
    trace: Trace
    azimut_deg: float
    rayon_m: float
    ecart_relatif: float  # (distance − cible) / cible
    #: La tolérance de distance en vigueur quand cette candidate a été jugée.
    tolerance: float = 0.0
    #: De combien il a fallu élargir cette tolérance, en paliers de 5 %.
    #: `0.0` quand la boucle tenait dans la tolérance — le cas normal.
    elargissement: float = 0.0

    @property
    def hors_tolerance(self) -> bool:
        """Vrai quand la boucle n'entre pas dans la tolérance demandée.

        C'est ce que l'ancienne rédaction taisait : la meilleure candidate
        était servie avec son écart, sans un mot, même à 17 % d'une tolérance
        réglée à 10 %.
        """
        return self.elargissement > 0.0


def appels_pour(nb: int) -> int:
    """Plafond d'appels au moteur pour `nb` candidates demandées.

    Chaque azimut a droit à son premier essai et à ses `AJUSTEMENTS_MAX`
    corrections : le plafond doit donc suivre la demande, et non l'inverse.
    Un plafond fixe faisait rendre trois candidates à qui en demandait cinq
    dès que le moteur cessait de converger — l'utilisateur demandait cinq
    directions, en voyait trois, et rien ne le lui disait.
    """
    return nb * (1 + AJUSTEMENTS_MAX)


def azimuts(azimut_deg: float, nb: int) -> list[float]:
    """`azimut_deg`, puis ± 20°, ± 40°… — `nb` directions, ramenées dans [0, 360)."""
    sortie = [azimut_deg % 360]
    pas = PAS_AZIMUT_DEG
    while len(sortie) < nb:
        sortie.append((azimut_deg + pas) % 360)
        if len(sortie) < nb:
            sortie.append((azimut_deg - pas) % 360)
        pas += PAS_AZIMUT_DEG
    return sortie


def _plus_proche(
    courte: Candidate, longue: Candidate | None, tolerance: float
) -> Candidate:
    """Des deux essais d'un azimut, celle qui répond le mieux à la demande.

    `courte` tient déjà dans la bande, sous la cible ; `longue` est ce qu'a
    rendu l'essai supplémentaire, et peut être `None` (tracé non borné) ou
    hors bande. La règle : **le plus petit écart absolu l'emporte, et à écart
    égal, la plus longue** — rallonger coûte moins que raccourcir, et c'est la
    même règle que le tri final entre azimuts, pour qu'un étage
    ne défasse pas ce que l'autre a choisi.
    """
    if longue is None or abs(longue.ecart_relatif) > tolerance:
        return courte
    if abs(longue.ecart_relatif) < abs(courte.ecart_relatif):
        return longue
    if abs(longue.ecart_relatif) > abs(courte.ecart_relatif):
        return courte
    # Écart égal : la préférence pour la plus longue s'exprime ici, sans rien coûter.
    return longue if longue.ecart_relatif > courte.ecart_relatif else courte


@dataclass
class _Budget:
    """Les appels au moteur déjà faits, leur plafond, et la dernière panne rencontrée.

    Partagé par tous les azimuts d'un même `generer` : le plafond d'appels
    porte sur la recherche entière, pas sur un azimut.
    """

    appels_max: int
    appels: int = 0
    derniere_erreur: ErreurConnecteur | None = None

    @property
    def epuise(self) -> bool:
        return self.appels >= self.appels_max


def generer(
    client: Routeur,
    depart: Depart,
    *,
    distance_km: float,
    azimut_deg: float,
    nb: int,
    tolerance: float,
    profil: str | None = None,
    appels_max: int | None = None,
) -> list[Candidate]:
    """Jusqu'à `nb` boucles autour de `azimut_deg`, triées par écart à la distance voulue.

    Chaque azimut (`azimuts`) est exploré par `_explorer_azimut`, qui rend sa
    meilleure boucle **bornée** — un tracé qui ne revient pas au départ n'est
    pas une boucle. Cette boucle est ensuite jugée contre la tolérance, une
    fois : elle emporte `tolerance`, `elargissement` (de combien il a fallu
    élargir, par paliers de 5 %) et `hors_tolerance` (sans eux, 2 km
    demandés et 2,69 km servis, +34,7 % pour une tolérance de 10 %, passeraient
    sans rien dire à l'écran). Servie si l'élargissement tient sous
    `elargissement_max`, écartée sinon ; `_conclure` décide enfin entre
    servir, relancer la dernière panne ou refuser.

    Deux garde-fous, et ils ne disent pas la même chose : `appels_max` borne
    le **nombre** d'appels au moteur, les bornes de `_rayon_suivant` leur
    **coût**. Par défaut, `appels_max` vaut `appels_pour(nb)` : le plafond
    suit la demande, pour que `nb = 5` rende cinq candidates même quand le
    moteur épuise ses ajustements sur chacune.

    Chaque règle est détaillée là où elle s'applique : `_valider`, `_essayer`
    (élagage, pannes), `_explorer_azimut`, `_rayon_suivant` et `_conclure`.
    """
    _valider(distance_km, nb)
    budget = _Budget(appels_max if appels_max is not None else appels_pour(nb))
    cible_m = distance_km * 1000.0
    plafond = elargissement_max(tolerance)
    candidates: list[Candidate] = []
    trop_loin: list[Candidate] = []
    for azimut in azimuts(azimut_deg, nb):
        meilleure = _explorer_azimut(
            client, depart, azimut, cible_m=cible_m, tolerance=tolerance, profil=profil, budget=budget
        )
        if meilleure is not None:
            marche = palier(meilleure.ecart_relatif, tolerance)
            meilleure = replace(meilleure, tolerance=tolerance, elargissement=marche)
            if marche <= plafond:
                candidates.append(meilleure)
            else:
                trop_loin.append(meilleure)
        if budget.epuise:
            break
    return _conclure(
        candidates,
        trop_loin,
        budget.derniere_erreur,
        distance_km=distance_km,
        tolerance=tolerance,
        plafond=plafond,
    )


def _valider(distance_km: float, nb: int) -> None:
    """Refuse une demande absurde **avant** le premier appel au moteur.

    Une `distance_km` qui n'est pas un nombre fini strictement positif et un
    `nb` inférieur à 1 sont des `ErreurUtilisateur` : sans cible,
    `ecart_relatif` ne veut rien dire (NaN), et sans candidate demandée il
    n'y a rien à chercher. Une entrée absurde ne doit pas coûter un
    aller-retour sur le serveur BRouter.
    """
    if not math.isfinite(distance_km) or distance_km <= 0:
        raise ErreurUtilisateur(
            f"distance_km = {distance_km} : une distance strictement positive est attendue "
            "(l'écart relatif vaut (distance − cible) / cible)"
        )
    if nb < 1:
        raise ErreurUtilisateur(f"nb = {nb} : au moins une candidate est attendue")


def _essayer(
    client: Routeur, depart: Depart, azimut: float, *, rayon: float, profil: str | None, budget: _Budget
) -> Trace | None:
    """Un appel au moteur, compté ; la boucle élaguée, ou `None` s'il faut arrêter l'azimut.

    `None` quand le plafond d'appels est atteint, ou quand le moteur échoue
    sur cet azimut (profil refusé sur une direction, panne passagère) : une
    telle panne ne fait pas perdre les autres azimuts. Elle est retenue dans
    `budget.derniere_erreur`, et `_conclure` ne la relance que si **aucune**
    candidate n'a pu être produite.

    Chaque réponse est **élaguée de ses antennes** avant d'être mesurée : les
    crochets que le mode boucle fabrique en allant chercher un point de passage
    tombé à côté de la route sont retirés, et
    `trace.meta["antennes"]` dit combien et combien de mètres. L'ajustement de
    rayon travaille donc sur la distance **réellement proposée au cycliste**,
    pas sur celle qui incluait l'aller-retour.
    """
    if budget.epuise:
        return None
    try:
        trace = client.boucle(
            (depart.latitude, depart.longitude),
            azimut_deg=azimut,
            rayon_m=rayon,
            profil=profil,
        )
    except ErreurConnecteur as e:
        budget.derniere_erreur = e
        budget.appels += 1
        return None
    budget.appels += 1
    return elaguer(trace, detecter(trace))


def _explorer_azimut(
    client: Routeur,
    depart: Depart,
    azimut: float,
    *,
    cible_m: float,
    tolerance: float,
    profil: str | None,
    budget: _Budget,
) -> Candidate | None:
    """La meilleure boucle bornée d'un azimut, ou `None` si aucune ne l'est.

    Un premier essai au rayon `distance / 5`, puis au plus `AJUSTEMENTS_MAX`
    corrections par proportion (`_rayon_suivant`) tant que l'écart dépasse
    `tolerance` — trois, l'élagage des antennes faisant osciller la distance
    mesurée.

    **À tolérance égale, on préfère dépasser la cible** : faire dix
    kilomètres de plus n'est pas dur, en faire dix de moins ampute la sortie.
    Sur 60, 100 et 125 km × 8 azimuts, 20 candidates sur 24 tombaient court, médiane
    autour de −5 %. Une candidate sous la cible mais dans la tolérance ne
    fait donc pas sortir tout de suite : une correction de plus vise plus
    loin (le facteur vaut déjà > 1 sous la cible), et `_plus_proche` tranche
    entre les deux — la plus proche, la plus longue à écart égal, la même
    règle que le tri final entre azimuts — et non « toujours la plus longue »,
    qui servirait 137 km pour 125 demandés quand on en a 120 en main. Un seul essai de plus, jamais une
    relance ; le plafond ne change pas, mais le coût réel double à peu près
    (1,67 à 2,38 appels par azimut contre un, mesuré). Une
    candidate déjà au-dessus de la cible n'est jamais retouchée.
    """
    rayon = _borner(cible_m / RAPPORT_RAYON_DEFAUT)
    meilleure: Candidate | None = None
    candidate_courte: Candidate | None = None
    for _ in range(1 + AJUSTEMENTS_MAX):
        trace = _essayer(client, depart, azimut, rayon=rayon, profil=profil, budget=budget)
        if trace is None:
            break
        ecart = (trace.distance_m - cible_m) / cible_m
        candidate = None
        if trace.bornee():
            candidate = Candidate(trace=trace, azimut_deg=azimut, rayon_m=rayon, ecart_relatif=ecart)
            if meilleure is None or abs(ecart) < abs(meilleure.ecart_relatif):
                meilleure = candidate
        if candidate_courte is not None:
            return _plus_proche(candidate_courte, candidate, tolerance)
        if abs(ecart) <= tolerance:
            if not (ecart < 0 and candidate is not None and not budget.epuise):
                break
            candidate_courte = candidate
        suivant = _rayon_suivant(rayon, trace.distance_m, cible_m)
        if suivant is None:
            break
        rayon = suivant
    return meilleure


def _rayon_suivant(rayon: float, distance_m: float, cible_m: float) -> float | None:
    """Le rayon corrigé par proportion (`rayon × cible / obtenu`), ou `None` pour abandonner.

    La correction est **bornée des deux côtés** : facteur dans
    `[FACTEUR_MIN, FACTEUR_MAX]`, rayon dans `[RAYON_MIN_M, RAYON_MAX_M]`. Une
    réponse qui force une borne est une réponse qu'on ne sait pas exploiter,
    pas une réponse à laquelle il faut insister : l'azimut est abandonné, avec
    sa meilleure tentative. Sans ces bornes, un moteur qui rend 100 m pour une
    cible de 60 km ferait demander 7 200 km puis 4,3 millions de kilomètres
    au serveur BRouter. Une boucle de longueur nulle n'a rien à
    corriger : insister coûterait des appels pour le même résultat.
    """
    if distance_m <= 0:
        return None
    facteur = cible_m / distance_m
    if not FACTEUR_MIN <= facteur <= FACTEUR_MAX:
        return None
    suivant = rayon * facteur
    if not RAYON_MIN_M <= suivant <= RAYON_MAX_M:
        return None
    return suivant


def _conclure(
    candidates: list[Candidate],
    trop_loin: list[Candidate],
    derniere_erreur: ErreurConnecteur | None,
    *,
    distance_km: float,
    tolerance: float,
    plafond: float,
) -> list[Candidate]:
    """Les candidates servies, triées par écart absolu ; ou l'erreur qui dit pourquoi aucune.

    **Au-delà d'un élargissement, on refuse plutôt que de servir** : le
    plafond est `elargissement_max(tolerance)`. Quand des boucles bornées ont
    été trouvées mais qu'aucune n'y tient, `_trop_loin` lève une
    `ErreurDistanceInatteignable` qui **porte les mesures** du refus, pour que
    l'écran d'échec dise de combien il aurait fallu élargir au lieu d'un
    « réessayez ». Un azimut hors plafond ne condamne pas les autres, et une
    panne du moteur n'est relancée que si **aucune** candidate n'a tenu.
    """
    if not candidates and derniere_erreur is not None:
        raise derniere_erreur
    if not candidates and trop_loin:
        raise _trop_loin(trop_loin, distance_km=distance_km, tolerance=tolerance, plafond=plafond)
    return sorted(candidates, key=lambda c: abs(c.ecart_relatif))


def _trop_loin(
    ecartees: list[Candidate], *, distance_km: float, tolerance: float, plafond: float
) -> ErreurDistanceInatteignable:
    """Le refus, avec les chiffres qui le justifient — jamais un « réessayez ».

    L'écran d'échec (E18 · échec) doit pouvoir dire de combien il aurait fallu
    élargir : c'est ce qui transforme une impasse en levier chiffré.
    """
    meilleure = min(ecartees, key=lambda c: abs(c.ecart_relatif))
    obtenue_km = meilleure.trace.distance_m / 1000.0
    return ErreurDistanceInatteignable(
        f"aucune boucle à moins de {tolerance:.0%} de {distance_km:g} km : la plus proche "
        f"fait {obtenue_km:.1f} km ({meilleure.ecart_relatif:+.0%}), il aurait fallu élargir "
        f"de {meilleure.elargissement:.0%} et on s'arrête à {plafond:.0%} — essayer une autre "
        "distance, une autre direction ou un autre profil",
        distance_cible_km=distance_km,
        distance_obtenue_km=obtenue_km,
        ecart_relatif=meilleure.ecart_relatif,
        tolerance=tolerance,
        elargissement_requis=meilleure.elargissement,
        elargissement_max=plafond,
    )


def _borner(rayon_m: float) -> float:
    """Le rayon ramené dans `[RAYON_MIN_M, RAYON_MAX_M]`."""
    return min(max(rayon_m, RAYON_MIN_M), RAYON_MAX_M)
