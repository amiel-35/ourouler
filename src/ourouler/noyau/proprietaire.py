"""À qui appartient une ligne de données. Une constante, pas un module.

Doctrine §10.1 : « Le schéma de l'index local est écrit avec une colonne
*propriétaire* en tête, pour que la migration soit un déplacement, pas une
réécriture. » §10.2 : « Isolation des données : par utilisateur, vérifiée côté
serveur à chaque requête, jamais seulement côté front. **Aucune requête sans
clause de propriétaire.** »

Il n'y a pas encore de comptes — c'est le lot F3. La colonne et la clause
s'écrivent quand même **maintenant** : aujourd'hui c'est une colonne et un
`WHERE` de plus, demain c'est une migration de données sous un service qui
tourne.

**Où le propriétaire entre.** Au constructeur du dépôt, et nulle part ailleurs.
`Cache(dossier, proprietaire=…)`, `BaseRoutes(chemin, proprietaire=…)`,
`ClientArchive(chemin_cache=…, proprietaire=…)` : exactement la même position
que le `Path`, qui est déjà ce que la ligne de commande fournit et que le cœur
ignore (règle absolue 2 de CLAUDE.md). Le reste du cœur continue d'appeler
`cache.lister()` sans jamais prononcer le mot. Le jour où l'hébergé arrivera,
c'est la couche web qui construira le dépôt avec l'identifiant de l'utilisateur
authentifié ; aucune fonction du cœur ne changera.
"""

from __future__ import annotations

#: Propriétaire des lignes écrites par la ligne de commande.
#:
#: En local il n'y a qu'un utilisateur, et la CLI n'a aucun moyen d'écrire
#: autre chose : la valeur ne sert qu'à ce que la clause existe et que la
#: migration vers l'hébergé soit un `UPDATE … SET proprietaire = <id>`.
PROPRIETAIRE_LOCAL = "local"

#: Propriétaire des données **publiques mutualisables**, qui n'appartiennent à
#: personne : l'archive météo d'un point et d'un jour est la même pour tous.
#:
#: Doctrine §10.1 : « cache des prévisions par maille et par heure, partagé
#: entre utilisateurs ». La colonne est quand même là, et la clause quand même
#: écrite — sans quoi il faudrait une liste d'exceptions à l'invariant, et une
#: liste d'exceptions se remplit toute seule. C'est précisément la colonne qui
#: rendra le partage explicite le jour venu, au lieu de le laisser implicite
#: dans l'absence de colonne.
PROPRIETAIRE_PARTAGE = "partage"
