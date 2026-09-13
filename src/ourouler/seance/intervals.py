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

- `%ftp` → part de FTP × FTP. **Exact.** Une consigne `{start, end}` donne
  une fourchette, dont `Etape.puissance_cible_w` prend le milieu. Deux
  écritures coexistent dans la nature et sont toutes deux acceptées, voir
  `SEUIL_FRACTION_FTP`.
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
import unicodedata
from dataclasses import dataclass
from datetime import date

from ourouler.activites.modele import est_sport_velo
from ourouler.connecteurs.intervals import ClientIntervals
from ourouler.seance.modele import (
    PUISSANCE_ENDURANCE_PCT_DEFAUT,
    SEUIL_RECUPERATION_PCT_DEFAUT,
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

#: Frontière entre les deux écritures d'une consigne `%ftp`.
#:
#: Le nom de l'unité dit « pourcentage », mais l'écriture ne suit pas : les
#: séances du mainteneur donnent l'entier (`80` pour 80 % de FTP, soit
#: 206-219 W pour une FTP de 258 W sur la séance du 08/02), et d'autres
#: sources donnent la fraction (`1.05` pour 105 %). Aucun champ ne distingue
#: les deux : c'est l'ordre de grandeur qui tranche, et il tranche sans
#: ambiguïté pratique. Une valeur **strictement supérieure** à ce seuil est
#: un pourcentage ; une valeur inférieure ou égale est une fraction.
#:
#: Le motif du seuil, et non d'un autre : 3 % de FTP vaudrait 8 W, ce qui
#: n'existe pas comme consigne d'entraînement, alors que 3 × FTP est un
#: sprint parfaitement plausible. Entre les deux lectures d'une même valeur
#: autour de 3, une seule est une consigne de cycliste.
#:
#: L'interprétation retenue n'est pas muette : elle est écrite dans
#: `Seance.meta["convention_pourcent_ftp"]`.
SEUIL_FRACTION_FTP = 3.0
UNITES_ZONE_PUISSANCE = ("power_zone", "powerzone")
UNITES_ZONE_FC = ("hr_zone", "hrzone", "heart_rate_zone")

#: Valeurs d'`intensity` qui désignent une récupération.
INTENSITES_RECUP = ("recovery", "rest", "recover")

#: Mots qui nomment un type dans le champ `text` d'une étape (deuxième règle
#: de la cascade de typage). Comparés sans accents et en minuscules, par
#: sous-chaîne : « recup » couvre « récupération » comme « recup ».
MOTS_ECHAUFFEMENT = ("echauffement", "warm")
MOTS_RECUPERATION = ("recuperation", "recup", "recovery")
MOTS_CALME = ("retour au calme", "cool")


def depuis_workout_doc(
    doc: dict,
    *,
    nom: str,
    jour: date,
    ftp_w: float | None,
    zones_puissance: tuple[tuple[float, float], ...] = ZONES_PUISSANCE_DEFAUT,
    puissance_endurance_pct: float = PUISSANCE_ENDURANCE_PCT_DEFAUT,
    seuil_recuperation_pct: float = SEUIL_RECUPERATION_PCT_DEFAUT,
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
        endurance_pct=_pct(puissance_endurance_pct, PUISSANCE_ENDURANCE_PCT_DEFAUT),
        seuil_pct=_pct(seuil_recuperation_pct, SEUIL_RECUPERATION_PCT_DEFAUT),
    )
    brut = doc.get("steps") if isinstance(doc, dict) else None
    lues = _aplatir(brut, etat=etat, profondeur=0, libelle="")
    etapes, sources = _reclasser(lues, etat=etat)
    etapes = _marquer_elastiques(etapes)
    duree_s = sum(e.duree_s for e in etapes)
    meta = etat.meta()
    meta["typage_source"] = sources
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
    seuil_recuperation_pct: float = SEUIL_RECUPERATION_PCT_DEFAUT,
) -> Seance | None:
    """La séance **vélo** planifiée ce jour-là, ou `None` s'il n'y en a pas.

    Le calendrier du mainteneur porte plusieurs événements par jour (une nage
    et un vélo le 08/09, par exemple) et des entrées qui ne sont pas des
    séances (notes, congés). Le filtre est donc triple : catégorie
    « WORKOUT », sport reconnu comme du vélo par `activites.modele.
    est_sport_velo` — le même filtre que l'inventaire — et `workout_doc`
    présent.

    **S'il reste plusieurs candidates, il n'en sort qu'une.** Une séance
    n'est pas la somme de deux prescriptions : coller bout à bout un home
    trainer du matin et une sortie du soir fabriquerait une séance que
    personne n'a prescrite, et le placement chercherait des couloirs pour
    elle. On retient donc la **plus longue en durée** — celle qui structure
    la journée — et les autres sont nommées dans `meta["seances_ignorees"]`.
    À durée égale, la première du calendrier l'emporte.
    """
    evenements = client.evenements(jour)
    candidates = [e for e in evenements if _est_seance_velo(e)]
    if not candidates:
        return None
    lues = [
        (
            evenement,
            depuis_workout_doc(
                evenement.get("workout_doc") or {},
                nom=str(evenement.get("name") or "séance sans nom"),
                jour=jour,
                ftp_w=ftp_w,
                zones_puissance=zones_puissance,
                puissance_endurance_pct=puissance_endurance_pct,
                seuil_recuperation_pct=seuil_recuperation_pct,
            ),
        )
        for evenement in candidates
    ]
    # `max` garde le premier des ex æquo : l'ordre du calendrier départage.
    retenue, seance = max(lues, key=lambda couple: couple[1].duree_s)
    seance.meta["source"] = "intervals"
    seance.meta["evenement_id"] = retenue.get("id")
    seance.meta["sport"] = retenue.get("type")
    if retenue.get("description") and "description" not in seance.meta:
        seance.meta["description"] = str(retenue["description"])
    ignorees = [e for e, _ in lues if e is not retenue]
    if ignorees:
        seance.meta["seances_ignorees"] = [str(e.get("name") or "sans nom") for e in ignorees]
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
        seuil_pct: float,
    ):
        self.ftp_w = ftp_w
        self.zones = zones
        self.endurance_pct = endurance_pct
        self.seuil_pct = seuil_pct
        self.seuil_w: float | None = None
        self.seuil_replie = False
        self.approximee = False
        self.fc_basses = 0  # étapes en zone de FC basse, calées sur l'endurance mesurée
        self.fc_hautes = 0  # étapes en zone de FC haute, traduites par la table des zones
        self.libres_reclassees: list[dict] = []
        self.unites_inconnues: list[str] = []
        self.sans_puissance = 0
        self.nulles = 0
        self.groupes_ignores = 0
        self.reps_bornees = 0  # groupes dont le `reps` a mordu sur `REPS_MAX`
        self.reps_tronquees = 0  # groupes dont le `reps` n'était pas entier
        self.trop_profond = 0
        self.elements_illisibles = 0
        self.ftp_manquante = 0
        self.fractions = 0  # consignes `%ftp` écrites en fraction (« 1.05 »)
        self.pourcentages = 0  # consignes `%ftp` écrites en pourcentage (« 105 »)

    def convention_pourcent_ftp(self) -> dict:
        """L'interprétation retenue pour les consignes `%ftp`, dite en clair."""
        if self.fractions and self.pourcentages:
            lecture = "mixte"
        elif self.pourcentages:
            lecture = "pourcentage"
        else:
            lecture = "fraction"
        return {
            "lecture": lecture,
            "seuil": SEUIL_FRACTION_FTP,
            "etapes_en_fraction": self.fractions,
            "etapes_en_pourcentage": self.pourcentages,
        }

    def unite_inconnue(self, unite: str) -> None:
        if unite not in self.unites_inconnues:
            self.unites_inconnues.append(unite)

    def meta(self) -> dict:
        meta: dict = {
            "puissance_approximee": self.approximee,
            "ftp_w": self.ftp_w,
            "zones_puissance": [list(z) for z in self.zones],
            "puissance_endurance_pct": self.endurance_pct,
            "seuil_recuperation_pct": self.seuil_pct,
        }
        if self.seuil_w is not None:
            meta["seuil_recuperation_w"] = round(self.seuil_w, 1)
        if self.seuil_replie:
            meta["seuil_recuperation_replie"] = True
        if self.fractions or self.pourcentages:
            meta["convention_pourcent_ftp"] = self.convention_pourcent_ftp()
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
            ("groupes_reps_bornees", self.reps_bornees),
            ("groupes_reps_tronquees", self.reps_tronquees),
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
    source_type: str  # « marqueur » | « texte » | « defaut »


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
    reps = _reps(groupe.get("reps"), etat=etat)
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
    type_, source = _type(step, herite=libelle)
    return _Lue(
        etape=Etape(
            type=type_,
            duree_s=duree,
            puissance_min_w=bas,
            puissance_max_w=haut,
            libelle=_joindre(libelle, descripteur),
        ),
        sans_consigne=sans_consigne,
        source_type=source,
    )


def _type(step: dict, *, herite: str) -> tuple[str, str]:
    """(type de l'étape, d'où il vient) — les deux premières règles de la cascade.

    1. **Marqueurs explicites** `warmup`, `cooldown`, `intensity` : la règle du
       contrat de sprint §1, inchangée. C'est ce que portent les séances
       « Vélo HIT » et « Sortie EF ».
    2. **Mots du champ `text`**, insensibles à la casse et aux accents. Les
       séances de coach (iDOSport) ne portent aucun marqueur : le type y est
       écrit en toutes lettres, « RPE cible 2, Échauffement », « RPE cible 2,
       Récupération ». Le texte de l'étape l'emporte sur celui de son groupe.

    La troisième règle — la puissance — ne peut pas s'appliquer ici : elle a
    besoin de toute la séance et de sa FTP. Elle est dans `_reclasser`, et ne
    corrige que ce que ces deux règles ont laissé en « bloc » par défaut.
    """
    intensite = str(step.get("intensity") or "").strip().casefold()
    if step.get("warmup") is True or intensite == "warmup":
        return ("echauffement", "marqueur")
    if step.get("cooldown") is True or intensite == "cooldown":
        return ("calme", "marqueur")
    if intensite in INTENSITES_RECUP:
        return ("recuperation", "marqueur")
    for texte in (str(step.get("text") or ""), herite):
        type_ = _type_du_texte(texte)
        if type_ is not None:
            return (type_, "texte")
    return ("bloc", "defaut")


def _type_du_texte(texte: str) -> str | None:
    """Le type que nomme un texte libre, ou `None`. Sans accents ni casse.

    Ordre calqué sur celui des marqueurs : échauffement, puis retour au calme,
    puis récupération.
    """
    reduit = _sans_accents(texte)
    if not reduit:
        return None
    for mots, type_ in (
        (MOTS_ECHAUFFEMENT, "echauffement"),
        (MOTS_CALME, "calme"),
        (MOTS_RECUPERATION, "recuperation"),
    ):
        if any(mot in reduit for mot in mots):
            return type_
    return None


def _sans_accents(texte: str) -> str:
    """Minuscules, sans signes diacritiques : « Récupération » → « recuperation »."""
    decompose = unicodedata.normalize("NFD", str(texte).casefold())
    return "".join(c for c in decompose if not unicodedata.combining(c))


def _reclasser(lues: list[_Lue], *, etat: _Etat) -> tuple[list[Etape], list[str]]:
    """Applique ce que la lecture étape par étape ne pouvait pas voir.

    Deux corrections, dans cet ordre, sur les seules étapes que les marqueurs
    et le texte ont laissées en « bloc » par défaut :

    1. **Aucune consigne** (`freeride`, ou rien du tout) : rien ne contraint
       le terrain, ce n'est pas un bloc.
    2. **Puissance sous le seuil de récupération** : troisième règle de la
       cascade de typage — voir `_reclasser_par_puissance`.

    Puis une dernière passe, sur les extrémités : voir
    `_recadrer_extremites`.

    Rend (les étapes, la provenance du type de chacune). La provenance va dans
    `meta["typage_source"]` : on doit toujours pouvoir dire pourquoi une étape
    est un bloc.
    """
    etapes = [lue.etape for lue in lues]
    sources = [lue.source_type for lue in lues]
    _reclasser_libres(lues, etapes, sources, etat=etat)
    _reclasser_par_puissance(etapes, sources, etat=etat)
    _recadrer_extremites(etapes, sources)
    return (etapes, sources)


def _recadrer_extremites(etapes: list[Etape], sources: list[str]) -> None:
    """Une récupération en bout de séance est en réalité un échauffement ou un calme.

    Les séances de coach nomment « Récupération » tout ce qui n'est pas un
    effort, la dernière étape comprise : « 2x20' + 4x3' » du 08/02/2026 finit
    par 20 minutes ainsi nommées. Ce n'est pas une récupération entre deux
    blocs, c'est le retour à la maison — et c'est lui qui referme la boucle,
    donc lui qui doit être élastique (cadrage du sprint 4 : « la Z2 de fin
    absorbe le reste »).

    La position l'emporte donc sur le nom, mais aux deux extrémités
    seulement : une récupération au milieu reste une récupération, quoi qu'on
    l'appelle.
    """
    if not etapes:
        return
    for indice, type_ in ((0, "echauffement"), (len(etapes) - 1, "calme")):
        if etapes[indice].type == "recuperation":
            etapes[indice] = _retyper(etapes[indice], type_)
            sources[indice] = "position"


def _reclasser_libres(
    lues: list[_Lue], etapes: list[Etape], sources: list[str], *, etat: _Etat
) -> None:
    """Une étape sans aucune consigne n'est pas un bloc : c'est du roulage libre.

    Décision du superviseur (13/09/2026). Sans puissance ni zone, rien ne
    contraint le terrain : chercher un couloir propre pour une telle étape
    n'a pas de sens, et la laisser typée « bloc » enverrait le placement
    (L4.3) travailler pour rien. Elle devient donc un échauffement si elle
    ouvre la séance, un retour au calme si elle la ferme, une récupération
    au milieu.

    Les marqueurs et le texte de la source restent prioritaires : une étape
    libre déjà nommée « Échauffement » garde son type, seul le « sinon bloc »
    par défaut est corrigé.
    """
    for indice, lue in enumerate(lues):
        if not lue.sans_consigne or sources[indice] != "defaut":
            continue
        type_ = _type_par_position(indice, len(etapes))
        etapes[indice] = _retyper(etapes[indice], type_)
        sources[indice] = "libre"
        etat.libres_reclassees.append({"indice": indice, "type": type_})


def _reclasser_par_puissance(etapes: list[Etape], sources: list[str], *, etat: _Etat) -> None:
    """Troisième règle de la cascade : sous le seuil, ce n'est pas un bloc.

    Les séances de coach ne portent ni marqueur ni texte : « 4x8 SV1 outdoor »
    du 22/04/2026 enchaîne des efforts à 98 et 145 % de FTP et des
    récupérations à 50 %, sans qu'un seul champ ne le dise. Sans cette règle,
    la séance entière serait un bloc, et le placement (L4.3) irait chercher un
    couloir propre pour un retour au calme de 40 minutes.

    Le seuil est `seuil_recuperation_pct × FTP`. Si la FTP est inconnue, on se
    rabat sur le mi-chemin entre la plus faible et la plus forte puissance
    cible de la séance, et `meta["seuil_recuperation_replie"]` le dit : c'est
    une frontière tirée de la séance elle-même, pas du cycliste.

    Si toutes les étapes tombent du même côté du seuil — une sortie
    d'endurance uniforme, par exemple — la séance n'a simplement aucun bloc.
    C'est correct : on ne cherche alors aucun couloir, et on ne fabrique pas
    un bloc artificiel pour avoir quelque chose à placer.
    """
    seuil = _seuil_recuperation(etapes, etat=etat)
    if seuil is None:
        return
    etat.seuil_w = seuil
    for indice, etape in enumerate(etapes):
        if sources[indice] != "defaut":
            continue
        cible = etape.puissance_cible_w
        if cible is None or cible >= seuil:
            continue
        type_ = _type_par_position(indice, len(etapes))
        etapes[indice] = _retyper(etape, type_)
        sources[indice] = "puissance"


def _type_par_position(indice: int, total: int) -> str:
    """Ce qu'est une étape qui n'est pas un bloc, selon l'endroit où elle tombe.

    En tête, c'est un échauffement ; en queue, un retour au calme ; entre les
    deux, une récupération. Le cas visé au milieu est celui d'une étape prise
    entre deux efforts ; une étape calme au milieu qui ne sépare pas deux
    blocs est traitée de même — une récupération ne demande rien au terrain
    (décision du 13/09), c'est donc le classement le plus prudent.
    """
    if indice == 0:
        return "echauffement"
    if indice == total - 1:
        return "calme"
    return "recuperation"


def _seuil_recuperation(etapes: list[Etape], *, etat: _Etat) -> float | None:
    """Le seuil en watts, ou `None` si la séance ne permet pas d'en fixer un."""
    if etat.ftp_w is not None:
        return etat.seuil_pct * etat.ftp_w
    cibles = [e.puissance_cible_w for e in etapes if e.puissance_cible_w is not None]
    if len(cibles) < 2 or min(cibles) == max(cibles):
        # Sans FTP et sans contraste, rien ne distingue un effort d'une
        # récupération : on ne devine pas, on laisse les types en place.
        return None
    etat.seuil_replie = True
    return (min(cibles) + max(cibles)) / 2


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
    illisible: tuple[float | None, float | None, str] | None = None
    for champ in ("power", "hr"):
        consigne = step.get(champ)
        if not isinstance(consigne, dict):
            continue
        lue = _depuis_consigne(consigne, etat=etat)
        if _bornes(consigne) is not None:
            return (*lue, False)
        # Une consigne dont l'unité est inconnue mais qui porte des bornes
        # reste une consigne : la source a voulu dire quelque chose, et on la
        # garde telle quelle. Un dictionnaire **sans aucune borne** (`power: {}`)
        # ne dit rien du tout : il ne doit pas masquer le `hr` qui suit, qui
        # lui en porte. On le garde en réserve, pour le cas où rien d'autre ne
        # vient — le descripteur qu'il produit reste utile au lecteur.
        illisible = illisible or lue
    if illisible is not None:
        return (*illisible, False)
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
        bas, haut = _en_pourcent_ftp(bas, haut, etat=etat)
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


def _en_pourcent_ftp(bas: float, haut: float, *, etat: _Etat) -> tuple[float, float]:
    """Ramène une consigne `%ftp` au pourcentage, quelle que soit son écriture.

    C'est la borne haute qui décide pour toute la fourchette : une rampe
    `{start: 0, end: 80}` est en pourcentage alors que son début vaut 0, et
    une rampe `{start: 0.5, end: 0.75}` est en fraction. Voir
    `SEUIL_FRACTION_FTP` pour le motif du seuil.
    """
    if haut > SEUIL_FRACTION_FTP:
        etat.pourcentages += 1
        return (bas, haut)
    etat.fractions += 1
    return (bas * 100.0, haut * 100.0)


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


def _reps(brut: object, *, etat: _Etat | None = None) -> int:
    """Le nombre de répétitions d'un groupe : 1 par défaut, borné à `REPS_MAX`.

    Les deux pertes se comptent, parce que le principe du lot est que rien ne
    disparaît en silence : `reps: 100000` ramené à 500 amputerait la séance de
    99 500 répétitions (absurde, donc sans conséquence pratique, mais muet),
    et `reps: 2.9` tronqué en 2 supprime un tour bien réel.
    """
    valeur = _nombre(brut)
    if valeur is None:
        return 1
    entier = int(valeur)
    if etat is not None:
        if entier != valeur:
            etat.reps_tronquees += 1
        if entier > REPS_MAX:
            etat.reps_bornees += 1
    return min(entier, REPS_MAX)


def _nombre(brut: object) -> float | None:
    """Un nombre lisible, ou `None`. Les booléens n'en sont pas."""
    if isinstance(brut, bool) or brut is None:
        return None
    try:
        valeur = float(brut)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return valeur if math.isfinite(valeur) else None


def _pct(brut: float, defaut: float) -> float:
    """Une part de FTP. Une valeur inutilisable revient au défaut plutôt que de lever."""
    valeur = _nombre(brut)
    if valeur is None or not 0.0 < valeur <= 2.0:
        return defaut
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


__all__ = [
    "MOTS_CALME",
    "MOTS_ECHAUFFEMENT",
    "MOTS_RECUPERATION",
    "PROFONDEUR_MAX",
    "REPS_MAX",
    "depuis_workout_doc",
    "seance_du_jour",
]
