"""Comment l'API appelle le cœur — et pourquoi elle l'appelle comme la CLI.

Doctrine §10.2 : « L'API expose ce que la CLI sait déjà rendre en JSON. »
Prise au mot, cette phrase interdit une deuxième implémentation. L'API
construit donc le même `argparse.Namespace` que la ligne de commande,
appelle la **même** fonction `executer(args, config, …)` avec `json=True`, et
rend le JSON qu'elle imprime. Aucune divergence possible : ce que le
mainteneur vérifie en ligne de commande est exactement ce que le front reçoit.

**Le prix, et il est réel.** `executer` imprime sur la sortie standard, qui
est un objet de processus, pas de fil d'exécution : deux commandes qui
tourneraient en même temps se mélangeraient. D'où le verrou ci-dessous, et
la réponse `calcul_en_cours` quand une deuxième requête coûteuse arrive
pendant qu'une première travaille. Pour un service dont le poste dominant
est de toute façon BRouter et Open-Meteo, sérialiser n'est pas une perte ;
c'est même ce qui rend la durée annoncée au front honnête.

**Ce que l'API ajoute, et que la CLI n'avait pas.** Les avertissements du
cœur (« second avis indisponible », « météo indisponible — le placement
reste valable », « départ géocodé ») partent sur la sortie d'erreur : un
humain les lit, un front ne les voit jamais. Ils sont capturés ici et rendus
dans `avertissements`. C'est le seul enrichissement ; les données, elles,
sont celles de la CLI, intactes.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import threading
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

from ourouler.api.erreurs import ErreurApi, assainir, classer

#: Un seul calcul du cœur à la fois par processus (voir le module).
_VERROU = threading.Lock()

#: Combien de temps une requête attend son tour avant d'abandonner. Plus long
#: que la génération la plus lente mesurée (6,0 s) : deux requêtes qui se
#: suivent doivent passer, dix qui s'empilent doivent être refusées vite et
#: proprement plutôt que de faire patienter le front sans rien dire.
DELAI_ATTENTE_S = 15.0

#: Le préfixe que le cœur met devant ses avertissements sur la sortie
#: d'erreur. Retiré avant de les rendre : le front n'affiche pas le nom du
#: programme dans une bulle d'alerte.
PREFIXE_AVERTISSEMENT = "ourouler : "


@dataclass(frozen=True)
class Resultat:
    """Ce qu'une commande a rendu, plus ce qu'elle a marmonné en chemin."""

    donnees: dict
    avertissements: tuple[str, ...] = ()
    duree_ms: int = 0

    def enveloppe(self, budget: dict | None = None, proprietaire: object | None = None) -> dict:
        """La forme que toute route de calcul rend au front.

        `proprietaire` **nomme qui a été servi**. Tant qu'il n'y a qu'une
        identité, la rattacher implicitement « marche » ; le jour où il y en a
        deux, ce défaut devient une fuite, et il est réparti dans toutes les
        routes. Une réponse qui dit pour qui elle a été calculée rend l'oubli
        visible au lieu de le rendre confortable, et donne au front de quoi
        refuser d'afficher les données de quelqu'un d'autre (doctrine §10.2).
        """
        charge: dict = {}
        if proprietaire is not None:
            charge["proprietaire"] = str(proprietaire)
        charge["donnees"] = self.donnees
        charge["avertissements"] = list(self.avertissements)
        charge["duree_ms"] = self.duree_ms
        if budget is not None:
            charge["budget"] = budget
        return charge


def namespace(**champs) -> argparse.Namespace:
    """Le `Namespace` qu'aurait produit `argparse`, avec `--json` toujours posé.

    Les commandes lisent leurs options par `getattr(args, nom, défaut)` : un
    champ absent vaut donc son défaut de ligne de commande, et il n'y a rien
    à recopier des déclarations d'`argparse`.
    """
    champs.setdefault("json", True)
    return argparse.Namespace(**champs)


def executer_commande(
    fonction: Callable[..., int],
    args: argparse.Namespace,
    config,
    *,
    secrets: Iterable[str] = (),
    operation: str = "",
    budgets: Budgets | None = None,
    **clients,
) -> Resultat:
    """Appelle une commande du cœur et rend son JSON, ses avertissements, sa durée.

    Toute exception du cœur est traduite en `ErreurApi` (voir `erreurs.py`) :
    une trace Python ne sort jamais d'ici.
    """
    sortie, erreurs = io.StringIO(), io.StringIO()
    if not _VERROU.acquire(timeout=DELAI_ATTENTE_S):
        raise ErreurApi(
            code="calcul_en_cours",
            message="un calcul est déjà en cours sur ce serveur — réessayer dans quelques "
            "secondes ; une génération prend de 4 à 6 secondes",
            statut=409,
        )
    # Chronométré **après** l'attente du verrou : la durée rendue est celle du
    # calcul, sinon le budget annoncé au front grossirait à chaque file
    # d'attente au lieu de décrire le travail.
    debut = time.perf_counter()
    try:
        with contextlib.redirect_stdout(sortie), contextlib.redirect_stderr(erreurs):
            code = fonction(args, config, **clients)
    except Exception as e:  # traduit, jamais propagé tel quel
        raise classer(e, secrets=secrets) from e
    finally:
        _VERROU.release()
    duree_ms = int((time.perf_counter() - debut) * 1000)

    if code != 0:  # pragma: no cover - les commandes lèvent, elles ne rendent pas de code
        raise ErreurApi(
            code="erreur_interne",
            message=f"la commande a rendu le code {code} sans lever d'erreur",
            statut=500,
        )
    brut = sortie.getvalue()
    try:
        donnees = json.loads(brut)
    except json.JSONDecodeError as e:  # pragma: no cover - `--json` est toujours posé
        raise ErreurApi(
            code="erreur_interne",
            message="la commande n'a pas rendu de JSON",
            statut=500,
        ) from e
    if operation and budgets is not None:
        budgets.noter(operation, duree_ms)
    return Resultat(
        donnees=donnees,
        avertissements=avertissements_de(erreurs.getvalue(), secrets),
        duree_ms=duree_ms,
    )


def avertissements_de(flux: str, secrets: Iterable[str] = ()) -> tuple[str, ...]:
    """Les lignes de la sortie d'erreur, nettoyées de leur préfixe et des secrets."""
    lignes = []
    for ligne in flux.splitlines():
        texte = ligne.strip()
        if not texte:
            continue
        lignes.append(assainir(texte.removeprefix(PREFIXE_AVERTISSEMENT), secrets))
    return tuple(lignes)


#: Ce qu'une opération est censée coûter, en millisecondes, **tant qu'aucune
#: mesure locale n'existe**. Ces chiffres viennent des mesures du 16/09/2026
#: rapportées dans `docs/ux/cycle_ux_contrat.md` (décision 6) : 3,8 à 6,0 s
#: pour une sortie complète. Ils sont marqués « defaut » dans la réponse tant
#: qu'ils ne sont pas remplacés par ce que ce serveur-ci a réellement mesuré
#: — règle absolue 5 : on ne fait pas passer une estimation pour une mesure.
BUDGETS_DEFAUT_MS = {
    "sortie": 6000,
    "boucle": 5000,
    "meteo": 2000,
    "seances": 1500,
    "seance": 1500,
    "geocodage": 800,
    "inventaire": 1000,
}


@dataclass
class Budgets:
    """Combien de temps chaque opération prend **sur ce serveur**.

    Décision 6 du cycle UX : « asynchrone ou semi-synchrone en précisant que
    ça prend X secondes », et « X doit être mesuré, pas inventé ». Le front a
    besoin d'un chiffre **avant** de lancer le calcul pour animer son attente ;
    ce registre le lui donne, et dit d'où il vient : `defaut` tant que ce
    serveur n'a rien mesuré, `mesure` dès la première exécution réussie.

    En mémoire, et c'est assez : le budget sert à peindre une barre de
    progression, pas à facturer. Un redémarrage repart des valeurs par défaut.
    """

    #: Combien d'exécutions récentes on garde par opération. Court exprès :
    #: un serveur qu'on vient de rapprocher de son BRouter doit le montrer en
    #: quelques requêtes, pas au bout de cent.
    fenetre: int = 10
    _mesures: dict[str, list[int]] = field(default_factory=dict)

    def noter(self, operation: str, duree_ms: int) -> None:
        mesures = self._mesures.setdefault(operation, [])
        mesures.append(int(duree_ms))
        del mesures[: -self.fenetre]

    def budget(self, operation: str) -> dict:
        """Ce qu'on annonce au front pour cette opération."""
        mesures = self._mesures.get(operation) or []
        if mesures:
            # La plus lente des mesures récentes, pas la moyenne : une barre
            # qui finit avant le calcul est pire qu'une barre un peu lente.
            return {
                "operation": operation,
                "attendu_ms": max(mesures),
                "source": "mesure",
                "n": len(mesures),
                "median_ms": sorted(mesures)[len(mesures) // 2],
            }
        return {
            "operation": operation,
            "attendu_ms": BUDGETS_DEFAUT_MS.get(operation, 5000),
            "source": "defaut",
            "n": 0,
            "median_ms": None,
        }

    def tous(self) -> list[dict]:
        operations = sorted(set(BUDGETS_DEFAUT_MS) | set(self._mesures))
        return [self.budget(operation) for operation in operations]


__all__ = [
    "BUDGETS_DEFAUT_MS",
    "DELAI_ATTENTE_S",
    "Budgets",
    "Resultat",
    "avertissements_de",
    "executer_commande",
    "namespace",
]
