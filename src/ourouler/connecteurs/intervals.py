"""Connecteur Intervals.icu : liste des activités, fichier d'origine, séances.

Un connecteur ne fait que rapatrier des fichiers et des métadonnées
(doctrine §5) : c'est le cache qui relit le fichier avec le lecteur unique.

Le client HTTP est injectable pour que les tests n'appellent jamais le
réseau. **La clé d'API n'apparaît jamais dans un message d'erreur, un log
ni un `repr`** : les messages ne nomment que le libellé de l'endpoint et le
code HTTP.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

import httpx

from ourouler.activites.cache import Cache
from ourouler.erreurs import ErreurConnecteur, ErreurLecture

BASE_URL = "https://intervals.icu"

#: Délai par défaut d'un appel, en secondes.
DELAI_S = 30.0

#: Au-delà de ce nombre d'activités dans une réponse, on suppose que l'API a
#: tronqué et on redemande mois par mois.
SEUIL_TRONCATURE = 100

#: Extension retenue quand la réponse ne dit rien du format du fichier.
EXTENSION_DEFAUT = "fit"


@dataclass
class RapportSynchro:
    vues: int = 0
    ajoutees: int = 0
    ignorees: int = 0
    echecs: int = 0
    messages: list[str] = field(default_factory=list)


class ClientIntervals:
    """Accès en lecture à un compte Intervals.icu (auth basique `API_KEY:<clé>`)."""

    def __init__(
        self,
        athlete_id: str,
        api_key: str,
        http: httpx.Client | None = None,
        base_url: str = BASE_URL,
    ):
        if not athlete_id or not api_key:
            raise ErreurConnecteur(
                "Intervals.icu : athlete_id et api_key sont requis "
                "(Intervals.icu → Settings → Developer)"
            )
        self.athlete_id = str(athlete_id)
        self.base_url = base_url.rstrip("/")
        self._http = http if http is not None else httpx.Client(timeout=DELAI_S)
        # L'authentification est passée par requête : un client injecté par un
        # test n'est jamais modifié, et la clé ne vit que dans cet objet.
        self._auth = httpx.BasicAuth("API_KEY", str(api_key))

    def __repr__(self) -> str:  # ne jamais laisser fuir la clé dans une trace
        return f"ClientIntervals(athlete_id={self.athlete_id!r}, base_url={self.base_url!r})"

    # --- endpoints ------------------------------------------------------------

    def activites(self, depuis: date, jusqua: date | None = None) -> list[dict]:
        """Activités de la fenêtre, triées du plus ancien au plus récent.

        Si l'API tronque la réponse (voir `SEUIL_TRONCATURE`), la fenêtre est
        redemandée mois par mois et les résultats sont dédoublonnés par `id`.
        """
        jusqua = jusqua or date.today()
        if jusqua < depuis:
            return []
        brut = self._activites_fenetre(depuis, jusqua)
        if len(brut) >= SEUIL_TRONCATURE and _mois_suivant(depuis) <= jusqua:
            brut = []
            for debut_mois, fin_mois in _par_mois(depuis, jusqua):
                brut.extend(self._activites_fenetre(debut_mois, fin_mois))
        return _dedoublonner(brut)

    def telecharger_fichier(self, activite_id: str) -> tuple[bytes, str]:
        """Fichier d'origine d'une activité : (contenu, extension sans point)."""
        reponse = self._get(f"/api/v1/activity/{activite_id}/file", "activity/{id}/file")
        contenu = reponse.content
        if not contenu:
            raise ErreurConnecteur(
                f"Intervals.icu activity/{activite_id}/file : réponse vide"
            )
        return contenu, _extension(reponse, contenu)

    def evenements(self, jour: date) -> list[dict]:
        """Séances planifiées d'un jour."""
        reponse = self._get(
            f"/api/v1/athlete/{self.athlete_id}/events",
            "athlete/{id}/events",
            params={"oldest": jour.isoformat(), "newest": jour.isoformat()},
        )
        return _liste_de_dicts(reponse, "athlete/{id}/events")

    # --- interne --------------------------------------------------------------

    def _activites_fenetre(self, depuis: date, jusqua: date) -> list[dict]:
        reponse = self._get(
            f"/api/v1/athlete/{self.athlete_id}/activities",
            "athlete/{id}/activities",
            params={"oldest": depuis.isoformat(), "newest": jusqua.isoformat()},
        )
        return _liste_de_dicts(reponse, "athlete/{id}/activities")

    def _get(self, chemin: str, libelle: str, params: dict | None = None) -> httpx.Response:
        """Un GET authentifié. Les messages d'erreur ne citent que `libelle`."""
        try:
            reponse = self._http.request(
                "GET", f"{self.base_url}{chemin}", params=params, auth=self._auth
            )
        except httpx.HTTPError as e:
            raise ErreurConnecteur(
                f"Intervals.icu {libelle} : appel impossible ({type(e).__name__})"
            ) from e
        if reponse.status_code != 200:
            raise ErreurConnecteur(
                f"Intervals.icu {libelle} : HTTP {reponse.status_code}{_indice(reponse.status_code)}"
            )
        return reponse


def _indice(code: int) -> str:
    if code in (401, 403):
        return " — clé d'API refusée, vérifier [intervals] api_key et athlete_id"
    if code == 429:
        return " — trop d'appels, réessayer plus tard"
    if code >= 500:
        return " — panne côté Intervals.icu, réessayer plus tard"
    return ""


def _liste_de_dicts(reponse: httpx.Response, libelle: str) -> list[dict]:
    try:
        charge = reponse.json()
    except ValueError as e:
        raise ErreurConnecteur(f"Intervals.icu {libelle} : réponse JSON illisible") from e
    if charge is None:
        return []
    if not isinstance(charge, list):
        raise ErreurConnecteur(
            f"Intervals.icu {libelle} : tableau attendu, reçu {type(charge).__name__}"
        )
    return [element for element in charge if isinstance(element, dict)]


def _dedoublonner(activites: list[dict]) -> list[dict]:
    """Une activité par `id`, triée par date de début puis par identifiant."""
    par_id: dict[str, dict] = {}
    sans_id: list[dict] = []
    for activite in activites:
        identifiant = activite.get("id")
        if identifiant is None:
            sans_id.append(activite)
        else:
            par_id.setdefault(str(identifiant), activite)
    ordonnees = sorted(par_id.values(), key=lambda a: (str(a.get("start_date_local") or ""), str(a["id"])))
    return ordonnees + sans_id


def _par_mois(depuis: date, jusqua: date):
    """Découpe [depuis, jusqua] en fenêtres mensuelles inclusives."""
    debut = depuis
    while debut <= jusqua:
        fin = min(_mois_suivant(debut) - timedelta(days=1), jusqua)
        yield debut, fin
        debut = fin + timedelta(days=1)


def _mois_suivant(jour: date) -> date:
    return date(jour.year + jour.month // 12, jour.month % 12 + 1, 1)


def _extension(reponse: httpx.Response, contenu: bytes) -> str:
    """Extension du fichier : en-têtes d'abord, puis signature du contenu."""
    disposition = reponse.headers.get("content-disposition", "")
    for morceau in disposition.split(";"):
        _, _, valeur = morceau.partition("=")
        nom = valeur.strip().strip('"').lower()
        if nom.endswith((".fit", ".gpx", ".tcx")):
            return nom.rsplit(".", 1)[1]
    if len(contenu) >= 12 and contenu[8:12] == b".FIT":
        return "fit"
    debut = contenu[:600].lower()
    if b"trainingcenterdatabase" in debut:
        return "tcx"
    if b"<gpx" in debut:
        return "gpx"
    return EXTENSION_DEFAUT


# --- synchronisation ----------------------------------------------------------


def metadonnees(activite: dict) -> dict:
    """Métadonnées Intervals à recopier dans `meta` de l'entrée de cache."""
    equipement = activite.get("gear")
    if isinstance(equipement, dict):
        nom_equipement = equipement.get("name")
    else:
        nom_equipement = str(equipement) if equipement else None
    type_activite = str(activite.get("type") or "")
    return {
        "source_id": activite.get("id"),
        "nom": activite.get("name"),
        "sport": activite.get("type"),
        "appareil": activite.get("device_name"),
        "equipement": nom_equipement,
        "puissance_moy_w": activite.get("icu_average_watts") or activite.get("average_watts"),
        "interieur": bool(activite.get("trainer")) or type_activite.casefold().startswith("virtual"),
        "debut_local": activite.get("start_date_local"),
    }


def synchroniser(client: ClientIntervals, cache: Cache, depuis: date) -> RapportSynchro:
    """Rapatrie dans le cache les activités absentes. Ne télécharge rien d'autre."""
    rapport = RapportSynchro()
    for activite in client.activites(depuis):
        rapport.vues += 1
        identifiant = activite.get("id")
        if identifiant is None:
            rapport.echecs += 1
            rapport.messages.append("activité sans identifiant, ignorée")
            continue
        identifiant = str(identifiant)
        if cache.contient(source="intervals", id_externe=identifiant):
            rapport.ignorees += 1
            continue
        try:
            contenu, extension = client.telecharger_fichier(identifiant)
            cache.ajouter(
                contenu,
                source="intervals",
                id_externe=identifiant,
                extension=extension,
                meta=metadonnees(activite),
            )
        except (ErreurConnecteur, ErreurLecture) as e:
            rapport.echecs += 1
            rapport.messages.append(f"{identifiant} : {e}")
            continue
        rapport.ajoutees += 1
    return rapport
