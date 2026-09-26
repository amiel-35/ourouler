"""Rejoue une séance HIT du plan avec les Z2 qu'elle aurait en extérieur.

Script de validation manuelle, **non collecté par pytest** : il appelle le
vrai serveur BRouter, la vraie météo et le vrai compte Intervals du
mainteneur, comme ses voisins de ce dossier.

Usage : `uv run python scripts/validation/seance_hit_exterieur.py --jour 2026-09-01`
puis les options habituelles de `ourouler sortie`.


Pourquoi il existe : sur 85 jours, le plan du mainteneur ne contient **aucune
séance à blocs en extérieur** — les HIT sont tous sur home-trainer, et leurs
Z2 sont volontairement tronquées. Une séance de 63 min dont 8 min
d'échauffement ne dit rien du placement réel : le moteur reste près de la
ville faute d'avoir à s'en éloigner.

Le mainteneur (16/09/2026) : « si tu veux te faire une séance test avec la
HIIT sans chercher une vieille séance, prends 1 h de Z2 au début et 30 à
45 min à la fin ». C'est sa prescription de ce à quoi ressemble la même
séance dehors — ce n'est donc pas une séance inventée, c'est la sienne dans
sa forme extérieure.

Les vieilles séances à blocs réelles (« 4x8 SV1 outdoor » du 22/04) restent
utilisables mais sortent de la fenêtre météo d'Open-Meteo : le placement
tourne, la pluie et le vent manquent.
"""

import sys
from dataclasses import replace

import ourouler.services.sortie as cmd
from ourouler.cli import main

VRAI = cmd.seance_du_jour
OUVERTURE_S = 60 * 60.0
FERMETURE_S = 40 * 60.0


def etendue(client, jour, **kw):
    s = VRAI(client, jour, **kw)
    etapes = list(s.etapes)
    etapes[0] = replace(etapes[0], duree_s=OUVERTURE_S, libelle="Z2 d'ouverture (extérieur)")
    etapes[-1] = replace(etapes[-1], duree_s=FERMETURE_S, libelle="Z2 de fin (extérieur)")
    duree = sum(e.duree_s for e in etapes)
    print(
        f"[test] séance « {s.nom} » : {s.duree_s / 60:.0f} min -> {duree / 60:.0f} min "
        f"(ouverture {OUVERTURE_S / 60:.0f}, fermeture {FERMETURE_S / 60:.0f})\n"
    )
    return replace(s, etapes=etapes, duree_s=duree)


cmd.seance_du_jour = etendue
sys.exit(main(["sortie", *sys.argv[1:]]))
