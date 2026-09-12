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
from ourouler.activites.modele import TYPES_VELO
from ourouler.erreurs import ErreurConnecteur, ErreurLecture

BASE_URL = "https://intervals.icu"

#: Délai par défaut d'un appel, en secondes.
DELAI_S = 30.0

#: Extension retenue quand la réponse ne dit rien du format du fichier.
EXTENSION_DEFAUT = "fit"


@dataclass
class RapportSynchro:
    """Ce qu'une synchronisation a fait. `vues` compte tout ce que l'API a rendu.

    `ignorees` = déjà en cache, donc pas retéléchargée ; `mises_a_jour` est le
    sous-ensemble de celles-là dont on a rafraîchi les métadonnées sur place.
    `autres_sports` compte ce qui n'est pas du vélo et n'a jamais été demandé.
    """

    vues: int = 0
    ajoutees: int = 0
    ignorees: int = 0
    mises_a_jour: int = 0
    autres_sports: int = 0
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
        # Résolu au premier besoin, puis gardé : l'endpoint gear est appelé
        # une seule fois par client, quel que soit le nombre d'activités.
        self._equipements: dict[str, str] | None = None

    def __repr__(self) -> str:  # ne jamais laisser fuir la clé dans une trace
        return f"ClientIntervals(athlete_id={self.athlete_id!r}, base_url={self.base_url!r})"

    # --- endpoints ------------------------------------------------------------

    def activites(self, depuis: date, jusqua: date | None = None) -> list[dict]:
        """Activités de la fenêtre, triées du plus ancien au plus récent.

        La fenêtre est **systématiquement** découpée par mois civil : un appel
        par mois, quelle que soit la taille des réponses, et dédoublonnage par
        `id` à l'arrivée (deux fenêtres mensuelles peuvent renvoyer la même
        activité).

        Il y avait avant une détection de troncature : au-delà de 100
        activités dans une réponse, on redemandait mois par mois. Ce 100
        était **deviné** — la limite de l'API n'est pas documentée et le
        connecteur n'a jamais pu être confronté au vrai service, faute de clé
        (Q1). Si la vraie limite est plus basse, la troncature passait
        inaperçue et des sorties manquaient sans un mot. La découpe
        systématique coûte 25 appels gratuits pour deux ans d'historique et
        ne dépend d'aucune constante devinée.
        """
        jusqua = jusqua or date.today()
        if jusqua < depuis:
            return []
        brut: list[dict] = []
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

    def equipements(self) -> dict[str, str]:
        """Équipements de l'athlète : identifiant → nom. Un seul appel par client.

        La liste d'activités ne porte qu'un `gear.id` (« b0000001 ») : le nom
        lisible (« rcr », « BMC ») ne vient que d'ici. Le résultat est gardé
        dans l'instance, y compris quand il est vide.
        """
        if self._equipements is None:
            reponse = self._get(
                f"/api/v1/athlete/{self.athlete_id}/gear", "athlete/{id}/gear"
            )
            liste = _liste_de_dicts(reponse, "athlete/{id}/gear")
            self._equipements = {
                str(e["id"]): str(e.get("name") or "")
                for e in liste
                if e.get("id") is not None and e.get("name")
            }
        return self._equipements

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
    """Le corps doit être un tableau de dictionnaires, sinon erreur connecteur.

    `null` était traduit en liste vide et les éléments non-dictionnaires
    silencieusement filtrés. Les deux mentaient : « aucune activité » et « le
    service a répondu n'importe quoi » sont des situations différentes, et la
    seconde doit se voir. Une liste vide, elle, reste une réponse valide.
    """
    try:
        charge = reponse.json()
    except ValueError as e:
        raise ErreurConnecteur(f"Intervals.icu {libelle} : réponse JSON illisible") from e
    if not isinstance(charge, list):
        raise ErreurConnecteur(
            f"Intervals.icu {libelle} : tableau attendu, reçu {type(charge).__name__}"
        )
    intrus = [type(e).__name__ for e in charge if not isinstance(e, dict)]
    if intrus:
        raise ErreurConnecteur(
            f"Intervals.icu {libelle} : {len(intrus)} élément(s) du tableau ne sont pas "
            f"des objets JSON ({', '.join(sorted(set(intrus)))})"
        )
    return list(charge)


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


def metadonnees(activite: dict, equipements: dict[str, str] | None = None) -> dict:
    """Métadonnées Intervals à recopier dans `meta` de l'entrée de cache.

    `equipements` est la table « identifiant → nom » de `ClientIntervals.
    equipements()` : la liste d'activités ne porte qu'un `gear.id`, le nom
    lisible vient de là. Sans elle, on se rabat sur ce que `gear` contient.

    Les champs de rattachement (contrat §7) sont recopiés tels quels :
    `power_meter` (« MARQUE 1234 », inventé : la valeur réelle du
    mainteneur reste dans `docs/`), son numéro de série, `bilateral` (déduit de
    la présence d'`avg_lr_balance`, qu'un capteur unilatéral ne renvoie pas),
    `gear_id`, `trainer` et `device_name`.
    """
    brut_equipement = activite.get("gear")
    gear_id = None
    nom_equipement = None
    if isinstance(brut_equipement, dict):
        if brut_equipement.get("id") is not None:
            gear_id = str(brut_equipement["id"])
        nom_equipement = brut_equipement.get("name")
    elif brut_equipement:
        nom_equipement = str(brut_equipement)
    if gear_id and equipements:
        nom_equipement = equipements.get(gear_id) or nom_equipement
    type_activite = str(activite.get("type") or "")
    return {
        "source_id": activite.get("id"),
        "nom": activite.get("name"),
        "sport": activite.get("type"),
        "appareil": activite.get("device_name"),
        "device_name": activite.get("device_name"),
        "equipement": nom_equipement,
        "gear_id": gear_id,
        "power_meter": activite.get("power_meter"),
        "power_meter_serial": activite.get("power_meter_serial"),
        "bilateral": activite.get("avg_lr_balance") is not None,
        "trainer": bool(activite.get("trainer")),
        "puissance_moy_w": activite.get("icu_average_watts") or activite.get("average_watts"),
        "interieur": bool(activite.get("trainer")) or type_activite.casefold().startswith("virtual"),
        "debut_local": activite.get("start_date_local"),
    }


def synchroniser(
    client: ClientIntervals,
    cache: Cache,
    depuis: date,
    *,
    rafraichir_meta: bool = True,
    types: tuple[str, ...] | None = TYPES_VELO,
) -> RapportSynchro:
    """Rapatrie dans le cache les sorties vélo absentes. Ne télécharge rien d'autre.

    `types` filtre sur le type d'activité Intervals : par défaut seul le vélo
    est rapatrié, le compte contenant aussi de la course, de la natation et de
    la musculation. `types=None` élargit à tout.

    `rafraichir_meta` met à jour sur place les métadonnées des entrées déjà en
    cache (capteur de puissance, équipement, appareil) **sans** retélécharger
    le fichier : c'est ce qui permet d'enrichir un cache rempli avant que le
    rattachement par capteur existe, sans repayer 355 téléchargements.
    """
    rapport = RapportSynchro()
    activites = client.activites(depuis)
    equipements: dict[str, str] = {}
    if activites:
        try:
            equipements = client.equipements()
        except ErreurConnecteur as e:
            # Un nom d'équipement manquant dégrade le rattachement, il ne doit
            # pas empêcher la synchronisation — mais il se dit.
            rapport.messages.append(f"équipements non résolus : {e}")
    for activite in activites:
        rapport.vues += 1
        identifiant = activite.get("id")
        if identifiant is None:
            rapport.echecs += 1
            rapport.messages.append("activité sans identifiant, ignorée")
            continue
        identifiant = str(identifiant)
        if types is not None and str(activite.get("type") or "") not in types:
            rapport.autres_sports += 1
            continue
        meta = metadonnees(activite, equipements)
        if cache.contient(source="intervals", id_externe=identifiant):
            rapport.ignorees += 1
            if rafraichir_meta and cache.mettre_a_jour_meta(
                source="intervals",
                id_externe=identifiant,
                meta=meta,
                equipement=meta.get("equipement"),
            ):
                rapport.mises_a_jour += 1
            continue
        try:
            contenu, extension = client.telecharger_fichier(identifiant)
            cache.ajouter(
                contenu,
                source="intervals",
                id_externe=identifiant,
                extension=extension,
                meta=meta,
            )
        except (ErreurConnecteur, ErreurLecture) as e:
            rapport.echecs += 1
            rapport.messages.append(f"{identifiant} : {e}")
            continue
        rapport.ajoutees += 1
    return rapport
