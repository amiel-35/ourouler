"""Les trois valeurs liées de l'écran de FTP, et l'escalier qu'elles déplacent.

Décision 7 du cycle UX (`docs/journal/ux/cycle_ux_contrat.md`) : l'écran montre trois
valeurs, dont deux sont éditables et la troisième réconcilie.

| la puissance visée | éditable — pour qui pense en watts |
| la vitesse **à plat, sans vent, lancé** | éditable — pour tous les autres |
| la moyenne compteur attendue | **non éditable** — la réconciliation |

Éditer l'une recalcule les autres par le modèle physique ; ce qui est stocké
est la **position dans la zone**, jamais la valeur. Ce module fait ce
calcul-là, dans les deux sens, et il ne stocke rien : il reçoit le profil
du cycliste (`noyau.profil`) et le modèle physique du vélo déjà construit
(`ModeleVelo`), et rend des nombres.

Décision 8 : la troisième valeur est obligatoire, et **elle doit dire si son
facteur est mesuré ou supposé**. Un facteur supposé (`facteur_compteur_defaut`)
est dérivé d'une sortie de référence — 10 m de dénivelé par kilomètre, 5 %
d'arrêts — et non du cycliste qui regarde l'écran. C'est le seul chiffre de
cette famille qui ne soit pas une mesure, donc `facteur_mesure` existe et
tout écran qui affiche la valeur affiche aussi cette mention (on ne présente
jamais une estimation comme une mesure).

**Pas d'écrêtage.** Une position hors de [0, 1] se voit et se dit : quelqu'un
qui saisit sa moyenne compteur dans le champ « à plat » se retrouve *sous* sa
Z2, et c'est exactement ce que l'écran doit montrer plutôt que corriger en
silence (`seance.zones.position_dans_zone`).

Ce module ne lit aucun fichier de configuration et ne connaît aucun chemin :
les paramètres physiques du vélo (calibrés ou non) lui arrivent tout faits,
et c'est `seance.ecran_ftp`, la couche commande, qui lit la calibration
et la `Config` pour les construire — comme le reste du cœur (le cœur ne lit ni
configuration ni environnement).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from ourouler.noyau.erreurs import ErreurUtilisateur
from ourouler.noyau.profil import Cycliste, ParametresSeance, Velo
from ourouler.noyau.zones import ZONE_ENDURANCE, echelle, position_dans_zone, puissance_pct_ftp
from ourouler.physique.modele import (
    FourchettePorteAPorte,
    Parametres,
    facteur_compteur_defaut,
    moyenne_compteur_kmh,
    puissance_a_plat_w,
    vitesse_a_plat_kmh,
)


@dataclass(frozen=True)
class ModeleVelo:
    """Le vélo de l'écran et son modèle physique, tels que la couche commande les a lus.

    `provenance` : « calibration », « configuration », « littérature » ou
    « défaut » (`physique.parametres_velo.parametres_du_velo`).
    """

    velo: Velo
    parametres: Parametres
    provenance: str


def valeurs_liees(
    modele: ModeleVelo | None,
    cycliste: Cycliste,
    seance: ParametresSeance,
    *,
    position: float | None = None,
) -> dict | None:
    """Les trois valeurs, à la position donnée (défaut : celle de la configuration).

    `None` sans vélo (`modele` absent), **ou si le profil ne porte
    aucune FTP** (facultative, `docs/journal/ux/parcours_accueil.md`) : sans
    l'une ou l'autre, il n'y a ni modèle physique complet ni référence de
    puissance, donc rien à réconcilier. Un
    profil qui n'a pas encore franchi l'étage T3/T4 de l'accueil est dans ce
    cas — c'est un état normal, pas une panne.
    """
    if modele is None or cycliste.ftp_w is None:
        return None
    velo, parametres, provenance = modele.velo, modele.parametres, modele.provenance
    ou = seance.position_zone if position is None else position
    pct = puissance_pct_ftp(ou, ZONE_ENDURANCE, seance.zones_pct)
    if pct is None:  # pragma: no cover - table sans Z2 fermée, refusée au chargement
        raise ErreurUtilisateur(
            "zones : la table n'a pas de Z2 fermée, la puissance d'endurance ne s'en déduit pas"
        )
    puissance_w = pct * cycliste.ftp_w
    mesure = velo.facteur_compteur is not None
    facteur = velo.facteur_compteur if mesure else facteur_compteur_defaut(puissance_w, parametres)
    return {
        "velo": velo.nom,
        "modele_physique": provenance,
        "position_zone": round(ou, 6),
        "puissance_endurance_w": round(puissance_w, 1),
        "puissance_endurance_pct": round(pct, 6),
        "vitesse_a_plat_kmh": round(vitesse_a_plat_kmh(puissance_w, parametres), 1),
        "moyenne_compteur_kmh": round(moyenne_compteur_kmh(puissance_w, parametres, facteur), 1),
        "facteur_compteur": round(facteur, 3),
        # Décision 8 : mesuré sur l'historique du cycliste, ou dérivé d'une
        # sortie de référence supposée. L'écran doit le dire.
        "facteur_mesure": mesure,
        # **Le même fait, en un mot.** `facteur_mesure`
        # est un booléen : un écran qui le lit sait quoi en faire, un écran qui
        # l'ignore affiche une mesure et une supposition de la même façon —
        # « un mensonge par mise en page », dit la maquette de E9. Le mot
        # `provenance` est celui que `seance --json` emploie déjà pour les
        # vitesses ; le reprendre ici évite au front d'apprendre deux
        # vocabulaires pour la même question.
        "facteur_provenance": "mesure" if mesure else "suppose",
        "hors_bande": not 0.0 <= ou <= 1.0,
    }


def bloc_compteur(liees: dict, fourchette: FourchettePorteAPorte) -> dict:
    """Le bloc « compteur » que `boucle` et `sortie` publient, depuis les valeurs liées.

    Voir `seance.ecran_ftp.info_compteur`, qui choisit la position et lit la
    fourchette du porte à porte du vélo avant d'appeler cette mise en forme.
    """
    return {
        "velo": liees["velo"],
        # La puissance à laquelle `moyenne_compteur_kmh` a été calculée — sans
        # elle, un client ne peut pas savoir ce qu'il lit (on ne présente jamais
        # une estimation comme une mesure).
        "puissance_w": liees["puissance_endurance_w"],
        "moyenne_compteur_kmh": liees["moyenne_compteur_kmh"],
        "facteur_compteur": liees["facteur_compteur"],
        "facteur_provenance": liees["facteur_provenance"],
        # La fourchette qui chronomètre le porte à porte :
        # `temps_estime_s × [bas, haut]`. « mesure » : centiles mesurés sur les
        # sorties de ce vélo par `ourouler calibrer` ; « defaut » : la
        # convention de `physique.litterature`, mesurée sur un seul cycliste.
        "porte_a_porte": {
            "bas": fourchette.bas,
            "mediane": fourchette.mediane,
            "haut": fourchette.haut,
            "provenance": fourchette.provenance,
            "n": fourchette.n,
        },
    }


def verifier_une_seule_saisie(puissance_w: float | None, vitesse_kmh: float | None) -> None:
    """Une puissance ou une vitesse à plat, et une seule : sinon `ErreurUtilisateur`."""
    if (puissance_w is None) == (vitesse_kmh is None):
        raise ErreurUtilisateur(
            "écran de FTP : donner soit une puissance en watts, soit une vitesse à plat "
            "en km/h, et une seule des deux"
        )


def position_pour(
    cycliste: Cycliste,
    seance: ParametresSeance,
    *,
    puissance_w: float | None = None,
    vitesse_kmh: float | None = None,
    modele: ModeleVelo | None = None,
) -> float:
    """La position dans la Z2 que désigne une puissance, ou une vitesse à plat.

    C'est le chemin de retour de l'écran : le cycliste tape des watts ou des
    km/h, on en déduit **la seule chose qui sera stockée**.

    `vitesse_kmh` est la vitesse **à plat, sans vent, lancé** — jamais une
    moyenne de compteur. C'est toute la raison d'être de la troisième valeur
    (décision 8), et l'API le redit dans le nom du champ. Elle ne se convertit
    qu'avec le modèle physique d'un vélo (`modele`).
    """
    verifier_une_seule_saisie(puissance_w, vitesse_kmh)
    if vitesse_kmh is not None:
        if modele is None:
            raise ErreurUtilisateur(
                "écran de FTP : une vitesse ne se convertit en puissance qu'avec un vélo — "
                "aucun [[velos]] dans la configuration"
            )
        puissance_w = puissance_a_plat_w(vitesse_kmh, modele.parametres)
    if cycliste.ftp_w is None:
        raise ErreurUtilisateur(
            "écran de FTP : aucune FTP renseignée — il n'y a pas encore d'échelle de "
            "zones dans laquelle situer une position (T3 de l'accueil : donner une FTP, "
            "ou T4 : partir d'une vitesse au compteur avec `ftp_pour_vitesse_compteur`)"
        )
    if cycliste.ftp_w <= 0:  # pragma: no cover - refusé au chargement
        raise ErreurUtilisateur("écran de FTP : FTP positive attendue")
    position = position_dans_zone(puissance_w / cycliste.ftp_w, ZONE_ENDURANCE, seance.zones_pct)
    if position is None:  # pragma: no cover - table sans Z2 fermée, refusée au chargement
        raise ErreurUtilisateur("zones : la table n'a pas de Z2 fermée")
    return position


def rendu(
    modele: ModeleVelo | None,
    cycliste: Cycliste,
    seance: ParametresSeance,
    *,
    position: float | None = None,
) -> dict:
    """Tout ce que l'écran de FTP affiche, pour une position donnée.

    L'escalier complet en watts (`seance.zones.echelle`), les trois valeurs
    liées, et la position. Une FTP qui bouge de 12 W déplace l'escalier
    entier sans qu'aucun réglage ne change — c'est le point de la décision 7,
    et c'est pourquoi rien ici n'est stocké en watts.

    **Sans FTP** (elle est facultative) : il n'y a pas d'échelle
    en watts à calculer — `echelle` l'exige, à raison, une bande de zones
    sans référence ne veut rien dire. `zones` et `valeurs_liees` rendent
    alors respectivement une liste vide et `None`, `ftp_w` reste `None`, et
    la position elle-même reste rendue : elle ne dépend pas de la FTP, et
    c'est ce qui permet à un front de continuer à afficher où la personne se
    place dans sa bande, même avant l'étage qui lui donne des watts.
    """
    ou = seance.position_zone if position is None else position
    if cycliste.ftp_w is None:
        return {
            "ftp_w": None,
            "position_zone": round(ou, 6),
            "zone_endurance": ZONE_ENDURANCE,
            "hors_bande": not 0.0 <= ou <= 1.0,
            "zones": [],
            "valeurs_liees": None,
        }
    paliers = echelle(ou, cycliste.ftp_w, seance.zones_pct)
    return {
        "ftp_w": cycliste.ftp_w,
        "position_zone": round(ou, 6),
        "zone_endurance": ZONE_ENDURANCE,
        "hors_bande": not 0.0 <= ou <= 1.0,
        "zones": [
            {
                "numero": p.numero,
                "bas_w": round(p.bas_w, 1),
                "haut_w": round(p.haut_w, 1),
                "puissance_w": None if p.puissance_w is None else round(p.puissance_w, 1),
                "ouverte": p.ouverte,
                "bas_pct": seance.zones_pct[p.numero - 1][0],
                "haut_pct": seance.zones_pct[p.numero - 1][1],
            }
            for p in paliers
        ],
        "valeurs_liees": valeurs_liees(modele, cycliste, seance, position=ou),
    }


# --- T4 de l'accueil : vitesse au compteur + terrain → une FTP ---------------
#
# `docs/journal/ux/parcours_accueil.md` §5.2-6 : on ne demande pas « à quelle vitesse
# roulez-vous à plat, sans vent » — personne ne sait répondre à une question sur
# des conditions qui n'arrivent jamais —
# mais la moyenne réellement lue sur le compteur, une vraie expérience, plus
# un terrain déclaré. La conversion retenue réutilise `facteur_compteur_defaut`
# tel quel, en lui donnant le dénivelé du terrain choisi au lieu du seul
# défaut plat qu'il servait jusqu'ici (`DENIVELE_REFERENCE_M_PAR_KM`) — un
# levier qui existait déjà dans le modèle physique sans qu'aucun écran ne
# s'en serve.

#: Bornes de la bissection qui retrouve la puissance depuis une vitesse
#: compteur. 1 W en bas : `facteur_compteur_defaut` refuse une puissance
#: nulle ou négative. 2000 W en haut : la même borne que `ApercuZones.
#: puissance_w` côté API — au-delà, ce n'est plus un chiffre qu'une sortie
#: solo peut produire.
PUISSANCE_MINI_BISSECTION_W = 1.0
PUISSANCE_MAXI_BISSECTION_W = 2000.0

#: Tolérance de la bissection, en watts — largement sous le dixième affiché.
TOLERANCE_PUISSANCE_W = 0.01

#: Garde-fou d'itérations — jamais atteint sur la plage utile ci-dessus
#: (log2(2000/0,01) ≈ 18), posé pour ne jamais boucler indéfiniment.
MAX_ITERATIONS_BISSECTION = 100


def verifier_saisie_compteur(vitesse_compteur_kmh: float, denivele_m_par_km: float) -> None:
    """Une vitesse au compteur et un dénivelé plausibles : sinon `ErreurUtilisateur`."""
    if not math.isfinite(vitesse_compteur_kmh) or vitesse_compteur_kmh <= 0:
        raise ErreurUtilisateur("écran de FTP : vitesse au compteur positive attendue")
    if not math.isfinite(denivele_m_par_km) or denivele_m_par_km < 0:
        raise ErreurUtilisateur("écran de FTP : dénivelé de terrain positif attendu")


def ftp_pour_vitesse_compteur(
    modele: ModeleVelo | None,
    seance: ParametresSeance,
    *,
    vitesse_compteur_kmh: float,
    denivele_m_par_km: float,
) -> float:
    """La FTP que désigne une vitesse au compteur et un terrain déclarés (T4).

    La vitesse au compteur représente une sortie d'endurance ordinaire — la
    même hypothèse que portait l'ancienne question « à plat, sans vent »
    (décision 8 du cycle UX). Elle est donc traitée comme la **puissance
    d'endurance** du cycliste : on en déduit la puissance (par bissection sur
    `physique.modele.moyenne_compteur_kmh`, avec le facteur par défaut au
    dénivelé du terrain déclaré, `facteur_compteur_defaut`), puis on remonte à
    la FTP en la rapportant à `position_zone` — **la position déjà en
    vigueur dans la configuration**, jamais recalculée ici : cette fonction
    établit une FTP là où il n'y en avait pas, elle ne repositionne rien
    d'autre. C'est symétrique de `valeurs_liees`, qui fait le calcul inverse
    (`puissance_w = pct * ftp_w`).

    Ni le facteur compteur ni le terrain ne sont mesurés sur ce cycliste :
    c'est une **supposition**, du même ordre que `facteur_compteur_defaut`
    l'est déjà pour tout vélo neuf — voir `docs/journal/ux/parcours_accueil.md` §6
    pour ce que chaque terrain vaut en `denivele_m_par_km`, et pourquoi la
    case « Montagne » y est signalée moins fiable que les trois autres.

    Ne stocke rien : l'appelant récupère la FTP rendue et l'envoie à
    `PATCH /profil` (`cycliste.ftp_w`) comme n'importe quelle FTP déclarée.
    """
    verifier_saisie_compteur(vitesse_compteur_kmh, denivele_m_par_km)
    if modele is None:
        raise ErreurUtilisateur(
            "écran de FTP : une vitesse au compteur ne se convertit en FTP qu'avec un "
            "vélo — aucun [[velos]] dans la configuration"
        )
    puissance_endurance_w = _puissance_pour_moyenne_compteur(
        vitesse_compteur_kmh, modele.parametres, denivele_m_par_km=denivele_m_par_km
    )
    pct = puissance_pct_ftp(seance.position_zone, ZONE_ENDURANCE, seance.zones_pct)
    if pct is None or pct <= 0:  # pragma: no cover - table sans Z2 fermée, refusée au chargement
        raise ErreurUtilisateur(
            "zones : la table n'a pas de Z2 fermée, ou sa borne basse est nulle — "
            "impossible d'en déduire une FTP"
        )
    return puissance_endurance_w / pct


def _puissance_pour_moyenne_compteur(
    vitesse_compteur_kmh: float, parametres: Parametres, *, denivele_m_par_km: float
) -> float:
    """La puissance dont `moyenne_compteur_kmh` (facteur par défaut, à ce dénivelé) vaut
    `vitesse_compteur_kmh` — l'inverse de `physique.modele.moyenne_compteur_kmh`
    composé avec `facteur_compteur_defaut`, par bissection : il n'y a pas de forme
    fermée, `facteur_compteur_defaut` fait lui-même deux bissections.

    Croissante en puissance sur toute la plage utile — une puissance plus
    grande ne peut pas rendre une moyenne plus basse dans ce modèle — donc la
    racine, si elle existe dans la plage bornée, est unique.
    """

    def ecart(p_w: float) -> float:
        facteur = facteur_compteur_defaut(p_w, parametres, denivele_m_par_km=denivele_m_par_km)
        return moyenne_compteur_kmh(p_w, parametres, facteur) - vitesse_compteur_kmh

    bas, haut = PUISSANCE_MINI_BISSECTION_W, PUISSANCE_MAXI_BISSECTION_W
    if ecart(haut) < 0:
        # Même une puissance de sprint ne suffit pas à expliquer la vitesse
        # déclarée à ce dénivelé — une saisie incohérente (montagne à 45 km/h
        # de moyenne compteur, par exemple), pas un cas que le modèle doit
        # deviner.
        raise ErreurUtilisateur(
            f"écran de FTP : {vitesse_compteur_kmh:g} km/h de moyenne compteur ne "
            "correspond à aucune puissance plausible pour ce terrain — vérifier la "
            "vitesse ou le terrain déclarés"
        )
    if ecart(bas) > 0:
        return bas
    for _ in range(MAX_ITERATIONS_BISSECTION):
        if haut - bas <= TOLERANCE_PUISSANCE_W:
            break
        milieu = (bas + haut) / 2
        if ecart(milieu) > 0:
            haut = milieu
        else:
            bas = milieu
    return (bas + haut) / 2


__all__ = [
    "MAX_ITERATIONS_BISSECTION",
    "PUISSANCE_MAXI_BISSECTION_W",
    "PUISSANCE_MINI_BISSECTION_W",
    "TOLERANCE_PUISSANCE_W",
    "ModeleVelo",
    "bloc_compteur",
    "ftp_pour_vitesse_compteur",
    "position_pour",
    "rendu",
    "valeurs_liees",
    "verifier_saisie_compteur",
    "verifier_une_seule_saisie",
]
