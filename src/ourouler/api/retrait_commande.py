"""`ourouler retirer` : ferme un compte, ses sessions, son invitation, et efface ses données.

Lot L9.6. Ce module orchestre — il ne réimplémente **jamais** l'effacement RGPD : il
appelle `vie_privee.effacer_donnees` exactement comme le fait `DELETE /moi`
(`api/routes.py`), le seul chemin d'effacement de ce dépôt. Même esprit qu'
`api/invitation_commande.py` : ce module reçoit tout ce dont il a besoin déjà résolu — un
dépôt de comptes ouvert sur la base, et un moyen de résoudre les dépôts de
profil/fichiers/journal/générations et le dossier de cache du déploiement hébergé — il ne
lit lui-même ni fichier ni variable d'environnement (règle absolue 2) ; c'est `cli.py` qui
les rassemble.

**Retrouver le propriétaire depuis l'adresse** est le geste propre à cette commande :
`DepotComptes.compte_par_email` puis `proprietaire_du_compte`, les deux existant déjà
séparément pour d'autres besoins ([[Q46]]) et assemblés ici pour la première fois.

**`resoudre_depots_heberges` est un *callable*, pas les dépôts déjà construits** (changé
lors de la relecture du 25/09/2026, [[B1]]) : la première version appelait
`cli._depots_de_l_hebergement()` avant même de savoir si l'adresse avait un compte ou si
la confirmation serait donnée, ce qui n'avait pas d'incidence en soi — mais figeait
l'ordre des vérifications dans le mauvais sens pour le prochain garde-fou ajouté côté
`cli.py` (un refus explicite si le dossier de données du serveur est introuvable, plutôt
que de continuer en silence sur une base vide). En le rendant paresseux, ce module choisit
*quand* le lire — après l'adresse et la confirmation, juste avant d'en avoir réellement
besoin — sans jamais le lire lui-même : c'est toujours `cli.py` qui répond à l'appel.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ourouler.api import vie_privee
from ourouler.api.comptes import DepotComptes, ErreurCompte, normaliser_email
from ourouler.config import Config

#: Les réponses qui valent « oui » à la confirmation interactive — en minuscules, sans
#: espace de bord (la comparaison est faite après `.strip().lower()`).
REPONSES_OUI = ("o", "oui", "y", "yes")


@dataclass(frozen=True)
class DepotsHeberges:
    """Les quatre dépôts de données personnelles du serveur hébergé, et son dossier de cache.

    Le type que rend `resoudre_depots_heberges` (`cli.py:_depots_de_l_hebergement`) —
    défini ici, pas dans `cli.py`, pour que ce module puisse l'annoter sans importer
    `cli.py` (qui, lui, importe déjà ce module) : l'import inverse créerait un cycle.
    """

    profils: Any
    fichiers: Any
    journal: Any
    generations: Any
    dossier_cache: Path


def executer_retirer(
    args: argparse.Namespace,
    config: Config,
    *,
    depot: DepotComptes,
    resoudre_depots_heberges: Callable[[], DepotsHeberges],
    demander_confirmation: Callable[[str], str] | None = None,
) -> int:
    """Exécute `ourouler retirer ADRESSE`. Renvoie le code de sortie (0 = succès, 1 = annulé).

    `demander_confirmation` est injectable (défaut : `None`, résolu en `input` **dans le
    corps de la fonction**, jamais comme valeur par défaut du paramètre) — un test lui
    passe une fonction qui rend une réponse toute faite, jamais un vrai `input()`
    bloquant qui attendrait une frappe pendant la suite de tests (règle absolue 3, pas de
    dépendance externe non maîtrisée dans un test).

    **Pourquoi pas `= input` en valeur par défaut** (bogue trouvé en relecture, une fois
    Docker redevenu disponible) : une valeur par défaut d'argument est évaluée **une
    fois**, à la définition de la fonction — `= input` y capture alors l'objet fonction
    `input` tel qu'il existe à l'import du module, une référence figée que
    `monkeypatch.setattr("builtins.input", ...)` ne peut plus atteindre ensuite. Un test
    qui remplaçait `input` se retrouvait donc à appeler le vrai `input()`, qui bloque sur
    une lecture de stdin — exactement le problème que l'injection est censée éviter.
    Résoudre `input` à l'intérieur du corps, par son nom nu, le relit dans `builtins` à
    chaque appel et respecte donc le monkeypatch.

    `resoudre_depots_heberges` n'est appelé **qu'une fois l'adresse et la confirmation
    validées** — voir la note de module : c'est ce qui laisse `cli._depots_de_l_hebergement`
    refuser proprement (dossier de données introuvable) sans avoir fait attendre une
    confirmation pour rien, et sans avoir laissé échapper un refus d'adresse derrière un
    refus d'environnement qui n'a rien à voir.

    Une adresse sans compte lève `ErreurCompte` telle quelle — `cli.main()` l'affiche en
    une ligne, code 2, sans trace, comme les refus d'`inviter`.
    """
    del config  # non utilisé : cette commande ne construit aucune configuration cycliste
    confirmer = demander_confirmation if demander_confirmation is not None else input
    adresse = normaliser_email(args.adresse)
    compte = depot.compte_par_email(adresse)
    if compte is None:
        raise ErreurCompte(f"{adresse} n'a pas de compte — rien à retirer")

    if not getattr(args, "oui", False):
        reponse = confirmer(
            f"Supprimer définitivement le compte {adresse} et toutes ses données "
            "personnelles (profil, fichiers déposés ou générés, cache d'activités) ? "
            "Les routes apprises de ses sorties resteront, collectives (doctrine §10.2). "
            "[o/N] "
        )
        if reponse.strip().lower() not in REPONSES_OUI:
            print("ourouler : annulé — rien n'a été supprimé", file=sys.stderr)
            return 1

    heberges = resoudre_depots_heberges()
    proprietaire = depot.proprietaire_du_compte(compte.identifiant)
    donnees = vie_privee.effacer_donnees(
        proprietaire,
        profils=heberges.profils,
        fichiers=heberges.fichiers,
        journal=heberges.journal,
        generations=heberges.generations,
        dossier_cache=heberges.dossier_cache,
        comptes=depot,
    )

    _afficher_retrait(args, adresse, donnees)
    return 0


def _afficher_retrait(args: argparse.Namespace, adresse: str, donnees: dict) -> None:
    if getattr(args, "json", False):
        print(json.dumps({"adresse": adresse, **donnees}, ensure_ascii=False, indent=2))
        return
    print(f"ourouler : compte {adresse} retiré")
    for cle, valeur in donnees["supprime"].items():
        print(f"  {cle} : {valeur}")
    print("conservé (collectif, doctrine §10.2) : routes apprises")


__all__ = ["REPONSES_OUI", "DepotsHeberges", "executer_retirer"]
