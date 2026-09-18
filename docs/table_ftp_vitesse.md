# FTP, vitesse à plat, moyenne compteur — la table indicative

**Engendrée par `tests/validation/table_ftp_vitesse.py`** : ne la corrigez pas
à la main, relancez le script. Dernier rendu le 18/09/2026.

Ce sont les **trois valeurs liées** de l'écran de FTP (décision 7 du cycle UX),
calculées pour un cycliste générique au lieu d'un cycliste réel.

## Comment la lire

**Dans un sens** : « ma FTP est de 250 W, je pèse 75 kg » → je tiendrai environ
30 km/h à plat en endurance, et mon compteur affichera environ 25 km/h de
moyenne sur une sortie vallonnée.

**Dans l'autre**, et c'est le plus utile : *« je ne connais pas ma FTP, mais je
sais que je roule à 26 km/h à plat sans forcer »* → ligne 175-200 W à 75 kg.
Le produit n'a pas besoin de la FTP, il a besoin d'une intensité ; une vitesse
à plat fait le même travail.

La masse compte, et elle compte surtout sur la **troisième** colonne : à FTP
égale, dix kilos de plus coûtent environ un kilomètre-heure à plat, mais deux
sur la moyenne compteur — parce que le relief pénalise la masse deux fois, à la
montée et en ne la rendant pas à la descente.


### cycliste 65 kg + vélo 9 kg = 74 kg

| FTP | endurance | à plat, sans vent | moyenne compteur attendue |
|---:|---:|---:|---:|
| 150 W | 90 W | 24,7 km/h | 19,9 km/h |
| 175 W | 105 W | 26,2 km/h | 21,7 km/h |
| 200 W | 120 W | 27,7 km/h | 23,4 km/h |
| 225 W | 135 W | 29,0 km/h | 24,9 km/h |
| 250 W | 150 W | 30,2 km/h | 26,3 km/h |
| 275 W | 165 W | 31,3 km/h | 27,5 km/h |
| 300 W | 180 W | 32,4 km/h | 28,7 km/h |
| 325 W | 195 W | 33,4 km/h | 29,8 km/h |
| 350 W | 210 W | 34,3 km/h | 30,8 km/h |

### cycliste 75 kg + vélo 9 kg = 84 kg

| FTP | endurance | à plat, sans vent | moyenne compteur attendue |
|---:|---:|---:|---:|
| 150 W | 90 W | 24,3 km/h | 18,8 km/h |
| 175 W | 105 W | 25,9 km/h | 20,7 km/h |
| 200 W | 120 W | 27,3 km/h | 22,4 km/h |
| 225 W | 135 W | 28,7 km/h | 24,0 km/h |
| 250 W | 150 W | 29,9 km/h | 25,4 km/h |
| 275 W | 165 W | 31,0 km/h | 26,7 km/h |
| 300 W | 180 W | 32,1 km/h | 27,9 km/h |
| 325 W | 195 W | 33,1 km/h | 29,0 km/h |
| 350 W | 210 W | 34,1 km/h | 30,1 km/h |

### cycliste 85 kg + vélo 9 kg = 94 kg

| FTP | endurance | à plat, sans vent | moyenne compteur attendue |
|---:|---:|---:|---:|
| 150 W | 90 W | 23,9 km/h | 17,8 km/h |
| 175 W | 105 W | 25,5 km/h | 19,8 km/h |
| 200 W | 120 W | 27,0 km/h | 21,5 km/h |
| 225 W | 135 W | 28,3 km/h | 23,0 km/h |
| 250 W | 150 W | 29,6 km/h | 24,5 km/h |
| 275 W | 165 W | 30,7 km/h | 25,8 km/h |
| 300 W | 180 W | 31,8 km/h | 27,0 km/h |
| 325 W | 195 W | 32,8 km/h | 28,2 km/h |
| 350 W | 210 W | 33,8 km/h | 29,3 km/h |

## Les trois réserves, à lire avec la table

**Le jeu CdA/Crr est celui dit « route amateur »** (CdA 0,320, Crr 0,0050),
mesuré au sprint 6 contre la calibration réelle du mainteneur : **+0,3 minute
de dérive sur une boucle de deux heures**. C'est le meilleur des jeux essayés —
sur **un** cycliste. Un autre corps, une autre position, un autre vélo, et la
ligne bouge.

**La colonne « compteur » est la plus faible des trois.** Elle vient du facteur
par défaut, dérivé d'un profil de référence — 10 m de dénivelé par kilomètre,
5 % du temps à l'arrêt — qui n'est la sortie de personne. Le vrai facteur se
mesure sur l'historique : chez le mainteneur il vaut **0,87** là où le défaut
supposait 0,803, soit 8 % de vitesse qui n'existaient pas.

**Tout est calculé à plat, sans vent, lancé**, à 60 % de la FTP. Une sortie
réelle a du relief, du vent et des carrefours. Et 60 % est conservateur : la
mesure en puissance normalisée sur les sorties du mainteneur donne **0,689**.

## Ce que la table ne remplace pas

Elle donne un ordre de grandeur pour démarrer, pas une prévision. Dès qu'il
existe un historique avec capteur de puissance, `ourouler calibrer` ajuste CdA
et Crr sur les sorties réelles et le modèle cesse de supposer.

Mesuré le 18/09/2026 sur l'historique du mainteneur, en calibrant sur les N
sorties les plus récentes :

| sorties | CdA | Crr |
|---:|---:|---:|
| 3 | 0,194 | 0,0106 |
| 5 | 0,241 | 0,0098 |
| 10 | 0,196 | **0,0120 — la borne haute** |
| 20 | 0,250 | 0,0116 |
| 40 | 0,233 | 0,0119 |

**La calibration n'est pas stable en dessous d'une vingtaine de sorties**, et le
Crr vient buter sur sa borne : CdA et Crr se compensent l'un l'autre, et rien
ne les sépare tant que les données ne présentent pas assez de vitesses et de
pentes différentes. Trois sorties donnent une erreur de validation de 0,03 % —
un chiffre flatteur qui ne mesure que le surapprentissage.
