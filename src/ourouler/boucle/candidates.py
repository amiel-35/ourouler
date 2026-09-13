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
from dataclasses import dataclass

from ourouler.boucle.antennes import detecter, elaguer
from ourouler.boucle.trace import Trace
from ourouler.config import Depart
from ourouler.connecteurs.brouter import ClientBrouter
from ourouler.erreurs import ErreurConnecteur, ErreurUtilisateur

#: Rapport de départ entre la longueur d'une boucle et le rayon demandé.
#: Point d'entrée de l'ajustement, pas une constante de vérité.
RAPPORT_RAYON_DEFAUT = 5.0

#: Écart entre deux azimuts essayés, de part et d'autre de la direction voulue.
PAS_AZIMUT_DEG = 20.0

#: Nombre d'ajustements de rayon par azimut, après le premier essai.
AJUSTEMENTS_MAX = 2

#: Bornes du facteur de correction d'une itération à la suivante. Diviser ou
#: multiplier le rayon par plus de 4 d'un coup, c'est croire une réponse que
#: le moteur ne sait manifestement pas rattacher au rayon demandé (boucle de
#: 100 m pour une cible de 60 km).
FACTEUR_MIN, FACTEUR_MAX = 0.25, 4.0

#: Bornes du rayon lui-même. En dessous de 500 m, aucun moteur ne rend une
#: boucle exploitable ; au-delà de 200 km, on demande à un serveur
#: auto-hébergé un calcul qui n'a plus de sens pour une sortie à vélo.
RAYON_MIN_M, RAYON_MAX_M = 500.0, 200_000.0


@dataclass
class Candidate:
    trace: Trace
    azimut_deg: float
    rayon_m: float
    ecart_relatif: float  # (distance − cible) / cible


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


def generer(
    client: ClientBrouter,
    depart: Depart,
    *,
    distance_km: float,
    azimut_deg: float,
    nb: int,
    tolerance: float,
    profil: str | None = None,
    appels_max: int = 12,
) -> list[Candidate]:
    """Jusqu'à `nb` boucles autour de `azimut_deg`, triées par écart à la distance voulue.

    Pour chaque azimut : un premier essai au rayon `distance / 5`, puis au plus
    `AJUSTEMENTS_MAX` corrections par proportion (`rayon × cible / obtenu`)
    tant que l'écart dépasse `tolerance`. Seules les boucles **bornées** sont
    retenues : un tracé qui ne revient pas au départ n'est pas une boucle.

    La correction est **bornée des deux côtés** : facteur dans
    `[FACTEUR_MIN, FACTEUR_MAX]`, rayon dans `[RAYON_MIN_M, RAYON_MAX_M]`. Une
    réponse qui force une borne est une réponse qu'on ne sait pas exploiter,
    pas une réponse à laquelle il faut insister : l'azimut est abandonné, avec
    sa meilleure tentative. Sans ces bornes, un moteur qui rend 100 m pour une
    cible de 60 km faisait demander 7 200 km puis 4,3 millions de kilomètres
    au serveur du mainteneur.

    Deux garde-fous, donc, et ils ne disent pas la même chose : `appels_max`
    borne le **nombre** d'appels au moteur, les bornes ci-dessus bornent leur
    **coût**. Si aucune candidate n'entre dans la tolérance, les meilleures
    sont rendues quand même — l'utilisateur juge mieux sur des chiffres que
    sur du vide.

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
    cible_m = distance_km * 1000.0
    appels = 0
    candidates: list[Candidate] = []
    derniere_erreur: ErreurConnecteur | None = None

    for azimut in azimuts(azimut_deg, nb):
        rayon = _borner(cible_m / RAPPORT_RAYON_DEFAUT)
        meilleure: Candidate | None = None
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
            if trace.bornee() and (meilleure is None or abs(ecart) < abs(meilleure.ecart_relatif)):
                meilleure = Candidate(
                    trace=trace, azimut_deg=azimut, rayon_m=rayon, ecart_relatif=ecart
                )
            if abs(ecart) <= tolerance:
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
            candidates.append(meilleure)
        if appels >= appels_max:
            break

    if not candidates and derniere_erreur is not None:
        raise derniere_erreur
    return sorted(candidates, key=lambda c: abs(c.ecart_relatif))


def _borner(rayon_m: float) -> float:
    """Le rayon ramené dans `[RAYON_MIN_M, RAYON_MAX_M]`."""
    return min(max(rayon_m, RAYON_MIN_M), RAYON_MAX_M)
