"""Les trois valeurs liées de l'écran de FTP, et l'escalier qu'elles déplacent.

Décision 7 du cycle UX (`docs/ux/cycle_ux_contrat.md`) : l'écran montre trois
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

from ourouler.config import Config, Velo
from ourouler.erreurs import ErreurUtilisateur
from ourouler.physique.commande import chemin_calibration, parametres_du_velo, velo_demande
from ourouler.physique.modele import (
    PART_ARRET_REFERENCE,
    Parametres,
    facteur_compteur_defaut,
    moyenne_compteur_kmh,
    puissance_a_plat_w,
    vitesse_a_plat_kmh,
)
from ourouler.seance.zones import ZONE_ENDURANCE, echelle, position_dans_zone, puissance_pct_ftp


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

    `None` si la configuration ne porte aucun vélo : il n'y a alors ni modèle
    physique ni facteur de compteur, donc rien à réconcilier.
    """
    trouve = contexte(config, nom_velo)
    if trouve is None:
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


def info_compteur(config: Config, nom_velo: str | None = None) -> dict | None:
    """Le bloc « compteur » que `boucle` et `sortie` publient à côté de `demande`.

    Réconcilier le temps en mouvement d'une candidate (`temps_estime_s`) et
    son temps écoulé porte à porte (`physique.modele.temps_ecoule`) demande
    trois des valeurs de cet écran — `moyenne_compteur_kmh`, `facteur_compteur`,
    `facteur_provenance` — plus le nom du vélo. Ce module en est la source
    unique (voir la docstring du module) : ceci n'est pas une deuxième lecture
    de la configuration, seulement un sous-ensemble mis en forme pour ce
    contrat-là, comme `cli._info_vitesse_compteur` l'est pour `ourouler config`.

    `None` si la configuration ne porte aucun vélo : pas de modèle physique,
    pas de facteur, rien à réconcilier — et `temps_ecoule_s` doit alors valoir
    `None` chez l'appelant.
    """
    liees = valeurs_liees(config, nom_velo)
    if liees is None:
        return None
    return {
        "velo": liees["velo"],
        "moyenne_compteur_kmh": liees["moyenne_compteur_kmh"],
        "facteur_compteur": liees["facteur_compteur"],
        "facteur_provenance": liees["facteur_provenance"],
        "part_arret_plancher": PART_ARRET_REFERENCE,
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
    """
    ou = config.seance.position_zone if position is None else position
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


__all__ = [
    "contexte",
    "info_compteur",
    "position_pour",
    "rendu",
    "valeurs_liees",
]
