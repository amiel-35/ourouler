#!/usr/bin/env python3
"""Ce que la position aérodynamique coûte ou rapporte, mesuré à Crr forcé commun.

**Pourquoi ce script existe.** La calibration ordinaire ajuste CdA et Crr
ensemble, sortie par sortie, vélo par vélo. Sur les données du mainteneur elle
rend deux CdA *identiques* pour un vélo de route et un vélo de contre-la-montre,
et fait passer tout l'écart dans le Crr, qui vient s'asseoir près de sa borne
haute. Ce n'est pas un résultat, c'est un aveu : **CdA et Crr ne sont pas
séparables** par ces données. Les deux termes se compensent — un CdA plus bas
avec un Crr plus haut prédit la même puissance à l'allure courante — et rien
dans une sortie ordinaire ne porte assez de variété de vitesse pour les
départager. `physique/calibration.py` le dit déjà dans son en-tête ; la
conséquence est que la somme des forces est juste, que les temps prédits sont
bons, et qu'**aucune lecture du CdA seul n'est fiable**.

D'où la question à laquelle la calibration ordinaire ne peut pas répondre :
*combien la position aéro fait-elle gagner ?*

**Ce que ce script fait de plus.** Il remplace l'information absente par une
**contrainte physique**. Si l'on compare deux populations de tronçons roulés
sur le **même vélo, les mêmes roues, les mêmes pneus, à la même masse**, et
que seule la position change, alors le Crr est nécessairement le même des deux
côtés. On n'ajuste plus deux paramètres deux fois, mais **trois en une fois** :
un Crr commun et un CdA par population. L'écart entre les deux CdA ne peut
plus être absorbé par le roulement — il n'a plus que l'air où aller.

L'ajustement reste celui de `calibration.calibrer` : le modèle est linéaire en
CdA et en Crr, les colonnes sortent de `puissance_requise` elle-même (via
`calibration._matrices`, réutilisée telle quelle pour que ce script ne puisse
pas diverger de la physique du reste du projet), et les bornes `CDA_MIN/MAX` et
`CRR_MIN/MAX` sont celles du contrat. Seule la géométrie du problème change :
une colonne de CdA par groupe au lieu d'une seule.

**Ce que le script mesure, exactement.** L'écart de CdA entre deux
**populations de tronçons**, pas entre deux positions pures. Personne ne tient
les prolongateurs cent pour cent d'une course, ni les mains en bas cent pour
cent d'un bloc d'entraînement. Le chiffre rendu est donc un écart *moyen* qui
sous-estime l'écart entre les positions elles-mêmes, dans une proportion que
les données ne disent pas.

**Les limites, à lire avec le chiffre.**

1. **L'aspiration ne peut pas être filtrée tronçon par tronçon.**
   `calibration.detecter_groupe` repère les tronçons roulés plus vite que la
   puissance ne le justifie — ce qui est la signature de la roue d'un autre.
   C'est aussi, exactement, la signature d'un CdA plus bas. Filtrer là-dessus
   effacerait le gain qu'on cherche à mesurer. Le script se contente donc de
   **rapporter** la part de distance anormalement rapide de chaque sortie.
   Quand le cycliste témoigne avoir roulé seul, cette part sert alors de
   **contrôle de l'instrument** et non de correction : si elle est forte là où
   il dit n'avoir eu personne devant lui, c'est un fait à regarder — soit la
   position gagne vraiment beaucoup, soit le modèle se trompe ailleurs.
2. **Le Crr commun est une hypothèse, pas un fait.** Deux populations séparées
   par des mois ou des années, ce sont des pneus qui ont vieilli, ou changé, ou
   gonflé autrement. L'hypothèse porte tout le résultat : si le Crr a réellement
   bougé entre les deux groupes, l'écart se retrouve dans le ΔCdA.
3. **La masse du cycliste est une seule valeur de configuration.** Elle ne suit
   pas le temps. Entre deux groupes distants d'un an, elle est donc fausse d'un
   côté au moins. Sur le plat l'effet est faible (le Crr la porte), en pente il
   ne l'est pas — d'où le plafond de pente hérité de `echantillonner`.
4. **Deux appareils peuvent enregistrer les deux groupes.** Montre et compteur
   n'échantillonnent pas au même pas, ne filtrent pas l'altitude pareil et ne
   donnent pas la vitesse de la même façon. Le script imprime l'appareil de
   chaque sortie : deux appareils différents sont un doute de plus.
5. **L'aéro croît en v³ en puissance.** Comparer des tronçons rapides à des
   tronçons lents laisse l'ajustement compenser ailleurs. Le script imprime la
   distribution de vitesse de chaque groupe et sait restreindre les deux à leur
   plage commune (`--plage-commune`).
6. **L'incertitude naïve est optimiste** : deux tronçons de 200 m voisins se
   ressemblent, les résidus ne sont pas indépendants. Le script rend donc aussi
   un intervalle par **bootstrap par blocs**, qui rééchantillonne des paquets de
   tronçons consécutifs et respecte cette ressemblance. C'est celui-là qu'il
   faut lire.
7. **Le terrain n'est pas le même, et ce biais va dans le sens de l'effet.**
   Un parcours de course fermé, plat et sans virages porte des tronçons
   beaucoup plus proches des hypothèses du modèle — `simuler` ne connaît
   qu'une vitesse d'équilibre, il n'a aucune accélération et aucun freinage —
   que des routes d'entraînement ordinaires, où le cycliste ralentit et
   relance sans arrêt. Le groupe roulé sur route ouverte paraît donc
   systématiquement plus lent que le modèle ne le prédit, **pour des raisons
   qui n'ont rien à voir avec la position**, et cet écart-là s'ajoute à celui
   qu'on cherche. `--stabilite-max`, `--delta-v-max` et `--pente-max-abs` sont
   les trois remèdes offerts ; le tableau de sensibilité dit ce qu'ils
   changent. Si le ΔCdA fond quand on les serre, c'est du terrain qu'on
   mesurait.

**Le script ne conclut pas à la place du lecteur.** Il imprime un tableau de
sensibilité : le même ΔCdA sous plusieurs jeux de filtres. Si le chiffre bouge
beaucoup d'une ligne à l'autre, c'est que la mesure ne tranche pas, et c'est
le résultat qu'il faut retenir.

**Le résultat du 18/09/2026**, groupe A = la partie cycliste d'un triathlon
longue distance sur route fermée et plate (85,6 km, prolongateurs), groupe B =
dix sorties d'entraînement du même vélo l'année suivante (route ouverte, sans
prolongateurs), segments d'un kilomètre :

    CdA A   0,180 m²   ← en butée sur CDA_MIN
    CdA B   0,230 m²
    Crr commun 0,0108
    ΔCdA  −0,050 m²  →  −13 W à 27 km/h,  −29 W à 35 km/h
    bootstrap par blocs (90 %)  −33 … −2 W à 35 km/h
    9 segments côté A (sur 38 formés), 17 côté B (sur 63)

**Ce résultat ne tranche pas, et voici pourquoi.** Trois faits, dans l'ordre
d'importance :

- **Le CdA du groupe A vient buter sur sa borne basse dans presque toutes les
  variantes**, et l'ajustement sans bornes veut descendre encore, jusqu'à
  0,170 m². Pour un cycliste de 91 kg sur des prolongateurs rapportés, c'est
  physiquement invraisemblable — un tel CdA est celui d'un spécialiste du
  contre-la-montre. Le modèle fait donc passer par la colonne aérodynamique
  quelque chose qui n'est pas de l'aérodynamique, et ce quelque chose est
  compté dans le ΔCdA.
- **Le chiffre dépend du filtre**, de −9 W à −31 W à 35 km/h selon la sévérité
  retenue. Il est d'autant plus petit qu'on serre la stabilité de vitesse ou
  qu'on restreint au plat — autrement dit, une part du ΔCdA est bien du terrain
  et non de la position.
- **Le bootstrap par blocs frôle zéro** par le haut (−2 W à 35 km/h à la borne
  optimiste), parce qu'il ne reste que neuf segments d'un kilomètre côté A.

**Ce qui est solide, en revanche** : le **signe**. Le groupe aux prolongateurs
est plus aérodynamique dans **toutes** les variantes essayées, sans exception,
et la valeur centrale reste autour de −29 W à 35 km/h que le groupe B compte
deux sorties ou dix. L'ordre de grandeur attendu par le mainteneur (25 à 30 W)
est compatible avec la mesure, mais la mesure ne le confirme pas : elle ne sait
pas distinguer 10 W de 30 W.

**Le contrôle d'aspiration concorde avec le témoignage.** Le mainteneur dit
avoir roulé seul (« pas de drafting et peu de paquets voire pas »).
`detecter_groupe` trouve 47 % de distance inexpliquée sur la course, contre 26
à 45 % sur les dix sorties d'entraînement solitaires : la course est au haut de
la fourchette, pas hors d'elle. Rien dans les données ne ressemble à la
signature d'un peloton — ce qui ne prouve pas l'absence d'abri, mais ne la
contredit pas.

**Ce que l'agrégation a changé.** En tronçons de 200 m, l'écart quadratique
résiduel valait 79 W ; en segments d'un kilomètre, 22 W. Le modèle d'équilibre
est bien beaucoup moins faux à l'échelle du kilomètre, comme le mainteneur
l'avait annoncé. Le ΔCdA, lui, bouge peu entre les deux granularités (−0,046
contre −0,050 m²) : la granularité n'est donc pas la source du désaccord.

**Aucun critère personnel n'est écrit ici.** Les sorties se désignent en ligne
de commande, par jour et éventuellement par un bout de nom ; la session à
isoler dans un fichier multisport se désigne par son sport ou son rang. Le
dépôt ne porte donc ni date, ni lieu, ni identifiant du mainteneur.

**Réseau.** Les sorties viennent du cache local. L'archive météo passe par la
mémoïsation de `ClientArchive`, comme `ourouler calibrer` : un jour déjà vu ne
coûte rien, un jour inconnu est un appel. Le rapport dit lequel des deux s'est
produit. `--sans-vent` interdit tout appel, au prix d'un vent compté nul.

**Ce script n'écrit rien.** Il ne touche ni `calibration.json` ni la
configuration : il ajuste en mémoire et imprime.

Usage :
    uv run python scripts/validation/cda_position_retrospectif.py \\
        --groupe-a AAAA-MM-JJ:bout-de-nom --session-sport cycling \\
        --groupe-b AAAA-MM-JJ --groupe-b AAAA-MM-JJ
"""

from __future__ import annotations

import argparse
import itertools
import math
import random
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import date, datetime
from pathlib import Path

import fitdecode
import numpy as np

from ourouler.activites.cache import Cache, EntreeCache
from ourouler.activites.inventaire import en_interieur, rattacher_velo
from ourouler.config import Config, Velo, charger
from ourouler.noyau.activite import Activite, est_sport_velo, puissance_moyenne
from ourouler.noyau.erreurs import ErreurConnecteur, ErreurUtilisateur
from ourouler.noyau.meteo import HeureArchive
from ourouler.physique.calibration import (
    CDA_MAX,
    CDA_MIN,
    CRR_MAX,
    CRR_MIN,
    V_REFERENCES_KMH,
    Echantillon,
    _matrices,
    detecter_groupe,
    echantillonner,
)
from ourouler.physique.echantillonnage import DELTA_V_MAX_MS, LONGUEUR_ECHANTILLON_M
from ourouler.physique.modele import Parametres, puissance_requise
from ourouler.services.calibrer import masse_totale_kg

#: Bornes des trois inconnues, dans l'ordre (CdA du groupe A, CdA du groupe B,
#: Crr commun). Ce sont celles du contrat de sprint, reprises telles quelles :
#: un ΔCdA obtenu avec des bornes plus larges ne serait pas comparable au CdA
#: que la calibration ordinaire rend.
BORNES = ((CDA_MIN, CDA_MAX), (CDA_MIN, CDA_MAX), (CRR_MIN, CRR_MAX))

#: Nombre d'inconnues. Nommé parce qu'il sert à trois endroits (degrés de
#: liberté de la variance, rang attendu, taille des vecteurs).
N_PARAMETRES = 3

#: Longueur d'un segment agrégé, en mètres. Le mainteneur a demandé « des
#: segments de 1-2 km stables » plutôt que les tronçons d'environ 200 m de
#: `echantillonner`, et il a raison : le modèle du projet calcule une vitesse
#: d'équilibre sans aucune accélération, hypothèse qui est fausse à 200 m et
#: défendable sur un kilomètre d'effort tenu.
SEGMENT_MIN_M = 1000.0
SEGMENT_MAX_M = 2000.0

#: Dispersion tolérée **à l'intérieur** d'un segment, en coefficient de
#: variation (écart-type sur moyenne) des tronçons qui le composent. La vitesse
#: est serrée : c'est elle qui porte l'aérodynamique, et un segment dont la
#: vitesse flotte de 10 % ne décrit plus un équilibre. La puissance est plus
#: lâche — un capteur de puissance est bruyant à l'échelle de 200 m, et un
#: cycliste humain ne tient pas un watt près.
CV_VITESSE_MAX = 0.05
CV_PUISSANCE_MAX = 0.25

#: Pente en deçà de laquelle on ne compte pas un changement de signe comme un
#: changement de sens : 0,5 % sur 200 m, c'est un mètre de dénivelé, soit le
#: bruit d'un altimètre barométrique et rien d'autre.
BANDE_MORTE_PENTE = 0.005

#: Longueur visée d'un bloc du bootstrap, en mètres. Assez long pour que deux
#: blocs tirés au sort ne partagent ni la même route, ni le même coup de vent,
#: ni la même minute d'archive météo. Exprimé en mètres et non en nombre
#: d'échantillons parce que l'échantillon fait 200 m sans agrégation et 1 à
#: 2 km avec : un nombre fixe donnerait des blocs de 5 km dans un cas et de
#: 37 km dans l'autre, et le second ne laisserait plus rien à tirer.
BLOC_BOOTSTRAP_M = 5000.0

#: Répétitions du bootstrap par blocs. 400 suffit pour un intervalle à 90 % :
#: l'incertitude du script sur ses propres quantiles y est très en dessous de
#: l'incertitude qu'il mesure.
REPETITIONS_BOOTSTRAP = 400

#: Les jeux de filtres du tableau de sensibilité. Le premier est celui que le
#: lecteur a demandé en ligne de commande ; les autres resserrent une vis à la
#: fois. C'est l'**écart entre ces lignes**, plus que la première d'entre
#: elles, qui dit si la mesure tranche.
VARIANTES: tuple[tuple[str, dict], ...] = (
    ("réglages demandés", {}),
    ("tronçons de 200 m, sans agrégation", {"segment_min_m": None}),
    ("segments de 2 à 3 km", {"segment_min_m": 2000.0, "segment_max_m": 3000.0}),
    ("segments très réguliers (CV vitesse < 3 %)", {"cv_vitesse_max": 0.03}),
    ("tronçons très réguliers (Δv < 0,5 m/s)", {"delta_v_max": 0.5}),
    ("vitesse stable dans le tronçon (< 0,5)", {"stabilite_max": 0.5}),
    ("presque plat des deux côtés (|p| < 1 %)", {"pente_max_abs": 0.01}),
    ("effort soutenu (P ≥ 0,55 × FTP)", {"puissance_min_pct": 0.55}),
    ("plage de vitesse commune", {"plage_commune": True}),
    (
        "tout ensemble",
        {
            "delta_v_max": 0.5,
            "stabilite_max": 0.5,
            "pente_max_abs": 0.01,
            "puissance_min_pct": 0.55,
            "plage_commune": True,
        },
    ),
)


# --- sessions d'un FIT multisport ---------------------------------------------


@dataclass(frozen=True)
class SessionFit:
    """Une trame `session` d'un FIT, réduite à ce qui sert à découper les points.

    `rang` est compté **à partir de 1**, dans l'ordre du fichier : c'est ce
    qu'un humain lit quand il regarde son triathlon, et c'est ce qu'il tapera
    en ligne de commande.
    """

    rang: int
    sport: str | None
    sous_sport: str | None
    debut: datetime
    fin: datetime
    distance_m: float | None = None

    @property
    def intitule(self) -> str:
        sport = self.sport or "?"
        return f"{sport}/{self.sous_sport}" if self.sous_sport else sport


def sessions_fit(chemin: Path) -> list[SessionFit]:
    """Les sessions d'un fichier FIT, dans l'ordre, avec leurs bornes de temps.

    `activites.lecture` compte les sessions et **somme** leurs distances : c'est
    ce qu'il faut pour inventorier, et c'est exactement ce qu'il ne faut pas
    pour calibrer un triathlon — la « sortie » obtenue commence à 3 km/h dans
    l'eau. Il faut donc redescendre au fichier pour récupérer les bornes, que
    le modèle `Activite` ne porte pas.

    Une trame `session` sans `start_time` ou sans `timestamp` est ignorée :
    sans ses deux bouts elle ne découpe rien.
    """
    sessions: list[SessionFit] = []
    with fitdecode.FitReader(str(chemin)) as fit:
        for trame in fit:
            if trame.frame_type != fitdecode.FIT_FRAME_DATA or trame.name != "session":
                continue
            debut = _valeur(trame, "start_time")
            fin = _valeur(trame, "timestamp")
            if not isinstance(debut, datetime) or not isinstance(fin, datetime):
                continue
            sessions.append(
                SessionFit(
                    rang=len(sessions) + 1,
                    sport=_texte(_valeur(trame, "sport")),
                    sous_sport=_texte(_valeur(trame, "sub_sport")),
                    debut=debut,
                    fin=fin,
                    distance_m=_flottant(_valeur(trame, "total_distance")),
                )
            )
    return sessions


def _valeur(trame, nom: str):
    return trame.get_value(nom, fallback=None) if trame.has_field(nom) else None


def _texte(valeur) -> str | None:
    if valeur is None:
        return None
    texte = str(valeur).strip().casefold()
    return texte or None


def _flottant(valeur) -> float | None:
    return float(valeur) if isinstance(valeur, int | float) else None


def choisir_session(
    sessions: Sequence[SessionFit], *, sport: str | None = None, rang: int | None = None
) -> SessionFit:
    """La session désignée par son sport ou par son rang. Lève si le choix est ambigu.

    Une ambiguïté n'est pas arbitrée en silence : un triathlon porte deux
    transitions et un duathlon deux courses à pied, et deviner laquelle compte
    fabriquerait un résultat que personne ne pourrait relire.
    """
    if rang is not None:
        for session in sessions:
            if session.rang == rang:
                return session
        raise ErreurUtilisateur(f"session {rang} absente : le fichier en porte {len(sessions)}")
    if sport is None:
        raise ErreurUtilisateur("préciser --session-sport ou --session-rang")
    voulu = sport.strip().casefold()
    trouvees = [s for s in sessions if s.sport == voulu]
    if not trouvees:
        connus = ", ".join(sorted({s.intitule for s in sessions})) or "aucune"
        raise ErreurUtilisateur(f"aucune session « {sport} » : sports du fichier — {connus}")
    if len(trouvees) > 1:
        rangs = ", ".join(str(s.rang) for s in trouvees)
        raise ErreurUtilisateur(
            f"{len(trouvees)} sessions « {sport} » (rangs {rangs}) : préciser --session-rang"
        )
    return trouvees[0]


def isoler_session(activite: Activite, session: SessionFit) -> Activite:
    """L'activité réduite aux points d'une seule session, distances remises à zéro.

    **La remise à zéro n'est pas cosmétique.** `echantillonner` écarte les
    premiers `DEBUT_IGNORE_M` mètres (mise en route, capteur qui se cale) en
    lisant la distance cumulée des points. Dans un fichier multisport, cette
    distance court depuis le tout premier coup de bras : la partie vélo d'un
    triathlon commencerait déjà « à 1,9 km » et ne perdrait presque rien de son
    départ, alors que c'est exactement le moment où le cycliste sort de l'eau,
    enfile ses chaussures et accélère depuis l'arrêt.

    Les grandeurs dérivées de l'activité entière (dénivelé, puissance
    normalisée) sont remises à `None` plutôt que recalculées à moitié : elles
    ne servent pas ici, et une valeur héritée du triathlon complet serait un
    piège pour le prochain lecteur. La puissance moyenne, elle, est recalculée
    sur les seuls points gardés — elle est bon marché et sert au rapport.
    """
    points = [p for p in activite.points if p.t is not None and session.debut <= p.t <= session.fin]
    if len(points) < 2:
        raise ErreurUtilisateur(
            f"session {session.rang} ({session.intitule}) : {len(points)} point(s) dans ses bornes"
        )
    origine = points[0].dist_m or 0.0
    points = [replace(p, dist_m=(p.dist_m - origine) if p.dist_m is not None else None) for p in points]
    return replace(
        activite,
        points=points,
        debut=points[0].t,
        duree_s=(points[-1].t - points[0].t).total_seconds(),
        duree_mouvement_s=None,
        distance_m=points[-1].dist_m,
        denivele_m=None,
        puissance_moy_w=puissance_moyenne(points),
        puissance_np_w=None,
        sport=session.intitule,
        meta={**activite.meta, "session_isolee": session.rang},
    )


# --- ajustement à trois paramètres --------------------------------------------


@dataclass(frozen=True)
class AjustementApparie:
    """Un Crr commun et un CdA par groupe, et ce que ça vaut.

    `ecart_type_delta` est celui de la **différence** des deux CdA, pas la
    somme des deux écarts-types : les deux colonnes partagent la colonne du
    Crr, donc leurs erreurs sont corrélées, et ignorer cette corrélation
    donnerait un intervalle faux — trop large ou trop étroit selon le signe.
    """

    cda_a: float
    cda_b: float
    crr: float
    n_a: int
    n_b: int
    rmse_w: float
    mae_w: float
    rho_moyen: float
    masse_totale_kg: float
    ecart_type_cda_a: float | None = None
    ecart_type_cda_b: float | None = None
    ecart_type_delta: float | None = None
    bornes_atteintes: tuple[str, ...] = ()
    avertissements: tuple[str, ...] = ()
    libre: tuple[float, float, float] | None = None
    """La solution **sans bornes**, telle que les moindres carrés la rendent.

    Elle est rapportée même — surtout — quand elle est physiquement absurde.
    Un CdA que l'ajustement voudrait poser à 0,05 m² ou à −0,1 m² ne dit pas
    que le cycliste vole : il dit que le modèle a un biais systématique entre
    les deux groupes et qu'il le fait passer par la seule colonne qui puisse
    l'absorber. La valeur bornée, elle, cache ce désaccord derrière une valeur
    d'apparence raisonnable. Les deux ensemble se lisent ; la bornée seule
    ment par omission.
    """

    @property
    def delta_cda(self) -> float:
        """CdA du groupe A moins CdA du groupe B. Négatif = A est plus aérodynamique."""
        return self.cda_a - self.cda_b

    def watts(self, v_kmh: float) -> float:
        """Ce que `delta_cda` vaut en watts au pédalier, à plat, sans vent, à `v_kmh`.

        Passe par `puissance_requise` avec deux jeux de paramètres qui ne
        diffèrent **que** par le CdA : la différence de gravité, de roulement
        et de rendement s'annule d'elle-même, et le chiffre reste celui du
        modèle du projet plutôt qu'une formule recopiée.
        """
        v = v_kmh / 3.6
        commun = {"masse_totale_kg": self.masse_totale_kg, "crr": self.crr, "rho": self.rho_moyen}
        avant = puissance_requise(v, 0.0, 0.0, Parametres(cda_m2=self.cda_a, **commun))
        apres = puissance_requise(v, 0.0, 0.0, Parametres(cda_m2=self.cda_b, **commun))
        return avant - apres


def ajuster(
    groupe_a: Sequence[Echantillon],
    groupe_b: Sequence[Echantillon],
    *,
    masse_totale_kg: float,
) -> AjustementApparie:
    """Moindres carrés bornés sur (CdA_A, CdA_B, Crr), Crr forcé commun aux deux groupes.

    Le modèle de `calibration.calibrer` est linéaire : la puissance d'un
    tronçon vaut `a·CdA + b·Crr + c`, où a, b et c ne dépendent d'aucun des
    deux paramètres. Deux groupes qui partagent le Crr mais pas le CdA donnent
    donc simplement **une colonne de CdA par groupe**, chacune nulle hors de son
    groupe, et **une seule colonne de Crr** pour tout le monde. C'est cette
    colonne unique qui porte l'hypothèse physique de tout le script.

    `a`, `b` et `c` sont obtenus par `calibration._matrices`, la même fonction
    que la calibration ordinaire : ce script ne redérive aucune physique, il ne
    fait que recoller les colonnes autrement.
    """
    if len(groupe_a) < N_PARAMETRES or len(groupe_b) < N_PARAMETRES:
        raise ErreurUtilisateur(
            f"ajustement : {len(groupe_a)} et {len(groupe_b)} tronçons — il en faut au moins "
            f"{N_PARAMETRES} par groupe pour trois inconnues"
        )
    if not math.isfinite(masse_totale_kg) or masse_totale_kg <= 0:
        raise ErreurUtilisateur(f"ajustement : masse totale {masse_totale_kg!r} invalide")

    a_a, b_a, c_a, y_a = _matrices(groupe_a, masse_totale_kg)
    a_b, b_b, c_b, y_b = _matrices(groupe_b, masse_totale_kg)
    n_a, n_b = len(groupe_a), len(groupe_b)

    matrice = np.zeros((n_a + n_b, N_PARAMETRES))
    matrice[:n_a, 0] = a_a
    matrice[n_a:, 1] = a_b
    matrice[:, 2] = np.concatenate((b_a, b_b))
    reste = np.concatenate((y_a - c_a, y_b - c_b))

    avertissements: list[str] = []
    libre, rang = _moindres_carres(matrice, reste)
    if rang < N_PARAMETRES:
        avertissements.append(
            "les tronçons ne séparent pas les trois inconnues (rang "
            f"{rang} au lieu de {N_PARAMETRES}) : le résultat ci-dessous ne mesure rien"
        )
    elif not _dans_les_bornes(libre):
        avertissements.append(
            "la solution libre sort des bornes : ce que le script rend est le meilleur "
            "point du pavé, pas le minimum du modèle"
        )
    solution, bornes = _resoudre_borne(matrice, reste)
    if bornes:
        avertissements.append(
            "une borne est atteinte — le paramètre concerné est un aveu, pas une mesure : "
            "les données ne le contraignent pas"
        )

    residus = matrice @ solution - reste
    n = n_a + n_b
    ecarts = _ecarts_types(matrice, residus, n)
    tous = list(groupe_a) + list(groupe_b)
    return AjustementApparie(
        cda_a=float(solution[0]),
        cda_b=float(solution[1]),
        crr=float(solution[2]),
        n_a=n_a,
        n_b=n_b,
        rmse_w=float(np.sqrt(np.mean(residus**2))),
        mae_w=float(np.mean(np.abs(residus))),
        rho_moyen=float(np.mean([e.rho for e in tous])),
        masse_totale_kg=float(masse_totale_kg),
        ecart_type_cda_a=ecarts[0],
        ecart_type_cda_b=ecarts[1],
        ecart_type_delta=ecarts[3],
        bornes_atteintes=bornes,
        avertissements=tuple(avertissements),
        libre=(float(libre[0]), float(libre[1]), float(libre[2])) if rang >= N_PARAMETRES else None,
    )


def _moindres_carres(matrice: np.ndarray, reste: np.ndarray) -> tuple[np.ndarray, int]:
    solution, _, rang, _ = np.linalg.lstsq(matrice, reste, rcond=None)
    return solution, int(rang)


def _dans_les_bornes(solution: np.ndarray, marge: float = 1e-12) -> bool:
    return all(
        bas - marge <= float(x) <= haut + marge for x, (bas, haut) in zip(solution, BORNES, strict=True)
    )


def _resoudre_borne(matrice: np.ndarray, reste: np.ndarray) -> tuple[np.ndarray, tuple[str, ...]]:
    """Le minimum de la forme quadratique **sur le pavé** des bornes, et les bornes touchées.

    Écrêter chaque coordonnée séparément ne donne pas ce minimum : quand le CdA
    d'un groupe sort par le bas, le Crr optimal *à CdA borné* n'est plus celui
    de la solution libre. `calibration._borner` résout pour cette raison les
    arêtes d'un rectangle ; à trois inconnues, on énumère les 27 façons de
    fixer chaque paramètre (libre, en bas, en haut), on résout les inconnues
    restantes, et on garde la meilleure candidate **admissible**.

    C'est exact et pas seulement plausible : le minimum sur le pavé appartient
    à une face, et sur l'enveloppe affine de *sa* face il est le minimum sans
    contrainte — donc il fait partie des candidates énumérées ici.
    """
    meilleure: tuple[float, np.ndarray] | None = None
    for etats in itertools.product((None, 0, 1), repeat=N_PARAMETRES):
        candidate = _candidate(matrice, reste, etats)
        if candidate is None:
            continue
        ecart = float(np.sum((matrice @ candidate - reste) ** 2))
        if meilleure is None or ecart < meilleure[0]:
            meilleure = (ecart, candidate)
    if meilleure is None:  # pragma: no cover — le sommet « tout borné » est toujours admissible
        raise ErreurUtilisateur("ajustement : aucune solution admissible dans les bornes")
    solution = meilleure[1]
    touchees = []
    for i, (valeur, (bas, haut)) in enumerate(zip(solution, BORNES, strict=True)):
        nom = ("CdA A", "CdA B", "Crr")[i]
        if math.isclose(float(valeur), bas):
            touchees.append(f"{nom} = {bas:g} (borne basse)")
        elif math.isclose(float(valeur), haut):
            touchees.append(f"{nom} = {haut:g} (borne haute)")
    return solution, tuple(touchees)


def _candidate(matrice: np.ndarray, reste: np.ndarray, etats: Sequence[int | None]) -> np.ndarray | None:
    """La solution d'une face du pavé, ou `None` si elle en sort ou n'est pas unique."""
    valeurs = np.zeros(N_PARAMETRES)
    libres = []
    for i, etat in enumerate(etats):
        if etat is None:
            libres.append(i)
        else:
            valeurs[i] = BORNES[i][etat]
    if libres:
        cible = reste - matrice @ valeurs
        sous_matrice = matrice[:, libres]
        solution, rang = _moindres_carres(sous_matrice, cible)
        if rang < len(libres):
            # Face dégénérée : `lstsq` rend la solution de norme minimale, qui
            # n'a aucune raison d'être celle qu'on cherche. On la laisse tomber
            # plutôt que de la faire passer pour un optimum ; une autre face
            # portera le minimum, et le rang global est déjà signalé plus haut.
            return None
        for i, valeur in zip(libres, solution, strict=True):
            valeurs[i] = float(valeur)
    return valeurs if _dans_les_bornes(valeurs) else None


def _ecarts_types(
    matrice: np.ndarray, residus: np.ndarray, n: int
) -> tuple[float | None, float | None, float | None, float | None]:
    """(σ CdA A, σ CdA B, σ Crr, σ de la différence des deux CdA), ou `None`.

    La quatrième valeur n'est pas la somme des deux premières : les deux CdA
    partagent la colonne du Crr, donc `Var(A − B) = Var A + Var B − 2·Cov(A, B)`.
    Sur des données où le Crr est mal contraint, ce terme croisé est gros.

    **Ces écarts-types supposent des résidus indépendants**, ce que deux
    tronçons de 200 m voisins ne sont pas. Ils disent l'ordre de grandeur de ce
    que les données contraignent, pas l'erreur vraie — le bootstrap par blocs
    est là pour ça.
    """
    if n <= N_PARAMETRES:
        return (None, None, None, None)
    variance = float(residus @ residus) / (n - N_PARAMETRES)
    try:
        covariance = np.linalg.inv(matrice.T @ matrice) * variance
    except np.linalg.LinAlgError:
        return (None, None, None, None)
    diagonale = np.diag(covariance)
    if np.any(diagonale < 0):
        return (None, None, None, None)
    var_delta = float(covariance[0, 0] + covariance[1, 1] - 2 * covariance[0, 1])
    delta = math.sqrt(var_delta) if var_delta >= 0 else None
    return (float(np.sqrt(diagonale[0])), float(np.sqrt(diagonale[1])), float(np.sqrt(diagonale[2])), delta)


# --- bootstrap par blocs ------------------------------------------------------


def bootstrap_delta(
    groupe_a: Sequence[Echantillon],
    groupe_b: Sequence[Echantillon],
    *,
    masse_totale_kg: float,
    repetitions: int = REPETITIONS_BOOTSTRAP,
    bloc: int = 25,
    graine: int = 12345,
) -> list[float]:
    """Les ΔCdA obtenus en rééchantillonnant des **blocs de tronçons consécutifs**.

    Tirer des tronçons un par un supposerait qu'ils sont indépendants ; ils ne
    le sont pas — deux cents mètres se ressemblent beaucoup à deux cents mètres
    près, même route, même vent, même minute d'archive. Un bootstrap qui ignore
    cette ressemblance rend un intervalle beaucoup trop étroit, et le lecteur
    conclut à un gain là où il n'y a que de l'autocorrélation.

    On tire donc des blocs de `bloc` tronçons consécutifs, jusqu'à retrouver
    l'effectif de chaque groupe. Une répétition dont l'ajustement échoue (groupe
    dégénéré) est simplement sautée : le nombre de répétitions réellement
    abouties est rendu par la longueur de la liste.
    """
    tirage = random.Random(graine)
    deltas: list[float] = []
    for _ in range(repetitions):
        try:
            resultat = ajuster(
                _tirer_blocs(groupe_a, bloc, tirage),
                _tirer_blocs(groupe_b, bloc, tirage),
                masse_totale_kg=masse_totale_kg,
            )
        except ErreurUtilisateur:
            continue
        deltas.append(resultat.delta_cda)
    return sorted(deltas)


def _tirer_blocs(echantillons: Sequence[Echantillon], bloc: int, tirage: random.Random) -> list[Echantillon]:
    """Des blocs de `bloc` tronçons consécutifs, tirés avec remise, jusqu'à l'effectif d'origine."""
    n = len(echantillons)
    # Un bloc aussi long que le groupe ne tire jamais qu'une seule fenêtre : le
    # groupe devient une constante et ne contribue **plus aucune variabilité**
    # à l'intervalle, qui paraît alors magnifiquement étroit sans l'être. On
    # plafonne donc le bloc au tiers du groupe.
    taille = max(1, min(bloc, n // 3 if n >= 3 else 1))
    tires: list[Echantillon] = []
    while len(tires) < n:
        debut = tirage.randrange(0, n - taille + 1)
        tires.extend(echantillons[debut : debut + taille])
    return tires[:n]


# --- choix des sorties et des tronçons ----------------------------------------


@dataclass(frozen=True)
class Critere:
    """« jour » ou « jour:bout de nom » : de quoi désigner une sortie sans l'écrire ici."""

    jour: date
    motif: str = ""

    @classmethod
    def depuis_texte(cls, texte: str) -> Critere:
        jour, _, motif = texte.partition(":")
        try:
            return cls(jour=date.fromisoformat(jour.strip()), motif=motif.strip())
        except ValueError as e:
            raise ErreurUtilisateur(
                f"critère « {texte} » : attendu AAAA-MM-JJ ou AAAA-MM-JJ:bout-de-nom ({e})"
            ) from e

    def correspond(self, entree: EntreeCache) -> bool:
        """Le jour, le bout de nom — **et** qu'il s'agisse bien d'une sortie à vélo.

        Le garde-fou du sport n'est pas une précaution de style. Un jour
        d'entraînement porte souvent deux ou trois fichiers : le vélo, puis le
        footing d'enchaînement, parfois la natation. Un critère qui ne
        regarderait que la date les prendrait tous, et le footing entrerait
        dans l'ajustement avec sa « puissance » de course à pied — plusieurs
        centaines de watts pour dix kilomètres à pied, que le modèle
        expliquerait en gonflant la traînée. L'erreur est silencieuse et le
        résultat, faux.
        """
        if entree.jour != self.jour:
            return False
        nom = str(entree.meta.get("nom") or "").casefold()
        if self.motif.casefold() not in nom:
            return False
        return (
            est_sport_velo(entree.sport) and not en_interieur(entree) and entree.puissance_moy_w is not None
        )


@dataclass
class Sortie:
    """Une sortie retenue, ses tronçons bruts, et les doutes qui l'accompagnent."""

    entree: EntreeCache
    activite: Activite
    echantillons: list[Echantillon]
    part_rapide: float | None = None
    session: SessionFit | None = None

    @property
    def nom(self) -> str:
        return str(self.entree.meta.get("nom") or "(sans nom)")


@dataclass
class Groupe:
    """Un des deux groupes : ses sorties, et le vélo auquel elles se rattachent."""

    nom: str
    sorties: list[Sortie] = field(default_factory=list)

    @property
    def bruts(self) -> list[Echantillon]:
        return [e for sortie in self.sorties for e in sortie.echantillons]


@dataclass(frozen=True)
class Reglages:
    """Les filtres appliqués **identiquement aux deux groupes**.

    Identiquement : c'est la seule façon de ne pas fabriquer soi-même l'écart
    qu'on prétend mesurer. Un filtre plus sévère d'un côté que de l'autre
    déplacerait la vitesse moyenne d'un groupe, et l'aéro croît en v³.

    `stabilite_max` et `pente_max_abs` traitent le biais de terrain : un
    parcours de course fermé et plat porte des tronçons plus proches des
    hypothèses du modèle (vitesse d'équilibre, aucun freinage) que les routes
    d'entraînement ordinaires. Ce biais pousse dans le **même sens** que
    l'effet cherché — il gonfle le ΔCdA — donc le corriger est une des rares
    façons de ne pas confondre la route et la position.
    """

    delta_v_max: float = DELTA_V_MAX_MS
    stabilite_max: float | None = None
    pente_max_abs: float | None = None
    puissance_min_pct: float = 0.0
    puissance_max_pct: float | None = None
    plage_commune: bool = False
    plage_commune_pct: float = 5.0
    segment_min_m: float | None = SEGMENT_MIN_M
    segment_max_m: float = SEGMENT_MAX_M
    cv_vitesse_max: float = CV_VITESSE_MAX
    cv_puissance_max: float = CV_PUISSANCE_MAX
    bande_morte_pente: float = BANDE_MORTE_PENTE


def survivants(bruts: Sequence[Echantillon], reglages: Reglages, *, ftp_w: float) -> list[bool]:
    """Quels tronçons passent les filtres, **dans l'ordre**, un booléen par tronçon.

    Un masque et non une liste filtrée : l'agrégation en segments a besoin de
    savoir *où* sont les trous. Deux tronçons acceptables séparés par un
    freinage ne forment pas un segment de 1 km d'effort tenu, et une liste
    compactée ne permet plus de le voir.

    Le voisinage se juge sur la liste complète, écartés compris : un tronçon
    régulier coincé entre deux freinages n'est pas un tronçon régulier.

    `stabilite_max` regarde **à l'intérieur** du tronçon (ses deux bouts),
    `delta_v_max` regarde **entre** tronçons voisins : un tronçon peut très
    bien commencer et finir à la même vitesse après avoir freiné puis relancé
    au milieu, et l'inverse aussi. Les deux ensemble valent mieux qu'un seul.
    """
    plancher = reglages.puissance_min_pct * ftp_w
    plafond = reglages.puissance_max_pct * ftp_w if reglages.puissance_max_pct else math.inf
    masque: list[bool] = []
    for i, e in enumerate(bruts):
        garde = (
            e.retenu
            and plancher <= e.puissance_w <= plafond
            and (reglages.pente_max_abs is None or abs(e.pente) <= reglages.pente_max_abs)
            and (reglages.stabilite_max is None or abs(e.v_fin_ms - e.v_debut_ms) <= reglages.stabilite_max)
            and not _saute(bruts, i, reglages.delta_v_max)
        )
        masque.append(garde)
    return masque


def _saute(bruts: Sequence[Echantillon], indice: int, delta_v_max: float) -> bool:
    """Vrai si la vitesse change de plus de `delta_v_max` avec un tronçon voisin."""
    v = bruts[indice].v_ms
    for voisin in (indice - 1, indice + 1):
        if 0 <= voisin < len(bruts) and abs(bruts[voisin].v_ms - v) >= delta_v_max:
            return True
    return False


# --- agrégation en segments de 1 à 2 km ---------------------------------------


def agreger(bruts: Sequence[Echantillon], masque: Sequence[bool], reglages: Reglages) -> list[Echantillon]:
    """Regroupe les tronçons **consécutifs et retenus** en segments de 1 à 2 km stables.

    **Pourquoi ne pas s'en tenir aux 200 m de `echantillonner`.** Le modèle du
    projet ne connaît qu'une vitesse d'équilibre : il n'a ni freinage, ni
    relance, ni inertie autre que le terme cinétique des deux bouts. À deux
    cents mètres, les fluctuations de vitesse et l'inertie pèsent autant que la
    physique qu'on veut mesurer, et le modèle y est le plus faux. Sur un
    kilomètre ou deux d'effort tenu, l'hypothèse d'équilibre redevient
    défendable et le bruit s'écrase — c'est la granularité que le mainteneur a
    demandée, et elle est fondée.

    **Un segment est lui-même un `Echantillon`.** Ses grandeurs sont les
    moyennes pondérées de ses tronçons — par la durée pour ce qui est un flux
    (puissance, vent, masse volumique), par la distance pour la pente, qui est
    un rapport de dénivelé à longueur. Ses vitesses de bout sont celles de ses
    deux extrémités, si bien que le terme cinétique porte sur tout le segment
    et non sur chaque bout de 200 m. L'ajustement qui suit ne sait donc pas
    qu'il travaille sur des segments, et c'est l'intérêt : rien d'autre ne
    change.

    **Un trou coupe le segment.** Un tronçon écarté au milieu, c'est un arrêt,
    un freinage ou un carrefour : coller ce qui l'entoure fabriquerait un
    kilomètre « tenu » qui ne l'a jamais été.
    """
    if reglages.segment_min_m is None:
        return [e for e, garde in zip(bruts, masque, strict=True) if garde]
    return [_fusionner(p) for p in paquets(bruts, masque, reglages) if _stable(p, reglages)]


def paquets(
    bruts: Sequence[Echantillon], masque: Sequence[bool], reglages: Reglages
) -> list[list[Echantillon]]:
    """Les paquets de tronçons candidats à faire un segment, **avant** le filtre de stabilité.

    Exposé pour que le rapport puisse dire combien de segments ont été formés
    et combien la stabilité en a écartés. « 9 segments » tout seul ne dit pas
    si le terrain n'en offrait que 9 ou si 60 ont été jugés trop instables, et
    ces deux situations ne se lisent pas du tout de la même façon.
    """
    formes: list[list[Echantillon]] = []
    for suite in _suites(bruts, masque):
        formes.extend(_decouper_suite(suite, reglages))
    return formes


def _suites(bruts: Sequence[Echantillon], masque: Sequence[bool]) -> list[list[Echantillon]]:
    """Les suites maximales de tronçons consécutifs tous retenus."""
    suites: list[list[Echantillon]] = []
    courante: list[Echantillon] = []
    for e, garde in zip(bruts, masque, strict=True):
        if garde:
            courante.append(e)
        elif courante:
            suites.append(courante)
            courante = []
    if courante:
        suites.append(courante)
    return suites


def _decouper_suite(suite: Sequence[Echantillon], reglages: Reglages) -> list[list[Echantillon]]:
    """Découpe une suite continue en paquets d'au moins `segment_min_m`, sans dépasser le max.

    On avance tant que le paquet n'atteint pas la longueur minimale, puis on
    ferme. Un paquet qui dépasserait `segment_max_m` en ajoutant un tronçon de
    plus est fermé avant : mieux vaut un segment un peu court qu'un segment qui
    mélange deux reliefs. Le reste d'une suite, trop court pour faire un
    segment, est abandonné — il n'y a pas de demi-segment.
    """
    minimum = reglages.segment_min_m or 0.0
    paquets: list[list[Echantillon]] = []
    courant: list[Echantillon] = []
    longueur = 0.0
    for e in suite:
        if courant and longueur + e.longueur_m > reglages.segment_max_m:
            if longueur >= minimum:
                paquets.append(courant)
            courant, longueur = [], 0.0
        courant.append(e)
        longueur += e.longueur_m
        if longueur >= minimum:
            paquets.append(courant)
            courant, longueur = [], 0.0
    return paquets


def _stable(paquet: Sequence[Echantillon], reglages: Reglages) -> bool:
    """Le segment tient-il l'effort ? Vitesse peu dispersée, puissance peu dispersée, pente d'un seul signe.

    Les deux dispersions sont des **coefficients de variation** (écart-type sur
    moyenne) et non des écarts absolus : un segment à 35 km/h et un segment à
    25 km/h n'ont aucune raison de tolérer le même nombre de mètres par seconde
    de flottement.

    La pente ne doit pas s'inverser : un kilomètre qui monte puis descend a une
    pente moyenne nulle et ne ressemble à rien de ce que le modèle simule. La
    bande morte évite de compter le bruit d'un altimètre barométrique sur du
    plat comme un changement de sens.
    """
    if len(paquet) < 2:
        return True
    vitesses = [e.v_ms for e in paquet]
    puissances = [e.puissance_w for e in paquet]
    if _coefficient_variation(vitesses) > reglages.cv_vitesse_max:
        return False
    if _coefficient_variation(puissances) > reglages.cv_puissance_max:
        return False
    bande = reglages.bande_morte_pente
    pentes = [e.pente for e in paquet]
    return not (any(p > bande for p in pentes) and any(p < -bande for p in pentes))


def _coefficient_variation(valeurs: Sequence[float]) -> float:
    """Écart-type sur moyenne. `inf` si la moyenne est nulle ou négative — donc rejeté."""
    moyenne = float(np.mean(valeurs))
    if moyenne <= 0:
        return math.inf
    return float(np.std(valeurs)) / moyenne


def _fusionner(paquet: Sequence[Echantillon]) -> Echantillon:
    """Un segment, à partir de ses tronçons : moyennes pondérées et bouts extrêmes."""
    longueur = sum(e.longueur_m for e in paquet)
    duree = sum(e.duree_s for e in paquet)
    poids = [e.duree_s for e in paquet]
    temperatures = [e.temp_c for e in paquet if math.isfinite(e.temp_c)]
    milieu = paquet[len(paquet) // 2]
    return Echantillon(
        v_ms=longueur / duree if duree > 0 else 0.0,
        puissance_w=_pondere([e.puissance_w for e in paquet], poids),
        # La pente est un dénivelé rapporté à une longueur : elle se pondère
        # par la distance, pas par le temps. Pondérée par le temps, un tronçon
        # lent de montée pèserait plus que sa part de dénivelé.
        pente=sum(e.pente * e.longueur_m for e in paquet) / longueur if longueur > 0 else 0.0,
        vent_face_ms=_pondere([e.vent_face_ms for e in paquet], poids),
        temp_c=float(np.mean(temperatures)) if temperatures else float("nan"),
        retenu=True,
        motif="",
        longueur_m=longueur,
        rho=_pondere([e.rho for e in paquet], poids),
        vent_connu=all(e.vent_connu for e in paquet),
        t=milieu.t,
        dist_m=paquet[-1].dist_m,
        v_debut_ms=paquet[0].v_debut_ms,
        v_fin_ms=paquet[-1].v_fin_ms,
        lat=milieu.lat,
        lon=milieu.lon,
    )


def _pondere(valeurs: Sequence[float], poids: Sequence[float]) -> float:
    total = sum(poids)
    if total <= 0:
        return float(np.mean(valeurs))
    return sum(v * p for v, p in zip(valeurs, poids, strict=True)) / total


def restreindre_plage_commune(
    groupe_a: Sequence[Echantillon], groupe_b: Sequence[Echantillon], pourcentage: float
) -> tuple[list[Echantillon], list[Echantillon], tuple[float, float] | None]:
    """Les deux groupes ramenés à la plage de vitesse qu'ils partagent vraiment.

    Les bornes sont des **centiles**, pas les extrêmes : un seul tronçon à
    45 km/h dans une descente suffirait sinon à déclarer toute la plage
    partagée. La plage rendue est `[max des bas, min des hauts]` ; vide, elle
    vaut `None` et les groupes reviennent intacts — à charge du rapport de dire
    que les deux populations ne se recouvrent pas.
    """
    if not groupe_a or not groupe_b:
        return (list(groupe_a), list(groupe_b), None)
    va = [e.v_ms for e in groupe_a]
    vb = [e.v_ms for e in groupe_b]
    bas = max(float(np.percentile(va, pourcentage)), float(np.percentile(vb, pourcentage)))
    haut = min(float(np.percentile(va, 100 - pourcentage)), float(np.percentile(vb, 100 - pourcentage)))
    if not bas < haut:
        return (list(groupe_a), list(groupe_b), None)
    garde = [e for e in groupe_a if bas <= e.v_ms <= haut]
    gardeb = [e for e in groupe_b if bas <= e.v_ms <= haut]
    return (garde, gardeb, (bas, haut))


def longueur_moyenne_m(echantillons: Sequence[Echantillon]) -> float:
    """Longueur moyenne d'un échantillon, en mètres. Sert à dimensionner les blocs du bootstrap."""
    longueurs = [e.longueur_m for e in echantillons if e.longueur_m > 0]
    return float(np.mean(longueurs)) if longueurs else LONGUEUR_ECHANTILLON_M


def distribution_kmh(echantillons: Sequence[Echantillon]) -> tuple[float, float, float, float, float]:
    """(min, 1ᵉʳ décile, médiane, 9ᵉ décile, max) des vitesses, en km/h."""
    v = np.asarray([e.v_ms * 3.6 for e in echantillons], dtype=float)
    return (
        float(v.min()),
        float(np.percentile(v, 10)),
        float(np.percentile(v, 50)),
        float(np.percentile(v, 90)),
        float(v.max()),
    )


# --- collecte -----------------------------------------------------------------


def collecter(
    cache: Cache,
    config: Config,
    criteres: Sequence[Critere],
    nom: str,
    *,
    client,
    session_sport: str | None,
    session_rang: int | None,
) -> Groupe:
    """Relit les sorties désignées, isole leur session cycliste au besoin, les échantillonne."""
    groupe = Groupe(nom=nom)
    entrees = [e for e in cache.lister() if any(c.correspond(e) for c in criteres)]
    if not entrees:
        raise ErreurUtilisateur(f"{nom} : aucune sortie du cache ne correspond aux critères")
    for entree in sorted(entrees, key=lambda e: (e.debut or datetime.min, e.identifiant)):
        activite = cache.relire(entree.identifiant)
        session = None
        chemin = cache.chemin(entree.identifiant)
        if chemin.suffix.casefold() == ".fit" and (session_sport or session_rang):
            sessions = sessions_fit(chemin)
            if len(sessions) > 1:
                session = choisir_session(sessions, sport=session_sport, rang=session_rang)
                activite = isoler_session(activite, session)
        vent = _archive(activite, client)
        echantillons = echantillonner(activite, vent, ftp_w=config.cycliste.ftp_w)
        groupe.sorties.append(
            Sortie(entree=entree, activite=activite, echantillons=echantillons, session=session)
        )
    return groupe


def _archive(activite: Activite, client) -> list[HeureArchive]:
    """L'archive du jour au point de départ. `[]` sans client, ou si le service n'a rien."""
    if client is None:
        return []
    depart = next((p for p in activite.points if p.lat is not None and p.lon is not None), None)
    if depart is None or activite.debut is None:
        return []
    try:
        return client.horaires(float(depart.lat), float(depart.lon), activite.debut.date())
    except (ErreurConnecteur, ErreurUtilisateur) as e:
        print(f"   (archive météo du {activite.debut.date()} indisponible : {e})")
        return []


def mesurer_aspiration(groupe: Groupe, parametres: Parametres, config: Config, client) -> None:
    """Pose `part_rapide` sur chaque sortie : la part de distance que le modèle n'explique pas.

    C'est `calibration.detecter_groupe`, utilisé ici comme **diagnostic** et
    non comme filtre. Rouler plus vite que la puissance ne le justifie, c'est
    la signature d'une roue à suivre — et c'est mot pour mot la signature d'un
    CdA plus bas. Les deux ne se distinguent pas dans le résidu ; filtrer
    dessus effacerait précisément le gain que ce script cherche.
    """
    for sortie in groupe.sorties:
        _, part = detecter_groupe(
            sortie.activite, parametres, _archive(sortie.activite, client), ftp_w=config.cycliste.ftp_w
        )
        sortie.part_rapide = part


# --- rapport ------------------------------------------------------------------


def decrire_sorties(groupe: Groupe, config: Config) -> None:
    for sortie in groupe.sorties:
        retenus = sum(1 for e in sortie.echantillons if e.retenu)
        session = f" · session {sortie.session.rang} ({sortie.session.intitule})" if sortie.session else ""
        aspiration = (
            f" · {sortie.part_rapide:.0%} de distance inexpliquée" if sortie.part_rapide is not None else ""
        )
        print(
            f"   {sortie.entree.jour} · {sortie.activite.distance_m / 1000:5.1f} km"
            f" · {retenus:4d}/{len(sortie.echantillons)} tronçons"
            f" · {sortie.entree.appareil or 'appareil inconnu'}{session}{aspiration}"
        )
        sans_vent = sum(1 for e in sortie.echantillons if e.retenu and not e.vent_connu)
        if sans_vent:
            print(f"      ({sans_vent} tronçons retenus sans vent archivé, comptés à vent nul)")
        _ = config


def rapporter_variante(
    titre: str,
    groupe_a: Sequence[Echantillon],
    groupe_b: Sequence[Echantillon],
    *,
    masse: float,
    plage: tuple[float, float] | None,
) -> AjustementApparie | None:
    try:
        resultat = ajuster(groupe_a, groupe_b, masse_totale_kg=masse)
    except ErreurUtilisateur as e:
        print(f"   {titre:38s}  impossible — {e}")
        return None
    bornes = f"  ⚠ {', '.join(resultat.bornes_atteintes)}" if resultat.bornes_atteintes else ""
    portee = f" · {plage[0] * 3.6:.0f}–{plage[1] * 3.6:.0f} km/h" if plage else ""
    print(
        f"   {titre:38s}  ΔCdA {resultat.delta_cda:+.4f} m²"
        f"   Crr {resultat.crr:.5f}"
        f"   {resultat.watts(V_REFERENCES_KMH[1]):+5.1f} W à {V_REFERENCES_KMH[1]:.0f}"
        f"   n {resultat.n_a}/{resultat.n_b}{portee}{bornes}"
    )
    return resultat


def main() -> int:
    parseur = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parseur.add_argument(
        "--groupe-a",
        action="append",
        default=[],
        metavar="AAAA-MM-JJ[:NOM]",
        help="sortie du groupe A (position supposée la plus aérodynamique), répétable",
    )
    parseur.add_argument(
        "--groupe-b",
        action="append",
        default=[],
        metavar="AAAA-MM-JJ[:NOM]",
        help="sortie du groupe B (position de référence), répétable",
    )
    parseur.add_argument("--nom-a", default="A", help="étiquette du groupe A dans le rapport")
    parseur.add_argument("--nom-b", default="B", help="étiquette du groupe B dans le rapport")
    parseur.add_argument(
        "--session-sport", default=None, help="sport de la session à isoler dans un FIT multisport"
    )
    parseur.add_argument(
        "--session-rang", type=int, default=None, help="rang (à partir de 1) de la session à isoler"
    )
    parseur.add_argument(
        "--delta-v-max",
        type=float,
        default=DELTA_V_MAX_MS,
        help=f"écart de vitesse toléré avec un tronçon voisin, en m/s (défaut {DELTA_V_MAX_MS})",
    )
    parseur.add_argument(
        "--segment-min-m",
        type=float,
        default=SEGMENT_MIN_M,
        help=f"longueur minimale d'un segment agrégé, en mètres (défaut {SEGMENT_MIN_M:.0f})",
    )
    parseur.add_argument(
        "--segment-max-m",
        type=float,
        default=SEGMENT_MAX_M,
        help=f"longueur maximale d'un segment agrégé, en mètres (défaut {SEGMENT_MAX_M:.0f})",
    )
    parseur.add_argument(
        "--sans-agregation",
        action="store_true",
        help="garder les tronçons d'environ 200 m au lieu de les agréger en segments",
    )
    parseur.add_argument(
        "--cv-vitesse-max",
        type=float,
        default=CV_VITESSE_MAX,
        help=f"dispersion de vitesse tolérée dans un segment (défaut {CV_VITESSE_MAX})",
    )
    parseur.add_argument(
        "--cv-puissance-max",
        type=float,
        default=CV_PUISSANCE_MAX,
        help=f"dispersion de puissance tolérée dans un segment (défaut {CV_PUISSANCE_MAX})",
    )
    parseur.add_argument(
        "--stabilite-max",
        type=float,
        default=None,
        help="écart de vitesse toléré entre les deux bouts d'un même tronçon, en m/s",
    )
    parseur.add_argument(
        "--pente-max-abs",
        type=float,
        default=None,
        help="pente absolue maximale d'un tronçon (0.01 = 1 %%), appliquée aux deux groupes",
    )
    parseur.add_argument(
        "--puissance-min-pct", type=float, default=0.0, help="plancher de puissance, en fraction de FTP"
    )
    parseur.add_argument(
        "--puissance-max-pct", type=float, default=None, help="plafond de puissance, en fraction de FTP"
    )
    parseur.add_argument(
        "--plage-commune",
        action="store_true",
        help="restreindre les deux groupes à leur plage de vitesse commune",
    )
    parseur.add_argument("--plage-commune-pct", type=float, default=5.0, help="centile des bornes de plage")
    parseur.add_argument(
        "--bootstrap", type=int, default=REPETITIONS_BOOTSTRAP, help="répétitions du bootstrap"
    )
    parseur.add_argument(
        "--bloc",
        type=int,
        default=None,
        help="échantillons par bloc du bootstrap (défaut : de quoi faire environ "
        f"{BLOC_BOOTSTRAP_M / 1000:.0f} km)",
    )
    parseur.add_argument("--graine", type=int, default=12345, help="graine du bootstrap")
    parseur.add_argument("--sans-vent", action="store_true", help="aucun appel réseau : vent compté nul")
    parseur.add_argument("--config", default=None, help="fichier de configuration")
    args = parseur.parse_args()

    if not args.groupe_a or not args.groupe_b:
        raise SystemExit("il faut au moins un --groupe-a et un --groupe-b")

    config = charger(args.config)
    cache = Cache(Path(config.cache.dossier).expanduser())
    client = None
    if not args.sans_vent:
        from ourouler.connecteurs.openmeteo_archive import ClientArchive
        from ourouler.physique.commande import NOM_CACHE

        client = ClientArchive(chemin_cache=Path(config.cache.dossier).expanduser() / NOM_CACHE)

    criteres_a = [Critere.depuis_texte(t) for t in args.groupe_a]
    criteres_b = [Critere.depuis_texte(t) for t in args.groupe_b]
    groupe_a = collecter(
        cache,
        config,
        criteres_a,
        args.nom_a,
        client=client,
        session_sport=args.session_sport,
        session_rang=args.session_rang,
    )
    groupe_b = collecter(
        cache, config, criteres_b, args.nom_b, client=client, session_sport=None, session_rang=None
    )

    velo = _velo_commun(groupe_a, groupe_b, config)
    masse = masse_totale_kg(config, velo)
    _diagnostiquer_aspiration(groupe_a, groupe_b, config, velo, client)

    print(
        f"\nVélo : {velo.nom} ({velo.usage}) · masse totale {masse:.0f} kg "
        f"· FTP {config.cycliste.ftp_w:.0f} W"
    )
    if client is not None:
        print(f"Archives météo : {client.appels} appel(s), {client.lectures_cache} déjà en cache")
    else:
        print("Archives météo : aucune (--sans-vent) — le vent est compté nul partout")
    for groupe in (groupe_a, groupe_b):
        print(f"\nGroupe {groupe.nom} — {len(groupe.sorties)} sortie(s)")
        decrire_sorties(groupe, config)

    reglages = Reglages(
        segment_min_m=None if args.sans_agregation else args.segment_min_m,
        segment_max_m=args.segment_max_m,
        cv_vitesse_max=args.cv_vitesse_max,
        cv_puissance_max=args.cv_puissance_max,
        delta_v_max=args.delta_v_max,
        stabilite_max=args.stabilite_max,
        pente_max_abs=args.pente_max_abs,
        puissance_min_pct=args.puissance_min_pct,
        puissance_max_pct=args.puissance_max_pct,
        plage_commune=args.plage_commune,
        plage_commune_pct=args.plage_commune_pct,
    )
    a, b, plage = _preparer(groupe_a, groupe_b, reglages, config)
    if not a or not b:
        raise SystemExit("aucun tronçon retenu dans l'un des deux groupes — desserrer les filtres")

    ftp = config.cycliste.ftp_w
    unite = "tronçons" if reglages.segment_min_m is None else "segments"
    if reglages.segment_min_m is not None:
        print(
            f"\nAgrégation en segments de {reglages.segment_min_m / 1000:.1f} à "
            f"{reglages.segment_max_m / 1000:.1f} km, dispersion tolérée "
            f"{reglages.cv_vitesse_max:.0%} en vitesse et {reglages.cv_puissance_max:.0%} en puissance"
        )
        for groupe, echantillons in ((groupe_a, a), (groupe_b, b)):
            longueurs = sorted(e.longueur_m for e in echantillons)
            formes = sum(
                len(paquets(s.echantillons, survivants(s.echantillons, reglages, ftp_w=ftp), reglages))
                for s in groupe.sorties
            )
            print(
                f"   {groupe.nom:3s} {len(longueurs)} segments gardés sur {formes} formés · "
                f"{longueurs[0] / 1000:.1f} … {longueurs[-1] / 1000:.1f} km (médiane "
                f"{longueurs[len(longueurs) // 2] / 1000:.1f}) · "
                f"{sum(longueurs) / 1000:.1f} km au total"
            )

    print(f"\nDistribution de vitesse des {unite} retenus (min · d1 · médiane · d9 · max, km/h)")
    for nom, echantillons in ((groupe_a.nom, a), (groupe_b.nom, b)):
        mini, d1, med, d9, maxi = distribution_kmh(echantillons)
        print(
            f"   {nom:3s} {mini:5.1f} · {d1:5.1f} · {med:5.1f} · {d9:5.1f} · {maxi:5.1f}"
            f"   ({len(echantillons)} {unite})"
        )
    if plage:
        print(f"   plage commune appliquée : {plage[0] * 3.6:.1f} – {plage[1] * 3.6:.1f} km/h")
    elif reglages.plage_commune:
        print("   ⚠ aucune plage commune : les deux populations ne se recouvrent pas")

    resultat = ajuster(a, b, masse_totale_kg=masse)
    _rapporter(resultat, groupe_a.nom, groupe_b.nom, unite)

    if args.bootstrap > 0:
        bloc = args.bloc or max(1, round(BLOC_BOOTSTRAP_M / longueur_moyenne_m(a + b)))
        deltas = bootstrap_delta(
            a, b, masse_totale_kg=masse, repetitions=args.bootstrap, bloc=bloc, graine=args.graine
        )
        _rapporter_bootstrap(deltas, resultat, bloc, longueur_moyenne_m(a + b))

    print("\nSensibilité aux filtres — c'est l'écart entre ces lignes qui dit si la mesure tranche")
    for titre, ajouts in VARIANTES:
        variante = replace(reglages, **ajouts)
        va, vb, vplage = _preparer(groupe_a, groupe_b, variante, config)
        if not va or not vb:
            print(f"   {titre:38s}  aucun tronçon retenu")
            continue
        rapporter_variante(titre, va, vb, masse=masse, plage=vplage)
    return 0


def _velo_commun(groupe_a: Groupe, groupe_b: Groupe, config: Config) -> Velo:
    """Le vélo auquel **toutes** les sorties se rattachent. Lève si elles n'en partagent pas un.

    Toute la méthode repose sur « même vélo, mêmes roues, mêmes pneus » : si le
    rattachement dit deux vélos, le Crr commun n'a plus aucune raison d'être
    commun, et le ΔCdA rendu serait un chiffre sans signification.
    """
    noms = {
        rattacher_velo(sortie.entree, config) for groupe in (groupe_a, groupe_b) for sortie in groupe.sorties
    }
    if len(noms) != 1:
        raise SystemExit(
            f"les sorties se rattachent à {sorted(noms)} : la méthode exige un seul et même vélo"
        )
    nom = noms.pop()
    for velo in config.velos:
        if velo.nom == nom:
            return velo
    raise SystemExit(f"« {nom} » n'est pas un vélo de la configuration : aucune masse à lui donner")


def _diagnostiquer_aspiration(groupe_a: Groupe, groupe_b: Groupe, config: Config, velo: Velo, client) -> None:
    """Pose la part de distance inexpliquée, avec les paramètres déjà calibrés du vélo.

    Import tardif : `physique.commande` lit la configuration et le fichier de
    calibration, ce qui n'a rien à faire dans l'en-tête d'un script qui doit
    aussi pouvoir tourner sans eux.
    """
    from ourouler.physique.commande import chemin_calibration, parametres_du_velo

    try:
        parametres, _ = parametres_du_velo(config, velo, chemin_calibration(config))
    except (ErreurUtilisateur, OSError) as e:
        print(f"(pas de diagnostic d'aspiration : {e})")
        return
    for groupe in (groupe_a, groupe_b):
        mesurer_aspiration(groupe, parametres, config, client)


def _preparer(
    groupe_a: Groupe, groupe_b: Groupe, reglages: Reglages, config: Config
) -> tuple[list[Echantillon], list[Echantillon], tuple[float, float] | None]:
    """Applique les mêmes filtres aux deux groupes, agrège, puis restreint la plage commune.

    L'agrégation se fait **sortie par sortie** : deux sorties bout à bout ne
    forment évidemment pas un segment continu, et les concaténer avant de
    découper collerait la fin d'un mars au début d'un septembre.
    """
    a = [e for sortie in groupe_a.sorties for e in _segments(sortie, reglages, config)]
    b = [e for sortie in groupe_b.sorties for e in _segments(sortie, reglages, config)]
    if reglages.plage_commune:
        return restreindre_plage_commune(a, b, reglages.plage_commune_pct)
    return (a, b, None)


def _segments(sortie: Sortie, reglages: Reglages, config: Config) -> list[Echantillon]:
    """Les segments exploitables d'une sortie : filtres de tronçon, puis agrégation."""
    masque = survivants(sortie.echantillons, reglages, ftp_w=config.cycliste.ftp_w)
    return agreger(sortie.echantillons, masque, reglages)


def _rapporter(resultat: AjustementApparie, nom_a: str, nom_b: str, unite: str) -> None:
    print("\nAjustement à trois paramètres — Crr forcé commun, un CdA par groupe")
    sigma_a = f" ± {resultat.ecart_type_cda_a:.4f}" if resultat.ecart_type_cda_a else ""
    sigma_b = f" ± {resultat.ecart_type_cda_b:.4f}" if resultat.ecart_type_cda_b else ""
    print(f"   CdA {nom_a:3s} {resultat.cda_a:.4f} m²{sigma_a}   sur {resultat.n_a} {unite}")
    print(f"   CdA {nom_b:3s} {resultat.cda_b:.4f} m²{sigma_b}   sur {resultat.n_b} {unite}")
    print(f"   Crr commun {resultat.crr:.5f}")
    sigma = (
        f"   (± {resultat.ecart_type_delta:.4f} en supposant les tronçons indépendants — optimiste)"
        if resultat.ecart_type_delta
        else ""
    )
    print(f"\n   ΔCdA = {resultat.delta_cda:+.4f} m²{sigma}")
    for v in V_REFERENCES_KMH:
        print(f"   à {v:.0f} km/h, à plat, sans vent : {resultat.watts(v):+.1f} W")
    if resultat.libre is not None and resultat.bornes_atteintes:
        cda_a, cda_b, crr = resultat.libre
        print(
            f"\n   sans les bornes, l'ajustement voudrait poser "
            f"CdA {nom_a} = {cda_a:.4f}, CdA {nom_b} = {cda_b:.4f}, Crr = {crr:.5f}"
            f"\n   (ΔCdA libre {cda_a - cda_b:+.4f} m² — à lire comme la mesure d'un désaccord "
            "entre les deux groupes,\n    pas comme un CdA)"
        )
    print(f"\n   RMSE {resultat.rmse_w:.1f} W · MAE {resultat.mae_w:.1f} W")
    for avertissement in resultat.avertissements:
        print(f"   ⚠ {avertissement}")
    for borne in resultat.bornes_atteintes:
        print(f"   ⚠ borne atteinte : {borne}")


def _rapporter_bootstrap(
    deltas: list[float], resultat: AjustementApparie, bloc: int, longueur_m: float
) -> None:
    if len(deltas) < 20:
        print(f"\nBootstrap par blocs : {len(deltas)} répétitions abouties — trop peu pour conclure")
        return
    bas = deltas[int(0.05 * len(deltas))]
    haut = deltas[min(int(0.95 * len(deltas)), len(deltas) - 1)]
    print(
        f"\nBootstrap par blocs ({len(deltas)} répétitions, blocs de {bloc} tronçons ≈ "
        f"{bloc * longueur_m / 1000:.0f} km) — l'intervalle à lire"
    )
    print(f"   ΔCdA           {bas:+.4f} … {haut:+.4f} m²   (90 %)")
    faux = replace(resultat, cda_a=resultat.cda_b + bas)
    vrai = replace(resultat, cda_a=resultat.cda_b + haut)
    for v in V_REFERENCES_KMH:
        print(f"   à {v:.0f} km/h    {faux.watts(v):+6.1f} … {vrai.watts(v):+6.1f} W")
    if bas < 0 < haut:
        print("   ⚠ l'intervalle contient zéro : ces données ne montrent pas d'écart de CdA")


if __name__ == "__main__":
    sys.exit(main())
