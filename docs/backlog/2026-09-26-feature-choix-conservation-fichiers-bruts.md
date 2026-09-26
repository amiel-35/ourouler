# Choix de conservation des fichiers bruts

Type : feature
Statut : validée le 26/09/2026

## Pourquoi

Des traces GPS brutes d'invités dorment aujourd'hui sur le serveur (`brut/comptes/<propriétaire>/`), alors que [[Q48]] disait « on jette le brut, on garde le dérivé » précisément pour ne pas devenir un Strava bis ([[Q67]]). Personne n'a jamais demandé à ces cyclistes s'ils étaient d'accord pour que leurs fichiers soient conservés. QP5 tranche le principe (choix conserver/effacer, refus par défaut, « entraîner le modèle » nommé mais sans usage) ; cette fiche l'applique.

## Ce que je veux voir

- Au moment où des données arrivent — juste après avoir branché Intervals.icu la première fois, et juste après un dépôt d'historique (`DepotHistorique.tsx`) — un écran demande : « Garder vos fichiers d'origine (FIT/GPX/TCX) sur ce serveur ? », jamais pré-coché, avec deux réponses explicites (« Garder » / « Ne pas garder »).
- Le texte nomme aussi « entraîner le modèle » comme option future, marquée « pas encore utilisée » — pour que la question ne se repose pas de zéro le jour où l'apprentissage collectif existera.
- Depuis Réglages → Mon compte, le choix est visible et réversible à tout moment (« Vous gardez vos fichiers d'origine » / « Vous ne les gardez pas », avec un bouton pour changer). Une ligne courte, affichée directement sous les deux boutons sur l'écran de la question, dit que ce choix est réversible depuis Réglages — visible tout de suite, au moment où la décision se prend, pas seulement à qui va la chercher ensuite.
- Retirer l'accord efface immédiatement ce qui était conservé à ce titre — pas seulement à la prochaine sortie importée.
- En refus (le défaut), après un import ou un dépôt, zéro fichier brut ne subsiste sous le dossier du compte : seul le dérivé (mailles, coefficients de calibration) reste.
- `DELETE /moi` efface toujours tout — brut, dérivé, preuve de consentement — inchangé sur ce point.
- Pour les comptes qui ont déjà des fichiers bruts conservés avant cette fonctionnalité : tous les bruts existants sont dérivés puis effacés d'office au déploiement, avant même que la personne se reconnecte ; la question ne se pose qu'ensuite, à la prochaine visite. La liste de ce qui sera purgé est montrée au mainteneur avant que la purge tourne en production.

## C'est fini quand

Sur le compte réel du mainteneur (ou un compte de test hébergé), un import Intervals.icu réel déclenche la question, un refus explicite est enregistré, l'import se termine sans qu'aucun fichier .fit/.gpx/.tcx n'existe sous le dossier du compte (vérifié par un listage du dossier en préprod), et la calibration lancée ensuite depuis l'écran donne un résultat identique à 1e-9 à celui obtenu sur le brut, sur les FIT réels du mainteneur. Un second passage avec « Garder » coché montre les fichiers présents, puis un retrait d'accord les fait disparaître sans attendre un nouvel import. À la migration, la liste des comptes et fichiers concernés par la purge d'office est montrée au mainteneur avant que la purge tourne en prod.

## Hors sujet

- Définir ce qu'« entraîner le modèle » recouvrira réellement (anonymisation, agrégation, sort d'un modèle déjà entraîné) — c'est QP5(b), explicitement écarté au 25/09.
- L'import par lien Strava/Garmin (B8) : cette fiche s'applique au chemin d'import existant (Intervals.icu, dépôt d'historique), pas à un nouveau connecteur.
- Toucher aux routes apprises collectives : elles ne dépendent pas de ce choix, doctrine §10.2 déjà tranchée.

## Acquis techniques

- Refus par défaut, jamais pré-coché (QP5-a, décidé).
- Le calcul pur de `physique/derive.py` et `simuler_profil` (branche `q67-sans-brut`) sert de base : dériver à l'arrivée du fichier, avant toute écriture en `brut/`, plutôt que dériver puis purger après coup.
- La preuve de consentement (accord ou refus, horodatée) est un enregistrement en base lié à `comptes_proprietaires`, pas un simple booléen en mémoire : elle doit survivre à un redémarrage, être exportée par `GET /moi/export` et effacée par `DELETE /moi`.
- Le dédoublonnage d'import (comparaison par contenu, L9.2) qui s'appuyait sur le brut conservé doit se rabattre sur une empreinte du dérivé ou sur les métadonnées déjà indexées (source + id externe).
- Fichier de compatibilité 0d pour la table `derives` (schéma 3, `CREATE TABLE IF NOT EXISTS`), comme prévu à la préparation.
- Les tests de `q67-sans-brut` (`tests/test_sans_brut.py`, `tests/api/test_api_sans_brut.py`) servent de critères d'acceptation repris, étendus au choix par personne (accord/refus) plutôt qu'à la règle unique de la branche.
- Recodé, pas rebasé (la branche traverse trois lots de restructuration qui éclatent `calibration.py` et `commande.py`) — décision déjà actée à la préparation.
- La migration des comptes existants purge d'office (dérivation puis effacement du brut) avant que la question ne soit reposée aux personnes concernées ; la liste de ce qui sera purgé est un rapport produit avant l'exécution en prod, pas seulement un journal après coup.

## Questions ouvertes

- La forme exacte de la preuve de consentement en base (table dédiée vs colonne sur `comptes_proprietaires`) — détail de schéma à trancher au lot, pas un choix produit.
- Si un jour l'apprentissage collectif existe, la question de consentement se repose précisée (déjà acté par QP5) : pas à cadrer ici.

## Déjà en place / Doctrine révisée

- `Cache.supprimer_tout()` (`src/ourouler/activites/cache.py`) efface déjà tout le brut et l'index d'un propriétaire.
- `vie_privee.effacer_donnees` (`src/ourouler/api/vie_privee.py`) efface déjà profil, fichiers, journal, cache (donc le brut) et ferme le compte via `DepotComptes`.
- Le calcul pur `physique/derive.py` et `simuler_profil` (branche `q67-sans-brut`) : dérivation identique au bit à la calibration sur brut, mesurée sur les FIT réels du mainteneur.
- La table `comptes_proprietaires` (`migrations/0001_comptes.sql`) et la cascade `ON DELETE` existent déjà pour rattacher une preuve de consentement à un compte.
- Cache classe déjà `brut/comptes/<propriétaire>/` séparé par propriétaire depuis la relecture Fable du 25/09/2026.
- [[Q67]] (posée le 25/09/2026, `questions_mainteneur.md`) : maintenue ouverte sur la conservation du brut ; cette fiche la ferme via QP5.
- `doctrine_architecture.md` §10.2, RGPD par construction : confirmée, pas révisée — cette fiche l'applique au cas du brut spécifiquement.
- QP5-a (25/09/2026, préparation sprints 11-12) : choix conserver/effacer, refus par défaut, preuve horodatée, retrait qui efface ; « entraîner le modèle » nommé sans usage.
- QP1-c (25/09/2026) : cette fonctionnalité vient après les lots 7, 8 et la partie physique/commande du lot 6, jamais pendant.
- Tranché le 26/09/2026 : à la mise en service, tous les bruts déjà conservés sont dérivés puis effacés d'office, la liste de ce qui sera purgé étant montrée au mainteneur avant l'exécution en prod ; la question de conservation n'est reposée qu'ensuite. Sur l'écran de la question, une ligne courte sous les deux boutons rappelle que le choix est réversible depuis Réglages.
