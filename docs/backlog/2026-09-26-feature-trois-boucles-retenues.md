# Trois boucles retenues d'office

Type : feature
Statut : validée le 26/09/2026

## Pourquoi

Note du 20/09/2026, mesurée dans la ville d'Amiel et à La Rochelle — en demandant trois parcours pour une séance, l'appli n'en retient souvent qu'un, les deux autres étant écartées à 31 % de recouvrement pour un seuil de 30 %. « C'est chiant quand le modèle arbitre trop » : Amiel veut plusieurs vraies propositions, sans avoir à cliquer sur « Chercher plus loin » lui-même.

## Ce que je veux voir

- Quand une demande de parcours ne retient qu'une ou deux boucles (trop de recouvrement entre candidates), le calcul relance lui-même la recherche avec plus de candidates **avant de répondre**, sans action du cycliste (QP4, 25/09/2026 : « relancer « Chercher plus loin » d'office jusqu'à trois boucles retenues »).
- Ça continue jusqu'à obtenir trois boucles retenues, ou jusqu'à une limite raisonnable de tentatives si trois vraies boucles disjointes n'existent pas autour de ce point de départ — l'appli le dit alors honnêtement plutôt que d'inventer un troisième itinéraire qui repasse par les mêmes routes.
- Une seule recherche demandée = une seule entrée de quota, même si plusieurs essais ont eu lieu en coulisse.
- Le bouton « Chercher plus loin » reste disponible, mais seulement si l'appli n'a toujours pas trouvé trois boucles après ses propres tentatives — pour pousser encore plus loin sur décision du cycliste.
- Exemple concret : une séance de 90 minutes en ville dense un jour de vent fort — avant, « Le seul » avec un bouton « Chercher plus loin » ; après, trois propositions numérotées d'emblée, sans clic de plus.

## C'est fini quand

Sur les séances réelles d'Amiel rejouées (dont celle mesurée le 20/09 en ville et à La Rochelle), la part des demandes qui rendent 3 propositions passe de la valeur mesurée avant le lot (à relever en tout début de lot) à au moins 90 % ; le coût en appels BRouter par demande est mesuré et rapporté ; une génération compte toujours une seule fois dans le quota, vérifié sur `POST /sorties`.

## Hors sujet

- Ne touche pas `SEUIL_RECOUVREMENT` (`sortie/contraste.py`) ni la logique de sélection elle-même (`_meilleur_groupe`, `_assez_disjointes`) — QP4 choisit de relancer la recherche, pas d'assouplir le seuil.
- Pas de seuil réglable par le cycliste dans les réglages : piste écartée par QP4 au profit de « relancer d'office ».
- Ne recroise pas B12 (relief demandé) ni B18 (qualité du tracé) : sujets voisins, pas traités ici.

## Acquis techniques

- Implémentation côté serveur (`sortie/commande.py`), pas front : la relance appelle `boucle.candidates.generer` avec un nombre de candidates croissant (sur le même principe que le `candidates: 8` déjà utilisé par le bouton « Chercher plus loin ») et revérifie via `sortie.contraste.selectionner` jusqu'à obtenir trois boucles retenues ou un plafond de tentatives.
- Le plafond de tentatives et les paliers de candidates sont un choix technique, borné pour ne pas multiplier sans fin les appels BRouter et Open-Meteo par demande — mesuré et rapporté dans les critères du lot, pas un choix produit.
- Le quota (`api/quotas.py`, `POST /sorties`) compte l'appel HTTP, pas les essais internes : en gardant toute la relance dans un seul appel serveur, « une génération = une entrée de quota » est automatique, pas un correctif à part.
- Le bouton « Chercher plus loin » du front (`Propositions.tsx`, `surElargir` dans `Contenu.tsx`) reste comme filet ; sa condition d'affichage passe de `sortie.propositions.length === 1` à « moins de trois propositions » après la relance serveur.
- La mesure « part des demandes à 3 propositions » et « coût en appels BRouter » se fait sur les séances réelles d'Amiel (règle 4 de la doctrine), avant/après, en reprenant les cas déjà mesurés le 20/09 (ville d'Amiel, La Rochelle).

## Questions ouvertes

Aucune.

## Déjà en place / Doctrine révisée

- `src/ourouler/sortie/contraste.py` : `SEUIL_RECOUVREMENT = 0.30`, `selectionner()`, `_meilleur_groupe()`, `_assez_disjointes()` — la logique de sélection existe et n'est pas à toucher.
- `front/src/ecrans/Propositions.tsx` + `front/src/app/Contenu.tsx` : bouton « Chercher plus loin », affiché seulement si `sortie.propositions.length === 1`, qui relance `chercher({ candidates: 8 })` manuellement.
- `src/ourouler/api/quotas.py` : le quota compte l'appel `POST /sorties`, pas les essais internes de recherche de candidates.
