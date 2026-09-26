"""Le vocabulaire de l'orientation au vent, et rien d'autre.

Un module volontairement minuscule et **sans aucune dépendance lourde** : la
ligne de commande a besoin de la liste des réponses possibles pour construire
son parseur, c'est-à-dire à chaque `ourouler --help`. Importer depuis
`sortie.contraste` ou `sortie.vent_demande` y ferait entrer httpx et sqlite3
— mesuré : 76 ms de plus au démarrage, contre 18 ms pour tout
`ourouler.cli`. C'est exactement ce que les imports paresseux de la ligne de
commande évitent.

Les trois orientations sont celles qu'un cycliste nomme : vent dans le dos
au départ de la sortie, à la fin, ou plutôt vent latéral. `ORIENTATION_FACE` est
la quatrième situation, celle qu'on ne propose pas mais qu'on doit savoir nommer
quand elle arrive : un tracé où le
vent est de face aux deux bouts.
"""

from __future__ import annotations

from ourouler.noyau.erreurs import ErreurUtilisateur

ORIENTATION_RETOUR_DOS = "retour-dos"
ORIENTATION_DEPART_DOS = "depart-dos"
ORIENTATION_TRAVERS = "travers"
ORIENTATION_FACE = "face"

#: « peu importe » est le défaut **et une réponse valable** : on ne
#: pré-sélectionne rien, parce qu'une mesure sur 161 sorties réelles ne montre
#: aucune préférence exprimée — ce qui ne prouve pas qu'il n'y en a pas,
#: seulement qu'aucun outil ne permettait d'en exprimer une. La réponse retombe alors sur les propositions
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
