# Facteur compteur mesuré depuis l'écran

Type : feature
Statut : validée le 26/09/2026

## Pourquoi

Le facteur qui relie la vitesse à plat du modèle à la moyenne réelle du compteur (`Velo.facteur_compteur`) se saisit à la main dans Réglages, ou reste au défaut supposé (profil générique 10 m/km de dénivelé, 5 % d'arrêts). Amiel a déjà ce chiffre mesuré sur son historique réel, mais seulement en ligne de commande (`tests/validation/facteur_compteur_retrospectif.py`), un outil de développement qui lit le cache local directement et ne touche à rien. [déduit] Retaper à la main un nombre que le dépôt sait déjà calculer à partir de ses propres sorties est le détour que cette fiche supprime.

## Ce que je veux voir

- Dans Réglages, à côté du champ « facteur compteur » de chaque vélo, un bouton « Mesurer sur mon historique ».
- Le bouton calcule le facteur avec exactement la méthode du script existant : temps écoulé (pas le temps de mouvement), sorties extérieures d'au moins une heure et 5 km, rattachées à ce vélo par le capteur de puissance, vitesse à plat modélisée à la puissance d'endurance du cycliste avec les paramètres calibrés du vélo.
- Le résultat **pré-remplit** le champ, ne l'enregistre pas tout seul — Amiel garde la main pour l'ajuster ou revenir en arrière avant de cliquer « Enregistrer les vélos », comme aujourd'hui.
- À côté du chiffre proposé, une phrase dit d'où il sort et sur combien de sorties : « Mesuré sur N sorties extérieures d'au moins une heure, depuis le JJ/MM/AAAA. »
- Si le vélo n'a pas assez de sorties exploitables, le bouton est grisé avec la raison : « Pas assez de sorties pour mesurer (6 sur 10 nécessaires). »
- Exemple (valeurs illustratives, pas attendues) : Amiel ouvre Réglages sur le RCR, clique « Mesurer sur mon historique », voit une valeur apparaître dans le champ avec la mention du nombre de sorties, l'arrondit à son goût, enregistre.

## C'est fini quand

Sur le vrai historique d'Amiel, en prod, depuis son téléphone : il ouvre Réglages sur un vélo qui a assez de sorties (RCR ou BMC), clique « Mesurer sur mon historique », le champ se pré-remplit avec une valeur qui correspond à ce que rend `facteur_compteur_retrospectif.py` sur les mêmes données (à l'arrondi près), il enregistre, et retrouve ce facteur appliqué dans l'écran FTP (`EcranFtp.tsx`) à sa prochaine visite.

## Hors sujet

- Pas de re-mesure automatique périodique : le bouton se clique, il ne tourne pas en tâche de fond.
- Pas de mesure proposée à un invité qui n'a pas encore assez d'historique : le bouton reste grisé, pas de faux chiffre.
- Ne change rien à la formule du défaut supposé (`facteur_compteur_defaut`) : elle reste le filet pour qui n'a rien mesuré.

## Acquis techniques

- Seuil minimal avant d'activer le bouton : 10 sorties exploitables, aligné sur le minimum de la calibration à l'écran (L9.4), pour qu'une seule règle soit visible par le cycliste (tranché le 26/09/2026 ; une note du 23/09 citait 8).
- Aucun appel réseau : la mesure lit le cache d'activités du propriétaire, exactement comme le script CLI.
- Le calcul est un pur calcul (`physique/`), appelé depuis une nouvelle route qui ne fait que résoudre le propriétaire et sa `Config`, sur le modèle de `api/routes/calibrations.py` (règle absolue 2). Le rattachement au vélo par capteur (`activites.inventaire.rattacher_velo`) et le filtre par durée/distance sont ceux du script existant, factorisés au même endroit pour ne pas exister deux fois.
- Pas de tâche de fond nécessaire : contrairement à la calibration CdA/Crr (L9.4, réseau et recherche numérique), cette mesure est un calcul immédiat sur l'index déjà en cache — réponse synchrone.
- Le script CLI `facteur_compteur_retrospectif.py` reste, pour Amiel en dépannage ou en audit ; l'écran appelle la même fonction, pas une réécriture.
- Le bouton « Mesurer » pré-remplit le champ, modifiable avant « Enregistrer » — Amiel garde la main sur le dernier mot avant que le chiffre s'applique à ses séances.

## Questions ouvertes

Aucune : Q54 est close par la décision retenue sur le comportement du bouton.

## Déjà en place / Doctrine révisée

- `config.Velo.facteur_compteur`, éditable dans `front/src/ecrans/reglages/ListeVelos.tsx`.
- Défaut serveur affiché sur champ vide via `GET /profil/zones` (`valeurs_liees.facteur_compteur`).
- `tests/validation/facteur_compteur_retrospectif.py` : la mesure existe déjà, en CLI/dev seulement.
- Q54 (`facteur_compteur_retrospectif.py`) : la mesure sur historique est l'outil, seule son exposition à l'écran manquait — appliqué dans cette fiche.
- Tranché le 26/09/2026 : le bouton « mesurer » pré-remplit le champ, modifiable avant « Enregistrer ». Q54 est close par cette décision.
