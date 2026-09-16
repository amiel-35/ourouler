"""Connecteur de géocodage : une adresse tapée devient des candidats notés.

**Une adresse ambiguë est la normale, pas l'exception** (« 12 rue de la
Gare » existe dans des centaines de communes) : ce connecteur rend toujours
une **liste** de `Candidat`, avec leur score, et ne tranche jamais tout
seul — c'est à l'appelant (le front, plus tard) de faire choisir
l'utilisateur. Une adresse introuvable n'est pas une erreur technique : la
liste est simplement vide.

Deux fournisseurs, chacun sans clé d'API :

1. **La Base Adresse Nationale (BAN)**, servie aujourd'hui par la
   Géoplateforme de l'IGN (`https://data.geopf.fr/geocodage/search`, qui
   prend le relais de l'ancien `api-adresse.data.gouv.fr`, en cours de
   retrait). Données officielles françaises, excellentes en France
   (adresse au numéro de rue près), **inexistantes hors de France** — la
   BAN ne connaît que le territoire national, elle rend alors zéro
   candidat, jamais une erreur. Licence Etalab 2.0 (licence ouverte),
   aucune clé, débit limité à 50 requêtes/s par IP (mesuré sur la
   documentation officielle, 16/09/2026) — sans commune mesure avec l'usage
   d'un cycliste qui tape une adresse de temps en temps.

2. **Nominatim** (OpenStreetMap, `https://nominatim.openstreetmap.org`),
   en repli quand la BAN ne rend aucun candidat — hors de France, ou
   adresse que la BAN ne reconnaît pas. Couverture mondiale, mais la
   politique d'usage du service (operations.osmfoundation.org/policies/
   nominatim, relevée le 16/09/2026) impose :
   - **1 requête par seconde maximum** — jamais en jeu ici : ce connecteur
     n'appelle Nominatim qu'une fois par recherche d'adresse, après un
     échec de la BAN, jamais en boucle ;
   - un en-tête **`User-Agent` identifiant l'application** — les en-têtes
     par défaut d'une bibliothèque HTTP ne suffisent pas, `USER_AGENT`
     ci-dessous est envoyé sur chaque requête, y compris avec un client
     HTTP injecté par un test ;
   - l'**autocomplétion** et les **requêtes systématiques** (grille de
     points, liste exhaustive) sont interdites — ce connecteur ne fait
     jamais ni l'une ni l'autre, une recherche = une requête ;
   - une **attribution ODbL** visible côté appelant (« © contributeurs
     OpenStreetMap ») quand un résultat Nominatim est affiché.

Les deux clients HTTP sont injectables : les tests n'appellent jamais le
réseau (réponses enregistrées, anonymisées, dans `tests/fixtures/geocodage/`).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from ourouler.erreurs import ErreurConnecteur

BASE_URL_BAN = "https://data.geopf.fr/geocodage"
CHEMIN_RECHERCHE_BAN = "/search"

BASE_URL_NOMINATIM = "https://nominatim.openstreetmap.org"
CHEMIN_RECHERCHE_NOMINATIM = "/search"

#: Identifie l'application auprès de Nominatim (politique d'usage, voir
#: docstring du module). Envoyé sur chaque requête, quel que soit le client
#: HTTP injecté.
USER_AGENT_NOMINATIM = "ourouler-cli (https://github.com/amiel-35/ourouler)"

#: Nombre de candidats par défaut, côté appelant comme côté service.
LIMITE_DEFAUT = 5

DELAI_S = 10.0


@dataclass(frozen=True)
class Candidat:
    """Un candidat de géocodage. `score` n'est comparable qu'entre candidats de la même `source`."""

    label: str
    latitude: float
    longitude: float
    score: float
    source: str  # "ban" ou "nominatim"


class ClientBAN:
    """Client de la Base Adresse Nationale (Géoplateforme IGN). `http` est injectable."""

    def __init__(self, http: httpx.Client | None = None, base_url: str = BASE_URL_BAN) -> None:
        self.base_url = base_url.rstrip("/")
        self.http = http if http is not None else httpx.Client(timeout=DELAI_S)

    @property
    def url_recherche(self) -> str:
        return f"{self.base_url}{CHEMIN_RECHERCHE_BAN}"

    def chercher(self, adresse: str, *, limite: int = LIMITE_DEFAUT) -> list[Candidat]:
        """Candidats pour `adresse`, triés par score décroissant par le service. Liste vide si rien."""
        adresse = adresse.strip()
        if not adresse:
            raise ErreurConnecteur("BAN : adresse vide")
        params = {"q": adresse, "limit": limite}
        try:
            reponse = self.http.get(self.url_recherche, params=params)
        except httpx.HTTPError as e:
            raise ErreurConnecteur(
                f"BAN : injoignable sur {self.url_recherche} ({type(e).__name__})"
            ) from e
        if reponse.status_code >= 400:
            raise ErreurConnecteur(f"BAN : HTTP {reponse.status_code} sur {self.url_recherche}")
        try:
            charge = reponse.json()
        except ValueError as e:
            raise ErreurConnecteur(f"BAN : réponse non-JSON sur {self.url_recherche} ({e})") from e
        return _candidats_ban(charge, self.url_recherche)


class ClientNominatim:
    """Client Nominatim (OpenStreetMap). `http` est injectable."""

    def __init__(self, http: httpx.Client | None = None, base_url: str = BASE_URL_NOMINATIM) -> None:
        self.base_url = base_url.rstrip("/")
        self.http = http if http is not None else httpx.Client(timeout=DELAI_S)

    @property
    def url_recherche(self) -> str:
        return f"{self.base_url}{CHEMIN_RECHERCHE_NOMINATIM}"

    def chercher(self, adresse: str, *, limite: int = LIMITE_DEFAUT) -> list[Candidat]:
        """Candidats pour `adresse`, triés par pertinence par le service. Liste vide si rien."""
        adresse = adresse.strip()
        if not adresse:
            raise ErreurConnecteur("Nominatim : adresse vide")
        params = {"q": adresse, "format": "jsonv2", "limit": limite}
        # Le User-Agent est passé par requête, pas seulement à la construction
        # du client HTTP : un client injecté par un test (ou un futur
        # appelant) l'obtient quand même, la politique d'usage l'exige.
        headers = {"User-Agent": USER_AGENT_NOMINATIM}
        try:
            reponse = self.http.get(self.url_recherche, params=params, headers=headers)
        except httpx.HTTPError as e:
            raise ErreurConnecteur(
                f"Nominatim : injoignable sur {self.url_recherche} ({type(e).__name__})"
            ) from e
        if reponse.status_code >= 400:
            raise ErreurConnecteur(f"Nominatim : HTTP {reponse.status_code} sur {self.url_recherche}")
        try:
            charge = reponse.json()
        except ValueError as e:
            raise ErreurConnecteur(f"Nominatim : réponse non-JSON sur {self.url_recherche} ({e})") from e
        return _candidats_nominatim(charge, self.url_recherche)


def chercher_adresse(
    adresse: str,
    *,
    ban: ClientBAN | None = None,
    nominatim: ClientNominatim | None = None,
    limite: int = LIMITE_DEFAUT,
) -> list[Candidat]:
    """Cherche `adresse` : la BAN d'abord, Nominatim en repli si elle ne rend rien.

    Le repli ne se déclenche que sur une liste **vide** (pas de candidat
    trouvé en France), jamais pour masquer une panne : si la BAN lève
    `ErreurConnecteur` (service injoignable, réponse illisible…), l'erreur
    remonte telle quelle et Nominatim n'est pas appelé — une panne du
    service ne doit pas se travestir en « adresse introuvable ». Si
    Nominatim est ensuite appelé et échoue à son tour, son erreur remonte
    aussi, sans être avalée : les deux échecs sont traités comme n'importe
    quel autre `ErreurConnecteur` par l'appelant.
    """
    ban = ban if ban is not None else ClientBAN()
    candidats = ban.chercher(adresse, limite=limite)
    if candidats:
        return candidats
    nominatim = nominatim if nominatim is not None else ClientNominatim()
    return nominatim.chercher(adresse, limite=limite)


def _candidats_ban(charge: Any, url: str) -> list[Candidat]:
    if not isinstance(charge, dict) or not isinstance(charge.get("features"), list):
        raise ErreurConnecteur(f"BAN : réponse inattendue sur {url}")
    candidats = []
    for f in charge["features"]:
        try:
            proprietes = f["properties"]
            lon, lat = f["geometry"]["coordinates"]
            candidats.append(
                Candidat(
                    label=str(proprietes["label"]),
                    latitude=float(lat),
                    longitude=float(lon),
                    score=float(proprietes.get("score", 0.0)),
                    source="ban",
                )
            )
        except (KeyError, TypeError, ValueError) as e:
            raise ErreurConnecteur(f"BAN : candidat illisible sur {url} ({e})") from e
    return candidats


def _candidats_nominatim(charge: Any, url: str) -> list[Candidat]:
    if not isinstance(charge, list):
        raise ErreurConnecteur(f"Nominatim : réponse inattendue sur {url}")
    candidats = []
    for item in charge:
        try:
            candidats.append(
                Candidat(
                    label=str(item["display_name"]),
                    latitude=float(item["lat"]),
                    longitude=float(item["lon"]),
                    score=float(item.get("importance", 0.0)),
                    source="nominatim",
                )
            )
        except (KeyError, TypeError, ValueError) as e:
            raise ErreurConnecteur(f"Nominatim : candidat illisible sur {url} ({e})") from e
    return candidats
