# Notes de mesure des en-têtes de module

Mesures et récits retirés d'en-têtes de module (docstrings, commentaires)
pendant N8, pour n'y garder que le pourquoi durable. Chaque module renvoie
ici en une ligne ; le comportement du code n'a pas changé.

## `boucle/antennes.py`

Le mécanisme de recalage de BRouter (`correctMisplacedViaPoints`, seuil de
distance à 0) élimine l'essentiel des antennes lui-même, mais pas toutes :
au rayon de boucle le plus petit mesuré (8 km), 4 boucles sur 7 gardaient
encore une antenne même à seuil 0 — signe que certains crochets ne sont pas
des points de passage mal placés mais de vrais culs-de-sac du réseau à ce
rayon, que le moteur ne peut pas recaler. C'est ce qui justifie que ce
module reste un filet plutôt qu'une optique corrigée une fois pour toutes
côté serveur BRouter.

## `sortie/contraste.py`

**`PAS_MARQUEURS_KM` (0,5 marqueur/km), chiffré sur une mesure**
(`scripts/validation/marqueurs_retrospectif.py`, 143 boucles proposées par
le moteur autour d'un départ réel) : q1 = 1,21, médiane = 1,50, q3 = 2,01,
soit un écart interquartile de 0,80. La moitié de cet écart, 0,40, est
l'oscillation ordinaire entre deux candidates ; 0,50 est au-dessus. En
unités de cycliste, sur une boucle de 60 km : 30 marqueurs d'écart, un arrêt
tous les deux kilomètres contre un arrêt tous les kilomètres.

**`PAS_TRAFIC_PART` (0,10), chiffré sur une mesure** (35 boucles proposées
par le moteur autour d'un départ réel, à 40, 60 et 80 km) : q1 = 34,8 %,
médiane = 41,1 %, q3 = 49,5 %, soit un écart interquartile de 14,7 points et
un écart-type de 12,0. La moitié de l'écart interquartile, 7,4 points, est
l'oscillation ordinaire entre deux candidates ; 10 points est au-dessus. En
unités de cycliste, sur une boucle de 60 km : 6 km de départementale en plus
ou en moins.

**Mesuré deux fois, pas supposé** (module `contraste.py`, sur l'exigence
d'un axe distinctif en plus du recouvrement de routes) : quatre candidates
dont le recouvrement médian valait 1,4 % — quasi disjointes — n'étaient
servies qu'à une ou deux sous cette exigence, qui absorbait tout le gain.
Plus on génère de candidates, moins un trio passe : à cinq candidates trois
axes distinguaient encore, à huit un seul.

## `physique/calibration.py`

**Réserve mesurée sur le CdA d'un vélo** : sur les deux vélos d'un cycliste
de référence, la calibration trouve le même CdA à 0,7 % près — dans le
bruit des incertitudes (±2 % et ±2,5 %) — alors qu'un chrono devrait être
nettement plus aérodynamique. Tout l'écart entre les deux (16 W à 25 km/h,
26 W à 40 km/h) est passé dans le Crr, plus bas de 21 % sur le chrono. Ce
n'est pas un artefact de régression : ce cycliste roule une partie de ses
sorties de chrono hors prolongateur, le chrono porte de meilleures roues et
des pneus plus larges (Crr réellement plus bas), et les gains marginaux
(tenue, casque, chaussettes) ne sont pas mis à toutes les sorties. Le CdA
calibré décrit donc un mélange de positions et d'équipements.

Conséquence mesurée sur la sensibilité au vent : le gain du chrono ne
grandit que de 0,6 W entre l'absence de vent et 20 km/h de vent de face à
30 km/h, là où un vrai gain aérodynamique grandirait franchement — pour un
effort réellement tenu en position, le modèle sous-estime.
