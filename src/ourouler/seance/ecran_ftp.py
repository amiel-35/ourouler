"""Les trois valeurs liées de l'écran de FTP, et l'escalier qu'elles déplacent.

Décision 7 du cycle UX (`docs/journal/ux/cycle_ux_contrat.md`) : l'écran montre trois
valeurs, dont deux sont éditables et la troisième réconcilie.

| la puissance visée | éditable — pour qui pense en watts |
| la vitesse **à plat, sans vent, lancé** | éditable — pour tous les autres |
| la moyenne compteur attendue | **non éditable** — la réconciliation |

Éditer l'une recalcule les autres par le modèle physique ; ce qui est stocké
est la **position dans la zone**, jamais la valeur. Ce module fait ce
calcul-là, dans les deux sens, et il ne stocke rien : il reçoit une `Config`
et rend des nombres.

Décision 8 : la troisième valeur est obligatoire, et **elle doit dire si son
facteur est mesuré ou supposé**. Un facteur supposé (`facteur_compteur_defaut`)
est dérivé d'une sortie de référence — 10 m de dénivelé par kilomètre, 5 %
d'arrêts — et non du cycliste qui regarde l'écran. C'est le seul chiffre de
cette famille qui ne soit pas une mesure, donc `facteur_mesure` existe et
tout écran qui affiche la valeur affiche aussi cette mention (règle absolue 5).

**Pas d'écrêtage.** Une position hors de [0, 1] se voit et se dit : quelqu'un
qui saisit sa moyenne compteur dans le champ « à plat » se retrouve *sous* sa
Z2, et c'est exactement ce que l'écran doit montrer plutôt que corriger en
silence (`seance.zones.position_dans_zone`).

Ce module ne lit aucun fichier de configuration et ne connaît aucun chemin :
il reçoit la `Config` et, pour la calibration, le chemin que l'appelant a
résolu — comme le reste du cœur (règle absolue 2).
"""

from __future__ import annotations

import math

from ourouler.config import Config
from ourouler.noyau.erreurs import ErreurUtilisateur
from ourouler.noyau.profil import Velo
from ourouler.noyau.zones import ZONE_ENDURANCE, echelle, position_dans_zone, puissance_pct_ftp
from ourouler.physique.commande import (
    chemin_calibration,
    fourchette_du_velo,
    parametres_du_velo,
    velo_demande,
)
from ourouler.physique.modele import (
    Parametres,
    facteur_compteur_defaut,
    moyenne_compteur_kmh,
    puissance_a_plat_w,
    vitesse_a_plat_kmh,
)


def contexte(config: Config, nom_velo: str | None = None) -> tuple[Velo, Parametres, str] | None:
    """(vélo, paramètres physiques, provenance du modèle), ou `None` sans vélo.

    `None` et non une exception : `ourouler config` doit rester utilisable
    sur une configuration sans `[[velos]]`, et l'écran de FTP doit pouvoir
    afficher la puissance sans la vitesse.
    """
    if not config.velos:
        return None
    velo = velo_demande(config, nom_velo)
    parametres, provenance = parametres_du_velo(config, velo, chemin_calibration(config))
    return (velo, parametres, provenance)


def valeurs_liees(
    config: Config,
    nom_velo: str | None = None,
    *,
    position: float | None = None,
) -> dict | None:
    """Les trois valeurs, à la position donnée (défaut : celle de la configuration).

    `None` si la configuration ne porte aucun vélo, **ou si elle ne porte
    aucune FTP** (facultative depuis le 19/09/2026, `docs/ux/
    parcours_accueil.md`) : sans l'une ou l'autre, il n'y a ni modèle
    physique complet ni référence de puissance, donc rien à réconcilier. Un
    profil qui n'a pas encore franchi l'étage T3/T4 de l'accueil est dans ce
    cas — c'est un état normal, pas une panne.
    """
    trouve = contexte(config, nom_velo)
    if trouve is None or config.cycliste.ftp_w is None:
        return None
    velo, parametres, provenance = trouve
    ou = config.seance.position_zone if position is None else position
    pct = puissance_pct_ftp(ou, ZONE_ENDURANCE, config.seance.zones_pct)
    if pct is None:  # pragma: no cover - table sans Z2 fermée, refusée au chargement
        raise ErreurUtilisateur(
            "zones : la table n'a pas de Z2 fermée, la puissance d'endurance ne s'en déduit pas"
        )
    puissance_w = pct * config.cycliste.ftp_w
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
        # **Le même fait, en un mot** (ajouté le 17/09/2026). `facteur_mesure`
        # est un booléen : un écran qui le lit sait quoi en faire, un écran qui
        # l'ignore affiche une mesure et une supposition de la même façon —
        # « un mensonge par mise en page », dit la maquette de E9. Le mot
        # `provenance` est celui que `seance --json` emploie déjà pour les
        # vitesses ; le reprendre ici évite au front d'apprendre deux
        # vocabulaires pour la même question.
        "facteur_provenance": "mesure" if mesure else "suppose",
        "hors_bande": not 0.0 <= ou <= 1.0,
    }


def info_compteur(
    config: Config,
    nom_velo: str | None = None,
    *,
    puissance_w: float | None = None,
    vitesse_a_plat_kmh: float | None = None,
) -> dict | None:
    """Le bloc « compteur » que `boucle` et `sortie` publient à côté de `demande`.

    La moyenne compteur qui a dimensionné la distance demandée (« 5 h à
    23 km/h » → 115 km) demande trois des valeurs de cet écran —
    `moyenne_compteur_kmh`, `facteur_compteur`, `facteur_provenance` — plus le
    nom du vélo. Depuis L9.1 (25/09/2026), le bloc porte aussi la fourchette
    du porte à porte du vélo (`porte_a_porte`) : c'est elle, et non plus la
    moyenne compteur, qui chronomètre une candidate
    (`physique.modele.temps_ecoule`). Ce module en est la source
    unique (voir la docstring du module) : ceci n'est pas une deuxième lecture
    de la configuration, seulement un sous-ensemble mis en forme pour ce
    contrat-là, comme `rendu.profil.info_vitesse_compteur` l'est pour `ourouler config`.

    **`puissance_w` / `vitesse_a_plat_kmh` (exclusifs entre eux, comme pour
    `position_pour`) : la puissance effectivement demandée pour CE parcours-ci**
    — `--puissance`, ou ce qu'exige `--vitesse-a-plat`, sur `ourouler boucle`.
    Corrige un défaut trouvé le 18/09/2026 : sans ce paramètre, la moyenne
    compteur restait celle de la puissance d'endurance **de la configuration**
    quelle que soit la puissance demandée, et le temps écoulé porte à porte
    n'en suivait donc pas les variations — 150 W et 300 W rendaient le même
    porte à porte alors que le temps en mouvement, lui, changeait bien.

    **Ce que ça ne change pas** : l'écran de FTP lui-même (décision 7 du cycle
    UX) continue de montrer les trois valeurs liées à la position **de la
    configuration** — c'est `valeurs_liees`/`rendu`, appelés sans ces
    paramètres, qui le servent. Seule la moyenne compteur **publiée à côté d'un
    parcours** doit suivre la puissance demandée ; les deux
    usages divergent donc ici plutôt que l'un ne se fasse passer pour l'autre.

    Sans aucun des deux (défaut, et le seul cas pour `sortie`, qui n'a pas
    cette option) : la position de la configuration, comme avant.

    **Le facteur compteur mesuré (`velo.facteur_compteur`) n'est jamais
    recalculé ici** — `valeurs_liees` le garde tel quel dès qu'il est mesuré ;
    seule la vitesse à laquelle il s'applique bouge avec la position.

    `None` si la configuration ne porte aucun vélo : pas de modèle physique,
    pas de facteur, rien à réconcilier — et `temps_ecoule_s` doit alors valoir
    `None` chez l'appelant.
    """
    position = None
    if puissance_w is not None or vitesse_a_plat_kmh is not None:
        position = position_pour(
            config, nom_velo, puissance_w=puissance_w, vitesse_kmh=vitesse_a_plat_kmh
        )
    liees = valeurs_liees(config, nom_velo, position=position)
    if liees is None:
        return None
    fourchette = fourchette_du_velo(velo_demande(config, nom_velo), chemin_calibration(config))
    return {
        "velo": liees["velo"],
        # La puissance à laquelle `moyenne_compteur_kmh` a été calculée — sans
        # elle, un client ne peut pas savoir ce qu'il lit (règle absolue 5).
        "puissance_w": liees["puissance_endurance_w"],
        "moyenne_compteur_kmh": liees["moyenne_compteur_kmh"],
        "facteur_compteur": liees["facteur_compteur"],
        "facteur_provenance": liees["facteur_provenance"],
        # La fourchette qui chronomètre le porte à porte (L9.1) :
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


def position_pour(
    config: Config,
    nom_velo: str | None = None,
    *,
    puissance_w: float | None = None,
    vitesse_kmh: float | None = None,
) -> float:
    """La position dans la Z2 que désigne une puissance, ou une vitesse à plat.

    C'est le chemin de retour de l'écran : le cycliste tape des watts ou des
    km/h, on en déduit **la seule chose qui sera stockée**.

    `vitesse_kmh` est la vitesse **à plat, sans vent, lancé** — jamais une
    moyenne de compteur. C'est toute la raison d'être de la troisième valeur
    (décision 8), et l'API le redit dans le nom du champ.
    """
    if (puissance_w is None) == (vitesse_kmh is None):
        raise ErreurUtilisateur(
            "écran de FTP : donner soit une puissance en watts, soit une vitesse à plat "
            "en km/h, et une seule des deux"
        )
    if vitesse_kmh is not None:
        trouve = contexte(config, nom_velo)
        if trouve is None:
            raise ErreurUtilisateur(
                "écran de FTP : une vitesse ne se convertit en puissance qu'avec un vélo — "
                "aucun [[velos]] dans la configuration"
            )
        _velo, parametres, _provenance = trouve
        puissance_w = puissance_a_plat_w(vitesse_kmh, parametres)
    if config.cycliste.ftp_w is None:
        raise ErreurUtilisateur(
            "écran de FTP : aucune FTP renseignée — il n'y a pas encore d'échelle de "
            "zones dans laquelle situer une position (T3 de l'accueil : donner une FTP, "
            "ou T4 : partir d'une vitesse au compteur avec `ftp_pour_vitesse_compteur`)"
        )
    if config.cycliste.ftp_w <= 0:  # pragma: no cover - refusé au chargement
        raise ErreurUtilisateur("écran de FTP : FTP positive attendue")
    position = position_dans_zone(
        puissance_w / config.cycliste.ftp_w, ZONE_ENDURANCE, config.seance.zones_pct
    )
    if position is None:  # pragma: no cover - table sans Z2 fermée, refusée au chargement
        raise ErreurUtilisateur("zones : la table n'a pas de Z2 fermée")
    return position


def rendu(config: Config, nom_velo: str | None = None, *, position: float | None = None) -> dict:
    """Tout ce que l'écran de FTP affiche, pour une position donnée.

    L'escalier complet en watts (`seance.zones.echelle`), les trois valeurs
    liées, et la position. Une FTP qui bouge de 12 W déplace l'escalier
    entier sans qu'aucun réglage ne change — c'est le point de la décision 7,
    et c'est pourquoi rien ici n'est stocké en watts.

    **Sans FTP** (facultative depuis le 19/09/2026) : il n'y a pas d'échelle
    en watts à calculer — `echelle` l'exige, à raison, une bande de zones
    sans référence ne veut rien dire. `zones` et `valeurs_liees` rendent
    alors respectivement une liste vide et `None`, `ftp_w` reste `None`, et
    la position elle-même reste rendue : elle ne dépend pas de la FTP, et
    c'est ce qui permet à un front de continuer à afficher où la personne se
    place dans sa bande, même avant l'étage qui lui donne des watts.
    """
    ou = config.seance.position_zone if position is None else position
    if config.cycliste.ftp_w is None:
        return {
            "ftp_w": None,
            "position_zone": round(ou, 6),
            "zone_endurance": ZONE_ENDURANCE,
            "hors_bande": not 0.0 <= ou <= 1.0,
            "zones": [],
            "valeurs_liees": None,
        }
    paliers = echelle(ou, config.cycliste.ftp_w, config.seance.zones_pct)
    return {
        "ftp_w": config.cycliste.ftp_w,
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
                "bas_pct": config.seance.zones_pct[p.numero - 1][0],
                "haut_pct": config.seance.zones_pct[p.numero - 1][1],
            }
            for p in paliers
        ],
        "valeurs_liees": valeurs_liees(config, nom_velo, position=ou),
    }


# --- T4 de l'accueil : vitesse au compteur + terrain → une FTP ---------------
#
# Décision du 19/09/2026 (`docs/ux/parcours_accueil.md` §5.2-6) : on ne
# demande plus « à quelle vitesse roulez-vous à plat, sans vent » — personne
# ne sait répondre à une question sur des conditions qui n'arrivent jamais —
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


def ftp_pour_vitesse_compteur(
    config: Config,
    nom_velo: str | None,
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
    l'est déjà pour tout vélo neuf — voir `docs/ux/parcours_accueil.md` §6
    pour ce que chaque terrain vaut en `denivele_m_par_km`, et pourquoi la
    case « Montagne » y est signalée moins fiable que les trois autres.

    Ne stocke rien : l'appelant récupère la FTP rendue et l'envoie à
    `PATCH /profil` (`cycliste.ftp_w`) comme n'importe quelle FTP déclarée.
    """
    if not math.isfinite(vitesse_compteur_kmh) or vitesse_compteur_kmh <= 0:
        raise ErreurUtilisateur("écran de FTP : vitesse au compteur positive attendue")
    if not math.isfinite(denivele_m_par_km) or denivele_m_par_km < 0:
        raise ErreurUtilisateur("écran de FTP : dénivelé de terrain positif attendu")
    trouve = contexte(config, nom_velo)
    if trouve is None:
        raise ErreurUtilisateur(
            "écran de FTP : une vitesse au compteur ne se convertit en FTP qu'avec un "
            "vélo — aucun [[velos]] dans la configuration"
        )
    _velo, parametres, _provenance = trouve
    puissance_endurance_w = _puissance_pour_moyenne_compteur(
        vitesse_compteur_kmh, parametres, denivele_m_par_km=denivele_m_par_km
    )
    pct = puissance_pct_ftp(config.seance.position_zone, ZONE_ENDURANCE, config.seance.zones_pct)
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
    "contexte",
    "ftp_pour_vitesse_compteur",
    "info_compteur",
    "position_pour",
    "rendu",
    "valeurs_liees",
]
