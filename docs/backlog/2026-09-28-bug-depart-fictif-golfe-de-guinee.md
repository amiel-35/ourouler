# Sans départ renseigné, le calcul part du golfe de Guinée

Type : bug
Statut : validée le 28/09/2026
Gravité : gênant
Signalé le 27/09/2026

## Constat

Sur le compte du mainteneur, sans aucun profil, « Demander » a échoué avec « Le traceur ne répond pas » et « BRouter : HTTP 400 … datafile E0_N0.rd5 not found ».

## Où

Interface web, onglet Demander ; prod v0.11.0 ; iPhone. Touche tout compte sans départ (compte neuf qui a quitté l'assistant, compte vidé).

## Pour reproduire

1. Créer un compte, quitter l'assistant sans renseigner de départ.
2. Demander → Chercher.

## Attendu

Le calcul part de Paris, avec un bandeau « Départ par défaut : Paris — renseignez le vôtre dans Réglages » et un lien vers Réglages.

## Observé

Le calcul part de (0, 0) ; BRouter n'a pas de carte à cet endroit et renvoie une erreur technique.

## Gravité

Gênant — tout compte sans départ ; contournable en renseignant son départ.

## Piste

- Constaté : `src/ourouler/config.py`, `_depart_depuis`, pose `latitude`/`longitude` à `0.0` quand le profil n'est pas exigé (mode hébergé), avec le nom « Départ ».
- Constaté : l'assistant ne s'impose qu'une fois (`front/src/App.tsx`, `assistantDejaImpose`) ; rien ne ramène ensuite vers lui.
- [déduit] Correctif : remplacer ce (0, 0) par un départ de repli nommé « Paris », défini à un seul endroit (constante documentée), et le marquer comme défaut dans la réponse de l'API pour que le front affiche le bandeau.
- [déduit] Le test d'invariants interdit des coordonnées réelles dans le Markdown, les fixtures et la configuration : la constante vit dans le code, les documents nomment la ville sans ses coordonnées.

## C'est corrigé quand

Sur la préprod, un compte neuf qui quitte l'assistant : Demander → Chercher donne des boucles autour de Paris, avec le bandeau et le lien ; une fois le départ renseigné dans Réglages, le bandeau disparaît et les boucles partent du vrai départ.

## Questions ouvertes

- Faut-il aussi reproposer l'assistant tant que le départ manque ?
