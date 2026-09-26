"""Les CdA et Crr d'un vélo jamais calibré, par catégorie, et ce qu'ils valent.

Arbitrage du mainteneur du 17/09/2026 (`docs/journal/questions/questions_mainteneur.md`, réponse
« la littérature plutôt que la précision ») : plutôt que d'exiger de chaque
nouveau venu une calibration personnelle, on lui sert des **valeurs de
littérature par catégorie** — et on le dit. Ce module est cette table, et rien
d'autre : il ne lit aucun fichier, ne connaît aucun chemin et ne décide pas
quel vélo l'appelant regarde (règle absolue 2).

**Ce que ces valeurs sont.** Des ordres de grandeur de vulgarisation cycliste
(Best Bike Split, Bicycle Rolling Resistance, Roadman Cycling), pas des
publications revues par les pairs, et surtout **pas une mesure du cycliste qui
les reçoit**. Tout écran qui affiche un temps calculé avec elles doit porter la
mention correspondante — c'est le rôle de la provenance `littérature` rendue
par `physique.commande.parametres_du_velo` (règle absolue 5).

**Ce qu'elles valent, mesuré.** La campagne du 17/09/2026 (commit `b6114b2`)
a rejoué **34 sorties de validation du mainteneur** avec ces jeux au lieu de sa
calibration, et lu l'écart en minutes sur une boucle de 2 h (`mae × 120`). Le
résultat tient en une phrase : **seule compte la résistance totale à l'allure
de croisière**, `F@27` — la force à vaincre à 27 km/h, sur le plat, sans vent.
À `F@27` égale, le partage entre CdA et Crr ne déplace pas la durée d'une
demi-minute ; un newton d'écart sur `F@27`, lui, coûte de l'ordre de deux
minutes et demie sur 2 h. C'est donc **ce nombre-là** que chaque entrée de la
table doit poser au bon endroit, pas un CdA physiquement défendable.

**n = 1.** Un cycliste, deux vélos, 34 sorties, à ~100 kg en ordre de marche.
Rien ici n'a été vérifié sur un autre gabarit, d'autres routes ou un autre
capteur. Les dérives citées plus bas sont celles mesurées **sur ses vélos à
lui**, et elles sont consignées entrée par entrée pour qu'on sache exactement
ce qu'on sert.

**Ce qui n'est pas résolu, et qu'on n'invente pas.** Deux jeux d'une même
famille — « route amateur » et le haut de sa fourchette — sont séparés de
2,4 N, soit ~5 minutes sur 2 h, et **rien dans ce que l'utilisateur saisit
aujourd'hui** (type de vélo, masse du vélo, masse du cycliste) ne dit lequel
lui va : ce qui les sépare, c'est la position sur le vélo, les pneus, la tenue
et la transmission. La masse, elle, déplace les deux jeux ensemble et ne
tranche donc rien. Faute de règle défendable, chaque catégorie porte le jeu
dont le `F@27` tombe le plus près de la **référence mesurée** pour cet usage,
et la question est posée au mainteneur (Q57). Une règle inventée serait pire
qu'un défaut assumé.
"""

from __future__ import annotations

from dataclasses import dataclass

from ourouler.noyau.texte import nombre_fr
from ourouler.physique.modele import RHO_DEFAUT, Parametres, force_a_plat_n

#: Vitesse de référence à laquelle la résistance totale se lit et se compare.
#: 27 km/h, c'est l'allure de croisière du mainteneur — et la valeur qui sert
#: encore de `vitesse_moyenne_kmh` par défaut dans la configuration.
VITESSE_REFERENCE_KMH = 27.0


@dataclass(frozen=True)
class Jeu:
    """Un couple (CdA, Crr) de littérature, avec d'où il sort."""

    nom: str
    cda_m2: float
    crr: float
    source: str

    def force_a_27_n(self, masse_totale_kg: float, rho: float = RHO_DEFAUT) -> float:
        """La résistance totale de ce jeu à 27 km/h, pour une masse donnée.

        Elle **dépend de la masse** : c'est pourquoi les valeurs citées dans
        `PAR_USAGE` sont celles du vélo sur lequel la dérive a été mesurée, et
        pas des constantes du jeu.
        """
        return force_a_plat_n(
            VITESSE_REFERENCE_KMH,
            Parametres(masse_totale_kg=masse_totale_kg, cda_m2=self.cda_m2, crr=self.crr, rho=rho),
        )


#: Les trois jeux mesurés le 17/09/2026. Les fourchettes citées sont celles sur
#: lesquelles les sources de vulgarisation s'accordent : amateur aux cocottes
#: 0,30 à 0,35 m², amateur dans le creux du cintre 0,27 à 0,30, chrono
#: compétitif 0,20 à 0,24 ; Crr d'un bon pneu de route sur bitume réel 0,004 à
#: 0,006, pneu bon marché ou VTT 0,008 à 0,012.
ROUTE_AMATEUR = Jeu(
    nom="route amateur",
    cda_m2=0.320,
    crr=0.0050,
    source=(
        "centre de la fourchette de vulgarisation cycliste — et, exactement, les "
        "CDA_DEFAUT/CRR_DEFAUT que le dépôt portait déjà sans le dire"
    ),
)

ROUTE_AMATEUR_HAUT = Jeu(
    nom="route amateur, haut de fourchette",
    cda_m2=0.360,
    crr=0.0060,
    source="position redressée, pneus courants ; 0,36 est au bord haut de ce que les sources citent",
)

CLM_AMATEUR = Jeu(
    nom="CLM amateur",
    cda_m2=0.260,
    crr=0.0045,
    source="chrono d'amateur, au-dessus des 0,20-0,24 du compétiteur",
)


@dataclass(frozen=True)
class Choix:
    """Le jeu retenu pour un usage, et **tout** ce qui permet d'en juger.

    `derive_min_2h` est l'écart mesuré à la calibration personnelle du vélo de
    référence, en minutes sur une boucle de 2 h : négatif, le jeu générique a
    fait *mieux* que la calibration sur les sorties de test. `ecartes` porte
    les jeux qu'on n'a pas pris et ce qu'ils auraient coûté — sans quoi
    personne ne peut vérifier le choix.
    """

    usage: str
    jeu: Jeu
    #: Le vélo du mainteneur sur lequel cet usage a été mesuré, et combien de
    #: sorties de validation. Jamais une marque ni un modèle : le nom que sa
    #: configuration donne au vélo est déjà dans la doc publique.
    mesure_sur: str
    #: La masse totale en mouvement de ce vélo-là, en kg (cycliste compris).
    #: Elle est nécessaire pour **recalculer** les `F@27` ci-dessous : la même
    #: paire (CdA, Crr) ne donne pas la même résistance à deux masses.
    masse_reference_kg: float
    #: `F@27` de sa calibration personnelle sur ce vélo : la cible à approcher.
    f27_reference_n: float
    #: `F@27` du jeu retenu, à la masse de ce vélo-là.
    f27_jeu_n: float
    derive_min_2h: float
    ecartes: tuple[tuple[Jeu, float, float], ...] = ()
    """Les jeux non retenus : (jeu, son F@27 sur le vélo de référence, sa dérive)."""

    @property
    def resume(self) -> str:
        """Une ligne lisible, pour un écran qui veut dire d'où sort le modèle."""
        return (
            f"« {self.jeu.nom} » — CdA {nombre_fr(self.jeu.cda_m2, 3)} m², "
            f"Crr {nombre_fr(self.jeu.crr, 4)} ; littérature, non mesurée sur vous. "
            f"Dérive mesurée sur {self.mesure_sur} : "
            f"{nombre_fr(self.derive_min_2h, 1, signe=True)} min sur 2 h "
            f"(F@27 {nombre_fr(self.f27_jeu_n, 2)} N contre {nombre_fr(self.f27_reference_n, 2)} N calibrés)."
        )


#: La table, par `config.Velo.usage`. Les usages acceptés sont ceux de
#: `config.USAGES_VELO` ; un usage absent d'ici rend `None` et l'appelant
#: retombe sur ses défauts muets, sans modèle physique.
#:
#: **Le choix de chaque ligne est celui du `F@27` le plus proche de la
#: référence mesurée, et rien de plus savant.** C'est assumé, et c'est
#: exactement ce que la mesure du 17/09 permet de justifier : à `F@27` bien
#: posée, le reste ne compte presque pas.
#:
#: **Deux lignes surprennent, et c'est la mesure qui les impose :**
#:
#: - `route` prend le **haut** de la fourchette, pas son centre. Sur le vélo de
#:   route du mainteneur, le centre (15,94 N) dérive de +3,3 min quand le haut
#:   (18,30 N) fait −0,8 min. C'est le défaut que le dépôt servait jusqu'ici :
#:   ses 25 sorties de validation se trompaient **toutes du même côté**, une
#:   boucle vendue pour 2 h en durant 2 h 07 à 2 h 22.
#: - `clm` ne prend **pas** le jeu qui porte son nom. Sur son chrono, « CLM
#:   amateur » est le pire des trois (+3,5 min) et « route amateur » le
#:   meilleur (+0,3 min) : il ne roule pas son chrono en position de chrono,
#:   ou pas avec l'équipement que la catégorie suppose. Nommer la catégorie
#:   d'après le vélo est mesuré faux **ici** ; que ce soit vrai ailleurs n'est
#:   pas mesuré, et c'est la moitié de Q57.
PAR_USAGE: dict[str, Choix] = {
    "route": Choix(
        usage="route",
        jeu=ROUTE_AMATEUR_HAUT,
        mesure_sur="le vélo de route du mainteneur, 25 sorties de validation",
        masse_reference_kg=100.0,
        f27_reference_n=18.04,
        f27_jeu_n=18.30,
        derive_min_2h=-0.8,
        ecartes=(
            (ROUTE_AMATEUR, 15.94, 3.3),
            (CLM_AMATEUR, 13.38, 10.3),
        ),
    ),
    "clm": Choix(
        usage="clm",
        jeu=ROUTE_AMATEUR,
        mesure_sur="le chrono du mainteneur, 9 sorties de validation (toutes estivales)",
        masse_reference_kg=101.0,
        f27_reference_n=15.90,
        f27_jeu_n=15.99,
        derive_min_2h=0.3,
        ecartes=(
            (CLM_AMATEUR, 13.42, 3.5),
            (ROUTE_AMATEUR_HAUT, 18.36, 5.6),
        ),
    ),
}


def pour_usage(usage: str) -> Choix | None:
    """Le choix de littérature d'un usage de vélo, ou `None` s'il n'y en a pas.

    `None` n'est pas une erreur : un usage que la table ne connaît pas (un
    gravel, le jour où `config.USAGES_VELO` s'ouvrira) doit laisser l'appelant
    dire « aucun modèle » plutôt que servir un temps calculé avec le jeu d'une
    autre catégorie.
    """
    return PAR_USAGE.get(str(usage).strip().casefold())


# --- le Crr par catégorie de pneu (L9.1, 25/09/2026) ---------------------------
#
# **Ce que valent les CdA et Crr calibrés avec ce Crr : des paramètres de
# compensation, pas des mesures physiques.** Ils absorbent tout ce que le
# modèle ne sait pas — l'étalonnage du capteur d'abord. Le vélo de route du
# mainteneur porte un capteur **unilatéral** (jambe gauche × 2), le chrono un
# capteur double : un écart de quelques pour cent sur les watts se retrouve
# tel quel dans le CdA (± 4 % de puissance déplacent le CdA de 0,306 à 0,356,
# mesuré le 25/09). Deux CdA calibrés sur deux capteurs différents **ne se
# comparent donc pas** ; ce qui se compare, c'est le temps prédit, et la
# puissance qu'il faut pour tenir une vitesse donnée *par watt affiché* sur
# ce capteur-là.
#
# La note du 23/09 (`docs/journal/sprints/plan_sprints_agents.md`, « le porte à porte ignore
# le relief ») a montré que la calibration libre ne sépare pas CdA et Crr sur
# les données du mainteneur : laissée à elle-même, elle rend un Crr de 0,0106
# au vélo en pneus quatre saisons et de 0,0084 au chrono en tubeless, puis
# dérive dès qu'on la pousse. **Fixer le Crr d'après le pneu et ne chercher que
# le CdA** fait apparaître un vrai minimum sur les deux vélos. Cette table est
# ce Crr fixé.
#
# **Ce que ces valeurs sont.** Des ordres de grandeur sur **bitume réel**, pas
# des mesures de banc. Les bancs à rouleau publiés (Bicycle Rolling Resistance,
# consulté pour cette table le 25/09/2026) mesurent un pneu de course rapide à
# ~0,003 et un pneu d'entraînement renforcé à ~0,005 sur un tambour lisse, à
# haute pression ; la route française, rugueuse, et les pressions basses
# (moins de 5 bar, hookless ou confort) les relèvent d'un tiers à la moitié —
# c'est la convention retenue ici, **non mesurée sur le cycliste**. Les deux
# premières lignes sont exactement celles avec lesquelles la note du 23/09 a
# trouvé ses minimums (0,005 et 0,006) ; les trois autres suivent la fourchette
# déjà citée en tête de ce module (« pneu bon marché ou VTT 0,008 à 0,012 »).
#
# Les clés sont celles que `config.PNEUS_VELO` accepte : un test garde les deux
# listes identiques.

#: Date de la table des pneus : à relire si elle vieillit.
DATE_PNEUS = "2026-09-25"


@dataclass(frozen=True)
class Pneu:
    """Une catégorie de pneu et le Crr sur bitume réel qu'on lui prête."""

    cle: str
    libelle: str
    crr: float
    source: str


PNEUS: dict[str, Pneu] = {
    p.cle: p
    for p in (
        Pneu(
            cle="course_rapide",
            libelle="course rapide (tubeless ou chambre latex, type GP5000 TR)",
            crr=0.005,
            source=(
                "banc ~0,003 relevé pour route réelle et pression basse ; valeur de la "
                "note du 23/09/2026 pour le chrono du mainteneur"
            ),
        ),
        Pneu(
            cle="course_quatre_saisons",
            libelle="course quatre saisons ou renforcé (type GP5000 All Season)",
            crr=0.006,
            source=(
                "banc ~0,004 relevé pour route réelle et pression basse ; valeur de la "
                "note du 23/09/2026 pour le vélo de route du mainteneur"
            ),
        ),
        Pneu(
            cle="entrainement",
            libelle="entraînement courant (renforcé anti-crevaison)",
            crr=0.008,
            source="banc ~0,005-0,006 relevé pour route réelle ; bas de la fourchette 0,008-0,012",
        ),
        Pneu(
            cle="gravel",
            libelle="gravel, roulé sur route",
            crr=0.009,
            source="pneu à crampons fins sur bitume ; ordre de grandeur de vulgarisation",
        ),
        Pneu(
            cle="vtt",
            libelle="VTT, roulé sur route",
            crr=0.012,
            source="haut de la fourchette 0,008-0,012 citée en tête de module",
        ),
    )
}


def pour_pneu(cle: str | None) -> Pneu | None:
    """La catégorie de pneu nommée, ou `None` (pneu non renseigné ou inconnu)."""
    if not cle:
        return None
    return PNEUS.get(str(cle).strip().casefold())


# --- la fourchette du porte à porte, pour un vélo jamais calibré ---------------
#
# Le porte à porte d'une boucle est `temps_estime_s × [bas, haut]` : le temps
# en mouvement que le modèle simule sur ce tracé-ci (relief et vent réels),
# multiplié par ce que les vraies sorties du cycliste coûtent en plus — arrêts,
# relances, et l'erreur propre du modèle. Un vélo calibré porte **sa**
# fourchette dans `calibration.json` (centiles 25-75 mesurés sur ses sorties
# de validation roulées seul, jamais vues par l'ajustement). Un vélo qui ne
# l'est pas — ou dont la validation compte moins de huit sorties roulées
# seul — reçoit celle-ci.
#
# **C'est une convention, mesurée sur un seul cycliste.** Le 25/09/2026,
# après la contre-lecture (fourchette sur la **validation** seule, CdA cherché
# sur les sorties à moins de 30 % de signal de groupe), `ourouler calibrer` a
# mesuré, sur le temps écoulé réel (du premier au dernier point, arrêts
# compris) rapporté au temps simulé, sorties de validation à moins de 50 % de
# signal de groupe :
#
# | vélo du mainteneur             | n  | 25ᵉ   | médiane | 75ᵉ   |
# |--------------------------------|----|-------|---------|-------|
# | route (Crr 0,006, CdA 0,378)   | 25 | 1,021 | 1,035   | 1,099 |
# | chrono (Crr 0,005, CdA 0,318)  | 7  | 1,044 | 1,086   | 1,137 |
#
# Le chrono n'a que sept sorties de validation roulées seul : trop peu pour
# sa propre fourchette (il reçoit donc celle-ci), assez pour en borner une.
# La fourchette par défaut est l'**enveloppe** des deux : le plus bas des deux
# 25ᵉ centiles, le plus haut des deux 75ᵉ, arrondis au centième vers
# l'extérieur, et la moyenne des deux médianes. Plus large que chacune, à
# dessein : elle couvre deux vélos et deux usages sans savoir lequel elle
# sert. La version précédente (× 1,01 à × 1,11) était mesurée sur toutes les
# sorties, apprentissage compris, et sous-prédisait une sortie neuve.

#: (bas, médiane, haut) du ratio temps écoulé réel / temps simulé.
FOURCHETTE_PORTE_A_PORTE_DEFAUT = (1.02, 1.06, 1.14)


# --- une FTP plausible, pour qui n'en a aucune (T5 de l'accueil) --------------
#
# Décision du 19/09/2026 (`docs/ux/parcours_accueil.md` §5.3, [[Q65]] encore
# ouverte) : le fond du tunnel de l'entonnoir d'accueil ne peut jamais
# échouer, même sans vitesse déclarée, sans compte Intervals et sans FTP
# connue. Jusqu'ici cette table ne donnait que des paramètres aérodynamiques
# (CdA, Crr) : rien n'y produisait une puissance seuil, alors que le reste du
# produit (les zones, `seance.ecran_ftp`) ne sait raisonner qu'en watts.
#
# **Ce chiffre est une convention, pas une mesure**, et il le reste tant que
# [[Q65]] n'est pas tranchée — exactement le même statut que les jeux
# aérodynamiques ci-dessus au moment de leur écriture, avant la campagne du
# 17/09/2026. La différence, assumée : aucune campagne équivalente n'existe
# ici. Une seule valeur, non distinguée par usage (route/clm) — [[Q57]] a
# montré qu'une distinction non mesurée peut se tromper de sens (le jeu
# « CLM amateur » n'est pas le meilleur pour un usage clm sur les données du
# mainteneur) ; inventer un second chiffre sans donnée serait le même risque
# une fois de plus.

#: Watts par kilogramme de cycliste, pour une FTP jamais mesurée ni déclarée.
#: Ordre de grandeur usuel pour un cycliste amateur non spécifiquement
#: entraîné (sources de vulgarisation citées en tête de module) : ni un
#: débutant complet, ni un compétiteur. **Non mesuré** — voir [[Q65]].
FTP_W_PAR_KG_DEFAUT = 2.2

#: Bornes de plausibilité de la FTP rendue : mêmes bornes que
#: `config.py` (`_nombre_optionnel(..., 50, 1000)`) pour qu'un poids extrême
#: ne produise jamais une FTP que la configuration refuserait de recharger.
FTP_W_MINI = 50.0
FTP_W_MAXI = 1000.0


def ftp_defaut(masse_kg: float) -> float:
    """Une FTP plausible à partir du seul poids du cycliste — le filet, T5.

    `masse_kg × FTP_W_PAR_KG_DEFAUT`, borné à `[FTP_W_MINI, FTP_W_MAXI]`.
    C'est délibérément le calcul le plus simple possible : il n'y a, à ce
    jour, aucune mesure qui justifierait d'y mêler le type de vélo, l'âge ou
    quoi que ce soit d'autre — en ajouter un serait donner à ce chiffre une
    précision qu'il n'a pas. Tout écran qui l'affiche doit le dire
    « générique, à partir de votre poids et de votre vélo seuls » (le vélo
    entrant par ailleurs, via son type, dans le reste du modèle physique).
    """
    brut = masse_kg * FTP_W_PAR_KG_DEFAUT
    return min(max(brut, FTP_W_MINI), FTP_W_MAXI)


__all__ = [
    "CLM_AMATEUR",
    "DATE_PNEUS",
    "FOURCHETTE_PORTE_A_PORTE_DEFAUT",
    "PNEUS",
    "FTP_W_MAXI",
    "FTP_W_MINI",
    "FTP_W_PAR_KG_DEFAUT",
    "PAR_USAGE",
    "ROUTE_AMATEUR",
    "ROUTE_AMATEUR_HAUT",
    "VITESSE_REFERENCE_KMH",
    "Choix",
    "Jeu",
    "Pneu",
    "ftp_defaut",
    "pour_pneu",
    "pour_usage",
]
