"""Outils des sorties de référence (filet 0b du plan d'ouverture).

Trois choses, partagées par `test_caracterisation_cli.py` (ici) et
`tests/api/test_caracterisation_api.py` :

1. **Le réseau rejoué.** `httpx.Client` est remplacé, le temps d'un test, par
   une sous-classe qui reçoit d'office un `httpx.MockTransport` aiguillé par
   hôte (Open-Meteo, archive Open-Meteo, BRouter, Intervals, géocodage). Le
   remplacement se fait **au niveau de `httpx`**, pas au niveau des
   connecteurs ni des commandes : c'est la seule couture que les lots de
   restructuration ne déplacent pas. Un hôte inconnu fait échouer le test.
   Chaque appel est journalisé (hôte, chemin, paramètres triés), et le
   journal fait partie de la référence : le nombre et la forme des appels
   aux services sont un comportement.
2. **L'horloge figée.** `date.today()`, `datetime.now()` et `datetime.today()`
   rendent l'instant `INSTANT` dans **tous** les modules `ourouler.*` qui ont
   importé `date` ou `datetime` — on les importe tous d'abord, puis on
   remplace l'attribut du module. Aucune modification de `src/` : le sens du
   balayage (tous les modules, pas une liste) survit aux déplacements de code.
3. **La comparaison normalisée** : `json.loads` puis
   `json.dumps(sort_keys=True, indent=2, ensure_ascii=False)`, chemins
   temporaires et identifiants aléatoires remplacés, flottants comparés à
   `TOLERANCE_RELATIVE` près.

Aucune donnée personnelle : départ (0, 0) en mer, clés et identifiants
inventés, séances de `tests/fixtures/workouts.py`.
"""

from __future__ import annotations

import datetime as _dt
import difflib
import importlib
import json
import math
import os
import pkgutil
import re
import socket
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl

import httpx
import pytest

DOSSIER = Path(__file__).resolve().parent
TESTS = DOSSIER.parent
FIXTURES = TESTS / "fixtures"

for _chemin in (TESTS, TESTS / "api"):
    if str(_chemin) not in sys.path:
        sys.path.insert(0, str(_chemin))

# --- l'instant figé ------------------------------------------------------------

#: Le jour des séances fabriquées (`workouts.evenement`) et des bouchons des
#: tests de `sortie` : mardi 8 septembre 2026, 09:00 à Paris (07:00 UTC).
INSTANT = _dt.datetime(2026, 9, 8, 7, 0, tzinfo=_dt.UTC)
JOUR = "2026-09-08"

_DATE = _dt.date
_DATETIME = _dt.datetime


class _MetaDate(type):
    """`isinstance(une_vraie_date, DateFigee)` doit rester vrai : le code
    remplacé teste `isinstance(o, date)` sur des dates qu'il n'a pas créées."""

    def __instancecheck__(cls, objet: object) -> bool:
        return isinstance(objet, cls._vraie)  # type: ignore[attr-defined]

    def __subclasscheck__(cls, sous: type) -> bool:
        return issubclass(sous, cls._vraie)  # type: ignore[attr-defined]


class DateFigee(_DATE, metaclass=_MetaDate):
    _vraie = _DATE

    @classmethod
    def __get_pydantic_core_schema__(cls, source: Any, handler: Any) -> Any:
        # Les routes de l'API annotent `date` en chaîne (`from __future__ import
        # annotations`) : FastAPI la résout au premier appel, dans le module…
        # où elle vaut désormais `DateFigee`. Pydantic la valide comme une date.
        return handler(_DATE)

    @classmethod
    def today(cls) -> _dt.date:
        return _maintenant(None).date()


class DatetimeFigee(_DATETIME, metaclass=_MetaDate):
    _vraie = _DATETIME

    @classmethod
    def __get_pydantic_core_schema__(cls, source: Any, handler: Any) -> Any:
        return handler(_DATETIME)

    @classmethod
    def now(cls, tz: _dt.tzinfo | None = None) -> _dt.datetime:
        return _maintenant(tz)

    @classmethod
    def today(cls) -> _dt.datetime:
        return _maintenant(None)

    @classmethod
    def utcnow(cls) -> _dt.datetime:
        return INSTANT.replace(tzinfo=None)


def _maintenant(tz: _dt.tzinfo | None) -> _dt.datetime:
    """Comme `datetime.now(tz)` : sans fuseau, l'heure locale naïve de la machine
    (celle que `fuseau_de_paris` pose), avec fuseau, l'instant converti."""
    if tz is None:
        return INSTANT.astimezone().replace(tzinfo=None)
    return INSTANT.astimezone(tz)


def _modules_du_paquet() -> list[str]:
    import ourouler

    noms = ["ourouler"]
    for info in pkgutil.walk_packages(ourouler.__path__, prefix="ourouler."):
        noms.append(info.name)
    return noms


def figer_horloge(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Fige `date`/`datetime` dans chaque module `ourouler.*`. Rend les modules touchés.

    Tous les modules sont importés d'abord : la CLI importe ses commandes
    paresseusement, et un module importé *après* le remplacement garderait la
    vraie horloge. Le remplacement vise l'**attribut du module** (`from
    datetime import date`), pas la classe elle-même, qui est immuable.
    """
    for nom in _modules_du_paquet():
        try:
            importlib.import_module(nom)
        except Exception:  # noqa: BLE001 — un module optionnel absent n'arrête rien
            continue
    touches = []
    for nom, module in sorted(sys.modules.items()):
        if not (nom == "ourouler" or nom.startswith("ourouler.")) or module is None:
            continue
        if getattr(module, "date", None) is _DATE:
            monkeypatch.setattr(module, "date", DateFigee)
            touches.append(nom)
        if getattr(module, "datetime", None) is _DATETIME:
            monkeypatch.setattr(module, "datetime", DatetimeFigee)
            touches.append(nom)
    return sorted(set(touches))


# --- la garde réseau ---------------------------------------------------------------


class ReseauInterdit(BaseException):
    """Un test a tenté d'ouvrir une connexion. Règle absolue 3 de CLAUDE.md."""


@pytest.fixture(autouse=True)
def garde_reseau(monkeypatch: pytest.MonkeyPatch) -> None:
    """La garde de `tests/api/conftest.py` (`reseau_interdit`), pour les modules
    hors de `tests/api/` qui l'importent.

    Une fixture importée dans un module de test s'applique à ce module : pas
    de `conftest.py` de plus sous `tests/` — quatre `conftest.py` rendent
    `from conftest import …` encore plus ambigu qu'avec trois (constaté :
    `tests/adversarial/test_adv_invariants.py` ne se collecte plus quand un
    autre `conftest.py` est chargé avant le sien). `BaseException` pour
    qu'aucun `except Exception` du code testé ne l'avale ; le réseau rejoué
    passe par `httpx.MockTransport`, qui n'ouvre aucune socket.
    """

    def refuser(*_args: Any, **_kwargs: Any):
        raise ReseauInterdit("réseau interdit dans les sorties de référence")

    monkeypatch.setattr(socket.socket, "connect", refuser)
    monkeypatch.setattr(socket.socket, "connect_ex", refuser)
    monkeypatch.setattr(socket, "create_connection", refuser)
    monkeypatch.setattr(socket, "getaddrinfo", refuser)


# --- le réseau rejoué ------------------------------------------------------------

HOTE_BROUTER = "brouter.exemple.test"
MODELE_PRINCIPAL = "modele_principal_test"
MODELE_SECOND = "modele_second_test"


def _meteo_prevision(requete: httpx.Request) -> httpx.Response:
    """Open-Meteo : une série horaire **qui suit la fenêtre demandée**.

    Pluie au nord du départ pour le modèle principal, à l'est pour le second :
    les deux modèles divergent, et la référence fige la façon dont le
    désaccord est rendu (règle absolue 5 : affiché, jamais moyenné).
    """
    p = requete.url.params
    lats = [float(x) for x in p["latitude"].split(",")]
    lons = [float(x) for x in p["longitude"].split(",")]
    debut = _DATETIME.fromisoformat(p["start_hour"])
    fin = _DATETIME.fromisoformat(p["end_hour"])
    n = int((fin - debut).total_seconds() // 3600) + 1
    heures = [(debut + _dt.timedelta(hours=i)).strftime("%Y-%m-%dT%H:%M") for i in range(n)]
    second = p.get("models") == MODELE_SECOND
    blocs = []
    for lat, lon in zip(lats, lons, strict=True):
        pluie = 2.0 if (lon > 0 if second else lat > 0) else 0.0
        blocs.append(
            {
                "latitude": lat,
                "longitude": lon,
                "hourly": {
                    "time": heures,
                    "precipitation": [pluie] * n,
                    "rain": [pluie] * n,
                    "wind_speed_10m": [14.0 + i for i in range(n)],
                    "wind_direction_10m": [45.0] * n,
                    "wind_gusts_10m": [25.0] * n,
                    "apparent_temperature": [11.5] * n,
                    "temperature_2m": [14.0] * n,
                },
            }
        )
    return httpx.Response(200, json=blocs if len(blocs) > 1 else blocs[0])


def _meteo_archive(requete: httpx.Request) -> httpx.Response:
    """L'archive Open-Meteo : 24 heures sans vent, 15 °C, pression standard."""
    jour = requete.url.params["start_date"]
    return httpx.Response(
        200,
        json={
            "latitude": 0.0,
            "longitude": 0.0,
            "hourly": {
                "time": [f"{jour}T{h:02d}:00" for h in range(24)],
                "wind_speed_10m": [0.0] * 24,
                "wind_direction_10m": [0.0] * 24,
                "temperature_2m": [15.0] * 24,
                "surface_pressure": [1013.25] * 24,
            },
        },
    )


def _intervals(requete: httpx.Request) -> httpx.Response:
    """Intervals.icu : une séance « 4x8 fabriquée » le 8 septembre, rien ailleurs."""
    import test_seance_intervals as tsi

    chemin = requete.url.path
    if chemin.endswith("/events") or "/events" in chemin:
        debut = requete.url.params.get("oldest")
        fin = requete.url.params.get("newest")
        dedans = debut is None or fin is None or debut[:10] <= JOUR <= fin[:10]
        charge = [tsi.W.evenement(tsi.W.groupes_watts(), nom="4x8 fabriquée")] if dedans else []
        return httpx.Response(200, json=charge)
    if chemin.rstrip("/").endswith(f"athlete/{tsi.ATHLETE}"):
        return httpx.Response(200, json={"id": tsi.ATHLETE, "icu_weight": 70.0})
    return httpx.Response(404, json={"error": "inconnu du rejeu"})


#: Relief par azimut (mètres d'amplitude) : les boucles ne se valent pas, et
#: le placement des blocs a de quoi trier.
RELIEF_PAR_AZIMUT = {0.0: 1.0, 45.0: 6.0, 90.0: 25.0, 135.0: 3.0, 180.0: 12.0, 225.0: 2.0}

#: Classes de route par tronçon, tournées selon l'azimut : une route à trafic,
#: un chemin non revêtu, un tronçon sans tag — sans cela tous les coûts de
#: route valent zéro et aucun poids de `boucle/couts.py` n'est exercé.
TAGS_TOURNANTS = (
    "highway=tertiary surface=asphalt",
    "highway=primary surface=asphalt maxspeed=80",
    "highway=tertiary surface=asphalt",
    "highway=track surface=gravel",
    "highway=residential surface=asphalt",
    "",
)


def _brouter(requete: httpx.Request) -> httpx.Response:
    """BRouter : l'anneau de `tests/test_sortie_commande.py`, relief et routes variés.

    La géométrie et le format du serveur réel sont empruntés tels quels
    (`anneau`, `reponse_anneau`) ; seuls l'amplitude du relief et les tags des
    tronçons dépendent ici de l'azimut demandé.
    """
    import test_sortie_commande as tsc

    azimut = float(requete.url.params["roundTripStartDirection"])
    corps = tsc.reponse_anneau(
        tsc.anneau(azimut, amplitude_m=RELIEF_PAR_AZIMUT.get(azimut % 360, 4.0))
    )
    messages = corps["features"][0]["properties"]["messages"]
    colonne = messages[0].index("WayTags")
    decalage = int(azimut // 45)
    for i, ligne in enumerate(messages[1:]):
        ligne[colonne] = TAGS_TOURNANTS[(i + decalage) % len(TAGS_TOURNANTS)]
    return httpx.Response(200, json=corps)


def _geocodage_ban(requete: httpx.Request) -> httpx.Response:
    texte = (FIXTURES / "geocodage" / "ban_franc.json").read_text(encoding="utf-8")
    return httpx.Response(200, json=json.loads(texte))


def _geocodage_nominatim(requete: httpx.Request) -> httpx.Response:
    texte = (FIXTURES / "geocodage" / "nominatim_un_candidat.json").read_text(encoding="utf-8")
    return httpx.Response(200, json=json.loads(texte))


AIGUILLAGE: dict[str, Callable[[httpx.Request], httpx.Response]] = {
    "api.open-meteo.com": _meteo_prevision,
    "archive-api.open-meteo.com": _meteo_archive,
    HOTE_BROUTER: _brouter,
    "intervals.icu": _intervals,
    "data.geopf.fr": _geocodage_ban,
    "nominatim.openstreetmap.org": _geocodage_nominatim,
}

#: Paramètres retirés du journal : aucun n'est un secret (les secrets sont
#: dans les en-têtes, jamais journalisés), mais ceux-ci ne portent pas de
#: comportement — ils portent la liste des variables demandées, déjà figée
#: par le code du connecteur et sans effet sur la suite.
PARAMETRES_TUS = frozenset({"hourly"})


class Rejeu:
    """Le routeur, et le journal des appels qu'il a servis."""

    def __init__(self) -> None:
        self.journal: list[str] = []

    def __call__(self, requete: httpx.Request) -> httpx.Response:
        hote = requete.url.host
        servir = AIGUILLAGE.get(hote)
        if servir is None:
            raise AssertionError(f"réseau rejoué : hôte inattendu {hote!r} ({requete.url})")
        params = sorted(
            (cle, valeur)
            for cle, valeur in parse_qsl(requete.url.query.decode(), keep_blank_values=True)
            if cle not in PARAMETRES_TUS
        )
        self.journal.append(
            f"{requete.method} {hote}{requete.url.path}"
            + ("?" + "&".join(f"{c}={v}" for c, v in params) if params else "")
        )
        return servir(requete)


def rejouer_reseau(monkeypatch: pytest.MonkeyPatch) -> Rejeu:
    """Remplace `httpx.Client` par une sous-classe au transport rejoué."""
    rejeu = Rejeu()
    vrai_client = httpx.Client

    class ClientRejoue(vrai_client):  # type: ignore[misc, valid-type]
        def __init__(self, *args: Any, transport: Any = None, **kwargs: Any) -> None:
            super().__init__(
                *args, transport=transport or httpx.MockTransport(rejeu), **kwargs
            )

    monkeypatch.setattr(httpx, "Client", ClientRejoue)
    return rejeu


# --- la configuration synthétique et la mise en place ----------------------------

#: Deux vélos, chacun rattaché par une **période** (étape 4 de
#: `rattacher_velo`) : les sorties importées n'ont ni capteur ni équipement.
CONFIG_TOML = """
historique_depuis = "2026-01-01"

[depart]
nom = "Point zéro"
latitude = 0.0
longitude = 0.0

[cycliste]
masse_kg = 91.0
ftp_w = 200

[[velos]]
nom = "RCR"
usage = "route"
periodes = [{{ debut = "2026-01-01", fin = "2026-01-31" }}]

[[velos]]
nom = "BMC"
usage = "clm"
periodes = [{{ debut = "2026-02-01", fin = "2026-02-28" }}]

[meteo]
directions = 8
distances_km = [15, 25]
modele = "{modele}"
second_avis = "{second}"
horizon_h = 4

[brouter]
url = "https://{brouter}"
profil = "fastbike"
timeout_s = 5.0

[boucle]
vitesse_moyenne_kmh = 27.0
sens = "horaire"
candidates = 4

[intervals]
athlete_id = "{athlete}"
api_key = "{cle}"

[cache]
dossier = "{cache}"
"""


def ecrire_config(chemin: Path, cache: Path, *, avec_intervals: bool = True) -> Path:
    """Écrit la configuration synthétique. `avec_intervals=False` : clé absente."""
    import test_seance_intervals as tsi

    chemin.write_text(
        CONFIG_TOML.format(
            modele=MODELE_PRINCIPAL,
            second=MODELE_SECOND,
            brouter=HOTE_BROUTER,
            athlete=tsi.ATHLETE if avec_intervals else "",
            cle=tsi.CLE if avec_intervals else "",
            cache=cache,
        ),
        encoding="utf-8",
    )
    return chemin


def preparer(monkeypatch: pytest.MonkeyPatch) -> Rejeu:
    """Environnement vidé des `OUROULER_*`, horloge figée, réseau rejoué.

    Les variables `OUROULER_*` de la machine surchargent la configuration
    (`config._survoler_environnement`) : une clé Intervals posée dans le shell
    du mainteneur changerait la référence. Elles sont retirées le temps du test.
    """
    for nom in list(os.environ):
        if nom.startswith("OUROULER_"):
            monkeypatch.delenv(nom)
    figer_horloge(monkeypatch)
    return rejouer_reseau(monkeypatch)


# --- normalisation et comparaison ---------------------------------------------

#: Identifiants tirés au hasard par le code : UUID (tâches de fond, fichiers
#: déposés, générations), et jetons hexadécimaux longs. Leur valeur ne dit
#: rien du comportement ; leur **présence** et leur place, si — d'où un
#: remplacement par un marqueur plutôt qu'une suppression.
UUID = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b")
HEX_LONG = re.compile(r"\b[0-9a-f]{24,}\b")


def normaliser(valeur: Any, remplacements: dict[str, str]) -> Any:
    """Remplace, dans toutes les chaînes, les chemins temporaires et les aléas."""
    if isinstance(valeur, dict):
        return {
            _normaliser_texte(str(cle), remplacements): normaliser(sous, remplacements)
            for cle, sous in valeur.items()
        }
    if isinstance(valeur, list):
        return [normaliser(sous, remplacements) for sous in valeur]
    if isinstance(valeur, str):
        return _normaliser_texte(valeur, remplacements)
    return valeur


def _normaliser_texte(texte: str, remplacements: dict[str, str]) -> str:
    # Les plus longs d'abord : un chemin temporaire en contient un autre.
    for avant in sorted(remplacements, key=len, reverse=True):
        texte = texte.replace(avant, remplacements[avant])
    texte = UUID.sub("<UUID>", texte)
    return HEX_LONG.sub("<HEX>", texte)


def arrondir(valeur: Any, chiffres: int) -> Any:
    """Arrondit chaque flottant à `chiffres` chiffres significatifs (calibrer seulement)."""
    if isinstance(valeur, dict):
        return {cle: arrondir(sous, chiffres) for cle, sous in valeur.items()}
    if isinstance(valeur, list):
        return [arrondir(sous, chiffres) for sous in valeur]
    if isinstance(valeur, float) and math.isfinite(valeur) and valeur != 0.0:
        return float(f"{valeur:.{chiffres}g}")
    return valeur


def serialiser(valeur: Any) -> str:
    return json.dumps(valeur, sort_keys=True, indent=2, ensure_ascii=False) + "\n"


#: Écart **relatif** admis entre un flottant mesuré et sa référence. Même
#: raisonnement que `TOLERANCE_GOLDEN` de `tests/adversarial/
#: test_adv_vent_placement.py` (1e-13, cinquante fois l'écart de plateforme
#: observé entre macOS et Linux, 1,9e-15), porté à 1e-12 parce que ces
#: références traversent des chaînes de calcul plus longues (boucle entière,
#: placement, météo le long du tracé). Toujours sept ordres de grandeur sous la
#: plus petite dérive qu'on veut voir (un mètre sur 30 km : 3e-5). Pas de
#: tolérance absolue : un zéro reste un zéro.
TOLERANCE_RELATIVE = 1e-12


def _proches(a: Any, b: Any) -> bool:
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(_proches(a[k], b[k]) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(_proches(x, y) for x, y in zip(a, b, strict=True))
    if isinstance(a, float) and isinstance(b, float | int) and not isinstance(b, bool):
        return math.isclose(a, b, rel_tol=TOLERANCE_RELATIVE, abs_tol=0.0)
    if isinstance(b, float) and isinstance(a, int) and not isinstance(a, bool):
        return math.isclose(a, b, rel_tol=TOLERANCE_RELATIVE, abs_tol=0.0)
    return type(a) is type(b) and a == b


def comparer_a_la_reference(
    obtenu: Any, reference: Path, regenerer: bool, commande_regeneration: str
) -> None:
    """Compare `obtenu` (déjà normalisé) au fichier de référence, ou le réécrit.

    L'égalité exacte du texte sérialisé passe d'abord ; à défaut, la même
    structure à `TOLERANCE_RELATIVE` près sur les flottants. Sinon, échec avec
    le diff : c'est un changement de comportement.
    """
    texte = serialiser(obtenu)
    if regenerer:
        reference.parent.mkdir(parents=True, exist_ok=True)
        reference.write_text(texte, encoding="utf-8")
        pytest.skip(f"référence régénérée : {reference.name}")
    assert reference.is_file(), (
        f"référence absente : {reference.name} — la créer par {commande_regeneration}"
    )
    attendu = reference.read_text(encoding="utf-8")
    if texte == attendu or _proches(json.loads(texte), json.loads(attendu)):
        return
    diff = "".join(
        difflib.unified_diff(
            attendu.splitlines(keepends=True),
            texte.splitlines(keepends=True),
            fromfile=f"{reference.name} (référence)",
            tofile="obtenu",
            n=2,
        )
    )
    if len(diff) > 6000:
        diff = diff[:6000] + "\n[… diff tronqué …]\n"
    pytest.fail(
        f"changement de comportement : {reference.name} ne correspond plus à la sortie. "
        f"Relire le diff comme un changement de comportement, puis {commande_regeneration}\n"
        + diff,
        pytrace=False,
    )
