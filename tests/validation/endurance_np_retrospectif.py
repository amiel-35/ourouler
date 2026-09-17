#!/usr/bin/env python3
"""Ce que le mainteneur roule vraiment en endurance, en puissance normalisée.

**Pourquoi ce script existe.** `config.seance.puissance_endurance_pct` vaut
0,60 par défaut, et rien ne justifiait ce chiffre. Il sert à dimensionner les
boucles d'endurance : trop bas, l'outil propose des parcours trop courts.

**La faute que ce script corrige.** Une première mesure, faite à la moyenne de
puissance, donnait 0,581 et concluait que 0,60 était déjà généreux. C'était
faux, et le mainteneur a nommé l'instrument juste : *« faut en extérieur pas
prendre la moyenne mais la puissance normalisée »*. La moyenne compte les
arrêts, les descentes et les virages comme de l'effort nul — elle mesure
autant le parcours que le cycliste. La NP est faite exactement pour ça.

**Le résultat du 16/09/2026**, sur 101 sorties extérieures d'au moins une
heure, sans nom de séance structurée :

    NP / FTP   médiane 0,689   quartiles 0,655 … 0,736
    moy / FTP  médiane 0,581

Le milieu de la zone 2 de `ZONES_PUISSANCE_DEFAUT` — (0,56 + 0,75) / 2 =
**0,655** — tombe sur le bord bas du quartile inférieur. La valeur par défaut
de 0,60 est donc **trop basse d'environ 15 %**.

**Le contrôle qui valide l'instrument.** Les 36 sorties portant un nom de
séance structurée donnent 0,691 en NP, contre 0,689 pour les autres : deux
millièmes d'écart. Sur la moyenne, l'écart existait (0,581 contre 0,591) et
disparaît en NP. C'est le comportement attendu — une séance à blocs ne roule
pas plus fort en moyenne, elle distribue l'effort autrement, et la NP est
conçue pour être insensible à cette distribution.

**Les deux réserves, à lire avec le chiffre.**

1. **La FTP est celle d'aujourd'hui**, appliquée à des sorties remontant à
   décembre 2023. Le rapport mélange donc ce que le mainteneur roule en
   endurance et la dérive de sa forme sur deux ans. Intervals suit une FTP
   estimée dans le temps ; le cache ne la garde pas. Le mainteneur l'avait
   signalé : *« c'est une question de forme aussi »*.
2. **La NP n'est pas une cible de sortie.** Elle dit le coût physiologique
   d'un effort variable, elle ne se vise pas au guidon. L'utiliser pour
   dimensionner une boucle est un raccourci assumé : on cherche une distance
   plausible, pas une consigne d'entraînement.

Aucun réseau : tout est lu dans le cache local (règle absolue 3).

Usage :
    uv run python tests/validation/endurance_np_retrospectif.py
    uv run python tests/validation/endurance_np_retrospectif.py --depuis 2025-01-01
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import statistics
import sys
from datetime import date
from pathlib import Path

from ourouler.activites.lecture import lecteur_pour
from ourouler.activites.modele import puissance_normalisee
from ourouler.config import charger
from ourouler.seance.modele import ZONES_PUISSANCE_DEFAUT

#: Un nom de séance qui porte une structure : répétitions, ou un mot de
#: famille d'entraînement. Le mainteneur a montré au sprint 5 que cette
#: détection par le nom rate des cas — elle sert ici de **contrôle**, pas de
#: filtre décisif : si les deux populations donnent la même NP, la question
#: de savoir qui est dans quelle population perd son importance.
NOM_STRUCTURE = re.compile(r"\d+\s*[x×]\s*\d|sst|seuil|vo2|hiit|ido|bloc|pma|tempo|intervall", re.I)

#: Durée minimale retenue. Sous une heure, une sortie extérieure est souvent
#: un trajet ou un bout de séance, pas une sortie d'endurance.
DUREE_MINIMALE_S = 3600


def _quartiles(valeurs: list[float]) -> tuple[float, float, float]:
    """Médiane et quartiles, sur une liste déjà triée."""
    return valeurs[len(valeurs) // 4], statistics.median(valeurs), valeurs[3 * len(valeurs) // 4]


def collecter(dossier: Path, depuis: date, ftp_w: float) -> tuple[list[float], list[float], int]:
    """Rapports NP/FTP des sorties extérieures, séparés par le nom. Aucun réseau."""
    index = dossier / "index.sqlite"
    if not index.is_file():
        raise SystemExit(f"cache introuvable : {index} — lancer `ourouler inventaire` d'abord")
    with sqlite3.connect(f"file:{index}?mode=ro", uri=True) as cx:
        lignes = cx.execute(
            "SELECT identifiant, extension, duree_s, meta FROM activites "
            "WHERE sport = 'Ride' AND debut >= ? ORDER BY debut",
            (depuis.isoformat(),),
        ).fetchall()

    libres: list[float] = []
    structurees: list[float] = []
    ecartees = 0
    for identifiant, extension, duree_s, meta in lignes:
        indexee = json.loads(meta) if meta else {}
        if indexee.get("trainer") or indexee.get("interieur"):
            continue
        if not duree_s or duree_s < DUREE_MINIMALE_S:
            continue
        chemin = dossier / "brut" / f"{identifiant}.{extension}"
        if not chemin.is_file():
            ecartees += 1
            continue
        try:
            activite = lecteur_pour(extension)(chemin)
            np_w = puissance_normalisee(activite.points)
        except Exception:  # noqa: BLE001 — un fichier illisible se compte, il ne casse pas la mesure
            ecartees += 1
            continue
        if not np_w:
            continue
        cible = structurees if NOM_STRUCTURE.search(indexee.get("nom") or "") else libres
        cible.append(np_w / ftp_w)
    return libres, structurees, ecartees


def main() -> None:
    parseur = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parseur.add_argument("--depuis", default="2023-12-01", help="date de début (défaut : 2023-12-01)")
    parseur.add_argument("--config", default=None, help="fichier de configuration")
    args = parseur.parse_args()

    config = charger(args.config)
    ftp = config.cycliste.ftp_w
    libres, structurees, ecartees = collecter(
        Path(config.cache.dossier).expanduser(), date.fromisoformat(args.depuis), ftp
    )
    if not libres:
        raise SystemExit("aucune sortie exploitable — vérifier le cache et la date de début")

    print(f"FTP de référence : {ftp:.0f} W · extérieur ≥ {DUREE_MINIMALE_S // 3600} h "
          f"· depuis {args.depuis} · {ecartees} fichiers écartés\n")
    populations = (
        ("sans nom de séance structurée", libres),
        ("avec nom de séance structurée", structurees),
    )
    for nom, valeurs in populations:
        if not valeurs:
            continue
        bas, med, haut = _quartiles(sorted(valeurs))
        print(f"{nom} — {len(valeurs)} sorties")
        print(f"   NP / FTP   médiane {med:.3f} ({med * ftp:.0f} W)   quartiles {bas:.3f} … {haut:.3f}")

    milieu_z2 = sum(ZONES_PUISSANCE_DEFAUT[1]) / 2
    actuel = config.seance.puissance_endurance_pct
    med_libres = statistics.median(libres)
    print(f"\nMilieu de la Z2 (ZONES_PUISSANCE_DEFAUT) : {milieu_z2:.3f} ({milieu_z2 * ftp:.0f} W)")
    print(f"puissance_endurance_pct configuré        : {actuel:.3f} ({actuel * ftp:.0f} W)")
    ecart = (med_libres - actuel) / actuel
    print(f"\nÉcart entre ce qui est roulé et ce qui est configuré : {ecart:+.1%}")
    if abs(med_libres - milieu_z2) < abs(med_libres - actuel):
        print("Le milieu de la Z2 est plus proche de la réalité que la valeur configurée.")
    else:
        print("La valeur configurée est plus proche de la réalité que le milieu de la Z2.")


if __name__ == "__main__":
    sys.exit(main())
