"""Connecteur BRouter : un itinéraire A→B, ou une boucle autour d'un point.

BRouter est auto-hébergé (Coolify) derrière une authentification basique. **Le
mot de passe n'apparaît jamais dans un message d'erreur, un log ni un
`repr`** : il ne vit que dans l'objet `httpx.BasicAuth`, jamais en attribut.
L'URL, elle, peut s'afficher : c'est une adresse de serveur, pas un secret.

Le client HTTP est injectable pour que les tests n'appellent jamais le réseau.

Format de réponse (relevé sur le serveur réel, profil `fastbike`) :
`features[0].geometry.coordinates` = `[lon, lat, alt]` en degrés ;
`properties` porte `track-length` (m), `total-time` (s), `filtered ascend`
(m) et `messages`, dont la première ligne est l'en-tête et chaque ligne
suivante décrit le tronçon **se terminant** au point cité. La colonne
`CostPerKm` de ces messages est retenue dans `Segment.cout_km` : c'est le
jugement du moteur lui-même sur le trafic du tronçon. La colonne `NodeTags`
va dans `Segment.node_tags` : ce sont les tags du **nœud de fin** du tronçon
(`highway=traffic_signals`, `highway=crossing`…), d'où `seance.terrain` tire
les feux et les stops sous un bloc. Les coordonnées
des messages sont des **microdegrés entiers passés en chaînes** (mesuré :
rapport message/géométrie = 1 000 000) et retombent **exactement** sur un
point de la géométrie (117/117 puis 802/802 sur deux réponses réelles).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any

import httpx

from ourouler.noyau.erreurs import ErreurConnecteur
from ourouler.noyau.profil import Evitement, ParametresBrouter
from ourouler.noyau.trace import DENIVELE_MOTEUR, PointTrace, Segment, Trace, distance_m

CHEMIN_ITINERAIRE = "/brouter"

#: `engineMode` est un **entier** : 4 = boucle (« round trip »).
MODE_BOUCLE = 4

#: Colonnes d'un message, dans l'ordre du serveur. Sert de repli quand la
#: réponse ne porte pas sa ligne d'en-tête.
COLONNES_MESSAGE = (
    "Longitude",
    "Latitude",
    "Elevation",
    "Distance",
    "CostPerKm",
    "ElevCost",
    "TurnCost",
    "NodeCost",
    "InitialCost",
    "WayTags",
    "NodeTags",
    "Time",
    "Energy",
)

#: Au-delà de cette médiane, les coordonnées des messages sont en microdegrés
#: (une latitude vaut au plus 90, une longitude au plus 180). Le seuil se
#: compare à la **médiane de toute la réponse**, jamais à une valeur isolée :
#: voir `_facteur_coordonnees`.
SEUIL_MICRODEGRES = 1000.0

#: Facteur appliqué à une coordonnée de message selon son unité.
DEGRES, MICRODEGRES = 1.0, 1e-6

#: Paramètres de profil qui demandent au moteur de recaler lui-même les points
#: de passage tombés à côté de la route — la cause des crochets en mode boucle,
#: où c'est le moteur qui place ces points.
#:
#: **Deux pièges, et chacun fait croire que le mécanisme ne fait rien.**
#:
#: 1. Le nom. BRouter attend le camelCase `correctMisplacedViaPoints` et
#:    `correctMisplacedViaPointsDistance` (PR abrensch/brouter#759, livrée en
#:    1.7.8) ; le snake_case `profile:correct_misplaced_via_points…` est un
#:    paramètre inconnu, silencieusement jeté par le serveur — d'où une
#:    réponse identique avec ou sans lui.
#: 2. Le seuil. À 40 m, il ne déclenche jamais rien : mesuré sur un serveur
#:    réel, 8 azimuts × 2 rayons
#:    (8 km et 20 km), la réponse à seuil 40 est identique à celle sans
#:    correction. Le seuil doit descendre à **0** (« pas de vérification de
#:    distance », dit la PR elle-même) pour que le recalage agisse : au
#:    rayon 20 km, 0 antenne sur 8 boucles contre 5 270 m médians aux seuils
#:    40-200 ; au rayon 8 km, le nombre d'antennes baisse aux seuils
#:    croissants (2 827 m médians à 40-200, 321 m à 1000) mais **ne tombe pas
#:    à zéro même à seuil 0** (283 m médians, 4 boucles sur 7 encore
#:    porteuses d'une antenne). **Pourquoi, on ne le sait pas** : ce peut être
#: de vrais culs-de-sac du réseau routier à ce rayon, qu'aucun réglage ne recale
#: ; ce peut être aussi que le moteur
#:    renonce, `snapPathConnection` bornant sa remontée à `MAX_STEPS_CHECK`
#:    nœuds et abandonnant sur plusieurs conditions sans rapport avec la
#:    voirie. Les deux explications sont ouvertes, aucune n'est départagée.
#:    0 reste le meilleur réglage
#:    mesuré (jamais pire, souvent strictement mieux qu'un seuil plus grand),
#:    mais **ne garantit pas** l'absence d'antenne : `boucle/antennes.py`
#:    reste nécessaire en filet, voir son docstring de module.
#: **Ce que ce mécanisme fait, et qu'il faut lire avant de toucher au seuil**
#: (la source de BRouter le dit, sa documentation non) : il ne **déplace** aucun point de passage et ne
#: recolle rien sur la route la plus proche. `snapPathConnection` remonte le
#: tracé déjà calculé, repère les nœuds parcourus deux fois — à l'aller puis
#: au retour — et **les retire du tracé**. Le seuil n'est donc pas un rayon
#: d'accrochage : c'est la **longueur maximale d'aller-retour** qu'on
#: s'autorise à couper. À 0, aucune limite. Le cercle des points de passage
#: est identique dans tous les cas, et l'azimut demandé ne peut pas dériver.
CORRECTION_POINTS_DE_PASSAGE: dict[str, Any] = {
    "profile:correctMisplacedViaPoints": 1,
    "profile:correctMisplacedViaPointsDistance": 0,
}


class ClientBrouter:
    """Accès à un serveur BRouter. `http` est injectable : les tests ne sortent jamais."""

    def __init__(
        self,
        params: ParametresBrouter,
        http: httpx.Client | None = None,
        *,
        evitements: Sequence[Evitement] = (),
    ):
        if not params.url:
            raise ErreurConnecteur(
                "BRouter : [brouter] url est vide — renseigner l'adresse du serveur dans la configuration"
            )
        self.base_url = params.url.rstrip("/")
        self.profil_defaut = params.profil or "fastbike"
        self.timeout_s = params.timeout_s
        self._http = http if http is not None else httpx.Client(timeout=params.timeout_s)
        # Le mot de passe n'est **pas** conservé en attribut : il ne vit que
        # dans l'objet d'authentification, passé à chaque requête. Un client
        # injecté par un test n'est jamais modifié.
        self._auth = httpx.BasicAuth(params.utilisateur, params.mot_de_passe) if params.utilisateur else None
        # Les zones à éviter viennent de `Config.evitements` et sont passées
        # par l'appelant : ce module ne lit aucune configuration.
        self.nogos = _nogos(evitements)

    def __repr__(self) -> str:  # ni mot de passe, ni utilisateur dans une trace
        return f"ClientBrouter(base_url={self.base_url!r}, profil={self.profil_defaut!r})"

    @property
    def url_itineraire(self) -> str:
        """L'URL sans paramètres — la seule qu'on cite dans un message d'erreur."""
        return f"{self.base_url}{CHEMIN_ITINERAIRE}"

    # --- endpoints ------------------------------------------------------------

    def itineraire(self, points: Sequence[tuple[float, float]], *, profil: str | None = None) -> Trace:
        """Itinéraire passant par `points`, donnés en (lat, lon) — au moins deux."""
        if len(points) < 2:
            raise ErreurConnecteur(
                f"BRouter : un itinéraire demande au moins deux points, {len(points)} reçu(s)"
            )
        profil = profil or self.profil_defaut
        charge = self._appeler(
            self._avec_nogos(
                {
                    "lonlats": "|".join(_lonlat(lat, lon) for lat, lon in points),
                    "profile": profil,
                    "alternativeidx": 0,
                    "format": "geojson",
                }
            ),
            profil,
        )
        return _trace(charge, nom=f"Itinéraire {profil}", profil=profil, url=self.url_itineraire)

    def boucle(
        self,
        depart: tuple[float, float],
        *,
        azimut_deg: float,
        rayon_m: float,
        nb_points: int = 5,
        ecart_deg: int | None = None,
        profil: str | None = None,
    ) -> Trace:
        """Boucle partant de `depart` (lat, lon) dans la direction `azimut_deg`.

        `rayon_m` est le paramètre `roundTripDistance` du moteur, **pas** la
        longueur de la boucle : mesuré sur le serveur réel, la boucle obtenue
        vaut environ cinq fois ce rayon. C'est `boucle.candidates` qui ajuste.

        `CORRECTION_POINTS_DE_PASSAGE` est joint à la demande, avec le nom
        camelCase et le seuil de distance que le serveur honore réellement —
        voir la constante. Il réduit les antennes mais ne les garantit pas
        nulles : `boucle/antennes.py` reste le filet.
        """
        if rayon_m <= 0:
            raise ErreurConnecteur(f"BRouter : rayon de boucle de {rayon_m} m, un rayon positif attendu")
        if nb_points < 1:
            raise ErreurConnecteur(f"BRouter : {nb_points} point(s) de boucle, au moins 1 attendu")
        profil = profil or self.profil_defaut
        azimut = azimut_deg % 360
        params: dict[str, Any] = {
            "engineMode": MODE_BOUCLE,
            "lonlats": _lonlat(*depart),
            "roundTripStartDirection": round(azimut),
            "roundTripDistance": round(rayon_m),
            "roundTripPoints": int(nb_points),
            "profile": profil,
            "alternativeidx": 0,
            "format": "geojson",
            **CORRECTION_POINTS_DE_PASSAGE,
        }
        if ecart_deg is not None:
            params["roundTripDirectionAdd"] = int(ecart_deg)
        charge = self._appeler(self._avec_nogos(params), profil)
        trace = _trace(
            charge,
            nom=f"Boucle {azimut:.0f}° {rayon_m / 1000:.1f} km",
            profil=profil,
            url=self.url_itineraire,
        )
        trace.meta["azimut_deg"] = azimut
        trace.meta["rayon_m"] = float(rayon_m)
        return trace

    # --- interne --------------------------------------------------------------

    def _avec_nogos(self, params: dict[str, Any]) -> dict[str, Any]:
        """Ajoute `nogos` aux paramètres s'il y a des zones à éviter.

        Le paramètre est **omis** quand la liste est vide plutôt qu'envoyé
        vide : un `nogos=` nu n'a pas de sens pour le moteur, et une URL sans
        le paramètre est celle qu'on sait déjà juste.
        """
        if not self.nogos:
            return params
        return {**params, "nogos": self.nogos}

    def _appeler(self, params: dict[str, Any], profil: str) -> Any:
        """Un GET authentifié. Les messages ne citent que l'URL nue et le code HTTP."""
        try:
            reponse = self._http.get(self.url_itineraire, params=params, auth=self._auth)
        except httpx.HTTPError as e:
            raise ErreurConnecteur(
                f"BRouter injoignable sur {self.url_itineraire} ({type(e).__name__})"
            ) from e
        if reponse.status_code >= 400:
            raise ErreurConnecteur(
                f"BRouter : HTTP {reponse.status_code} sur {self.url_itineraire}{_indice(reponse, profil)}"
            )
        if not reponse.content:
            raise ErreurConnecteur(f"BRouter : réponse vide sur {self.url_itineraire}")
        try:
            return reponse.json()
        except ValueError as e:
            raise ErreurConnecteur(f"BRouter : réponse non-JSON sur {self.url_itineraire} ({e})") from e


#: Nombre de caractères du corps d'erreur cités dans un message. Assez pour
#: « datafile W5_N40.rd5 not found », trop peu pour noyer la sortie.
CORPS_ERREUR_MAX = 120


def _indice(reponse: httpx.Response, profil: str) -> str:
    """Ce qu'on peut dire du code HTTP. Ne cite jamais les identifiants envoyés."""
    code = reponse.status_code
    if code in (401, 403):
        return " — identifiants refusés, vérifier [brouter] utilisateur et mot_de_passe"
    if code == 404:
        return " — adresse inconnue, vérifier [brouter] url"
    if code >= 500 and not reponse.content:
        # Mesuré sur le serveur réel : un profil absent donne un 500 **sans
        # corps**, sans autre indice. C'est de très loin la cause la plus
        # fréquente, on la nomme plutôt que de laisser un « HTTP 500 » nu.
        return f" sans corps — profil inconnu ? ({profil})"
    if code >= 500:
        return " — panne côté serveur BRouter, réessayer plus tard"
    # Sur un 400, le moteur dit **pourquoi** en clair : « datafile W5_N40.rd5
    # not found » (région absente du serveur), « target island detected for
    # section 3 » (aucun itinéraire possible). Sans ce mot, un rejeu de 156
    # sorties rendait 156 fois « HTTP 400 » et rien d'exploitable.
    return _corps(reponse)


def _corps(reponse: httpx.Response) -> str:
    """Le message du moteur, sur une ligne et borné. Vide si illisible ou absent."""
    try:
        texte = reponse.text
    except (UnicodeDecodeError, ValueError):  # pragma: no cover - corps binaire
        return ""
    texte = " ".join(texte.split())
    if not texte:
        return ""
    if len(texte) > CORPS_ERREUR_MAX:
        texte = texte[:CORPS_ERREUR_MAX] + "…"
    return f" — {texte}"


def _lonlat(lat: float, lon: float) -> str:
    """BRouter attend `lon,lat` ; le reste du projet manipule des (lat, lon)."""
    return f"{lon:.6f},{lat:.6f}"


def _nogos(evitements: Sequence[Evitement]) -> str:
    """`lon,lat,rayon|lon,lat,rayon…` — les zones que le moteur doit contourner.

    Même convention que `lonlats` : BRouter attend `lon,lat`, le rayon en
    mètres entiers. Une zone au rayon absurde (négatif, nul, non fini) est
    écartée : demander au moteur d'éviter un disque de rayon négatif ne veut
    rien dire, et un `nogos` illisible fait échouer **tout** l'itinéraire.
    """
    morceaux = []
    for e in evitements:
        rayon = float(e.rayon_m)
        if not math.isfinite(rayon) or rayon <= 0:
            continue
        morceaux.append(f"{_lonlat(e.latitude, e.longitude)},{round(rayon)}")
    return "|".join(morceaux)


# --- lecture du GeoJSON -------------------------------------------------------


def _trace(charge: Any, *, nom: str, profil: str, url: str) -> Trace:
    """Construit un `Trace` depuis la réponse GeoJSON de BRouter."""
    if not isinstance(charge, dict):
        raise ErreurConnecteur(f"BRouter : JSON inattendu ({type(charge).__name__}) sur {url}")
    entites = charge.get("features")
    if not isinstance(entites, list) or not entites:
        raise ErreurConnecteur(
            f"BRouter : réponse sans « features » exploitable sur {url} (aucun itinéraire trouvé ?)"
        )
    entite = entites[0]
    if not isinstance(entite, dict):
        raise ErreurConnecteur(f"BRouter : « features[0] » inattendu ({type(entite).__name__}) sur {url}")

    points = _points(entite.get("geometry"), url)
    proprietes = entite.get("properties") if isinstance(entite.get("properties"), dict) else {}

    ignores: list[str] = []
    segments = _segments(points, proprietes.get("messages"), ignores)
    cumul = points[-1].dist_m
    distance = _nombre(proprietes.get("track-length"))
    denivele = _nombre(proprietes.get("filtered ascend"))
    meta: dict = {
        "moteur": "brouter",
        "profil": profil,
        "nom_moteur": str(proprietes.get("name") or ""),
        "cout": _nombre(proprietes.get("cost")),
        "distance_cumulee_m": round(cumul, 1),
        "messages_ignores": len(ignores),
        # Le D+ vient du « filtered ascend » du moteur, pas d'un recalcul sur
        # les altitudes : les deux divergent, et la colonne doit le dire.
        "denivele_source": DENIVELE_MOTEUR if denivele is not None else None,
    }
    if ignores:
        # Une ligne de message illisible ne doit pas faire perdre tout
        # l'itinéraire, mais elle ne doit pas non plus disparaître en silence.
        meta["messages_ignores_motifs"] = sorted(set(ignores))[:5]
    return Trace(
        nom=nom,
        points=points,
        segments=segments,
        distance_m=distance if distance is not None else cumul,
        denivele_m=denivele,
        temps_moteur_s=_nombre(proprietes.get("total-time")),
        meta=meta,
    )


def _points(geometrie: Any, url: str) -> list[PointTrace]:
    """Les points du `LineString`, avec leur distance cumulée (haversine)."""
    if not isinstance(geometrie, dict):
        raise ErreurConnecteur(f"BRouter : « geometry » absente ou inattendue sur {url}")
    brut = geometrie.get("coordinates")
    if not isinstance(brut, list) or len(brut) < 2:
        raise ErreurConnecteur(
            f"BRouter : géométrie de {len(brut) if isinstance(brut, list) else 0} point(s) sur {url}, "
            "au moins 2 attendus"
        )
    points: list[PointTrace] = []
    cumul = 0.0
    for i, coordonnee in enumerate(brut):
        if not isinstance(coordonnee, (list, tuple)) or len(coordonnee) < 2:
            raise ErreurConnecteur(f"BRouter : coordonnée n° {i} illisible sur {url}")
        try:
            lon, lat = float(coordonnee[0]), float(coordonnee[1])
            alt = float(coordonnee[2]) if len(coordonnee) > 2 and coordonnee[2] is not None else None
        except (TypeError, ValueError) as e:
            raise ErreurConnecteur(f"BRouter : coordonnée n° {i} non numérique sur {url}") from e
        point = PointTrace(lat=lat, lon=lon, alt_m=alt, dist_m=cumul)
        if points:
            cumul += distance_m(points[-1], point)
            point = PointTrace(lat=lat, lon=lon, alt_m=alt, dist_m=cumul)
        points.append(point)
    return points


def _segments(points: list[PointTrace], messages: Any, ignores: list[str]) -> list[Segment]:
    """Un `Segment` par ligne de message, rattachée au point où le tronçon finit.

    Le rattachement se fait **en avançant** : le dernier message d'une boucle
    cite le point de départ, qui est aussi le point d'arrivée — une recherche
    par valeur seule le renverrait à l'indice 0 et inverserait le tronçon.
    """
    if not isinstance(messages, list) or len(messages) < 2:
        return []
    colonnes, lignes = _colonnes(messages)
    facteur = _facteur_coordonnees(points, lignes, colonnes)
    index = _index_des_points(points)
    segments: list[Segment] = []
    curseur = 0
    for numero, ligne in enumerate(lignes):
        if curseur >= len(points) - 1:
            # Plus de point où accrocher un tronçon : le serveur a envoyé plus
            # de messages que la géométrie ne porte de points. Les lignes
            # restantes sont perdues, et ça se compte — sinon
            # `meta["messages_ignores"]` annoncerait 0 alors que des tronçons
            # ont disparu, le contraire de l'intention.
            ignores.extend(
                f"ligne {reste} : plus de point où s'accrocher" for reste in range(numero, len(lignes))
            )
            break
        if not isinstance(ligne, (list, tuple)) or len(ligne) <= colonnes["Latitude"]:
            ignores.append(f"ligne {numero} trop courte")
            continue
        try:
            lat = _degres(ligne[colonnes["Latitude"]], facteur)
            lon = _degres(ligne[colonnes["Longitude"]], facteur)
        except (TypeError, ValueError):
            ignores.append(f"ligne {numero} : coordonnée illisible")
            continue
        fin = _point_suivant(points, index, lat, lon, curseur + 1)
        longueur = _nombre(_colonne(ligne, colonnes, "Distance"))
        if longueur is None:
            longueur = points[fin].dist_m - points[curseur].dist_m
        segments.append(
            Segment(
                debut_idx=curseur,
                fin_idx=fin,
                longueur_m=longueur,
                tags=_tags(_colonne(ligne, colonnes, "WayTags")),
                # `CostPerKm` est le jugement du moteur sur le tronçon : on le
                # garde tel quel, sans le convertir ni le moyenner ici. Une
                # colonne absente ou illisible donne `None`, jamais 0 — un
                # coût nul voudrait dire « route idéale », ce qui est le
                # contraire d'une mesure manquante (on n'affirme rien sans mesure).
                cout_km=_nombre(_colonne(ligne, colonnes, "CostPerKm")),
                # `NodeTags` décrit le **nœud de fin** du tronçon, celui que la
                # ligne cite : `highway=traffic_signals`, `highway=crossing`…
                # C'est la seule source de feux et de stops du projet ; la
                # colonne était lue et jetée jusqu'ici.
                node_tags=_tags(_colonne(ligne, colonnes, "NodeTags")),
            )
        )
        curseur = fin
    return segments


def _colonnes(messages: list) -> tuple[dict[str, int], list]:
    """(position de chaque colonne, lignes de données).

    La première ligne est normalement l'en-tête. Si elle n'en est pas une
    (serveur plus ancien, réponse tronquée), on retombe sur l'ordre connu des
    colonnes et **toutes** les lignes sont des données : perdre le premier
    tronçon serait pire que supposer un ordre qui n'a jamais changé.
    """
    defaut = {nom: i for i, nom in enumerate(COLONNES_MESSAGE)}
    entete = messages[0]
    if not isinstance(entete, (list, tuple)) or "Longitude" not in entete:
        return defaut, list(messages)
    positions = {str(nom): i for i, nom in enumerate(entete)}
    if "Latitude" not in positions:
        return defaut, list(messages[1:])
    return {**defaut, **positions}, list(messages[1:])


def _colonne(ligne: Any, colonnes: dict[str, int], nom: str) -> Any:
    i = colonnes.get(nom)
    if i is None or i >= len(ligne):
        return None
    return ligne[i]


def _index_des_points(points: list[PointTrace]) -> dict[tuple[int, int], list[int]]:
    """Les indices de chaque point, rangés par coordonnée arrondie au microdegré."""
    index: dict[tuple[int, int], list[int]] = {}
    for i, p in enumerate(points):
        index.setdefault(_cle(p.lat, p.lon), []).append(i)
    return index


def _cle(lat: float, lon: float) -> tuple[int, int]:
    return (round(lat * 1e6), round(lon * 1e6))


def _point_suivant(
    points: list[PointTrace], index: dict[tuple[int, int], list[int]], lat: float, lon: float, depuis: int
) -> int:
    """L'indice ≥ `depuis` du point cité par un message.

    Sur le serveur réel, la coordonnée d'un message retombe **exactement** sur
    un point de la géométrie ; le repli par distance sert aux réponses
    arrondies différemment, pour ne pas perdre le tronçon.
    """
    for i in index.get(_cle(lat, lon), ()):
        if i >= depuis:
            return i
    cible = PointTrace(lat=lat, lon=lon, alt_m=None, dist_m=0.0)
    return min(range(depuis, len(points)), key=lambda i: distance_m(points[i], cible))


def _facteur_coordonnees(points: list[PointTrace], lignes: list, colonnes: dict[str, int]) -> float:
    """L'unité des coordonnées des messages, décidée **une fois pour toute la réponse**.

    Deviner valeur par valeur était faux : une coordonnée à moins de 0,001°
    d'un axe vaut moins de 1 000 microdegrés, et « 570 » (0,00057°) était lu
    comme 570 degrés. Le tronçon partait alors s'accrocher au point le plus
    proche d'une latitude impossible — c'est-à-dire n'importe lequel, en
    silence, et `km_trafic` devenait faux. La bande d'ambiguïté fait ±111 m
    autour de l'équateur **et du méridien de Greenwich**, et toutes les
    fixtures du dépôt y vivent (anonymisation).

    Deux critères, dans cet ordre :

    1. médiane des |valeurs| au-dessus de `SEUIL_MICRODEGRES` : des
       microdegrés, sans discussion (le cas de tous les serveurs mesurés) ;
    2. sinon, la médiane seule ne tranche pas — on compare à la géométrie,
       qui est toujours en degrés, et on retient le facteur qui rapproche le
       plus les deux.

    Sans aucune valeur lisible, on retient les microdegrés : c'est ce que
    rendent les serveurs mesurés, et aucune coordonnée ne sera convertie de
    toute façon.
    """
    valeurs = []
    for ligne in lignes:
        if not isinstance(ligne, (list, tuple)):
            continue
        for nom in ("Latitude", "Longitude"):
            brut = _colonne(ligne, colonnes, nom)
            try:
                valeurs.append(abs(float(brut)))
            except (TypeError, ValueError):
                continue
    if not valeurs:
        return MICRODEGRES
    mediane = _mediane(valeurs)
    if mediane > SEUIL_MICRODEGRES:
        return MICRODEGRES
    reference = _mediane([abs(p.lat) for p in points] + [abs(p.lon) for p in points])
    ecart_micro = abs(mediane * MICRODEGRES - reference)
    ecart_degres = abs(mediane * DEGRES - reference)
    return MICRODEGRES if ecart_micro < ecart_degres else DEGRES


def _mediane(valeurs: list[float]) -> float:
    ordonnees = sorted(valeurs)
    milieu = len(ordonnees) // 2
    if len(ordonnees) % 2:
        return ordonnees[milieu]
    return (ordonnees[milieu - 1] + ordonnees[milieu]) / 2.0


def _degres(brut: Any, facteur: float) -> float:
    """Une coordonnée de message en degrés, avec le facteur décidé pour la réponse.

    Mesuré sur le serveur réel : des **microdegrés entiers passés en chaînes**
    (« 4811234 »). L'unité n'est jamais devinée ici : `_facteur_coordonnees`
    l'a tranchée pour toutes les lignes à la fois.
    """
    return float(brut) * facteur


def _tags(brut: Any) -> dict[str, str]:
    """`"highway=tertiary surface=asphalt"` → `{"highway": "tertiary", "surface": "asphalt"}`."""
    if not isinstance(brut, str):
        return {}
    tags: dict[str, str] = {}
    for morceau in brut.split():
        cle, separateur, valeur = morceau.partition("=")
        if separateur and cle:
            tags[cle] = valeur
    return tags


def _nombre(brut: Any) -> float | None:
    """Une propriété numérique de BRouter (donnée en chaîne), ou None si absente."""
    if brut is None or isinstance(brut, bool):
        return None
    try:
        valeur = float(brut)
    except (TypeError, ValueError):
        return None
    return valeur if valeur == valeur and abs(valeur) != float("inf") else None
