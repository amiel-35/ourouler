"""Configuration : objets de données + chargement TOML.

Règle absolue 2 de CLAUDE.md : ce module et `cli.py` sont les seuls
autorisés à lire un fichier, `Path.home()` ou une variable d'environnement.
Le reste du cœur reçoit un objet `Config` déjà construit.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field, replace
from datetime import date, datetime
from pathlib import Path
from typing import Any

from ourouler.erreurs import ErreurConfig

CHEMIN_CONFIG_DEFAUT = Path("~/.config/ourouler/config.toml")
HISTORIQUE_DEPUIS_DEFAUT = date(2023, 12, 1)
USAGES_VELO = ("route", "clm")

#: Nombres de directions acceptés pour la couronne. Défini ici, et non dans
#: `meteo.couronne`, pour que la validation ait lieu au chargement : c'est ce
#: module qui doit nommer le champ fautif. `couronne.py` le réimporte.
DIRECTIONS_ACCEPTEES = (8, 16)

#: Horizon maximal accepté, en heures : au-delà, AROME HD n'a plus rien à dire.
HORIZON_MAX_H = 48


@dataclass(frozen=True)
class Depart:
    nom: str
    latitude: float
    longitude: float


@dataclass(frozen=True)
class Cycliste:
    masse_kg: float
    ftp_w: float


@dataclass(frozen=True)
class Periode:
    """Intervalle de dates pendant lequel un vélo a servi. `fin` None = encore en service."""

    debut: date
    fin: date | None = None

    def contient(self, jour: date) -> bool:
        return self.debut <= jour and (self.fin is None or jour <= self.fin)


@dataclass(frozen=True)
class Velo:
    nom: str
    usage: str = "route"
    masse_kg: float | None = None
    cda_m2: float | None = None
    crr: float | None = None  # coefficient de roulement, estimé par la calibration (S3)
    intervals_gear: str = ""
    intervals_gear_id: str = ""
    capteur_puissance: str = ""  # valeur exacte du champ Intervals `power_meter`, ex. « MARQUE 1234 »
    periodes: tuple[Periode, ...] = ()


@dataclass(frozen=True)
class ParametresMeteo:
    directions: int = 8
    distances_km: tuple[float, ...] = (15.0, 25.0, 40.0)
    modele: str = "meteofrance_arome_france_hd"
    second_avis: str = "icon_seamless"
    horizon_h: int = 6


@dataclass(frozen=True, repr=False)
class ParametresIntervals:
    """`repr` explicite (d'où `repr=False` sur la dataclass) : la clé ne doit jamais s'imprimer.

    Une trace pytest (`-l`), un futur log de contexte ou un `print(config)`
    suffirait à publier la clé d'API si le `repr` engendré était conservé.
    `Config` imprime ses champs avec leur `repr`, le masquage se propage donc.
    """

    athlete_id: str = ""
    api_key: str = ""

    @property
    def renseigne(self) -> bool:
        return bool(self.athlete_id and self.api_key)

    def __repr__(self) -> str:
        etat = "***" if self.api_key else ""
        return f"ParametresIntervals(athlete_id={self.athlete_id!r}, api_key={etat!r})"


@dataclass(frozen=True)
class ParametresCache:
    dossier: Path = Path("~/.cache/ourouler")


SENS_BOUCLE = ("horaire", "antihoraire")


@dataclass(frozen=True, repr=False)
class ParametresBrouter:
    """Serveur BRouter (auto-hébergé sur Coolify). Le mot de passe n'apparaît jamais dans `repr`."""

    url: str = ""
    utilisateur: str = ""
    mot_de_passe: str = ""
    profil: str = "fastbike"
    timeout_s: float = 120.0

    @property
    def renseigne(self) -> bool:
        return bool(self.url)

    def __repr__(self) -> str:
        etat = "***" if self.mot_de_passe else ""
        return (
            f"ParametresBrouter(url={self.url!r}, utilisateur={self.utilisateur!r}, "
            f"mot_de_passe={etat!r}, profil={self.profil!r}, timeout_s={self.timeout_s!r})"
        )


@dataclass(frozen=True)
class ParametresSeance:
    """Marge de placement d'une séance sur une boucle (sprint 4).

    Seules les zones 2 d'ouverture et de fermeture sont élastiques : toutes
    les récupérations font partie de la prescription et ne bougent pas.

    Les deux élasticités ne sont pas la même chose (Q14, close le 13/09/2026).
    La Z2 d'**ouverture** est le levier de placement : l'allonger fait
    coulisser les blocs jusqu'à un bon couloir, et le mainteneur a fixé sa
    fenêtre à −5 % / +20 %. Le **retour au calme**, lui, ne place rien : il
    referme une boucle dont la longueur n'est jamais exacte, et sa fenêtre est
    largement ouverte vers le haut — « le retour au calme en fait peut dépasser
    de plus, c'est souvent ce que je fais car c'est incontrôlable de faire
    parfait, et c'est du kilomètre facile. Faut réduire le dépassement au max. »
    """

    elasticite_z2_max: float = 0.20  # allongement maximal de la Z2 d'ouverture
    elasticite_z2_min: float = -0.05  # raccourcissement maximal

    #: Allongement maximal du **retour au calme** avant qu'il soit signalé
    #: comme anormal : +150 %. Ce n'est pas une autorisation de dépasser —
    #: chaque minute de dépassement se paie déjà, au prorata et sans seuil
    #: (`seance.placement.PENALITE_CALME_ALLONGE_KM_PAR_H`) — c'est la limite
    #: au-delà de laquelle le dépassement n'est plus « la boucle qui ne tombe
    #: pas juste » mais une boucle qui ne va pas avec la séance.
    elasticite_calme_max: float = 1.5
    #: Raccourcissement maximal du retour au calme, inchangé : amputer une
    #: séance reste un vrai défaut, et il se paie très cher
    #: (`seance.placement.PENALITE_SEANCE_NON_TENUE`).
    elasticite_calme_min: float = -0.05

    demi_tour_penalite: float = 1.0  # coût d'un bloc qui reprend le segment précédent à l'envers

    #: Puissance d'endurance du cycliste, en fraction de sa FTP. Elle sert de
    #: cible aux étapes prescrites en **zone de fréquence cardiaque basse**
    #: (Z1, Z2), dont la traduction par la table des zones de puissance donne
    #: un résultat faux (Q11, close le 13/09/2026 : la médiane mesurée sur
    #: 96 sorties extérieures de plus d'une heure est 60 % de FTP).
    puissance_endurance_pct: float = 0.60

    #: Sous cette part de FTP, une étape n'est pas un bloc : c'est de
    #: l'échauffement, de la récupération ou du retour au calme. Dernier
    #: recours du typage, quand la séance ne porte ni marqueur ni texte —
    #: c'est le cas des séances de coach en pourcentage de FTP.
    seuil_recuperation_pct: float = 0.75

    #: Écart relatif de note de placement en dessous duquel deux boucles
    #: comptent comme équivalentes. Depuis le sprint 5 la note inclut le
    #: vent, donc deux boucles ne sont quasiment plus jamais égales au bit
    #: près : sans cette tolérance, le vent l'emporterait toujours, même sur
    #: un écart de note minuscule, et la pluie ne départagerait plus jamais
    #: comme au sprint 4. Au-dessus du seuil, c'est la note — vent compris —
    #: qui décide directement.
    #:
    #: **Ce n'est pas un réglage technique, c'est une préférence du
    #: cycliste** : « le vent doit-il faire préférer une boucle plus mouillée
    #: à une boucle plus sèche ? » Le défaut ci-dessous répond non dans le cas
    #: mesuré en L5.1 (deux boucles de même relief, seul le vent les
    #: distingue) : voir `docs/sprint5_contrat.md` §1.6 pour la mesure sur
    #: les boucles réelles du mainteneur qui le justifie. 0.0 = le vent
    #: tranche toujours, sans tolérance — l'autre réponse possible.
    tolerance_egalite: float = 0.15


@dataclass(frozen=True)
class ParametresTenue:
    """Seuils de tenue. Les bornes sont en ressenti, croissantes."""

    #: très froid < 3 ; froid < 9 ; frais < 15 ; modéré < 22 ; chaud < 30 ; canicule au-delà.
    bornes_c: tuple[float, ...] = (3.0, 9.0, 15.0, 22.0, 30.0)
    #: sec < 0,2 ; humide < 0,5 ; averses < 1,0 ; pluie au-delà, en mm/h.
    bornes_pluie_mmh: tuple[float, ...] = (0.2, 0.5, 1.0)
    vent_veste_kmh: float = 30.0
    #: Tenue par catégorie de température : {"froid": ["collant", "veste"], …}.
    #: Vide = le jeu par défaut de `seance/tenue.py`. Les catégories données
    #: remplacent celles du défaut, une par une.
    tenues: tuple[tuple[str, tuple[str, ...]], ...] = ()

    def tenue_de(self, categorie: str) -> tuple[str, ...] | None:
        """Les vêtements configurés pour une catégorie, ou None si non configurée."""
        for nom, pieces in self.tenues:
            if nom == categorie:
                return pieces
        return None


@dataclass(frozen=True)
class ParametresCalibration:
    # Une sortie dont le nom contient un de ces mots est écartée de la
    # calibration (peloton). Les quatre valeurs du contrat de sprint §0 : la
    # recherche étant par sous-chaîne, « club » couvre déjà « sortie club »,
    # mais la valeur par défaut doit dire ce que le contrat écrit.
    mots_groupe: tuple[str, ...] = ("club", "groupe", "peloton", "sortie club")
    part_validation: float = 0.25  # part des sorties (les plus récentes) réservée au test
    vitesse_min_kmh: float = 8.0


@dataclass(frozen=True)
class Evitement:
    """Zone à éviter, transmise au moteur de tracé (nogo BRouter)."""

    nom: str
    latitude: float
    longitude: float
    rayon_m: float = 200.0


@dataclass(frozen=True)
class ParametresBoucle:
    vitesse_moyenne_kmh: float = 27.0  # en attendant le modèle physique (S3)
    sens: str = "horaire"  # sens de boucle préféré (horaire en France, antihoraire au Royaume-Uni)
    candidates: int = 5
    tolerance_distance: float = 0.10  # écart relatif accepté sur la distance cible


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


def charger(chemin: Path | None = None) -> Config:
    """Lit un fichier TOML et construit la `Config`. Chemin par défaut : ~/.config/ourouler/config.toml."""
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
    config = depuis_dict(brut)
    # Seul endroit où « ~ » est développé : le cœur reçoit un chemin absolu.
    return replace(config, cache=ParametresCache(config.cache.dossier.expanduser()))


def depuis_dict(d: dict[str, Any]) -> Config:
    """Construit la `Config` depuis un dictionnaire (contenu TOML déjà lu). Valide et nomme les champs."""
    if not isinstance(d, dict):
        # Un TOML valide donne toujours un dict, mais `depuis_dict` est aussi
        # appelée directement (tests, futurs appelants) : une liste ou une
        # chaîne finissait en `AttributeError: 'list' object has no attribute
        # 'get'`, donc une trace et un code 1 au lieu d'un message.
        raise ErreurConfig(f"configuration : dictionnaire attendu, reçu {type(d).__name__}")
    depart = _section(d, "depart")
    cycliste = _section(d, "cycliste")
    velos = tuple(_velo(v, i) for i, v in enumerate(d.get("velos", []) or []))
    if not velos:
        velos = (Velo(nom="Route"),)
    meteo = d.get("meteo", {}) or {}
    intervals = d.get("intervals", {}) or {}
    cache = d.get("cache", {}) or {}
    brouter = d.get("brouter", {}) or {}
    boucle = d.get("boucle", {}) or {}
    calibration = d.get("calibration", {}) or {}
    seance_brut = d.get("seance", {}) or {}
    tenue_brut = d.get("tenue", {}) or {}
    evitements = tuple(_evitement(e, i) for i, e in enumerate(d.get("evitements", []) or []))
    sens = str(boucle.get("sens", "horaire"))
    if sens not in SENS_BOUCLE:
        raise ErreurConfig(f"[boucle] sens = {sens!r}, attendu un de {SENS_BOUCLE}")
    return Config(
        depart=Depart(
            nom=str(depart.get("nom", "Départ")),
            latitude=_nombre(depart, "latitude", "depart", -90, 90),
            longitude=_nombre(depart, "longitude", "depart", -180, 180),
        ),
        cycliste=Cycliste(
            masse_kg=_nombre(cycliste, "masse_kg", "cycliste", 20, 300),
            ftp_w=_nombre(cycliste, "ftp_w", "cycliste", 50, 1000),
        ),
        velos=velos,
        meteo=ParametresMeteo(
            directions=_entier(
                meteo.get("directions", 8), "directions", "meteo", parmi=DIRECTIONS_ACCEPTEES
            ),
            distances_km=_distances(meteo.get("distances_km", (15, 25, 40))),
            modele=str(meteo.get("modele", ParametresMeteo.modele)),
            second_avis=str(meteo.get("second_avis", ParametresMeteo.second_avis)),
            horizon_h=_entier(
                meteo.get("horizon_h", 6), "horizon_h", "meteo", mini=1, maxi=HORIZON_MAX_H
            ),
        ),
        intervals=ParametresIntervals(
            athlete_id=str(intervals.get("athlete_id", "") or ""),
            api_key=str(intervals.get("api_key", "") or ""),
        ),
        cache=ParametresCache(dossier=Path(str(cache.get("dossier", "~/.cache/ourouler")))),
        brouter=ParametresBrouter(
            url=str(brouter.get("url", "") or "").rstrip("/"),
            utilisateur=str(brouter.get("utilisateur", "") or ""),
            mot_de_passe=str(brouter.get("mot_de_passe", "") or ""),
            profil=str(brouter.get("profil", "fastbike") or "fastbike"),
            timeout_s=_flottant(brouter.get("timeout_s", 120.0), "timeout_s", "brouter", mini=1, maxi=600),
        ),
        boucle=ParametresBoucle(
            vitesse_moyenne_kmh=_flottant(
                boucle.get("vitesse_moyenne_kmh", 27.0), "vitesse_moyenne_kmh", "boucle", mini=5, maxi=60
            ),
            sens=sens,
            candidates=_entier(boucle.get("candidates", 5), "candidates", "boucle", mini=1, maxi=20),
            tolerance_distance=_flottant(
                boucle.get("tolerance_distance", 0.10), "tolerance_distance", "boucle", mini=0.01, maxi=0.5
            ),
        ),
        calibration=ParametresCalibration(
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
        ),
        seance=ParametresSeance(
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
            puissance_endurance_pct=_flottant(
                seance_brut.get("puissance_endurance_pct", 0.60),
                "puissance_endurance_pct",
                "seance",
                mini=0.40,
                maxi=0.80,
            ),
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
        ),
        tenue=ParametresTenue(
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
        ),
        evitements=evitements,
        historique_depuis=_date(d.get("historique_depuis", HISTORIQUE_DEPUIS_DEFAUT), "historique_depuis"),
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


def _section(d: dict[str, Any], nom: str) -> dict[str, Any]:
    s = d.get(nom)
    if not isinstance(s, dict):
        raise ErreurConfig(f"section [{nom}] manquante")
    return s


def _champ(section: str, cle: str) -> str:
    """« [meteo] horizon_h » pour une section TOML, « velos[0] masse_kg » pour un élément."""
    return f"{section} {cle}" if "[" in section else f"[{section}] {cle}"


def _nombre(s: dict[str, Any], cle: str, section: str, mini: float, maxi: float) -> float:
    if cle not in s:
        raise ErreurConfig(f"[{section}] {cle} manquant")
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
        raise ErreurConfig(f"{_champ(section, cle)} = {valeur} hors de [{mini}, {maxi}]")
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
    )
