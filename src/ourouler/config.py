"""Configuration : objets de données + chargement TOML.

Règle absolue 2 de CLAUDE.md : ce module et `cli.py` sont les seuls
autorisés à lire un fichier, `Path.home()` ou une variable d'environnement.
Le reste du cœur reçoit un objet `Config` déjà construit.
"""

from __future__ import annotations

import dataclasses
import os
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import date, datetime
from pathlib import Path
from typing import Any

from ourouler.erreurs import ErreurConfig
from ourouler.seance.modele import ZONES_PUISSANCE_DEFAUT
from ourouler.seance.zones import (
    POSITION_ENDURANCE_DEFAUT,
    ZONE_ENDURANCE,
    position_endurance,
    puissance_endurance_pct,
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

#: Préfixe commun des variables d'environnement lues par `charger()` (contrat
#: de l'hébergé minimal, docs/heberge_minimal_contrat.md § « Les secrets »).
PREFIXE_ENV = "OUROULER_"

#: Nombres de directions acceptés pour la couronne. Défini ici, et non dans
#: `meteo.couronne`, pour que la validation ait lieu au chargement : c'est ce
#: module qui doit nommer le champ fautif. `couronne.py` le réimporte.
DIRECTIONS_ACCEPTEES = (8, 16)

#: Horizon maximal accepté, en heures : au-delà, AROME HD n'a plus rien à dire.
HORIZON_MAX_H = 48

#: Jusqu'à combien de jours en avant on accepte de demander une météo pour un
#: parcours (Q40 a). **Mesuré le 17/09/2026 sur le vrai service**, depuis un
#: point français, avec les deux modèles par défaut : AROME HD rendait sa
#: dernière valeur le 19/09 à 03 h (J+2), `icon_seamless` le 24/09 à 12 h
#: (J+7). C'est donc le **modèle de repli** qui fixe la portée du produit.
#:
#: Réglable parce que la portée appartient au modèle et non au projet :
#: quelqu'un qui configure un autre second avis a un autre horizon, et un
#: chiffre en dur mentirait pour lui. Au-delà, le parcours est servi et la
#: météo déclarée absente sans qu'Open-Meteo soit appelé (`meteo.portee`).
HORIZON_JOURS_DEFAUT = 7

#: Borne haute acceptée pour `[meteo] horizon_jours` : Open-Meteo ne publie
#: pas de prévision au-delà de seize jours, quel que soit le modèle.
HORIZON_JOURS_MAX = 16


@dataclass(frozen=True)
class Depart:
    nom: str
    latitude: float
    longitude: float


@dataclass(frozen=True)
class Cycliste:
    masse_kg: float
    ftp_w: float

    #: Identité du compte. Décision du mainteneur (17/09/2026, Q36) : « nom
    #: prénom obligatoire car c'est la base, voilà, point. » L'assistant de
    #: configuration **est** la création du profil (Q36) — il n'y a pas
    #: d'étape « identité » séparée des autres — et il refuse maintenant de
    #: continuer sans les deux, au même titre que sans point de départ.
    #:
    #: **Optionnels ici, dans le cœur, et c'est volontaire.** L'obligation est
    #: une règle de *parcours* (l'assistant), pas une règle de *chargement* :
    #: une configuration écrite avant ce lot — celle du mainteneur comprise —
    #: ne porte ni l'un ni l'autre, et doit continuer à se charger et à se
    #: modifier (FTP, poids, vélos, tout le reste) sans qu'on lui invente un
    #: nom. Même traitement que la migration `puissance_endurance_pct` →
    #: `position_zone` (`_position_zone`, plus bas) et que la colonne
    #: propriétaire des dépôts (`api/depots.py`) : ce qui existait déjà
    #: continue de tourner, la nouvelle règle s'applique à ce qui s'écrit à
    #: partir de maintenant. Une valeur absente reste une chaîne vide, jamais
    #: un nom inventé — la règle absolue 1 l'interdirait de toute façon.
    #:
    #: **Aucun calcul du cœur ne s'en sert aujourd'hui** — ni le modèle
    #: physique, ni les zones, ni la tenue (règle absolue 5 : on n'affirme pas
    #: un usage qui n'existe pas). L'usage réel attend le lot F3 des comptes
    #: multi-utilisateurs : l'e-mail d'invitation et l'affichage d'un compte
    #: parmi plusieurs. Jusque-là, c'est une donnée de compte pure.
    prenom: str = ""
    nom: str = ""


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

    #: Rapport entre la moyenne d'une vraie sortie — distance divisée par le
    #: **temps écoulé**, arrêts compris — et la vitesse à plat, sans vent,
    #: lancé, que le modèle prédit à la même puissance. C'est la troisième
    #: valeur de l'écran de FTP (décision 8 du cycle UX) : celle qui empêche
    #: quelqu'un de saisir sa moyenne de compteur dans le champ « à plat » et
    #: de décaler tout son escalier de zones.
    #:
    #: **Par vélo, et non par cycliste** : le chrono et la route n'ont ni la
    #: même aérodynamique ni les mêmes parcours, et la mesure du 16/09/2026 les
    #: sépare de trois points. **Réglage utilisateur, et non constante** : le
    #: facteur dépend de la masse du cycliste autant que de ses routes, et un
    #: chiffre écrit en dur serait celui d'un seul homme.
    #:
    #: `None` — le cas d'un vélo neuf ou d'un utilisateur sans historique —
    #: fait tomber le cœur sur `physique.modele.facteur_compteur_defaut`, qui
    #: le dérive du modèle et de la masse sur une sortie de référence. C'est
    #: une supposition, pas une mesure, et l'écran doit le dire. La mesure se
    #: fait avec `tests/validation/facteur_compteur_retrospectif.py`.
    facteur_compteur: float | None = None


@dataclass(frozen=True)
class ParametresMeteo:
    directions: int = 8
    distances_km: tuple[float, ...] = (15.0, 25.0, 40.0)
    modele: str = "meteofrance_arome_france_hd"
    second_avis: str = "icon_seamless"
    horizon_h: int = 6
    #: Jusqu'à combien de jours en avant on accepte de demander une météo
    #: (Q40 a). Au-delà, le parcours est servi et la météo déclarée absente,
    #: **sans appeler Open-Meteo** — voir `meteo.portee`. La valeur par défaut
    #: est celle du modèle de repli, mesurée sur le vrai service.
    horizon_jours: int = HORIZON_JOURS_DEFAUT


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

    #: Les bornes des zones de **puissance**, en fraction de FTP, de Z1 à Z7.
    #:
    #: Éditable depuis la décision 7 du cycle UX : la table était jusque-là une
    #: constante Python que rien ne reliait à `Config`, contrairement à tous
    #: les autres réglages de séance. Le défaut est la table de Coggan
    #: (`seance/modele.ZONES_PUISSANCE_DEFAUT`), celle que le compte
    #: Intervals.icu du mainteneur renvoie au pourcent près.
    zones_pct: tuple[tuple[float, float], ...] = ZONES_PUISSANCE_DEFAUT

    #: **La position du cycliste dans sa bande**, entre 0 (bas de la zone) et
    #: 1 (haut). C'est la seule chose qu'on stocke, et c'est la décision 7 :
    #: « on stocke la position dans la zone, pas la valeur — comme ça la FTP
    #: change ou les zones décalent, on suit ». Elle se propage à toutes les
    #: zones fermées : qui se met au milieu de sa Z2 prend le milieu de sa Z3.
    #:
    #: Le défaut n'est pas un chiffre choisi mais la position qu'occupe la
    #: puissance d'endurance **mesurée** du mainteneur (0,60 de FTP, Q11) dans
    #: la Z2 de la table par défaut — de sorte que la dérivation ne change
    #: aucun comportement (règle absolue 5).
    #:
    #: Bornes de chargement : [`POSITION_ZONE_MINI`, `POSITION_ZONE_MAXI`],
    #: soit au plus une largeur de bande au-dessous ou au-dessus. Une position
    #: hors bande se voit et se dit ; elle ne se corrige pas à l'insu du
    #: cycliste (décision 8). Le chemin de migration depuis
    #: `puissance_endurance_pct` passe par **ces bornes-là** (`_position_zone`)
    #: : ce qui se charge doit pouvoir se recharger.
    position_zone: float = POSITION_ENDURANCE_DEFAUT

    @property
    def puissance_endurance_pct(self) -> float:
        """Puissance d'endurance en fraction de FTP — **dérivée**, plus stockée.

        Elle sert de cible aux étapes prescrites en **zone de fréquence
        cardiaque basse** (Z1, Z2 de FC), dont la traduction par la table des
        zones de puissance donne un résultat faux (Q11, close le 13/09/2026).
        Depuis la décision 7 elle n'est plus un réglage : elle se lit dans la
        Z2 de `zones_pct`, à `position_zone`. C'est une
        propriété et non un champ — les appelants ne changent pas, et il n'y a
        plus deux définitions de « la Z2 » qui puissent diverger.
        """
        return puissance_endurance_pct(self.position_zone, self.zones_pct)

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


#: Ce que `en_dict_public` écrit à la place d'un secret renseigné. Une chaîne
#: fixe, jamais un compte de caractères : la longueur d'une clé est déjà une
#: information.
MASQUE = "***"


def en_dict_public(config: Config) -> dict:
    """La configuration en dictionnaire, **secrets masqués**, prête à publier.

    Existe parce que `dataclasses.asdict` ne voit que les champs : il ignore
    les `__repr__` qui masquent, et il ignore aussi les propriétés dérivées.
    Le masquage vivait donc en deux lignes à l'intérieur de `cli.py`, après
    l'`asdict` — et la relecture des tests de contrat de l'API l'a relevé :
    **l'API n'avait rien à réutiliser**, elle aurait réécrit son propre
    masquage, et un masquage qu'on réécrit est un masquage qu'on oublie.

    Ce que cette fonction garantit, et qui se teste :

    - la clé Intervals et le mot de passe BRouter ne sortent jamais en clair ;
    - un secret absent rend une chaîne vide, pas `MASQUE` — pour qu'un écran
      puisse distinguer « non renseigné » de « renseigné, caché » ;
    - `puissance_endurance_pct`, devenue une **propriété** dérivée de la
      position dans la zone (décision 7), reste présente : sans ça elle
      disparaîtrait du contrat d'API sans que rien ne le signale.

    Ce qui n'est **pas** un secret et sort en clair : l'URL du serveur BRouter
    et l'identifiant d'athlète Intervals — une adresse et un identifiant, que
    le mainteneur a déjà tranchés comme publiables (Q6).
    """
    d = dataclasses.asdict(config)
    d["intervals"]["api_key"] = MASQUE if config.intervals.api_key else ""
    d["brouter"]["mot_de_passe"] = MASQUE if config.brouter.mot_de_passe else ""
    d["seance"]["puissance_endurance_pct"] = config.seance.puissance_endurance_pct
    return d


def charger(chemin: Path | None = None, *, environ: Mapping[str, str] | None = None) -> Config:
    """Lit un fichier TOML, le complète depuis l'environnement, et construit la `Config`.

    Chemin par défaut : ~/.config/ourouler/config.toml. `environ` est
    injectable pour les tests (défaut : `os.environ`, jamais lu ailleurs que
    dans ce module et `cli.py`, règle absolue 2).

    Contrat de l'hébergé minimal (docs/heberge_minimal_contrat.md, § « Les
    secrets ») : la tâche planifiée conteneurisée n'a ni fichier de
    configuration personnel dans l'image, ni coordonnée de départ commitée.
    La clé Intervals, le point de départ et le serveur BRouter viennent donc
    de l'environnement — posés dans l'interface Coolify, jamais écrits
    ailleurs — et l'emportent sur le TOML quand ils sont présents. Pour
    l'usage local (CLI interactive), rien ne change : sans ces variables,
    le TOML seul décide, comme avant.
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
    return finaliser(brut, environ=environ)


def finaliser(brut: dict[str, Any], *, environ: Mapping[str, str] | None = None) -> Config:
    """La fin du chargement, à partir d'un dict TOML déjà lu.

    Extraite de `charger` pour l'API (lot F1) : le profil d'un propriétaire
    se superpose au TOML **entre** la lecture du fichier et la validation, et
    `charger` ne laissait aucun point d'entrée à cet endroit-là. Aucun
    changement de comportement : `charger` appelle cette fonction.
    """
    environ = os.environ if environ is None else environ
    config = depuis_dict(_survoler_environnement(brut, environ))
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
    """Pose `section[champ]` depuis `{PREFIXE_ENV}<suffixe>`, si la variable est présente."""
    valeur = environ.get(f"{PREFIXE_ENV}{suffixe}")
    if valeur is not None:
        section[champ] = valeur


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
    zones_pct = _zones_pct(seance_brut.get("zones", ZONES_PUISSANCE_DEFAUT))
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
            # Absents dans toute configuration écrite avant ce lot : une
            # chaîne vide, jamais un refus de chargement (voir la docstring
            # de `Cycliste.prenom`).
            prenom=str(cycliste.get("prenom", "") or ""),
            nom=str(cycliste.get("nom", "") or ""),
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
            horizon_jours=_entier(
                meteo.get("horizon_jours", HORIZON_JOURS_DEFAUT),
                "horizon_jours",
                "meteo",
                mini=0,
                maxi=HORIZON_JOURS_MAX,
            ),
        ),
        intervals=ParametresIntervals(
            athlete_id=str(intervals.get("athlete_id", "") or ""),
            api_key=str(intervals.get("api_key", "") or ""),
        ),
        # `.expanduser()` : un TOML écrit à la main porte presque toujours un
        # `~`, et le cœur qui reçoit ce chemin n'a pas le droit de le résoudre.
        cache=ParametresCache(
            dossier=Path(str(cache.get("dossier") or CACHE_DEFAUT)).expanduser()
        ),
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
        # Bornes larges à dessein : 0,40 attrape le zéro et le pourcentage
        # écrit en entier (« 87 » au lieu de « 0.87 »), 1,20 laisse passer le
        # cycliste de plaine qui roule abrité en groupe et va plus vite que le
        # modèle solo. Entre les deux, on ne juge pas de ses routes.
        facteur_compteur=(
            _flottant(v["facteur_compteur"], "facteur_compteur", section, mini=0.4, maxi=1.2)
            if v.get("facteur_compteur") is not None
            else None
        ),
    )
