"""Lecteur de fichier de séance Zwift (`.ZWO`) vers `Seance`.

Le `.ZWO` est un fichier XML, lu avec `xml.etree` de la bibliothèque
standard — le même mécanisme que pour le TCX (`activites/lecture.py`),
**aucune dépendance nouvelle**.

Six balises de bloc sont couvertes sous `<workout>`, chacune explicitement :

- `Warmup` / `Cooldown` — une rampe de puissance (`PowerLow` à
  `PowerHigh`) ; ce sont les seules étapes élastiques, comme pour une
  séance Intervals.icu (décision du mainteneur du 13/09, `seance/modele.py`
  `TYPES_ELASTIQUES`).
- `SteadyState` — un bloc à puissance fixe (`Power`).
- `Ramp` — un bloc à puissance variable (`PowerLow` à `PowerHigh`). Traité
  comme un bloc, pas comme un échauffement : rien dans le fichier ne dit
  qu'une rampe est un `Warmup` déguisé, et ce lecteur ne devine pas ce que
  la balise ne dit pas — seule sa position (voir plus bas) peut encore le
  corriger si elle se trouve sans aucune puissance exploitable.
- `IntervalsT` — une répétition qui se déplie : `Repeat` fois la paire
  (`OnDuration`/`OnPower` → bloc, `OffDuration`/`OffPower` → récupération).
- `FreeRide` — aucune consigne de puissance. Comme une étape sans consigne
  d'Intervals.icu (`seance/intervals.py` `_reclasser_libres`), elle n'est
  pas un bloc : elle est retypée selon sa position dans la séance
  (échauffement en tête, calme en queue, récupération au milieu).

Le même retypage par position s'applique à toute `SteadyState` ou `Ramp`
qui se retrouve sans la moindre puissance exploitable (pas de `Power`, pas
de `PowerLow`/`PowerHigh`, ou une FTP manquante) : sans consigne, rien ne
contraint le terrain, ce n'est pas un bloc (même raisonnement que pour
Intervals.icu).

`<textevent>` (les indications textuelles à l'écran pendant la séance, sans
durée ni puissance propres) est une balise reconnue mais **ignorée** :
Zwift l'exporte couramment aux côtés des blocs, et elle ne décrit aucune
étape à rouler. Toute autre balise inconnue sous `<workout>` fait échouer
la lecture avec `ErreurLecture` qui la nomme : on ne devine pas ce qu'on ne
connaît pas.

Les puissances du `.ZWO` sont **toujours** une fraction de FTP (`0.65` pour
65 %), jamais des watts. La conversion utilise la FTP fournie par
l'appelant — jamais lue depuis un fichier ou une configuration ici — et le
résultat le dit toujours dans `Seance.meta["conversion"]` : c'est un point
d'interface (quelqu'un qui voit 220 W là où il attendait 250 vient
d'apprendre que sa FTP est mal renseignée), pas un détail technique à
taire. Sans FTP, aucune puissance n'est calculée et `meta` compte les
étapes concernées.

Ce module ne lit aucune configuration, ne touche pas le réseau.
"""

from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from datetime import date
from pathlib import Path

from ourouler.noyau.erreurs import ErreurLecture
from ourouler.noyau.seance import Etape, Seance

Entree = Path | str | bytes | bytearray

#: Balises de bloc reconnues sous `<workout>`, traduites en étapes.
BALISES_CONNUES = ("SteadyState", "Warmup", "Cooldown", "Ramp", "IntervalsT", "FreeRide")

#: Balises reconnues mais sans étape à en tirer (cues texte à l'écran).
BALISES_IGNOREES = ("textevent",)

#: Répétitions maximales d'un `IntervalsT` (même garde-fou qu'Intervals.icu,
#: voir `seance/intervals.py` `REPS_MAX` : `Repeat="100000"` ferait exploser
#: la mémoire pour une séance qui n'existe pas).
REPS_MAX = 500


def lire_zwo(
    source: Entree,
    *,
    ftp_w: float | None = None,
    nom: str | None = None,
    jour: date | None = None,
) -> Seance:
    """Lit un `.ZWO` (Zwift workout, XML) vers une `Seance`.

    Lève `ErreurLecture` si le fichier est vide, mal formé, sans balise
    `<workout>`, ou s'il porte un bloc dont ce lecteur ne connaît pas la
    forme. `jour` vaut la date du jour si omis — cette séance-fichier n'a
    pas de date propre, c'est l'appelant (la commande) qui sait pour quel
    jour elle est importée.
    """
    contenu, fichier = _octets(source)
    try:
        racine = ET.fromstring(contenu)
    except ET.ParseError as e:
        raise ErreurLecture(f"{fichier or '<octets>'} : ZWO illisible ({e})") from e

    workout = racine.find("workout")
    if workout is None:
        raise ErreurLecture(f"{fichier or '<octets>'} : ZWO sans balise <workout>")

    compteurs: dict[str, int] = {}
    paires: list[tuple[Etape, bool, bool]] = []
    for element in workout:
        if not isinstance(element.tag, str):
            continue  # commentaire XML ou autre nœud sans nom de balise
        paires.extend(_bloc(element, ftp_w=ftp_w, compteurs=compteurs, fichier=fichier))

    etapes = _reclasser_sans_consigne(
        [e for e, _, _ in paires], [d for _, d, _ in paires], [s for _, _, s in paires]
    )
    etapes = _marquer_elastiques(etapes)

    meta: dict = {"source": "zwo", "ftp_w": ftp_w}
    if ftp_w is not None:
        meta["conversion"] = f"pourcentages de FTP convertis en watts avec une FTP de {ftp_w:g} W"
    else:
        meta["conversion"] = (
            "FTP inconnue : aucune consigne en pourcentage de FTP n'a pu être convertie en watts"
        )
    for cle in ("etapes_ignorees", "groupes_ignores", "etapes_sans_ftp"):
        if compteurs.get(cle):
            meta[cle] = compteurs[cle]

    description = _texte(racine, "description")
    if description:
        meta["description"] = description
    nom_seance = nom or _texte(racine, "name") or (fichier or "séance ZWO")
    duree_s = sum(e.duree_s for e in etapes)
    return Seance(
        nom=str(nom_seance),
        jour=jour or date.today(),
        etapes=etapes,
        duree_s=duree_s,
        meta=meta,
    )


# --- un bloc -------------------------------------------------------------------


def _bloc(
    element: ET.Element, *, ftp_w: float | None, compteurs: dict[str, int], fichier: str | None
) -> list[tuple[Etape, bool, bool]]:
    """Une balise de `<workout>` vers 0, 1 ou plusieurs (étape, défaut, sans_consigne).

    `defaut` dit si le type assigné est provisoire (`True`, sujet au
    retypage par position) ou définitif parce que la balise elle-même le
    dit (`False` : `Warmup`, `Cooldown`, et les moitiés d'un `IntervalsT`).

    `sans_consigne` dit si la balise ne porte **structurellement** aucune
    puissance (`FreeRide`, ou un `Power`/`PowerLow`/`PowerHigh` absent) —
    c'est ce qui déclenche le retypage, pas le simple fait que la FTP
    manque pour convertir une consigne pourtant présente : une `SteadyState`
    à « 90 % » reste un bloc même sans FTP, elle est juste non chiffrée.
    """
    balise = element.tag
    if balise in BALISES_IGNOREES:
        return []
    if balise == "Warmup":
        return _etape_simple(element, type_="echauffement", ftp_w=ftp_w, compteurs=compteurs, defaut=False)
    if balise == "Cooldown":
        return _etape_simple(element, type_="calme", ftp_w=ftp_w, compteurs=compteurs, defaut=False)
    if balise == "SteadyState":
        return _etape_simple(element, type_="bloc", ftp_w=ftp_w, compteurs=compteurs, defaut=True)
    if balise == "Ramp":
        return _etape_simple(element, type_="bloc", ftp_w=ftp_w, compteurs=compteurs, defaut=True)
    if balise == "FreeRide":
        return _etape_freeride(element, compteurs=compteurs)
    if balise == "IntervalsT":
        return _intervalles(element, ftp_w=ftp_w, compteurs=compteurs)
    raise ErreurLecture(
        f"{fichier or '<octets>'} : bloc <{balise}> non pris en charge par ce lecteur "
        f"(connus : {', '.join(BALISES_CONNUES)})"
    )


def _etape_simple(
    element: ET.Element, *, type_: str, ftp_w: float | None, compteurs: dict[str, int], defaut: bool
) -> list[tuple[Etape, bool, bool]]:
    duree = _flottant(element.get("Duration"))
    if duree is None or duree <= 0:
        compteurs["etapes_ignorees"] = compteurs.get("etapes_ignorees", 0) + 1
        return []
    bas_pct, haut_pct = _pct(element)
    sans_consigne = bas_pct is None and haut_pct is None
    bas_w, haut_w = _bornes_watts(bas_pct, haut_pct, ftp_w, compteurs=compteurs)
    etape = Etape(
        type=type_,
        duree_s=duree,
        puissance_min_w=bas_w,
        puissance_max_w=haut_w,
        libelle=_libelle(bas_pct, haut_pct),
    )
    return [(etape, defaut, sans_consigne)]


def _etape_freeride(element: ET.Element, *, compteurs: dict[str, int]) -> list[tuple[Etape, bool, bool]]:
    duree = _flottant(element.get("Duration"))
    if duree is None or duree <= 0:
        compteurs["etapes_ignorees"] = compteurs.get("etapes_ignorees", 0) + 1
        return []
    etape = Etape(type="bloc", duree_s=duree, puissance_min_w=None, puissance_max_w=None, libelle="libre")
    return [(etape, True, True)]


def _intervalles(
    element: ET.Element, *, ftp_w: float | None, compteurs: dict[str, int]
) -> list[tuple[Etape, bool, bool]]:
    """`IntervalsT` : une répétition qui se déplie en paires (effort, récupération)."""
    reps = _entier(element.get("Repeat"))
    if reps is None or reps <= 0:
        compteurs["groupes_ignores"] = compteurs.get("groupes_ignores", 0) + 1
        return []
    reps = min(reps, REPS_MAX)
    on_duree = _flottant(element.get("OnDuration"))
    off_duree = _flottant(element.get("OffDuration"))
    on_pct = _flottant(element.get("OnPower"))
    off_pct = _flottant(element.get("OffPower"))

    resultat: list[tuple[Etape, bool, bool]] = []
    for tour in range(1, reps + 1):
        for duree, pct, type_ in ((on_duree, on_pct, "bloc"), (off_duree, off_pct, "recuperation")):
            if duree is None or duree <= 0:
                compteurs["etapes_ignorees"] = compteurs.get("etapes_ignorees", 0) + 1
                continue
            bas_w, haut_w = _bornes_watts(pct, pct, ftp_w, compteurs=compteurs)
            resultat.append(
                (
                    Etape(
                        type=type_,
                        duree_s=duree,
                        puissance_min_w=bas_w,
                        puissance_max_w=haut_w,
                        libelle=_joindre(f"{tour}/{reps}", _libelle(pct, pct)),
                    ),
                    False,
                    pct is None,
                )
            )
    return resultat


# --- retypage par position, comme la troisième règle d'Intervals.icu ----------


def _reclasser_sans_consigne(
    etapes: list[Etape], defauts: list[bool], sans_consignes: list[bool]
) -> list[Etape]:
    """Une `SteadyState`/`Ramp`/`FreeRide` sans aucune puissance n'est pas un bloc.

    Seules les étapes marquées « type par défaut » (`defaut=True`) **et**
    structurellement sans consigne sont concernées : un `Warmup`, un
    `Cooldown` ou une moitié d'`IntervalsT` garde son type quoi qu'il
    arrive, et une consigne présente mais non convertible faute de FTP
    reste un bloc, juste sans watts chiffrés.
    """
    total = len(etapes)
    sortie = list(etapes)
    for indice, (etape, defaut, sans_consigne) in enumerate(
        zip(etapes, defauts, sans_consignes, strict=True)
    ):
        if not defaut or not sans_consigne:
            continue
        sortie[indice] = _retyper(etape, _type_par_position(indice, total))
    return sortie


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


# --- puissance ------------------------------------------------------------------


def _pct(element: ET.Element) -> tuple[float | None, float | None]:
    """(bas, haut) en fraction de FTP, depuis `Power` ou `PowerLow`/`PowerHigh`."""
    valeur = _flottant(element.get("Power"))
    if valeur is not None:
        return (valeur, valeur)
    bas = _flottant(element.get("PowerLow"))
    haut = _flottant(element.get("PowerHigh"))
    if bas is None and haut is None:
        return (None, None)
    return (bas if bas is not None else haut, haut if haut is not None else bas)


def _bornes_watts(
    bas_pct: float | None, haut_pct: float | None, ftp_w: float | None, *, compteurs: dict[str, int]
) -> tuple[float | None, float | None]:
    if bas_pct is None and haut_pct is None:
        return (None, None)
    if ftp_w is None:
        compteurs["etapes_sans_ftp"] = compteurs.get("etapes_sans_ftp", 0) + 1
        return (None, None)
    bas = bas_pct * ftp_w if bas_pct is not None else None
    haut = haut_pct * ftp_w if haut_pct is not None else None
    if (bas is not None and bas < 0) or (haut is not None and haut < 0):
        # Une puissance négative est une consigne illisible (voir la même
        # décision dans `seance/intervals.py`), pas un ordre de freiner.
        return (None, None)
    return (bas, haut)


def _libelle(bas_pct: float | None, haut_pct: float | None) -> str:
    if bas_pct is None and haut_pct is None:
        return "libre"
    if bas_pct == haut_pct:
        return f"{_court(bas_pct * 100)}% FTP"
    return f"{_court(bas_pct * 100)}-{_court(haut_pct * 100)}% FTP"


def _court(valeur: float) -> str:
    return f"{valeur:g}"


def _joindre(*morceaux: str) -> str:
    return " · ".join(m for m in morceaux if m)


# --- petits utilitaires ---------------------------------------------------------


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


def _flottant(valeur: str | None) -> float | None:
    if valeur is None:
        return None
    try:
        nombre = float(valeur)
    except ValueError:
        return None
    return nombre if math.isfinite(nombre) else None


def _entier(valeur: str | None) -> int | None:
    nombre = _flottant(valeur)
    return int(nombre) if nombre is not None else None


def _texte(racine: ET.Element, balise: str) -> str | None:
    element = racine.find(balise)
    if element is None or element.text is None:
        return None
    texte = element.text.strip()
    return texte or None


__all__ = [
    "BALISES_CONNUES",
    "BALISES_IGNOREES",
    "REPS_MAX",
    "lire_zwo",
]
