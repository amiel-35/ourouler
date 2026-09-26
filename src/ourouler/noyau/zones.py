"""La position du cycliste dans sa zone, et ce qu'elle vaut en watts.

Décision 7 du cycle UX (`docs/journal/ux/cycle_ux_contrat.md`) : **on stocke la
position dans la zone, jamais la valeur** : si la FTP change ou si les
zones se décalent, la position suit. Une FTP qui progresse de 12 W
déplace tout l'escalier sans qu'on touche à un réglage ; une puissance figée
en watts, elle, aurait recréé la dette qu'on retire ici — une valeur posée à
côté d'une table qui bouge.

**Ce que ce module remplace.** Le code portait deux définitions de « la Z2 »
qui n'étaient pas d'accord : la table `ZONES_PUISSANCE_DEFAUT` (56-75 % de
FTP) et `puissance_endurance_pct` (0,60), à deux endroits sans rien entre
eux. Désormais une seule donnée est stockée — la position — et
`puissance_endurance_pct` en est une **conséquence** :

    puissance_endurance_pct = bas(Z2) + position × (haut(Z2) − bas(Z2))

Avec la table par défaut, la position qui rend 0,60 vaut 0,2105
(`POSITION_ENDURANCE_DEFAUT`). C'est le défaut du projet, précisément pour
que rien ne bouge : 0,60 est la **médiane mesurée** sur les sorties
extérieures réelles (décision Q11, `docs/journal/questions/questions_mainteneur.md`), et une mesure ne se
remplace pas par une valeur ronde.

**Les zones ouvertes.** La première zone part de 0 et la dernière n'a pas de
haut fini : la table leur donne bien deux nombres (0,00-0,55 et 1,51-2,00)
mais ce sont des conventions d'écriture, pas des bornes que quelqu'un a
roulées. « Le milieu de la Z1 » vaut 27,5 % de FTP — du pédalage à vide — et
« le milieu de la Z7 » n'a pas davantage de sens. Une position n'y veut donc
rien dire, et les deux fonctions de conversion rendent `None` plutôt qu'un
chiffre faux (`zone_ouverte`). La propagation de la décision 7 — « qui se met
au milieu de sa Z2 prend le milieu de sa Z3 et de sa Z4 » — porte sur les
zones fermées, et sur elles seules.

**Les zones de FC ne sont pas les zones de puissance de même numéro.** Ce
module ne parle que de **puissance** : `ZONE_ENDURANCE = 2` désigne la Z2 de
la table des zones de puissance. Une consigne donnée en zone de fréquence
cardiaque se traduit ailleurs (`seance/intervals.py`), et c'est justement
parce que la correspondance de numéros est fausse dans le bas que les zones
de FC basses visent la puissance d'endurance dérivée ici.

Ce module ne lit aucun fichier et ne connaît aucune configuration : la table
et la position lui sont passées.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from ourouler.noyau.erreurs import ErreurUtilisateur
from ourouler.noyau.seance import PUISSANCE_ENDURANCE_PCT_DEFAUT, ZONES_PUISSANCE_DEFAUT

#: Numéro (1-based) de la zone de **puissance** qui porte l'endurance, et dans
#: laquelle le cycliste se place sur l'écran de FTP. Ce n'est pas un numéro de
#: zone de fréquence cardiaque : voir la docstring du module.
ZONE_ENDURANCE = 2

#: Décimales conservées sur une part de FTP dérivée d'une position.
#:
#: 10⁻⁶ de FTP vaut moins de 0,001 W pour n'importe quelle FTP de cycliste :
#: l'arrondi n'est pas une approximation du modèle, c'est ce qui garantit
#: qu'une valeur saisie, convertie en position puis reconvertie, revienne
#: exactement à elle-même — sans quoi `0,60` pourrait ressortir en
#: `0,6000000000000001` et une configuration migrée n'aurait plus l'air
#: d'être la même.
DECIMALES_PCT = 6


def _fini(valeur: float, nom: str) -> float:
    try:
        nombre = float(valeur)
    except (TypeError, ValueError) as e:
        raise ErreurUtilisateur(f"zones : {nom} — nombre attendu, reçu {valeur!r}") from e
    if not math.isfinite(nombre):
        raise ErreurUtilisateur(f"zones : {nom} — nombre fini attendu, reçu {valeur!r}")
    return nombre


def bornes_zone(
    numero: int, zones: tuple[tuple[float, float], ...] = ZONES_PUISSANCE_DEFAUT
) -> tuple[float, float]:
    """Les bornes (bas, haut) de la zone `numero`, en fraction de FTP.

    `numero` est 1-based comme il s'écrit : Z1 est `numero = 1`.
    """
    if not isinstance(numero, int) or isinstance(numero, bool):
        raise ErreurUtilisateur(f"zones : numéro de zone entier attendu, reçu {numero!r}")
    if not 1 <= numero <= len(zones):
        raise ErreurUtilisateur(
            f"zones : Z{numero} n'existe pas — la table en compte {len(zones)}"
        )
    return zones[numero - 1]


def zone_ouverte(
    numero: int, zones: tuple[tuple[float, float], ...] = ZONES_PUISSANCE_DEFAUT
) -> bool:
    """Vrai pour la première et la dernière zone de la table.

    La première est ouverte vers le bas (son 0 est le pédalage à vide, pas une
    borne roulée), la dernière vers le haut (aucun sprint ne plafonne à
    151-200 % de FTP parce qu'une table l'écrit). Une position dans l'une ou
    l'autre ne veut rien dire. Le critère est **positionnel** : il vaut pour
    n'importe quelle table, y compris une table de zones configurée par
    l'utilisateur qui n'en compterait pas sept.
    """
    return numero <= 1 or numero >= len(zones)


def puissance_pct_ftp(
    position: float,
    numero: int = ZONE_ENDURANCE,
    zones: tuple[tuple[float, float], ...] = ZONES_PUISSANCE_DEFAUT,
) -> float | None:
    """La puissance visée dans la zone `numero`, en fraction de FTP.

    `position` vaut 0 au bas de la bande et 1 en haut ; le milieu de la zone
    est 0,5. C'est ici que se fait la **propagation** de la décision 7 : la
    même position sert pour toutes les zones fermées.

    Rend `None` pour une zone ouverte (`zone_ouverte`) : mieux vaut un trou
    assumé à l'écran qu'un chiffre que personne ne peut tenir.
    """
    bas, haut = bornes_zone(numero, zones)
    if zone_ouverte(numero, zones):
        return None
    valeur = _fini(position, "position") * (haut - bas) + bas
    return round(valeur, DECIMALES_PCT)


def position_dans_zone(
    pct_ftp: float,
    numero: int = ZONE_ENDURANCE,
    zones: tuple[tuple[float, float], ...] = ZONES_PUISSANCE_DEFAUT,
) -> float | None:
    """La position qu'occupe `pct_ftp` dans la zone `numero`. L'inverse de
    `puissance_pct_ftp`.

    **Le résultat n'est pas ramené dans [0, 1], et c'est voulu.** Décision 8 :
    quelqu'un qui saisit sa moyenne compteur au lieu de sa vitesse à plat se
    retrouve *sous* sa Z2 — 0,508 × FTP donne ici −0,274, soit « à −27 % de la
    bande », exactement le chiffre qu'il faut rapporter. Un écrêtage aurait
    masqué la faute au lieu de la montrer, et l'écran doit pouvoir la dire.

    Rend `None` pour une zone ouverte, pour la même raison que
    `puissance_pct_ftp`.
    """
    bas, haut = bornes_zone(numero, zones)
    if zone_ouverte(numero, zones):
        return None
    largeur = haut - bas
    if largeur <= 0:
        # Une bande de largeur nulle n'a pas d'intérieur : aucune position
        # ne la décrit. La configuration refuse déjà une telle table ; cette
        # garde protège les appels directs.
        return None
    return (_fini(pct_ftp, "pct_ftp") - bas) / largeur


def puissance_endurance_pct(
    position: float, zones: tuple[tuple[float, float], ...] = ZONES_PUISSANCE_DEFAUT
) -> float:
    """La puissance d'endurance, en fraction de FTP — **dérivée**, plus stockée.

    C'est la cible des étapes prescrites en zone de fréquence cardiaque basse
    (`seance/intervals.py`). Elle n'est plus un réglage depuis la décision 7 :
    elle se lit dans la Z2 de la table, à la position du cycliste.
    """
    valeur = puissance_pct_ftp(position, ZONE_ENDURANCE, zones)
    if valeur is None:
        # N'arrive qu'avec une table de moins de trois zones, que la
        # configuration refuse au chargement.
        raise ErreurUtilisateur(
            f"zones : la table n'a pas de Z{ZONE_ENDURANCE} fermée, "
            "la puissance d'endurance ne peut pas en être déduite"
        )
    return valeur


def position_endurance(
    pct_ftp: float, zones: tuple[tuple[float, float], ...] = ZONES_PUISSANCE_DEFAUT
) -> float:
    """La position qu'occupe une puissance d'endurance donnée dans la Z2.

    C'est le chemin de migration d'une configuration écrite avant la
    décision 7 : elle portait une valeur, on en fait une position.
    """
    valeur = position_dans_zone(pct_ftp, ZONE_ENDURANCE, zones)
    if valeur is None:
        raise ErreurUtilisateur(
            f"zones : la table n'a pas de Z{ZONE_ENDURANCE} fermée, "
            "une puissance d'endurance ne peut pas y être située"
        )
    return valeur


#: Position par défaut du cycliste dans sa bande.
#:
#: Ce n'est pas un chiffre choisi : c'est la position qu'occupe la puissance
#: d'endurance **mesurée** (0,60 de FTP, décision Q11) dans la Z2 de la table par
#: défaut, soit 0,2105. Le défaut est posé ainsi pour que la dérivation ne
#: change aucun comportement observable : `puissance_endurance_pct(
#: POSITION_ENDURANCE_DEFAUT)` rend exactement 0,60.
POSITION_ENDURANCE_DEFAUT = position_endurance(
    PUISSANCE_ENDURANCE_PCT_DEFAUT, ZONES_PUISSANCE_DEFAUT
)


@dataclass(frozen=True)
class Palier:
    """Une zone, telle que l'écran de FTP la montre.

    `puissance_w` vaut `None` pour une zone ouverte : il n'y a pas de cible à
    y viser, et la case reste vide plutôt que de porter un chiffre inventé.
    """

    numero: int
    bas_w: float
    haut_w: float
    puissance_w: float | None
    ouverte: bool


def echelle(
    position: float,
    ftp_w: float,
    zones: tuple[tuple[float, float], ...] = ZONES_PUISSANCE_DEFAUT,
) -> tuple[Palier, ...]:
    """Tout l'escalier en watts pour une FTP et une position données.

    C'est la vue dont l'écran de FTP a besoin : les bornes de chaque zone, et
    la cible que la position y désigne. Une FTP qui bouge de 12 W déplace
    l'escalier entier sans qu'aucun réglage ne change — c'est le point de la
    décision 7.
    """
    ftp = _fini(ftp_w, "ftp_w")
    if ftp <= 0:
        raise ErreurUtilisateur(f"zones : FTP positive attendue, reçu {ftp_w!r}")
    paliers = []
    for numero in range(1, len(zones) + 1):
        bas, haut = bornes_zone(numero, zones)
        pct = puissance_pct_ftp(position, numero, zones)
        paliers.append(
            Palier(
                numero=numero,
                bas_w=bas * ftp,
                haut_w=haut * ftp,
                puissance_w=None if pct is None else pct * ftp,
                ouverte=zone_ouverte(numero, zones),
            )
        )
    return tuple(paliers)


__all__ = [
    "DECIMALES_PCT",
    "POSITION_ENDURANCE_DEFAUT",
    "ZONE_ENDURANCE",
    "Palier",
    "bornes_zone",
    "echelle",
    "position_dans_zone",
    "position_endurance",
    "puissance_endurance_pct",
    "puissance_pct_ftp",
    "zone_ouverte",
]
