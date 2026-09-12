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
   C'est là qu'on en est (sprint 2, septembre 2026).
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
| `ourouler inventaire` | lecture FIT / GPX / TCX, cache local, inventaire des sorties par vélo et par mois, synchronisation Intervals.icu | sprint 1 — **vérifié sur vraies données (13/09/2026)** |
| `ourouler boucle` | boucle de la bonne distance dans la direction sèche, vent de face à l'aller, GPX | sprint 2 — **vérifié pour de vrai** sur BRouter auto-hébergé + Open-Meteo |
| `ourouler sortie` | séance du jour ↔ terrain : modèle physique calibré par vélo, choix de la boucle, résumé, tenue | plus tard |
| envoi vers Garmin Connect | | plus tard |

Les trois commandes ont tourné sur les vraies données du mainteneur, et pas
seulement sur des fixtures — c'est la règle 4 de `CLAUDE.md` : un lot non
vérifié le dit en toutes lettres, un lot vérifié dit quand et sur quoi.

- `ourouler meteo` : Open-Meteo, gratuit et sans clé, sur le point de départ
  de la configuration.
- `ourouler inventaire` : le 13/09/2026, sur le compte Intervals.icu réel du
  mainteneur — synchronisation complète, puis inventaire des sorties vélo
  avec les deux vélos de route séparés par leur capteur de puissance. Une
  seconde synchronisation n'ajoute rien et ne retélécharge rien.
- `ourouler boucle` : sur le serveur BRouter auto-hébergé et Open-Meteo, avec
  écriture du GPX et relecture de ce GPX par `--gpx`.

## Limites connues

Ce que le mainteneur doit savoir avant de lire un chiffre.

- **Activités multisport.** Intervals découpe un triathlon en segments qui
  citent le **même** fichier d'origine. Chaque segment a sa propre ligne de
  cache depuis le sprint 2, et le fichier brut est partagé ; une version
  antérieure n'en gardait qu'une, ce qui faisait disparaître la partie vélo
  de quatre triathlons. Les segments nommés « Triathlon », « Transition » ou
  « OpenWaterSwim » restent hors de l'inventaire vélo : seuls les segments
  que la source annonce comme du vélo y entrent.
- **D+ moteur ou D+ relu, ce n'est pas le même chiffre.** BRouter donne son
  « filtered ascend » ; relire un GPX recalcule le dénivelé depuis les
  altitudes, avec un seuil de 2 m. Mesuré sur une même boucle de 43 km :
  216 m côté moteur, 287 m à la relecture, soit +33 %. Les deux sont
  affichés avec leur provenance — « 216 m (moteur) », « 287 m (gpx relu) » —
  plutôt que moyennés ou choisis en silence.
- **Classes de trafic provisoires.** Le classement d'une route en
  « trafic » ou « calme » suit les tags `highway` d'OpenStreetMap, et la
  pondération (un kilomètre à trafic en coûte trois) est un arbitrage, pas
  une mesure. `secondary` compte aujourd'hui comme du trafic alors qu'une
  part importante des routes réellement empruntées en relève : le curseur
  reste à régler. Les kilomètres que le classement ne sait pas trancher sont
  affichés à part (`km_non_classe`) plutôt que fondus dans « calme ».

## Installation (développement)

```bash
uv sync --extra dev
mkdir -p ~/.config/ourouler && cp config.example.toml ~/.config/ourouler/config.toml
uv run ourouler config
```

Renseigner ensuite le point de départ, le cycliste, les vélos et, pour la
synchronisation, la clé d'API Intervals.icu. Les données et les clés restent
chez l'utilisateur : rien de personnel n'entre dans ce dépôt — dans le code,
les tests et la configuration d'exemple. Le fichier de configuration réel
n'est jamais commité ; `config.example.toml` ne porte que des valeurs
inventées, et un test le mesure (`tests/test_invariants.py`). La
documentation de cadrage, elle, contient encore des chiffres réels du
mainteneur : à trancher avant l'ouverture du dépôt (Q6).

## Documentation

- `docs/cadrage.md` — le besoin d'origine.
- `doctrine_architecture.md` — les choix structurants et leurs raisons.
- `docs/plan_sprints_agents.md` — sprints, critères d'acceptation, équipe d'agents.
- `docs/questions_mainteneur.md` — ce qui attend une décision.

Licence MIT.
