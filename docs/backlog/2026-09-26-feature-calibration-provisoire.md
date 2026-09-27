# Incertitude affichée sur peu de sorties de calibration

Type : feature
Statut : validée le 26/09/2026

## Pourquoi

Constaté au sprint 9 (25/09/2026) : sur 40 sorties récentes du mainteneur, le CdA calculé (0,408) et son erreur de validation (5,6 % sur seulement 10 sorties de validation) diffèrent nettement du chiffre obtenu sur tout l'historique (0,364, 3,6 % sur 25 sorties). QP7 (25/09/2026) tranche : Amiel doit voir l'erreur de validation et le nombre de sorties à côté du CdA, avec « personne n'est bloqué, et on dit ce que l'on sait : l'instabilité à 10 sorties est une information, pas une raison de refuser ».

## Ce que je veux voir

- Sur la fiche vélo (`CalibrationVelo.tsx`) : le CdA reste en second plan (déjà le cas), et juste à côté de la phrase déjà affichée (« sur N sorties [...] le temps prévu s'écarte en moyenne de X % »), un badge ou un mot « provisoire » apparaît quand `n_validation` est sous 20 sorties de validation. Ce seuil est le double du minimum de 10 sorties exploitables déjà exigé pour calibrer (L9.4), et l'écart mesuré au sprint 9 (5,6 % à 10 sorties contre 3,6 % à 25) montre que l'instabilité se réduit nettement avant ce palier.
- Le mot « provisoire » est expliqué en survol ou en une ligne : « peu de sorties ont servi à vérifier ce chiffre, il peut encore bouger en important plus d'historique ».
- Rien ne change dans le calcul lui-même : aucune calibration existante n'est invalidée, aucun seuil minimal de sorties pour *calibrer* ne bouge (10 exploitables reste le plancher posé par L9.4).

## C'est fini quand

Sur l'historique réel d'Amiel, calibré successivement à 10, 30 et toutes les sorties disponibles (comme déjà fait au sprint 9), l'écran affiche à chaque fois le CdA, l'erreur de validation, le nombre de sorties, et marque « provisoire » exactement sur les tirages sous 20 sorties de validation — les trois résultats sont rapportés dans la PR comme le critère le demande.

## Hors sujet

- Remonter le minimum de sorties exploitables pour calibrer (option QP7-b, écartée) — on n'empêche personne de calibrer, on dit seulement ce qu'on sait.
- La fourchette en watts à 30 km/h plutôt qu'un pourcentage (option QP7-c, écartée) — la fourchette porte-à-porte existe déjà séparément et n'est pas remplacée.
- La calibration qui garde les sorties de club par erreur (B10) et le changement d'entrée de la calibration vers le dérivé (B6) — sujets distincts, cette fiche suppose B6 fait avant d'être vérifiée en prod, comme décidé en préparation de sprint.

## Acquis techniques

- Le seuil (20 sorties de validation) se compare directement à `n_validation`, déjà calculé et servi par l'API (`api/calibrations.py::resume()`) : pas de nouveau calcul, seulement une condition d'affichage côté front sur une valeur déjà disponible.

## Questions ouvertes

Aucune.

## Déjà en place / Doctrine révisée

- `src/ourouler/physique/calibration.py` — la validation expose déjà `.mae`, `.n`, `.biais` : l'erreur de validation, le nombre de sorties de validation et le biais sont calculés.
- `src/ourouler/stockage/calibrations.py` — `mae`, `n_validation` sont déjà écrits et relus dans `calibration.json` (format 0d compatible).
- `src/ourouler/api/calibrations.py::resume()` — la route sert déjà `erreur_validation` (mae), `n_validation`, `n_sorties`, `biais_validation` et la fourchette porte-à-porte pour chaque vélo.
- `front/src/composants/CalibrationVelo.tsx::Resultat` — affiche déjà « Sur N sorties que le calcul n'avait pas vues, le temps prévu s'écarte en moyenne de X % du temps réel » quand `erreur_validation` et `n_validation` sont présents.
- `docs/journal/sprints/plan_sprints_agents.md`, clôture sprint 9 (L9.4) — mesure réelle déjà faite sur l'historique du mainteneur : 40 sorties récentes → CdA 0,408, MAE 5,6 % sur 10 de validation ; 102 sorties (100 exploitables) → CdA 0,364, MAE 3,6 %, biais −1,8 % (n=25) ; instabilité du chiffre selon la taille de l'échantillon déjà constatée et chiffrée.
- QP7 (25/09/2026), option (a) tranchée : afficher l'erreur de validation et le nombre de sorties à côté du chiffre, avec « provisoire » sous un seuil. Cette fiche ne rouvre pas le choix de la forme (une fourchette de watts, option (c), est écartée) — elle porte sur le seuil du mot « provisoire ».
- Préparation sprints 11/12 : cette fonctionnalité vient après le lot 8 et après B6 (B6 change l'entrée de la calibration — dérivé au lieu du brut) ; placé au sprint 12 dans la proposition, dépend donc du calendrier de B6.
- Tranché le 26/09/2026 : le mot « provisoire » s'affiche sous 20 sorties de validation.
