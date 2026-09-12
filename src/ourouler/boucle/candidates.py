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

from dataclasses import dataclass

from ourouler.boucle.trace import Trace
from ourouler.config import Depart
from ourouler.connecteurs.brouter import ClientBrouter
from ourouler.erreurs import ErreurConnecteur

#: Rapport de départ entre la longueur d'une boucle et le rayon demandé.
#: Point d'entrée de l'ajustement, pas une constante de vérité.
RAPPORT_RAYON_DEFAUT = 5.0

#: Écart entre deux azimuts essayés, de part et d'autre de la direction voulue.
PAS_AZIMUT_DEG = 20.0

#: Nombre d'ajustements de rayon par azimut, après le premier essai.
AJUSTEMENTS_MAX = 2


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

    Le total d'appels au moteur est plafonné par `appels_max` : c'est la seule
    garantie que la commande finit en un temps borné, quel que soit le terrain.
    Si aucune candidate n'entre dans la tolérance, les meilleures sont rendues
    quand même — l'utilisateur juge mieux sur des chiffres que sur du vide.

    Un azimut qui fait échouer le moteur (profil refusé sur une direction,
    panne passagère) ne fait pas perdre les autres : l'erreur est retenue et
    relancée seulement si **aucune** candidate n'a pu être produite.
    """
    if distance_km <= 0:
        raise ErreurConnecteur(f"boucle : distance de {distance_km} km, une distance positive attendue")
    cible_m = distance_km * 1000.0
    appels = 0
    candidates: list[Candidate] = []
    derniere_erreur: ErreurConnecteur | None = None

    for azimut in azimuts(azimut_deg, max(1, nb)):
        rayon = cible_m / RAPPORT_RAYON_DEFAUT
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
            rayon *= cible_m / trace.distance_m
        if meilleure is not None:
            candidates.append(meilleure)
        if appels >= appels_max:
            break

    if not candidates and derniere_erreur is not None:
        raise derniere_erreur
    return sorted(candidates, key=lambda c: abs(c.ecart_relatif))
