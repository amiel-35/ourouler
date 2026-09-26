#!/usr/bin/env python3
"""Le facteur qui relie la vitesse à plat à la moyenne du compteur, mesuré.

**Pourquoi ce script existe.** L'écran de FTP montre trois valeurs liées
(décision 8 du cycle UX, `docs/journal/ux/cycle_ux_contrat.md`) : la puissance visée,
la vitesse à plat sans vent lancé, et **la moyenne que le compteur affichera**.
Sans la troisième, quelqu'un tape dans le champ « à plat » la moyenne qu'il lit
sur son compteur, et tout l'escalier de ses zones se décale vers le bas.

Le facteur qui relie les deux est un **réglage par vélo**
(`config.Velo.facteur_compteur`), pas une constante : il dépend de la masse du
cycliste autant que de ses routes. Un chiffre écrit en dur serait juste pour un
seul homme sur ses seules routes. Ce script le mesure sur l'historique réel.

**Le temps retenu est le temps écoulé.** Deux durées existent et donnent deux
facteurs différents : la sortie entière (`duree_s` de l'index — dernier point
moins premier, arrêts compris) et le temps de mouvement
(`Activite.duree_mouvement_s`, quand la source le donne). Ce script affiche les
deux et **retient le temps écoulé** : il se lit sur n'importe quelle source (le
GPX et le TCX ne portent aucun temps de mouvement), il ne dépend pas du réglage
d'arrêt automatique du compteur — une propriété de l'appareil, pas du cycliste
— et c'est celui que le cycliste calcule de tête.

**Le rattachement au vélo passe par le capteur de puissance**, comme le fait
déjà la calibration (`activites.inventaire.rattacher_velo`) : `gear_id` est vide
sur la majorité des sorties extérieures du mainteneur, le capteur ne l'est pas —
il est physiquement monté sur un vélo et un seul.

**La vitesse de référence est un modèle, pas une mesure.** « À plat, sans vent,
lancé » ne s'observe nulle part dans un fichier d'activité : elle sort de
`physique.modele.vitesse_a_plat_kmh`, à la puissance d'endurance du cycliste,
avec les paramètres calibrés du vélo. Le facteur mesuré ici hérite donc de la
qualité de la calibration ; le script dit d'où viennent les paramètres.

**Ce que le script ne sépare pas.** Le relief, le vent et les arrêts sont
mélangés dans un seul nombre, et c'est voulu : c'est ce nombre-là que l'écran
applique. L'écart entre la ligne « en mouvement » et la ligne « temps écoulé »
donne quand même la part des arrêts.

Aucun réseau : tout est lu dans le cache local (règle absolue 3).

Usage :
    uv run python scripts/validation/facteur_compteur_retrospectif.py
    uv run python scripts/validation/facteur_compteur_retrospectif.py --depuis 2025-01-01
    uv run python scripts/validation/facteur_compteur_retrospectif.py --sans-mouvement
"""

from __future__ import annotations

import argparse
import statistics
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from ourouler.activites.cache import Cache, EntreeCache
from ourouler.activites.inventaire import en_interieur, rattacher_velo
from ourouler.config import Config, Velo, charger
from ourouler.noyau.activite import est_sport_velo
from ourouler.physique.commande import chemin_calibration, parametres_du_velo
from ourouler.physique.modele import (
    DENIVELE_REFERENCE_M_PAR_KM,
    PART_ARRET_REFERENCE,
    facteur_compteur_defaut,
    vitesse_a_plat_kmh,
)

#: Durée minimale d'une sortie retenue. Sous une heure, une sortie extérieure
#: est souvent un trajet ou un bout de séance : ses arrêts et ses relances n'y
#: pèsent pas du tout le même poids que sur une vraie sortie.
DUREE_MINIMALE_S = 3600.0

#: Distance minimale, en mètres. Une trace de quelques centaines de mètres
#: (compteur oublié allumé, transfert) fabriquerait une moyenne absurde.
DISTANCE_MINIMALE_M = 5000.0


@dataclass
class MesuresVelo:
    """Ce qu'on a pu mesurer pour un vélo."""

    velo: Velo
    vitesses_ecoulees_kmh: list[float] = field(default_factory=list)
    vitesses_mouvement_kmh: list[float] = field(default_factory=list)
    sans_temps_mouvement: int = 0
    illisibles: int = 0


def retenue(entree: EntreeCache) -> bool:
    """Une sortie extérieure, en vélo, assez longue et assez loin pour compter."""
    return (
        est_sport_velo(entree.sport)
        and not en_interieur(entree)
        and (entree.duree_s or 0.0) >= DUREE_MINIMALE_S
        and (entree.distance_m or 0.0) >= DISTANCE_MINIMALE_M
    )


def collecter(
    config: Config, depuis: date, *, avec_mouvement: bool
) -> tuple[dict[str, MesuresVelo], int]:
    """Les vitesses réelles, par vélo. Aucun réseau : le cache local seulement."""
    cache = Cache(Path(config.cache.dossier).expanduser())
    par_velo = {velo.nom: MesuresVelo(velo=velo) for velo in config.velos}
    hors_velos = 0

    for entree in cache.lister(depuis=depuis):
        if not retenue(entree):
            continue
        mesures = par_velo.get(rattacher_velo(entree, config))
        if mesures is None:
            # « home-trainer » et « inconnu » ne sont pas des vélos de la
            # configuration : ils n'ont ni masse ni calibration, donc aucune
            # vitesse à plat à laquelle se comparer.
            hors_velos += 1
            continue

        distance_m = float(entree.distance_m or 0.0)
        mesures.vitesses_ecoulees_kmh.append(distance_m / float(entree.duree_s) * 3.6)
        if avec_mouvement:
            _ajouter_mouvement(cache, entree, mesures)

    return par_velo, hors_velos


def _ajouter_mouvement(cache: Cache, entree: EntreeCache, mesures: MesuresVelo) -> None:
    """Relit le fichier brut pour son temps de **mouvement**, absent de l'index.

    Le fichier n'est relu que pour ça — le temps écoulé, lui, est dans l'index.
    Un fichier illisible ou sans temps de mouvement se compte et ne casse rien :
    la ligne de contrôle perd une sortie, la mesure retenue n'y touche pas.
    """
    try:
        activite = cache.relire(entree.identifiant)
    except Exception:  # noqa: BLE001 — un fichier illisible se compte, il n'arrête pas la mesure
        mesures.illisibles += 1
        return
    if not activite.duree_mouvement_s or not activite.distance_m:
        mesures.sans_temps_mouvement += 1
        return
    mesures.vitesses_mouvement_kmh.append(
        float(activite.distance_m) / float(activite.duree_mouvement_s) * 3.6
    )


def rapporter(config: Config, par_velo: dict[str, MesuresVelo], depuis: date) -> None:
    """Un bloc par vélo : la référence du modèle, les deux mesures, le défaut."""
    pct = config.seance.puissance_endurance_pct
    puissance_w = pct * config.cycliste.ftp_w
    chemin = chemin_calibration(config)

    print(
        f"Puissance de référence : {pct:.3f} × FTP = {puissance_w:.0f} W "
        f"· extérieur ≥ {DUREE_MINIMALE_S / 3600:.0f} h · depuis {depuis.isoformat()}\n"
    )

    for nom, mesures in par_velo.items():
        if not mesures.vitesses_ecoulees_kmh:
            print(f"{nom} — aucune sortie exploitable\n")
            continue
        parametres, provenance = parametres_du_velo(config, mesures.velo, chemin)
        v_plat = vitesse_a_plat_kmh(puissance_w, parametres)
        defaut = facteur_compteur_defaut(puissance_w, parametres)

        print(f"{nom} ({mesures.velo.usage}) — {len(mesures.vitesses_ecoulees_kmh)} sorties")
        print(
            f"   à plat, sans vent, lancé    {v_plat:5.1f} km/h"
            f"          [paramètres : {provenance}]"
        )
        if mesures.vitesses_mouvement_kmh:
            med = statistics.median(mesures.vitesses_mouvement_kmh)
            print(
                f"   en mouvement (médiane)      {med:5.1f} km/h   {med / v_plat:4.0%}"
                f"   sur {len(mesures.vitesses_mouvement_kmh)} sorties lisibles"
            )
        med_ecoule = statistics.median(mesures.vitesses_ecoulees_kmh)
        facteur = med_ecoule / v_plat
        print(
            f"   au compteur, temps écoulé   {med_ecoule:5.1f} km/h   {facteur:4.0%}"
            "   ← le facteur retenu"
        )
        configure = mesures.velo.facteur_compteur
        print(
            "   facteur_compteur configuré  "
            + (f"{configure:.3f}" if configure is not None else "absent")
        )
        print(
            f"   défaut dérivé du modèle     {defaut:.3f}"
            f"   ({DENIVELE_REFERENCE_M_PAR_KM:.0f} m/km, "
            f"{PART_ARRET_REFERENCE:.0%} d'arrêt — une supposition, pas une mesure)"
        )
        print(f"\n   à reporter dans [[velos]] nom = {nom!r} : facteur_compteur = {facteur:.2f}\n")


def main() -> None:
    parseur = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parseur.add_argument(
        "--depuis", default=None, help="date de début (défaut : celle de la configuration)"
    )
    parseur.add_argument("--config", default=None, help="fichier de configuration")
    parseur.add_argument(
        "--sans-mouvement",
        action="store_true",
        help="ne pas relire les fichiers bruts (plus rapide, pas de ligne « en mouvement »)",
    )
    args = parseur.parse_args()

    config = charger(args.config)
    depuis = date.fromisoformat(args.depuis) if args.depuis else config.historique_depuis
    if not config.velos:
        raise SystemExit("aucun vélo dans la configuration : ajouter une section [[velos]]")

    par_velo, hors_velos = collecter(config, depuis, avec_mouvement=not args.sans_mouvement)
    if not any(m.vitesses_ecoulees_kmh for m in par_velo.values()):
        raise SystemExit("aucune sortie exploitable — vérifier le cache et la date de début")

    rapporter(config, par_velo, depuis)
    ecartees = sum(m.illisibles + m.sans_temps_mouvement for m in par_velo.values())
    if hors_velos or ecartees:
        print(
            f"({hors_velos} sorties rattachées à aucun vélo de la configuration, "
            f"{ecartees} fichiers sans temps de mouvement exploitable)"
        )


if __name__ == "__main__":
    sys.exit(main())
