"""Inventaire : ce que le cache contient, par vélo et par mois.

Sert à répondre « de quoi disposera la calibration ? » avant de calibrer
quoi que ce soit : combien de sorties, avec quel vélo, avec ou sans
puissance, et quelles entrées sont suspectes.

Ne lit ni configuration, ni environnement : reçoit un `Cache` et une `Config`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from ourouler.activites.cache import Cache, EntreeCache
from ourouler.config import Config

#: Rattachement rendu pour une sortie manifestement faite en intérieur.
HOME_TRAINER = "home-trainer"

#: Rattachement rendu quand la configuration ne déclare aucun vélo exploitable.
INCONNU = "inconnu"

#: Une sortie plus courte que ça est signalée comme anomalie.
DUREE_MINIMALE_S = 600.0

#: Marques d'appareil qui signent une sortie en intérieur.
APPAREILS_INTERIEUR = ("zwift", "rouvy", "trainerroad", "bkool", "mywhoosh", "indievelo")


@dataclass
class StatsVelo:
    velo: str
    nombre: int = 0
    km: float = 0.0
    heures: float = 0.0
    premiere: date | None = None
    derniere: date | None = None
    avec_puissance: int = 0

    @property
    def part_puissance(self) -> float:
        """Part des sorties de ce vélo qui portent une puissance, entre 0 et 1."""
        return self.avec_puissance / self.nombre if self.nombre else 0.0


@dataclass
class StatsMois:
    mois: str  # "AAAA-MM"
    sorties: int = 0  # sorties extérieures seulement
    km: float = 0.0
    sorties_avec_puissance: int = 0


@dataclass
class Anomalie:
    identifiant: str
    jour: date | None
    motif: str


@dataclass
class Inventaire:
    depuis: date
    total: int = 0
    par_velo: list[StatsVelo] = field(default_factory=list)
    par_mois: list[StatsMois] = field(default_factory=list)
    anomalies: list[Anomalie] = field(default_factory=list)


# --- rattachement -------------------------------------------------------------


def rattacher_velo(entree: EntreeCache, config: Config) -> str:
    """Nom du vélo auquel rattacher une sortie.

    Dans l'ordre du contrat : (1) l'équipement de la source correspond au
    `intervals_gear` d'un vélo ; (2) une période d'un vélo contient la date ;
    (3) sortie en intérieur ; (4) à défaut le premier vélo d'usage route.
    """
    equipement = (entree.equipement or "").strip().casefold()
    if equipement:
        for velo in config.velos:
            if velo.intervals_gear and velo.intervals_gear.strip().casefold() == equipement:
                return velo.nom

    jour = entree.jour
    if jour is not None:
        for velo in config.velos:
            if any(periode.contient(jour) for periode in velo.periodes):
                return velo.nom

    if en_interieur(entree):
        return HOME_TRAINER

    for velo in config.velos:
        if velo.usage == "route":
            return velo.nom
    return config.velos[0].nom if config.velos else INCONNU


def en_interieur(entree: EntreeCache) -> bool:
    """Vrai si la sortie a manifestement été faite sur home-trainer."""
    if entree.meta.get("interieur"):
        return True
    sport = (entree.sport or "").casefold().replace("_", "")
    if "virtual" in sport or "indoor" in sport:
        return True
    appareil = (entree.appareil or "").casefold()
    return any(marque in appareil for marque in APPAREILS_INTERIEUR)


# --- inventaire ---------------------------------------------------------------


def inventaire(cache: Cache, config: Config, depuis: date) -> Inventaire:
    entrees = cache.lister(depuis=depuis)
    inv = Inventaire(depuis=depuis, total=len(entrees))
    velos: dict[str, StatsVelo] = {}
    mois: dict[str, StatsMois] = {}

    for entree in entrees:
        nom_velo = rattacher_velo(entree, config)
        km = (entree.distance_m or 0.0) / 1000.0
        heures = (entree.duree_s or 0.0) / 3600.0
        avec_puissance = entree.puissance_moy_w is not None

        stats = velos.setdefault(nom_velo, StatsVelo(velo=nom_velo))
        stats.nombre += 1
        stats.km += km
        stats.heures += heures
        stats.avec_puissance += int(avec_puissance)
        jour = entree.jour
        if jour is not None:
            stats.premiere = jour if stats.premiere is None else min(stats.premiere, jour)
            stats.derniere = jour if stats.derniere is None else max(stats.derniere, jour)

        if jour is not None and not en_interieur(entree):
            clef = f"{jour.year:04d}-{jour.month:02d}"
            par_mois = mois.setdefault(clef, StatsMois(mois=clef))
            par_mois.sorties += 1
            par_mois.km += km
            par_mois.sorties_avec_puissance += int(avec_puissance)

        inv.anomalies.extend(_anomalies(entree))

    inv.par_velo = sorted(velos.values(), key=lambda s: (-s.nombre, s.velo))
    inv.par_mois = sorted(mois.values(), key=lambda s: s.mois)
    return inv


def _anomalies(entree: EntreeCache) -> list[Anomalie]:
    trouvees = []
    if entree.duree_s is not None and entree.duree_s < DUREE_MINIMALE_S:
        trouvees.append(f"durée {entree.duree_s:.0f} s (< 10 min)")
    if not entree.distance_m:
        trouvees.append("distance nulle")
    if entree.puissance_moy_w is None:
        trouvees.append("sans puissance")
    return [Anomalie(entree.identifiant, entree.jour, motif) for motif in trouvees]


# --- rendus -------------------------------------------------------------------


def rendre_texte(inv: Inventaire) -> str:
    lignes = [f"Inventaire des sorties depuis le {inv.depuis.isoformat()} — {inv.total} activité(s)"]
    if not inv.total:
        lignes.append("")
        lignes.append("Cache vide : importer un dossier (--importer) ou synchroniser (--synchroniser).")
        return "\n".join(lignes)

    lignes.append("")
    lignes.append("Par vélo")
    lignes.append(f"  {'vélo':<18}{'sorties':>8}{'km':>10}{'heures':>8}{'% puiss.':>10}  période")
    for s in inv.par_velo:
        plage = f"{s.premiere or '?'} → {s.derniere or '?'}"
        lignes.append(
            f"  {s.velo:<18}{s.nombre:>8}{s.km:>10.0f}{s.heures:>8.0f}"
            f"{100 * s.part_puissance:>9.0f}%  {plage}"
        )

    lignes.append("")
    lignes.append("Par mois (sorties extérieures)")
    lignes.append(f"  {'mois':<10}{'sorties':>8}{'km':>10}{'dont puiss.':>13}")
    for m in inv.par_mois:
        lignes.append(
            f"  {m.mois:<10}{m.sorties:>8}{m.km:>10.0f}{m.sorties_avec_puissance:>13}"
        )

    lignes.append("")
    if inv.anomalies:
        lignes.append(f"Anomalies ({len(inv.anomalies)})")
        for a in inv.anomalies:
            lignes.append(f"  {a.jour or '?'}  {a.identifiant[:12]}  {a.motif}")
    else:
        lignes.append("Aucune anomalie.")
    return "\n".join(lignes)


def rendre_json(inv: Inventaire) -> dict:
    return {
        "depuis": inv.depuis.isoformat(),
        "total": inv.total,
        "par_velo": [
            {
                "velo": s.velo,
                "nombre": s.nombre,
                "km": round(s.km, 1),
                "heures": round(s.heures, 2),
                "premiere": s.premiere.isoformat() if s.premiere else None,
                "derniere": s.derniere.isoformat() if s.derniere else None,
                "avec_puissance": s.avec_puissance,
                "part_puissance": round(s.part_puissance, 3),
            }
            for s in inv.par_velo
        ],
        "par_mois": [
            {
                "mois": m.mois,
                "sorties": m.sorties,
                "km": round(m.km, 1),
                "sorties_avec_puissance": m.sorties_avec_puissance,
            }
            for m in inv.par_mois
        ],
        "anomalies": [
            {
                "identifiant": a.identifiant,
                "jour": a.jour.isoformat() if a.jour else None,
                "motif": a.motif,
            }
            for a in inv.anomalies
        ],
    }
