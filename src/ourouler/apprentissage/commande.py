"""Sous-commande `ourouler routes` : apprendre, regarder, pondérer.

Cas d'usage entre l'entrée (`commandes/routes.py`, qui lit argparse) et
`apprentissage.routes`. C'est **ici** que les chemins se composent
(`contexte.dossier_cache / …`) et que les clients se créent : le cœur, lui,
reçoit des objets déjà faits. Le texte et le JSON sont dans `rendu/routes.py`.

Trois actions :

* `apprendre` rejoue les sorties extérieures du cache dans BRouter — un appel
  par sortie, idempotent, on peut relancer sans compter ;
* `stats` montre ce que le cycliste roule vraiment, par classe de route ;
* `poids` génère huit boucles de 40 km autour du départ pour mesurer ce que le
  moteur **propose** (l'exposition, élaguée de ses antennes comme les
  candidates de `boucle`), le compare à ce qu'il **prend**, et rend les poids
  appris — écrits dans `poids_routes.json` avec `--appliquer`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

from ourouler.activites.cache import Cache
from ourouler.apprentissage.routes import (
    BaseRoutes,
    RapportApprentissage,
    Statistiques,
    apprendre,
    ecrire_poids,
    lire_poids,
    poids_appris,
    statistiques_de_traces,
)
from ourouler.boucle.antennes import detecter, elaguer
from ourouler.connecteurs.brouter import ClientBrouter
from ourouler.meteo.couronne import NOMS_DIRECTIONS, azimut_de
from ourouler.noyau.erreurs import ErreurConnecteur, ErreurUtilisateur
from ourouler.noyau.profil import Profil
from ourouler.noyau.trace import Trace
from ourouler.services.contexte import Contexte

#: Nom du fichier de base des routes connues, sous le dossier de cache. Il vit
#: ici et non dans `apprentissage/routes.py` : le cœur reçoit un `Path` déjà
#: résolu, il ne fabrique pas le nom du fichier (règle absolue 2 de CLAUDE.md,
#: contrat du sprint 3 §2). `boucle/commande.py` le lit ici aussi.
NOM_BASE = "routes_connues.sqlite"

#: Nom du fichier de poids appris, sous le dossier de cache. Même raison.
NOM_POIDS = "poids_routes.json"

#: Distance des boucles d'exposition, en kilomètres. Assez long pour sortir de
#: l'agglomération et rencontrer les mêmes classes de routes qu'une vraie
#: sortie, assez court pour que huit appels restent une affaire de secondes.
DISTANCE_EXPOSITION_KM = 40.0

#: Rapport entre la longueur d'une boucle BRouter et le rayon demandé, mesuré
#: sur le serveur réel (voir `boucle.candidates`). L'exposition se lit en
#: **parts** : quelques kilomètres d'écart sur la longueur ne changent rien.
RAPPORT_RAYON = 5.0

#: Ce qu'on affiche à la place d'une mesure absente.
ABSENT = "—"

ACTIONS = ("apprendre", "stats", "poids")


@dataclass(frozen=True)
class DemandeRoutes:
    """L'action demandée, et ses options déjà interprétées par l'entrée (`commandes/routes.py`)."""

    action: str
    #: `apprendre` : depuis quand rejouer les sorties (le début de l'historique par défaut).
    depuis: date | None = None
    max_sorties: int | None = None
    #: `poids` : écrire les poids dans `poids_routes.json`, ou seulement les montrer.
    appliquer: bool = False


@dataclass(frozen=True)
class ResultatApprentissage:
    rapport: RapportApprentissage
    depuis: date
    #: L'état de la base **après** l'apprentissage.
    stats: Statistiques


@dataclass(frozen=True)
class ResultatStats:
    stats: Statistiques
    appris: dict[str, float] | None


@dataclass(frozen=True)
class ResultatPoids:
    stats: Statistiques
    exposition: Statistiques
    poids: dict[str, float]
    echecs: list[str]
    #: Là où les poids ont été écrits, ou `None` sans `--appliquer`.
    ecrit_dans: Path | None


def valider_action(action: str | None) -> str:
    if action not in ACTIONS:
        raise ErreurUtilisateur(
            f"routes : préciser une action — {', '.join(ACTIONS)} "
            "(`ourouler routes apprendre` rejoue vos sorties dans BRouter)"
        )
    return action


def executer(
    demande: DemandeRoutes,
    contexte: Contexte,
    client_brouter: ClientBrouter | None = None,
    base: BaseRoutes | None = None,
) -> ResultatApprentissage | ResultatStats | ResultatPoids:
    """Exécute `ourouler routes <action>`.

    **`base` s'injecte, comme `client_brouter` juste au-dessus.** Absente — le
    cas de la ligne de commande — le service la construit sur
    `contexte.dossier_cache` et avec le propriétaire par défaut.

    C'est ce qui ferme [[Q58]] sans faire entrer la notion de service dans le
    cœur : le service reçoit un dépôt déjà fait et ne prononce jamais le mot
    « propriétaire ». Voir `activites/commande.executer` pour le raisonnement
    complet et la phrase de doctrine §10.1 qui le porte.
    """
    action = valider_action(demande.action)
    base = base if base is not None else BaseRoutes(contexte.dossier_cache / NOM_BASE)
    if action == "apprendre":
        return _apprendre(demande, contexte, base, client_brouter)
    if action == "stats":
        return ResultatStats(
            stats=base.statistiques(), appris=lire_poids(contexte.dossier_cache / NOM_POIDS)
        )
    return _poids(demande, contexte, base, client_brouter)


def _client(profil: Profil, client_brouter: ClientBrouter | None) -> ClientBrouter:
    if client_brouter is not None:
        return client_brouter
    if not profil.brouter.renseigne:
        raise ErreurUtilisateur(
            "routes : [brouter] url n'est pas renseigné dans la configuration — "
            "y mettre l'adresse du serveur BRouter"
        )
    return ClientBrouter(profil.brouter, evitements=profil.evitements)


# --- apprendre ----------------------------------------------------------------


def _apprendre(
    demande: DemandeRoutes,
    contexte: Contexte,
    base: BaseRoutes,
    client_brouter: ClientBrouter | None,
) -> ResultatApprentissage:
    depuis = demande.depuis or contexte.profil.historique_depuis
    # Pas de dépôt injecté ici, contrairement à `base` : `apprendre` est une
    # action d'administration que l'API n'expose pas (`api/routes/inventaire.py` n'accepte
    # que `stats` et `poids`), donc ce `Cache` n'est jamais construit pour le
    # compte d'un demandeur. Le jour où une route l'exposerait, c'est ce
    # constructeur-là qu'il faudrait injecter — [[Q58]].
    cache = Cache(contexte.dossier_cache)
    client = _client(contexte.profil, client_brouter)
    rapport = apprendre(cache, client, base, depuis=depuis, max_sorties=demande.max_sorties)
    return ResultatApprentissage(rapport=rapport, depuis=depuis, stats=base.statistiques())


# --- poids --------------------------------------------------------------------


def _poids(
    demande: DemandeRoutes,
    contexte: Contexte,
    base: BaseRoutes,
    client_brouter: ClientBrouter | None,
) -> ResultatPoids:
    stats = base.statistiques()
    if stats.km_total <= 0:
        raise ErreurUtilisateur(
            "routes poids : aucune route apprise — lancer d'abord "
            "`ourouler routes apprendre`"
        )
    client = _client(contexte.profil, client_brouter)
    traces, echecs = _boucles_exposition(client, contexte.profil)
    exposition = statistiques_de_traces(traces)
    poids = poids_appris(stats, exposition if traces else None)

    chemin = contexte.dossier_cache / NOM_POIDS
    if demande.appliquer:
        ecrire_poids(
            chemin,
            poids,
            meta={
                "sorties_apprises": stats.sorties,
                "km_appris": round(stats.km_total, 1),
                "boucles_exposition": len(traces),
                "km_exposition": round(exposition.km_total, 1),
            },
        )
    return ResultatPoids(
        stats=stats,
        exposition=exposition,
        poids=poids,
        echecs=echecs,
        ecrit_dans=chemin if demande.appliquer else None,
    )


def _boucles_exposition(client: ClientBrouter, profil: Profil) -> tuple[list[Trace], list[str]]:
    """Une boucle de 40 km par direction : ce que le moteur **propose** au départ.

    Chaque réponse est **élaguée de ses antennes**, exactement comme
    `boucle.candidates.generer` le fait : l'exposition doit mesurer ce que
    `ourouler boucle` proposera vraiment, pas ce que le moteur rend avant
    élagage. Sans cela, les deux parts du rapport
    `log2(part exposition / part sorties)` ne décrivent pas la même chose, et
    l'écart n'est pas réparti au hasard — les culs-de-sac sont parcourus à
    60-70 % sur `track` et `unclassified` (voir `boucle.antennes`), c'est-à-dire
    sur les classes marginales où le logarithme amplifie déjà le bruit.

    Une direction qui échoue n'annule pas la mesure : on compte l'échec et on
    continue. Comparer sept directions vaut mieux que ne rien comparer — mais
    le nombre de boucles est affiché, pour qu'on sache sur quoi repose le
    chiffre (règle absolue 5).
    """
    traces: list[Trace] = []
    echecs: list[str] = []
    rayon = DISTANCE_EXPOSITION_KM * 1000.0 / RAPPORT_RAYON
    for nom in NOMS_DIRECTIONS:
        try:
            trace = client.boucle(
                (profil.depart.latitude, profil.depart.longitude),
                azimut_deg=azimut_de(nom),
                rayon_m=rayon,
                profil=profil.brouter.profil,
            )
            traces.append(elaguer(trace, detecter(trace)))
        except ErreurConnecteur as e:
            echecs.append(f"{nom} : {e}")
    return (traces, echecs)


def date_depuis(brut: str | None) -> date | None:
    """`--depuis` en date ; `None` s'il est absent (le service prend alors le début de l'historique)."""
    if not brut:
        return None
    try:
        return date.fromisoformat(brut)
    except ValueError as e:
        raise ErreurUtilisateur(f"--depuis : date AAAA-MM-JJ attendue, reçu « {brut} »") from e
