"""Lecteur de fichier de séance home-trainer (`.MRC`) vers `Seance`.

Format texte : un en-tête qui dit l'unité de la seconde colonne
(`MINUTES PERCENT` ou `MINUTES WATTS`), puis des couples minute / valeur qui
décrivent une courbe de puissance par morceaux — la forme classique
`[COURSE HEADER] ... [END COURSE HEADER]` / `[COURSE DATA] ... [END COURSE
DATA]`, mais la lecture ne dépend pas de ces crochets : elle cherche la
ligne d'unité et les lignes de données où qu'elles soient dans le fichier,
et ignore tout le reste (crochets de section, `CLE = valeur`). Deux points
consécutifs délimitent une étape : sa durée est l'écart de minutes entre les
deux, sa puissance va de la première valeur à la seconde — un palier si
elles sont égales, une rampe si elles diffèrent.

**La valeur peut être en watts ou en pourcentage de FTP selon l'en-tête, et
ce lecteur ne suppose rien : sans la ligne `MINUTES PERCENT`/`MINUTES
WATTS`, il refuse de deviner et lève `ErreurLecture`.**

Le fichier ne porte aucun marqueur de type d'étape — pas de « Warmup », pas
de texte, rien que des nombres. Le type se déduit donc comme la troisième
règle de la cascade d'Intervals.icu (`seance/intervals.py`,
`_reclasser_par_puissance`) : sous `seuil_recuperation_pct × FTP`, une étape
n'est pas un bloc ; celle qui n'est pas un bloc en tête de séance est un
échauffement, celle en queue un retour au calme, celle du milieu une
récupération. Sans FTP et sans contraste de puissance dans le fichier, rien
ne permet de fixer ce seuil : toutes les étapes restent des blocs plutôt que
de deviner.

Ce module ne lit aucune configuration, ne touche pas le réseau.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

from ourouler.erreurs import ErreurLecture
from ourouler.seance.modele import SEUIL_RECUPERATION_PCT_DEFAUT, Etape, Seance

Entree = Path | str | bytes | bytearray

_UNITES = {"percent": "percent", "pct": "percent", "watts": "watts", "watt": "watts"}
_RE_DONNEE = re.compile(r"^\s*([+-]?\d+(?:\.\d+)?)\s+([+-]?\d+(?:\.\d+)?)\s*$")
_RE_MINUTES = re.compile(r"^\s*MINUTES\s+([A-Za-z]+)\s*$", re.IGNORECASE)
_RE_DESCRIPTION = re.compile(r"^\s*DESCRIPTION\s*=\s*(.*)$", re.IGNORECASE)


def lire_mrc(
    source: Entree,
    *,
    ftp_w: float | None = None,
    seuil_recuperation_pct: float = SEUIL_RECUPERATION_PCT_DEFAUT,
    nom: str | None = None,
    jour: date | None = None,
) -> Seance:
    """Lit un `.MRC` vers une `Seance`.

    Lève `ErreurLecture` si le fichier est vide, si l'en-tête ne dit pas
    l'unité de puissance, ou s'il ne contient pas au moins deux points de
    données (rien à en tirer). `jour` vaut la date du jour si omis.
    """
    contenu, fichier = _octets(source)
    texte = contenu.decode("utf-8", errors="replace")

    unite = _unite(texte)
    if unite is None:
        raise ErreurLecture(
            f"{fichier or '<octets>'} : en-tête « MINUTES PERCENT » ou « MINUTES WATTS » "
            "absent — impossible de savoir si les valeurs sont des watts ou un pourcentage de FTP"
        )

    points = _points(texte)
    if len(points) < 2:
        raise ErreurLecture(
            f"{fichier or '<octets>'} : moins de deux points de données exploitables, "
            "aucune étape à en tirer"
        )

    etapes = _segments(points, unite=unite, ftp_w=ftp_w)
    if not etapes:
        raise ErreurLecture(
            f"{fichier or '<octets>'} : tous les points de données donnent une durée nulle "
            "ou négative, aucune étape à en tirer"
        )
    etapes = _typer(etapes, ftp_w=ftp_w, seuil_pct=seuil_recuperation_pct)
    etapes = _marquer_elastiques(etapes)

    description = _description(texte)
    meta: dict = {"source": "mrc", "unite": unite, "ftp_w": ftp_w}
    if unite == "percent":
        if ftp_w is not None:
            meta["conversion"] = (
                f"pourcentages de FTP convertis en watts avec une FTP de {ftp_w:g} W"
            )
        else:
            sans_ftp = sum(1 for e in etapes if e.puissance_cible_w is None)
            meta["conversion"] = (
                "FTP inconnue : aucun pourcentage de FTP n'a pu être converti en watts"
            )
            if sans_ftp:
                meta["etapes_sans_ftp"] = sans_ftp
    if description:
        meta["description"] = description

    nom_seance = nom or description or (fichier or "séance MRC")
    duree_s = sum(e.duree_s for e in etapes)
    return Seance(
        nom=str(nom_seance),
        jour=jour or date.today(),
        etapes=etapes,
        duree_s=duree_s,
        meta=meta,
    )


# --- en-tête et données ----------------------------------------------------------


def _unite(texte: str) -> str | None:
    for ligne in texte.splitlines():
        trouve = _RE_MINUTES.match(ligne)
        if trouve:
            mot = trouve.group(1).casefold()
            if mot in _UNITES:
                return _UNITES[mot]
    return None


def _points(texte: str) -> list[tuple[float, float]]:
    points: list[tuple[float, float]] = []
    for ligne in texte.splitlines():
        trouve = _RE_DONNEE.match(ligne)
        if trouve:
            points.append((float(trouve.group(1)), float(trouve.group(2))))
    return points


def _description(texte: str) -> str | None:
    for ligne in texte.splitlines():
        trouve = _RE_DESCRIPTION.match(ligne)
        if trouve:
            valeur = trouve.group(1).strip()
            return valeur or None
    return None


# --- segments et conversion -------------------------------------------------------


def _segments(points: list[tuple[float, float]], *, unite: str, ftp_w: float | None) -> list[Etape]:
    """Un `Etape` par paire de points consécutifs ; les segments de durée nulle
    ou négative (minutes qui n'avancent pas ou reculent) sont écartés."""
    etapes: list[Etape] = []
    for (m1, v1), (m2, v2) in zip(points, points[1:], strict=False):
        duree_s = (m2 - m1) * 60.0
        if duree_s <= 0:
            continue
        bas = _en_watts(v1, unite, ftp_w)
        haut = _en_watts(v2, unite, ftp_w)
        etapes.append(
            Etape(
                type="bloc",
                duree_s=duree_s,
                puissance_min_w=bas,
                puissance_max_w=haut,
                libelle=_libelle(v1, v2, unite),
            )
        )
    return etapes


def _en_watts(valeur: float, unite: str, ftp_w: float | None) -> float | None:
    if unite == "watts":
        return valeur if valeur >= 0 else None  # une consigne négative n'a pas de sens
    if ftp_w is None:
        return None
    watts = valeur / 100.0 * ftp_w
    return watts if watts >= 0 else None


def _libelle(v1: float, v2: float, unite: str) -> str:
    suffixe = "W" if unite == "watts" else "% FTP"
    if v1 == v2:
        return f"{_court(v1)} {suffixe}"
    return f"{_court(v1)}-{_court(v2)} {suffixe}"


def _court(valeur: float) -> str:
    return f"{valeur:g}"


# --- typage par puissance et position, comme Intervals.icu ------------------------


def _typer(etapes: list[Etape], *, ftp_w: float | None, seuil_pct: float) -> list[Etape]:
    seuil = _seuil(etapes, ftp_w=ftp_w, seuil_pct=seuil_pct)
    if seuil is None:
        return etapes
    total = len(etapes)
    sortie = list(etapes)
    for indice, etape in enumerate(etapes):
        cible = etape.puissance_cible_w
        if cible is None or cible >= seuil:
            continue
        sortie[indice] = _retyper(etape, _type_par_position(indice, total))
    return sortie


def _seuil(etapes: list[Etape], *, ftp_w: float | None, seuil_pct: float) -> float | None:
    if ftp_w is not None:
        return seuil_pct * ftp_w
    cibles = [e.puissance_cible_w for e in etapes if e.puissance_cible_w is not None]
    if len(cibles) < 2 or min(cibles) == max(cibles):
        # Sans FTP et sans contraste, rien ne distingue un effort d'une
        # récupération : on ne devine pas, tout reste « bloc ».
        return None
    return (min(cibles) + max(cibles)) / 2


def _type_par_position(indice: int, total: int) -> str:
    if indice == 0:
        return "echauffement"
    if indice == total - 1:
        return "calme"
    return "recuperation"


def _retyper(etape: Etape, type_: str) -> Etape:
    return Etape(
        type=type_,
        duree_s=etape.duree_s,
        puissance_min_w=etape.puissance_min_w,
        puissance_max_w=etape.puissance_max_w,
        libelle=etape.libelle,
    )


def _marquer_elastiques(etapes: list[Etape]) -> list[Etape]:
    """Élastiques : la première étape si elle échauffe, la dernière si elle calme."""
    if not etapes:
        return etapes
    sortie = list(etapes)
    if sortie[0].type == "echauffement":
        sortie[0] = _elastique(sortie[0])
    if sortie[-1].type == "calme":
        sortie[-1] = _elastique(sortie[-1])
    return sortie


def _elastique(etape: Etape) -> Etape:
    return Etape(
        type=etape.type,
        duree_s=etape.duree_s,
        puissance_min_w=etape.puissance_min_w,
        puissance_max_w=etape.puissance_max_w,
        libelle=etape.libelle,
        elastique=True,
    )


# --- petits utilitaires ------------------------------------------------------------


def _octets(source: Entree) -> tuple[bytes, str | None]:
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


__all__ = ["lire_mrc"]
