# Sprint 9 — Inviter pour de vrai

Cadré le 25/09/2026, à la demande du mainteneur : « refaire une passe du
projet pour finaliser et pouvoir inviter des gens », et « j'ai encore du mal
avec le modèle vélo ». Ce sprint reprend ce que la clôture du sprint 8 a
renvoyé ici nommément (L8.1, la boucle de correction, le coût par
utilisateur) et **code** le recalage Crr/CdA que la note du 23/09 a mesuré à
la main sans l'écrire (plan, section « le porte à porte ignore le relief »,
jusqu'au « Récapitulatif du 23/09 »).

## Ce qui est déjà vrai (vérifié le 25/09)

Compte sur invitation (`ourouler inviter`, lien à usage unique, courriel
Brevo), session par cookie, isolation par propriétaire testée route par
route, accueil qui mène à une boucle même sans Intervals ni capteur, export
et suppression RGPD. `uv run pytest` : 4767 passés ; `npm test` : 249.

## Les lots

### L9.1 — le modèle vélo : Crr par pneu, CdA cherché, porte à porte en fourchette

La note du 23/09 a trouvé la méthode qui converge : **Crr fixé par la
littérature selon le pneu, CdA seul cherché** ; la calibration libre à deux
paramètres dérive (CdA et Crr mal séparés : RCR 0,222/0,0106, BMC
0,220/0,0084, à l'envers du matériel). Et le porte à porte devient
`temps_estime_s × [bas, haut]`, centiles 25-75 du ratio réel/simulé.

- Un champ `pneu` facultatif sur le vélo (catégories de littérature, Crr
  sourcé) ; sans pneu, le Crr de l'usage comme aujourd'hui.
- `ourouler calibrer` fixe le Crr du pneu et ne cherche que le CdA ; la
  calibration libre reste accessible par option explicite.
- `calibration.json` porte la fourchette du porte à porte (centiles 25, 50,
  75 du ratio réel/simulé, sorties à moins de 50 % de signal de groupe, et
  leur nombre).
- `temps_ecoule` rend une fourchette ; un vélo sans calibration reçoit une
  fourchette par défaut **qui se dit comme telle**.
- Le front affiche « entre 4 h 23 et 4 h 38 », avec sa provenance.

*Acceptation, sur les vraies données du mainteneur* : CdA dans les
fourchettes de littérature (route 0,27-0,36 ; CLM 0,20-0,26) ; erreur de
validation non dégradée par rapport au récapitulatif (RCR ≤ 5 %, BMC ≤ 3 %) ;
fourchettes à ±0,02 de celles de la note (RCR × 1,015-1,072, BMC ×
1,057-1,095) ou l'écart expliqué.

### L9.2 — importer son historique (L8.1)

Un invité sans Intervals dépose ses sorties : fichiers `.fit`, `.gpx`,
`.tcx` (éventuellement `.gz`), ou l'archive d'export Strava ou Garmin, en
une ou plusieurs fois ([[Q62]]). Route authentifiée, cloisonnée par
propriétaire, bornée (taille, nombre de fichiers, décompression, chemins).

*Acceptation* : un compte A importe, B ne voit rien ; une archive hostile
(bombe de décompression, chemin `../`, fichier corrompu) est refusée ou
ignorée avec un motif lisible ; import réel vérifié sur quelques FIT du
mainteneur en local.

### L9.3 — le coût par utilisateur

Cache mutualisé des prévisions Open-Meteo (même point arrondi, même heure :
un seul appel pour tous) et un quota journalier de générations par compte,
réglable côté service, avec un refus lisible (`quota_atteint`).

### L9.4 — la boucle de correction, depuis l'écran

Un compte hébergé avec capteur de puissance lance sa calibration (L9.1)
sans la ligne de commande du mainteneur. Sans capteur ou sans assez de
sorties, un refus qui dit quoi faire. Dépend de L9.1 et L9.2.

### L9.5 — le mode d'emploi de l'invitation

`docs/inviter.md` : ce que le mainteneur fait (commande, prérequis de
déploiement dont Q66a), ce que l'invité voit, ce qui reste générique.

## Hors périmètre

Passkey, Google/Apple, Postgres pour les profils, stockage objet, la
fenêtre glissante des sans-capteur (sa mesure demande des sorties sans
capteur que le dépôt n'a pas), [[Q53]], [[Q65]].
