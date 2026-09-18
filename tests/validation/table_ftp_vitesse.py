#!/usr/bin/env python3
"""La table indicative FTP → vitesse à plat → moyenne compteur.

**Pourquoi ce script existe.** L'assistant demande une FTP, et le produit en
déduit une vitesse. Quelqu'un qui découvre l'outil n'a aucune idée de ce que
ça donne : 220 W de FTP, est-ce que ça fait 25 ou 32 km/h ? La table répond
avant qu'on ait à saisir quoi que ce soit, et elle se lit **dans les deux
sens** — celui qui ne connaît pas sa FTP mais sait qu'il tient 26 km/h à plat
y trouve la sienne, approximativement.

**Rien n'est écrit à la main dans la doc** : `docs/table_ftp_vitesse.md` est
le rendu de ce script. Si les valeurs de littérature changent, on le relance
plutôt que de corriger vingt-sept nombres à la main.

Les trois colonnes sont les **trois valeurs liées** de l'écran de FTP
(décision 7 du cycle UX), calculées ici pour un cycliste générique au lieu du
cycliste réel.

**Ce que la table ne sait pas**, et qu'il faut lire avec elle :

1. Le jeu CdA/Crr est celui dit « route amateur », mesuré au sprint 6 contre
   la calibration réelle du mainteneur : +0,3 minute de dérive sur une boucle
   de deux heures. C'est le meilleur des jeux essayés — sur **un** cycliste.
   Un autre corps, une autre position, un autre vélo, et la ligne bouge.
2. La colonne « compteur » est la plus faible des trois. Elle vient du facteur
   par défaut, dérivé d'un profil de référence — 10 m de dénivelé par km, 5 %
   du temps à l'arrêt — qui n'est la sortie de personne. Le vrai facteur se
   mesure sur l'historique (`facteur_compteur_retrospectif.py`) : chez le
   mainteneur, il vaut 0,87 là où le défaut supposait 0,803.
3. Tout est calculé **à plat, sans vent, lancé**, à la puissance d'endurance.
   Une sortie réelle a du relief, du vent et des carrefours.

Aucun réseau, aucune configuration lue : la table est générique par construction.

Usage :
    uv run python tests/validation/table_ftp_vitesse.py            # texte
    uv run python tests/validation/table_ftp_vitesse.py --markdown # la doc
"""

from __future__ import annotations

import argparse

from ourouler.physique.modele import (
    Parametres,
    facteur_compteur_defaut,
    moyenne_compteur_kmh,
    vitesse_a_plat_kmh,
)

#: Jeu « route amateur », mesuré au sprint 6 (commit b6114b2) : celui dont la
#: dérive vaut +0,3 min sur une boucle de 2 h face à une vraie calibration.
CDA_ROUTE, CRR_ROUTE = 0.320, 0.0050

#: Part de la FTP tenue en endurance. C'est le défaut du produit, et le
#: mainteneur a mesuré 0,689 en puissance normalisée sur ses propres sorties :
#: la colonne est donc plutôt conservatrice.
PCT_ENDURANCE = 0.60

#: Masse du vélo supposée, en kilogrammes. Un vélo de route complet.
VELO_KG = 9.0

MASSES_CYCLISTE = (65, 75, 85)
FTP_MIN, FTP_MAX, FTP_PAS = 150, 350, 25


def ligne(ftp_w: float, masse_cycliste_kg: float) -> tuple[float, float, float, float]:
    """(puissance d'endurance, vitesse à plat, moyenne compteur, facteur)."""
    p = Parametres(
        masse_totale_kg=masse_cycliste_kg + VELO_KG, cda_m2=CDA_ROUTE, crr=CRR_ROUTE
    )
    w = ftp_w * PCT_ENDURANCE
    facteur = facteur_compteur_defaut(w, p)
    return (w, vitesse_a_plat_kmh(w, p), moyenne_compteur_kmh(w, p, facteur), facteur)


def main() -> None:
    parseur = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parseur.add_argument("--markdown", action="store_true", help="rendu pour la doc")
    args = parseur.parse_args()

    for masse in MASSES_CYCLISTE:
        titre = f"cycliste {masse} kg + vélo {VELO_KG:.0f} kg = {masse + VELO_KG:.0f} kg"
        if args.markdown:
            print(f"\n### {titre}\n")
            print("| FTP | endurance | à plat, sans vent | moyenne compteur attendue |")
            print("|---:|---:|---:|---:|")
        else:
            print(f"\n### {titre}")
            print(f"{'FTP':>5} {'Z2':>7} {'à plat':>9} {'compteur':>10} {'facteur':>8}")
        for ftp in range(FTP_MIN, FTP_MAX + 1, FTP_PAS):
            w, plat, compteur, facteur = ligne(ftp, masse)
            if args.markdown:
                print(
                    f"| {ftp} W | {w:.0f} W | {plat:.1f} km/h | {compteur:.1f} km/h |".replace(
                        ".", ","
                    )
                )
            else:
                print(f"{ftp:>5} {w:>6.0f}W {plat:>8.1f} {compteur:>9.1f} {facteur:>8.3f}")


if __name__ == "__main__":
    main()
