"""Un PostgreSQL jetable, le temps de la session de tests.

## Pourquoi ce dossier existe à côté de `tests/api/`

`tests/api/conftest.py` coupe `socket.connect` pour **tous** les tests de son
dossier : ils parlent à l'application par un client ASGI, jamais par le
réseau. Les tests d'ici ont besoin de l'inverse — une vraie connexion TCP vers
un vrai PostgreSQL — et les mettre là-bas aurait voulu dire lever la coupure,
donc l'affaiblir pour tout le monde. Un dossier séparé dit la frontière au
lieu de la trouer.

## Ce que « pas de réseau » veut dire ici (règle absolue 3)

La règle refuse **Internet**, pas la boucle locale : un test qui interroge
api.open-meteo.com est refusé, un test qui interroge un Postgres tournant sur
la machine du mainteneur ne l'est pas. Trois précautions rendent la
distinction vérifiable plutôt que déclarative :

1. l'URL servie pointe sur `127.0.0.1`, et la fixture le vérifie ;
2. l'image n'est **jamais téléchargée** : si `postgres:17-alpine` n'est pas
   déjà présente localement, les tests sautent avec la commande à lancer. Un
   `docker run` qui tire une image irait sur Internet, ce que la règle
   interdit — et un test qui se met à télécharger 100 Mo la première fois
   n'est pas le même test ;
3. rien n'est écrit hors du conteneur, qui disparaît à la fin de la session.

## Sauter proprement, et que ça se voie

Sans Docker, sans démon Docker, sans `psycopg` ou sans image, `uv run pytest`
reste **vert** — mais ces tests apparaissent comme *sautés*, avec la raison,
jamais comme passés. Une suite qui verdit en ne testant rien est pire qu'une
suite rouge : elle ment.

## Une base par test

Le conteneur vit une session, mais chaque test reçoit une **base neuve**
(`CREATE DATABASE`) sur laquelle les migrations sont appliquées. C'est ce qui
permet d'écrire sans nettoyer, de rejouer les migrations sur une base vierge,
et de lancer deux connexions concurrentes sans qu'un test d'à côté explique un
échec.
"""

from __future__ import annotations

import json
import secrets
import shutil
import subprocess
import time
from collections.abc import Iterator

import pytest

#: L'image du conteneur, épinglée. Jamais tirée par les tests : voir la note
#: de module — une image absente fait sauter, elle ne déclenche pas un
#: téléchargement.
IMAGE = "postgres:17-alpine"

#: Combien de temps on laisse au serveur pour accepter des connexions. Un
#: `postgres:alpine` démarre en une poignée de secondes sur un portable ;
#: au-delà, c'est une panne, pas de la lenteur.
DELAI_DEMARRAGE_S = 30.0

#: L'utilisateur et la base d'administration du conteneur. Le mot de passe,
#: lui, est **tiré au hasard à chaque session** : rien qui ressemble à un
#: secret ne doit pouvoir être commité (règle absolue 1), même jetable.
UTILISATEUR = "ourouler_test"
BASE_ADMIN = "postgres"


def _docker(*arguments: str, verifier: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["docker", *arguments], capture_output=True, text=True, check=verifier
    )


def _raison_de_sauter() -> str | None:
    """Ce qui manque pour lancer un Postgres local, dit en une phrase actionnable."""
    try:
        import psycopg  # noqa: F401
    except ImportError:
        return "psycopg absent — « uv sync --extra dev --extra api »"
    if shutil.which("docker") is None:
        return "docker absent de cette machine"
    if _docker("info", verifier=False).returncode != 0:
        return "le démon Docker ne répond pas — le démarrer"
    if _docker("image", "inspect", IMAGE, verifier=False).returncode != 0:
        return (
            f"image {IMAGE} absente localement — « docker pull {IMAGE} » "
            "(les tests ne la téléchargent pas eux-mêmes : règle absolue 3)"
        )
    return None


@pytest.fixture(scope="session")
def postgres_jetable() -> Iterator[str]:
    """Un conteneur PostgreSQL éphémère ; rend l'URL d'administration."""
    raison = _raison_de_sauter()
    if raison is not None:
        pytest.skip(f"PostgreSQL local indisponible : {raison}")

    motdepasse = secrets.token_hex(16)
    nom = f"ourouler-test-{secrets.token_hex(4)}"
    _docker(
        "run", "--detach", "--rm", "--name", nom,
        "--env", f"POSTGRES_USER={UTILISATEUR}",
        "--env", f"POSTGRES_PASSWORD={motdepasse}",
        "--env", f"POSTGRES_DB={BASE_ADMIN}",
        # Port choisi par Docker, sur la boucle locale seulement : deux
        # sessions de tests en parallèle ne se marchent pas dessus, et rien
        # n'est exposé au-delà de la machine.
        "--publish", "127.0.0.1::5432",
        IMAGE,
        # `fsync=off` : cette base vit quelques secondes et n'a rien à
        # survivre. C'est ce qui rend une base par test supportable.
        "-c", "fsync=off", "-c", "full_page_writes=off",
    )
    try:
        port = _port_publie(nom)
        url = f"postgresql://{UTILISATEUR}:{motdepasse}@127.0.0.1:{port}/{BASE_ADMIN}"
        _attendre_le_serveur(nom, url)
        yield url
    finally:
        _docker("rm", "--force", nom, verifier=False)


@pytest.fixture
def url_base(postgres_jetable: str) -> Iterator[str]:
    """Une base neuve, migrée, pour ce test seul."""
    import psycopg

    from ourouler.api.base_de_donnees import appliquer_migrations, ouvrir

    assert "@127.0.0.1:" in postgres_jetable, "le Postgres de test doit être local"
    nom = f"essai_{secrets.token_hex(6)}"
    with psycopg.connect(postgres_jetable, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{nom}"')
    url = postgres_jetable.rsplit("/", 1)[0] + "/" + nom
    with ouvrir(url) as connexion:
        appliquer_migrations(connexion)
    try:
        yield url
    finally:
        with psycopg.connect(postgres_jetable, autocommit=True) as admin:
            admin.execute(f'DROP DATABASE IF EXISTS "{nom}" WITH (FORCE)')


@pytest.fixture
def url_base_vierge(postgres_jetable: str) -> Iterator[str]:
    """Une base neuve **et non migrée** — celle que la vraie vie présente.

    `url_base` migre avant de rendre la main, ce qui est ce que veulent les
    tests du dépôt. Mais ça cachait un trou : personne n'appliquait les
    migrations en dehors des tests, et `ourouler inviter` mourait sur
    `relation "comptes" does not exist` au premier vrai lancement
    (19/09/2026). Une base vierge est la seule façon d'écrire un test qui
    aurait attrapé ça.
    """
    import psycopg

    assert "@127.0.0.1:" in postgres_jetable, "le Postgres de test doit être local"
    nom = f"vierge_{secrets.token_hex(6)}"
    with psycopg.connect(postgres_jetable, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{nom}"')
    try:
        yield postgres_jetable.rsplit("/", 1)[0] + "/" + nom
    finally:
        with psycopg.connect(postgres_jetable, autocommit=True) as admin:
            admin.execute(f'DROP DATABASE IF EXISTS "{nom}" WITH (FORCE)')


@pytest.fixture
def connexion(url_base: str) -> Iterator:
    """Une connexion ouverte sur la base du test."""
    from ourouler.api.base_de_donnees import ouvrir

    with ouvrir(url_base) as cx:
        yield cx


@pytest.fixture
def depot(connexion):
    """Le dépôt des comptes, branché sur la base du test."""
    from ourouler.api.comptes import DepotComptes

    return DepotComptes(connexion)


def _port_publie(nom: str) -> int:
    """Le port que Docker a choisi côté machine."""
    sortie = _docker("inspect", nom).stdout
    ports = json.loads(sortie)[0]["NetworkSettings"]["Ports"]["5432/tcp"]
    return int(ports[0]["HostPort"])


def _attendre_le_serveur(nom: str, url: str) -> None:
    """Attend que le serveur réponde **à une vraie requête**, ou échoue en le disant.

    On sonde en se connectant comme les tests, pas avec `pg_isready` dans le
    conteneur : l'image `postgres` démarre d'abord un serveur **temporaire**,
    le temps d'`initdb` et des scripts d'amorçage, puis l'arrête et relance le
    vrai. `pg_isready` répond « prêt » au premier, et la connexion suivante se
    fait couper au nez (« server closed the connection unexpectedly »). C'est
    exactement le faux positif qu'on a rencontré le 18/09/2026 : une sonde qui
    mesure autre chose que ce dont on a besoin.
    """
    import psycopg

    limite = time.monotonic() + DELAI_DEMARRAGE_S
    derniere: Exception | None = None
    while time.monotonic() < limite:
        try:
            with psycopg.connect(url, connect_timeout=2) as essai:
                essai.execute("SELECT 1")
            return
        except psycopg.Error as e:
            derniere = e
            time.sleep(0.2)
    journal = _docker("logs", "--tail", "20", nom, verifier=False)
    raise RuntimeError(
        f"le conteneur {nom} n'a pas répondu en {DELAI_DEMARRAGE_S:.0f} s ({derniere}) :\n"
        + journal.stderr
        + journal.stdout
    )
