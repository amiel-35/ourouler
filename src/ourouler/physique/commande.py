"""Sous-commandes `ourouler calibrer` et `ourouler simuler`.

Ce module est la couche qui **touche les fichiers** : il lit le cache, écrit
`calibration.json` et relit ce dernier pour les autres commandes. Le cœur
(`physique.modele`, `physique.calibration`) ne connaît aucun chemin : il reçoit
des objets déjà construits, comme `boucle.commande` le fait pour les tracés.

`calibrer` enchaîne : choix des sorties → archives météo (mémoïsées) →
échantillons → deux passes d'ajustement → validation sur les sorties les plus
récentes → rapport et JSON. Les appels réseau sont ceux de l'archive, un par
jour de sortie, et une seule fois dans la vie du cache.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from ourouler.activites.cache import Cache
from ourouler.boucle.gpx import lire_gpx_trace
from ourouler.config import Config, Velo
from ourouler.connecteurs.openmeteo_archive import NOM_CACHE, ClientArchive
from ourouler.erreurs import ErreurConnecteur, ErreurUtilisateur
from ourouler.meteo.openmeteo import ClientOpenMeteo
from ourouler.physique import calibration as calib
from ourouler.physique.modele import Parametres, Simulation, simuler

#: Nom du fichier où la calibration est écrite, dans le dossier de cache.
NOM_CALIBRATION = "calibration.json"

#: Version du format de `calibration.json`. Un fichier plus récent est ignoré
#: plutôt que relu de travers.
VERSION_CALIBRATION = 1

#: CdA et Crr par défaut d'un vélo de route jamais calibré. Ils ne sont **pas**
#: une mesure : toute commande qui s'en sert le dit.
CDA_DEFAUT = 0.32
CRR_DEFAUT = 0.005

#: Mention affichée à côté d'un temps, selon d'où il vient.
MENTION_MODELE = "(modèle)"


# --- lecture et écriture de calibration.json ---------------------------------


@dataclass(frozen=True)
class Calibration:
    """Ce que `calibration.json` garde d'un vélo."""

    velo: str
    parametres: Parametres
    date: str = ""
    n_sorties: int = 0
    mae: float | None = None

    @property
    def resume(self) -> str:
        mae = f", MAE {self.mae * 100:.1f} %" if self.mae is not None else ""
        return (
            f"CdA {self.parametres.cda_m2:.3f} m², Crr {self.parametres.crr:.5f}, "
            f"{self.parametres.masse_totale_kg:.1f} kg (calibré le {self.date or '?'} "
            f"sur {self.n_sorties} sortie(s){mae})"
        )


def chemin_calibration(config: Config) -> Path:
    return config.cache.dossier / NOM_CALIBRATION


def lire_calibration(chemin: Path, velo: str) -> Calibration | None:
    """La calibration d'un vélo, ou `None` si le fichier manque, est illisible ou muet.

    Jamais d'exception : une calibration absente n'empêche pas de rouler, elle
    change seulement la mention affichée à côté du temps estimé.
    """
    try:
        charge = json.loads(chemin.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(charge, dict) or charge.get("version") != VERSION_CALIBRATION:
        return None
    velos = charge.get("velos")
    if not isinstance(velos, dict):
        return None
    brut = velos.get(velo) or _sans_casse(velos, velo)
    if not isinstance(brut, dict):
        return None
    try:
        parametres = Parametres(
            masse_totale_kg=float(brut["masse_totale_kg"]),
            cda_m2=float(brut["cda_m2"]),
            crr=float(brut["crr"]),
            rendement=float(brut.get("rendement", Parametres.rendement)),
            rho=float(brut.get("rho", Parametres.rho)),
        )
    except (KeyError, TypeError, ValueError):
        return None
    mae = brut.get("mae")
    return Calibration(
        velo=velo,
        parametres=parametres,
        date=str(brut.get("date") or ""),
        n_sorties=int(brut.get("n_sorties") or 0),
        mae=float(mae) if isinstance(mae, (int, float)) else None,
    )


def _sans_casse(velos: dict, nom: str) -> dict | None:
    for cle, valeur in velos.items():
        if str(cle).casefold() == nom.casefold():
            return valeur
    return None


def ecrire_calibration(chemin: Path, velo: str, contenu: dict) -> None:
    """Écrit (ou remplace) l'entrée d'un vélo **sans toucher aux autres.

    Calibrer le BMC ne doit pas effacer le RCR : le fichier est relu, l'entrée
    du vélo remplacée, et le tout réécrit.
    """
    charge: dict = {"version": VERSION_CALIBRATION, "velos": {}}
    try:
        ancien = json.loads(chemin.read_text(encoding="utf-8"))
        if isinstance(ancien, dict) and isinstance(ancien.get("velos"), dict):
            charge["velos"] = dict(ancien["velos"])
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        pass
    charge["velos"][velo] = contenu
    try:
        chemin.parent.mkdir(parents=True, exist_ok=True)
        chemin.write_text(
            json.dumps(charge, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    except OSError as e:
        raise ErreurUtilisateur(f"calibration : écriture impossible dans {chemin} ({e})") from e


def parametres_du_velo(config: Config, velo: Velo, chemin: Path) -> tuple[Parametres, str]:
    """(paramètres, provenance) : la calibration si elle existe, sinon la configuration.

    Provenance vaut « calibration », « configuration » ou « défaut ». Elle est
    affichée telle quelle : un CdA par défaut n'est pas une mesure, et la
    commande ne doit jamais laisser croire le contraire.
    """
    calibree = lire_calibration(chemin, velo.nom)
    if calibree is not None:
        return (calibree.parametres, "calibration")
    masse = calib.masse_totale_kg(config, velo)
    if velo.cda_m2 is not None and velo.crr is not None:
        return (Parametres(masse, velo.cda_m2, velo.crr), "configuration")
    return (
        Parametres(
            masse,
            velo.cda_m2 if velo.cda_m2 is not None else CDA_DEFAUT,
            velo.crr if velo.crr is not None else CRR_DEFAUT,
        ),
        "défaut",
    )


def velo_demande(config: Config, nom: str | None) -> Velo:
    """Le vélo nommé, ou le premier vélo d'usage route."""
    if nom:
        return config.velo(nom)
    for velo in config.velos:
        if velo.usage == "route":
            return velo
    if not config.velos:
        raise ErreurUtilisateur("aucun vélo dans la configuration : ajouter une section [[velos]]")
    return config.velos[0]


# --- ourouler calibrer --------------------------------------------------------


def executer_calibrer(
    args: argparse.Namespace, config: Config, client_archive: ClientArchive | None = None
) -> int:
    """Calibre un vélo sur les sorties réelles du cache. Code de sortie 0 si ça a marché."""
    velo = velo_demande(config, getattr(args, "velo", None))
    depuis = _date_option(getattr(args, "depuis", None), config.historique_depuis)
    cache = Cache(config.cache.dossier)

    toutes = cache.lister(depuis=depuis)
    motifs: dict[str, int] = {}
    for entree in toutes:
        motif = calib.motif_exclusion(entree, config, velo)
        if motif and motif not in ("pas du vélo", "autre vélo", "home-trainer"):
            motifs[motif] = motifs.get(motif, 0) + 1
    entrees = calib.sorties_calibrables(cache, config, velo, depuis=depuis)
    maximum = getattr(args, "max", None)
    if maximum:
        entrees = entrees[-int(maximum) :]
    if not entrees:
        raise ErreurUtilisateur(
            f"calibration : aucune sortie calibrable pour {velo.nom} depuis le {depuis} "
            "— vérifier le rattachement au vélo (`ourouler inventaire`)"
        )

    client = (
        client_archive
        if client_archive is not None
        else ClientArchive(chemin_cache=config.cache.dossier / NOM_CACHE)
    )
    sorties, pannes = _charger_sorties(cache, entrees, client)
    if not sorties:
        raise ErreurUtilisateur(
            f"calibration : aucune des {len(entrees)} sortie(s) de {velo.nom} n'est relisible"
        )

    rapport = calib.calibrer_en_deux_passes(
        sorties,
        velo=velo.nom,
        masse_totale_kg=calib.masse_totale_kg(config, velo),
        part_validation=config.calibration.part_validation,
        ftp_w=config.cycliste.ftp_w,
        vitesse_min_kmh=config.calibration.vitesse_min_kmh,
    )

    chemin = chemin_calibration(config)
    ecrire_calibration(chemin, velo.nom, _contenu_json(rapport))
    for panne in pannes:
        print(f"ourouler : {panne}", file=sys.stderr)
    if getattr(args, "json", False):
        print(
            json.dumps(
                rendre_json_calibration(rapport, velo, config, chemin, client, motifs, len(entrees)),
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print(
            rendre_texte_calibration(rapport, velo, config, chemin, client, motifs, len(entrees))
        )
    return 0


def _charger_sorties(
    cache: Cache, entrees, client: ClientArchive
) -> tuple[list[calib.SortieCalibration], list[str]]:
    """Relit chaque sortie et va chercher l'archive météo de son jour, à son départ.

    Une sortie illisible ou une archive indisponible ne fait pas échouer la
    calibration : elle est signalée et la sortie continue sans vent (ou pas du
    tout, si c'est le fichier qui manque).
    """
    sorties: list[calib.SortieCalibration] = []
    pannes: list[str] = []
    for entree in entrees:
        try:
            activite = cache.relire(entree.identifiant)
        except (KeyError, ErreurUtilisateur, OSError) as e:
            pannes.append(f"sortie {entree.identifiant[:12]} illisible ({e})")
            continue
        # Le nom de la sortie vit dans l'index du cache, pas dans le fichier
        # brut : sans ce report, le rapport désignait chaque sortie par le
        # chemin de son FIT, ce qui n'apprend rien à personne.
        nom = entree.meta.get("nom")
        if nom:
            activite.meta["nom"] = str(nom)
        vent = _archive_du_depart(activite, client, pannes)
        sorties.append(
            calib.SortieCalibration(activite=activite, vent=vent, identifiant=entree.identifiant)
        )
    return (sorties, pannes)


def _archive_du_depart(activite, client: ClientArchive, pannes: list[str]) -> list:
    """L'archive du jour au **point de départ** de la sortie, arrondi à 0,05°."""
    depart = next(
        (p for p in activite.points if p.lat is not None and p.lon is not None), None
    )
    if depart is None or activite.debut is None:
        return []
    try:
        return client.horaires(float(depart.lat), float(depart.lon), activite.debut.date())
    except (ErreurConnecteur, ErreurUtilisateur) as e:
        motif = f"archive météo du {activite.debut.date()} indisponible ({e})"
        if motif not in pannes:
            pannes.append(motif)
        return []


def _contenu_json(rapport: calib.RapportCalibration) -> dict:
    a = rapport.ajustement
    return {
        "cda_m2": round(a.cda_m2, 5),
        "crr": round(a.crr, 6),
        "masse_totale_kg": round(a.masse_totale_kg, 2),
        "rendement": a.parametres().rendement,
        "rho": round(a.rho_moyen, 4),
        "date": datetime.now().date().isoformat(),
        "n_sorties": rapport.n_apprentissage,
        "n_echantillons": a.n_echantillons,
        "cda_incertitude": _arrondi(a.cda_incertitude, 5),
        "crr_incertitude": _arrondi(a.crr_incertitude, 6),
        "rmse_w": round(a.rmse_w, 2),
        "mae": _arrondi(rapport.validation.mae, 4),
        "mediane": _arrondi(rapport.validation.mediane, 4),
        "biais": _arrondi(rapport.validation.biais, 4),
        "n_validation": rapport.validation.n,
        "bornes_atteintes": list(a.bornes_atteintes),
    }


def _arrondi(valeur: float | None, decimales: int) -> float | None:
    return None if valeur is None else round(valeur, decimales)


def rendre_texte_calibration(
    rapport: calib.RapportCalibration,
    velo: Velo,
    config: Config,
    chemin: Path,
    client: ClientArchive,
    motifs: dict[str, int],
    n_calibrables: int,
) -> str:
    a = rapport.ajustement
    v = rapport.validation
    lignes = [
        f"Calibration {velo.nom} — {n_calibrables} sortie(s) calibrable(s) "
        f"depuis le {config.historique_depuis.isoformat()}"
    ]
    if motifs:
        detail = ", ".join(f"{nombre} {motif}" for motif, nombre in sorted(motifs.items()))
        lignes.append(f"Sorties du vélo écartées : {detail}")
    lignes.append(
        f"Archives météo : {client.appels} appel(s), {client.lectures_cache} déjà en cache"
    )
    lignes.append("")
    lignes.append(
        f"Apprentissage : {rapport.n_apprentissage} sortie(s), "
        f"{rapport.echantillons_retenus} échantillon(s) retenu(s) sur {rapport.echantillons}"
    )
    if rapport.motifs:
        detail = ", ".join(f"{motif} {nombre}" for motif, nombre in rapport.motifs.items())
        lignes.append(f"  échantillons écartés : {detail}")
    if rapport.echantillons_sans_vent:
        lignes.append(
            f"  {rapport.echantillons_sans_vent} échantillon(s) retenu(s) sans vent archivé "
            "(comptés à vent nul)"
        )
    lignes.append(
        f"  CdA {_fr(a.cda_m2, 3)} m²{_incertitude(a.cda_incertitude, 3)}   "
        f"Crr {_fr(a.crr, 5)}{_incertitude(a.crr_incertitude, 5)}   "
        f"masse {_fr(a.masse_totale_kg, 1)} kg   ρ moyen {_fr(a.rho_moyen, 3)}"
    )
    lignes.append(
        f"  résidu de puissance : RMSE {_fr(a.rmse_w, 1)} W, MAE {_fr(a.mae_w, 1)} W"
    )
    lignes.append(
        f"  résistance totale à {calib.V_REFERENCE_KMH:g} km/h : "
        f"{_fr(a.force_reference_n, 1)} N — c'est ce que les données contraignent le "
        "mieux, CdA et Crr pouvant se compenser l'un l'autre"
    )
    lignes.append(
        f"  première passe (avec les sorties en groupe) : CdA {_fr(rapport.passe1.cda_m2, 3)}, "
        f"Crr {_fr(rapport.passe1.crr, 5)}"
    )
    for borne in a.bornes_atteintes:
        lignes.append(f"  ⚠ borne atteinte : {borne} — la vraie valeur est probablement au-delà")
    for avertissement in a.avertissements:
        lignes.append(f"  ⚠ {avertissement}")
    if rapport.groupes:
        lignes.append(f"  {len(rapport.groupes)} sortie(s) écartée(s) au résidu (« groupe ») :")
        for nom, part in rapport.groupes:
            lignes.append(f"    {part:.0%} de la distance trop rapide — {nom}")

    lignes.append("")
    lignes.append(f"Validation : {v.n} sortie(s) les plus récentes, jamais vues par l'ajustement")
    if v.n:
        lignes.append(
            f"  erreur de temps en mouvement : MAE {_pourcent(v.mae)}  "
            f"médiane {_pourcent(v.mediane)}  biais {_pourcent(v.biais, signe=True)}"
        )
        lignes.append(f"  {'jour':<12}{'km':>7}{'réel':>9}{'simulé':>9}{'écart':>9}  nom")
        for sortie in sorted(v.sorties, key=lambda s: abs(s.erreur_relative), reverse=True):
            lignes.append(
                f"  {str(sortie.jour or '?'):<12}{sortie.distance_m / 1000:>7.1f}"
                f"{_duree(sortie.temps_reel_s):>9}{_duree(sortie.temps_simule_s):>9}"
                f"{sortie.erreur_relative * 100:>+8.1f}%  {sortie.nom[:40]}"
            )
    if rapport.groupes_en_validation:
        lignes.append(
            f"  dont {len(rapport.groupes_en_validation)} sortie(s) que le même critère "
            "désigne comme « groupe » — elles restent comptées dans l'erreur :"
        )
        for nom, part in rapport.groupes_en_validation:
            lignes.append(f"    {part:.0%} de la distance trop rapide — {nom}")
    lignes.append("")
    lignes.append(
        "Le temps simulé est un temps **en mouvement** : ni les arrêts, ni les "
        "redémarrages n'y sont modélisés."
    )
    lignes.append(f"Écrit dans {chemin}")
    return "\n".join(lignes)


def rendre_json_calibration(
    rapport: calib.RapportCalibration,
    velo: Velo,
    config: Config,
    chemin: Path,
    client: ClientArchive,
    motifs: dict[str, int],
    n_calibrables: int,
) -> dict:
    a = rapport.ajustement
    v = rapport.validation
    return {
        "velo": velo.nom,
        "depuis": config.historique_depuis.isoformat(),
        "sorties_calibrables": n_calibrables,
        "sorties_ecartees": motifs,
        "archives": {"appels": client.appels, "cache": client.lectures_cache},
        "apprentissage": {
            "n_sorties": rapport.n_apprentissage,
            "echantillons": rapport.echantillons,
            "echantillons_retenus": rapport.echantillons_retenus,
            "echantillons_sans_vent": rapport.echantillons_sans_vent,
            "motifs": rapport.motifs,
            "groupes": [{"nom": nom, "part": round(part, 3)} for nom, part in rapport.groupes],
        },
        "ajustement": {
            "cda_m2": a.cda_m2,
            "crr": a.crr,
            "cda_incertitude": a.cda_incertitude,
            "crr_incertitude": a.crr_incertitude,
            "masse_totale_kg": a.masse_totale_kg,
            "rho_moyen": a.rho_moyen,
            "n_echantillons": a.n_echantillons,
            "rmse_w": a.rmse_w,
            "mae_w": a.mae_w,
            "bornes_atteintes": list(a.bornes_atteintes),
            "avertissements": list(a.avertissements),
        },
        "passe1": {"cda_m2": rapport.passe1.cda_m2, "crr": rapport.passe1.crr},
        "validation": {
            "n": v.n,
            "mae": v.mae,
            "mediane": v.mediane,
            "biais": v.biais,
            "groupes": [
                {"nom": nom, "part": round(part, 3)} for nom, part in rapport.groupes_en_validation
            ],
            "sorties": [
                {
                    "jour": s.jour.isoformat() if s.jour else None,
                    "nom": s.nom,
                    "distance_km": round(s.distance_m / 1000, 2),
                    "temps_reel_s": round(s.temps_reel_s),
                    "temps_simule_s": round(s.temps_simule_s),
                    "erreur_relative": round(s.erreur_relative, 4),
                }
                for s in v.sorties
            ],
        },
        "fichier": str(chemin),
    }


# --- ourouler simuler ---------------------------------------------------------


def executer_simuler(
    args: argparse.Namespace, config: Config, client_meteo: ClientOpenMeteo | None = None
) -> int:
    """Simule un GPX à puissance constante, avec le vent prévu si un départ est donné."""
    chemin_gpx = getattr(args, "gpx", None)
    if not chemin_gpx:
        raise ErreurUtilisateur("simuler : --gpx FICHIER.GPX est obligatoire")
    chemin_gpx = Path(chemin_gpx)
    if not chemin_gpx.is_file():
        raise ErreurUtilisateur(f"--gpx {chemin_gpx} : fichier introuvable")
    puissance = getattr(args, "puissance", None)
    if puissance is None or not (0 < float(puissance) <= 2000):
        raise ErreurUtilisateur(
            f"--puissance {puissance} : une puissance en watts entre 1 et 2000 est attendue"
        )

    velo = velo_demande(config, getattr(args, "velo", None))
    parametres, provenance = parametres_du_velo(config, velo, chemin_calibration(config))
    trace = lire_gpx_trace(chemin_gpx)

    vent = None
    panne = None
    depart = getattr(args, "depart", None)
    if depart:
        from ourouler.meteo.commande import heure_depart

        client = client_meteo if client_meteo is not None else ClientOpenMeteo()
        try:
            vent, resume = vent_prevu(trace, client, config, heure_depart(depart))
        except ErreurConnecteur as e:
            panne, resume = str(e), None
    else:
        resume = None

    simulation = simuler(trace, float(puissance), parametres, vent=vent)
    if panne is not None:
        print(f"ourouler : météo indisponible ({panne}) — simulation à vent nul", file=sys.stderr)
    if getattr(args, "json", False):
        print(
            json.dumps(
                rendre_json_simulation(
                    simulation, trace, velo, parametres, provenance, float(puissance), resume
                ),
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print(
            rendre_texte_simulation(
                simulation, trace, velo, parametres, provenance, float(puissance), resume
            )
        )
    return 0


def vent_prevu(trace, client: ClientOpenMeteo, config: Config, depart: datetime):
    """(fonction de vent pour `simuler`, résumé lisible) à partir de la prévision.

    Le vent vient de `boucle.meteo_trace`, échantillonné le long du tracé : le
    modèle a besoin de la composante de face en m/s, que la direction
    interpolée et le cap local donnent.
    """
    from ourouler.boucle.meteo_trace import evaluer as evaluer_meteo

    meteo = evaluer_meteo(
        trace,
        client,
        depart=depart,
        vitesse_kmh=config.boucle.vitesse_moyenne_kmh,
        modele=config.meteo.modele,
        second_avis=None,
    )
    return (vent_depuis_meteo(meteo), meteo)


def vent_depuis_meteo(meteo):
    """`vent(dist_m, cap_deg)` en m/s de face, depuis les échantillons météo d'un tracé.

    L'échantillon le plus proche en distance sert tel quel : les échantillons
    sont espacés de 5 km, le vent d'une prévision horaire ne varie pas plus
    vite que ça.
    """
    connus = [
        (e.dist_m, e.vent_kmh, e.vent_depuis_deg)
        for e in meteo.echantillons
        if e.vent_kmh is not None and e.vent_depuis_deg is not None
    ]
    if not connus:
        return None

    def face(dist_m: float, cap: float) -> float:
        _, vitesse, depuis = min(connus, key=lambda c: abs(c[0] - dist_m))
        return (vitesse / 3.6) * math.cos(math.radians(depuis - cap))

    return face


def rendre_texte_simulation(
    simulation: Simulation,
    trace,
    velo: Velo,
    parametres: Parametres,
    provenance: str,
    puissance_w: float,
    meteo,
) -> str:
    lignes = [
        f"Simulation de « {trace.nom} » — {_fr(simulation.distance_m / 1000, 1)} km"
        + (f", D+ {trace.denivele_m:.0f} m" if trace.denivele_m is not None else ""),
        f"Vélo {velo.nom} — CdA {_fr(parametres.cda_m2, 3)} m², Crr {_fr(parametres.crr, 5)}, "
        f"{_fr(parametres.masse_totale_kg, 1)} kg ({provenance}), ρ {_fr(parametres.rho, 3)}",
        f"Puissance tenue : {puissance_w:.0f} W",
    ]
    if meteo is not None:
        lignes.append(
            f"Vent prévu : face sur {meteo.part_vent_face:.0%} des échantillons "
            f"({meteo.n_vent_connu}/{len(meteo.echantillons)} connus)"
        )
    lignes.append("")
    lignes.append(
        f"Temps en mouvement : {_duree(simulation.temps_s)} "
        f"({_fr(simulation.vitesse_moy_kmh, 1)} km/h de moyenne) {MENTION_MODELE}"
    )
    if simulation.pas_plafonnes:
        lignes.append(
            f"  {simulation.pas_plafonnes} pas de 100 m plafonnés à 60 km/h en descente"
        )
    if simulation.pas_bloques:
        lignes.append(
            f"  {simulation.pas_bloques} pas où la vitesse calculée est sous 0,5 m/s "
            "(temps plancher, pas une mesure)"
        )
    lignes.append(
        "Les arrêts ne sont pas modélisés : feux, stops et ravitaillements s'ajoutent à ce temps."
    )
    if provenance != "calibration":
        lignes.append(
            f"CdA et Crr viennent de la {provenance} et n'ont pas été mesurés : "
            f"lancer `ourouler calibrer --velo {velo.nom}`."
        )
    return "\n".join(lignes)


def rendre_json_simulation(
    simulation: Simulation,
    trace,
    velo: Velo,
    parametres: Parametres,
    provenance: str,
    puissance_w: float,
    meteo,
) -> dict:
    return {
        "trace": trace.nom,
        "distance_m": round(simulation.distance_m, 1),
        "denivele_m": trace.denivele_m,
        "velo": velo.nom,
        "parametres": {
            "cda_m2": parametres.cda_m2,
            "crr": parametres.crr,
            "masse_totale_kg": parametres.masse_totale_kg,
            "rendement": parametres.rendement,
            "rho": parametres.rho,
            "provenance": provenance,
        },
        "puissance_w": puissance_w,
        "temps_mouvement_s": round(simulation.temps_s),
        "vitesse_moy_kmh": round(simulation.vitesse_moy_kmh, 2),
        "pas_plafonnes": simulation.pas_plafonnes,
        "pas_bloques": simulation.pas_bloques,
        "vent": None
        if meteo is None
        else {
            "part_vent_face": round(meteo.part_vent_face, 3),
            "n_vent_connu": meteo.n_vent_connu,
            "n_echantillons": len(meteo.echantillons),
        },
        "arrets_modelises": False,
    }


# --- petits rendus ------------------------------------------------------------


def _date_option(texte: str | None, defaut: date) -> date:
    if not texte:
        return defaut
    try:
        return date.fromisoformat(str(texte).strip())
    except ValueError as e:
        raise ErreurUtilisateur(f"--depuis {texte!r} : date AAAA-MM-JJ attendue") from e


def _fr(valeur: float, decimales: int) -> str:
    """Un nombre à la française : virgule décimale."""
    return f"{valeur:.{decimales}f}".replace(".", ",")


def _incertitude(valeur: float | None, decimales: int) -> str:
    return "" if valeur is None else f" ± {_fr(valeur, decimales)}"


def _pourcent(valeur: float | None, *, signe: bool = False) -> str:
    if valeur is None:
        return "—"
    texte = f"{valeur * 100:{'+' if signe else ''}.1f}"
    return texte.replace(".", ",") + " %"


def _duree(secondes: float) -> str:
    """« 2:14 » — heures et minutes."""
    minutes = round(secondes / 60)
    return f"{minutes // 60}:{minutes % 60:02d}"


__all__ = [
    "NOM_CALIBRATION",
    "Calibration",
    "chemin_calibration",
    "ecrire_calibration",
    "executer_calibrer",
    "executer_simuler",
    "lire_calibration",
    "parametres_du_velo",
    "velo_demande",
    "vent_depuis_meteo",
]
