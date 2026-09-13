"""Lecture d'un `workout_doc` Intervals.icu vers une `Seance`.

Format **relevé le 13/09/2026 sur le compte du mainteneur**, et il est plus
libre que ce que le contrat de sprint §1 décrit :

- `doc["steps"]` mélange des **groupes** `{reps, text, duration, steps: [...]}`
  et des **étapes** directes `{duration, power|hr, ...}`. Les deux formes
  cohabitent dans la même séance (« 4x8 SV1 outdoor » du 22/04 : deux étapes
  libres, deux groupes `reps`, quatre étapes plates). La lecture est donc
  récursive : un élément qui porte une liste `steps` est un groupe, tout le
  reste est une étape.
- Une consigne se donne par `power` **ou** par `hr`, en
  `{units, value}` ou `{units, start, end}`. Unités observées : `%ftp`,
  `power_zone` (numéro de zone de puissance) et `hr_zone` (numéro de zone de
  fréquence cardiaque). Le contrat annonçait aussi `watts` : il est accepté,
  mais n'apparaît pas sur ce compte.
- Une étape peut n'avoir **aucune** consigne (`freeride: true`, ou rien) :
  elle est gardée, sans puissance. Le rendu le dit et aucune longueur de
  route ne lui est attribuée.

Deux traductions, et une seule est exacte :

- `power_zone` → bornes de la zone × FTP. C'est une **traduction** : la
  consigne était déjà en puissance.
- `hr_zone` → bornes de la zone de puissance **de même numéro** × FTP. C'est
  une **approximation**, et elle se dit : `meta["puissance_approximee"]` passe
  à vrai et le rendu l'affiche. Une zone de fréquence cardiaque n'est pas une
  zone de puissance — la FC dérive, traîne au départ d'un effort et monte
  seule à la chaleur. C'est la meilleure passerelle disponible sans modèle
  FC ↔ puissance, pas une équivalence.

Ce module ne lit aucun fichier, ne connaît aucune configuration : la FTP et
les zones lui sont passées.
"""

from __future__ import annotations

import math
from datetime import date

from ourouler.activites.modele import est_sport_velo
from ourouler.connecteurs.intervals import ClientIntervals
from ourouler.seance.modele import ZONES_PUISSANCE_DEFAUT, Etape, Seance

#: Profondeur d'imbrication maximale des groupes. Le format n'en impose
#: aucune ; trois niveaux ont été vus. Au-delà, on s'arrête plutôt que de
#: suivre un document cyclique ou malveillant, et `meta` le dit.
PROFONDEUR_MAX = 10

#: Nombre de répétitions maximal d'un groupe. `reps: 100000` ferait exploser
#: la mémoire pour une séance qui n'existe pas.
REPS_MAX = 500

#: Unités de puissance reconnues (en minuscules, sans espace).
UNITES_WATTS = ("watts", "w", "watt")
UNITES_POURCENT_FTP = ("%ftp", "ftp%", "percent_ftp", "pctftp")
UNITES_ZONE_PUISSANCE = ("power_zone", "powerzone")
UNITES_ZONE_FC = ("hr_zone", "hrzone", "heart_rate_zone")

#: Valeurs d'`intensity` qui désignent une récupération.
INTENSITES_RECUP = ("recovery", "rest", "recover")


def depuis_workout_doc(
    doc: dict,
    *,
    nom: str,
    jour: date,
    ftp_w: float | None,
    zones_puissance: tuple[tuple[float, float], ...] = ZONES_PUISSANCE_DEFAUT,
) -> Seance:
    """Construit une `Seance` à partir du `workout_doc` d'un événement Intervals.

    Ne lève jamais sur un document mal formé : un document vide, sans `steps`,
    ou dont tout est illisible donne une séance **sans étape**, et `meta` dit
    pourquoi. C'est l'appelant qui décide si une séance vide est utilisable —
    la commande, elle, l'affiche et le dit.
    """
    etat = _Etat(ftp_w=_ftp(ftp_w), zones=_zones(zones_puissance))
    brut = doc.get("steps") if isinstance(doc, dict) else None
    etapes = _aplatir(brut, etat=etat, profondeur=0, libelle="")
    etapes = _marquer_elastiques(etapes)
    duree_s = sum(e.duree_s for e in etapes)
    meta = etat.meta()
    meta["nom_source"] = str(nom)
    if isinstance(doc, dict):
        duree_doc = _nombre(doc.get("duration"))
        if duree_doc is not None:
            meta["duree_doc_s"] = duree_doc
            if abs(duree_doc - duree_s) > 1.0:
                meta["ecart_duree_doc_s"] = round(duree_doc - duree_s, 1)
        description = doc.get("description")
        if description:
            meta["description"] = str(description)
    if not etapes:
        meta["vide"] = True
    return Seance(nom=str(nom), jour=jour, etapes=etapes, duree_s=duree_s, meta=meta)


def seance_du_jour(
    client: ClientIntervals,
    jour: date,
    *,
    ftp_w: float | None,
    zones_puissance: tuple[tuple[float, float], ...] = ZONES_PUISSANCE_DEFAUT,
) -> Seance | None:
    """La séance **vélo** planifiée ce jour-là, ou `None` s'il n'y en a pas.

    Le calendrier du mainteneur porte plusieurs événements par jour (une nage
    et un vélo le 08/09, par exemple) et des entrées qui ne sont pas des
    séances (notes, congés). Le filtre est donc triple : catégorie
    « WORKOUT », sport reconnu comme du vélo par `activites.modele.
    est_sport_velo` — le même filtre que l'inventaire — et `workout_doc`
    présent. S'il reste plusieurs candidates, la première du calendrier est
    retenue et les autres sont nommées dans `meta["autres_seances"]`.
    """
    evenements = client.evenements(jour)
    candidates = [e for e in evenements if _est_seance_velo(e)]
    if not candidates:
        return None
    retenue, *autres = candidates
    seance = depuis_workout_doc(
        retenue.get("workout_doc") or {},
        nom=str(retenue.get("name") or "séance sans nom"),
        jour=jour,
        ftp_w=ftp_w,
        zones_puissance=zones_puissance,
    )
    seance.meta["source"] = "intervals"
    seance.meta["evenement_id"] = retenue.get("id")
    seance.meta["sport"] = retenue.get("type")
    if retenue.get("description") and "description" not in seance.meta:
        seance.meta["description"] = str(retenue["description"])
    if autres:
        seance.meta["autres_seances"] = [str(e.get("name") or "sans nom") for e in autres]
    return seance


# --- filtres ------------------------------------------------------------------


def _est_seance_velo(evenement: object) -> bool:
    if not isinstance(evenement, dict):
        return False
    categorie = str(evenement.get("category") or "WORKOUT").strip().casefold()
    if categorie != "workout":
        return False
    if not est_sport_velo(evenement.get("type")):
        return False
    return isinstance(evenement.get("workout_doc"), dict)


# --- aplatissement ------------------------------------------------------------


class _Etat:
    """Ce que l'aplatissement accumule en chemin, et qui finit dans `meta`."""

    def __init__(self, *, ftp_w: float | None, zones: tuple[tuple[float, float], ...]):
        self.ftp_w = ftp_w
        self.zones = zones
        self.approximee = False
        self.unites_inconnues: list[str] = []
        self.sans_puissance = 0
        self.nulles = 0
        self.groupes_ignores = 0
        self.trop_profond = 0
        self.elements_illisibles = 0
        self.ftp_manquante = 0

    def unite_inconnue(self, unite: str) -> None:
        if unite not in self.unites_inconnues:
            self.unites_inconnues.append(unite)

    def meta(self) -> dict:
        meta: dict = {
            "puissance_approximee": self.approximee,
            "ftp_w": self.ftp_w,
            "zones_puissance": [list(z) for z in self.zones],
        }
        if self.approximee:
            meta["approximation"] = (
                "puissance déduite des zones de fréquence cardiaque par la zone de "
                "puissance de même numéro — une FC n'est pas une puissance"
            )
        for cle, valeur in (
            ("unites_inconnues", self.unites_inconnues),
            ("etapes_sans_puissance", self.sans_puissance),
            ("etapes_nulles", self.nulles),
            ("groupes_ignores", self.groupes_ignores),
            ("groupes_trop_profonds", self.trop_profond),
            ("elements_illisibles", self.elements_illisibles),
            ("etapes_sans_ftp", self.ftp_manquante),
        ):
            if valeur:
                meta[cle] = valeur
        return meta


def _aplatir(brut: object, *, etat: _Etat, profondeur: int, libelle: str) -> list[Etape]:
    """Développe groupes et répétitions en une liste d'étapes, dans l'ordre."""
    if not isinstance(brut, list):
        if brut is not None:
            etat.elements_illisibles += 1
        return []
    if profondeur > PROFONDEUR_MAX:
        etat.trop_profond += 1
        return []
    etapes: list[Etape] = []
    for element in brut:
        if not isinstance(element, dict):
            etat.elements_illisibles += 1
            continue
        if isinstance(element.get("steps"), list):
            etapes.extend(_groupe(element, etat=etat, profondeur=profondeur, libelle=libelle))
        else:
            etape = _etape(element, etat=etat, libelle=libelle)
            if etape is not None:
                etapes.append(etape)
    return etapes


def _groupe(groupe: dict, *, etat: _Etat, profondeur: int, libelle: str) -> list[Etape]:
    reps = _reps(groupe.get("reps"))
    if reps <= 0:
        # `reps: 0` ou négatif : le groupe ne se roule pas. On ne le garde pas,
        # et on le compte — une séance qui perd un groupe doit pouvoir le dire.
        etat.groupes_ignores += 1
        return []
    texte = str(groupe.get("text") or "").strip()
    etapes: list[Etape] = []
    for tour in range(1, reps + 1):
        prefixe = _joindre(libelle, _libelle_groupe(texte, tour, reps))
        etapes.extend(
            _aplatir(groupe["steps"], etat=etat, profondeur=profondeur + 1, libelle=prefixe)
        )
    return etapes


def _etape(step: dict, *, etat: _Etat, libelle: str) -> Etape | None:
    duree = _nombre(step.get("duration"))
    if duree is None or duree <= 0:
        # Une étape de durée nulle ou absente ne se roule pas et n'occupe
        # aucun mètre de route : elle est écartée, et comptée.
        etat.nulles += 1
        return None
    bas, haut, descripteur = _puissance(step, etat=etat)
    if bas is None and haut is None:
        etat.sans_puissance += 1
    return Etape(
        type=_type(step),
        duree_s=duree,
        puissance_min_w=bas,
        puissance_max_w=haut,
        libelle=_joindre(libelle, descripteur),
    )


def _type(step: dict) -> str:
    """Le type d'une étape, dans l'ordre de priorité du contrat de sprint §1."""
    intensite = str(step.get("intensity") or "").strip().casefold()
    if step.get("warmup") is True or intensite == "warmup":
        return "echauffement"
    if step.get("cooldown") is True or intensite == "cooldown":
        return "calme"
    if intensite in INTENSITES_RECUP:
        return "recuperation"
    return "bloc"


def _marquer_elastiques(etapes: list[Etape]) -> list[Etape]:
    """Élastiques : la première étape si elle échauffe, la dernière si elle calme.

    Jamais ailleurs. Une récupération, courte ou longue, fait partie de la
    prescription (décision du mainteneur du 13/09).
    """
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


# --- consigne de puissance ----------------------------------------------------


def _puissance(step: dict, *, etat: _Etat) -> tuple[float | None, float | None, str]:
    """(min, max, descripteur lisible) d'une étape. `(None, None, …)` si muette."""
    for champ in ("power", "hr"):
        consigne = step.get(champ)
        if isinstance(consigne, dict):
            return _depuis_consigne(consigne, etat=etat)
    return (None, None, "libre" if step.get("freeride") else "")


def _depuis_consigne(consigne: dict, *, etat: _Etat) -> tuple[float | None, float | None, str]:
    """C'est `units` qui décide, jamais le champ porteur.

    Un `hr: {units: "%ftp"}` est une incohérence de la source ; l'unité écrite
    reste le renseignement le plus sûr, et une unité absente ou inconnue ne
    donne aucune puissance plutôt qu'une puissance devinée.
    """
    unite = "".join(str(consigne.get("units") or "").split()).casefold()
    bornes = _bornes(consigne)
    if bornes is None:
        return (None, None, "")
    bas, haut = bornes

    if unite in UNITES_WATTS:
        return (bas, haut, _descripteur(bas, haut, "W"))

    if unite in UNITES_POURCENT_FTP:
        if etat.ftp_w is None:
            etat.ftp_manquante += 1
            return (None, None, _descripteur(bas, haut, "% FTP"))
        return (
            bas * etat.ftp_w / 100.0,
            haut * etat.ftp_w / 100.0,
            _descripteur(bas, haut, "% FTP"),
        )

    if unite in UNITES_ZONE_FC:
        etat.approximee = True
        return _depuis_zones(bas, haut, etat=etat, fc=True)

    if unite in UNITES_ZONE_PUISSANCE:
        return _depuis_zones(bas, haut, etat=etat, fc=False)

    etat.unite_inconnue(str(consigne.get("units") or "(absente)"))
    return (None, None, "")


def _depuis_zones(
    bas: float, haut: float, *, etat: _Etat, fc: bool
) -> tuple[float | None, float | None, str]:
    """Traduit un intervalle de numéros de zone en fourchette de watts."""
    z_bas = _zone(bas, etat.zones)
    z_haut = _zone(haut, etat.zones)
    suffixe = " (FC)" if fc else ""
    nom = f"Z{z_bas + 1}" if z_bas == z_haut else f"Z{z_bas + 1}-Z{z_haut + 1}"
    if etat.ftp_w is None:
        etat.ftp_manquante += 1
        return (None, None, nom + suffixe)
    return (
        etat.zones[z_bas][0] * etat.ftp_w,
        etat.zones[z_haut][1] * etat.ftp_w,
        nom + suffixe,
    )


def _zone(valeur: float, zones: tuple[tuple[float, float], ...]) -> int:
    """Indice (0-based) de la zone demandée, ramené dans les bornes de la table."""
    indice = int(round(valeur)) - 1
    return max(0, min(len(zones) - 1, indice))


def _bornes(consigne: dict) -> tuple[float, float] | None:
    """(bas, haut) d'une consigne `{value}` ou `{start, end}`, ordonnés."""
    valeur = _nombre(consigne.get("value"))
    if valeur is not None:
        return (valeur, valeur)
    debut = _nombre(consigne.get("start"))
    fin = _nombre(consigne.get("end"))
    if debut is None and fin is None:
        return None
    if debut is None:
        return (fin, fin)  # type: ignore[arg-type]
    if fin is None:
        return (debut, debut)
    return (min(debut, fin), max(debut, fin))


def _descripteur(bas: float, haut: float, unite: str) -> str:
    if bas == haut:
        return f"{_nombre_court(bas)} {unite}"
    return f"{_nombre_court(bas)}-{_nombre_court(haut)} {unite}"


def _nombre_court(valeur: float) -> str:
    return f"{valeur:g}"


# --- petits utilitaires -------------------------------------------------------


def _joindre(*morceaux: str) -> str:
    return " · ".join(m for m in morceaux if m)


def _libelle_groupe(texte: str, tour: int, reps: int) -> str:
    if not texte:
        return f"{tour}/{reps}" if reps > 1 else ""
    return f"{texte} ({tour}/{reps})" if reps > 1 else texte


def _reps(brut: object) -> int:
    """Le nombre de répétitions d'un groupe : 1 par défaut, borné à `REPS_MAX`."""
    valeur = _nombre(brut)
    if valeur is None:
        return 1
    return min(int(valeur), REPS_MAX)


def _nombre(brut: object) -> float | None:
    """Un nombre lisible, ou `None`. Les booléens n'en sont pas."""
    if isinstance(brut, bool) or brut is None:
        return None
    try:
        valeur = float(brut)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return valeur if math.isfinite(valeur) else None


def _ftp(brut: float | None) -> float | None:
    valeur = _nombre(brut)
    return valeur if valeur is not None and valeur > 0 else None


def _zones(brut: object) -> tuple[tuple[float, float], ...]:
    """Table de zones utilisable, sinon celle par défaut. Jamais d'exception ici."""
    if not isinstance(brut, (list, tuple)) or not brut:
        return ZONES_PUISSANCE_DEFAUT
    table: list[tuple[float, float]] = []
    for zone in brut:
        if not isinstance(zone, (list, tuple)) or len(zone) != 2:
            return ZONES_PUISSANCE_DEFAUT
        bas, haut = _nombre(zone[0]), _nombre(zone[1])
        if bas is None or haut is None or bas < 0 or haut < 0:
            return ZONES_PUISSANCE_DEFAUT
        table.append((min(bas, haut), max(bas, haut)))
    return tuple(table)


__all__ = ["PROFONDEUR_MAX", "REPS_MAX", "depuis_workout_doc", "seance_du_jour"]
