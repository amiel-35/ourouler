"""`ourouler retirer` : ferme un compte, ses sessions, son invitation, et efface ses données.

Lot L9.6. Ce module orchestre — il ne réimplémente **jamais** l'effacement RGPD : il
appelle `vie_privee.effacer_donnees` exactement comme le fait `DELETE /moi`
(`api/routes.py`), le seul chemin d'effacement de ce dépôt. Même esprit qu'
`api/invitation_commande.py` : ce module reçoit tout ce dont il a besoin déjà résolu — un
dépôt de comptes ouvert sur la base, les dépôts de profil/fichiers/journal/générations et
le dossier de cache du déploiement hébergé — il ne lit lui-même ni fichier ni variable
d'environnement (règle absolue 2) ; c'est `cli.py` qui les rassemble.

**Retrouver le propriétaire depuis l'adresse** est le geste propre à cette commande :
`DepotComptes.compte_par_email` puis `proprietaire_du_compte`, les deux existant déjà
séparément pour d'autres besoins ([[Q46]]) et assemblés ici pour la première fois.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from pathlib import Path

from ourouler.api import vie_privee
from ourouler.api.comptes import DepotComptes, ErreurCompte, normaliser_email
from ourouler.api.depots import DepotFichiers, DepotGenerations, DepotProfils, JournalServices
from ourouler.config import Config

#: Les réponses qui valent « oui » à la confirmation interactive — en minuscules, sans
#: espace de bord (la comparaison est faite après `.strip().lower()`).
REPONSES_OUI = ("o", "oui", "y", "yes")


def executer_retirer(
    args: argparse.Namespace,
    config: Config,
    *,
    depot: DepotComptes,
    profils: DepotProfils,
    fichiers: DepotFichiers,
    journal: JournalServices,
    generations: DepotGenerations,
    dossier_cache: Path,
    demander_confirmation: Callable[[str], str] = input,
) -> int:
    """Exécute `ourouler retirer ADRESSE`. Renvoie le code de sortie (0 = succès, 1 = annulé).

    `demander_confirmation` est injectable (défaut : `input`) — un test lui passe une
    fonction qui rend une réponse toute faite, jamais un vrai `input()` bloquant qui
    attendrait une frappe pendant la suite de tests (règle absolue 3, pas de dépendance
    externe non maîtrisée dans un test).

    Une adresse sans compte lève `ErreurCompte` telle quelle — `cli.main()` l'affiche en
    une ligne, code 2, sans trace, comme les refus d'`inviter`.
    """
    del config  # non utilisé : cette commande ne construit aucune configuration cycliste
    adresse = normaliser_email(args.adresse)
    compte = depot.compte_par_email(adresse)
    if compte is None:
        raise ErreurCompte(f"{adresse} n'a pas de compte — rien à retirer")

    if not getattr(args, "oui", False):
        reponse = demander_confirmation(
            f"Supprimer définitivement le compte {adresse} et toutes ses données "
            "personnelles (profil, fichiers déposés ou générés, cache d'activités) ? "
            "Les routes apprises de ses sorties resteront, collectives (doctrine §10.2). "
            "[o/N] "
        )
        if reponse.strip().lower() not in REPONSES_OUI:
            print("ourouler : annulé — rien n'a été supprimé", file=sys.stderr)
            return 1

    proprietaire = depot.proprietaire_du_compte(compte.identifiant)
    donnees = vie_privee.effacer_donnees(
        proprietaire,
        profils=profils,
        fichiers=fichiers,
        journal=journal,
        generations=generations,
        dossier_cache=dossier_cache,
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


__all__ = ["REPONSES_OUI", "executer_retirer"]
