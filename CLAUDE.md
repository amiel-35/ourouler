@AGENTS.md

# Propre à Claude Code dans ce dépôt

Tout ce qui vaut pour n'importe quel agent est dans `AGENTS.md`, importé
ci-dessus. Ne s'ajoute ici que ce qui concerne Claude Code.

## Politique de modèles

- Le `model` est **obligatoire** sur chaque appel d'agent : l'omettre hérite
  silencieusement du modèle de la session.
- Le tier se choisit d'avance, selon la nature de la tâche :
  - **Sonnet**, le défaut : implémentation bien cadrée, critères
    d'acceptation clairs ;
  - **Haiku** : mécanique en masse (renommage, boilerplate, conversion de
    format) ;
  - **Opus** : jugement et algorithmes subtils (relecture, tests
    adversariaux, découpage, débogage coriace, concurrence) ;
  - **Fable** : seulement quand l'indépendance vis-à-vis du contexte courant
    est le but, et toujours en demandant d'abord.
- Ne pas monter en tier sur un aveu d'incertitude pour une tâche de
  jugement : un agent sous-dimensionné ne doute pas, il se trompe avec
  assurance.
