# Obtenir un serveur BRouter

Recette pour un nouveau venu sur ce dépôt : faire tourner un serveur
[BRouter](https://github.com/abrensch/brouter) en local, le brancher sur
`ourouler`, et ce qu'il faut savoir avant de l'exposer. **Documentation
seulement** — aucune commande n'a été exécutée pour l'écrire ; ce qui reste à
vérifier soi-même est marqué comme tel.

## Pourquoi BRouter

`ourouler` ne trace aucun itinéraire lui-même : il délègue tout tracé à
BRouter, un moteur de routage OpenStreetMap auto-hébergé, sans clé ni compte,
avec des profils par usage (`fastbike`, `trekking`, `gravel`…).

En dépendent : `ourouler boucle` (le cœur du produit, mode « round trip » de
BRouter, `engineMode=4` — voir `MODE_BOUCLE` dans
`src/ourouler/connecteurs/brouter.py`), `ourouler sortie` (sa carte s'appuie
sur une boucle tracée par BRouter), et l'écran web (page du jour, API : même
chemin de code, via `ClientBrouter`). `ourouler meteo` et `ourouler analyser`
n'en ont **pas besoin** : la météo ne regarde que des coordonnées, et
`analyser` relit un GPX déjà tracé sans rappeler le moteur. Sans
`[brouter] url` renseigné, `boucle` et `sortie` s'arrêtent et le disent
(`ErreurConnecteur`) plutôt que de produire un résultat incomplet.

## La voie la plus simple en local

### L'image et le conteneur

Le dépôt *abrensch/brouter* publie une image sur GitHub Container Registry :
`ghcr.io/abrensch/brouter`, en tags `nightly` (un build par jour depuis
`master`), `latest`/version taguée, et par version (`v1.7.x`). Épingler par
**digest** plutôt qu'un tag mouvant, `nightly` changeant de contenu à chaque
build sans prévenir : `docker pull ghcr.io/abrensch/brouter:nightly` puis
`docker inspect --format='{{index .RepoDigests 0}}' ghcr.io/abrensch/brouter:nightly`
donne `ghcr.io/abrensch/brouter@sha256:<empreinte>`, la référence à figer.

**Prendre `nightly`, pas `latest`.** Constaté sur le déploiement du
mainteneur : la version taguée (`latest`, 1.7.8 au moment de l'essai) lit
l'ancien format de segments, alors que les `.rd5` téléchargeables
aujourd'hui sont au format suivant ; elle démarre, puis ne trouve aucun
itinéraire. Une `nightly` épinglée par empreinte fonctionne. Ce même
déploiement tourne avec `JAVA_OPTS=-Xmx1024M` et `MAXTHREADS=4`, et trois
tuiles de 5° × 5° : c'est assez pour une région.

Vérifié sur ce déploiement réel : l'image, les tuiles `.rd5` de
`segments4` et leur nommage par le coin sud-ouest (`W5_N45`, `E0_N45`…),
les profils fournis avec l'image (`fastbike`, `trekking`, `gravel`…, mais
pas `fastbike-lowtraffic`), et l'appel en boucle (`engineMode=4`). Lus
dans le dépôt amont et pas éprouvés tels quels ici : le port par défaut
(17777) et les chemins de volumes `/segments4` et `/profiles2` du
`docker run` ci-dessous.

```bash
mkdir -p ~/brouter/segments4 ~/brouter/profiles2

docker run -d --name brouter \
  -p 17777:17777 \
  -v ~/brouter/segments4:/segments4 \
  -v ~/brouter/profiles2:/profiles2 \
  ghcr.io/abrensch/brouter@sha256:<empreinte>
```

Ou, en *deploiement/brouter/docker-compose.yml* (à créer si cette forme est
préférée — rien de tel n'existe encore ici ; `deploiement/docker-compose.yml`
orchestre `ourouler` lui-même, pas BRouter) :

```yaml
services:
  brouter:
    image: ghcr.io/abrensch/brouter@sha256:<empreinte>
    ports: ["17777:17777"]
    volumes:
      - ./segments4:/segments4
      - ./profiles2:/profiles2
    restart: unless-stopped
```

### Les segments `.rd5` et les profils

BRouter ne route que sur les tuiles OpenStreetMap qu'il a en local, des
carrés de **5° × 5°** au format `.rd5`, téléchargeables sur
`https://brouter.de/brouter/segments4/`. Nom de tuile :
`<E ou W><longitude>_<N ou S><latitude>.rd5`, coin **sud-ouest** — par
exemple `E0_N45.rd5` couvre de 0° à 5° de longitude est et de 45° à 50° de
latitude nord. Pour trouver la sienne : arrondir longitude et latitude du
point de départ **vers le bas** au multiple de 5 (une longitude négative
arrondit vers l'ouest, donc vers `W`). 1 à 4 tuiles suffisent en général
(celle du départ, plus les voisines si le rayon des boucles dépasse ses
bords). Les fichiers vont dans `/segments4`.

Les profils (`fastbike`, `fastbike-verylowtraffic`, `trekking`, `gravel`…)
doivent être des fichiers `.brf` dans `/profiles2` — un profil absent donne
un **HTTP 500 sans corps** (voir plus bas). Ceux du dépôt *abrensch/brouter* (dossier *misc/profiles2/*, sur GitHub)
sont la source à copier ; `[brouter] profil` doit nommer
exactement un fichier présent là, sans l'extension.

## Brancher `ourouler`

Dans `~/.config/ourouler/config.toml` (voir `config.example.toml`), section
`[brouter]` :

```toml
[brouter]
url = "http://localhost:17777"
utilisateur = ""       # vide en local direct, sans proxy devant
mot_de_passe = ""
profil = "fastbike"    # ou trekking, gravel... — doit exister dans /profiles2
```

Vérifier le serveur seul, avec des coordonnées génériques à remplacer par
les siennes :

```bash
curl "http://localhost:17777/brouter?lonlats=LON1,LAT1|LON2,LAT2&profile=trekking&alternativeidx=0&format=geojson"
```

Un `features[0].geometry.coordinates` non vide dans la réponse veut dire que
le serveur route sur la zone couverte. Puis, côté `ourouler` :

```bash
uv run ourouler boucle --distance 30
```

Un échec ici avec un message BRouter en clair (pas un simple « HTTP 400 »)
est normal la première fois : lire `_indice()` dans
`src/ourouler/connecteurs/brouter.py` pour l'interpréter, et les pièges
ci-dessous.

## Pièges connus

Mesurés sur un déploiement réel (voir `docs/services_externes.md`, section
BRouter, et les commentaires de `src/ourouler/connecteurs/brouter.py`) :

- **Un profil absent de `/profiles2` donne un HTTP 500 sans corps**, sans
  autre indice — la cause la plus fréquente après une configuration fraîche.
  Vérifier le nom du fichier `.brf`. `allowSamewayback` a le même symptôme
  s'il reçoit autre chose que 0 ou 1 (`ourouler` envoie déjà la bonne forme).
- **`engineMode=4` (boucle) place des points de passage sur un cercle**, pas
  un algorithme de boucle : un point tombé à côté d'une route produit un
  cul-de-sac (« antenne ») que `ourouler` élague après coup
  (`boucle/antennes.py`) — pas un signe de mauvaise configuration. Les
  paramètres `profile:…` qui réduisent ces antennes demandent le nom
  camelCase de BRouter (`correctMisplacedViaPoints`) : un nom erroné est
  silencieusement ignoré, sans erreur.
- **Une région hors des tuiles installées** ne route pas : message explicite
  en général (« datafile … not found », « target island detected »).
  Télécharger la ou les tuiles `.rd5` manquantes.
- **Identifiants refusés (401/403)** : vérifier `[brouter] utilisateur` et
  `mot_de_passe`, ou l'absence de proxy si on route en direct sur le port du
  conteneur.

## Exposer le serveur

Ce dépôt n'installe rien sur un serveur pour le compte de qui que ce soit
(`AGENTS.md` : « Aucune installation sur une machine ou un serveur sans
l'accord explicite du mainteneur ») : ce qui suit décrit un principe, pas une
procédure vers une machine précise. BRouter lui-même ne porte aucune
authentification. L'exposer au-delà de `localhost` passe par un **proxy
inverse avec authentification basique** devant le conteneur, jamais par le
port 17777 ouvert tel quel. `[brouter] utilisateur` et `mot_de_passe`
correspondent aux identifiants de ce proxy, pas à un compte BRouter (qui
n'existe pas). L'URL de `[brouter] url` est une adresse de serveur, pas un
secret : elle peut s'afficher dans un message d'erreur ; le mot de passe,
lui, ne vit que dans l'objet d'authentification HTTP, jamais en log ni en
`repr` (`ClientBrouter.__repr__`).
