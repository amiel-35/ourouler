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

**Le cas nominal est `%ftp`, et il est exact.** Comptage des 82 séances vélo
de 2026 sur le compte du mainteneur : 259 étapes en `%ftp`, 16 en
`power_zone`, 28 en `hr_zone`. Les séances de son coach et son plan Ironman
sont toutes en pourcentage de FTP ; elles se traduisent en watts sans
approximation et sans avertissement. Les zones de fréquence cardiaque sont
l'exception (un lot de séances de juin à septembre 2026), et c'est la seule
qui demande des précautions.

Les traductions, de la plus sûre à la moins sûre :

- `%ftp` → fraction × FTP. **Exact.** Une consigne `{start, end}` donne une
  fourchette, dont `Etape.puissance_cible_w` prend le milieu.
- `watts` → tel quel. Exact aussi, mais absent de ce compte.
- `power_zone` → bornes de la zone × FTP. C'est une **traduction** : la
  consigne était déjà en puissance.
- `hr_zone` **haute** (au-dessus de `ZONE_FC_BASSE_MAX`) → bornes de la zone
  de puissance de même numéro × FTP. C'est une **approximation**, mais elle
  tombe juste : une Z4 de FC donne 235-271 W pour 258 W de FTP, ce qui est
  bien du seuil.
- `hr_zone` **basse** (Z1, Z2) → `puissance_endurance_pct × FTP`. La table
  des zones ne sait pas traduire celles-là : la Z1 de puissance va de 0 à
  55 % de FTP, son milieu vaut 27,5 % — du pédalage à vide — et une zone
  ouverte vers le bas n'a pas de milieu qui veuille dire quelque chose. Une
  zone de FC n'est pas davantage la zone de puissance de même numéro : un
  plan qui écrit « Z1 de FC » pour une endurance désigne une puissance
  d'endurance franche. Le défaut, 60 % de FTP, est la médiane **mesurée** sur
  les sorties extérieures du mainteneur (Q11, close le 13/09/2026).

Seules les deux formes `hr_zone` font passer `meta["puissance_approximee"]`
à vrai, et le rendu l'affiche alors. `%ftp`, `watts` et `power_zone` ne
déclenchent aucun avertissement : il n'y a rien à avertir.

Ce module ne lit aucun fichier, ne connaît aucune configuration : la FTP et
les zones lui sont passées.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date

from ourouler.activites.modele import est_sport_velo
from ourouler.connecteurs.intervals import ClientIntervals
from ourouler.seance.modele import (
    PUISSANCE_ENDURANCE_PCT_DEFAUT,
    ZONE_FC_BASSE_MAX,
    ZONES_PUISSANCE_DEFAUT,
    Etape,
    Seance,
)

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
    puissance_endurance_pct: float = PUISSANCE_ENDURANCE_PCT_DEFAUT,
) -> Seance:
    """Construit une `Seance` à partir du `workout_doc` d'un événement Intervals.

    Ne lève jamais sur un document mal formé : un document vide, sans `steps`,
    ou dont tout est illisible donne une séance **sans étape**, et `meta` dit
    pourquoi. C'est l'appelant qui décide si une séance vide est utilisable —
    la commande, elle, l'affiche et le dit.
    """
    etat = _Etat(
        ftp_w=_ftp(ftp_w),
        zones=_zones(zones_puissance),
        endurance_pct=_pct(puissance_endurance_pct),
    )
    brut = doc.get("steps") if isinstance(doc, dict) else None
    lues = _aplatir(brut, etat=etat, profondeur=0, libelle="")
    etapes = _marquer_elastiques(_reclasser_libres(lues, etat=etat))
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
    puissance_endurance_pct: float = PUISSANCE_ENDURANCE_PCT_DEFAUT,
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
        puissance_endurance_pct=puissance_endurance_pct,
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

    def __init__(
        self,
        *,
        ftp_w: float | None,
        zones: tuple[tuple[float, float], ...],
        endurance_pct: float,
    ):
        self.ftp_w = ftp_w
        self.zones = zones
        self.endurance_pct = endurance_pct
        self.approximee = False
        self.fc_basses = 0  # étapes en zone de FC basse, calées sur l'endurance mesurée
        self.fc_hautes = 0  # étapes en zone de FC haute, traduites par la table des zones
        self.libres_reclassees: list[dict] = []
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
            "puissance_endurance_pct": self.endurance_pct,
        }
        if self.approximee:
            meta["approximation"] = (
                "consignes données en zones de fréquence cardiaque : les zones basses "
                f"(jusqu'à Z{ZONE_FC_BASSE_MAX}) sont calées sur la puissance d'endurance "
                "mesurée du cycliste, les zones hautes sur la table des zones de puissance"
            )
        for cle, valeur in (
            ("etapes_fc_basses", self.fc_basses),
            ("etapes_fc_hautes", self.fc_hautes),
            ("etapes_libres_reclassees", self.libres_reclassees),
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


@dataclass(frozen=True)
class _Lue:
    """Une étape et ce que l'aplatissement doit encore savoir d'elle.

    `sans_consigne` distingue « la source ne dit rien de l'intensité » de
    « la consigne existe mais n'a pas pu être convertie en watts » (un `%ftp`
    sans FTP disponible, par exemple). Les deux donnent une étape sans
    puissance, seule la première est du roulage libre.
    """

    etape: Etape
    sans_consigne: bool


def _aplatir(brut: object, *, etat: _Etat, profondeur: int, libelle: str) -> list[_Lue]:
    """Développe groupes et répétitions en une liste d'étapes, dans l'ordre."""
    if not isinstance(brut, list):
        if brut is not None:
            etat.elements_illisibles += 1
        return []
    if profondeur > PROFONDEUR_MAX:
        etat.trop_profond += 1
        return []
    etapes: list[_Lue] = []
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


def _groupe(groupe: dict, *, etat: _Etat, profondeur: int, libelle: str) -> list[_Lue]:
    reps = _reps(groupe.get("reps"))
    if reps <= 0:
        # `reps: 0` ou négatif : le groupe ne se roule pas. On ne le garde pas,
        # et on le compte — une séance qui perd un groupe doit pouvoir le dire.
        etat.groupes_ignores += 1
        return []
    texte = str(groupe.get("text") or "").strip()
    etapes: list[_Lue] = []
    for tour in range(1, reps + 1):
        prefixe = _joindre(libelle, _libelle_groupe(texte, tour, reps))
        etapes.extend(
            _aplatir(groupe["steps"], etat=etat, profondeur=profondeur + 1, libelle=prefixe)
        )
    return etapes


def _etape(step: dict, *, etat: _Etat, libelle: str) -> _Lue | None:
    duree = _nombre(step.get("duration"))
    if duree is None or duree <= 0:
        # Une étape de durée nulle ou absente ne se roule pas et n'occupe
        # aucun mètre de route : elle est écartée, et comptée.
        etat.nulles += 1
        return None
    bas, haut, descripteur, sans_consigne = _puissance(step, etat=etat)
    if bas is None and haut is None:
        etat.sans_puissance += 1
    return _Lue(
        etape=Etape(
            type=_type(step),
            duree_s=duree,
            puissance_min_w=bas,
            puissance_max_w=haut,
            libelle=_joindre(libelle, descripteur),
        ),
        sans_consigne=sans_consigne,
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


def _reclasser_libres(lues: list[_Lue], *, etat: _Etat) -> list[Etape]:
    """Une étape sans aucune consigne n'est pas un bloc : c'est du roulage libre.

    Décision du superviseur (13/09/2026). Sans puissance ni zone, rien ne
    contraint le terrain : chercher un couloir propre pour une telle étape
    n'a pas de sens, et la laisser typée « bloc » enverrait le placement
    (L4.3) travailler pour rien. Elle devient donc un échauffement si elle
    ouvre la séance, un retour au calme si elle la ferme, une récupération
    au milieu.

    Les marqueurs explicites de la source restent prioritaires : une étape
    libre déjà marquée `warmup`, `cooldown` ou `intensity=recovery` garde son
    type, seul le « sinon bloc » par défaut est corrigé.
    """
    etapes = [lue.etape for lue in lues]
    dernier = len(etapes) - 1
    for indice, lue in enumerate(lues):
        if not lue.sans_consigne or lue.etape.type != "bloc":
            continue
        if indice == 0:
            type_ = "echauffement"
        elif indice == dernier:
            type_ = "calme"
        else:
            type_ = "recuperation"
        etapes[indice] = _retyper(lue.etape, type_)
        etat.libres_reclassees.append({"indice": indice, "type": type_})
    return etapes


def _retyper(etape: Etape, type_: str) -> Etape:
    return Etape(
        type=type_,
        duree_s=etape.duree_s,
        puissance_min_w=etape.puissance_min_w,
        puissance_max_w=etape.puissance_max_w,
        libelle=etape.libelle,
        elastique=etape.elastique,
    )


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


def _puissance(step: dict, *, etat: _Etat) -> tuple[float | None, float | None, str, bool]:
    """(min, max, descripteur lisible, aucune consigne) d'une étape."""
    for champ in ("power", "hr"):
        consigne = step.get(champ)
        if isinstance(consigne, dict):
            bas, haut, descripteur = _depuis_consigne(consigne, etat=etat)
            # Une consigne illisible (unité inconnue, bornes absentes) reste
            # une consigne : la source a voulu dire quelque chose.
            return (bas, haut, descripteur, False)
    return (None, None, "libre", True)


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
    if fc and z_haut + 1 <= ZONE_FC_BASSE_MAX:
        # Zone de FC basse : la table des zones de puissance ne sait pas la
        # traduire (voir la docstring du module). On vise la puissance
        # d'endurance mesurée du cycliste, une valeur et non une fourchette.
        etat.fc_basses += 1
        puissance = etat.endurance_pct * etat.ftp_w
        return (puissance, puissance, nom + suffixe)
    if fc:
        etat.fc_hautes += 1
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


def _pct(brut: float) -> float:
    """La part de FTP visée en endurance. Une valeur inutilisable revient au défaut."""
    valeur = _nombre(brut)
    if valeur is None or not 0.0 < valeur <= 2.0:
        return PUISSANCE_ENDURANCE_PCT_DEFAUT
    return valeur


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
