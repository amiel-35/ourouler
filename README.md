# ourouler — où rouler ?

Pour cyclistes avec capteur de puissance. La question de départ : *« je vais
rouler ; au nord, au sud ou à l'est, où va-t-il pleuvoir ? »* — puis un
parcours de la bonne durée dans la bonne direction, cohérent avec la séance
du jour, avec la tenue à mettre, poussé sur le compteur.

## Où ça va

La cible est un **service hébergé avec une interface web** : chacun se crée
un compte, renseigne son profil (puissance, point de départ habituel, vélos),
importe ses données (FIT / GPX / TCX, Intervals.icu…) et obtient la météo par
direction, une boucle adaptée et sa sortie du jour.

Le chemin pour y arriver, dans cet ordre, sans brûler d'étape :

1. **Une bibliothèque Python et une ligne de commande** qui couvrent d'abord
   le besoin du mainteneur, premier utilisateur, sur ses vraies données.
   C'est là qu'on en est (sprint 1, septembre 2026).
2. **Une API** au-dessus du même cœur : la CLI n'est qu'un adaptateur, l'API
   en sera un second.
3. **Le front web** et les comptes.

Le cœur est écrit dès aujourd'hui pour ça : il ne lit ni fichier local ni
variable d'environnement, il reçoit un profil et des connecteurs, et chaque
commande sait rendre du JSON. Détail des choix : `doctrine_architecture.md`.

## Ce que fait la ligne de commande

| Commande | Rôle | État |
|---|---|---|
| `ourouler meteo` | pluie, vent et ressenti par direction et par heure autour du point de départ (Open-Meteo, AROME 1,3 km + second modèle en indice de confiance) | sprint 1 |
| `ourouler inventaire` | lecture FIT / GPX / TCX, cache local, inventaire des sorties par vélo et par mois, synchronisation Intervals.icu | sprint 1 |
| `ourouler boucle` | boucle de la bonne distance dans la direction sèche, vent de face à l'aller, GPX | sprint 2 |
| `ourouler sortie` | séance du jour ↔ terrain : modèle physique calibré par vélo, choix de la boucle, résumé, tenue | plus tard |
| envoi vers Garmin Connect | | plus tard |

## Installation (développement)

```bash
uv sync --extra dev
mkdir -p ~/.config/ourouler && cp config.example.toml ~/.config/ourouler/config.toml
uv run ourouler config
```

Renseigner ensuite le point de départ, le cycliste, les vélos et, pour la
synchronisation, la clé d'API Intervals.icu. Les données et les clés restent
chez l'utilisateur : rien de personnel n'entre dans ce dépôt.

## Documentation

- `docs/cadrage.md` — le besoin d'origine.
- `doctrine_architecture.md` — les choix structurants et leurs raisons.
- `docs/plan_sprints_agents.md` — sprints, critères d'acceptation, équipe d'agents.
- `docs/questions_mainteneur.md` — ce qui attend une décision.

Licence MIT.
