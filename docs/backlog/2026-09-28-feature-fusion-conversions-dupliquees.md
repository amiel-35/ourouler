# Une seule conversion km/h ↔ m/s, au lieu de dix-neuf

Type : feature
Statut : à valider

## Pourquoi

Le facteur 3,6 (km/h vers m/s ou l'inverse) est écrit en dur, à chaque
endroit qui en a besoin, dans au moins neuf fichiers du domaine et des
services. Ce n'est pas qu'une question de style : une constante de
conversion recopiée dix-neuf fois est dix-neuf endroits où une erreur de
sens (`* 3.6` au lieu de `/ 3.6`) passerait une revue distraite, et dix-neuf
endroits à retrouver si le projet devait un jour arrondir différemment ou
tracer qui convertit quoi. [déduit]

## Ce que je veux voir

- Deux fonctions nommées, dans le cœur (probablement `physique/modele.py` ou
  un module dédié assez bas pour que tout le monde puisse l'importer sans
  cycle) : `kmh_vers_ms(v_kmh: float) -> float` et `ms_vers_kmh(v_ms: float)
  -> float`, chacune une ligne, avec une docstring qui nomme le facteur.
- Tous les points recensés ci-dessous remplacés par un appel à l'une des deux
  fonctions, sans changer le résultat numérique (même flottant, à l'epsilon
  près — un test de non-régression le vérifie).
- Aucun changement de comportement observable : c'est un renommage de calcul,
  pas une nouvelle règle physique.

## C'est fini quand

`grep -rn '/ 3\.6\|\* 3\.6' src/ourouler` (hors tests, hors la définition des
deux fonctions elles-mêmes) ne rend plus rien ; la suite complète
(`uv run pytest -q`) passe sans qu'aucune valeur numérique attendue n'ait dû
changer — un changement de valeur attendue dans un test existant serait le
signe d'une conversion mal reportée, pas d'un « détail d'implémentation ».

## Hors sujet

- Toute autre conversion d'unité (degrés/radians déjà via `math.radians`,
  mètres/kilomètres, watts/kilowatts…) : ce lot ne traite que km/h ↔ m/s,
  seule paire trouvée dupliquée de façon probante lors de cette revue.
- Les formes `.json()`/`.charge()` qui convertissent une dataclass en dict,
  présentes séparément dans six fichiers
  (`activites/import_archive.py`, `meteo/portee.py`, `api/depots.py`,
  `api/erreurs.py`, `api/taches_fond.py`, `api/adaptateur.py`) : chacune
  rend une forme différente, propre à son objet — ni la même signature, ni
  le même contenu ; ce n'est pas une duplication au sens de cette fiche, et
  la fusionner forcerait une forme commune à des objets qui n'en ont pas
  besoin. Non retenu, faute de doublon probant.

## Acquis techniques

Aucune infrastructure nouvelle : deux fonctions pures, sans état, sans
dépendance externe.

## Questions ouvertes

- Le nom exact et l'emplacement des deux fonctions (à côté de
  `physique/modele.py::vitesse_a_plat_kmh`, qui fait déjà `* 3.6` en une
  ligne, semble le plus proche du domaine) — à trancher au lot, pas ici.

## Déjà en place / Doctrine révisée

- Constaté (`grep -rn '/ 3\.6\|\* 3\.6' src/ourouler`, hors tests) : dix-neuf
  occurrences, dans neuf fichiers —
  `services/seance.py` (lignes 77, 151, 174, 474),
  `services/physique.py` (ligne 377),
  `services/comparer.py` (lignes 249-250, 302),
  `services/sortie.py` (lignes 704, 718),
  `physique/calibration.py` (ligne 169),
  `physique/echantillonnage.py` (lignes 371, 445),
  `physique/modele.py` (lignes 267, 284, 298, 391, 616, 634),
  `seance/vent.py` (lignes 58, 85),
  `seance/pas_trace.py` (ligne 124).
- Constaté : aucune fonction `kmh_vers_ms`/`ms_vers_kmh` (ni motif
  équivalent) n'existe aujourd'hui dans `src/ourouler` — la conversion n'a
  jamais été nommée, seulement recopiée.
