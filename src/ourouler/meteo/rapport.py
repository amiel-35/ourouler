"""Rapport météo par direction : assemblage des cellules, rendu texte et JSON.

Deux modèles qui divergent ne sont **jamais** moyennés (doctrine §1) : le
désaccord est affiché comme tel, via `confiance` et le marqueur « ? ».
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime

from ourouler.config import Depart
from ourouler.meteo.couronne import NOM_ICI, PointCouronne, ecart_angulaire
from ourouler.meteo.openmeteo import PrevisionPoint

#: Au-delà, un modèle « annonce de la pluie ».
SEUIL_PLUIE_MM_H = 0.3
#: En dessous, un modèle « n'annonce pas de pluie ».
SEUIL_SEC_MM_H = 0.1
#: Écart de cumul en dessous duquel deux directions sont à égalité.
SEUIL_EGALITE_MM = 0.2
#: Demi-secteur du vent de face (et, en miroir, du vent de dos).
SECTEUR_VENT_DEG = 45.0

VENT_FACE = "face"
VENT_DOS = "dos"
VENT_TRAVERS = "travers"

CONFIANCE_ACCORD = "accord"
CONFIANCE_DESACCORD = "desaccord"
CONFIANCE_INCONNUE = "inconnu"

#: Lettre affichée dans la table pour chaque vent relatif.
LETTRE_VENT = {VENT_FACE: "f", VENT_DOS: "d", VENT_TRAVERS: "t"}

#: Largeur d'une cellule de la table. 12 suffisait pour « 0.0 14f 12°? » mais
#: pas pour une pluie à deux chiffres : « 12.5 100f -10°? » fait 15 caractères
#: (pluie 4 + vent 3 + lettre 1 + ressenti 4 + marqueur 1 + 2 espaces), et la
#: cellule débordait sur la colonne suivante. Mesuré par un test sur le rendu.
LARGEUR_CELLULE = 15
#: Largeur de la colonne des noms de direction (« NNE », « ici »).
LARGEUR_LIBELLE = 5

#: Noms français fixes : on ne dépend pas de la locale du système.
JOURS = ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche")
MOIS = (
    "janvier",
    "février",
    "mars",
    "avril",
    "mai",
    "juin",
    "juillet",
    "août",
    "septembre",
    "octobre",
    "novembre",
    "décembre",
)


def date_en_francais(t: datetime) -> str:
    """« samedi 13 septembre 2026 à 08h00 », sans dépendre de la locale."""
    return f"{JOURS[t.weekday()]} {t.day} {MOIS[t.month - 1]} {t.year} à {t:%Hh%M}"


def jour_en_francais(j: date) -> str:
    """« 13 septembre 2026 » — la même table de mois, sans l'heure.

    Un jour sans heure se dit sans heure : « le 17 septembre 2036 à 00h00 »
    ferait croire à une précision que la phrase n'a pas.
    """
    return f"{j.day} {MOIS[j.month - 1]} {j.year}"


@dataclass
class Cellule:
    """Une direction, une distance, une heure."""

    direction: str
    distance_km: float
    t: datetime
    pluie_mm: float | None
    pluie_second_avis_mm: float | None
    vent_kmh: float | None
    vent_depuis_deg: float | None
    vent_relatif: str | None
    ressenti_c: float | None
    confiance: str


@dataclass
class RapportMeteo:
    """Toutes les cellules d'un appel, plus ce qu'il faut pour les rendre."""

    depart: Depart
    debut: datetime
    horizon_h: int
    modele: str
    second_avis: str
    cellules: list[Cellule] = field(default_factory=list)

    def meilleure_direction(self) -> tuple[str, str]:
        """La direction où il pleut le moins, et le motif en une phrase.

        Cumul de pluie minimal sur l'horizon, toutes distances confondues ; à
        égalité (moins de 0,2 mm d'écart), on préfère le vent de face à
        l'aller — on rentre alors poussé, ce qui est le bon sens du cycliste.
        Le point « ici » n'est pas une direction : il est exclu.

        Une cellule de pluie absente n'ajoutait rien au cumul : une direction
        dont le modèle ne rendait aucune pluie affichait donc 0,0 mm et
        était **conseillée**, avec le motif « cumul de pluie le plus faible ».
        C'est l'affirmation sans mesure que la règle absolue 5 interdit. Les
        directions incomplètes sont donc écartées tant qu'il reste une
        direction complète ; s'il n'en reste aucune, on conseille la moins
        trouée et **le motif dit combien d'heures manquent**.
        """
        cumuls: dict[str, float] = {}
        faces: dict[str, int] = {}
        ordre: dict[str, int] = {}
        trous: dict[str, int] = {}
        for c in self.cellules:
            if c.direction == NOM_ICI:
                continue
            if c.direction not in cumuls:
                cumuls[c.direction] = 0.0
                faces[c.direction] = 0
                trous[c.direction] = 0
                ordre[c.direction] = len(ordre)
            if c.pluie_mm is None:
                trous[c.direction] += 1
            else:
                cumuls[c.direction] += c.pluie_mm
            if c.vent_relatif == VENT_FACE:
                faces[c.direction] += 1

        if not cumuls:
            return ("", "aucune prévision exploitable")

        completes = [d for d in cumuls if trous[d] == 0]
        if completes:
            candidates = completes
            ecartees = len(cumuls) - len(completes)
            reserve = f", {ecartees} direction(s) écartée(s) faute de données" if ecartees else ""
        else:
            # Aucune direction complète : on conseille quand même, mais en le disant.
            moins_troue = min(trous.values())
            candidates = [d for d in cumuls if trous[d] == moins_troue]
            reserve = f", {moins_troue} h sans donnée sur cette direction"

        mini = min(cumuls[d] for d in candidates)
        ex_aequo = [d for d in candidates if cumuls[d] - mini < SEUIL_EGALITE_MM]
        if len(ex_aequo) == 1:
            nom = ex_aequo[0]
            return (
                nom,
                f"cumul de pluie le plus faible sur l'horizon ({cumuls[nom]:.1f} mm){reserve}",
            )

        nom = max(ex_aequo, key=lambda d: (faces[d], -ordre[d]))
        egalite = f"{len(ex_aequo)} directions à égalité ({cumuls[nom]:.1f} mm de pluie)"
        if faces[nom]:
            return (nom, f"{egalite}, vent de face à l'aller{reserve}")
        return (nom, f"{egalite}, aucun vent de face à l'aller{reserve}")

    def distances(self) -> list[float]:
        """Les distances présentes, croissantes."""
        return sorted({c.distance_km for c in self.cellules})

    def heures(self) -> list[datetime]:
        """Les horodatages présents, croissants."""
        return sorted({c.t for c in self.cellules})


def vent_relatif(
    azimut_deg: float, vent_depuis_deg: float | None, *, direction: str | None = None
) -> str | None:
    """« face », « dos » ou « travers » pour qui **s'éloigne** du départ selon `azimut_deg`.

    `vent_depuis_deg` est la direction d'où vient le vent (convention
    météo). Vent de face = il vient de là où on va.

    Sur le point de départ (`direction == NOM_ICI`), il n'y a pas de « à
    l'aller » : la valeur est `None`. Ce point est créé avec un azimut de 0°,
    donc le calcul répondait « face » dès que le vent venait du nord — et
    cette valeur fausse partait telle quelle dans le JSON. Le rendu texte
    masquait la lettre, ce qui trompait un consommateur du JSON : il lisait
    `vent_relatif: "face"` sur « ici » sans rien pour le prévenir.
    """
    if direction == NOM_ICI or vent_depuis_deg is None:
        return None
    ecart = ecart_angulaire(azimut_deg, vent_depuis_deg)
    if ecart <= SECTEUR_VENT_DEG:
        return VENT_FACE
    if ecart >= 180.0 - SECTEUR_VENT_DEG:
        return VENT_DOS
    return VENT_TRAVERS


def confiance(pluie_mm: float | None, pluie_second_avis_mm: float | None) -> str:
    """« accord », « desaccord » ou « inconnu » entre les deux modèles, sur la pluie."""
    if pluie_mm is None or pluie_second_avis_mm is None:
        return CONFIANCE_INCONNUE
    a, b = pluie_mm, pluie_second_avis_mm
    if (a >= SEUIL_PLUIE_MM_H and b < SEUIL_SEC_MM_H) or (b >= SEUIL_PLUIE_MM_H and a < SEUIL_SEC_MM_H):
        return CONFIANCE_DESACCORD
    return CONFIANCE_ACCORD


def construire(
    depart: Depart,
    couronne: Sequence[PointCouronne],
    prevision_principale: Sequence[PrevisionPoint],
    prevision_second_avis: Sequence[PrevisionPoint] | None,
    debut: datetime,
    horizon_h: int,
    *,
    modele: str = "",
    second_avis: str = "",
) -> RapportMeteo:
    """Croise la couronne et les prévisions en une liste de cellules.

    `prevision_second_avis` peut être `None` **ou une liste vide** (second
    avis indisponible : modèle hors domaine, appel en échec, option non
    demandée) : la confiance de toutes les cellules vaut alors « inconnu ».
    Une liste vide levait `ValueError` — « 0 prévision pour 9 points » — donc
    une trace et un code 1 pour un second avis simplement absent, alors que
    `None` passait. Une liste **non vide** de la mauvaise longueur reste une
    erreur : là, les deux séries ne se correspondent pas.
    """
    if len(couronne) != len(prevision_principale):
        raise ValueError(
            f"{len(prevision_principale)} prévision(s) pour {len(couronne)} point(s) de couronne"
        )
    avec_second = bool(prevision_second_avis)
    if avec_second and len(prevision_second_avis) != len(couronne):  # type: ignore[arg-type]
        raise ValueError(
            f"second avis : {len(prevision_second_avis)} prévision(s) pour "  # type: ignore[arg-type]
            f"{len(couronne)} point(s) de couronne"
        )

    cellules: list[Cellule] = []
    for i, point in enumerate(couronne):
        # Le second avis peut ne pas couvrir exactement les mêmes heures :
        # on l'indexe par horodatage plutôt que par position.
        second_par_heure: dict[datetime, float | None] = {}
        if avec_second:
            second_par_heure = {h.t: h.pluie_mm for h in prevision_second_avis[i].heures}
        for heure in prevision_principale[i].heures:
            pluie_second = second_par_heure.get(heure.t) if avec_second else None
            cellules.append(
                Cellule(
                    direction=point.nom,
                    distance_km=point.distance_km,
                    t=heure.t,
                    pluie_mm=heure.pluie_mm,
                    pluie_second_avis_mm=pluie_second,
                    vent_kmh=heure.vent_kmh,
                    vent_depuis_deg=heure.vent_depuis_deg,
                    vent_relatif=vent_relatif(
                        point.azimut_deg, heure.vent_depuis_deg, direction=point.nom
                    ),
                    ressenti_c=heure.ressenti_c,
                    confiance=confiance(heure.pluie_mm, pluie_second),
                )
            )
    return RapportMeteo(
        depart=depart,
        debut=debut,
        horizon_h=horizon_h,
        modele=modele,
        second_avis=second_avis,
        cellules=cellules,
    )


# --- rendu texte ------------------------------------------------------------


def rendre_texte(rapport: RapportMeteo, distance_km: float | None = None) -> str:
    """Une table par distance : lignes = directions, colonnes = heures **locales**.

    Les heures sont calculées en UTC et affichées dans le fuseau du système.
    """
    lignes: list[str] = []
    local = rapport.debut.astimezone()
    fuseau = local.tzname() or "heure locale"
    lignes.append(
        f"Départ {rapport.depart.nom} — {date_en_francais(local)} ({fuseau}) — horizon {rapport.horizon_h} h"
    )
    lignes.append(f"Modèle {rapport.modele or '?'}, second avis {rapport.second_avis or 'aucun'}")
    lignes.append("Cellule : pluie mm | vent km/h + f=face d=dos t=travers (à l'aller) | ressenti °C")
    lignes.append("« ? » = les deux modèles ne sont pas d'accord sur la pluie ; « - » = valeur absente")

    distances = rapport.distances()
    if distance_km is not None:
        distances = [d for d in distances if abs(d - distance_km) < 1e-6]
        if not distances:
            lignes.append("")
            lignes.append(
                f"Aucune couronne à {distance_km:g} km "
                f"(disponibles : {', '.join(f'{d:g}' for d in rapport.distances())})."
            )
            return "\n".join(lignes)

    heures = rapport.heures()
    for d in distances:
        lignes.append("")
        lignes.append(f"── {d:g} km {'(sur place)' if d == 0 else ''}".rstrip())
        lignes.append(_ligne_entete(heures))
        for nom in _directions_a(rapport, d):
            lignes.append(_ligne_direction(rapport, d, nom, heures))

    nom, motif = rapport.meilleure_direction()
    lignes.append("")
    if nom:
        lignes.append(f"Direction conseillée : {nom} — {motif}.")
    else:
        lignes.append(f"Direction conseillée : indéterminée — {motif}.")
    return "\n".join(lignes)


def _directions_a(rapport: RapportMeteo, distance: float) -> list[str]:
    """Les directions présentes à cette distance, dans l'ordre de la couronne."""
    noms: list[str] = []
    for c in rapport.cellules:
        if c.distance_km == distance and c.direction not in noms:
            noms.append(c.direction)
    return noms


def _ligne_entete(heures: Sequence[datetime]) -> str:
    cases = [f"{t.astimezone():%H}h".ljust(LARGEUR_CELLULE) for t in heures]
    return " ".ljust(LARGEUR_LIBELLE) + " ".join(cases).rstrip()


def _ligne_direction(rapport: RapportMeteo, distance: float, nom: str, heures: Sequence[datetime]) -> str:
    par_heure = {c.t: c for c in rapport.cellules if c.distance_km == distance and c.direction == nom}
    cases = [_case(par_heure.get(t)).ljust(LARGEUR_CELLULE) for t in heures]
    return nom.ljust(LARGEUR_LIBELLE) + " ".join(cases).rstrip()


def _case(cellule: Cellule | None) -> str:
    """La cellule compacte : « 0.0 14f 12° », suivie de « ? » en cas de désaccord.

    Pas de cas particulier pour « ici » : sa cellule porte désormais
    `vent_relatif = None` (voir `vent_relatif`), donc aucune lettre à
    afficher — la règle générale « pas de vent relatif, pas de lettre »
    suffit, ici comme pour une direction dont le vent est inconnu.
    """
    if cellule is None:
        return "-"
    pluie = f"{cellule.pluie_mm:.1f}" if cellule.pluie_mm is not None else "-"
    if cellule.vent_kmh is None:
        vent = "-"
    else:
        vent = f"{cellule.vent_kmh:.0f}{LETTRE_VENT.get(cellule.vent_relatif or '', '')}"
    ressenti = f"{cellule.ressenti_c:.0f}°" if cellule.ressenti_c is not None else "-"
    marqueur = "?" if cellule.confiance == CONFIANCE_DESACCORD else ""
    return f"{pluie} {vent} {ressenti}{marqueur}"


# --- rendu JSON -------------------------------------------------------------


def rendre_json(rapport: RapportMeteo) -> dict:
    """Le rapport en structures sérialisables JSON (horodatages ISO 8601 en UTC)."""
    nom, motif = rapport.meilleure_direction()
    return {
        "depart": {
            "nom": rapport.depart.nom,
            "latitude": rapport.depart.latitude,
            "longitude": rapport.depart.longitude,
        },
        "debut": rapport.debut.isoformat(),
        "horizon_h": rapport.horizon_h,
        "modele": rapport.modele,
        "second_avis": rapport.second_avis,
        "meilleure_direction": {"nom": nom, "motif": motif},
        "cellules": [
            {
                "direction": c.direction,
                "distance_km": c.distance_km,
                "t": c.t.isoformat(),
                "pluie_mm": c.pluie_mm,
                "pluie_second_avis_mm": c.pluie_second_avis_mm,
                "vent_kmh": c.vent_kmh,
                "vent_depuis_deg": c.vent_depuis_deg,
                "vent_relatif": c.vent_relatif,
                "ressenti_c": c.ressenti_c,
                "confiance": c.confiance,
            }
            for c in rapport.cellules
        ],
    }
