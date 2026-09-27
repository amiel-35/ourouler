"""Le double chemin : l'ancien (la CLI capturée), le nouveau (service et rendu).

L'API cesse d'appeler la ligne de commande. Le risque est de changer, sans le voir, ce que le front reçoit ;
d'où trois modes, choisis au démarrage par `OUROULER_API_CHEMIN`
(`api/exploitation.py`, le seul endroit qui lit l'environnement) :

- `ancien` — l'adaptateur (`api/adaptateur.py`) : `argparse.Namespace`,
  sortie standard capturée, verrou global. **Le défaut** ;
- `nouveau` — `api/calculs.py` : la demande, le service, le rendu JSON ;
  ni `Namespace`, ni capture, ni verrou ;
- `double` — les deux tournent, l'ancien d'abord ; **l'ancien répond**, et
  toute différence de statut ou de corps est journalisée en une ligne
  structurée (`ecart_double_chemin {…}`), sans valeur : des chemins de clés,
  des codes, des statuts — jamais un message, une adresse ou un jeton.

Ce que le mode `double` coûte, et qu'il faut savoir avant de le poser en
préproduction : chaque calcul est fait **deux fois** (deux fois les appels
à BRouter et Open-Meteo, deux fois la durée) ; les fichiers qu'une
génération écrit (carte, GPX) sont réécrits à l'identique par le second
passage. Un écart peut aussi venir de l'horloge (une météo « à l'heure
courante » demandée à cheval sur deux heures) : il se lit dans la ligne.
"""

from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import Callable, Iterable, Mapping
from typing import Any

from ourouler.api.adaptateur import (
    Budgets,
    Resultat,
    avertissements_de,
    executer_commande,
    namespace,
)
from ourouler.api.erreurs import ErreurApi, classer, secrets_de
from ourouler.config import Config

CHEMIN_ANCIEN = "ancien"
CHEMIN_NOUVEAU = "nouveau"
CHEMIN_DOUBLE = "double"
CHEMINS = (CHEMIN_ANCIEN, CHEMIN_NOUVEAU, CHEMIN_DOUBLE)

#: Le chemin d'une application construite sans en nommer un
#: (`creer_application(chemin_api=None)`). **`ancien` pour ce lot** : la
#: bascule se fait en préproduction, par `double` d'abord.
CHEMIN_DEFAUT = CHEMIN_ANCIEN

#: Le journal des écarts. Une ligne par requête qui diverge, au niveau
#: `WARNING` : c'est ce qu'on lit en préproduction avant de basculer.
journal = logging.getLogger("ourouler.api.double_chemin")

#: Au-delà, la liste des clés qui diffèrent est tronquée : la ligne dit
#: qu'il y a un écart et où il commence, pas l'inventaire complet.
ECARTS_MAX = 20


def executer_service(
    travail: Callable[[Callable[[str], None]], dict],
    *,
    secrets: Iterable[str] = (),
    chemins: Mapping[str, str] | None = None,
    operation: str = "",
    budgets: Budgets | None = None,
) -> Resultat:
    """Le nouveau chemin : `travail(avertir)` rend le JSON, `avertir` recueille les avertissements.

    Mêmes garanties que `adaptateur.executer_commande`, sans ce qu'elle a de
    processus : toute exception est traduite par `erreurs.classer` (une trace
    Python ne sort jamais d'ici), chemins et secrets sont masqués dans
    l'erreur **et** dans les avertissements, la durée est celle du calcul.

    **Le JSON repasse par `json.dumps`/`json.loads`**, comme l'ancien chemin
    le lisait sur la sortie standard : un rendu qui contiendrait un tuple, une
    clé entière ou un objet sérialisable seulement par `json` rendrait sinon
    un autre objet Python que l'ancien — même corps HTTP, mais une
    comparaison en mode `double` fausse, et une route qui relit
    `resultat.donnees` pourrait se comporter autrement.
    """
    lignes: list[str] = []
    debut = time.perf_counter()
    try:
        donnees = json.loads(json.dumps(travail(lignes.append), ensure_ascii=False))
    except Exception as e:  # traduit, jamais propagé tel quel
        raise classer(e, secrets=secrets, chemins=chemins) from e
    duree_ms = int((time.perf_counter() - debut) * 1000)
    if operation and budgets is not None:
        budgets.noter(operation, duree_ms)
    return Resultat(
        donnees=donnees,
        # Joindre puis redécouper : une ligne qui contiendrait un saut de
        # ligne devient plusieurs avertissements, comme sur la sortie d'erreur.
        avertissements=avertissements_de("\n".join(lignes), secrets, chemins),
        duree_ms=duree_ms,
    )


def calculer(
    chemin: str,
    config: Config,
    *,
    route: str,
    operation: str,
    ancien: Callable[..., int],
    nouveau: Callable[..., dict],
    options: Mapping[str, Any],
    clients: Mapping[str, Any],
    budgets: Budgets,
    chemins: Mapping[str, str] | None = None,
    recueils: tuple[str, ...] = (),
) -> Resultat:
    """Un calcul décrit une fois, servi par le chemin choisi.

    `ancien` est le service que `commandes.executer_depuis_namespace` sait
    servir ; `nouveau` la fonction de `api/calculs.py` qui fait le même
    travail. Les deux reçoivent les **mêmes** `options` (les champs du
    `Namespace` de l'ancien chemin) et les **mêmes** `clients`.

    `recueils` nomme les clients qui sont des **rappels** plutôt que des
    connecteurs (`recueil_gpx` de `POST /sorties`) : en mode `double`, le
    nouveau chemin reçoit le sien, et ce qu'il y a déposé est comparé à ce
    que l'ancien a déposé dans celui de la route — la route, elle, ne voit
    que ce que l'ancien a produit.
    """
    secrets = secrets_de(config)

    def par_l_ancien(clients_de_l_ancien: Mapping[str, Any]) -> Resultat:
        return executer_commande(
            ancien,
            namespace(**options),
            config,
            secrets=secrets,
            chemins=chemins,
            operation=operation,
            budgets=budgets,
            **clients_de_l_ancien,
        )

    def par_le_nouveau(clients_du_nouveau: Mapping[str, Any], noter: bool) -> Resultat:
        return executer_service(
            lambda avertir: nouveau(config, avertir, **options, **clients_du_nouveau),
            secrets=secrets,
            chemins=chemins,
            operation=operation,
            budgets=budgets if noter else None,
        )

    if chemin == CHEMIN_ANCIEN:
        return par_l_ancien(clients)
    if chemin == CHEMIN_NOUVEAU:
        return par_le_nouveau(clients, noter=True)
    if chemin != CHEMIN_DOUBLE:  # pragma: no cover - refusé au démarrage
        raise ValueError(f"chemin d'API inconnu : {chemin!r}")

    # --- double : l'ancien répond, le nouveau est comparé -------------------
    deposes: dict[str, list] = {nom: [] for nom in recueils}
    clients_du_nouveau = {
        **clients,
        **{nom: deposes[nom].extend for nom in recueils if clients.get(nom) is not None},
    }
    deposes_par_l_ancien: dict[str, list] = {nom: [] for nom in recueils}
    clients_de_l_ancien = {
        **clients,
        **{
            nom: _aussi(clients[nom], deposes_par_l_ancien[nom].extend)
            for nom in recueils
            if clients.get(nom) is not None
        },
    }
    try:
        reponse = par_l_ancien(clients_de_l_ancien)
    except ErreurApi as erreur:
        # Un serveur occupé n'a rien calculé : rien à comparer, et relancer
        # le calcul par le nouveau chemin ajouterait du travail là où il y en
        # a déjà trop.
        if erreur.code != "calcul_en_cours":
            _comparer_au_nouveau(route, erreur, lambda: par_le_nouveau(clients_du_nouveau, False))
        raise
    _comparer_au_nouveau(
        route,
        reponse,
        lambda: par_le_nouveau(clients_du_nouveau, False),
        deposes_par_l_ancien,
        deposes,
    )
    return reponse


def _aussi(premier: Callable, second: Callable) -> Callable:
    """Un rappel qui appelle `premier`, puis `second` avec la même valeur."""

    def les_deux(valeur: Any) -> None:
        premier(valeur)
        second(valeur)

    return les_deux


# --- la comparaison -------------------------------------------------------------


def _comparer_au_nouveau(
    route: str,
    ancien: Resultat | ErreurApi,
    nouveau: Callable[[], Resultat],
    deposes_par_l_ancien: Mapping[str, list] | None = None,
    deposes_par_le_nouveau: Mapping[str, list] | None = None,
) -> None:
    """Fait tourner le nouveau chemin et journalise l'écart. **Ne lève jamais.**

    Le mode `double` sert la réponse de l'ancien : un nouveau chemin qui
    planterait, ou une comparaison qui se tromperait, ne doit rien changer à
    ce que reçoit le cycliste. D'où le `except Exception` le plus large, dont
    la seule trace est une ligne d'écart de nature `exception`.
    """
    try:
        try:
            obtenu: Resultat | ErreurApi = nouveau()
        except ErreurApi as erreur:
            obtenu = erreur
        ecart = ecart_entre(ancien, obtenu)
        if ecart is None and deposes_par_l_ancien is not None:
            for nom, deposes in deposes_par_l_ancien.items():
                if deposes != (deposes_par_le_nouveau or {}).get(nom):
                    ecart = {"nature": "recueil", "recueil": nom}
                    break
    except Exception as e:  # voir la docstring
        ecart = {"nature": "exception", "exception": type(e).__name__}
    if ecart is not None:
        journal.warning("ecart_double_chemin %s", json.dumps({"route": route, **ecart}, sort_keys=True))


def ecart_entre(ancien: Resultat | ErreurApi, nouveau: Resultat | ErreurApi) -> dict | None:
    """Ce qui sépare deux réponses, **sans aucune valeur** — ou `None` si elles sont identiques.

    Comparé : le statut, puis le corps. Pour une erreur, son code, son
    service et ses détails (le message aussi, mais seule sa différence est
    dite, jamais son texte) ; pour un succès, `donnees` et `avertissements`.
    `duree_ms` ne l'est pas : c'est une mesure, pas un comportement.
    """
    statut_ancien, statut_nouveau = _statut(ancien), _statut(nouveau)
    if statut_ancien != statut_nouveau:
        return {
            "nature": "statut",
            "ancien": _resume(ancien),
            "nouveau": _resume(nouveau),
        }
    corps_ancien, corps_nouveau = _corps(ancien), _corps(nouveau)
    differences = list(_differences(corps_ancien, corps_nouveau, ""))
    if not differences:
        return None
    return {
        "nature": "corps",
        "statut": statut_ancien,
        "ancien": _resume(ancien),
        "cles": differences[:ECARTS_MAX],
        "n": len(differences),
    }


def _statut(reponse: Resultat | ErreurApi) -> int:
    return reponse.statut if isinstance(reponse, ErreurApi) else 200


def _resume(reponse: Resultat | ErreurApi) -> dict:
    """Ce qu'on peut dire d'une réponse sans rien en citer : un statut, un code."""
    if isinstance(reponse, ErreurApi):
        return {"statut": reponse.statut, "code": reponse.code}
    return {"statut": 200}


def _corps(reponse: Resultat | ErreurApi) -> dict:
    if isinstance(reponse, ErreurApi):
        return reponse.charge()
    return {
        "donnees": reponse.donnees,
        "avertissements": [a.charge() for a in reponse.avertissements],
    }


def _differences(a: Any, b: Any, ou: str, cles_donnees: bool = False):
    """Les chemins de clés où `a` et `b` diffèrent (types compris : `30` n'est pas `30.0`).

    `cles_donnees` : les clés de ce dictionnaire sont des données (des noms de
    vélos), masquées quelle que soit leur orthographe.
    """
    if isinstance(a, dict) and isinstance(b, dict):
        if list(a) != list(b):
            yield f"{ou or '.'}{{clés}}"
        for cle in a:
            if cle in b:
                segment = "*" if cles_donnees else _segment(cle)
                yield from _differences(a[cle], b[cle], f"{ou}.{segment}", cle in _PARENTS_DE_DONNEES)
        return
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            yield f"{ou}[longueur]"
        for i, (x, y) in enumerate(zip(a, b, strict=False)):
            yield from _differences(x, y, f"{ou}[{i}]")
        return
    if type(a) is not type(b) or a != b:
        # Deux NaN sont « égaux » ici : ils ont été rendus de la même façon.
        if not (isinstance(a, float) and isinstance(b, float) and a != a and b != b):
            yield ou or "."


def _segment(cle: Any) -> str:
    """Une clé de dictionnaire, si c'est un identifiant du code ; `*` sinon.

    Les clés du rendu sont des noms de champ (`propositions`, `distance_km`) ;
    certaines sont des **données** (un nom de vélo, une date) : celles-là ne
    sortent pas dans le journal.
    """
    texte = str(cle)
    if _IDENTIFIANT.fullmatch(texte):
        return texte
    return "*"


#: Un nom de champ du rendu : minuscules, chiffres et soulignés.
_IDENTIFIANT = re.compile(r"[a-z_][a-z0-9_]*")

#: Les champs du rendu dont les clés sont des noms de vélos (la comparaison
#: de deux vélos, `rendu/comparaison.py`) : un nom tout en minuscules, « route »,
#: passerait `_IDENTIFIANT`, il est donc masqué d'office sous ces champs.
_PARENTS_DE_DONNEES = frozenset({"velos", "vitesse_mediane_kmh", "vitesse_kmh"})


__all__ = [
    "CHEMINS",
    "CHEMIN_ANCIEN",
    "CHEMIN_DEFAUT",
    "CHEMIN_DOUBLE",
    "CHEMIN_NOUVEAU",
    "calculer",
    "ecart_entre",
    "executer_service",
    "journal",
]
