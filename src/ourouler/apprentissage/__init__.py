"""Apprentissage : ce que les sorties passées du cycliste disent de ses routes.

Les traces servent à **apprendre**, jamais de critère de choix : elles ne
couvrent qu'une partie du territoire (sud et ouest de Rennes pour le
mainteneur), et pénaliser ce qu'elles ignorent condamnerait toute boucle vers
le nord ou l'est. « Inconnu » n'est donc jamais un malus.
"""
