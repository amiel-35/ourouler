# Effacer mes données de parcours vs supprimer mon compte

Type : feature
Statut : validée le 26/09/2026

## Pourquoi

Réglages → Mon compte ne propose aujourd'hui qu'un seul geste destructeur, « Supprimer mon compte », qui efface tout et ferme la session. Le mainteneur veut un second geste, plus léger : vider son historique de sorties sans perdre son accès — utile après un import raté, un changement de vélo, ou simplement l'envie de repartir propre sans se réinscrire. [déduit] du texte du backlog : « le compte reste » pour le premier geste, « tout part » pour le second.

## Ce que je veux voir

- Dans Réglages → Mon compte, une seule zone rouge visuellement marquée en bas de l'écran (bordure ou fond distinct, pas un simple bouton parmi d'autres), qui regroupe les deux gestes destructeurs :
  - « Effacer mes données de parcours » — sorties importées, fichiers déposés, calibrations, cache d'activités ; le profil, le mot de passe, la session et l'invitation restent intacts.
  - « Supprimer mon compte » — effacement inchangé (`DELETE /moi` existant) ; seule sa confirmation change (mot SUPPRIMER à retaper).
- Chacune des deux derrière sa propre confirmation forte, avec un mot différent par geste (EFFACER pour les données de parcours, SUPPRIMER pour le compte) : il faut retaper le mot exact dans un champ avant que le bouton de confirmation s'active, ce qui force à relire lequel des deux gestes on confirme et réduit le risque de confondre les deux.
- Avant de confirmer, un texte dit en clair ce qui sera effacé et ce qui reste — sur le modèle du texte déjà écrit pour « Supprimer mon compte » (`MonCompteVolet.tsx`), adapté au geste plus léger : pour « Effacer mes données de parcours », préciser que le profil et le compte restent, que les routes apprises collectives ne bougent jamais.
- Le bouton « Effacer mes données de parcours » n'apparaît que s'il y a quelque chose à effacer (au moins une activité en cache, un fichier déposé ou une calibration) — sinon il reste absent ou visiblement désactivé.

## C'est fini quand

Sur le compte réel du mainteneur (ou un compte de test hébergé) avec au moins une sortie importée et une calibration, cliquer « Effacer mes données de parcours », retaper le mot de confirmation puis confirmer vide le cache d'activités et la calibration (vérifié par un nouvel appel à l'écran d'inventaire, qui rend vide), tout en laissant la session ouverte et le profil (poids, FTP, vélos) intact. Rejouer ensuite « Supprimer mon compte » de bout en bout confirme que ce second geste, lui, ferme la session comme avant.

## Hors sujet

- Le choix « garder ou effacer mes fichiers bruts par défaut » (B5+B6, QP5) : cette fiche ajoute un geste à la demande, ponctuel ; B5+B6 pose la règle par défaut à l'arrivée des données. Les deux se croisent (le geste à la demande est la version manuelle du même effacement) mais s'écrivent et se livrent séparément.
- Les demandes d'invitation publiques et la connexion par lien (sujets 1 et 2 du même backlog « les comptes ») : hors périmètre de cette fiche.
- Toucher aux routes apprises collectives : jamais effacées par aucun des deux gestes, doctrine §10.2.
- Un export partiel (« exporter puis effacer ») : l'export ZIP existant reste accessible séparément, sans lien automatique avec l'effacement.

## Acquis techniques

- Réutilise `Cache.supprimer_tout()` (`src/ourouler/activites/cache.py`) pour vider le cache d'activités d'un propriétaire — déjà écrit, déjà testé.
- Nouvelle route API (ex. `POST /moi/donnees-parcours`), à côté de `DELETE /moi` existant dans `api/vie_privee.py` — même module, nouvelle fonction qui appelle une partie seulement de ce que fait `effacer_donnees` (cache d'activités, fichiers déposés/générés, calibration) sans toucher au profil ni fermer le compte via `DepotComptes`.
- Le mot de confirmation et son activation du bouton sont un composant partagé entre les deux gestes de `MonCompteVolet.tsx`, pas dupliqué.
- La détection « y a-t-il quelque chose à effacer » réutilise l'inventaire déjà exposé côté API plutôt que d'ajouter un nouvel appel dédié.

## Questions ouvertes

- Le nom exact de la route API et sa forme de retour (confirmation, décompte de ce qui a été effacé) — détail d'implémentation, pas produit.
- Si « Effacer mes données de parcours » doit aussi réinitialiser une calibration en cours (tâche de fond) comme le fait déjà `DELETE /moi` (verrou une seule suppression à la fois) — à vérifier au lot, probablement oui par cohérence.

## Déjà en place / Doctrine révisée

- Réglages → Mon compte (`front/src/ecrans/reglages/MonCompteVolet.tsx`) : export ZIP, changement de mot de passe, et « Supprimer mon compte » avec double confirmation par un second écran, déjà écrits, lot L9.6 (d'après `docs/inviter.md` §5). Le mot à retaper est nouveau pour les deux gestes.
- `DELETE /moi` et `vie_privee.effacer_donnees` (`src/ourouler/api/vie_privee.py`) : effacement complet + fermeture de compte, cascade DB via `DepotComptes`, déjà en service.
- `Cache.supprimer_tout()` (`src/ourouler/activites/cache.py`) : efface déjà index et fichiers bruts d'un propriétaire sans toucher au profil ni au compte — c'est exactement le geste « effacer mes données de parcours » manquant côté route API.
- QP5-a (25/09/2026) : « le premier geste [effacer mes données] en est la version à la demande » du choix garder/effacer de B5+B6 — reprise telle quelle.
- Doctrine §10.2, routes apprises collectives jamais effacées par un compte — reprise sans discussion.
- Tranché le 26/09/2026 : un mot de confirmation différent par geste (EFFACER / SUPPRIMER) ; les deux gestes groupés dans une seule zone rouge en bas de l'écran Mon compte.
