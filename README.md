# ourouler — où rouler ?

« Je vais rouler : où va-t-il pleuvoir, et quel parcours de la bonne durée,
cohérent avec ma séance ? » ourouler répond à ces deux questions, en ligne de
commande ou dans une interface web.

*In English:* ourouler is a planning tool for cyclists who ride with a power
meter. It shows rain and wind by direction around your starting point, then
builds a loop of the right length that fits the day's planned workout, as a
GPX file. The project is written in French and licensed under AGPL-3.0-or-later.

## Ce que ça fait

- **La météo par direction.** Pluie, vent et ressenti au nord, au sud, à
  l'est, heure par heure, avec un second modèle météo affiché en désaccord
  plutôt que moyenné.
- **Une boucle de la bonne distance**, dans la direction sèche, au choix
  vent de face à l'aller, avec des routes pondérées par vos sorties passées
  (`ourouler routes`). Elle s'exporte en GPX.
- **La séance posée sur le terrain.** Les blocs de la séance du jour tombent
  là où la route s'y prête : pas en ville, pas en descente pour un bloc
  intense. Une carte HTML montre où commence chaque bloc.
- **Un temps de parcours réaliste**, calculé par un modèle physique calibré
  sur vos propres sorties, vent compris.
- **La tenue à mettre**, d'après la météo prévue sur le parcours.
- **Deux vélos comparés** à puissance égale, mesure faite sur vos sorties.

## Pour qui, et où en est le projet

Pour un cycliste qui roule avec un capteur de puissance. Un compte
intervals.icu est facultatif : il apporte l'historique et la séance du jour ;
sans lui, on importe ses fichiers FIT, GPX ou TCX, ou une séance `.zwo`.

Version actuelle : 0.9.6 (voir le [journal des changements](CHANGELOG.md)).
Un service hébergé tourne, sur invitation seulement. Le dépôt est en cours
d'ouverture : la 1.0.0 viendra avec l'ouverture publique.

## Démarrage rapide

Il faut Python 3.12 ou plus et [uv](https://docs.astral.sh/uv/).

```bash
uv sync --extra dev
mkdir -p ~/.config/ourouler
cp config.example.toml ~/.config/ourouler/config.toml
uv run ourouler config        # relit la configuration et dit ce qui manque
```

Renseignez dans ce fichier votre point de départ, votre masse et votre FTP,
vos vélos et, si vous en avez une, votre clé d'API intervals.icu.

Ce qui marche selon ce que vous avez :

- **Rien de plus** : `meteo` fonctionne tout de suite, sans clé.
- **Un serveur [BRouter](https://github.com/abrensch/brouter)** (le moteur de
  tracé, à héberger soi-même, renseigné dans `[brouter] url`) : `boucle` et
  `sortie`. Sans lui, ces commandes s'arrêtent et le disent. Recette :
  [`docs/brouter.md`](docs/brouter.md).
- **Une séance** : la séance du jour vient d'intervals.icu ; sans compte,
  `sortie --fichier-seance ma_seance.zwo`.

```bash
uv run ourouler meteo --heure-depart 08:00 --horizon 6
uv run ourouler boucle --distance 60 --direction S --sortie boucle.gpx
uv run ourouler sortie --heure-depart 09:30 --carte sortie.html
```

Chaque commande accepte `--json`, et `uv run ourouler --help` les liste
toutes.

L'interface web vit dans `front/` et ne parle qu'à l'API :

`--extra dev` installe aussi ce qu'il faut pour l'API.

```bash
uv run ourouler api --port 8000              # dans un terminal
cd front && npm ci && npm run dev            # dans un autre, puis http://localhost:5180
```


## Pour aller plus loin

- [Guide de la ligne de commande](docs/guide_ligne_de_commande.md) : chaque
  commande, ses options, les limites connues.
- [Obtenir un serveur BRouter](docs/brouter.md) : la recette d'installation
  du moteur de tracé.
- [La démarche](docs/demarche.md) : d'où vient le projet, ce qui a été
  mesuré, essayé, abandonné.
- [Doctrine d'architecture](doctrine_architecture.md) : les choix
  structurants et leurs raisons.
- [Journal des changements](CHANGELOG.md).
- [L'interface web](front/README.md) : sa construction et ses règles.

## Licence

[AGPL-3.0-or-later](LICENSE).
