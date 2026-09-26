"""Aides de lecture partagées par les lecteurs de fichiers : octets d'une entrée, champ texte.

Au noyau parce que les lecteurs vivent dans des couches différentes
(`activites.lecture` au stockage, `seance.zwo` et `seance.mrc` au domaine) et
qu'une seule définition vaut mieux que trois copies qui divergeraient.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ourouler.noyau.erreurs import ErreurLecture

#: Ce qu'un lecteur accepte : un chemin, ou le contenu déjà en mémoire.
Entree = Path | str | bytes | bytearray


def lire_octets(source: Entree) -> tuple[bytes, str | None]:
    """Renvoie (contenu, chemin informatif). Lève `ErreurLecture` si vide ou illisible."""
    if isinstance(source, bytes | bytearray):
        contenu, fichier = bytes(source), None
    else:
        chemin = Path(source)
        try:
            contenu = chemin.read_bytes()
        except OSError as e:
            raise ErreurLecture(f"{chemin} : lecture impossible ({e})") from e
        fichier = str(chemin)
    if not contenu:
        raise ErreurLecture(f"{fichier or '<octets>'} : fichier vide")
    return contenu, fichier


def texte_ou_none(valeur: Any) -> str | None:
    """Une chaîne non vide, ou `None`. Un champ absent et un champ vide se valent ici."""
    if valeur is None:
        return None
    texte = str(valeur).strip()
    return texte or None
