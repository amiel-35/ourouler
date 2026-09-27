# Partage GPX depuis l'écran des boucles libres

Type : feature
Statut : validée le 26/09/2026

## Pourquoi

Amiel veut envoyer un parcours à son compteur sans le détour « télécharger, puis ouvrir avec » ([[Q5]], close le 15/09/2026 : « deep link vers l'appli, sinon partage système »). C'est fait sur l'écran d'une sortie avec séance ; ça manque encore sur l'écran d'une boucle libre.

## Ce que je veux voir

- Sur l'écran d'une boucle libre (`front/src/ecrans/Boucles.tsx`), à côté du GPX de la candidate retenue, un bouton « Envoyer vers mon compteur » identique dans son comportement à celui déjà livré sur l'écran d'une proposition (`front/src/ecrans/proposition/Onglets.tsx` + `partager.ts`) : `navigator.share({files})` avec le fichier `.gpx`, et si le navigateur ne sait pas partager de fichier, le lien « Télécharger le GPX » reste juste en dessous, inchangé.
- Une panne de génération du GPX (ex. `generation_introuvable`) affiche le même message nommé que sur l'écran de proposition, pas « ce navigateur ne sait pas partager » par erreur (c'est exactement le défaut corrigé le 18/09/2026 sur l'autre écran, à ne pas réintroduire ici).
- Sur un téléphone réel : le bouton ouvre la feuille de partage système avec le fichier `.gpx`, et le parcours arrive dans l'application du compteur (Garmin Connect ou Coros).

## C'est fini quand

Depuis un téléphone réel, sur une boucle libre calculée avec les vraies données du mainteneur (son point de départ, son vélo), le bouton « Envoyer vers mon compteur » ouvre la feuille de partage et le GPX atterrit dans Garmin Connect (ou Coros) — pas seulement sur l'écran de proposition, mais aussi sur l'écran de boucle libre.

## Hors sujet

- Wahoo cloud (API OAuth) : à part, nécessite un accès développeur, attend que le service soit hébergé.
- Hammerhead : pas de dépôt direct, import par tableau de bord web — hors périmètre de ce bouton.
- Toute nouvelle dépendance front : `navigator.share` est une API native, zéro paquet ajouté.

## Acquis techniques

- La fonction `partager()` (`front/src/ecrans/proposition/partager.ts`) et la distinction des pannes (`panneDeReponseGpx`, `recupererGpx` dans `front/src/api/client.ts`) sont déjà écrites et testées (`front/tests/gpx_proposition.test.tsx`) ; le travail sur `Boucles.tsx` est de les réutiliser, pas de les réécrire — même fonction importée, pas de duplication.
- Le bouton `<a href download>` reste natif et inchangé (les tests existants vérifient son `href`/`download` exacts) ; le bouton de partage vient en plus, pas à la place.
- Le point de montage : juste après le bloc `{boucle.gpx && active?.retenue ? (...) : ...}` actuel de `Boucles.tsx` (bouton « Télécharger le GPX »), avec le même garde-fou (« Le GPX prêt est celui de la boucle retenue, pas de celle-ci » quand une autre candidate est sélectionnée).

## Questions ouvertes

Aucune.

## Déjà en place / Doctrine révisée

- Le partage direct du GPX existe déjà sur l'écran d'une proposition (sortie avec séance) ; cette fiche ne couvre que l'écran des boucles libres, où le geste manque encore.
- Partage système du GPX avec Web Share API et repli sur le téléchargement, complet et testé sur l'écran de proposition (`front/src/ecrans/proposition/Onglets.tsx`, `front/src/ecrans/proposition/partager.ts`, `front/src/api/client.ts` fonctions `recupererGpx`/`panneDeReponseGpx`, `front/tests/gpx_proposition.test.tsx`).
- Bouton « Télécharger le GPX » natif sur l'écran de boucle libre (`front/src/ecrans/Boucles.tsx`).
- GPX rendu à la demande avec le bon type MIME `application/gpx+xml`, sans toucher le disque (référencé dans `docs/journal/sprints/plan_sprints_agents.md`).
- [[Q5]], close le 15/09/2026 : pas d'API Garmin Connect pour un particulier, le partage système du GPX suffit.
- Backlog « envoi au compteur » requalifié le 25/09/2026 : ce qui reste sur cette fiche est du confort (Web Share API), pas un bloquant.
