# Sprint 12 — bilan : le cycliste décide de ses données, le mainteneur administre sans ssh

Du 27/09/2026 au 28/09/2026. Relectures : Fable ; implémentation : Sonnet,
dans des sessions cloud.
Livré en préprod ; en prod avec la 0.12.0, qui réunit les sprints 11 et 12.

## Prévu

Trois fiches et une anomalie ajoutée par dérogation : une calibration sur peu
de sorties qui se dit « provisoire », un formulaire public de demande
d'invitation avec une administration hors d'Internet, le choix de garder ou
non ses fichiers d'origine, et le départ fictif (0, 0) d'un compte sans
départ.

## Réalisé

| Élément | Issue | PR |
|---|---|---|
| Calibration provisoire | livrée, **non vérifiée par le mainteneur** | #133 |
| Demande d'invitation et administration | livrée, **non vérifiée** ; le courriel d'invitation n'est pas arrivé en préprod | #135, #138, #140 |
| Garder ou non ses fichiers d'origine | livrée, **non vérifiée** | #136 |
| Départ par défaut sur Paris | livrée, **non vérifiée** ; deux passes de relecture | #142 |

## Écarts

- **Sprint clos sans les vérifications du mainteneur en préprod**, à sa
  demande, faute de temps. Les quatre éléments sont passés en `livre` sur la
  foi de la CI (tests Postgres compris) et des relectures. Les vérifications
  restent à faire avant ou juste après la mise en prod de la 0.12.0 : c'est
  le premier sprint où l'on déroge à la règle de la vérification humaine.
- **Le courriel d'invitation n'est pas arrivé en préprod** (#135). L'alerte
  au mainteneur est bien partie ; le courriel à l'invité non. Les journaux du
  projet sont désormais visibles dans ceux du conteneur (#140) pour chercher
  la cause. Le même jour, une invitation lancée en prod (0.11.0) a été
  acceptée par le relais : le défaut est peut-être propre à la configuration
  de la préprod, rien ne le prouve encore.
- **L'administration pouvait faire tomber l'API** au démarrage, et les
  migrations n'étaient pas appliquées au démarrage du conteneur : corrigé en
  route (#138).
- **Le départ fictif, trouvé au sprint 11, est entré par dérogation.** La
  première version corrigeait le cas nominal ; la relecture a trouvé un
  départ partiel qui produisait un point hybride (un nom réel posé sur les
  coordonnées du repli), un champ du profil hors contrat OpenAPI, et
  l'absence de test d'API du scénario du bug. Tout repris avant le merge.

## Ce qu'on en apprend

- Une relecture qui sonde de bout en bout (application hébergée bouchonnée,
  vraies requêtes) trouve ce qu'une lecture du diff ne trouve pas : le point
  hybride n'était visible qu'en envoyant un profil partiel.
- Clore sans vérification humaine est possible parce que la CI couvre
  Postgres et l'image ; mais l'anomalie du courriel montre ce que la CI ne
  voit pas : la configuration réelle d'un déploiement.
- Le travail en session cloud tient la cadence : développement, relecture et
  merge sans poste local ; seuls les gestes sur le serveur et la prod restent
  à faire depuis le poste du mainteneur.
