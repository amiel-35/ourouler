"""Stockage : ce que le code écrit sur disque et relit plus tard.

Couche 2 du contrat d'imports (`docs/ouverture_plan.md` §2), à côté des
connecteurs : un module de stockage reçoit un chemin et rend des objets du
domaine (ou en reçoit et les écrit). Il n'importe que le noyau et le domaine,
jamais la configuration : c'est l'appelant qui résout le chemin.

`calibrations` (lot 7) : `calibration.json`.
"""
