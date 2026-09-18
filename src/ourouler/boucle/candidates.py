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
from ourouler.boucle.trace import Trace
from ourouler.config import Depart
from ourouler.connecteurs.brouter import ClientBrouter
from ourouler.erreurs import ErreurConnecteur, ErreurDistanceInatteignable, ErreurUtilisateur

#: Rapport de départ entre la longueur d'une boucle et le rayon demandé.
#: Point d'entrée de l'ajustement, pas une constante de vérité.
RAPPORT_RAYON_DEFAUT = 5.0

#: Écart entre deux azimuts essayés, de part et d'autre de la direction voulue.
PAS_AZIMUT_DEG = 20.0

#: Nombre d'ajustements de rayon par azimut, après le premier essai.
#:
#: Passé de 2 à 3 le 13/09/2026, décision du superviseur prise après la
#: vérification réelle. L'élagage des antennes (lot L3.1) retire des centaines
#: de mètres à la boucle rendue par le moteur : la distance mesurée oscille
#: alors d'une itération à l'autre — 53,6 km puis 65,4 km pour 60 km demandés
#: — et deux corrections s'arrêtaient au milieu de l'oscillation. Une
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
#: Mots du mainteneur (Q41 d, 17/09/2026) : « le mieux c'est de dire au user :
#: on n'a pas trouvé de boucle dans les contraintes, on a élargi de X %. Et on
#: incrémente de 5 % en 5 %. Comme ça on explique. »
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
    une opinion. Dans `generer`, `tolerance` ne sert qu'à décider quand
    *arrêter* d'affiner le rayon (`if abs(ecart) <= tolerance: break`) : elle
    ne filtre rien et n'oriente rien. Une tolérance plus large arrête donc
    l'affinage **plus tôt**, et ne peut rendre qu'une boucle égale ou pire.
    Élargir puis réessayer dépenserait des appels au serveur du mainteneur
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
    rien, ça substitue une autre sortie à celle qui était demandée. Mais le
    mainteneur a refusé qu'on invente un seuil pour le dire (Q41 d), et il a
    raison — un seuil inventé est un chiffre qu'on passe sa vie à défendre.

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
    que le mainteneur a demandé n'aurait jamais lieu d'être. **On ne refuse
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

    @property
    def tolerance_atteinte(self) -> float:
        """La bande qu'il a fallu accepter : `tolerance + elargissement`."""
        return self.tolerance + self.elargissement


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
    égal, la plus longue** — c'est l'arbitrage du mainteneur (18/09/2026),
    et c'est la même règle que le tri final entre azimuts, pour qu'un étage
    ne défasse pas ce que l'autre a choisi.
    """
    if longue is None or abs(longue.ecart_relatif) > tolerance:
        return courte
    if abs(longue.ecart_relatif) < abs(courte.ecart_relatif):
        return longue
    if abs(longue.ecart_relatif) > abs(courte.ecart_relatif):
        return courte
    # Écart égal : la préférence du mainteneur s'exprime ici, et ne coûte rien.
    return longue if longue.ecart_relatif > courte.ecart_relatif else courte


def generer(
    client: ClientBrouter,
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

    Pour chaque azimut : un premier essai au rayon `distance / 5`, puis au plus
    `AJUSTEMENTS_MAX` corrections par proportion (`rayon × cible / obtenu`)
    tant que l'écart dépasse `tolerance` — trois corrections depuis le
    13/09/2026, l'élagage des antennes faisant osciller la distance mesurée.
    Seules les boucles **bornées** sont retenues : un tracé qui ne revient pas
    au départ n'est pas une boucle.

    La correction est **bornée des deux côtés** : facteur dans
    `[FACTEUR_MIN, FACTEUR_MAX]`, rayon dans `[RAYON_MIN_M, RAYON_MAX_M]`. Une
    réponse qui force une borne est une réponse qu'on ne sait pas exploiter,
    pas une réponse à laquelle il faut insister : l'azimut est abandonné, avec
    sa meilleure tentative. Sans ces bornes, un moteur qui rend 100 m pour une
    cible de 60 km faisait demander 7 200 km puis 4,3 millions de kilomètres
    au serveur du mainteneur.

    Deux garde-fous, donc, et ils ne disent pas la même chose : `appels_max`
    borne le **nombre** d'appels au moteur, les bornes ci-dessus bornent leur
    **coût**. Par défaut, `appels_max` vaut `appels_pour(nb)` : le plafond
    suit la demande, pour que `nb = 5` rende bien cinq candidates même quand
    le moteur épuise ses ajustements sur chacune.

    **Une candidate hors tolérance est servie, mais elle le dit** (Q41 d,
    17/09/2026). Jusqu'à cette correction, `tolerance` ne servait qu'à
    *arrêter* la recherche : la meilleure tentative était retenue quoi qu'il
    arrive, avec son écart, **sans un mot**. Mesuré le 17/09/2026 sur le
    serveur du mainteneur : 2 km demandés, 2,69 km servis, soit +34,7 % pour
    une tolérance réglée à 10 %, et rien à l'écran ne le disait. Désormais
    chaque candidate porte `tolerance`, `elargissement` (de combien il a
    fallu élargir, par paliers de 5 %) et `hors_tolerance`.

    **À tolérance égale, on préfère dépasser la cible que rester en dessous**
    (mots du mainteneur, 18/09/2026 : « c'est con car c'est pas dur de faire
    10 bornes de plus »). Mesuré sur le serveur du mainteneur avant ce
    correctif : sur trois cibles (60, 100, 125 km) × 8 azimuts, 20 candidates
    sur 24 rendaient une boucle plus courte que la cible, médiane autour de
    −5 %, alors que la tolérance acceptait tout aussi bien un dépassement.
    Désormais, une candidate trouvée sous la cible mais déjà dans la
    tolérance ne fait pas sortir l'azimut tout de suite : une des corrections
    restantes est dépensée pour viser plus loin (la correction proportionnelle
    normale vise déjà plus long, puisque `cible_m / trace.distance_m > 1`
    sous la cible), et la plus longue des deux l'emporte **si elle tient
    elle aussi dans la bande** — sinon on revient à la première. Un seul essai
    de plus par azimut, jamais une relance. **Le plafond ne change pas**
    (`appels_pour` l'autorisait déjà), mais **le coût réel, lui, double à peu
    près** : le premier essai tombait court 20 fois sur 24, donc l'essai
    supplémentaire se déclenche presque toujours. Mesuré le 18/09/2026 sur le
    serveur du mainteneur, cibles 60/100/125 km : **1,67 à 2,38 appels par
    azimut** contre un seul auparavant, pour un plafond de 4 jamais approché.
    Dire « mieux dépensé » sans ce chiffre masquerait le coût (règle
    absolue 5). Une
    candidate déjà au-dessus de la cible, elle, n'est jamais retouchée : le
    biais ne joue que dans un sens.

    **Et au-delà d'un élargissement, on refuse plutôt que de servir.** Le
    plafond est `elargissement_max(tolerance)` — la tolérance elle-même,
    jamais moins d'un palier ; sa justification est dans sa docstring. Quand
    des boucles bornées ont été trouvées mais qu'aucune n'y tient, la
    `ErreurDistanceInatteignable` levée **porte les mesures** du refus, pour
    que l'écran d'échec dise de combien il aurait fallu élargir au lieu d'un
    « réessayez ». Un azimut hors plafond ne condamne pas les autres : le
    refus n'a lieu que si **aucune** candidate n'a tenu.

    Un azimut qui fait échouer le moteur (profil refusé sur une direction,
    panne passagère) ne fait pas perdre les autres : l'erreur est retenue et
    relancée seulement si **aucune** candidate n'a pu être produite.

    Chaque réponse du moteur est **élaguée de ses antennes** avant d'être
    mesurée (contrat §1) : les crochets que le mode boucle fabrique en allant
    chercher un point de passage tombé à côté de la route sont retirés, et
    `trace.meta["antennes"]` dit combien et combien de mètres. L'ajustement de
    rayon travaille donc sur la distance **réellement proposée au cycliste**,
    pas sur celle qui incluait l'aller-retour.

    Une `distance_km` qui n'est pas un nombre fini strictement positif et un
    `nb` inférieur à 1 sont des `ErreurUtilisateur` levées **avant** tout
    appel : sans cible, `ecart_relatif` ne veut rien dire (NaN), et sans
    candidate demandée il n'y a rien à chercher.
    """
    # Les deux refus tombent avant le premier appel : une entrée absurde ne
    # doit pas coûter un aller-retour sur le serveur BRouter du mainteneur.
    if not math.isfinite(distance_km) or distance_km <= 0:
        raise ErreurUtilisateur(
            f"distance_km = {distance_km} : une distance strictement positive est attendue "
            "(l'écart relatif vaut (distance − cible) / cible)"
        )
    if nb < 1:
        raise ErreurUtilisateur(f"nb = {nb} : au moins une candidate est attendue")
    appels_max = appels_max if appels_max is not None else appels_pour(nb)
    cible_m = distance_km * 1000.0
    appels = 0
    plafond = elargissement_max(tolerance)
    candidates: list[Candidate] = []
    trop_loin: list[Candidate] = []
    derniere_erreur: ErreurConnecteur | None = None

    for azimut in azimuts(azimut_deg, nb):
        rayon = _borner(cible_m / RAPPORT_RAYON_DEFAUT)
        meilleure: Candidate | None = None
        # Dès qu'une candidate tient dans la tolérance mais reste sous la
        # cible, elle est retenue ici et l'affinage n'est pas arrêté tout de
        # suite : une correction de plus (déjà prévue par la boucle, déjà
        # payée par `appels_pour`) vise plus loin, et seule celle-ci décide
        # entre les deux — voir le commentaire après la boucle.
        candidate_courte: Candidate | None = None
        for _ in range(1 + AJUSTEMENTS_MAX):
            if appels >= appels_max:
                break
            try:
                trace = client.boucle(
                    (depart.latitude, depart.longitude),
                    azimut_deg=azimut,
                    rayon_m=rayon,
                    profil=profil,
                )
            except ErreurConnecteur as e:
                derniere_erreur = e
                appels += 1
                break
            appels += 1
            trace = elaguer(trace, detecter(trace))
            ecart = (trace.distance_m - cible_m) / cible_m
            candidate = None
            if trace.bornee():
                candidate = Candidate(
                    trace=trace, azimut_deg=azimut, rayon_m=rayon, ecart_relatif=ecart
                )
                if meilleure is None or abs(ecart) < abs(meilleure.ecart_relatif):
                    meilleure = candidate

            if candidate_courte is not None:
                # **Arbitrage du mainteneur du 18/09/2026, et il a changé.**
                # La première écriture gardait toujours la plus longue des
                # deux dès qu'elle tenait dans la bande. Conséquence, montrée
                # avec ses chiffres : sur 125 km demandés, un premier essai à
                # 120 km (−4 %) et un second à 137 km (+9,9 %) faisaient
                # servir 137 — on s'éloignait de douze kilomètres de la
                # demande alors qu'on en avait cinq en main. Et la règle
                # contredisait le tri final entre azimuts, qui classe par
                # écart absolu : une candidate retenue *parce qu'*elle était
                # longue finissait dernière au classement, punie de ce qui
                # l'avait fait choisir.
                #
                # La règle retenue est donc **la plus proche de la cible, le
                # plus long départageant à écart égal**. Elle dit la
                # préférence du mainteneur là où elle ne coûte rien — un
                # choix entre −5 % et +5 % va vers le haut — et elle ne la
                # dit plus là où elle coûterait cher. Surtout, c'est la même
                # règle aux deux étages : plus de contradiction.
                #
                # Un seul essai de plus, jamais une relance : `palier` et
                # `elargissement_max` jugent ensuite le verdict final, pas
                # l'aller-retour qui l'a produit.
                meilleure = _plus_proche(candidate_courte, candidate, tolerance)
                break

            if abs(ecart) <= tolerance:
                if ecart < 0 and candidate is not None and appels < appels_max:
                    # Mots du mainteneur (18/09/2026) : « c'est con car c'est
                    # pas dur de faire 10 bornes de plus » — à tolérance
                    # égale, il préfère dépasser la cible que rester en
                    # dessous. On ne sert donc pas la première candidate sous
                    # la cible sans avoir essayé plus long : le facteur
                    # ci-dessous vaut déjà > 1 puisque `trace.distance_m` est
                    # sous `cible_m`, la correction naturelle vise donc plus
                    # loin sans code séparé.
                    candidate_courte = candidate
                else:
                    break
            if trace.distance_m <= 0:
                # Rien à corriger proportionnellement : insister coûterait des
                # appels pour le même résultat.
                break
            facteur = cible_m / trace.distance_m
            if not FACTEUR_MIN <= facteur <= FACTEUR_MAX:
                break  # correction hors de portée : on abandonne l'azimut
            suivant = rayon * facteur
            if not RAYON_MIN_M <= suivant <= RAYON_MAX_M:
                break  # le rayon sortirait de la plage exploitable
            rayon = suivant
        if meilleure is not None:
            # L'écart cesse d'être tu : il est jugé ici, une fois, et la
            # candidate emporte son verdict. Avant ce correctif, `tolerance`
            # ne servait qu'à arrêter l'affinage et la meilleure tentative
            # était servie quoi qu'il arrive, sans un mot — 2 km demandés,
            # 2,69 km servis (+34,7 %) sur le serveur du mainteneur, mesuré
            # le 17/09/2026.
            marche = palier(meilleure.ecart_relatif, tolerance)
            meilleure = replace(meilleure, tolerance=tolerance, elargissement=marche)
            if marche <= plafond:
                candidates.append(meilleure)
            else:
                trop_loin.append(meilleure)
        if appels >= appels_max:
            break

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
