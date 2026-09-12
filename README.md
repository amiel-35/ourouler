# ourouler — où rouler ?

Bibliothèque Python et ligne de commande pour cyclistes avec capteur de
puissance : où va-t-il pleuvoir dans les prochaines heures autour de chez
moi, dans quelle direction partir, sur quel parcours de la bonne durée,
cohérent avec la séance du jour, et avec quelle tenue.

État : **en cadrage** (septembre 2026). Voir `docs/cadrage.md` pour le besoin,
`doctrine_architecture.md` pour les choix, `docs/plan_sprints_agents.md`
pour l'avancement.

## Installation (développement)

```bash
uv sync --extra dev
cp config.example.toml ~/.config/ourouler/config.toml   # puis renseigner
uv run ourouler --help
```

Les données et les clés d'API restent chez l'utilisateur : rien de
personnel n'entre dans ce dépôt.

Licence MIT.
