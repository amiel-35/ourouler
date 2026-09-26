"""`ourouler sortie` : la séance du jour posée sur une boucle, et sa carte.

Le cas d'usage (`services/sortie.py`) **assemble** ce que les autres ont
produit — la séance (`seance.intervals`), les boucles candidates
(`boucle.candidates`), les coûts et la météo le long du tracé (`boucle.couts`,
`boucle.meteo_trace`), le placement des blocs et la tenue (`seance.placement`,
`seance.tenue`) — et il n'ajoute aucune règle de son côté. Ce paquet garde ce
qui est propre à la sortie : le contraste des propositions (`contraste`),
l'orientation et le vent de la demande (`orientation`, `vent_demande`).

Pourquoi un paquet à lui plutôt que `seance/sortie.py` : le lot ne relève
d'aucun des deux domaines qu'il relie. Le mettre sous `seance/` ferait
dépendre le paquet de la séance de la génération de boucles, de la météo et
d'un générateur de page HTML, alors que `seance/` est aujourd'hui du calcul
pur (son cas d'usage, qui touche au réseau, est `services/seance.py`).
`sortie/` est donc le pendant de `boucle/`.
"""
