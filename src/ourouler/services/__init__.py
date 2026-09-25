"""Cas d'usage : une demande en entrée, un résultat en sortie.

Couche 3 de `docs/ouverture_plan.md` §2. Un service orchestre le domaine, les
dépôts et les connecteurs qu'on lui passe ; il ne lit ni configuration, ni
variable d'environnement, ni chemin de l'utilisateur, ne connaît pas argparse
et n'imprime rien. La ligne de commande et l'API en sont les adaptateurs.
"""
