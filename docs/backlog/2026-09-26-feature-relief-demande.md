# Demander un relief

Type : feature
Statut : validée le 26/09/2026

## Pourquoi

En plus de la durée et de la direction, Amiel veut demander le relief de sa boucle — « plat, vallonné, qui grimpe, montagne » (note du 20/09/2026) — et que l'appli réponde honnêtement quand ce relief n'existe pas à portée, au lieu de servir la moins plate des boucles sous ce nom.

## Ce que je veux voir

- Sur l'écran de demande, un choix de relief à côté de la direction : « Peu importe », « Plat », « Vallonné », « Qui grimpe », « Montagne ».
- La génération des candidates vise le relief demandé (le moyen technique se choisit au lot) ; un filtre sur le dénivelé par km de la trace, déjà connu (`boucle/trace.py: denivele_filtre`), vérifie ensuite le résultat. Filtrer seulement après une génération aveugle ne suffit pas : « Qui grimpe » tomberait souvent sur « introuvable » alors que ces boucles existent.
- Les quatre catégories sont séparées par des seuils resserrés : Plat < 8 m/km, Vallonné 8–20 m/km, Qui grimpe 20–35 m/km, Montagne > 35 m/km avec une pente soutenue ≥ 6 %. Première étape du lot : mesurer le dénivelé par km réel des sorties du mainteneur, pour savoir quelles catégories sont atteignables depuis son départ (non mesuré à la rédaction de la fiche).
- Si aucune candidate à portée ne correspond au relief demandé (ex. « Montagne » depuis une région de plaine), un message le dit explicitement — « Aucune boucle montagne trouvée à cette distance depuis [départ] ; la plus proche fait X m/km » — plutôt que de rendre silencieusement la moins plate des boucles sous ce nom.
- Si le relief obtenu contredit un bloc de la séance du jour (ex. un bloc Z2 placé sur un col à forte pente, un bloc de force à cadence basse sur du plat qui descend), une alerte nomme le bloc concerné et la pente en cause — elle ne se résout jamais en silence par le placement.

## C'est fini quand

Sur une vraie demande du mainteneur depuis son point de départ réel, avec un relief choisi parmi les quatre, la boucle rendue correspond au seuil retenu pour ce relief, ou l'appli dit clairement qu'aucune boucle de ce relief n'existe à cette distance — rejoué sur au moins un cas où le relief demandé existe et un cas où il n'existe pas (ex. « Montagne » dans sa région).

## Hors sujet

- Le porte-à-porte qui ignore le relief de la boucle (backlog séparé, doctrine du `temps_estime_s`) : sujet distinct, déjà livré au sprint 9 (fourchette du porte à porte, `physique/calibration.py`).
- Recherche par dénivelé exact ou en mètres cumulés absolus : le relief se demande par catégorie, pas par un chiffre à saisir.
- [[Q53]] (qualité du tracé, feux, dégagement urbain, mode circuit) : backlog séparé.

## Acquis techniques

- Le dénivelé filtré par trace existe déjà (`boucle/trace.py: denivele_filtre`, `SEUIL_DENIVELE_M`, utilisé par `boucle/commande.py` et `boucle/gpx.py`) ; le filtrage par relief se branche dessus, pas de nouveau calcul de pente à inventer.
- Le désaccord relief/séance se détecte avec les mêmes outils que le placement des blocs (`seance/terrain.py`, pente en tangente, écart-type de pente) ; l'alerte est un message ajouté au rendu existant, pas une nouvelle mécanique de calcul de pente.
- Paramètre ajouté à la `Demande` du cœur (comme la direction), lu par `cli.py`/l'API ; le cœur reste ignorant d'où vient ce paramètre (règle 2 de CLAUDE.md).

## Questions ouvertes

Aucune.

## Déjà en place / Doctrine révisée

- Dénivelé filtré par trace, déjà calculé et attaché à chaque candidate (`src/ourouler/boucle/trace.py: denivele_filtre`, `SEUIL_DENIVELE_M` ; `src/ourouler/boucle/commande.py`, `boucle/gpx.py`).
- Profil coloré par la pente déjà livré (mentionné dans le backlog relief comme socle à rattacher).
- Score de placement des blocs de séance selon la pente (`src/ourouler/seance/terrain.py`, tangente, écart-type de pente).
- Note du mainteneur du 20/09/2026 : quatre catégories nommées (plat, vallonné, qui grimpe, montagne), réponse honnête si introuvable à portée, alerte nommée si désaccord avec un bloc de séance plutôt qu'une résolution silencieuse.
- Tranché le 26/09/2026 : seuils resserrés retenus — plat < 8 m/km, vallonné 8–20, qui grimpe 20–35, montagne > 35 m/km avec une pente soutenue ≥ 6 %.
