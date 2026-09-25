"""Le vocabulaire de l'orientation au vent, et rien d'autre.

Un module volontairement minuscule et **sans aucune dépendance lourde** : la
ligne de commande a besoin de la liste des réponses possibles pour construire
son parseur, c'est-à-dire à chaque `ourouler --help`. Importer depuis
`sortie.contraste` ou `sortie.vent_demande` y ferait entrer httpx et sqlite3
— mesuré le 16/09/2026 : 76 ms de plus au démarrage, contre 18 ms pour tout
`ourouler.cli`. C'est exactement ce que les imports paresseux du lot L4.4
évitent.

Les trois orientations sont celles que le mainteneur a nommées lui-même :
« vent dans le dos au départ de la sortie, ou à la fin, ou plutôt vent
latéral ? ». `ORIENTATION_FACE` est la quatrième situation, celle qu'on ne
propose pas mais qu'on doit savoir nommer quand elle arrive : un tracé où le
vent est de face aux deux bouts.
"""

from __future__ import annotations

from ourouler.noyau.erreurs import ErreurUtilisateur

ORIENTATION_RETOUR_DOS = "retour-dos"
ORIENTATION_DEPART_DOS = "depart-dos"
ORIENTATION_TRAVERS = "travers"
ORIENTATION_FACE = "face"

#: « peu importe » est le défaut **et une réponse valable** : on ne
#: pré-sélectionne rien, parce que la mesure du 16/09/2026 sur 161 sorties dit
#: que le mainteneur n'a jamais exprimé de préférence — ce qui ne prouve pas
#: qu'il n'en a pas, seulement qu'aucun outil ne lui avait permis d'en
#: exprimer une (contrat §3.2). La réponse retombe alors sur les propositions
#: contrastées.
PEU_IMPORTE = "peu-importe"

#: Ce que `--vent` accepte, dans l'ordre où l'aide les présente.
CHOIX = (PEU_IMPORTE, ORIENTATION_RETOUR_DOS, ORIENTATION_DEPART_DOS, ORIENTATION_TRAVERS)


def valider(brut: str | None) -> str:
    """Normalise la réponse de la ligne de commande. `None` → « peu importe »."""
    if brut is None:
        return PEU_IMPORTE
    valeur = str(brut).strip().lower().replace("_", "-")
    if valeur in CHOIX:
        return valeur
    raise ErreurUtilisateur(
        f"--vent {brut!r} : attendu {', '.join(CHOIX)} "
        "(« peu-importe » laisse les trois propositions contrastées répondre)"
    )
