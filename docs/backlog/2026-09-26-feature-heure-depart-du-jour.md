# Séance du jour à l'heure réelle

Type : feature
Statut : validée le 26/09/2026

## Pourquoi

Le 25/09/2026 vers 17:30, en production, l'onglet « Aujourd'hui » a proposé « 9 h 00 … retour vers 9 h 52 » avec une tenue d'automne (14 °C ressentis : manchettes, jambières, gilet, gants longs) alors qu'il faisait environ 30 °C au moment réel du départ. `demandeInitiale()` pose `heure_depart: "09:00"` en dur, et « Aujourd'hui » lance la recherche avec cette heure sans jamais la demander ni l'afficher. Météo, tenue et placement des blocs de vent sont donc calculés pour un départ imaginaire.

## Ce que je veux voir

- Sur « Aujourd'hui », l'heure de départ utilisée pour chercher le parcours du jour n'est plus "09:00" figé : c'est **l'heure courante arrondie au quart d'heure suivant**, quand on cherche le jour même (QP3, 25/09/2026 : « le jour même, l'heure courante arrondie au quart d'heure suivant, 9 h un autre jour, affichée et modifiable en un geste »).
- Cette heure est **affichée sur l'écran « Aujourd'hui »** (pas seulement dans « Demander »), avec le même champ `<input type="time">` que dans Demander, modifiable en un geste avant de lancer la recherche.
- Pour « Demain » et « Après-demain » (tout jour qui n'est pas aujourd'hui), le défaut reste 9 h, comme avant.
- Si on bascule de « Demain » vers « Aujourd'hui » dans l'écran Demander, l'heure par défaut se recalcule — elle ne reste pas gelée à ce qu'elle était au chargement de la page.
- Exemple concret : Amiel ouvre l'app à 14 h 37 un jour de séance planifiée ; « Aujourd'hui » affiche « Départ à 14:45 » (ou le prochain quart d'heure), et la tenue, la météo et le placement des blocs de vent sont calculés pour ce départ-là, pas pour 9 h.

## C'est fini quand

Le jour même, « Aujourd'hui » n'affiche plus 09:00 en dur mais la règle QP3 ; l'heure est visible et modifiable en un geste ; un test du front couvre les trois cas (jour même, autre jour, heure déjà avancée dans la journée) ; vérifié sur la séance réelle d'Amiel un jour où il ouvre l'app en début d'après-midi — la tenue affichée suit la température de cette heure-là, pas celle de 9 h.

## Hors sujet

- Ne pas lire l'heure de la séance planifiée sur Intervals.icu pour préremplir le départ : piste écartée par QP3, qui retient l'heure courante arrondie, pas l'heure Intervals.
- Ne pas retoucher le fuseau horaire du conteneur (correctif 0.9.4, déjà fait, sujet distinct).
- Ne pas changer le comportement de « Demain » / « Après-demain » : ils gardent 9 h par défaut.
- Pas de plafond ni d'avertissement inventé pour une heure de départ tardive (ex. calculée après 22 h) : on affiche l'heure telle quelle.

## Acquis techniques

- Calcul entièrement côté front (TypeScript) : cohérent avec la règle « le cœur ne sait pas où il tourne » — le cœur Python continue de recevoir une `heure_depart` déjà résolue, comme aujourd'hui.
- Nouvelle fonction pure dans `front/src/ecrans/demander/demande.ts`, par exemple `heureDepartParDefaut(jour: string): string`, qui rend l'heure courante arrondie au quart d'heure suivant si `jour === aujourdhui()`, sinon `"09:00"`. `demandeInitiale()` l'appelle pour poser `heure_depart`.
- Recalcul déclenché à deux moments : à la création de l'état (`useRecherche.ts`, `useState<Demande>(demandeInitiale)`) et quand l'utilisateur choisit « Aujourd'hui » dans le sélecteur « Quand » de `Demander.tsx` — pour ne pas garder une heure calculée à l'ouverture de la page si elle est restée ouverte longtemps.
- Affichage/édition sur l'écran « Aujourd'hui » (`front/src/ecrans/Aujourdhui.tsx`) : reprendre le même `<input type="time" id="heure-depart">` que `Demander.tsx`, relié au même état `demande.heure_depart` (prop à faire descendre depuis `Contenu.tsx` / `useRecherche.ts`).
- Arrondi au quart d'heure suivant : fonction utilitaire testée unitairement (14:37 → 14:45 ; 14:45 déjà pile → 14:45 ; 23:50 → 00:00 affiché tel quel, sans cas particulier).
- Tests front par cas explicite : jour même à une heure quelconque, jour différent (reste 9 h), heure déjà avancée dans la journée (ex. réouverture à 20 h → 20:15, ce n'est pas une régression, le sujet est le départ réel).

## Questions ouvertes

Aucune.

## Déjà en place / Doctrine révisée

- `front/src/ecrans/Demander.tsx` : champ `<input type="time" id="heure-depart">` déjà là, relié à `demande.heure_depart` — modèle à réutiliser tel quel pour l'écran Aujourd'hui.
- `front/src/app/useRecherche.ts` : `useState<Demande>(demandeInitiale)` — l'état `demande.heure_depart` existe déjà et est déjà envoyé tel quel à `api.sortie()`.
- `front/src/etat/ressource.ts` : `aujourdhui()` donne déjà la date du jour dans le fuseau du navigateur, réutilisable pour tester `jour === aujourdhui()`.
