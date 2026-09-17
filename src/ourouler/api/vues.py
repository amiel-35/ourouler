"""Ce que le front voit, à partir de ce que la ligne de commande rend.

Deux écarts assumés avec le JSON de la CLI, et deux seulement. Tout le reste
est transmis tel quel.

**1. Le profil n'est pas la configuration.** `ourouler config --json` rend
tout, y compris ce qui décrit la *machine* : le dossier de cache, l'URL du
serveur BRouter, son identifiant. Utile dans un terminal, inutile dans un
navigateur, et c'est l'arborescence d'un serveur. L'API rend le profil du
**cycliste**, et remplace l'exploitation par ce que le front a réellement
besoin de savoir : le service est-il renseigné, oui ou non.

**2. Un fichier est un identifiant, pas un chemin.** `carte` porte, en ligne
de commande, un chemin sur le disque. Le front reçoit `{"id", "nom", "url"}`,
et c'est la route des fichiers — qui vérifie le propriétaire — qui sert le
contenu. Le GPX, lui, n'est plus un fichier du tout : chaque proposition
porte l'adresse de sa propre trace, fabriquée à l'appel (Q40 g, voir
`avec_gpx_par_proposition`).
"""

from __future__ import annotations

import json

from ourouler.api.depots import Fichier

#: Les sections de `Config` qui décrivent la machine et non le cycliste.
#: Retirées du profil rendu par l'API.
SECTIONS_EXPLOITATION = ("cache",)


def profil(config) -> dict:
    """Le profil du cycliste, secrets masqués, exploitation retirée.

    Part de `cli.profil_json`, qui est la **même** fonction que celle
    d'`ourouler config --json` : le masquage de la clé Intervals et du mot de
    passe BRouter se fait là-bas, à un seul endroit, pour les deux surfaces.
    """
    from ourouler.cli import profil_json

    # `default=str` : dates et chemins, comme la ligne de commande le fait.
    donnees = json.loads(json.dumps(profil_json(config), default=str, ensure_ascii=False))
    for section in SECTIONS_EXPLOITATION:
        donnees.pop(section, None)
    brouter = donnees.pop("brouter", {}) or {}
    intervals = donnees.get("intervals", {}) or {}
    donnees["services"] = {
        "intervals": {
            "renseigne": bool(config.intervals.renseigne),
            "athlete_id": intervals.get("athlete_id", ""),
        },
        # Ni l'URL ni l'identifiant : le front n'a rien à en faire, et une
        # adresse de serveur interne n'a pas à traverser un navigateur.
        "brouter": {
            "renseigne": bool(config.brouter.renseigne),
            "profil": brouter.get("profil"),
        },
    }
    return donnees


def avec_fichiers(donnees: dict, **fichiers: Fichier | None) -> dict:
    """Remplace les chemins de fichiers du JSON du cœur par leurs fiches.

    Une clé absente du JSON n'est pas ajoutée : `boucle` sans GPX et `sortie`
    sans carte gardent leur forme.
    """
    sortie = dict(donnees)
    for cle, fichier in fichiers.items():
        if cle not in sortie:
            continue
        sortie[cle] = None if fichier is None else fichier.json()
    return sortie


def avec_gpx_par_proposition(
    donnees: dict, *, generation: str, noms: dict[int, str], prefixe: str
) -> dict:
    """Donne à **chaque** proposition l'adresse de son propre GPX (Q40 g).

    Les trois propositions sont contrastées exprès : celle qu'on emporte
    n'est pas forcément la première. Tant qu'un seul GPX était exposé,
    choisir « la plus sèche » puis l'envoyer au compteur envoyait la mauvaise
    trace, et l'erreur ne se voyait qu'une fois dehors (E19, E20).

    Rien n'est écrit sur le disque : `url` désigne une route qui fabrique le
    fichier à l'appel. La génération est nommée au premier niveau
    (`generation`) pour qu'un écran puisse la garder sans relire les
    propositions.
    """
    propositions = donnees.get("propositions")
    if not isinstance(propositions, list):
        return donnees
    sortie = dict(donnees)
    sortie["generation"] = generation
    sortie["propositions"] = [
        {
            **proposition,
            "gpx": {
                "nom": noms.get(proposition.get("numero"), ""),
                "url": f"{prefixe}/sorties/{generation}/propositions/"
                f"{proposition.get('numero')}/gpx",
            },
        }
        if isinstance(proposition, dict)
        else proposition
        for proposition in propositions
    ]
    return sortie


__all__ = [
    "SECTIONS_EXPLOITATION",
    "avec_fichiers",
    "avec_gpx_par_proposition",
    "profil",
]
