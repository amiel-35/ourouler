# Scripts de mesure (`scripts/validation/`)

Ces scripts **ne sont pas des tests**. Chacun rejoue une question sur les
vraies données d'un cycliste (son cache d'activités, son compte Intervals.icu,
un vrai serveur BRouter, l'archive Open-Meteo) et imprime une mesure : un
chiffre, une comparaison, parfois un critère d'acceptation qu'un réglage du
produit a dû passer. Ils ne rendent pas de verdict automatique et pytest ne
les collecte pas (ils vivent hors de `tests/`).

C'est pour cela qu'ils sont ici : la suite de tests n'a droit ni au réseau ni
à une donnée réelle, eux n'existent que pour ça. Aucune donnée n'est dans le
dépôt : ils lisent la configuration de la personne qui les lance
(`~/.config/ourouler/config.toml` ou `--config`) et le cache qu'elle désigne.
Ce qu'ils impriment reste agrégé ; aucun ne doit imprimer une coordonnée.

## Les lancer

Depuis la racine du dépôt, après `uv sync --frozen --extra dev` :

    uv run python scripts/validation/<script>.py --help
    uv run python scripts/validation/<script>.py [options]

Il faut un cache rempli (`ourouler inventaire --importer …` ou
`ourouler inventaire --synchroniser`) et, selon le script, une clé
Intervals.icu, un serveur BRouter joignable, ou l'accès à l'archive
Open-Meteo (colonne « Données » ci-dessous) : sans eux, il n'y a rien à mesurer.

## Ce que chacun mesure

| Script | Question | Données |
|---|---|---|
| `terrain_retrospectif.py` | la note de terrain distingue-t-elle les emplacements où les blocs sont vraiment tombés d'emplacements tirés au hasard ? (résultat dans `docs/demarche.md`) | cache, Intervals |
| `vent_retrospectif.py` | notre vent (archive, cap local, secteur ±45°) dit-il la même chose que celui d'Intervals ? | cache, Intervals, Open-Meteo |
| `orientation_vent_retrospectif.py` | le cycliste part-il déjà face au vent ? | cache, Intervals, Open-Meteo |
| `marqueurs_retrospectif.py` | la densité de marqueurs urbains au kilomètre sépare-t-elle les sorties réelles des boucles proposées ? | cache, BRouter |
| `trafic_estime_retrospectif.py` | `estimated_traffic_class` de BRouter sépare-t-il les routes choisies des routes proposées ? | cache, BRouter |
| `arrets_bloc_recup.py` | feux, stops et giratoires tombent-ils plutôt dans les blocs ou dans les récupérations ? | cache, BRouter, Intervals |
| `style_retrospectif.py` | que cherche le cycliste quand il roule (répétition, secteurs, style) ? exploratoire, sans réseau | cache |
| `cda_position_retrospectif.py` | ce que la position aérodynamique coûte, à Crr commun forcé entre deux vélos | cache, Open-Meteo |
| `endurance_np_retrospectif.py` | la part de FTP roulée en endurance, en puissance normalisée (défaut de `puissance_endurance_pct`) | cache |
| `facteur_compteur_retrospectif.py` | le facteur entre vitesse à plat et moyenne du compteur, par vélo (`facteur_compteur`) | cache |
| `seance_hit_exterieur.py` | une séance à blocs du plan, rejouée dehors avec ses vraies Z2 | cache, Intervals, BRouter, météo |
| `table_ftp_vitesse.py` | engendre `docs/table_ftp_vitesse.md` (`--markdown`) à partir des valeurs de littérature | aucune |

Deux tests lisent ces scripts sans les exécuter sur des données réelles :
`tests/test_seance_terrain.py` vérifie que les poids de la note de terrain
restent ceux que `terrain_retrospectif.py` diagnostique, et
`tests/test_cda_position.py` éprouve l'ajustement de `cda_position_retrospectif.py`
sur des échantillons fabriqués.

## Lint

Ruff les vérifie comme le reste du dépôt. Trois d'entre eux gardent une
exception permanente de taille (`C901`, `PLR0915`, dans `pyproject.toml`) :
leur fonction principale enchaîne collecte, calcul et rapport, et se lit mieux
d'une traite qu'en morceaux qu'aucun autre code n'appellerait.
