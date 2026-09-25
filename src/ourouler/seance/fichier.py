"""Lecture d'un fichier de séance, lecteur choisi par son extension.

`seance/zwo.py` et `seance/mrc.py` savent chacun lire leur propre forme,
mais rien avant ce module ne choisissait lequel appeler pour un fichier
donné : c'est le trou relevé en **C1** de `docs/journal/ux/relecture_f0.md` — 683
lignes lues et testées, sans le moindre appelant. Ce module est ce point
d'entrée, dans le même esprit que `activites.lecture.lire` pour les
fichiers d'activité (FIT/GPX/TCX).

Le `.FIT` n'est pas couvert ici : ses messages de séance sont d'une autre
famille que ses messages d'activité, les seuls lus aujourd'hui (l'ordre —
ZWO et MRC d'abord, FIT ensuite — est celui tranché par le mainteneur, voir
`docs/journal/ux/maquettes_v1.html` E17).

Ce module ne lit aucune configuration, aucun chemin utilisateur, aucune
variable d'environnement : `chemin` est un `Path` que l'appelant (`cli.py`
via `seance/commande.py` ou `sortie/commande.py`) a déjà choisi.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from ourouler.erreurs import ErreurLecture
from ourouler.seance.modele import SEUIL_RECUPERATION_PCT_DEFAUT, Seance
from ourouler.seance.mrc import lire_mrc
from ourouler.seance.zwo import lire_zwo

#: Extensions reconnues, en minuscules et sans le point.
EXTENSIONS = ("zwo", "mrc")


def lire_fichier_seance(
    chemin: Path,
    *,
    ftp_w: float | None = None,
    seuil_recuperation_pct: float = SEUIL_RECUPERATION_PCT_DEFAUT,
    jour: date | None = None,
) -> Seance:
    """Lit un `.ZWO` ou un `.MRC` vers une `Seance`, lecteur choisi par l'extension.

    Insensible à la casse (`.ZWO` comme `.zwo`). Lève `ErreurLecture` si
    l'extension n'est ni l'une ni l'autre, ou si le lecteur choisi refuse le
    contenu (fichier vide, mal formé, balise ou en-tête inconnu) — un seul
    type d'erreur à attraper côté appelant, celui que lèvent déjà `lire_zwo`
    et `lire_mrc`.

    `seuil_recuperation_pct` ne sert qu'au `.MRC`, qui n'a aucun marqueur de
    type d'étape et doit deviner un bloc d'une récupération par contraste de
    puissance (voir la docstring de `seance/mrc.py`) ; le `.ZWO` nomme ses
    balises et n'en a pas besoin.
    """
    chemin = Path(chemin)
    extension = chemin.suffix.lower().lstrip(".")
    if extension == "zwo":
        return lire_zwo(chemin, ftp_w=ftp_w, jour=jour)
    if extension == "mrc":
        return lire_mrc(
            chemin, ftp_w=ftp_w, seuil_recuperation_pct=seuil_recuperation_pct, jour=jour
        )
    raise ErreurLecture(
        f"{chemin} : extension « {chemin.suffix or '(aucune)'} » inconnue "
        f"(attendu {', '.join('.' + e for e in EXTENSIONS)} — le .FIT n'est pas encore lu)"
    )


__all__ = ["EXTENSIONS", "lire_fichier_seance"]
