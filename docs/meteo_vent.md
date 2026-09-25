# Météo et vent — ce qu'on demande, et ce qu'on en fait

État en septembre 2026. Les justifications complètes sont dans les docstrings des
modules cités.

## Deux questions, deux mécanismes

Le produit pose deux questions météo qui n'ont rien à voir, et qui ont chacune
leur module.

**« Où va-t-il pleuvoir autour de moi ? »** — `meteo/couronne.py` pose une
couronne de points autour du départ, 8 ou 16 directions, et on interroge chaque
point. C'est ce qui répond à *au nord, au sud ou à l'est ?* avant même qu'un
parcours existe. Rendu par `meteo/rapport.py`.

**« Qu'est-ce que je vais prendre, où, et à quelle heure ? »** —
`boucle/meteo_trace.py` suit un tracé **déjà calculé** et interroge chaque
tronçon **à l'heure où le cycliste y sera**. Une averse qui traverse la région
à 10 h ne concerne que les kilomètres 25 à 35.

## Ce qu'on demande à Open-Meteo

Cinq variables horaires, en un seul appel HTTP pour tous les points (l'API
accepte plusieurs coordonnées par requête) :

```
precipitation · wind_speed_10m · wind_direction_10m · wind_gusts_10m · apparent_temperature
```

Le vent est donc celui **à 10 mètres du sol**, convention météo standard — pas
celui que vous prenez dans la figure à 1,10 m derrière une haie.

## Deux modèles, jamais moyennés

| | rôle | portée mesurée (septembre 2026) |
|---|---|---|
| `meteofrance_arome_france_hd` | maille 1,3 km, France seulement | dernière valeur à **J+2** |
| `icon_seamless` | le second avis | **J+7** |

Quand les deux divergent sur un échantillon, on ne fait pas la moyenne : la
réponse porte `confiance` = `accord`, `desaccord` ou `inconnu`, et l'écran le
montre (règle absolue 5, doctrine §1).

C'est le **modèle de repli** qui fixe la portée du produit : `horizon_jours`
vaut 7 par défaut, et c'est un paramètre de configuration, pas une constante —
la portée appartient au modèle, pas au projet.

## Deux horizons, et ils ne disent pas la même chose

- **`horizon_jours` = 7** — au-delà, le parcours est servi quand même et la
  météo est **déclarée absente**, sans qu'Open-Meteo soit appelé
  (`meteo/portee.py`). Une date lointaine ne se refuse pas : mieux vaut un
  parcours sans météo qu'un refus.
- **`HORIZON_ORIENTATION_J` = 3** — au-delà, on ne propose plus de **s'orienter
  au vent**. Mesuré : à 3 jours la direction tombe dans le bon secteur 88 % du
  temps, à 4 jours 85 %, et AROME est déjà sorti du jeu. La pluie reste
  annoncée, le choix de direction non.

## Le long du tracé

Échantillonnage tous les **5 km** (`PAS_DEFAUT_M`), chacun daté de l'heure de
passage estimée. Le coût d'un appel croît donc avec la **longueur** du
parcours, pas avec un rayon autour de chez vous.

Les valeurs horaires sont interpolées linéairement entre les deux heures
encadrantes — et **angulairement pour la direction du vent**, sans quoi 350° et
10° donneraient 180°, c'est-à-dire le sud au lieu du nord.

## Face, dos, travers

`meteo/rapport.py:vent_relatif` compare le cap du cycliste à la direction
**d'où vient** le vent (convention météo) :

| écart angulaire | verdict |
|---|---|
| ≤ 45° | **face** — il vient de là où on va |
| ≥ 135° | **dos** |
| entre les deux | **travers** |

`SECTEUR_VENT_DEG = 45` est le demi-secteur ; face et dos sont donc chacun un
quart de l'horizon, le travers occupe la moitié.

Sur le point de départ, la valeur est `None` et non « face » : il n'y a pas de
« à l'aller » quand on n'est pas encore parti.

Les parts `part_vent_face` et `part_vent_dos` se calculent **sur les seuls
échantillons au vent connu**, et la réponse porte `n_vent_connu` à côté : « vent
de face 100 % » ne disait pas s'il reposait sur douze échantillons ou sur un
seul, les onze autres étant hors de portée.

## Le seuil de 8 km/h

`SEUIL_VENT_SENSIBLE_KMH = 8.0` — en dessous, il n'y a rien à sentir, donc rien
à montrer ni à demander.

Ce n'est pas une valeur ronde : 8 km/h est le haut de la force 1 de Beaufort
(« très légère brise, à peine perceptible sur un visage ») et le bas de la
force 2 (« légère brise, sentie sur le visage »).

**Une seule constante pour trois usages**, et c'est voulu : les flèches de la
carte se dessinent exactement quand la question de l'orientation au vent se
pose. Si le vent ne mérite pas d'être montré, il ne mérite pas qu'on demande
son orientation.

## Les flèches de la carte

`fleches_vent` sérialise un échantillon sur deux environ, en écartant ceux sous
le seuil de 8 km/h et ceux dont le vent est inconnu. Chacune porte :

```json
{"pt": [lat, lon], "depuis_deg": 272.4, "vent_kmh": 8, "rafale_kmh": 18, "relatif": "face"}
```

**La flèche pointe d'où vient le vent, comme une girouette** — pas où il va.
Les chiffres affichés sont la moyenne, puis la rafale.

## La pluie

| constante | valeur | où |
|---|---|---|
| `SEUIL_PLUIE_MM_H` | 0,2 mm/h | le long du tracé : au-delà, l'échantillon est « sous la pluie » |
| `SEUIL_PLUIE_MM_H` | 0,3 mm/h | rapport par direction : au-delà, un modèle « annonce de la pluie » |
| `SEUIL_SEC_MM_H` | 0,1 mm/h | en dessous, un modèle « n'annonce pas de pluie » |
| `SEUIL_EGALITE_MM` | 0,2 mm | deux directions à égalité de cumul |

L'écart entre 0,1 et 0,3 n'est pas un oubli : entre les deux, un modèle ne dit
ni oui ni non, et on ne le force pas à trancher.

## Le vent qu'il faisait

`connecteurs/openmeteo_archive.py` sert la calibration, pas la prévision. Sans
le vent réel d'une sortie passée, calibrer un CdA revient à attribuer au
cycliste ce qui appartenait à la brise : trois mètres par seconde de face sur
une sortie plate, c'est 20 % de puissance aérodynamique en plus.

Un jour **clos** ne change plus : ces réponses-là sont mémoïsées dans un
SQLite. Le jour courant bouge encore, et n'est jamais écrit sur disque.
