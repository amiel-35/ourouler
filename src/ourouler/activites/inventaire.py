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
from ourouler.activites.modele import est_sport_velo
from ourouler.config import Config

#: Rattachement rendu pour une sortie manifestement faite en intérieur.
HOME_TRAINER = "home-trainer"

#: Rattachement rendu quand la configuration ne déclare aucun vélo exploitable.
INCONNU = "inconnu"

#: Une sortie plus courte que ça est signalée comme anomalie.
DUREE_MINIMALE_S = 600.0

#: Libellé de repli quand une entrée écartée n'a pas de sport nommé. Ne
#: devrait pas se produire (`est_sport_velo` compte un sport absent comme du
#: vélo), mais mieux vaut un libellé lisible qu'une chaîne vide.
SPORT_SANS_NOM = "sans sport"

#: Nombre de libellés cités dans la ligne « autres sports ignorés » ; au-delà,
#: la ligne dit « … » plutôt que de dérouler toute la liste.
LIBELLES_CITES = 4

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
    capteurs: list[str] = field(default_factory=list)
    """Valeurs distinctes de `power_meter` vues sur ce vélo, dans l'ordre
    d'apparition : c'est sur elles que repose la règle 2 du rattachement, le
    mainteneur doit pouvoir les lire sans ouvrir le cache."""

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
    autres_sports: int = 0
    """Entrées du cache écartées parce qu'elles ne sont pas du vélo (course à
    pied, natation, musculation…). Elles restent stockées, elles ne sont
    simplement pas comptées comme des sorties."""
    autres_sports_par_libelle: dict[str, int] = field(default_factory=dict)
    """Les libellés écartés et leur compte, du plus fréquent au moins
    fréquent. Le nombre seul ne suffisait pas : avec « Triathlon » parmi les
    libellés, le mainteneur ne pouvait pas savoir que quatre sorties vélo
    réelles venaient d'en sortir."""


# --- rattachement -------------------------------------------------------------


def rattacher_velo(entree: EntreeCache, config: Config) -> str:
    """Nom du vélo auquel rattacher une sortie.

    Ordre du contrat du sprint 2, §7 (lot L2.7) — il a changé depuis le
    sprint 1, où l'équipement primait sur tout :

    1. sortie en **intérieur** (`VirtualRide`, `meta["trainer"]`, appareil
       Zwift/Rouvy, `meta["interieur"]`) → « home-trainer » ;
    2. `meta["power_meter"]` égal au `capteur_puissance` non vide d'un vélo,
       à la casse et aux espaces près — c'est le signal le plus sûr, le
       capteur étant physiquement monté sur un vélo et un seul ;
    3. `meta["gear_id"]` égal à l'`intervals_gear_id` non vide d'un vélo, ou
       `equipement` égal (casse) à son `intervals_gear` non vide ;
    4. une période d'un vélo contient la date ;
    5. à défaut, le premier vélo d'usage route.

    L'intérieur passe devant parce qu'un capteur ou un équipement déclaré ne
    dit rien du lieu : une séance de home-trainer faite avec le capteur du
    vélo de route resterait comptée en sortie extérieure.
    """
    if en_interieur(entree):
        return HOME_TRAINER
    explicite = rattachement_explicite(entree, config)
    if explicite is not None:
        return explicite
    for velo in config.velos:
        if velo.usage == "route":
            return velo.nom
    return config.velos[0].nom if config.velos else INCONNU


def rattachement_explicite(entree: EntreeCache, config: Config) -> str | None:
    """Le vélo que la sortie **désigne elle-même** — étapes 2 à 4 de `rattacher_velo` —, ou `None`.

    Capteur, équipement Intervals ou période : un signal que la sortie porte,
    par opposition au repli « premier vélo de route » qui n'en est pas un.
    Sert à la calibration depuis l'écran (L9.4) : un compte à plusieurs vélos
    qui dépose des fichiers sans équipement ne doit pas voir toutes ses
    sorties créditées au premier vélo sans qu'on le lui dise.
    """
    capteur = _sans_blancs(entree.meta.get("power_meter"))
    if capteur:
        for velo in config.velos:
            if velo.capteur_puissance and _sans_blancs(velo.capteur_puissance) == capteur:
                return velo.nom

    gear_id = str(entree.meta.get("gear_id") or "").strip()
    if gear_id:
        for velo in config.velos:
            if velo.intervals_gear_id and velo.intervals_gear_id.strip() == gear_id:
                return velo.nom
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
    return None


def _sans_blancs(valeur: object) -> str:
    """Forme comparable d'un nom de capteur : sans aucun blanc, sans casse.

    « MARQUE 0000 », « marque0000 » et « MARQUE  0000 » désignent le même
    capteur : la valeur vient d'un champ libre côté Intervals, on ne la
    compare pas caractère à caractère.
    """
    if valeur is None:
        return ""
    return "".join(str(valeur).split()).casefold()


def en_interieur(entree: EntreeCache) -> bool:
    """Vrai si la sortie a manifestement été faite sur home-trainer."""
    if entree.meta.get("interieur") or entree.meta.get("trainer"):
        return True
    sport = (entree.sport or "").casefold().replace("_", "")
    if "virtual" in sport or "indoor" in sport:
        return True
    appareil = (entree.appareil or "").casefold()
    return any(marque in appareil for marque in APPAREILS_INTERIEUR)


# --- inventaire ---------------------------------------------------------------


def inventaire(cache: Cache, config: Config, depuis: date) -> Inventaire:
    """Ce que le cache contient en **vélo**, par vélo et par mois.

    Le cache peut contenir d'autres sports (le compte Intervals du mainteneur
    mêle course à pied, natation et musculation aux sorties) : ces entrées
    restent stockées mais sont écartées ici et comptées dans `autres_sports`,
    sans quoi « RCR : 697 sorties » additionnerait les footings.
    """
    toutes = cache.lister(depuis=depuis)
    entrees = [e for e in toutes if est_sport_velo(e.sport)]
    ecartees = [e for e in toutes if not est_sport_velo(e.sport)]
    inv = Inventaire(
        depuis=depuis,
        total=len(entrees),
        autres_sports=len(ecartees),
        autres_sports_par_libelle=_par_libelle(ecartees),
    )
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
        capteur = str(entree.meta.get("power_meter") or "").strip()
        if capteur and capteur not in stats.capteurs:
            stats.capteurs.append(capteur)
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


def _par_libelle(ecartees: list[EntreeCache]) -> dict[str, int]:
    """Les libellés de sport écartés et leur compte, du plus fréquent au moins."""
    comptes: dict[str, int] = {}
    for entree in ecartees:
        libelle = (entree.sport or "").strip() or SPORT_SANS_NOM
        comptes[libelle] = comptes.get(libelle, 0) + 1
    return dict(sorted(comptes.items(), key=lambda kv: (-kv[1], kv[0])))


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
    lignes.append(
        f"  {'vélo':<18}{'sorties':>8}{'km':>10}{'heures':>8}{'% puiss.':>10}"
        f"  {'capteur':<22}période"
    )
    for s in inv.par_velo:
        plage = f"{s.premiere or '?'} → {s.derniere or '?'}"
        lignes.append(
            f"  {s.velo:<18}{s.nombre:>8}{s.km:>10.0f}{s.heures:>8.0f}"
            f"{100 * s.part_puissance:>9.0f}%  {_capteurs(s):<22}{plage}"
        )

    lignes.append("")
    lignes.append("Par mois (sorties extérieures)")
    lignes.append(f"  {'mois':<10}{'sorties':>8}{'km':>10}{'dont puiss.':>13}")
    for m in inv.par_mois:
        lignes.append(
            f"  {m.mois:<10}{m.sorties:>8}{m.km:>10.0f}{m.sorties_avec_puissance:>13}"
        )

    lignes.append("")
    if inv.autres_sports:
        lignes.append(
            f"{inv.autres_sports} activité(s) d'autres sports ignorée(s){_libelles_ecartes(inv)}."
        )
        lignes.append("")
    if inv.anomalies:
        lignes.append(f"Anomalies ({len(inv.anomalies)})")
        for a in inv.anomalies:
            lignes.append(f"  {a.jour or '?'}  {a.identifiant[:12]}  {a.motif}")
    else:
        lignes.append("Aucune anomalie.")
    return "\n".join(lignes)


def _libelles_ecartes(inv: Inventaire) -> str:
    """« (Run 410, Swim 180, Triathlon 4…) » — dire *lesquels*, pas seulement combien.

    Avec « Triathlon » parmi les libellés écartés, le nombre seul ne permet
    pas de voir que des sorties vélo réelles viennent de sortir de
    l'inventaire (point 16 de la relecture du sprint 2).
    """
    comptes = list(inv.autres_sports_par_libelle.items())
    if not comptes:
        return ""
    cites = [f"{libelle} {nombre}" for libelle, nombre in comptes[:LIBELLES_CITES]]
    suite = "…" if len(comptes) > LIBELLES_CITES else ""
    return f" ({', '.join(cites)}{suite})"


def _capteurs(stats: StatsVelo) -> str:
    """Capteurs vus sur un vélo, en une cellule de tableau."""
    if not stats.capteurs:
        return "—"
    texte = ", ".join(stats.capteurs)
    return texte if len(texte) <= 21 else texte[:20] + "…"


def rendre_json(inv: Inventaire) -> dict:
    return {
        "depuis": inv.depuis.isoformat(),
        "total": inv.total,
        "autres_sports": inv.autres_sports,
        "autres_sports_par_libelle": dict(inv.autres_sports_par_libelle),
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
                "capteurs": list(s.capteurs),
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
