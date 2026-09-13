# Relecture Fable du lot physique (sprint 3, L3.3) — point critique

Relu le 13/09/2026 par le superviseur (Fable), sur `physique/modele.py`,
`physique/calibration.py` et le rapport de calibration réel (RCR : MAE
5,5 %, BMC : 4,8 % sur sorties non vues ; CdA en butée basse 0,18 pour les
deux vélos avec Crr ≈ 0,010-0,011). Verdict : **à corriger avant de s'en
servir pour un CLM ou pour extrapoler**, OK pour la colonne « temps » d'une
boucle à allure habituelle.

## Ce qui est bon

- Bilan de Martin & al. réduit à l'essentiel, traînée en `v_air·|v_air|`
  (écart au contrat justifié), bissection bornée, réciprocité vérifiée à
  0,1 W, temps *en mouvement* dit partout, densité de l'air mesurée.
- Calibration **linéaire exacte** en (CdA, Crr) avec coefficients tirés du
  modèle lui-même : aucune formule recopiée, aucune divergence possible.
- Validation sur sorties non vues, à la puissance moyenne en mouvement, avec
  la mesure qui justifie ce choix (profil par 100 m : 15,7 % ; moyenne :
  5,0 %). Deux passes avec détection des pelotons au résidu.
- Tout ce qui est incertain est dit (bornes atteintes, incertitude
  optimiste, vent à 10 m).

## Le défaut : pourquoi CdA tombe en butée

L'agent observe que, sur les tronçons plats sans vent, la puissance croît
**presque linéairement** avec la vitesse (120 W à 24, 151 à 27, 167 à
30 km/h) au lieu de v³. Ce n'est pas la physique qui est linéaire, c'est la
régression qui est **atténuée** : le régresseur aérodynamique
`½ρ·v_air·|v_air|·v` est construit avec un vent **mesuré avec erreur**
(archive à 10 m de hauteur, maille de plusieurs kilomètres, interpolée à
l'heure). Une erreur sur un régresseur biaise son coefficient **vers zéro**
(dilution de régression) : CdA descend, et Crr, dont le régresseur `m·g·v`
est presque sans erreur, absorbe le reste. Deux indices le confirment dans
le rapport même : le sous-ensemble « vent d'archive presque nul » rend un
couple plausible (CdA 0,26 / Crr 0,0093), et le meilleur ajustement
s'obtient avec un vent ×0,25-0,5.

Un second facteur : le filtre `|Δv| < 0,3 m/s` (contrat §3, ma faute) jette
95 % des tronçons et ne garde que des tronçons « stationnaires » qui ne
sont pas un échantillon neutre de la sortie (faux plats descendants,
vent arrière non capturé), ce qui nourrit le même biais.

## Corrections demandées — réduites après l'avis du mainteneur

Amiel (13/09) : « on va trop dans le détail pour un coureur amateur ; mon
CLM va plus vite sur le plat grâce aux prolongateurs, on doit pouvoir voir
sur des segments identiques la différence approximative, à la louche 25 à
30 W ». Le modèle sert à prédire une durée — il le fait à 5 %. On ne
cherche plus à séparer CdA et Crr ; on garde deux corrections simples et
on remplace la décomposition par une **mesure directe**.

1. **Vent à hauteur du cycliste.** L'archive et la prévision sont à 10 m ;
   à 1,5 m en bocage (rugosité ≈ 0,1 m) le profil logarithmique donne
   ≈ 0,6. `FACTEUR_VENT_HAUTEUR = 0.6`, constante nommée, appliquée des
   deux côtés (calibration ET simulation) pour rester cohérent.
2. **Terme d'énergie cinétique** dans la part connue de chaque tronçon
   (`m·(v_fin² − v_début²) / (2·Δt)`) et `DELTA_V_MAX_MS` relâché à 1,0 :
   on garde des milliers de tronçons au lieu de 886, sans exiger la
   stationnarité. Re-vérifier MAE ; si elle ne s'améliore pas, revenir.
3. **Comparaison RCR / BMC sur tronçons identiques** — nouvelle commande
   `ourouler comparer --velos RCR BMC` : sur les mailles de
   `routes_connues.sqlite` roulées avec les deux vélos, à pente ≈ 0 et
   vitesse comparable (classes de 2 km/h), la différence de puissance
   moyenne par classe de vitesse, avec le nombre de tronçons de chaque
   côté. Résultat attendu de l'ordre de « BMC : −25 à −30 W à 30 km/h ».
   C'est la réponse à la question du mainteneur, mesurée, sans modèle.
4. **Fichiers multisport (Q10)** écartés de la calibration avec le motif
   « multisport ».
5. `boucle` : heure de passage météo à la vitesse du modèle quand la
   calibration existe ; les tests de `boucle` font un `chdir` sur
   `tmp_path` (ils écrivaient un GPX dans le dossier courant).

Abandonné : la sélection entre trois ajustements, et la plausibilité
physique de CdA/Crr comme critère. Le rapport de calibration affiche à la
place la **résistance totale à 27 et 35 km/h** par vélo, qui est ce que les
données mesurent bien.

## Ce qui reste à la main du mainteneur

- **Q8** : puissance de la colonne « temps » d'une boucle — 65 % de la FTP
  par défaut (proposé), ou la puissance de la séance du jour quand S4
  existera.
- **Q9** : close dans l'esprit ci-dessus — on ne sépare plus CdA et Crr.
