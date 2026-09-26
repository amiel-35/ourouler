"""Configuration : objets de données + chargement TOML.

Règle absolue 2 de CLAUDE.md : ce module et `cli.py` sont les seuls
autorisés à lire un fichier, `Path.home()` ou une variable d'environnement.
Le reste du cœur reçoit un objet `Config` déjà construit.
"""

from __future__ import annotations

import os
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import date, datetime
from pathlib import Path
from typing import Any

from ourouler.noyau.erreurs import ErreurConfig

# Le profil du cycliste vit au noyau depuis le lot 4 (`noyau/profil.py`) ;
# `Config` le compose. Ces types restent aussi importables depuis ce module
# (`config.Velo`, `config.Depart`…) — alias public délibéré, souvent importé
# ainsi par les appelants (tests compris) plutôt que depuis `noyau.profil`.
from ourouler.noyau.profil import (
    DIRECTIONS_ACCEPTEES,
    HORIZON_JOURS_DEFAUT,
    HORIZON_MAX_H,
    Cycliste,
    Depart,
    Evitement,
    ParametresBoucle,
    ParametresBrouter,
    ParametresCalibration,
    ParametresIntervals,
    ParametresMeteo,
    ParametresSeance,
    ParametresTenue,
    Periode,
    Velo,
)
from ourouler.noyau.seance import ZONES_PUISSANCE_DEFAUT
from ourouler.noyau.zones import (
    POSITION_ENDURANCE_DEFAUT,
    ZONE_ENDURANCE,
    position_endurance,
)

#: Bornes de chargement de `[seance] position_zone` : au plus une largeur de
#: bande au-dessous du bas de la zone, une au-dessus du haut. Ce n'est pas le
#: domaine normal — l'écran de FTP tient l'utilisateur dans [0, 1] — c'est la
#: marge que la décision 8 réclame pour qu'une saisie fautive **se voie** au
#: lieu d'être corrigée en douce (0,508 × FTP se lit −0,274 dans la table par
#: défaut, « à −27 % de la bande »).
#:
#: Ces deux nombres sont la **seule** borne du réglage : le chemin de
#: migration depuis `puissance_endurance_pct` passe par eux comme le chemin
#: direct (`_position_zone`), de sorte qu'aucune configuration ne puisse se
#: charger une fois puis être refusée à la relecture.
POSITION_ZONE_MINI = -1.0
POSITION_ZONE_MAXI = 2.0

#: Bornes de lecture de l'ancienne clé `puissance_endurance_pct`, en fraction
#: de FTP. Inchangées depuis avant la décision 7 : on ne convertit pas plus
#: largement qu'on n'acceptait.
ENDURANCE_PCT_MINI = 0.40
ENDURANCE_PCT_MAXI = 0.80

CHEMIN_CONFIG_DEFAUT = Path("~/.config/ourouler/config.toml")
HISTORIQUE_DEPUIS_DEFAUT = date(2023, 12, 1)
USAGES_VELO = ("route", "clm")

#: Les catégories de pneu qu'un vélo peut déclarer (`Velo.pneu`). La table des
#: Crr correspondants vit dans `physique.litterature.PNEUS` ; un test garde les
#: deux listes identiques. Déclarée ici, comme `USAGES_VELO`, pour que la
#: configuration se valide sans importer le modèle physique.
PNEUS_VELO = ("course_rapide", "course_quatre_saisons", "entrainement", "gravel", "vtt")

#: Préfixe commun des variables d'environnement lues par `charger()` (contrat
#: de l'hébergé minimal, docs/journal/sprints/heberge_minimal_contrat.md § « Les secrets »).
PREFIXE_ENV = "OUROULER_"

#: Borne haute acceptée pour `[meteo] horizon_jours` : Open-Meteo ne publie
#: pas de prévision au-delà de seize jours, quel que soit le modèle.
HORIZON_JOURS_MAX = 16


#: Emplacement du cache quand la configuration n'en nomme pas.
#:
#: **Développé ici, et pas ailleurs** (corrigé le 18/09/2026). Le chemin était
#: écrit `Path("~/.cache/ourouler")` et le `~` n'était jamais résolu : tout
#: appelant qui oubliait `.expanduser()` — et la moitié du dépôt l'oubliait —
#: créait un dossier **littéral** nommé `~` dans le répertoire courant. La
#: suite de tests en fabriquait un à la racine du dépôt à chaque exécution.
#:
#: La règle absolue 2 désigne `config.py` comme le seul endroit du cœur
#: autorisé à résoudre un chemin utilisateur : c'est donc ici que le `~` se
#: développe, une fois, pour que plus personne n'ait à y penser.
CACHE_DEFAUT = Path("~/.cache/ourouler").expanduser()


@dataclass(frozen=True)
class ParametresCache:
    dossier: Path = CACHE_DEFAUT
    #: Où lire et écrire `calibration.json`. `None` — la ligne de commande, et
    #: `ourouler api` en mode personnel — : dans `dossier`, comme toujours.
    #: **Jamais lu dans un TOML** : c'est la couche web hébergée qui le pose,
    #: par propriétaire (`api/routes/commun._config`, L9.4), pour que la calibration
    #: d'un compte ne soit lue que par lui. Le dossier de cache, lui, est
    #: celui du serveur et se partage (l'index d'activités y porte déjà sa
    #: colonne de propriétaire ; `calibration.json`, un fichier entier, n'en a
    #: pas).
    fichier_calibration: Path | None = None


SENS_BOUCLE = ("horaire", "antihoraire")


@dataclass(frozen=True)
class Config:
    depart: Depart
    cycliste: Cycliste
    velos: tuple[Velo, ...] = ()
    meteo: ParametresMeteo = field(default_factory=ParametresMeteo)
    intervals: ParametresIntervals = field(default_factory=ParametresIntervals)
    cache: ParametresCache = field(default_factory=ParametresCache)
    brouter: ParametresBrouter = field(default_factory=ParametresBrouter)
    boucle: ParametresBoucle = field(default_factory=ParametresBoucle)
    calibration: ParametresCalibration = field(default_factory=ParametresCalibration)
    seance: ParametresSeance = field(default_factory=ParametresSeance)
    tenue: ParametresTenue = field(default_factory=ParametresTenue)
    evitements: tuple[Evitement, ...] = ()
    historique_depuis: date = HISTORIQUE_DEPUIS_DEFAUT

    def velo(self, nom: str) -> Velo:
        for v in self.velos:
            if v.nom.casefold() == nom.casefold():
                return v
        raise ErreurConfig(f"velos : aucun vélo nommé « {nom} »")


# --- chargement -------------------------------------------------------------


def charger(
    chemin: Path | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    requiert_profil: bool = True,
) -> Config:
    """Lit un fichier TOML, le complète depuis l'environnement, et construit la `Config`.

    Chemin par défaut : ~/.config/ourouler/config.toml. `environ` est
    injectable pour les tests (défaut : `os.environ`, jamais lu ailleurs que
    dans ce module et `cli.py`, règle absolue 2).

    Contrat de l'hébergé minimal (docs/journal/sprints/heberge_minimal_contrat.md, § « Les
    secrets ») : la tâche planifiée conteneurisée n'a ni fichier de
    configuration personnel dans l'image, ni coordonnée de départ commitée.
    La clé Intervals, le point de départ et le serveur BRouter viennent donc
    de l'environnement — posés dans l'interface Coolify, jamais écrits
    ailleurs — et l'emportent sur le TOML quand ils sont présents. Pour
    l'usage local (CLI interactive), rien ne change : sans ces variables,
    le TOML seul décide, comme avant.

    `requiert_profil=False` (`cli.py`, commandes de comptes — constat du
    25/09/2026 en invitant depuis la prod) : `[depart]` et `[cycliste]`
    deviennent facultatives. Ces commandes ne parlent qu'à la base des
    comptes et, pour `inviter`/`reinitialiser`, au relais SMTP — jamais au
    profil du cycliste — et un déploiement hébergé sans tiers 3 (Q35/Q66)
    n'écrit justement plus ces deux sections dans son TOML.
    """
    environ = os.environ if environ is None else environ
    chemin = (chemin or CHEMIN_CONFIG_DEFAUT).expanduser()
    if not chemin.is_file():
        raise ErreurConfig(
            f"fichier de configuration introuvable : {chemin} "
            "(copier config.example.toml et le renseigner, ou passer --config)"
        )
    try:
        with chemin.open("rb") as f:
            brut = tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        raise ErreurConfig(f"{chemin} : TOML invalide ({e})") from e
    return finaliser(brut, environ=environ, requiert_profil=requiert_profil)


def finaliser(
    brut: dict[str, Any],
    *,
    environ: Mapping[str, str] | None = None,
    requiert_profil: bool = True,
) -> Config:
    """La fin du chargement, à partir d'un dict TOML déjà lu.

    Extraite de `charger` pour l'API (lot F1) : le profil d'un propriétaire
    se superpose au TOML **entre** la lecture du fichier et la validation, et
    `charger` ne laissait aucun point d'entrée à cet endroit-là. Aucun
    changement de comportement : `charger` appelle cette fonction.
    """
    environ = os.environ if environ is None else environ
    config = depuis_dict(_survoler_environnement(brut, environ), requiert_profil=requiert_profil)
    # Seul endroit où « ~ » est développé : le cœur reçoit un chemin absolu.
    return replace(config, cache=ParametresCache(config.cache.dossier.expanduser()))


def _survoler_environnement(brut: dict[str, Any], environ: Mapping[str, str]) -> dict[str, Any]:
    """Complète ou remplace, dans le dict TOML, les trois sections que le contrat de
    l'hébergé minimal fait venir de l'environnement : le point de départ, la
    clé Intervals, l'URL et les identifiants BRouter. Une variable absente
    laisse le TOML inchangé ; présente, elle l'emporte toujours — c'est
    l'environnement qui fait foi en conteneur. Ne mute jamais `brut` : une
    copie superficielle par section touchée.
    """
    d = dict(brut)

    depart = dict(d.get("depart") or {})
    _reporter(depart, "nom", environ, "DEPART_NOM")
    _reporter(depart, "latitude", environ, "DEPART_LATITUDE")
    _reporter(depart, "longitude", environ, "DEPART_LONGITUDE")
    if depart:
        d["depart"] = depart

    intervals = dict(d.get("intervals") or {})
    _reporter(intervals, "api_key", environ, "INTERVALS_API_KEY")
    _reporter(intervals, "athlete_id", environ, "INTERVALS_ATHLETE_ID")
    if intervals:
        d["intervals"] = intervals

    brouter = dict(d.get("brouter") or {})
    _reporter(brouter, "url", environ, "BROUTER_URL")
    _reporter(brouter, "utilisateur", environ, "BROUTER_UTILISATEUR")
    _reporter(brouter, "mot_de_passe", environ, "BROUTER_MOT_DE_PASSE")
    if brouter:
        d["brouter"] = brouter

    return d


def _reporter(section: dict[str, Any], champ: str, environ: Mapping[str, str], suffixe: str) -> None:
    """Pose `section[champ]` depuis `{PREFIXE_ENV}<suffixe>`, si la variable **porte
    une valeur**.

    Vide vaut absente, et ce n'est pas du confort : un fichier compose écrit
    `OUROULER_DEPART_LATITUDE: ${OUROULER_DEPART_LATITUDE}` pour laisser
    l'hébergeur poser la variable, et l'hébergeur qui ne la pose pas la
    transmet quand même au conteneur, vide. Avec `valeur is not None` seul,
    cette chaîne vide écrasait la latitude du TOML et le démarrage échouait
    sur « [depart] latitude : nombre attendu, reçu '' » — un fichier de
    configuration valide rendu invalide par une variable que personne n'a
    remplie (constaté le 18/09/2026 sur le premier déploiement Coolify de
    l'API : boucle de redémarrage, 503 derrière le proxy).

    Effacer une valeur du TOML par l'environnement n'est donc pas possible,
    et n'a jamais été demandé : ces variables servent à **fournir** ce que le
    fichier n'a pas, pas à retirer ce qu'il a.
    """
    valeur = environ.get(f"{PREFIXE_ENV}{suffixe}")
    if valeur:
        section[champ] = valeur


def dossier_cache_depuis(brut: Mapping[str, Any]) -> Path:
    """Le dossier de cache, lu dans un dict TOML déjà chargé — sans construire toute la `Config`.

    Extraite pour l'API (`api/application.py`, mode hébergé) : `[cache]` est
    un réglage serveur (Q35), qui ne dépend d'aucune section perso pur
    (`depart`, `cycliste`, `velos`, `intervals`) ; le lire seul ne doit donc
    pas exiger que ces sections soient déjà renseignées. C'est précisément ce
    que `depuis_dict` ne peut plus garantir en mode hébergé, depuis que
    `SocleTOML` retire les sections perso pur du socle serveur
    (`api/depots.py`) — un socle hébergé sans surcharge de propriétaire est,
    à raison, un profil incomplet qui ne construit plus de `Config` du tout.
    """
    cache = brut.get("cache", {}) or {}
    return Path(str(cache.get("dossier") or CACHE_DEFAUT)).expanduser()


def depuis_dict(d: dict[str, Any], *, requiert_profil: bool = True) -> Config:
    """Construit la `Config` depuis un dictionnaire (contenu TOML déjà lu). Valide et nomme les champs.

    `requiert_profil=False` (commandes de comptes, voir `charger`) : `[depart]`
    et `[cycliste]` peuvent être absentes, ou présentes sans `latitude`,
    `longitude` ni `masse_kg` — le `Depart`/`Cycliste` rendu porte alors des
    zéros, jamais lus par ces commandes (`ourouler inviter` ne s'en sert que
    pour composer « Prénom Nom vous invite », vide si absent). Toute autre
    validation (bornes, types) reste inchangée : ce n'est pas un mode permissif
    général, seulement ces deux sections, seulement leur absence.
    """
    if not isinstance(d, dict):
        # Un TOML valide donne toujours un dict, mais `depuis_dict` est aussi
        # appelée directement (tests, futurs appelants) : une liste ou une
        # chaîne finissait en `AttributeError: 'list' object has no attribute
        # 'get'`, donc une trace et un code 1 au lieu d'un message.
        raise ErreurConfig(f"configuration : dictionnaire attendu, reçu {type(d).__name__}")
    depart = _section(d, "depart", requis=requiert_profil)
    cycliste = _section(d, "cycliste", requis=requiert_profil)
    velos = tuple(_velo(v, i) for i, v in enumerate(d.get("velos", []) or []))
    if not velos:
        velos = (Velo(nom="Route"),)
    meteo = d.get("meteo", {}) or {}
    intervals = d.get("intervals", {}) or {}
    brouter = d.get("brouter", {}) or {}
    boucle = d.get("boucle", {}) or {}
    calibration = d.get("calibration", {}) or {}
    seance_brut = d.get("seance", {}) or {}
    zones_pct = _zones_pct(seance_brut.get("zones", ZONES_PUISSANCE_DEFAUT))
    tenue_brut = d.get("tenue", {}) or {}
    evitements = tuple(_evitement(e, i) for i, e in enumerate(d.get("evitements", []) or []))
    sens = str(boucle.get("sens", "horaire"))
    if sens not in SENS_BOUCLE:
        raise ErreurConfig(f"[boucle] sens = {sens!r}, attendu un de {SENS_BOUCLE}")
    return Config(
        depart=_depart_depuis(depart, requiert_profil=requiert_profil),
        cycliste=_cycliste_depuis(cycliste, requiert_profil=requiert_profil),
        velos=velos,
        meteo=_meteo_depuis(meteo),
        intervals=ParametresIntervals(
            athlete_id=str(intervals.get("athlete_id", "") or ""),
            api_key=str(intervals.get("api_key", "") or ""),
        ),
        # `.expanduser()` : un TOML écrit à la main porte presque toujours un
        # `~`, et le cœur qui reçoit ce chemin n'a pas le droit de le résoudre.
        cache=ParametresCache(dossier=dossier_cache_depuis(d)),
        brouter=_brouter_depuis(brouter),
        boucle=_boucle_depuis(boucle, sens),
        calibration=_calibration_depuis(calibration),
        seance=_seance_depuis(seance_brut, zones_pct),
        tenue=_tenue_depuis(tenue_brut),
        evitements=evitements,
        historique_depuis=_date(d.get("historique_depuis", HISTORIQUE_DEPUIS_DEFAUT), "historique_depuis"),
    )


def _depart_depuis(depart: dict[str, Any], *, requiert_profil: bool) -> Depart:
    return Depart(
        nom=str(depart.get("nom", "Départ")),
        latitude=_nombre(
            depart, "latitude", "depart", -90, 90, requis=requiert_profil, defaut=0.0
        ),
        longitude=_nombre(
            depart, "longitude", "depart", -180, 180, requis=requiert_profil, defaut=0.0
        ),
    )


def _cycliste_depuis(cycliste: dict[str, Any], *, requiert_profil: bool) -> Cycliste:
    return Cycliste(
        masse_kg=_nombre(
            cycliste, "masse_kg", "cycliste", 20, 300, requis=requiert_profil, defaut=0.0
        ),
        ftp_w=_nombre_optionnel(cycliste, "ftp_w", "cycliste", 50, 1000),
        # Absents dans toute configuration écrite avant ce lot : une
        # chaîne vide, jamais un refus de chargement (voir la docstring
        # de `Cycliste.prenom`).
        prenom=str(cycliste.get("prenom", "") or ""),
        nom=str(cycliste.get("nom", "") or ""),
    )


def _meteo_depuis(meteo: dict[str, Any]) -> ParametresMeteo:
    return ParametresMeteo(
        directions=_entier(
            meteo.get("directions", 8), "directions", "meteo", parmi=DIRECTIONS_ACCEPTEES
        ),
        distances_km=_distances(meteo.get("distances_km", (15, 25, 40))),
        modele=str(meteo.get("modele", ParametresMeteo.modele)),
        second_avis=str(meteo.get("second_avis", ParametresMeteo.second_avis)),
        horizon_h=_entier(
            meteo.get("horizon_h", 6), "horizon_h", "meteo", mini=1, maxi=HORIZON_MAX_H
        ),
        horizon_jours=_entier(
            meteo.get("horizon_jours", HORIZON_JOURS_DEFAUT),
            "horizon_jours",
            "meteo",
            mini=0,
            maxi=HORIZON_JOURS_MAX,
        ),
    )


def _brouter_depuis(brouter: dict[str, Any]) -> ParametresBrouter:
    return ParametresBrouter(
        url=str(brouter.get("url", "") or "").rstrip("/"),
        utilisateur=str(brouter.get("utilisateur", "") or ""),
        mot_de_passe=str(brouter.get("mot_de_passe", "") or ""),
        profil=str(brouter.get("profil", "fastbike") or "fastbike"),
        timeout_s=_flottant(brouter.get("timeout_s", 120.0), "timeout_s", "brouter", mini=1, maxi=600),
    )


def _boucle_depuis(boucle: dict[str, Any], sens: str) -> ParametresBoucle:
    return ParametresBoucle(
        vitesse_moyenne_kmh=_flottant(
            boucle.get("vitesse_moyenne_kmh", 27.0), "vitesse_moyenne_kmh", "boucle", mini=5, maxi=60
        ),
        sens=sens,
        candidates=_entier(boucle.get("candidates", 5), "candidates", "boucle", mini=1, maxi=20),
        tolerance_distance=_flottant(
            boucle.get("tolerance_distance", 0.10), "tolerance_distance", "boucle", mini=0.01, maxi=0.5
        ),
    )


def _calibration_depuis(calibration: dict[str, Any]) -> ParametresCalibration:
    return ParametresCalibration(
        mots_groupe=_mots(
            calibration.get("mots_groupe", ParametresCalibration().mots_groupe)
        ),
        part_validation=_flottant(
            calibration.get("part_validation", 0.25),
            "part_validation",
            "calibration",
            mini=0.05,
            maxi=0.5,
        ),
        vitesse_min_kmh=_flottant(
            calibration.get("vitesse_min_kmh", 8.0), "vitesse_min_kmh", "calibration", mini=1, maxi=30
        ),
        part_groupe_max=_flottant(
            calibration.get("part_groupe_max", 0.30),
            "part_groupe_max",
            "calibration",
            mini=0.05,
            maxi=0.5,
        ),
    )


def _seance_depuis(
    seance_brut: dict[str, Any], zones_pct: tuple[tuple[float, float], ...]
) -> ParametresSeance:
    return ParametresSeance(
        elasticite_z2_max=_flottant(
            seance_brut.get("elasticite_z2_max", 0.20),
            "elasticite_z2_max",
            "seance",
            mini=0.0,
            maxi=1.0,
        ),
        elasticite_z2_min=_flottant(
            seance_brut.get("elasticite_z2_min", -0.05),
            "elasticite_z2_min",
            "seance",
            mini=-0.5,
            maxi=0.0,
        ),
        elasticite_calme_max=_flottant(
            seance_brut.get("elasticite_calme_max", 1.5),
            "elasticite_calme_max",
            "seance",
            mini=0.0,
            maxi=5.0,
        ),
        elasticite_calme_min=_flottant(
            seance_brut.get("elasticite_calme_min", -0.05),
            "elasticite_calme_min",
            "seance",
            mini=-0.5,
            maxi=0.0,
        ),
        demi_tour_penalite=_flottant(
            seance_brut.get("demi_tour_penalite", 1.0),
            "demi_tour_penalite",
            "seance",
            mini=0.0,
            maxi=20.0,
        ),
        zones_pct=zones_pct,
        position_zone=_position_zone(seance_brut, zones_pct),
        seuil_recuperation_pct=_flottant(
            seance_brut.get("seuil_recuperation_pct", 0.75),
            "seuil_recuperation_pct",
            "seance",
            mini=0.50,
            maxi=0.90,
        ),
        tolerance_egalite=_flottant(
            seance_brut.get("tolerance_egalite", 0.15),
            "tolerance_egalite",
            "seance",
            mini=0.0,
            maxi=0.5,
        ),
    )


def _tenue_depuis(tenue_brut: dict[str, Any]) -> ParametresTenue:
    return ParametresTenue(
        bornes_c=_bornes(
            tenue_brut.get("bornes_c", (3.0, 9.0, 15.0, 22.0, 30.0)), "bornes_c", "tenue"
        ),
        bornes_pluie_mmh=_bornes(
            tenue_brut.get("bornes_pluie_mmh", (0.2, 0.5, 1.0)), "bornes_pluie_mmh", "tenue"
        ),
        vent_veste_kmh=_flottant(
            tenue_brut.get("vent_veste_kmh", 30.0), "vent_veste_kmh", "tenue", mini=0.0, maxi=100.0
        ),
        tenues=_tenues(tenue_brut.get("tenues", {})),
    )


def _mots(brut: Any) -> tuple[str, ...]:
    """Liste de mots, en minuscules. Une chaîne nue est refusée : `"club"` itéré
    donnerait ('c', 'l', 'u', 'b') et écarterait presque toutes les sorties."""
    if isinstance(brut, str) or not isinstance(brut, (list, tuple)):
        raise ErreurConfig(
            f"[calibration] mots_groupe : liste de mots attendue (ex. [\"club\"]), reçu {brut!r}"
        )
    mots = tuple(str(m).strip().casefold() for m in brut if str(m).strip())
    return mots


def _tenues(brut: Any) -> tuple[tuple[str, tuple[str, ...]], ...]:
    """{catégorie: [vêtements]} → couples figés. Une catégorie absente garde le défaut du code."""
    if not brut:
        return ()
    if not isinstance(brut, dict):
        raise ErreurConfig(f"[tenue] tenues : table {{catégorie = [vêtements]}} attendue, reçu {brut!r}")
    couples = []
    for categorie, pieces in brut.items():
        if isinstance(pieces, str) or not isinstance(pieces, (list, tuple)):
            raise ErreurConfig(f"[tenue] tenues.{categorie} : liste de vêtements attendue, reçu {pieces!r}")
        couples.append((str(categorie), tuple(str(p) for p in pieces)))
    return tuple(couples)


def _zones_pct(brut: Any) -> tuple[tuple[float, float], ...]:
    """La table des zones de puissance, en fractions de FTP, ou `ErreurConfig`.

    Elle s'écrit `zones = [[0.0, 0.55], [0.56, 0.75], …]` sous `[seance]`.
    Contrairement à `seance.intervals._zones`, qui se rabat en silence sur la
    table par défaut — là il s'agit de données venues d'une API, qu'on ne
    contrôle pas — une table de configuration fautive est **refusée en nommant
    le champ** : c'est le cycliste qui l'a écrite, il doit savoir qu'elle est
    fausse plutôt que de rouler avec une autre.

    Trois zones au minimum : la Z2 porte l'endurance et doit être fermée, donc
    ni première ni dernière (`seance/zones.zone_ouverte`).
    """
    if isinstance(brut, str) or not isinstance(brut, (list, tuple)):
        raise ErreurConfig(
            "[seance] zones : liste de paires [bas, haut] en fraction de FTP attendue "
            f"(ex. [[0.0, 0.55], [0.56, 0.75], …]), reçu {brut!r}"
        )
    if len(brut) < 3:
        raise ErreurConfig(
            f"[seance] zones : au moins trois zones attendues, reçu {len(brut)} — "
            "la zone d'endurance (Z2) doit être fermée, donc ni la première ni la dernière"
        )
    table: list[tuple[float, float]] = []
    for i, zone in enumerate(brut):
        numero = i + 1
        if isinstance(zone, str) or not isinstance(zone, (list, tuple)) or len(zone) != 2:
            raise ErreurConfig(
                f"[seance] zones : Z{numero} — paire [bas, haut] attendue, reçu {zone!r}"
            )
        bas = _flottant(zone[0], f"zones Z{numero} (bas)", "seance", mini=0.0, maxi=5.0)
        haut = _flottant(zone[1], f"zones Z{numero} (haut)", "seance", mini=0.0, maxi=5.0)
        if haut <= bas:
            raise ErreurConfig(
                f"[seance] zones : Z{numero} = [{bas}, {haut}] — le haut doit dépasser le bas "
                "(une bande de largeur nulle n'a pas de position)"
            )
        if table and bas < table[-1][1]:
            raise ErreurConfig(
                f"[seance] zones : Z{numero} commence à {bas}, sous le haut de Z{numero - 1} "
                f"({table[-1][1]}) — les zones montent et ne se chevauchent pas"
            )
        table.append((bas, haut))
    return tuple(table)


def _position_zone(seance_brut: dict[str, Any], zones_pct: tuple[tuple[float, float], ...]) -> float:
    """La position du cycliste dans sa bande, 0 = bas de zone, 1 = haut.

    **Compatibilité.** Une configuration écrite avant la décision 7 ne porte
    pas `position_zone` mais `puissance_endurance_pct`, une valeur. On la lit
    alors telle quelle et on la **convertit en position** dans la Z2 de
    `zones_pct` : 0,60 de FTP avec la table par défaut donne 0,2105, et la
    puissance d'endurance dérivée revient exactement à 0,60 (`DECIMALES_PCT`
    garantit l'aller-retour). Rien ne bouge pour une configuration existante,
    et c'est la seule réponse acceptable à la règle absolue 5.

    Les bornes de lecture de l'ancienne clé sont inchangées
    ([`ENDURANCE_PCT_MINI` ; `ENDURANCE_PCT_MAXI`]) : on ne convertit pas plus
    largement qu'on n'acceptait.

    **La conversion passe par la même borne que le chemin direct**
    ([`POSITION_ZONE_MINI` ; `POSITION_ZONE_MAXI`]), et c'est l'invariant qui
    compte : *tout ce qui se charge doit pouvoir se recharger*. Un profil
    chargé est réécrit par le produit sous sa forme d'aujourd'hui — une
    position — et la relecture de cette position ne doit jamais échouer.
    Avant cette borne, `zones = [[0,0.55],[0.70,0.72],[0.73,0.90],[0.91,1.05]]`
    avec `puissance_endurance_pct = 0.40` se chargeait en silence sur
    `position_zone = −15,0`, valeur que le chargement suivant refusait.

    **Ce qui est refusé, et pourquoi c'est un refus et non un écrêtage.** Une
    table `zones` personnalisée dont la Z2 ne contient ni n'approche l'ancienne
    valeur décrit un fichier qui dit deux choses contradictoires : « ma Z2 va
    de 70 à 72 % de FTP » et « mon endurance est à 40 % ». Rien ne peut les
    réconcilier sans en jeter une :

    - écrêter à −1 ferait passer l'endurance de 0,40 à 0,68 × FTP — +70 %, en
      silence, sur la valeur qui pilote les étapes prescrites en FC basse.
      Règle absolue 5 : on n'aligne pas deux sources qui divergent, on montre
      le désaccord ;
    - convertir dans la table **par défaut** puis appliquer la position à la
      table de l'utilisateur ferait passer 0,40 à 0,7042 × FTP — pire ;
    - élargir les bornes garderait un chiffre (« −15 ») auquel ne correspond
      aucune réalité : personne ne roule à quinze largeurs de bande sous sa Z2.

    **Aucune configuration d'avant la décision 7 n'est bloquée par là**, et
    c'est démontrable : `zones` n'existait pas encore quand l'ancienne clé
    s'écrivait, donc une telle configuration est lue avec la table par défaut,
    où [0,40 ; 0,80] se convertit dans [−0,842 ; 1,263] — à l'intérieur des
    bornes. Le refus ne peut donc atteindre qu'un fichier qui porte les deux
    générations de réglages à la fois.

    **Si les deux clés sont présentes**, `position_zone` l'emporte et
    l'ancienne est ignorée : c'est la nouvelle qui est stockée, et refuser le
    chargement pour une clé oubliée dans un fichier serait la pire des
    réponses.
    """
    if "position_zone" in seance_brut:
        return _flottant(
            seance_brut["position_zone"],
            "position_zone",
            "seance",
            mini=POSITION_ZONE_MINI,
            maxi=POSITION_ZONE_MAXI,
        )
    if "puissance_endurance_pct" in seance_brut:
        ancienne = _flottant(
            seance_brut["puissance_endurance_pct"],
            "puissance_endurance_pct",
            "seance",
            mini=ENDURANCE_PCT_MINI,
            maxi=ENDURANCE_PCT_MAXI,
        )
        position = position_endurance(ancienne, zones_pct)
        if not POSITION_ZONE_MINI <= position <= POSITION_ZONE_MAXI:
            bas, haut = zones_pct[ZONE_ENDURANCE - 1]
            raise ErreurConfig(
                f"[seance] puissance_endurance_pct = {ancienne} ne peut pas se convertir "
                f"en position : la Z2 de votre table zones va de {bas} à {haut} de FTP, "
                f"cette valeur s'y situe à {position:.1f}, hors de "
                f"[{POSITION_ZONE_MINI}, {POSITION_ZONE_MAXI}]. Les deux réglages ne disent "
                "pas la même chose. Écrivez position_zone (0 = bas de la Z2, 1 = haut) et "
                "retirez puissance_endurance_pct, ou corrigez zones."
            )
        return position
    # Ni l'une ni l'autre : le défaut du projet, qui est lui-même la position
    # de la puissance d'endurance mesurée dans la table par défaut. Avec une
    # table personnalisée, cette position désigne le même endroit *relatif* de
    # la bande — c'est tout l'intérêt de stocker une position.
    return POSITION_ENDURANCE_DEFAUT


def _bornes(brut: Any, cle: str, section: str) -> tuple[float, ...]:
    """Suite de bornes strictement croissantes. Une chaîne nue est refusée."""
    if isinstance(brut, str) or not isinstance(brut, (list, tuple)):
        raise ErreurConfig(f"[{section}] {cle} : liste de nombres croissants attendue, reçu {brut!r}")
    valeurs = tuple(_flottant(x, cle, section, mini=-100, maxi=1000) for x in brut)
    if not valeurs:
        raise ErreurConfig(f"[{section}] {cle} : au moins une borne est attendue")
    if any(b <= a for a, b in zip(valeurs, valeurs[1:], strict=False)):
        raise ErreurConfig(f"[{section}] {cle} : bornes non strictement croissantes ({list(valeurs)})")
    return valeurs


def _evitement(e: Any, i: int) -> Evitement:
    section = f"evitements[{i}]"
    if not isinstance(e, dict):
        raise ErreurConfig(f"{section} : table attendue")
    return Evitement(
        nom=str(e.get("nom", f"évitement {i + 1}")),
        latitude=_nombre(e, "latitude", section, -90, 90),
        longitude=_nombre(e, "longitude", section, -180, 180),
        rayon_m=_flottant(e.get("rayon_m", 200.0), "rayon_m", section, mini=10, maxi=20000),
    )


def _section(d: dict[str, Any], nom: str, *, requis: bool = True) -> dict[str, Any]:
    """La table `[nom]`, ou une table vide quand `requis=False` et qu'elle est absente.

    `requis=False` sert au chargement allégé des commandes de comptes
    (`ourouler inviter`, `invitations`, `reinitialiser`, `retirer`) : elles
    n'ont besoin ni de `[depart]` ni de `[cycliste]`, et un TOML hébergé sans
    tiers 3 (Q35/Q66) ne les porte pas — voir `charger`/`depuis_dict`.
    Une section **présente** mais du mauvais type reste toujours un refus,
    `requis` ou pas : ce n'est plus une absence, c'est un TOML fautif.
    """
    s = d.get(nom)
    if s is None and not requis:
        return {}
    if not isinstance(s, dict):
        raise ErreurConfig(f"section [{nom}] manquante")
    return s


def _champ(section: str, cle: str) -> str:
    """« [meteo] horizon_h » pour une section TOML, « velos[0] masse_kg » pour un élément."""
    return f"{section} {cle}" if "[" in section else f"[{section}] {cle}"


def _nombre(
    s: dict[str, Any],
    cle: str,
    section: str,
    mini: float,
    maxi: float,
    *,
    requis: bool = True,
    defaut: float = 0.0,
) -> float:
    """`requis=False` : une clé absente rend `defaut` plutôt qu'un refus.

    Comme `_section(..., requis=False)`, sert au chargement allégé des
    commandes de comptes — une valeur présente reste soumise aux mêmes
    bornes, `requis` ou pas.
    """
    if cle not in s:
        if requis:
            raise ErreurConfig(f"[{section}] {cle} manquant")
        return defaut
    return _flottant(s[cle], cle, section, mini=mini, maxi=maxi)


def _nombre_optionnel(
    s: dict[str, Any], cle: str, section: str, mini: float, maxi: float
) -> float | None:
    """Comme `_nombre`, mais une clé absente ou vide rend `None` plutôt que de refuser.

    Écrit pour `cycliste.ftp_w` (facultative depuis le 19/09/2026,
    `docs/journal/ux/parcours_accueil.md`) : l'absence n'est plus une configuration
    fautive, c'est un profil qui n'a pas encore d'étage T3 franchi. Une
    valeur **présente** reste soumise aux mêmes bornes qu'avant — ce n'est
    pas parce que le champ est facultatif qu'une FTP de 4 W devient plausible.
    `""` (chaîne vide) compte comme absente : c'est ce qu'un profil JSON de
    l'API écrit pour « je corrige, mais je n'ai encore rien tapé » plutôt que
    d'omettre la clé.
    """
    if cle not in s or s[cle] is None or s[cle] == "":
        return None
    return _flottant(s[cle], cle, section, mini=mini, maxi=maxi)


def _flottant(
    x: Any,
    cle: str,
    section: str,
    *,
    mini: float | None = None,
    maxi: float | None = None,
) -> float:
    """Une valeur de configuration en `float`, ou `ErreurConfig` nommant le champ.

    Les booléens sont refusés : `latitude = true` passait à 1.0 parce que
    `bool` hérite de `int`, et la commande partait interroger Open-Meteo à
    une latitude de 1° sans un mot. Un `true` dans un champ numérique est
    une faute de frappe, pas une valeur.
    """
    if isinstance(x, bool):
        raise ErreurConfig(f"{_champ(section, cle)} : nombre attendu, reçu le booléen {x!r}")
    try:
        valeur = float(x)
    except (TypeError, ValueError) as e:
        raise ErreurConfig(f"{_champ(section, cle)} : nombre attendu, reçu {x!r}") from e
    if valeur != valeur or valeur in (float("inf"), float("-inf")):
        raise ErreurConfig(f"{_champ(section, cle)} : nombre fini attendu, reçu {x!r}")
    if mini is not None and maxi is not None and not mini <= valeur <= maxi:
        raise ErreurConfig(
            f"{_champ(section, cle)} = {valeur} hors de [{mini}, {maxi}]",
            champ=cle,
            section=section,
            mini=mini,
            maxi=maxi,
            valeur=valeur,
        )
    return valeur


def _entier(
    x: Any,
    cle: str,
    section: str,
    *,
    mini: int | None = None,
    maxi: int | None = None,
    parmi: tuple[int, ...] | None = None,
) -> int:
    """Un entier de configuration, ou `ErreurConfig` nommant le champ.

    `int(meteo.get(...))` laissait remonter la `ValueError` brute de
    `int("huit")` : trace et code 1, là où le contrat demande une erreur
    utilisateur nommant le champ. Les bornes sont vérifiées ici plutôt qu'au
    moment de s'en servir, pour que la faute soit signalée au chargement.
    """
    if isinstance(x, bool):
        raise ErreurConfig(f"{_champ(section, cle)} : entier attendu, reçu le booléen {x!r}")
    try:
        valeur = int(x)
    except (TypeError, ValueError) as e:
        raise ErreurConfig(f"{_champ(section, cle)} : entier attendu, reçu {x!r}") from e
    if isinstance(x, float) and valeur != x:
        raise ErreurConfig(f"{_champ(section, cle)} : entier attendu, reçu {x!r}")
    if parmi is not None and valeur not in parmi:
        raise ErreurConfig(f"{_champ(section, cle)} = {valeur}, attendu un de {parmi}")
    if mini is not None and valeur < mini:
        raise ErreurConfig(f"{_champ(section, cle)} = {valeur}, attendu entre {mini} et {maxi}")
    if maxi is not None and valeur > maxi:
        raise ErreurConfig(f"{_champ(section, cle)} = {valeur}, attendu entre {mini} et {maxi}")
    return valeur


def _distances(brut: Any) -> tuple[float, ...]:
    """Les distances de couronne, toutes strictement positives.

    Une distance négative ou nulle était silencieusement ignorée plus loin
    (`couronne.py`) : l'utilisateur obtenait une table sans la couronne
    demandée et sans explication. Le contrat veut que `ErreurConfig` nomme le
    champ fautif, et c'est le rôle de ce module.
    """
    try:
        valeurs = tuple(float(x) for x in brut)
    except (TypeError, ValueError) as e:
        raise ErreurConfig(f"[meteo] distances_km : liste de nombres attendue, reçu {brut!r}") from e
    fautives = [x for x in valeurs if x <= 0]
    if fautives:
        raise ErreurConfig(
            f"[meteo] distances_km : distance(s) négative(s) ou nulle(s) "
            f"{fautives} — une couronne se mesure en km strictement positifs"
        )
    return valeurs


def _date(x: Any, champ: str) -> date:
    # `isinstance(x, date)` est vrai pour un `datetime` : TOML accepte
    # parfaitement `historique_depuis = 2023-12-01T00:00:00`, et le `datetime`
    # qui en sortait cassait la première comparaison de période en
    # `TypeError: '<=' not supported between date and datetime`. On le ramène
    # donc à sa date avant tout autre test.
    if isinstance(x, datetime):
        return x.date()
    if isinstance(x, date):
        return x
    texte = str(x)
    try:
        return date.fromisoformat(texte)
    except ValueError:
        pass
    try:
        # Même tolérance pour la forme écrite en chaîne (« 2024-03-01T06:30:00 »).
        return datetime.fromisoformat(texte).date()
    except ValueError as e:
        raise ErreurConfig(f"{champ} : date AAAA-MM-JJ attendue, reçu {x!r}") from e


def _velo(v: Any, i: int) -> Velo:
    section = f"velos[{i}]"
    if not isinstance(v, dict) or not v.get("nom"):
        raise ErreurConfig(f"{section} : nom manquant")
    usage = str(v.get("usage", "route"))
    if usage not in USAGES_VELO:
        raise ErreurConfig(f"{section} usage = {usage!r}, attendu un de {USAGES_VELO}")
    periodes = []
    for j, p in enumerate(v.get("periodes", []) or []):
        if not isinstance(p, dict) or "debut" not in p:
            raise ErreurConfig(f"{section}.periodes[{j}] : debut manquant")
        periodes.append(
            Periode(
                debut=_date(p["debut"], f"{section}.periodes[{j}].debut"),
                fin=_date(p["fin"], f"{section}.periodes[{j}].fin") if p.get("fin") else None,
            )
        )
    return Velo(
        nom=str(v["nom"]),
        usage=usage,
        # `float(v["masse_kg"])` laissait passer la ValueError brute de
        # `float("leger")` : trace et code 1 pour une faute de frappe.
        masse_kg=(
            _flottant(v["masse_kg"], "masse_kg", section, mini=1, maxi=50)
            if v.get("masse_kg") is not None
            else None
        ),
        cda_m2=(
            _flottant(v["cda_m2"], "cda_m2", section, mini=0.1, maxi=1.0)
            if v.get("cda_m2") is not None
            else None
        ),
        crr=(
            _flottant(v["crr"], "crr", section, mini=0.001, maxi=0.05)
            if v.get("crr") is not None
            else None
        ),
        intervals_gear=str(v.get("intervals_gear", "") or ""),
        intervals_gear_id=str(v.get("intervals_gear_id", "") or ""),
        capteur_puissance=str(v.get("capteur_puissance", "") or ""),
        periodes=tuple(periodes),
        # Bornes larges à dessein : 0,40 attrape le zéro et le pourcentage
        # écrit en entier (« 87 » au lieu de « 0.87 »), 1,20 laisse passer le
        # cycliste de plaine qui roule abrité en groupe et va plus vite que le
        # modèle solo. Entre les deux, on ne juge pas de ses routes.
        facteur_compteur=(
            _flottant(v["facteur_compteur"], "facteur_compteur", section, mini=0.4, maxi=1.2)
            if v.get("facteur_compteur") is not None
            else None
        ),
        pneu=_pneu(v.get("pneu"), section),
    )


def _pneu(brut: Any, section: str) -> str | None:
    """La catégorie de pneu, ou `None` si absente ou vide. Refusée si inconnue."""
    if brut is None or (isinstance(brut, str) and not brut.strip()):
        return None
    pneu = str(brut).strip().casefold()
    if pneu not in PNEUS_VELO:
        raise ErreurConfig(f"{section} pneu = {brut!r}, attendu un de {PNEUS_VELO}")
    return pneu
