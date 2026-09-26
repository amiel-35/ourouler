"""Calibrer CdA et Crr sur les sorties réelles, puis mesurer ce que ça vaut.

La chaîne, en cinq temps :

1. `services.calibrer.sorties_calibrables` choisit les sorties exploitables
   (extérieur, avec puissance, ≥ 20 km, nom sans mot de groupe, et — quand
   elle peut relire les fichiers — sans mélange de sports dans le même
   enregistrement, `motif_multisport`) ;
2. `echantillonner` découpe chaque sortie en tronçons d'environ 200 m et note,
   pour chacun, vitesse (moyenne et aux deux bouts), puissance, pente, vent de
   face et masse volumique de l'air — puis marque ceux qu'on garde et
   **pourquoi** on jette les autres ;
3. `calibrer` ajuste (CdA, Crr) aux moindres carrés sur l'écart de puissance —
   ou, quand le pneu donne le Crr, le CdA seul, que
   `chercher_cda_sur_sorties` affine ensuite sur le temps des sorties ;
4. `detecter_groupe` repère, avec le modèle obtenu, les sorties
   anormalement rapides — l'aspiration d'un peloton, que ni la pente ni le
   vent n'expliquent ;
5. `valider` rejoue les sorties **les plus récentes**, jamais vues par
   l'ajustement, et rend l'erreur de temps en mouvement ;
6. `mesurer_porte_a_porte` rejoue les sorties de validation avec les
   paramètres finaux et en tire la fourchette du porte à porte.

Le tout deux fois (`calibrer_en_deux_passes`) : la première passe sert à
trouver les sorties en groupe, la seconde à calibrer sans elles.

**Ce module ne fait que calculer** : il
reçoit des activités déjà lues, l'archive météo déjà obtenue
(`noyau.meteo.HeureArchive`), une masse et des options. Choisir et lire les
sorties — l'index du cache, le rattachement aux vélos, l'archive, la
configuration — est le cas d'usage `services.calibrer`.

Ce que le modèle ne sait pas, et qu'il faut lire avec le rapport : il ignore
les arrêts (le temps rendu est un temps **en mouvement**) et il ne connaît du
vent que ce qu'une maille d'archive de plusieurs kilomètres en dit, interpolée
à l'heure — pas la haie qui coupe le vent sur deux cents mètres. Ces écarts
vont dans le même sens : ils font paraître le cycliste plus lent que le modèle.

Troisième réserve, mesurée : **le CdA d'un vélo n'est pas le CdA d'une
position, c'est la moyenne des positions réellement tenues sur ce vélo.** Sur
les deux vélos d'un cycliste de référence, la calibration
trouve le même CdA à 0,7 % près — dans le bruit des incertitudes (±2 % et
±2,5 %) — alors qu'un chrono devrait être nettement plus aérodynamique. Tout
l'écart entre les deux (16 W à 25 km/h, 26 W à 40 km/h) est passé dans le Crr,
plus bas de 21 % sur le chrono.

Ce n'est pas un artefact de régression. Ce cycliste roule une partie de ses
sorties de chrono **hors prolongateur**, en particulier en Z2 ; le chrono porte
de meilleures roues et des pneus plus larges, donc son Crr est réellement plus
bas ; et les gains marginaux (tenue, casque, chaussettes) ne sont pas mis à
toutes les sorties. Le CdA calibré décrit donc un mélange de positions et
d'équipements — ce qui est **exactement ce qu'il faut** pour prédire des
sorties ordinaires, et faux pour prédire un effort tenu au prolongateur de
bout en bout.

Conséquence à connaître : la sensibilité au vent de face est elle aussi une
moyenne. Le gain du chrono ne grandit que de 0,6 W entre l'absence de vent et
20 km/h de vent de face à 30 km/h, là où un vrai gain aérodynamique grandirait
franchement. Pour un effort réellement en position, le modèle sous-estime.

Le vent d'archive est donné à 10 m du sol ; il est **ramené à hauteur de
cycliste** avant d'entrer dans le modèle (`modele.vent_au_cycliste`). Sans
cela, le régresseur aérodynamique est construit sur un vent systématiquement
trop fort, et l'erreur sur un régresseur tire son coefficient vers zéro : le
CdA descendait en butée basse et le Crr absorbait le reste.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date

import numpy as np

from ourouler.noyau.activite import Activite, est_sport_velo
from ourouler.noyau.erreurs import ErreurUtilisateur
from ourouler.noyau.meteo import HeureArchive
from ourouler.noyau.profil import Velo
from ourouler.physique.echantillonnage import (
    Echantillon,
    echantillonner,
)
from ourouler.physique.groupe import (
    PART_DISTANCE_GROUPE,
    detecter_groupe,
)
from ourouler.physique.modele import (
    RHO_DEFAUT,
    Parametres,
    puissance_requise,
)
from ourouler.physique.validation import (
    Validation,
    simuler_sortie,
    valider,
)

#: Bornes de l'ajustement.
CDA_MIN, CDA_MAX = 0.18, 0.60
CRR_MIN, CRR_MAX = 0.002, 0.012

#: Masse d'un vélo dont la configuration ne dit rien, en kilogrammes.
MASSE_VELO_DEFAUT_KG = 9.0

#: Nombre minimal d'échantillons pour ajuster deux paramètres.
ECHANTILLONS_MINIMUM = 3

#: Distance minimale d'une sortie calibrable, en mètres.
DISTANCE_MINIMALE_M = 20_000.0

#: Les deux allures auxquelles le rapport chiffre la résistance totale — la
#: somme des forces, bien contrainte par les données même quand CdA et Crr
#: pris séparément le sont mal (décision Q9, `docs/journal/questions/questions_mainteneur.md`) :
#: l'allure d'entraînement et l'allure de contre-la-montre. Deux points valent mieux qu'un : c'est leur
#: **écart** qui dit la part aérodynamique, sans qu'on ait à prétendre séparer
#: CdA de Crr.
V_REFERENCES_KMH = (27.0, 35.0)

#: Motif d'exclusion d'un fichier qui ne contient pas *que* du vélo : un FIT de
#: triathlon, un enregistrement coupé en plusieurs sessions, un fichier dont le
#: sport déclaré n'est pas cycliste (décision Q10).
MOTIF_MULTISPORT = "multisport"


# --- ajustement ---------------------------------------------------------------


@dataclass(frozen=True)
class Incertitudes:
    """Écarts-types des deux paramètres ajustés. `None` quand ils ne se calculent pas.

    Regroupées plutôt que posées à plat sur `Ajustement` : un attribut
    `cda_incertitude` à côté de `cda_m2` donne deux nombres « CdA » sur le
    même objet, et le premier lecteur venu — humain ou test — prend l'un pour
    l'autre.
    """

    cda: float | None = None
    crr: float | None = None


@dataclass
class Ajustement:
    """Le couple (CdA, Crr) qui explique le mieux les échantillons, et ce qu'il vaut."""

    cda_m2: float
    crr: float
    masse_totale_kg: float
    n_echantillons: int
    rmse_w: float
    mae_w: float
    incertitudes: Incertitudes = field(default_factory=Incertitudes)
    rho_moyen: float = RHO_DEFAUT
    bornes_atteintes: tuple[str, ...] = ()
    avertissements: tuple[str, ...] = ()
    #: Vrai quand le Crr n'a pas été cherché mais **reçu** (pneu déclaré ou
    #: valeur de configuration) : seul le CdA est alors ajusté, et
    #: `incertitudes.crr` vaut `None`.
    crr_fixe: bool = False

    def resistance_a(self, v_kmh: float) -> tuple[float, float]:
        """(force en newtons, puissance au pédalier en watts) sur le plat sans vent.

        C'est **la** grandeur que ces données mesurent. CdA et Crr peuvent se
        compenser l'un l'autre — un CdA trop bas avec un Crr trop haut donne la
        même puissance à 27 km/h — mais cette somme-là, non : elle est
        directement ce que le capteur a vu, à l'allure où il l'a vu.
        """
        p = self.parametres()
        v = v_kmh / 3.6
        puissance = puissance_requise(v, 0.0, 0.0, p)
        return (puissance * p.rendement / v, puissance)

    @property
    def resistances(self) -> list[tuple[float, float, float]]:
        """(vitesse km/h, force N, puissance W) à chacune des `V_REFERENCES_KMH`."""
        return [(v, *self.resistance_a(v)) for v in V_REFERENCES_KMH]

    def parametres(self, *, rho: float | None = None) -> Parametres:
        """Les `Parametres` correspondants, avec la masse volumique moyenne des échantillons."""
        return Parametres(
            masse_totale_kg=self.masse_totale_kg,
            cda_m2=self.cda_m2,
            crr=self.crr,
            rho=rho if rho is not None else self.rho_moyen,
        )


def calibrer(
    echantillons: Sequence[Echantillon],
    *,
    masse_totale_kg: float,
    cda_init: float = 0.32,
    crr_init: float = 0.005,
    crr_fixe: float | None = None,
) -> Ajustement:
    """Moindres carrés sur (CdA, Crr), bornés, à partir des échantillons retenus.

    **`crr_fixe` donné** : le Crr n'est pas cherché, seul le CdA l'est
    — moindres carrés à une inconnue sur la même équation, écrêtés à
    `[CDA_MIN, CDA_MAX]`. C'est la méthode qui converge : laissés libres
    ensemble, CdA et Crr se compensent l'un l'autre et la solution dérive (voir
    `calibrer_en_deux_passes`).

    **Le modèle est linéaire en CdA et en Crr** : à vitesse, pente et vent
    donnés, la puissance vaut `a·CdA + b·Crr + c`, où a, b et c ne dépendent
    d'aucun des deux. Le contrat de sprint prévoyait une grille grossière puis
    un affinage ; la solution exacte existe, on la prend — et les coefficients
    a, b, c sont obtenus en appelant `puissance_requise` avec des paramètres
    unitaires, de sorte que la calibration ne puisse pas diverger de la
    physique du modèle. Écart au contrat assumé et signalé.

    Hors des bornes, le minimum d'une forme quadratique convexe sur un pavé
    est sur le bord : on résout alors les quatre arêtes et on garde la
    meilleure. `cda_init` et `crr_init` ne servent donc qu'à nommer un point
    de départ dans le rapport (ils n'influent pas sur le résultat) et à
    répondre quand le problème est dégénéré.

    **L'incertitude rendue est optimiste** : elle suppose des résidus
    indépendants, alors que deux tronçons de 200 m voisins se ressemblent.
    Elle dit l'ordre de grandeur de ce que les données contraignent, pas
    l'erreur vraie.
    """
    retenus = [e for e in echantillons if e.retenu]
    if len(retenus) < ECHANTILLONS_MINIMUM:
        raise ErreurUtilisateur(
            f"calibration : {len(retenus)} échantillon(s) retenu(s), "
            f"au moins {ECHANTILLONS_MINIMUM} sont nécessaires pour ajuster CdA et Crr"
        )
    if not math.isfinite(masse_totale_kg) or masse_totale_kg <= 0:
        raise ErreurUtilisateur(
            f"calibration : masse totale {masse_totale_kg!r} — une masse positive est attendue"
        )

    a, b, c, y = _matrices(retenus, masse_totale_kg)
    if crr_fixe is not None:
        return _calibrer_cda_seul(retenus, a, b, c, y, masse_totale_kg=masse_totale_kg, crr=crr_fixe)
    matrice = np.column_stack((a, b))
    reste = y - c
    avertissements: list[str] = []

    solution, rang = _moindres_carres(matrice, reste)
    if rang < 2:
        avertissements.append(
            "les échantillons ne séparent pas CdA de Crr (trop peu de variété de "
            "vitesse ou de pente) : la solution est celle de norme minimale"
        )
        solution = np.array([cda_init, crr_init], dtype=float)
    cda, crr, bornes = _borner(matrice, reste, solution)
    if bornes:
        avertissements.append(
            "une borne est atteinte : CdA et Crr ne sont plus séparés par ces "
            "données, seule leur résistance combinée à l'allure courante est mesurée"
        )

    residus = matrice @ np.array([cda, crr]) - reste
    n = len(retenus)
    rmse = float(np.sqrt(np.mean(residus**2)))
    mae = float(np.mean(np.abs(residus)))
    incertitudes = _incertitudes(matrice, residus, n)
    return Ajustement(
        cda_m2=float(cda),
        crr=float(crr),
        masse_totale_kg=float(masse_totale_kg),
        n_echantillons=n,
        rmse_w=rmse,
        mae_w=mae,
        incertitudes=Incertitudes(*incertitudes),
        rho_moyen=float(np.mean([e.rho for e in retenus])),
        bornes_atteintes=bornes,
        avertissements=tuple(avertissements),
    )


def _calibrer_cda_seul(
    retenus: Sequence[Echantillon],
    a: np.ndarray,
    b: np.ndarray,
    c: np.ndarray,
    y: np.ndarray,
    *,
    masse_totale_kg: float,
    crr: float,
) -> Ajustement:
    """Le CdA qui explique le mieux les échantillons, le Crr étant donné.

    `P = a·CdA + b·Crr + c` ; à Crr connu, `a·CdA = y − c − b·Crr` se résout
    exactement aux moindres carrés, `CdA = a·r / a·a`.
    """
    if not math.isfinite(crr) or not CRR_MIN <= crr <= CRR_MAX:
        raise ErreurUtilisateur(
            f"calibration : Crr fixé {crr!r} hors de [{CRR_MIN}, {CRR_MAX}]"
        )
    reste = y - c - b * crr
    denominateur = float(a @ a)
    if denominateur <= 0:
        raise ErreurUtilisateur(
            "calibration : les échantillons ne portent aucune traînée aérodynamique, "
            "le CdA ne se mesure pas"
        )
    libre = float(a @ reste) / denominateur
    cda = min(max(libre, CDA_MIN), CDA_MAX)
    bornes: tuple[str, ...] = ()
    avertissements: tuple[str, ...] = ()
    if cda != libre:
        bornes = (f"CdA = {cda:.2f}",)
        avertissements = (
            "une borne est atteinte : à ce Crr, aucun CdA plausible n'explique les "
            "données — le pneu déclaré est peut-être le mauvais",
        )
    residus = a * cda - reste
    n = len(retenus)
    incertitude = None
    if n > 1:
        incertitude = math.sqrt(float(residus @ residus) / (n - 1) / denominateur)
    return Ajustement(
        cda_m2=float(cda),
        crr=float(crr),
        masse_totale_kg=float(masse_totale_kg),
        n_echantillons=n,
        rmse_w=float(np.sqrt(np.mean(residus**2))),
        mae_w=float(np.mean(np.abs(residus))),
        incertitudes=Incertitudes(cda=incertitude, crr=None),
        rho_moyen=float(np.mean([e.rho for e in retenus])),
        bornes_atteintes=bornes,
        avertissements=avertissements,
        crr_fixe=True,
    )


def _matrices(
    retenus: Sequence[Echantillon], masse_totale_kg: float
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Les colonnes (a, b, c) du modèle linéaire et le vecteur des puissances mesurées.

    a, b et c sortent de `puissance_requise` elle-même, avec des paramètres
    unitaires : `a = P(CdA=1, Crr=0) − P(0, 0)`, `b = P(0, Crr=1) − P(0, 0)`,
    `c = P(0, 0)` (la part gravité + rendement). Aucune formule n'est donc
    recopiée ici.

    À `c` s'ajoute la **variation d'énergie cinétique** du tronçon,
    `m · (v_fin² − v_début²) / (2 · Δt)`, elle aussi connue sans CdA ni Crr.
    Sans elle, la calibration ne pouvait garder que des tronçons à vitesse
    constante ; avec elle, un tronçon où le cycliste accélère de 1 m/s dit
    autant qu'un autre, et il y en a des milliers au lieu de quelques
    centaines.
    """
    a = np.empty(len(retenus))
    b = np.empty(len(retenus))
    c = np.empty(len(retenus))
    y = np.empty(len(retenus))
    for i, e in enumerate(retenus):
        base = Parametres(masse_totale_kg=masse_totale_kg, cda_m2=0.0, crr=0.0, rho=e.rho)
        seul_cda = Parametres(masse_totale_kg=masse_totale_kg, cda_m2=1.0, crr=0.0, rho=e.rho)
        seul_crr = Parametres(masse_totale_kg=masse_totale_kg, cda_m2=0.0, crr=1.0, rho=e.rho)
        # `sans_rien` sert de référence aux deux colonnes : le terme cinétique
        # ne doit surtout pas entrer dans `a` et `b`, qui sont des **écarts**
        # à cette référence. Il ne rejoint `c` qu'ensuite.
        sans_rien = puissance_requise(e.v_ms, e.pente, e.vent_face_ms, base)
        a[i] = puissance_requise(e.v_ms, e.pente, e.vent_face_ms, seul_cda) - sans_rien
        b[i] = puissance_requise(e.v_ms, e.pente, e.vent_face_ms, seul_crr) - sans_rien
        c[i] = sans_rien + e.puissance_cinetique_w(masse_totale_kg, base.rendement)
        y[i] = e.puissance_w
    return a, b, c, y


def _moindres_carres(matrice: np.ndarray, reste: np.ndarray) -> tuple[np.ndarray, int]:
    solution, _, rang, _ = np.linalg.lstsq(matrice, reste, rcond=None)
    return solution, int(rang)


def _borner(
    matrice: np.ndarray, reste: np.ndarray, solution: np.ndarray
) -> tuple[float, float, tuple[str, ...]]:
    """Ramène la solution dans le pavé des bornes, en minimisant vraiment l'écart.

    Écrêter les deux coordonnées séparément ne donne pas le minimum du pavé :
    si CdA sort par le haut, le Crr optimal **à CdA borné** n'est plus celui
    de la solution libre. On résout donc chaque arête à une inconnue et on
    garde la meilleure des candidates.
    """
    cda, crr = float(solution[0]), float(solution[1])
    if CDA_MIN <= cda <= CDA_MAX and CRR_MIN <= crr <= CRR_MAX:
        return (cda, crr, ())

    candidates: list[tuple[float, float]] = []
    for valeur in (CDA_MIN, CDA_MAX):
        candidates.append((valeur, _arete(matrice, reste, fixe=0, valeur=valeur)))
    for valeur in (CRR_MIN, CRR_MAX):
        candidates.append((_arete(matrice, reste, fixe=1, valeur=valeur), valeur))
    candidates += [
        (x, z) for x in (CDA_MIN, CDA_MAX) for z in (CRR_MIN, CRR_MAX)
    ]
    valides = [
        (x, z)
        for x, z in candidates
        if CDA_MIN - 1e-12 <= x <= CDA_MAX + 1e-12 and CRR_MIN - 1e-12 <= z <= CRR_MAX + 1e-12
    ]
    meilleure = min(
        valides, key=lambda xz: float(np.sum((matrice @ np.array(xz) - reste) ** 2))
    )
    cda, crr = meilleure
    bornes = []
    if math.isclose(cda, CDA_MIN) or math.isclose(cda, CDA_MAX):
        bornes.append(f"CdA = {cda:.2f}")
    if math.isclose(crr, CRR_MIN) or math.isclose(crr, CRR_MAX):
        bornes.append(f"Crr = {crr:.4f}")
    return (cda, crr, tuple(bornes))


def _arete(matrice: np.ndarray, reste: np.ndarray, *, fixe: int, valeur: float) -> float:
    """Optimum de l'inconnue restante quand l'autre est fixée à `valeur`, écrêté à ses bornes."""
    libre = 1 - fixe
    colonne = matrice[:, libre]
    cible = reste - matrice[:, fixe] * valeur
    denominateur = float(colonne @ colonne)
    if denominateur <= 0:
        return CRR_MIN if libre == 1 else CDA_MIN
    x = float((colonne @ cible) / denominateur)
    mini, maxi = (CDA_MIN, CDA_MAX) if libre == 0 else (CRR_MIN, CRR_MAX)
    return min(max(x, mini), maxi)


def _incertitudes(
    matrice: np.ndarray, residus: np.ndarray, n: int
) -> tuple[float | None, float | None]:
    """Écarts-types des deux paramètres, `σ²·(AᵀA)⁻¹`. `None` si la matrice est singulière."""
    if n <= 2:
        return (None, None)
    variance = float(residus @ residus) / (n - 2)
    try:
        covariance = np.linalg.inv(matrice.T @ matrice) * variance
    except np.linalg.LinAlgError:
        return (None, None)
    diagonale = np.diag(covariance)
    if np.any(diagonale < 0):
        return (None, None)
    racines = np.sqrt(diagonale)
    return (float(racines[0]), float(racines[1]))


# --- CdA cherché sur le temps des sorties --------------------------------------

#: Précision de la recherche du CdA sur le temps des sorties, en m². En deçà,
#: le minimum est plat (mesuré : 0,30 à 0,36 donnent presque la même erreur
#: sur un vélo de route de référence) — chercher plus fin ne dirait
#: rien de plus.
PRECISION_CDA_M2 = 0.002


def erreur_temps(sorties: Sequence[SortieCalibration], p: Parametres) -> float | None:
    """Erreur relative absolue moyenne du temps en mouvement simulé, sur ces sorties."""
    return valider([(s.activite, s.vent) for s in sorties], p).mae


def chercher_cda_sur_sorties(
    sorties: Sequence[SortieCalibration],
    *,
    masse_totale_kg: float,
    crr: float,
    rho: float = RHO_DEFAUT,
    precision: float = PRECISION_CDA_M2,
) -> float:
    """Le CdA qui minimise l'erreur de temps en mouvement sur ces sorties, Crr fixé.

    **Pourquoi pas les moindres carrés des échantillons.** Mesuré sur un vélo
    de route de référence, Crr fixé à 0,006 : les
    moindres carrés à une inconnue sur les tronçons filtrés donnent CdA 0,299
    et une erreur de validation de 6,5 % ; minimiser l'erreur de temps sur
    les sorties complètes d'apprentissage donne 0,33 et 4,6 %. Les tronçons
    retenus sont des tronçons calmes (pente ≤ 8 %, sans arrêt ni relance
    brutale) : ils ne portent pas le reste de la sortie, que le temps, lui,
    porte entièrement. Et c'est le temps qu'on prédit.

    Recherche par section dorée sur `[CDA_MIN, CDA_MAX]` : l'erreur en
    fonction du CdA est en cuvette (plus haut, trop lent ; plus bas, trop
    rapide), une dizaine de rejeux suffisent. Seules des sorties **vues par
    l'apprentissage** entrent ici — la validation reste intacte.
    """
    if not sorties:
        raise ErreurUtilisateur("calibration : aucune sortie pour chercher le CdA")

    def cout(cda: float) -> float:
        mae = erreur_temps(
            sorties, Parametres(masse_totale_kg=masse_totale_kg, cda_m2=cda, crr=crr, rho=rho)
        )
        return math.inf if mae is None else mae

    or_ = (math.sqrt(5.0) - 1.0) / 2.0
    a, b = CDA_MIN, CDA_MAX
    c, d = b - or_ * (b - a), a + or_ * (b - a)
    fc, fd = cout(c), cout(d)
    while b - a > precision:
        if fc <= fd:
            b, d, fd = d, c, fc
            c = b - or_ * (b - a)
            fc = cout(c)
        else:
            a, c, fc = c, d, fd
            d = a + or_ * (b - a)
            fd = cout(d)
    return (a + b) / 2.0


def ajuster_sur_sorties(
    ajustement: Ajustement,
    sorties: Sequence[SortieCalibration],
    echantillons: Sequence[Echantillon],
) -> Ajustement:
    """`ajustement` (Crr fixé), son CdA remplacé par celui qui prédit le mieux le temps.

    Les résidus de puissance (`rmse_w`, `mae_w`) sont recalculés au nouveau
    CdA sur les mêmes échantillons, pour que le rapport ne cite pas ceux d'un
    autre point. L'incertitude des moindres carrés ne s'applique plus : elle
    vaut `None`.
    """
    cda = chercher_cda_sur_sorties(
        sorties,
        masse_totale_kg=ajustement.masse_totale_kg,
        crr=ajustement.crr,
        rho=ajustement.rho_moyen,
    )
    retenus = [e for e in echantillons if e.retenu]
    a, b, c, y = _matrices(retenus, ajustement.masse_totale_kg)
    residus = a * cda + b * ajustement.crr + c - y
    bornes: tuple[str, ...] = ()
    avertissements: tuple[str, ...] = ()
    if math.isclose(cda, CDA_MIN, abs_tol=PRECISION_CDA_M2) or math.isclose(
        cda, CDA_MAX, abs_tol=PRECISION_CDA_M2
    ):
        bornes = (f"CdA = {cda:.2f}",)
        avertissements = (
            "une borne est atteinte : à ce Crr, aucun CdA plausible n'explique le temps "
            "des sorties — le pneu déclaré est peut-être le mauvais",
        )
    return Ajustement(
        cda_m2=float(cda),
        crr=ajustement.crr,
        masse_totale_kg=ajustement.masse_totale_kg,
        n_echantillons=len(retenus),
        rmse_w=float(np.sqrt(np.mean(residus**2))) if len(retenus) else 0.0,
        mae_w=float(np.mean(np.abs(residus))) if len(retenus) else 0.0,
        incertitudes=Incertitudes(cda=None, crr=None),
        rho_moyen=ajustement.rho_moyen,
        bornes_atteintes=bornes,
        avertissements=avertissements,
        crr_fixe=True,
    )


# --- la fourchette du porte à porte -------------------------------------------


#: Les centiles du ratio réel/simulé qui bornent la fourchette affichée : la
#: moitié centrale des sorties — assez resserrée pour rester utile, assez
#: large pour ne pas mentir.
CENTILES_PORTE_A_PORTE = (25, 50, 75)

#: En dessous de ce nombre de sorties de validation roulées seul, les
#: centiles ne disent rien de stable : le vélo garde la fourchette par
#: défaut. Convention, pas mesure — un quartile sur sept valeurs, c'est déjà
#: deux sorties.
SORTIES_MIN_FOURCHETTE = 8

#: Part de signal de groupe au-delà de laquelle une sortie d'apprentissage ne
#: sert pas à chercher le CdA sur le temps — défaut de
#: `config.ParametresCalibration.part_groupe_max`, voir sa justification.
PART_GROUPE_MAX_APPRENTISSAGE = 0.30

#: En dessous de ce nombre de sorties d'apprentissage sous
#: `part_groupe_max`, la recherche du CdA retombe sur toutes les sorties non
#: écartées au seuil de 50 %, et le rapport le dit. Convention.
SORTIES_MIN_SOLO = 8


@dataclass(frozen=True)
class RatioSortie:
    """Une sortie rejouée avec les paramètres finaux : ses trois temps et sa part de groupe."""

    jour: str
    nom: str
    #: Du premier au dernier point de l'enregistrement, arrêts compris : le
    #: porte à porte réel.
    temps_ecoule_s: float
    temps_mouvement_s: float
    temps_simule_s: float
    #: Part de la distance anormalement rapide (`detecter_groupe`), avant
    #: tout seuil.
    part_groupe: float

    @property
    def ratio(self) -> float:
        """Temps écoulé réel / temps simulé en mouvement : ce que la fourchette mesure."""
        return self.temps_ecoule_s / self.temps_simule_s

    @property
    def ratio_mouvement(self) -> float:
        """Temps en mouvement réel / temps simulé : l'erreur du modèle seul, arrêts exclus."""
        return self.temps_mouvement_s / self.temps_simule_s


def _centiles(valeurs: Sequence[float]) -> tuple[float, float, float]:
    """25ᵉ, 50ᵉ et 75ᵉ centiles, interpolés entre valeurs (méthode « inclusive »)."""
    q1, q2, q3 = statistics.quantiles(valeurs, n=4, method="inclusive")
    return (q1, q2, q3)


@dataclass
class MesurePorteAPorte:
    """Le ratio réel/simulé sortie par sortie, et la fourchette qu'on en tire.

    Le filtre de groupe se fait **ici, une fois**, sur la part brute rendue
    par `detecter_groupe` avec les paramètres finaux — jamais à la main : un
    réglage qui demande au cycliste d'y passer du temps ne sera pas tenu.
    """

    sorties: list[RatioSortie] = field(default_factory=list)
    seuil_groupe: float = PART_DISTANCE_GROUPE

    @property
    def retenues(self) -> list[RatioSortie]:
        """Les sorties roulées seul : part de groupe **strictement** sous le seuil."""
        return [s for s in self.sorties if s.part_groupe < self.seuil_groupe]

    @property
    def n(self) -> int:
        return len(self.retenues)

    @property
    def centiles(self) -> tuple[float, float, float] | None:
        """(25ᵉ, 50ᵉ, 75ᵉ) du ratio écoulé/simulé, ou `None` s'il y a trop peu de sorties."""
        if self.n < SORTIES_MIN_FOURCHETTE:
            return None
        return _centiles([s.ratio for s in self.retenues])

    @property
    def centiles_mouvement(self) -> tuple[float, float, float] | None:
        """Les mêmes centiles, sur le temps **en mouvement** : l'erreur du modèle seul."""
        if self.n < SORTIES_MIN_FOURCHETTE:
            return None
        return _centiles([s.ratio_mouvement for s in self.retenues])


def mesurer_porte_a_porte(
    sorties: Sequence[SortieCalibration],
    p: Parametres,
    *,
    ftp_w: float = 250.0,
    vitesse_min_kmh: float = 8.0,
    seuil_groupe: float = PART_DISTANCE_GROUPE,
) -> MesurePorteAPorte:
    """Rejoue chaque sortie avec `p` et mesure temps écoulé réel / temps simulé.

    `calibrer_en_deux_passes` ne lui passe que les sorties de **validation**,
    jamais vues par l'ajustement : mesurée sur les sorties apprises, la
    fourchette hériterait de l'ajustement du CdA sur elles et sous-prédirait
    le porte à porte d'une sortie neuve (médiane 1,054 en échantillon contre
    1,072 en validation sur un vélo de route de référence). Le ratio dit ce
    qu'une sortie nouvelle coûte en plus du temps simulé : arrêts, relances, et
    l'erreur propre du modèle.

    Le temps de référence est le temps **écoulé** (dernier point − premier) :
    c'est lui que la fourchette doit prédire, porte à porte. Le
    `temps_reel_s` de la validation est un temps **en mouvement** ; ce
    ratio-là est gardé à côté (`ratio_mouvement`), pour
    qu'on puisse comparer.
    """
    mesure = MesurePorteAPorte(seuil_groupe=seuil_groupe)
    for s in sorties:
        rejeu = simuler_sortie(s.activite, s.vent, p)
        if rejeu is None:
            continue
        simulation, mouvement = rejeu
        ecoule = float(s.activite.duree_s or 0.0)
        if simulation.temps_s <= 0 or ecoule <= 0:
            continue
        _, part = detecter_groupe(
            s.activite, p, s.vent, ftp_w=ftp_w, vitesse_min_kmh=vitesse_min_kmh
        )
        mesure.sorties.append(
            RatioSortie(
                jour=s.jour.isoformat() if s.jour else "",
                nom=s.nom,
                temps_ecoule_s=ecoule,
                temps_mouvement_s=mouvement,
                temps_simule_s=simulation.temps_s,
                part_groupe=part,
            )
        )
    return mesure


# --- masse et fichiers multisport -------------------------------------------


def masse_totale(masse_cycliste_kg: float, velo: Velo) -> float:
    """Cycliste + vélo. Un vélo sans masse déclarée pèse `MASSE_VELO_DEFAUT_KG`.

    Une masse approximative par vélo suffit : 1 kg sur 100 kg fait 1 % en
    montée et rien sur le plat. La masse du cycliste est reçue : c'est
    `services.calibrer.masse_totale_kg` qui la lit dans le profil.
    """
    return masse_cycliste_kg + (
        velo.masse_kg if velo.masse_kg is not None else MASSE_VELO_DEFAUT_KG
    )


def motif_multisport(activite: Activite | None) -> str | None:
    """`MOTIF_MULTISPORT` si ce fichier ne contient pas *que* du vélo, sinon `None`.

    Trois signes, et un seul suffit :

    - `meta["sessions"]` vaut plus de 1 — le lecteur FIT l'y met quand le
      fichier porte plusieurs trames `session` ;
    - un avertissement de lecture parle de sessions multiples (même cause, vue
      de l'autre côté : un fichier relu par une version qui n'écrivait pas
      encore la clé le dit quand même) ;
    - le sport **du fichier** n'est pas cycliste.

    Ce dernier point ne fait pas doublon avec `services.calibrer.motif_exclusion`,
    qui regarde le
    sport de l'**index** : celui-ci vient d'Intervals, qui annonce « Ride »
    pour le segment vélo d'un triathlon alors que le FIT d'origine, partagé
    entre les trois segments, contient aussi la natation et la course. Relu
    entièrement, un tel fichier donne une « sortie » qui commence à 3 km/h dans
    l'eau : la calibrer reviendrait à demander au modèle d'expliquer une
    brasse par de la traînée aérodynamique.

    Une activité absente (fichier illisible) rend `None` : on ne sait pas,
    donc on ne juge pas — la commande la signalera pour ce qu'elle est.
    """
    if activite is None:
        return None
    sessions = activite.meta.get("sessions")
    if isinstance(sessions, (int, float)) and sessions > 1:
        return MOTIF_MULTISPORT
    for avertissement in activite.avertissements:
        if "session" in str(avertissement).casefold():
            return MOTIF_MULTISPORT
    if not est_sport_velo(activite.sport):
        return MOTIF_MULTISPORT
    return None


# --- les deux passes ----------------------------------------------------------


@dataclass
class SortieCalibration:
    """Une sortie prête à calibrer : son enregistrement et l'archive météo du jour."""

    activite: Activite
    vent: list[HeureArchive] = field(default_factory=list)
    identifiant: str = ""

    @property
    def jour(self) -> date | None:
        return self.activite.debut.date() if self.activite.debut else None

    @property
    def nom(self) -> str:
        return str(self.activite.meta.get("nom") or self.activite.fichier or self.identifiant)


@dataclass
class RapportCalibration:
    """Tout ce qu'une calibration a trouvé, mesuré et écarté — de quoi la juger."""

    velo: str
    ajustement: Ajustement
    validation: Validation
    passe1: Ajustement
    n_apprentissage: int
    n_validation: int
    groupes: list[tuple[str, float]] = field(default_factory=list)
    """Sorties d'apprentissage écartées au résidu : (nom, part de la distance
    anormalement rapide)."""
    groupes_en_validation: list[tuple[str, float]] = field(default_factory=list)
    """Sorties de **test** que le même critère désigne. Elles restent dans la
    validation — ce sont de vraies sorties — mais il faut savoir qu'elles y
    sont quand on lit l'erreur."""
    echantillons: int = 0
    echantillons_retenus: int = 0
    motifs: dict[str, int] = field(default_factory=dict)
    echantillons_sans_vent: int = 0
    porte_a_porte: MesurePorteAPorte = field(default_factory=MesurePorteAPorte)
    """Le ratio temps écoulé réel / temps simulé sur les sorties de
    validation, rejouées avec les paramètres finaux."""
    n_solo: int = 0
    """À Crr fixé : combien de sorties d'apprentissage ont servi à chercher le
    CdA sur le temps (sous `part_groupe_max`). 0 en calibration libre."""
    part_groupe_max: float = PART_GROUPE_MAX_APPRENTISSAGE
    repli_solo: str = ""
    """Non vide quand trop peu de sorties passaient `part_groupe_max` : dit
    sur quoi le CdA a été cherché à la place."""


def sorties_minimum(part_validation: float) -> int:
    """Le moins de sorties calibrables avec lequel une calibration a un sens.

    Dérivé, pas choisi : il faut `SORTIES_MIN_SOLO` sorties d'**apprentissage**
    pour que le CdA ne soit pas cherché sur une poignée de sorties (en deçà,
    `calibrer_en_deux_passes` le dit par `repli_solo`), **plus** la part que
    `partager` met de côté pour la validation. 10 avec la part par défaut
    (0,25). La fourchette du porte à porte, elle, demande davantage (au moins
    `SORTIES_MIN_FOURCHETTE` sorties de validation roulées seul) : en deçà,
    la convention reste en vigueur, et le rapport le dit.
    """
    n = SORTIES_MIN_SOLO
    while True:
        n_test = max(1, min(n - 1, round(n * part_validation)))
        if n - n_test >= SORTIES_MIN_SOLO:
            return n
        n += 1


def partager(
    sorties: Sequence[SortieCalibration], part_validation: float
) -> tuple[list[SortieCalibration], list[SortieCalibration]]:
    """(apprentissage, validation) : les plus récentes en validation.

    Partager par date et non au hasard est le seul partage honnête ici : un
    tirage aléatoire mettrait dans le test des sorties voisines, faites le même
    mois avec le même matériel, et flatterait le modèle.
    """
    ordonnees = sorted(sorties, key=lambda s: (s.jour or date.min, s.nom))
    if len(ordonnees) < 2:
        return (list(ordonnees), [])
    n_test = max(1, min(len(ordonnees) - 1, round(len(ordonnees) * part_validation)))
    coupe = len(ordonnees) - n_test
    return (ordonnees[:coupe], ordonnees[coupe:])


def calibrer_en_deux_passes(
    sorties: Sequence[SortieCalibration],
    *,
    velo: str,
    masse_totale_kg: float,
    part_validation: float = 0.25,
    ftp_w: float = 250.0,
    vitesse_min_kmh: float = 8.0,
    crr_fixe: float | None = None,
    part_groupe_max: float = PART_GROUPE_MAX_APPRENTISSAGE,
) -> RapportCalibration:
    """Calibre, repère les sorties en groupe au résidu, recalibre sans elles, valide.

    Une seule itération : calibrer d'abord sur les sorties sûres, puis
    utiliser le modèle obtenu pour repérer les autres et les écarter, une
    fois.

    `crr_fixe` : le Crr connu par le pneu ou la configuration. Les
    deux passes ne cherchent alors que le CdA. Sans lui, l'ajustement libre à
    deux paramètres — qui ne sépare pas CdA et Crr sur des données réelles
    (0,0106 de Crr pour un vélo en pneus quatre saisons, mesuré).

    `part_groupe_max` : à Crr fixé, le CdA
    n'est cherché sur le temps que des sorties d'apprentissage dont la part
    de signal de groupe est **sous** ce seuil — une roue partielle, sous les
    50 % qui écartent une sortie, suffit à faire paraître le vélo plus fin.
    Moins de `SORTIES_MIN_SOLO` sorties passent : repli sur toutes celles
    que le seuil de 50 % garde, et `repli_solo` le dit.

    Enfin, la fourchette du porte à porte est mesurée sur les sorties de
    **validation** avec les paramètres finaux (`mesurer_porte_a_porte`).
    """
    if not sorties:
        raise ErreurUtilisateur(f"calibration : aucune sortie exploitable pour le vélo {velo}")
    apprentissage, validation_sorties = partager(sorties, part_validation)

    # Indexé par **position** dans `apprentissage`, et non par une clé
    # reconstruite : `identifiant` vaut `""` par défaut et `nom` retombe sur le
    # nom du fichier, si bien que deux sorties sans identifiant nommées
    # « Sortie du matin » s'écrasaient l'une l'autre — elles disparaissaient
    # alors de `tous` **et** de `restants` sans un mot. La commande passe
    # toujours un identifiant, donc c'était sans effet sur elle ; un appelant
    # de bibliothèque, lui, perdait des échantillons.
    par_sortie = [
        echantillonner(s.activite, s.vent, ftp_w=ftp_w, vitesse_min_kmh=vitesse_min_kmh)
        for s in apprentissage
    ]
    tous = [e for liste in par_sortie for e in liste]
    motifs: dict[str, int] = {}
    for e in tous:
        if not e.retenu:
            motifs[e.motif] = motifs.get(e.motif, 0) + 1

    passe1 = calibrer(tous, masse_totale_kg=masse_totale_kg, crr_fixe=crr_fixe)
    p1 = passe1.parametres()

    groupes: list[tuple[str, float]] = []
    gardees: list[int] = []
    parts: dict[int, float] = {}
    for rang, s in enumerate(apprentissage):
        en_groupe, part = detecter_groupe(
            s.activite, p1, s.vent, ftp_w=ftp_w, vitesse_min_kmh=vitesse_min_kmh
        )
        parts[rang] = part
        if en_groupe:
            groupes.append((s.nom, part))
        else:
            gardees.append(rang)

    restants = [e for rang in gardees for e in par_sortie[rang]]
    passe2 = (
        calibrer(restants, masse_totale_kg=masse_totale_kg, crr_fixe=crr_fixe)
        if gardees
        else passe1
    )
    n_solo = 0
    repli_solo = ""
    if crr_fixe is not None:
        # À Crr fixé, le CdA retenu est celui qui prédit le mieux le
        # **temps** des sorties d'apprentissage roulées seul, pas celui qui
        # explique le mieux la puissance des tronçons plats — mesuré, voir
        # `chercher_cda_sur_sorties`.
        #
        # La part de groupe qui trie ici n'est **pas** celle de la première
        # passe : ses paramètres sortent des moindres carrés des tronçons,
        # dont le CdA trop bas (0,287 sur un vélo de route de référence)
        # prédit des vitesses trop hautes et cache la roue partielle — 45
        # sorties passaient sous 30 %, contre 27 avec des paramètres
        # justes. On cherche donc d'abord le CdA sur toutes les sorties
        # gardées à 50 %, on remesure leur part avec lui, puis on ne garde
        # que celles sous `part_groupe_max`. Une itération de plus, pas deux.
        candidates = [apprentissage[rang] for rang in gardees] or list(apprentissage)
        passe2 = ajuster_sur_sorties(passe2, candidates, restants or tous)
        p_temps = passe2.parametres()
        for rang in gardees:
            s = apprentissage[rang]
            _, parts[rang] = detecter_groupe(
                s.activite, p_temps, s.vent, ftp_w=ftp_w, vitesse_min_kmh=vitesse_min_kmh
            )
        rangs_solo = [rang for rang in gardees if parts[rang] < part_groupe_max]
        if len(rangs_solo) < SORTIES_MIN_SOLO:
            repli_solo = (
                f"{len(rangs_solo)} sortie(s) d'apprentissage sous {part_groupe_max:.0%} de "
                f"signal de groupe, il en faut {SORTIES_MIN_SOLO} : le CdA est cherché sur "
                f"les {len(gardees) or len(apprentissage)} sorties sous "
                f"{PART_DISTANCE_GROUPE:.0%}, roue partielle comprise"
            )
            # Le CdA déjà cherché sur ces sorties-là reste le bon.
            n_solo = len(candidates)
        else:
            n_solo = len(rangs_solo)
            solo = [apprentissage[rang] for rang in rangs_solo]
            passe2 = ajuster_sur_sorties(passe2, solo, restants or tous)
    p2 = passe2.parametres()

    validation = valider([(s.activite, s.vent) for s in validation_sorties], p2)
    groupes_test = []
    for s in validation_sorties:
        en_groupe, part = detecter_groupe(
            s.activite, p2, s.vent, ftp_w=ftp_w, vitesse_min_kmh=vitesse_min_kmh
        )
        if en_groupe:
            groupes_test.append((s.nom, part))

    return RapportCalibration(
        velo=velo,
        ajustement=passe2,
        validation=validation,
        passe1=passe1,
        n_apprentissage=len(gardees),
        n_validation=len(validation_sorties),
        groupes=groupes,
        groupes_en_validation=groupes_test,
        echantillons=len(tous),
        echantillons_retenus=sum(1 for e in tous if e.retenu),
        motifs=dict(sorted(motifs.items(), key=lambda kv: (-kv[1], kv[0]))),
        echantillons_sans_vent=sum(1 for e in tous if e.retenu and not e.vent_connu),
        porte_a_porte=mesurer_porte_a_porte(
            validation_sorties, p2, ftp_w=ftp_w, vitesse_min_kmh=vitesse_min_kmh
        ),
        n_solo=n_solo,
        part_groupe_max=part_groupe_max,
        repli_solo=repli_solo,
    )
