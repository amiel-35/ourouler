# Sprint 11 — bilan : trois gestes quotidiens du cycliste

Du 27/09/2026 au 27/09/2026. Relectures : Fable ; implémentation : Sonnet.
Livré en préprod ; en prod avec la prochaine version.

## Prévu

Trois fiches et une anomalie ajoutée par dérogation : la séance du jour à
l'heure réelle, trois boucles retenues d'office, le partage du GPX depuis
l'écran des boucles libres, et le bouton retour du navigateur qui quittait
l'appli.

## Réalisé

| Élément | Issue | PR |
|---|---|---|
| Séance du jour à l'heure réelle | livrée, vérifiée par le mainteneur sur iPhone | #123 |
| Trois boucles retenues d'office | livrée, vérifiée par le mainteneur ; 83 % → 100 % de demandes à trois propositions sur ses données | #124 |
| Bouton retour du navigateur | livré, vérifié par le mainteneur sur iPhone | #125 |
| Partage GPX des boucles libres | abandonné : bouton retiré des deux écrans | #122, #127, #128 |

## Écarts

- **Le partage GPX n'a jamais atteint Garmin Connect sur iPhone.** Le bouton
  n'ouvrait pas la feuille de partage (le téléchargement préalable consommait
  le geste que Safari exige, #127) ; une fois ouverte, la feuille ne
  proposait pas Connect. Le bouton, déjà en prod sur l'écran de proposition
  depuis le sprint 5, n'avait jamais été vérifié sur un vrai téléphone. Il
  est retiré ; le lien « Télécharger le GPX » reste.
- **Trois boucles : le coût est réel.** Appels BRouter moyens 9,1 → 11,2 ;
  jusqu'à ~23 s sur un cas défavorable ; délai du verrou du chemin `ancien`
  porté à 60 s. Deux lenteurs du serveur BRouter (41 et 45 s) restent
  inexpliquées.
- **Une relecture a tout fait reprendre** : l'heure réelle confondait heure
  par défaut et heure saisie (« Demain » partait à 14:45). Repris selon la
  proposition du relecteur avant le merge.
- **Hors sprint, trouvé en route** : un compte sans profil calcule depuis un
  départ fictif à (0, 0) (BRouter « datafile E0_N0.rd5 not found ») ; un zéro
  négatif propre à Linux cassait des références en CI.

## Ce qu'on en apprend

- Un critère « sur un vrai téléphone » ne se coche pas en test : le partage
  GPX le prouve, livré au sprint 5 et jamais vérifié.
- Une relecture indépendante par lot a évité trois défauts en prod
  (défaut/saisie de l'heure, perte d'un résultat sur panne BRouter, double
  entrée d'historique).
- Écrire, relire, corriger, merger : quatre fiches en une journée, deux agents
  à la fois.
