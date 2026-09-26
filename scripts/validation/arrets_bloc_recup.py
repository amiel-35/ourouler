#!/usr/bin/env python3
"""Concentration des éléments de circulation : blocs contre récupérations.

**Ce script n'est pas un test pytest.** Il appelle le vrai serveur BRouter et,
pour la question 2, le vrai compte Intervals.icu du mainteneur : les deux sont
interdits dans la suite de tests (règles absolues 1 et 3). Il se lance à la
main, depuis la racine du dépôt :

    uv run python scripts/validation/arrets_bloc_recup.py

La question du mainteneur, dans ses mots : « tu peux faire générer des
itinéraires de type bloc et regarder la concentration des éléments de
circulation — cédez-le-passage, feux, stops, giratoires, etc. — entre récup et
bloc ? » C'est une comparaison **appariée dans la même sortie** : elle
contrôle d'un coup la géographie, la distance au départ, le jour et la météo,
là où comparer à des lots de boucles proposées (comme `marqueurs_retrospectif.
py`) ne contrôle rien de tout cela.

Il y a deux questions distinctes, mesurées l'une après l'autre.

**Question 1 — notre moteur fait-il son travail ?** `seance.placement.placer`
place les blocs en notant le terrain sous eux (`seance.terrain.
evaluer_couloir`) et **n'évalue jamais les récupérations** — règle du sprint 4,
assumée : la récup absorbe le point dur. Si le placement fonctionne, les
blocs d'une séance synthétique posée sur une boucle générée doivent donc
porter moins d'arrêts au kilomètre que les récupérations de la **même**
boucle. C'est une question sur l'**algorithme**, pas sur la pratique du
mainteneur : les séances sont construites ici à la main (§ »synthétique«),
et le mesurer sur beaucoup de directions vaut mieux qu'une comparaison à un
lot de boucles au hasard, parce que chaque sortie contrôle sa propre
géographie.

**Question 2 — le critère est-il réel ?** Le mainteneur place ses blocs à
l'instinct depuis des années. Ses **propres** blocs, en extérieur, tombent-ils
sur des portions plus propres que ses **propres** récupérations ? Les
intervalles enregistrés donnent où un bloc a été réellement roulé
(`ClientIntervals.intervalles`), croisés avec la trace GPS **rejouée** dans
BRouter (même méthode que `scripts/validation/marqueurs_retrospectif.py`, qui
fait déjà ce rejeu) pour obtenir les tags de nœud, absents d'une trace GPS
brute.

**Comment les 21 sorties à blocs en extérieur sont trouvées.** Le plan du
mainteneur ne contient aucune séance à blocs en extérieur programmée au
calendrier — chercher par la séance planifiée du jour ne trouve donc qu'une
poignée de sorties, c'est une erreur déjà commise, on ne la répète pas.
Le nom de l'activité, lui, porte la marque d'une séance à blocs : un motif
« N×M » (« 2x20 », « 4x8 »…), « durabilité », « rappel » ou « dont NN' ».
Sont écartés : le home-trainer (motifs `ht`, `home`, `trainer`, `zwift`,
`ergo`) et l'endurance pure (`EF`, `Z2`, « 3h à… », « 4h30 »). Vérifié sur le
cache réel du mainteneur le 16/09/2026 : ce filtre trouve exactement
**21 jours** (22 activités, un jour en portant deux).

**Ce qui est mesuré, précisément — et pourquoi.**

* **Arrêts et ralentissements, jamais un composite.** `boucle.marqueurs.
  NOEUDS_ARRET` (feux, stops) pose vraiment le pied ; le reste (cédez-le-
  passage, mini-giratoires, passages piétons, ralentisseurs) fait seulement
  lever le pied. Les mélanger a déjà produit une unité trompeuse (Q28,
  8d0c240) : les deux comptes sont donc **toujours rapportés à part**.
* **La concentration, pas seulement la densité — c'est le mot du
  mainteneur.** Un bloc de 5 km avec 4 feux groupés sur 500 m n'est pas un
  bloc avec 4 feux répartis : la densité au kilomètre ne les distingue pas,
  elle vaut 0,8/km dans les deux cas. La mesure retenue ici est **la plus
  longue portion sans arrêt à l'intérieur de l'étape**, en part de sa
  longueur : plus elle est grande, plus les arrêts qui existent sont
  regroupés ailleurs dans l'étape (un groupe de 4 feux sur 500 m dans un bloc
  de 5 km laisse une portion libre de 4,5 km, soit 90 % — contre 20 % pour
  quatre feux régulièrement espacés). Elle n'a de sens qu'à partir de **deux**
  arrêts : avec 0 ou 1, elle vaut trivialement (presque) 100 % et ne dit rien
  d'un regroupement — ces étapes sont donc comptées à part et exclues de la
  distribution de concentration.
* **Apparié, au sein de chaque sortie.** Pour chaque sortie (une boucle et
  une séance posée dessus, ou une activité réelle), on prend la **médiane**
  des blocs et la médiane des récupérations — pas une comparaison de deux
  moyennes globales, qui perdrait l'appariement et laisserait filtrer la
  géographie.

**Les pièges, traités explicitement.**

* **Les récups sont plus courtes que les blocs**, donc leur densité a une
  variance bien plus grande (un seul feu sur 1,5 km pèse plus qu'un seul feu
  sur 5 km). Le test retenu est le **test du signe** : il ne regarde que la
  direction de l'écart dans chaque sortie (bloc < récup, ou l'inverse), jamais
  son amplitude — une récup à densité extrême ne compte pas plus qu'une
  autre. C'est un choix délibéré, pas la fainéantise : un test qui pèse
  l'amplitude (t apparié, Wilcoxon signé) se ferait dominer par le bruit des
  récups courtes.
* **Une portion sans marqueur n'est pas « propre prouvée ».** Un tracé sans
  `segments` (import GPX, activité non rejouée) ne porte aucun tag de nœud :
  `Marqueurs.connue` serait faux, et ce script écarte alors la sortie plutôt
  que de compter un zéro qui ne voudrait rien dire (règle absolue 5, déjà
  tenue par `boucle.marqueurs.Marqueurs.connue`).
* **Le rejeu BRouter n'est pas la trace GPS** (question 2 seulement) : un
  point de passage tous les 1,5 km, le moteur recolle l'itinéraire entre eux
  et peut choisir une rue voisine. La position d'un bloc réel sur le tracé
  rejoué est donc retrouvée par le point **le plus proche géographiquement**
  du début/de la fin du bloc dans la trace GPS d'origine — une approximation
  connue, déjà signalée par `marqueurs_retrospectif.py` pour son propre rejeu.
* **Trouver un effet dans du bruit.** Le projet a deux précédents où
  l'intuition ne tenait pas la mesure (les côtes au sprint 3, l'orientation
  au vent le 16/09). Chaque comparaison de ce script est donc accompagnée
  d'un **contrôle** qui aurait pu la démentir : l'échauffement, une étape
  élastique **jamais notée par `evaluer_couloir`** au même titre qu'une
  récupération, est comparé à la récupération de la même façon. S'il bat
  aussi nettement la récupération, l'écart mesuré sur les blocs n'est pas la
  preuve d'une évaluation de terrain qui fonctionne : ce serait alors la
  simple longueur (l'échauffement dure 40 à 60 min contre quelques minutes
  pour une récup) qui lisse le bruit, pas un choix de couloir.

**Aucune coordonnée ni nom de lieu n'est imprimé ni stocké.** Les sorties
réelles (question 2) sont désignées par leur **date seule**, jamais par le
nom de l'activité — qui, pour ce mainteneur, commence souvent par le nom
d'une commune de départ. Le nom sert uniquement, en mémoire, à décider si
l'activité est une séance à blocs ; il n'est jamais affiché ni écrit dans ce
fichier.
"""

from __future__ import annotations

import argparse
import math
import random
import re
import statistics
import sys
from dataclasses import dataclass, replace
from datetime import date

from ourouler.activites.cache import Cache, EntreeCache
from ourouler.activites.inventaire import en_interieur
from ourouler.apprentissage.routes import points_de_passage
from ourouler.boucle.candidates import appels_pour, generer
from ourouler.boucle.marqueurs import NOEUDS_ARRET, nature_du_noeud
from ourouler.config import Config, charger
from ourouler.connecteurs.brouter import ClientBrouter
from ourouler.connecteurs.intervals import ClientIntervals
from ourouler.noyau.activite import est_sport_velo
from ourouler.noyau.erreurs import ErreurConnecteur, ErreurUtilisateur
from ourouler.noyau.seance import Etape, Seance
from ourouler.noyau.trace import PointTrace, Trace, distance_m
from ourouler.physique.commande import chemin_calibration, parametres_du_velo, velo_demande
from ourouler.physique.modele import Parametres
from ourouler.physique.validation import trace_depuis_activite
from ourouler.seance.commande import longueurs
from ourouler.seance.placement import CLE_MOTIF, Emplacement, placer

# --- réglages ------------------------------------------------------------------

#: Directions testées par séance synthétique (question 1), réparties sur
#: l'horizon : une tous les 45°.
AZIMUTS_Q1 = 8

#: Graine du tirage aléatoire (l'ordre des sorties réelles traitées quand
#: `--sorties` en limite le nombre) : le résultat doit être le même d'une
#: exécution à l'autre.
GRAINE = 20260916

#: Part de la FTP au-dessus de laquelle un intervalle Intervals.icu est un
#: bloc. Même seuil que `terrain_retrospectif.py` (`PART_FTP_BLOC`) et que
#: `seance.modele.SEUIL_RECUPERATION_PCT_DEFAUT` : les trois doivent dire la
#: même chose de ce qui est un bloc.
PART_FTP_BLOC = 0.75

#: Durée minimale d'un bloc, en secondes. Même valeur que `terrain_
#: retrospectif.py` : un pic de puissance de quelques secondes n'est pas un
#: bloc de séance.
DUREE_MIN_BLOC_S = 180.0

#: Distance plancher d'une boucle synthétique (question 1), en km, si
#: l'estimation de longueur de la séance tombait anormalement bas.
DISTANCE_MIN_Q1_KM = 20.0

#: Seuil de significativité en dessous duquel un test du signe est dit net.
#: Choix usuel, pas une valeur mesurée.
SEUIL_P = 0.05

#: Motif d'inclusion d'une activité réelle comme séance à blocs en extérieur :
#: un compte « N×M » (« 2x20 », « 4x8 »…), « durabilité », « rappel » ou
#: « dont NN' ». Vérifié le 16/09/2026 sur le cache réel : 21 jours trouvés.
MOTIF_BLOC_INCLUS = re.compile(r"\d+\s*[x×]\s*\d+|durabilit|rappel|dont\s+\d+", re.IGNORECASE)

#: Motifs d'exclusion : home-trainer (l'outil ne place jamais de bloc dedans,
#: hors de portée de ce script) et endurance pure (aucun bloc à y chercher).
MOTIF_BLOC_EXCLU = re.compile(
    r"\bht\b|\bhome\b|\btrainer\b|\bzwift\b|\bergo\b|\bef\b|\bz2\b|3h\s*[aà]|4h30",
    re.IGNORECASE,
)

#: Libellés lisibles des quatre types d'étape, dans l'ordre où on les roule.
LIBELLE_TYPE = {
    "bloc": "Blocs",
    "recuperation": "Récupérations",
    "echauffement": "Échauffements",
    "calme": "Retours au calme",
}


# --- marqueurs le long d'un tracé, par fenêtre ---------------------------------


def marqueurs_positions(trace: Trace) -> list[tuple[float, str]]:
    """(position en m, nature) de chaque nœud marqué du tracé, triés par position.

    Même dédoublonnage que `boucle.marqueurs.compter` — un nœud n'est compté
    qu'une fois, à la position de son dernier tronçon connu — pour que cette
    mesure parle du même objet que la densité déjà en service.
    """
    if not trace.segments or len(trace.points) < 2:
        return []
    natures: dict[int, str] = {}
    for segment in trace.segments:
        nature = nature_du_noeud(segment.node_tags)
        if nature is not None:
            natures[segment.fin_idx] = nature
    paires = [
        (trace.points[idx].dist_m, nature) for idx, nature in natures.items() if 0 <= idx < len(trace.points)
    ]
    paires.sort(key=lambda p: p[0])
    return paires


def dans_fenetre(
    positions: list[tuple[float, str]], debut_m: float, fin_m: float, marge_m: float = 1e-6
) -> list[tuple[float, str]]:
    """Les marqueurs de `positions` compris dans `[debut_m, fin_m]` (ordre indifférent)."""
    lo, hi = min(debut_m, fin_m), max(debut_m, fin_m)
    return [(p, n) for p, n in positions if lo - marge_m <= p <= hi + marge_m]


def plus_longue_portion_libre_km(positions_arret: list[float], debut_m: float, fin_m: float) -> float | None:
    """La plus longue portion sans arrêt à l'intérieur de l'étape, en km.

    `None` si moins de deux arrêts : voir la justification de la mesure dans
    l'en-tête du fichier — en dessous de deux arrêts, la portion libre vaut
    trivialement (presque) toute l'étape et ne renseigne aucun regroupement.
    """
    if len(positions_arret) < 2:
        return None
    lo, hi = min(debut_m, fin_m), max(debut_m, fin_m)
    bornes = [lo, *sorted(positions_arret), hi]
    ecarts = [b - a for a, b in zip(bornes[:-1], bornes[1:], strict=True)]
    return max(0.0, max(ecarts)) / 1000.0


# --- une mesure, quelle que soit son origine ------------------------------------


@dataclass
class MesureEtape:
    """Une étape (bloc, récup, échauffement, calme) d'une sortie, et ce qu'elle porte.

    `sortie` identifie la sortie pour l'appariement — une date seule pour une
    sortie réelle (question 2), jamais un nom d'activité ni un lieu.
    """

    origine: str  # "Q1 synthétique" | "Q2 réel"
    sortie: str
    type_etape: str
    longueur_km: float
    arrets: int
    ralentit: int
    plus_longue_libre_km: float | None

    @property
    def arrets_par_km(self) -> float | None:
        return self.arrets / self.longueur_km if self.longueur_km > 0 else None

    @property
    def ralentit_par_km(self) -> float | None:
        return self.ralentit / self.longueur_km if self.longueur_km > 0 else None

    @property
    def concentration(self) -> float | None:
        """La plus longue portion libre, en part de la longueur de l'étape."""
        if self.plus_longue_libre_km is None or self.longueur_km <= 0:
            return None
        return min(1.0, self.plus_longue_libre_km / self.longueur_km)


def mesurer_fenetre(
    positions: list[tuple[float, str]],
    debut_m: float,
    fin_m: float,
    *,
    longueur_reelle_km: float,
    type_etape: str,
    sortie: str,
    origine: str,
) -> MesureEtape:
    """Une `MesureEtape` sur un unique passage de `debut_m` à `fin_m`."""
    dans = dans_fenetre(positions, debut_m, fin_m)
    arrets = sum(1 for _, n in dans if n in NOEUDS_ARRET)
    ralentit = sum(1 for _, n in dans if n not in NOEUDS_ARRET)
    positions_arret = [p for p, n in dans if n in NOEUDS_ARRET]
    portion_libre = plus_longue_portion_libre_km(positions_arret, debut_m, fin_m)
    return MesureEtape(
        origine=origine,
        sortie=sortie,
        type_etape=type_etape,
        longueur_km=longueur_reelle_km,
        arrets=arrets,
        ralentit=ralentit,
        plus_longue_libre_km=portion_libre,
    )


# --- question 1 : séances synthétiques sur boucles générées ---------------------


def seance_synthetique(nom: str, etapes: list[tuple[str, float, float]], ftp_w: float) -> Seance:
    """Une `Seance` construite à la main : (type, durée en minutes, fraction de FTP).

    Purement synthétique — aucune donnée du mainteneur : c'est le placement
    lui-même qui est mis à l'épreuve ici (question 1), pas sa pratique.
    """
    construites = [
        Etape(
            type=type_etape,
            duree_s=duree_min * 60.0,
            puissance_min_w=fraction * ftp_w,
            puissance_max_w=fraction * ftp_w,
            libelle=f"{nom} — étape {i + 1}",
            elastique=type_etape in ("echauffement", "calme"),
        )
        for i, (type_etape, duree_min, fraction) in enumerate(etapes)
    ]
    duree_s = sum(e.duree_s for e in construites)
    return Seance(
        nom=nom,
        jour=date(2026, 1, 1),  # sans signification : purement synthétique
        etapes=construites,
        duree_s=duree_s,
        meta={"ftp_w": ftp_w},
    )


def seances_synthetiques(ftp_w: float) -> list[Seance]:
    """Quatre gabarits de séance à blocs, représentatifs de ce qu'un cycliste programme.

    Blocs courts, moyens, récups courtes — c'est délibérément varié : le but
    est de mettre le placement à l'épreuve sur plusieurs formes, pas de
    reproduire une séance précise du mainteneur (c'est le rôle de la
    question 2).

    **Le quatrième gabarit, à échauffement court, a été ajouté après une
    première mesure** (16/09/2026) : avec un échauffement réaliste de 40 à
    60 min, `placer` pousse systématiquement les blocs à plus de 15-20 km du
    départ configuré, où BRouter/OSM ne posent quasiment plus aucun tag de
    nœud autour de Rennes (constaté sur les 8 azimuts × 3 gabarits de la
    première mesure : 96 blocs et 72 récups à **zéro** marqueur, sans
    exception). Les deux premiers gabarits ne peuvent alors rien départager :
    bloc et récup sont tous les deux au plancher. Le quatrième reste dans la
    zone qui porte des marqueurs, pour donner à la mesure quelque chose à
    trancher — voir la conclusion pour ce que cela signifie pour l'axe
    « carrefours » lui-même, pas seulement pour ce script.
    """
    return [
        seance_synthetique(
            "2x20' seuil (synthétique)",
            [
                ("echauffement", 60, 0.60),
                ("bloc", 20, 0.95),
                ("recuperation", 8, 0.55),
                ("bloc", 20, 0.95),
                ("calme", 30, 0.60),
            ],
            ftp_w,
        ),
        seance_synthetique(
            "4x8' SV1 (synthétique)",
            [
                ("echauffement", 45, 0.60),
                ("bloc", 8, 1.05),
                ("recuperation", 4, 0.55),
                ("bloc", 8, 1.05),
                ("recuperation", 4, 0.55),
                ("bloc", 8, 1.05),
                ("recuperation", 4, 0.55),
                ("bloc", 8, 1.05),
                ("calme", 30, 0.60),
            ],
            ftp_w,
        ),
        seance_synthetique(
            "6x4' VO2 (synthétique)",
            [
                ("echauffement", 40, 0.60),
                ("bloc", 4, 1.15),
                ("recuperation", 4, 0.55),
                ("bloc", 4, 1.15),
                ("recuperation", 4, 0.55),
                ("bloc", 4, 1.15),
                ("recuperation", 4, 0.55),
                ("bloc", 4, 1.15),
                ("recuperation", 4, 0.55),
                ("bloc", 4, 1.15),
                ("recuperation", 4, 0.55),
                ("bloc", 4, 1.15),
                ("calme", 25, 0.60),
            ],
            ftp_w,
        ),
        seance_synthetique(
            "3x3' seuil, échauffement court (synthétique)",
            [
                ("echauffement", 10, 0.60),
                ("bloc", 3, 1.00),
                ("recuperation", 3, 0.55),
                ("bloc", 3, 1.00),
                ("recuperation", 3, 0.55),
                ("bloc", 3, 1.00),
                ("calme", 15, 0.60),
            ],
            ftp_w,
        ),
    ]


def fenetre_physique(emplacement: Emplacement) -> tuple[float, float, int]:
    """La fenêtre réellement parcourue sous cette étape, et combien de fois.

    Un bloc — demi-tour ou non — est un passage **unique** : `_couloir`
    (`seance.placement`) donne déjà la fenêtre du seul passage, y compris pour
    la variante demi-tour, qui note le bloc repris en sens inverse comme un
    couloir neuf (voir `placement._variante_demi_tour`). Une récupération en
    demi-tour, elle, est parcourue à l'aller **et** au retour sur le **même**
    couloir : sa `longueur_m` vaut `2 × besoin_m` (la docstring d'`Emplacement`
    le dit explicitement), donc la fenêtre physique ne fait que la moitié,
    parcourue deux fois — chaque marqueur qu'elle contient est donc rencontré
    deux fois par le cycliste.
    """
    if emplacement.demi_tour and emplacement.note is None:
        largeur = emplacement.longueur_m / 2.0
        return emplacement.debut_m, emplacement.debut_m + largeur, 2
    return emplacement.debut_m, emplacement.debut_m + emplacement.longueur_m, 1


def mesurer_emplacement(
    positions: list[tuple[float, str]], emplacement: Emplacement, *, type_etape: str, sortie: str
) -> MesureEtape:
    debut_m, fin_m, traversees = fenetre_physique(emplacement)
    base = mesurer_fenetre(
        positions,
        debut_m,
        fin_m,
        longueur_reelle_km=emplacement.longueur_m / 1000.0,
        type_etape=type_etape,
        sortie=sortie,
        origine="Q1 synthétique",
    )
    if traversees == 1:
        return base
    # La concentration se mesure sur un seul passage (symétrie aller-retour) ;
    # seuls les comptes absolus doublent avec le nombre de traversées.
    return replace(base, arrets=base.arrets * traversees, ralentit=base.ralentit * traversees)


def executer_q1(
    client: ClientBrouter,
    config: Config,
    parametres: Parametres,
    ftp_w: float,
    *,
    azimuts: int,
    bavard: bool,
) -> tuple[list[MesureEtape], list[str]]:
    """Génère des boucles dans plusieurs directions, y place les séances synthétiques."""
    mesures: list[MesureEtape] = []
    manques: list[str] = []
    pas = 360.0 / azimuts
    for seance in seances_synthetiques(ftp_w):
        estimations = longueurs(seance, parametres=parametres)
        distance_m_totale = sum(e.longueur_m for e in estimations if e.longueur_m is not None)
        distance_km = max(distance_m_totale / 1000.0, DISTANCE_MIN_Q1_KM)
        for i in range(azimuts):
            azimut = i * pas
            sortie_id = f"{seance.nom} az {azimut:.0f}°"
            try:
                candidates = generer(
                    client,
                    config.depart,
                    distance_km=distance_km,
                    azimut_deg=azimut,
                    nb=1,
                    tolerance=config.boucle.tolerance_distance,
                    profil=config.brouter.profil,
                    appels_max=appels_pour(1),
                )
            except ErreurConnecteur as e:
                manques.append(f"{sortie_id} : boucle indisponible ({e})")
                continue
            if not candidates:
                manques.append(f"{sortie_id} : aucune boucle rendue")
                continue
            trace = candidates[0].trace
            placement = placer(seance, trace, parametres)
            if placement is None:
                manques.append(f"{sortie_id} : {trace.meta.get(CLE_MOTIF, 'séance non placée')}")
                continue
            positions = marqueurs_positions(trace)
            for emplacement in placement.emplacements:
                type_etape = seance.etapes[emplacement.etape_idx].type
                if emplacement.longueur_m <= 0:
                    continue
                mesures.append(
                    mesurer_emplacement(positions, emplacement, type_etape=type_etape, sortie=sortie_id)
                )
            if bavard:
                print(
                    f"  {sortie_id} : {trace.distance_m / 1000:.1f} km, "
                    f"{len(placement.blocs())} bloc(s) placé(s)"
                )
    return mesures, manques


# --- question 2 : sorties réelles ------------------------------------------------


def nom_indique_bloc_exterieur(nom: str) -> bool:
    """Vrai si ce nom d'activité porte la marque d'une séance à blocs en extérieur."""
    return bool(MOTIF_BLOC_INCLUS.search(nom)) and not MOTIF_BLOC_EXCLU.search(nom)


def sorties_a_bloc(cache: Cache, config: Config) -> list[EntreeCache]:
    """Les activités vélo, extérieures, dont le nom indique une séance à blocs."""
    retenues = []
    for entree in cache.lister(depuis=config.historique_depuis):
        if not est_sport_velo(entree.sport) or en_interieur(entree):
            continue
        if entree.id_externe is None:
            continue  # pas d'identifiant Intervals : pas d'intervalles à lire
        nom = str(entree.meta.get("nom") or "")
        if not nom_indique_bloc_exterieur(nom):
            continue
        retenues.append(entree)
    return retenues


@dataclass(frozen=True)
class SegmentIdentifie:
    type_etape: str
    debut_idx: int
    fin_idx: int
    duree_s: float


def _flottant(brut: object) -> float | None:
    try:
        valeur = float(brut)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return valeur if math.isfinite(valeur) else None


def _entier(brut: object) -> int | None:
    valeur = _flottant(brut)
    return None if valeur is None else int(valeur)


def segments_identifies(
    intervalles: list[dict],
    *,
    ftp_w: float,
    part_ftp: float = PART_FTP_BLOC,
    duree_min_bloc_s: float = DUREE_MIN_BLOC_S,
) -> list[SegmentIdentifie]:
    """Les intervalles Intervals classés bloc / récupération / échauffement / calme.

    Un bloc est un intervalle d'au moins `duree_min_bloc_s` à au moins
    `part_ftp` de FTP (même règle que `terrain_retrospectif.py`). L'intensité
    vient du champ `intensity` d'Intervals (déjà en % de FTP) quand il existe,
    sinon de `average_watts / ftp_w`. Une récupération est tout intervalle
    **entre deux blocs** ; avant le premier bloc ou après le dernier, c'est de
    l'échauffement ou du retour au calme — jamais une récupération de séance.
    """
    bruts = []
    for brut in intervalles:
        duree = _flottant(brut.get("elapsed_time"))
        debut = _entier(brut.get("start_index"))
        fin = _entier(brut.get("end_index"))
        if duree is None or debut is None or fin is None or fin <= debut:
            continue
        intensite = _flottant(brut.get("intensity"))
        puissance = _flottant(brut.get("average_watts"))
        if intensite is not None:
            fraction = intensite / 100.0
        elif puissance is not None and ftp_w > 0:
            fraction = puissance / ftp_w
        else:
            continue
        bruts.append((debut, fin, duree, fraction))
    bruts.sort(key=lambda t: t[0])
    est_bloc = [duree >= duree_min_bloc_s and fraction >= part_ftp for _, _, duree, fraction in bruts]
    if True not in est_bloc:
        return []
    premier = est_bloc.index(True)
    dernier = len(est_bloc) - 1 - est_bloc[::-1].index(True)
    segments = []
    for i, (debut, fin, duree, _fraction) in enumerate(bruts):
        if est_bloc[i]:
            type_etape = "bloc"
        elif i < premier:
            type_etape = "echauffement"
        elif i > dernier:
            type_etape = "calme"
        else:
            type_etape = "recuperation"
        segments.append(SegmentIdentifie(type_etape, debut, fin, duree))
    return segments


def position_sur_trace(point_gps: PointTrace, replay: Trace) -> float:
    """`dist_m` du point du tracé rejoué le plus proche géographiquement de `point_gps`.

    Voir la limite « le rejeu BRouter n'est pas la trace GPS » dans l'en-tête
    du fichier : c'est l'approximation qui relie les deux.
    """
    meilleure_distance, meilleur_dist_m = math.inf, 0.0
    for p in replay.points:
        d = distance_m(point_gps, p)
        if d < meilleure_distance:
            meilleure_distance, meilleur_dist_m = d, p.dist_m
    return meilleur_dist_m


def executer_q2(
    cache: Cache,
    client_brouter: ClientBrouter,
    client_intervals: ClientIntervals,
    config: Config,
    ftp_w: float,
    *,
    combien: int,
    bavard: bool,
) -> tuple[list[MesureEtape], list[str]]:
    """Rejoue les sorties réelles à blocs et mesure où les blocs et récups sont tombés."""
    candidates = sorties_a_bloc(cache, config)
    tirage = random.Random(GRAINE)
    tirage.shuffle(candidates)
    if combien:
        candidates = candidates[:combien]

    mesures: list[MesureEtape] = []
    manques: list[str] = []
    for entree in candidates:
        jour = entree.jour
        sortie_id = str(jour) if jour else entree.identifiant[:8]
        try:
            activite = cache.relire(entree.identifiant)
        except Exception as e:  # noqa: BLE001 — un fichier abîmé ne fait pas tomber la mesure
            manques.append(f"{sortie_id} : illisible ({e})")
            continue
        try:
            intervalles = client_intervals.intervalles(entree.id_externe)
        except ErreurConnecteur as e:
            manques.append(f"{sortie_id} : intervalles indisponibles ({e})")
            continue
        segments = segments_identifies(intervalles, ftp_w=ftp_w)
        blocs = [s for s in segments if s.type_etape == "bloc"]
        recups = [s for s in segments if s.type_etape == "recuperation"]
        if not blocs or not recups:
            manques.append(f"{sortie_id} : pas de paire bloc/récupération exploitable")
            continue
        if trace_depuis_activite(activite) is None:
            manques.append(f"{sortie_id} : pas de trace GPS exploitable")
            continue
        passages = points_de_passage(activite)
        if len(passages) < 2:
            manques.append(f"{sortie_id} : aucune position exploitable pour le rejeu")
            continue
        try:
            replay = client_brouter.itineraire(passages)
        except ErreurConnecteur as e:
            manques.append(f"{sortie_id} : rejeu BRouter impossible ({e})")
            continue
        positions = marqueurs_positions(replay)
        if not positions:
            manques.append(f"{sortie_id} : rejeu sans tags de nœud")
            continue

        points = activite.points
        comptees = 0
        for segment in segments:
            i = min(max(segment.debut_idx, 0), len(points) - 1)
            j = min(max(segment.fin_idx, 0), len(points) - 1)
            if points[i].lat is None or points[j].lat is None or j <= i:
                continue
            d0, d1 = points[i].dist_m, points[j].dist_m
            if d0 is None or d1 is None or d1 <= d0:
                continue
            debut_m = position_sur_trace(PointTrace(points[i].lat, points[i].lon, None, 0.0), replay)
            fin_m = position_sur_trace(PointTrace(points[j].lat, points[j].lon, None, 0.0), replay)
            mesures.append(
                mesurer_fenetre(
                    positions,
                    debut_m,
                    fin_m,
                    longueur_reelle_km=(d1 - d0) / 1000.0,
                    type_etape=segment.type_etape,
                    sortie=sortie_id,
                    origine="Q2 réel",
                )
            )
            comptees += 1
        if bavard:
            print(
                f"  {sortie_id} : {len(blocs)} bloc(s), {len(recups)} récup(s), "
                f"{comptees} étape(s) mesurée(s)"
            )
    return mesures, manques


# --- statistiques ----------------------------------------------------------------


def test_signe(paires: list[tuple[float, float]]) -> tuple[int, int, int, float]:
    """Test du signe apparié : (favorables, défavorables, égalités, p bilatérale).

    « Favorable » = le premier terme de la paire est strictement plus petit
    que le second. Robuste au piège de la variance inégale entre blocs et
    récups (voir l'en-tête du fichier) : seul le **signe** compte, jamais
    l'amplitude. Sous l'hypothèse nulle (aucune préférence), chaque sortie a
    une chance sur deux de tomber d'un côté ; la p-value est celle,
    bilatérale, de la loi binomiale(n, 0,5) — stricte, exacte, sans
    dépendance à `scipy`.
    """
    favorables = sum(1 for a, b in paires if a < b)
    defavorables = sum(1 for a, b in paires if a > b)
    egalites = len(paires) - favorables - defavorables
    n = favorables + defavorables
    if n == 0:
        return favorables, defavorables, egalites, float("nan")
    k = min(favorables, defavorables)
    p_unilaterale = sum(math.comb(n, i) for i in range(0, k + 1)) / (2**n)
    return favorables, defavorables, egalites, min(1.0, 2 * p_unilaterale)


def paires_par_sortie(
    mesures: list[MesureEtape], type_a: str, type_b: str, champ: str
) -> list[tuple[float, float]]:
    """Une paire (médiane `type_a`, médiane `type_b`) par sortie où les deux existent.

    La médiane, pas la moyenne ni chaque étape séparément : c'est ce qui
    fait de la comparaison une comparaison **appariée par sortie**, comme
    demandé, et non une comparaison de deux populations d'étapes qui
    perdrait l'appariement.
    """
    par_sortie: dict[str, dict[str, list[float]]] = {}
    for m in mesures:
        valeur = getattr(m, champ)
        if valeur is None:
            continue
        par_sortie.setdefault(m.sortie, {}).setdefault(m.type_etape, []).append(valeur)
    paires = []
    for par_type in par_sortie.values():
        a, b = par_type.get(type_a), par_type.get(type_b)
        if a and b:
            paires.append((statistics.median(a), statistics.median(b)))
    return paires


def _centile(valeurs_triees: list[float], centile: float) -> float:
    if not valeurs_triees:
        return float("nan")
    k = min(len(valeurs_triees) - 1, int(round(centile / 100 * (len(valeurs_triees) - 1))))
    return valeurs_triees[k]


def imprimer_distribution(titre: str, valeurs: list[float]) -> None:
    if not valeurs:
        print(f"    {titre} : aucune mesure")
        return
    v = sorted(valeurs)
    print(
        f"    {titre} : n={len(v):<4} médiane={statistics.median(v):6.2f}  "
        f"q1={_centile(v, 25):6.2f}  q3={_centile(v, 75):6.2f}"
    )


def bilan_par_type(mesures: list[MesureEtape]) -> None:
    for type_etape in ("bloc", "recuperation", "echauffement", "calme"):
        sous = [m for m in mesures if m.type_etape == type_etape]
        if not sous:
            continue
        print(
            f"\n  {LIBELLE_TYPE[type_etape]} (n={len(sous)}, "
            f"{sum(m.longueur_km for m in sous):.0f} km cumulés) :"
        )
        arrets = [m.arrets_par_km for m in sous if m.arrets_par_km is not None]
        ralentit = [m.ralentit_par_km for m in sous if m.ralentit_par_km is not None]
        imprimer_distribution("arrêts/km      ", arrets)
        imprimer_distribution("ralentit/km    ", ralentit)
        conc = [m.concentration for m in sous if m.concentration is not None]
        if conc:
            imprimer_distribution(f"portion libre max (n={len(conc)} avec ≥2 arrêts, part d'étape)", conc)
        else:
            print("    portion libre max : aucune étape avec ≥2 arrêts — rien à regrouper")


def rapporter_test(titre: str, paires: list[tuple[float, float]]) -> None:
    if len(paires) < 3:
        print(f"    {titre} : {len(paires)} sortie(s) comparable(s) — trop peu pour un test")
        return
    favorables, defavorables, egalites, p = test_signe(paires)
    n = favorables + defavorables
    if n == 0:
        print(f"    {titre} : {len(paires)} sortie(s), toutes à égalité — rien à trancher")
        return
    if p < SEUIL_P and favorables > defavorables:
        verdict = f"net (p={p:.3f} < {SEUIL_P:g})"
    elif p < SEUIL_P and defavorables > favorables:
        verdict = f"net, en sens INVERSE de l'attendu (p={p:.3f} < {SEUIL_P:g})"
    else:
        verdict = f"rien de net (p={p:.3f})"
    print(f"    {titre}")
    print(
        f"      {len(paires)} sortie(s) comparable(s), {egalites} égalité(s) — "
        f"{favorables}/{n} favorables — {verdict}"
    )


# --- conclusions -------------------------------------------------------------------


def conclure_q1(mesures: list[MesureEtape]) -> None:
    print("\n--- Q1 : par type d'étape ---")
    bilan_par_type(mesures)
    print("\n--- Q1 : bloc contre récupération, appariés par sortie ---")
    rapporter_test(
        "arrêts/km — bloc plus bas que récup",
        paires_par_sortie(mesures, "bloc", "recuperation", "arrets_par_km"),
    )
    rapporter_test(
        "ralentit/km — bloc plus bas que récup",
        paires_par_sortie(mesures, "bloc", "recuperation", "ralentit_par_km"),
    )
    print("\n--- Q1 : contrôle — l'échauffement, jamais noté lui non plus, bat-il aussi la récup ? ---")
    print("    (s'il bat la récup aussi nettement que le bloc, l'écart mesuré sur les blocs")
    print("     pourrait n'être que l'effet de la longueur, pas d'un vrai choix de terrain)")
    rapporter_test(
        "arrêts/km — échauffement plus bas que récup (contrôle)",
        paires_par_sortie(mesures, "echauffement", "recuperation", "arrets_par_km"),
    )
    rapporter_test(
        "ralentit/km — échauffement plus bas que récup (contrôle)",
        paires_par_sortie(mesures, "echauffement", "recuperation", "ralentit_par_km"),
    )

    blocs = [m for m in mesures if m.type_etape == "bloc"]
    recups = [m for m in mesures if m.type_etape == "recuperation"]
    autres = [m for m in mesures if m.type_etape in ("echauffement", "calme")]
    mediane_nulle = _mediane_nulle(blocs) and _mediane_nulle(recups)
    if blocs and recups and mediane_nulle:
        sans_marqueur = sum(1 for m in blocs + recups if m.arrets == 0 and m.ralentit == 0)
        porte_marqueurs = sum(1 for m in autres if m.arrets or m.ralentit)
        print(
            "\n  NOTE — effet de plancher probable : la médiane des blocs et des récupérations\n"
            f"  vaut zéro marqueur des deux côtés ({sans_marqueur}/{len(blocs) + len(recups)} étapes\n"
            "  strictement sans marqueur). L'échauffement et le retour au calme, mesurés sur\n"
            f"  les mêmes boucles, en portent ({porte_marqueurs}/{len(autres)} étapes avec au moins\n"
            "  un marqueur) : la mesure fonctionne, elle n'a simplement guère de quoi départager\n"
            "  ici — une fois hors du cœur urbain du départ, la plupart des boucles testées, dans\n"
            "  la plupart des directions, ne font plus rencontrer de feu, stop, cédez-le-passage,\n"
            "  giratoire, passage piéton ni ralentisseur, ni pour un bloc ni pour une récup."
        )


def _mediane_nulle(mesures: list[MesureEtape]) -> bool:
    """Vrai si la médiane des arrêts/km **et** des ralentit/km de ce lot vaut zéro."""
    arrets = [m.arrets_par_km for m in mesures if m.arrets_par_km is not None]
    ralentit = [m.ralentit_par_km for m in mesures if m.ralentit_par_km is not None]
    if not arrets or not ralentit:
        return False
    return statistics.median(arrets) == 0.0 and statistics.median(ralentit) == 0.0


def conclure_q2(mesures: list[MesureEtape]) -> None:
    print("\n--- Q2 : par type d'étape ---")
    bilan_par_type(mesures)
    print("\n--- Q2 : bloc contre récupération, appariés par sortie ---")
    rapporter_test(
        "arrêts/km — bloc plus bas que récup",
        paires_par_sortie(mesures, "bloc", "recuperation", "arrets_par_km"),
    )
    rapporter_test(
        "ralentit/km — bloc plus bas que récup",
        paires_par_sortie(mesures, "bloc", "recuperation", "ralentit_par_km"),
    )
    print("\n--- Q2 : contrôle — l'échauffement/le retour au calme battent-ils aussi la récup ? ---")
    print("    (même logique que le contrôle Q1 : ni l'un ni l'autre n'est choisi pour son terrain)")
    paires_ec = paires_par_sortie(mesures, "echauffement", "recuperation", "arrets_par_km")
    paires_calme = paires_par_sortie(mesures, "calme", "recuperation", "arrets_par_km")
    rapporter_test("arrêts/km — échauffement plus bas que récup (contrôle)", paires_ec)
    rapporter_test("arrêts/km — retour au calme plus bas que récup (contrôle)", paires_calme)


def imprimer_manques(manques: list[str]) -> None:
    if not manques:
        return
    print(f"\n{len(manques)} sortie(s)/étape(s) écartée(s) :")
    for ligne in manques[:15]:
        print(f"  {ligne}")
    if len(manques) > 15:
        print(f"  … et {len(manques) - 15} autre(s)")


# --- programme principal ------------------------------------------------------------


def executer(arguments: argparse.Namespace) -> int:
    config = charger(arguments.config)
    if not config.brouter.url:
        print("NON VÉRIFIÉ : aucun serveur BRouter configuré.", file=sys.stderr)
        return 2
    dossier = config.cache.dossier
    if not (dossier / "index.sqlite").is_file():
        print(f"NON VÉRIFIÉ : cache introuvable dans {dossier}.", file=sys.stderr)
        return 2
    cache = Cache(dossier)
    client_brouter = ClientBrouter(config.brouter, evitements=config.evitements)
    velo = velo_demande(config, None)
    parametres, provenance = parametres_du_velo(config, velo, chemin_calibration(config))
    ftp_w = config.cycliste.ftp_w
    print(f"Vélo « {velo.nom} », paramètres physiques : {provenance}. FTP {ftp_w:.0f} W.")

    mesures_q1: list[MesureEtape] = []
    mesures_q2: list[MesureEtape] = []

    if not arguments.sans_q1:
        print("\n" + "=" * 78)
        print("QUESTION 1 — le placement note-t-il vraiment moins bien les récups ?")
        print("(séances synthétiques posées sur des boucles générées, plusieurs directions)")
        print("=" * 78)
        mesures_q1, manques_q1 = executer_q1(
            client_brouter, config, parametres, ftp_w, azimuts=arguments.azimuts, bavard=arguments.bavard
        )
        if mesures_q1:
            conclure_q1(mesures_q1)
        else:
            print("\nNON MESURÉ : aucune séance synthétique n'a pu être placée.")
        imprimer_manques(manques_q1)

    if not arguments.sans_q2:
        print("\n" + "=" * 78)
        print("QUESTION 2 — ses propres blocs réels tombent-ils mieux que ses propres récups ?")
        print("=" * 78)
        if not config.intervals.renseigne:
            print("NON VÉRIFIÉ : aucune clé Intervals.icu configurée ([intervals] dans la config).")
        else:
            client_intervals = ClientIntervals(config.intervals.athlete_id, config.intervals.api_key)
            mesures_q2, manques_q2 = executer_q2(
                cache,
                client_brouter,
                client_intervals,
                config,
                ftp_w,
                combien=arguments.sorties,
                bavard=arguments.bavard,
            )
            if mesures_q2:
                jours = {m.sortie for m in mesures_q2}
                print(f"\n{len(jours)} sortie(s) réelle(s) mesurée(s) (sur 21 attendues au 16/09/2026).")
                conclure_q2(mesures_q2)
            else:
                print("\nNON MESURÉ : aucune sortie réelle à blocs n'a pu être mesurée.")
            imprimer_manques(manques_q2)

    if not mesures_q1 and not mesures_q2:
        print("\nNON VÉRIFIÉ : ni la question 1 ni la question 2 n'ont pu être mesurées.", file=sys.stderr)
        return 2
    return 0


def analyser(argv: list[str] | None = None) -> argparse.Namespace:
    analyseur = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    analyseur.add_argument("--config", help="fichier de configuration (défaut : celui du mainteneur)")
    analyseur.add_argument(
        "--azimuts",
        type=int,
        default=AZIMUTS_Q1,
        help=f"directions testées par séance synthétique, Q1 (défaut {AZIMUTS_Q1})",
    )
    analyseur.add_argument(
        "--sorties", type=int, default=0, help="nombre de sorties réelles traitées pour Q2, 0 = toutes"
    )
    analyseur.add_argument("--sans-q1", action="store_true", help="ne pas mesurer la question 1")
    analyseur.add_argument("--sans-q2", action="store_true", help="ne pas mesurer la question 2")
    analyseur.add_argument("--bavard", action="store_true", help="imprimer chaque sortie mesurée")
    return analyseur.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    try:
        return executer(analyser(argv))
    except ErreurUtilisateur as e:
        print(f"arrets_bloc_recup : {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
