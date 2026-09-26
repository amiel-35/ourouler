<!--
Reprend la liste « Proposer une PR » d'AGENTS.md et CONTRIBUTING.md.
Supprimer les sections qui ne s'appliquent pas et dire pourquoi (« pas de
changement de comportement », « pas de fichier de référence touché »...).
-->

## Quoi et pourquoi

Ce que la PR change, et pourquoi.

## Comment c'est vérifié

- [ ] `uv run ruff check .`
- [ ] `uv run pytest -q` (suite complète, pas un sous-ensemble)
- [ ] `cd front && npm run verifier`
- [ ] Une ligne dans `CHANGELOG.md` sous « Non publié », du point de vue du
      cycliste — ou explication de pourquoi la PR n'en a pas besoin
      (documentation interne, outillage sans effet visible).
- [ ] Si un fichier de référence a changé (`tests/caracterisation/openapi.json`,
      sorties de référence, formats persistés), la différence est expliquée
      ci-dessus : ce n'est jamais régénéré par réflexe.
- [ ] Si la PR contredit `doctrine_architecture.md`, la question est posée
      ci-dessus, et la doctrine est mise à jour dans la même PR si elle est
      tranchée.

## Fichiers de référence régénérés (le cas échéant)

Lesquels, et pourquoi.
