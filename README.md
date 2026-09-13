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
   C'est là qu'on en est (sprint 3, septembre 2026).
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
| `ourouler boucle` | boucle de la bonne distance dans la direction sèche, vent de face à l'aller, GPX | sprint 2, enrichi au sprint 3 (temps du modèle calibré, poids appris, « connu % », antennes) — **vérifié pour de vrai** sur BRouter auto-hébergé + Open-Meteo |
| `ourouler routes` | apprend sur vos sorties passées quelles routes vous acceptez (rejeu dans BRouter), et en tire les poids du score | sprint 3 — **vérifié pour de vrai** sur 154 sorties rejouées |
| `ourouler calibrer` | ajuste CdA et Crr d'un vélo sur les sorties réelles (vent d'archive compris) et mesure l'erreur de temps sur des sorties non vues | sprint 3 — **vérifié sur vraies données (13/09/2026)** |
| `ourouler simuler` | temps en mouvement d'un GPX à puissance tenue, avec le modèle calibré et le vent prévu | sprint 3 — **vérifié** sur une boucle générée |
| `ourouler comparer` | de combien un vélo va plus vite que l'autre **à puissance égale**, mesuré sur des séries plates sans arrêt, sans modèle physique | sprint 3 — **vérifié sur vraies données (13/09/2026)** |
| `ourouler seance` | la séance planifiée du jour (Intervals.icu), étape par étape, avec la longueur de route que chaque bloc demande et celle qu'il faut au-delà pour faire demi-tour pendant la récupération | sprint 4 — **vérifié sur vraies données (13/09/2026)** |
| `ourouler sortie` | séance du jour ↔ terrain : boucles candidates, placement des blocs, tableau trié par note de placement puis pluie, GPX, tenue et **carte HTML de vérification** (tracé, blocs colorés, profil d'altitude) | sprint 4 — **vérifié sur vraies données (13/09/2026)**, météo absente sur les jours passés (hors horizon de prévision) |
| envoi vers Garmin Connect | | plus tard |

Ces commandes ont toutes tourné sur les vraies données du mainteneur, et pas
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
- `ourouler sortie` : le 13/09/2026, sur les deux séances de coach de référence
  (08/02/2026 « 2x20' + 4x3' », 22/04/2026 « 4x8 SV1 outdoor »), quatre boucles
  candidates chacune, GPX et carte écrits. Pluie, vent et tenue ne sortent que
  pour un jour dans l'horizon de prévision : sur un jour passé, les colonnes
  météo disparaissent et le tableau le dit.
- `ourouler routes` : le 13/09/2026, 154 sorties extérieures rejouées dans
  BRouter (2 min 26). Ce que le mainteneur roule vraiment : 58 % de
  `tertiary`, 20 % de `secondary`, 13 % d'`unclassified`, 3 % de `primary`.
  Les poids appris qui en sortent renversent le score du sprint 2 — la
  `secondary` passe de 3,0 à 0,4 km équivalents par kilomètre (0,44 mesuré le
  13/09/2026, l'exposition étant élaguée de ses antennes comme les candidates
  de `boucle`).
- `ourouler calibrer` : le 13/09/2026, sur 99 sorties RCR et 35 sorties BMC,
  avec 137 jours d'archive météo Open-Meteo téléchargés une fois pour toutes.
  Erreur de temps en mouvement sur les 25 % de sorties les plus récentes,
  jamais vues par l'ajustement : **MAE 4,2 % (médiane 3,7 %) pour le RCR**,
  **MAE 2,4 % (médiane 3,1 %) pour le BMC**. Ce que ces données mesurent
  vraiment, c'est la **résistance totale** sur le plat sans vent : 18,0 N
  (139 W) à 27 km/h et 23,2 N (231 W) à 35 km/h pour le RCR, 15,9 N (122 W)
  et 21,0 N (210 W) pour le BMC. CdA et Crr pris séparément sont mal
  contraints par ces données et ne doivent pas être cités seuls.
- `ourouler comparer` : le 13/09/2026, RCR contre BMC. La mesure est une
  **vitesse à puissance égale**, prise sur des séries de tronçons plats
  (|pente| ≤ 0,8 %), d'au moins 500 m, sans arrêt ni relance, à une puissance
  d'endurance (56-75 % de la FTP, soit 144-194 W) : 317 séries et 239 km pour
  le RCR, 145 séries et 116 km pour le BMC. Lues au milieu de la zone
  (169 W) : **RCR 29,0 km/h, BMC 31,5 km/h, soit +2,4 km/h pour le BMC**.
  Les watts n'en sont qu'une conversion, et elle dépend de la façon de
  convertir : **27 W** par la calibration du RCR (ce qu'il faut de plus pour
  tenir 31,5 km/h au lieu de 29,0), **42 W** par la loi en v³
  (`ΔP ≈ 3·P·Δv/v`). Retenir **25 à 45 W en faveur du BMC**, du même ordre
  que le « 25-30 W à la louche » du mainteneur, et de même signe que la
  résistance totale calibrée ci-dessus (17 W de moins pour le BMC à
  27 km/h) — deux mesures indépendantes qui vont dans le même sens. Aucun
  appel réseau : tout vient du cache.

### Comparer deux vélos

```
ourouler comparer --velos RCR BMC                     # écart de vitesse à puissance égale
ourouler comparer --velos RCR BMC --pente-max 0.005   # plat plus strict
ourouler comparer --velos RCR BMC --cap-max 15        # ne garder que les lignes droites
```

Aucun modèle physique n'intervient dans la mesure. Les sorties des deux vélos
sont découpées en tronçons de 200 m ; on ne garde que les tronçons plats, sans
arrêt ni relance, dont la puissance tombe dans la zone d'endurance ; on les
recolle en **séries** consécutives d'au moins 500 m ; et on compare la vitesse
des séries à puissance égale, par une régression `vitesse = a + b·puissance`
lue au milieu de la zone.

**La mesure est en km/h**, les watts en sont une conversion — par la loi en v³
ou par la calibration du vélo de référence, les deux affichées avec leur
formule. Le nombre de mailles communes aux deux vélos est indiqué pour dire à
quel point ils ont roulé aux mêmes endroits, mais il ne filtre rien : les
séries plates et droites d'un vélo de route et d'un CLM ne se superposent pas
assez pour qu'il en reste quelque chose.

### Apprendre ses routes

```
ourouler routes apprendre        # rejoue les sorties du cache dans BRouter (idempotent)
ourouler routes stats            # km et part par classe de route, part semaine
ourouler routes poids            # compare vos sorties à huit boucles d'exposition
ourouler routes poids --appliquer   # écrit les poids, `ourouler boucle` les utilise
```

Les traces servent à **apprendre**, jamais de critère : elles ne couvrent
qu'une partie du territoire, et pénaliser ce qu'elles ignorent condamnerait
toute boucle vers une direction jamais explorée. La colonne « connu % » de
`ourouler boucle` est informative et n'entre dans aucun score.

## Limites connues

Ce que le mainteneur doit savoir avant de lire un chiffre.

- **`maxspeed` absent des tags BRouter.** Le profil `fastbike` n'expose pas
  `maxspeed` dans ses `WayTags` : la table « par maxspeed » de
  `ourouler routes stats` est donc vide à 100 %, et le dit plutôt que
  d'inventer une vitesse. Le profil expose en revanche son propre
  `estimated_traffic_class`, qu'on n'exploite pas encore.
- **Routes hors de la région chargée sur le serveur.** BRouter ne route que
  sur les tuiles OSM présentes sur le serveur : deux sorties de vacances à
  350 km n'ont pas pu être rejouées (« datafile … not found »). Elles sont
  comptées en échec, avec le message du moteur.
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
  216 m côté moteur, 287 m à la relecture, soit +33 % ; revérifié le
  13/09/2026 sur une boucle de 60 km, 295 m contre 405 m, soit +37 %. Les
  deux sont affichés avec leur provenance — « 295 m (moteur) », « 405 m (gpx
  relu) » — plutôt que moyennés ou choisis en silence.
- **Le temps simulé est un temps *en mouvement*.** Ni les feux, ni les stops,
  ni les ravitaillements ne sont modélisés. L'inertie, elle, est comptée dans
  la calibration depuis le 13/09/2026 (la variation d'énergie cinétique de
  chaque tronçon de 200 m), mais pas dans la simulation d'un parcours, qui
  reste un modèle d'équilibre. Un temps de sortie réel, montre en main, est
  plus long — de ce que le cycliste passe à l'arrêt.
- **CdA et Crr ne se séparent pas.** Ils ne sont plus en butée depuis que le
  vent météo est ramené à hauteur de cycliste (0,22 m² et 0,011 pour le RCR,
  0,22 et 0,0086 pour le BMC), mais leur partage reste mal contraint : un CdA
  plus bas avec un Crr plus haut expliquerait les mêmes données. Ce qu'il faut
  lire, et ce que le rapport met en avant, c'est la **résistance totale** à 27
  et 35 km/h. Le couple prédit correctement le temps entre 20 et 36 km/h, et
  se tromperait hors de cette plage. C'est une limite acceptée, pas une
  question en attente : Q9 est close depuis le 13/09/2026 (« on va trop dans
  le détail pour un coureur amateur »), on ne cherche plus à séparer les deux
  termes. Historique : Q9 de `docs/questions_mainteneur.md`.
- **Le vent météo n'est pas le vent du cycliste.** Archive et prévision le
  donnent à 10 m du sol ; un facteur 0,6 (profil logarithmique, bocage) le
  ramène à 1,5 m. Ce facteur est une hypothèse de rugosité moyenne, pas une
  mesure du terrain : une route abritée par une haie et une route en plein
  champ le subissent différemment, et rien ici ne les distingue.
- **L'écart RCR / BMC est un ordre de grandeur, pas une mesure de
  soufflerie.** `ourouler comparer` mesure +2,4 km/h à puissance égale ; le
  passage aux watts dépend de la conversion (27 W par la calibration, 42 W par
  la loi en v³), d'où la fourchette 25-45 W. Deux séries n'ont ni le même
  vent, ni la même fraîcheur, ni le même sens de passage : sur des centaines
  de séries ces écarts se compensent en partie, ils ne s'annulent pas. Citer
  la fourchette, jamais un chiffre au watt près.
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
