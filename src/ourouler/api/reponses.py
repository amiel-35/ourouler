"""Les réponses réussies de l'API, décrites pour le contrat OpenAPI.

Sans eux, le schéma ne décrirait **aucune** réponse réussie (les 200 seraient
des objets vides), et les types du front ne seraient vérifiés que pour les
requêtes. Ces modèles décrivent ce que les routes rendent déjà.

**Ils décrivent, ils ne filtrent pas.** Une route les déclare par
`responses={200: {"model": …}}` en gardant `response_model=dict`
(`reponse_de`) : FastAPI les publie dans le schéma, mais ne s'en sert pas
pour sérialiser. Un `response_model` ordinaire validerait la réponse, en retirerait les champs
non déclarés, les réordonnerait dans l'ordre du modèle et convertirait un
entier en flottant là où le modèle le dit — un changement de corps pour le
front, et une 500 le jour où le rendu produit une valeur que le modèle
n'attend pas. Le corps reste donc exactement celui du rendu ; que ces
modèles disent vrai, `tests/api/test_reponses_openapi.py` le vérifie sur
les réponses de référence (`tests/caracterisation/api_*.json`).

**Permissifs au-delà du premier niveau** (`extra="allow"`, `dict[str, Any]`) :
chaque champ de premier niveau des données est nommé et typé ; ce qu'il y a
dessous reste ouvert, pour ne pas figer ici le détail d'un rendu que
`rendu/` fait évoluer. Les champs sont ceux que le rendu écrit toujours :
ils sont déclarés requis, avec `None` quand il peut valoir `null`.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict


class _Ouvert(BaseModel):
    """Un objet dont les champs nommés sont garantis, et les autres admis."""

    model_config = ConfigDict(extra="allow")


# --- ce que plusieurs réponses partagent ------------------------------------------


class Avertissement(_Ouvert):
    """Une phrase du cœur et son code (`api/adaptateur.Avertissement`)."""

    code: str
    message: str


class Budget(_Ouvert):
    """Ce qu'une opération est censée coûter sur ce serveur (`adaptateur.Budgets`)."""

    operation: str
    attendu_ms: int
    source: Literal["defaut", "mesure"]
    n: int
    median_ms: int | None


class FichierServi(_Ouvert):
    """Un fichier que le serveur garde pour le cycliste (carte, GPX)."""

    id: str
    nom: str
    url: str


class Lieu(_Ouvert):
    nom: str
    latitude: float
    longitude: float


# --- les données de chaque route ----------------------------------------------------


class DonneesGeocodage(_Ouvert):
    adresse: str
    ambigu: bool
    motif_ambiguite: str | None
    candidats: list[dict[str, Any]]


class DonneesVentDepart(_Ouvert):
    jour: str
    depart: str
    horizon_jours: int
    posee: bool
    motif: str | None
    vent_kmh: float | None
    vent_depuis_deg: float | None
    vent_depuis_nom: str | None
    seuil_kmh: float
    choix: list[str]
    azimuts_par_choix: dict[str, Any]


class DonneesMeteo(_Ouvert):
    depart: Lieu
    debut: str
    horizon_h: int
    modele: str
    second_avis: str | None
    meilleure_direction: dict[str, Any] | None
    cellules: list[dict[str, Any]]


class DonneesSemaine(_Ouvert):
    depuis: str
    jusqua: str
    #: Un jour par date : `seance` vaut `null` un jour sans séance.
    jours: list[dict[str, Any]]


class DonneesSeance(_Ouvert):
    jour: str
    nom: str
    duree_s: int
    n_blocs: int
    distance_estimee_m: float
    vitesses: dict[str, Any]
    meta: dict[str, Any]
    avertissements: list[Any]
    etapes: list[dict[str, Any]]


class DonneesJourSansSeance(BaseModel):
    """Un jour sans séance **n'est pas une erreur** : 200, `seance: null`."""

    model_config = ConfigDict(extra="forbid")

    jour: str
    seance: None


class DonneesSortie(_Ouvert):
    jour: str
    seance: dict[str, Any]
    demande: dict[str, Any]
    compteur: dict[str, Any] | None
    modele_physique: str
    modele_meteo: dict[str, Any]
    meteo_absente: dict[str, Any] | None
    seuil_bloc_bien_place: float
    tolerance_egalite: float
    gpx: FichierServi | None
    carte: FichierServi | None
    ecartees: list[Any]
    tenue: dict[str, Any] | None
    propositions: list[dict[str, Any]]
    #: Vrai quand ce calcul est parti du départ de repli du produit
    #: (« Paris ») faute de départ renseigné, jamais du départ demandé —
    #: fiche `docs/backlog/2026-09-28-bug-depart-fictif-golfe-de-guinee.md`.
    #: Le front affiche alors un bandeau vers Réglages.
    depart_par_defaut: bool
    #: Deux propositions au lieu de trois : l'explication, sinon `null`.
    motif_deux_propositions: str | None
    #: Trois propositions qui se valent : l'explication, sinon `null`.
    motif_equivalence: str | None
    question_vent: dict[str, Any] | None
    arbitrage: dict[str, Any] | None
    candidates: list[dict[str, Any]]
    #: L'identifiant à repasser à `…/propositions/{n}/gpx`.
    generation: str | None = None


class DonneesSortieSansSeance(_Ouvert):
    """Rien de planifié ce jour-là : une réponse, pas une erreur (`rendu.json_sans_seance`)."""

    jour: str
    seance: None
    candidates: list[Any]
    carte: FichierServi | None
    depart_par_defaut: bool


class DonneesBoucle(_Ouvert):
    depart: dict[str, Any]
    demande: dict[str, Any]
    pauses: list[Any]
    compteur: dict[str, Any] | None
    vitesse_moyenne_kmh: float
    sens_prefere: str
    modele: str
    second_avis: str | None
    modele_meteo: dict[str, Any]
    meteo_absente: dict[str, Any] | None
    gpx: FichierServi | None
    poids_routes: dict[str, Any] | None
    modele_physique: dict[str, Any]
    candidates: list[dict[str, Any]]
    #: Même signal que `DonneesSortie.depart_par_defaut`.
    depart_par_defaut: bool


class DonneesInventaire(_Ouvert):
    depuis: str
    total: int
    autres_sports: int
    autres_sports_par_libelle: dict[str, Any]
    par_velo: list[dict[str, Any]]
    par_mois: list[dict[str, Any]]
    anomalies: list[Any]
    #: Les lignes d'import et de synchronisation (vide : l'API ne synchronise pas).
    journal: list[str]


class DonneesCalibrations(_Ouvert):
    sorties_necessaires: int
    ftp_renseignee: bool
    velos: list[dict[str, Any]]


class DonneesZones(_Ouvert):
    ftp_w: float
    position_zone: float
    zone_endurance: int
    hors_bande: bool
    zones: list[dict[str, Any]]
    valeurs_liees: dict[str, Any]


class DonneesProfilIntervals(_Ouvert):
    ftp_w: float | None
    masse_kg: float | None


class DonneesProfil(_Ouvert):
    """Le profil **public** : les secrets y sont masqués (`rendu/profil.py`)."""

    historique_depuis: str | None
    assistant_recommande: bool
    depart: dict[str, Any] | None
    cycliste: dict[str, Any] | None
    velos: list[dict[str, Any]]
    meteo: dict[str, Any]
    boucle: dict[str, Any]
    seance: dict[str, Any]
    tenue: dict[str, Any]
    evitements: list[Any]
    intervals: dict[str, Any]
    calibration: dict[str, Any]
    services: dict[str, Any]


# --- les enveloppes -------------------------------------------------------------------


class _Enveloppe(_Ouvert):
    #: Pour qui la réponse a été calculée : le front refuse d'afficher celle d'un autre.
    proprietaire: str


class _Calcul(_Enveloppe):
    """La forme de toute route de calcul (`adaptateur.Resultat.enveloppe`)."""

    avertissements: list[Avertissement]
    #: Ce que le calcul a réellement pris.
    duree_ms: int
    #: Ce que le front avait annoncé avant de lancer le calcul.
    budget: Budget


class ReponseGeocodage(_Calcul):
    donnees: DonneesGeocodage


class ReponseVentDepart(_Calcul):
    donnees: DonneesVentDepart


class ReponseMeteo(_Calcul):
    donnees: DonneesMeteo


class ReponseSemaine(_Calcul):
    donnees: DonneesSemaine


class ReponseSeance(_Calcul):
    donnees: DonneesSeance | DonneesJourSansSeance


class ReponseSeanceDeposee(ReponseSeance):
    #: Le fichier déposé : son identifiant se repasse à `POST /sorties`.
    fichier: FichierServi


class ReponseSortie(_Calcul):
    donnees: DonneesSortie | DonneesSortieSansSeance


class ReponseBoucle(_Calcul):
    donnees: DonneesBoucle


class ReponseInventaire(_Calcul):
    donnees: DonneesInventaire


class ReponseCalcul(_Calcul):
    """Une route de calcul dont les données ne sont pas détaillées ici (simulation…)."""

    donnees: dict[str, Any]


class ReponseCalibrations(_Enveloppe):
    donnees: DonneesCalibrations


class ReponseZones(_Enveloppe):
    donnees: DonneesZones


class ReponseProfilIntervals(_Enveloppe):
    donnees: DonneesProfilIntervals


class ReponseProfil(_Enveloppe):
    donnees: DonneesProfil


class Capacites(_Ouvert):
    brouter: bool
    intervals: bool
    velos: list[str]


class ReponseSysteme(_Enveloppe):
    version: str
    capacites: Capacites
    budgets: list[Budget]


class ReponseBudgets(_Enveloppe):
    budgets: list[Budget]


def reponse_de(modele: type[BaseModel]) -> dict:
    """Les arguments du décorateur de route qui **décrivent** la réponse 200 sans la filtrer.

    `response_model=dict` est ce que FastAPI déduisait déjà de `-> dict` : la
    réponse continue d'être sérialisée exactement comme avant — par
    pydantic-core, qui écrit par exemple `0.000054` là où `json.dumps`
    écrirait `5.4e-05`. Le retirer (`response_model=None`) changeait ces
    octets : mesuré sur les géométries de `POST /sorties` et `POST /boucles`.
    `responses` publie le modèle ; `publier_modeles` retire ensuite du schéma
    l'objet vide que `dict` y ajoutait à côté.
    """
    return {"response_model": dict, "responses": {200: {"model": modele}}}


#: Ce que `response_model=dict` ajoute au schéma d'une réponse 200 : un objet
#: sans propriétés, fusionné par FastAPI avec le `$ref` du modèle déclaré.
_CLES_DE_DICT = frozenset({"additionalProperties", "type", "title"})


def publier_modeles(schema: dict) -> dict:
    """Ne garde, pour chaque réponse 200 qui déclare un modèle, que la référence au modèle.

    FastAPI fusionne le schéma de `response_model=dict` (`{"type": "object",
    "additionalProperties": true, "title": …}`) avec le `$ref` du modèle de
    `responses` : deux descriptions pour une réponse, dont une vide. Seule la
    seconde dit quelque chose ; la première est retirée. Rien d'autre n'est
    touché : chemins, paramètres, `operationId` et corps de requête restent
    ceux que FastAPI a produits.
    """
    for operations in schema.get("paths", {}).values():
        for operation in operations.values():
            if not isinstance(operation, dict):
                continue
            contenu = operation.get("responses", {}).get("200", {}).get("content", {})
            for media in contenu.values():
                forme = media.get("schema", {})
                if "$ref" in forme and set(forme) - {"$ref"} <= _CLES_DE_DICT:
                    media["schema"] = {"$ref": forme["$ref"]}
    return schema


__all__ = [
    "Avertissement",
    "Budget",
    "FichierServi",
    "ReponseBoucle",
    "ReponseBudgets",
    "ReponseCalcul",
    "ReponseCalibrations",
    "ReponseGeocodage",
    "ReponseInventaire",
    "ReponseMeteo",
    "ReponseProfil",
    "ReponseProfilIntervals",
    "ReponseSeance",
    "ReponseSeanceDeposee",
    "ReponseSemaine",
    "ReponseSortie",
    "ReponseSysteme",
    "ReponseVentDepart",
    "ReponseZones",
    "publier_modeles",
    "reponse_de",
]
