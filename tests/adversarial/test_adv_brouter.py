"""L2.1 — connecteur BRouter, mis à l'épreuve.

Cible : contrat du sprint 2 §1 et §8. Le serveur réel n'est jamais appelé :
tout passe par `httpx.MockTransport` et des réponses **fabriquées**
(`fabriques.geojson_brouter`), la fixture `reseau_interdit` garantissant
qu'aucune socket ne s'ouvre.

Deux fils rouges :

* **le mot de passe ne sort jamais** — ni dans `repr`, ni dans une erreur, ni
  dans l'URL appelée ;
* **aucune trace aberrante** — le contrat laisse ouverte la question des
  coordonnées des `messages` (microdegrés entiers ou degrés). Les deux formes
  sont testées : le lecteur a le droit de refuser celle qu'il ne gère pas
  (`ErreurConnecteur`), il n'a pas le droit de rendre une trace de
  10 000 kilomètres.
"""

from __future__ import annotations

import traceback
from typing import Any

import fabriques
import httpx
import pytest
from fabriques import EspionHttp, geojson_brouter
from outils import robuste

from ourouler.config import ParametresBrouter
from ourouler.connecteurs import brouter as module_brouter
from ourouler.noyau.erreurs import ErreurConnecteur, ErreurUtilisateur

#: Un départ et une arrivée volontairement dissymétriques : si le connecteur
#: inverse `lat` et `lon`, l'URL le dit tout de suite.
DEPART = (0.0011, 0.0022)
ARRIVEE = (0.0033, 0.0044)

TAGS_DISTINCTS = [
    {"highway": "tertiary", "surface": "asphalt"},
    {"highway": "residential"},
    {"highway": "primary"},
    {"highway": "track", "surface": "gravel"},
]


def _params(**surcharges) -> ParametresBrouter:
    valeurs: dict[str, Any] = {
        "url": fabriques.URL_BROUTER,
        "utilisateur": fabriques.UTILISATEUR_BIDON,
        "mot_de_passe": fabriques.MOT_DE_PASSE_BIDON,
        "profil": "fastbike",
        "timeout_s": 5.0,
    }
    valeurs.update(surcharges)
    return ParametresBrouter(**valeurs)


def _client(module, reponse, **surcharges):
    espion = EspionHttp(reponse)
    client = module.ClientBrouter(_params(**surcharges), http=espion.client())
    return client, espion


def _reponse(coords, **kwargs) -> httpx.Response:
    return httpx.Response(200, json=geojson_brouter(coords, **kwargs))


def _verifier_sans_mot_de_passe(objet: Any, quoi: str) -> None:
    """Le mot de passe ne doit apparaître dans aucun texte rendu par le connecteur."""
    textes: list[str] = []
    if isinstance(objet, BaseException):
        vu: set[int] = set()
        courante: BaseException | None = objet
        while courante is not None and id(courante) not in vu:
            vu.add(id(courante))
            textes += [str(courante), repr(courante)]
            textes += traceback.format_exception_only(type(courante), courante)
            courante = courante.__cause__ or courante.__context__
    else:
        textes += [str(objet), repr(objet)]
    for texte in textes:
        assert fabriques.MOT_DE_PASSE_BIDON not in texte, (
            f"{quoi} : le mot de passe BRouter fuit dans « {texte[:200]} »"
        )


def _verifier_urls_sans_secret(espion: EspionHttp) -> None:
    for requete in espion.requetes:
        assert fabriques.MOT_DE_PASSE_BIDON not in str(requete.url), (
            "le mot de passe ne doit pas voyager dans l'URL (auth basique en en-tête)"
        )


# --- cas nominal : ce que le contrat promet ---------------------------------


def test_itineraire_lit_la_reponse_fabriquee():
    module = module_brouter
    coords = fabriques.ligne(5, pas_m=400.0, cap_deg=90.0)
    client, espion = _client(module, _reponse(coords, tags=TAGS_DISTINCTS))
    trace = client.itineraire([DEPART, ARRIVEE])

    fabriques.verifier_trace(trace, quoi="itineraire", distance_max_km=50.0)
    assert len(trace.points) == len(coords), "un point de géométrie = un PointTrace"
    assert trace.distance_m > 0, "track-length doit alimenter distance_m"
    assert trace.temps_moteur_s is not None, "total-time est informatif mais présent"
    assert trace.denivele_m is not None, "« filtered ascend » alimente le dénivelé"
    _verifier_urls_sans_secret(espion)


def test_les_points_partent_en_lon_lat():
    """Contrat §1 : (lat, lon) côté Python, `lon,lat` côté BRouter."""
    module = module_brouter
    client, espion = _client(module, _reponse(fabriques.ligne(3)))
    client.itineraire([DEPART, ARRIVEE])

    params = espion.params()
    assert "lonlats" in params, f"paramètre `lonlats` attendu, reçu {sorted(params)}"
    paires = [p.split(",") for p in params["lonlats"].split("|")]
    assert len(paires) == 2, f"deux paires attendues, reçu {params['lonlats']!r}"
    premier = [float(x) for x in paires[0]]
    assert premier[0] == pytest.approx(DEPART[1], abs=1e-6), (
        f"lonlats commence par {premier[0]} : la longitude était attendue en premier "
        f"(départ passé en (lat={DEPART[0]}, lon={DEPART[1]}))"
    )
    assert premier[1] == pytest.approx(DEPART[0], abs=1e-6)
    assert params.get("format") == "geojson", "le contrat demande format=geojson"
    assert params.get("profile") == "fastbike"


def test_boucle_envoie_les_parametres_du_mode_4():
    module = module_brouter
    coords = fabriques.cercle(12, rayon_m=800.0)
    client, espion = _client(module, _reponse(coords))
    trace = client.boucle(DEPART, azimut_deg=45.0, rayon_m=8000.0, nb_points=5)

    params = espion.params()
    assert params.get("engineMode") == "4", (
        f"engineMode doit valoir l'entier 4, reçu {params.get('engineMode')!r} "
        "(« 4.0 » ou « true » ne sont pas acceptés par BRouter)"
    )
    assert params.get("roundTripDistance") == "8000", (
        f"roundTripDistance attendu à 8000, reçu {params.get('roundTripDistance')!r}"
    )
    assert params.get("roundTripStartDirection") == "45", (
        f"roundTripStartDirection attendu à 45, reçu {params.get('roundTripStartDirection')!r}"
    )
    assert params.get("roundTripPoints") == "5"
    assert "|" not in params.get("lonlats", ""), "une boucle ne part que d'un point"
    fabriques.verifier_trace(trace, quoi="boucle", distance_max_km=50.0)
    assert trace.bornee(), "un cercle fermé doit être borné"


def test_le_profil_passe_en_argument_prime_sur_la_configuration():
    module = module_brouter
    client, espion = _client(module, _reponse(fabriques.ligne(3)), profil="fastbike")
    client.itineraire([DEPART, ARRIVEE], profil="gravel")
    assert espion.params().get("profile") == "gravel"


def test_l_url_configuree_est_respectee():
    """`url` est une base : le chemin `/brouter` s'y ajoute, sans doublon de `/`."""
    module = module_brouter
    client, espion = _client(module, _reponse(fabriques.ligne(3)))
    client.itineraire([DEPART, ARRIVEE])
    url = espion.requetes[0].url
    assert str(url).startswith(fabriques.URL_BROUTER), f"appel parti sur {url}"
    assert "//brouter" not in url.path, f"chemin mal recollé : {url.path}"


# --- microdegrés ou degrés : le contrat ne tranche pas ----------------------


@pytest.mark.parametrize("microdegres", [True, False])
def test_les_messages_en_microdegres_ou_en_degres_ne_donnent_jamais_une_trace_aberrante(microdegres):
    """Contrat §1 : « en microdegrés entiers (à vérifier sur la réponse : sinon en degrés) ».

    Les deux issues cohérentes sont acceptées — segments correctement rattachés,
    ou `ErreurConnecteur` qui dit l'unité inattendue. Ce qui est refusé, c'est
    une trace de plusieurs milliers de kilomètres ou des segments rattachés
    n'importe où : c'est exactement ce que produit une confusion d'unité.
    """
    module = module_brouter
    coords = fabriques.ligne(5, pas_m=500.0, cap_deg=45.0)
    client, _ = _client(
        module, _reponse(coords, tags=TAGS_DISTINCTS, microdegres=microdegres)
    )
    trace, erreur = robuste(
        lambda: client.itineraire([DEPART, ARRIVEE]),
        quoi=f"itineraire(messages en {'microdegrés' if microdegres else 'degrés'})",
        erreurs_acceptees=(ErreurUtilisateur,),
    )
    if erreur is not None:
        assert str(erreur).strip(), "une ErreurConnecteur doit expliquer ce qui cloche"
        return

    fabriques.verifier_trace(trace, quoi="itineraire", distance_max_km=50.0)
    if not trace.segments:
        return  # lecture dégradée assumée : pas de segments, pas de mensonge
    routes = [s.tags.get("highway") for s in trace.segments]
    attendues = [t["highway"] for t in TAGS_DISTINCTS]
    assert routes == attendues, (
        f"tronçons rattachés dans le désordre : {routes} au lieu de {attendues} — "
        "chaque message décrit le tronçon se terminant au point cité"
    )
    couverture = sum(s.longueur_m for s in trace.segments)
    assert couverture <= trace.distance_m * 1.5 + 1.0, (
        f"les segments couvrent {couverture:.0f} m pour une trace de {trace.distance_m:.0f} m"
    )


@pytest.mark.parametrize("microdegres", [True, False])
def test_chaque_troncon_est_rattache_au_point_qui_le_termine(microdegres):
    """La géométrie est bien plus dense que les messages : compter les lignes ne suffit pas.

    Contrat §1 : « rattacher chaque message au point de la géométrie le plus
    proche ». Ici un message tous les trois points : une implémentation qui
    consomme les points dans l'ordre, un par message, découpe les trois
    premiers tronçons et abandonne les deux tiers du tracé.
    """
    module = module_brouter
    coords = fabriques.ligne(10, pas_m=300.0, cap_deg=60.0)
    client, _ = _client(
        module,
        _reponse(coords, tags=TAGS_DISTINCTS[:3], pas_messages=3, microdegres=microdegres),
    )
    trace, erreur = robuste(
        lambda: client.itineraire([DEPART, ARRIVEE]),
        quoi="itineraire(un message tous les trois points)",
        erreurs_acceptees=(ErreurUtilisateur,),
    )
    if erreur is not None or not trace.segments:
        return

    fabriques.verifier_trace(trace, quoi="messages espacés", distance_max_km=50.0)
    assert [s.tags.get("highway") for s in trace.segments] == [
        t["highway"] for t in TAGS_DISTINCTS[:3]
    ], "tronçons rattachés dans le désordre"
    assert [s.fin_idx for s in trace.segments] == [3, 6, 9], (
        f"fins de tronçon aux indices {[s.fin_idx for s in trace.segments]} : les messages "
        "citent les points 3, 6 et 9 de la géométrie"
    )
    couverture = sum(s.longueur_m for s in trace.segments)
    assert couverture >= trace.distance_m * 0.9, (
        f"les segments ne couvrent que {couverture:.0f} m des {trace.distance_m:.0f} m du tracé"
    )


#: Un tracé entièrement dans la bande |coordonnée| ≤ 0,001°, à cheval sur
#: l'équateur **et** sur le méridien de Greenwich. C'est la seule zone où une
#: conversion microdegrés/degrés décidée valeur par valeur se trompe : 570
#: microdegrés valent 0,00057°, pas 570 degrés. Contrat §8, « le cap au
#: passage du méridien 0 » ; point 12 de la relecture du sprint 2.
BANDE_AMBIGUE = {"depart": (-0.0004, -0.0004), "pas_m": 20.0, "cap_deg": 45.0}


@pytest.mark.parametrize("microdegres", [True, False])
def test_la_bande_d_ambiguite_autour_des_axes_est_lue_dans_la_bonne_unite(microdegres):
    """Sous 0,001°, une coordonnée de message tient en moins de 1 000 microdegrés.

    Une règle « au-delà de 1 000, c'est des microdegrés » y voit donc des
    degrés, et le tronçon part s'accrocher au point le plus proche d'une
    latitude de 570° — c'est-à-dire n'importe lequel, en silence. Les tags,
    et donc `km_trafic`, deviennent faux sans le moindre message.
    """
    module = module_brouter
    coords = fabriques.ligne(9, **BANDE_AMBIGUE)
    assert all(abs(lat) <= 0.001 and abs(lon) <= 0.001 for lat, lon, _ in coords), (
        "le tracé de ce test doit rester dans la bande d'ambiguïté"
    )
    assert any(lat > 0 for lat, _, _ in coords) and any(lat < 0 for lat, _, _ in coords), (
        "et traverser l'équateur"
    )

    client, _ = _client(
        module, _reponse(coords, tags=TAGS_DISTINCTS, pas_messages=2, microdegres=microdegres)
    )
    trace, erreur = robuste(
        lambda: client.itineraire([DEPART, ARRIVEE]),
        quoi=f"itineraire(bande d'ambiguïté, {'microdegrés' if microdegres else 'degrés'})",
        erreurs_acceptees=(ErreurUtilisateur,),
    )
    if erreur is not None:
        assert str(erreur).strip(), "une ErreurConnecteur doit expliquer ce qui cloche"
        return

    fabriques.verifier_trace(trace, quoi="bande d'ambiguïté", distance_max_km=50.0)
    if not trace.segments:
        return  # lecture dégradée assumée : pas de segments, pas de mensonge
    assert [s.tags.get("highway") for s in trace.segments] == [
        t["highway"] for t in TAGS_DISTINCTS
    ], "tronçons rattachés dans le désordre : l'unité des coordonnées a été mal lue"
    assert [s.fin_idx for s in trace.segments] == [2, 4, 6, 8], (
        f"fins de tronçon aux indices {[s.fin_idx for s in trace.segments]}, attendu [2, 4, 6, 8]"
    )


def test_messages_absents_ne_font_pas_de_segments_imaginaires():
    module = module_brouter
    coords = fabriques.ligne(4, pas_m=300.0)
    client, _ = _client(module, _reponse(coords, messages=False))
    trace, erreur = robuste(
        lambda: client.itineraire([DEPART, ARRIVEE]),
        quoi="itineraire(sans messages)",
        erreurs_acceptees=(ErreurUtilisateur,),
    )
    if erreur is None:
        fabriques.verifier_trace(trace, quoi="itineraire sans messages", distance_max_km=50.0)
        assert trace.segments == [], "sans `messages`, il n'y a rien pour décrire les tronçons"


def test_messages_sans_entete_ne_produisent_pas_de_tags_fantaisistes():
    """Sans en-tête, la première ligne est une donnée : ne pas la lire comme des noms de colonnes."""
    module = module_brouter
    coords = fabriques.ligne(4, pas_m=300.0)
    client, _ = _client(module, _reponse(coords, tags=TAGS_DISTINCTS[:3], entete=False))
    trace, erreur = robuste(
        lambda: client.itineraire([DEPART, ARRIVEE]),
        quoi="itineraire(messages sans en-tête)",
        erreurs_acceptees=(ErreurUtilisateur,),
    )
    if erreur is None:
        fabriques.verifier_trace(trace, quoi="messages sans en-tête", distance_max_km=50.0)
        for segment in trace.segments:
            for cle in segment.tags:
                assert not cle.isdigit(), (
                    f"tag numérique {cle!r} : une ligne de données a été lue comme un en-tête"
                )


# --- réponses hostiles -------------------------------------------------------


@pytest.mark.parametrize(
    "reponse, quoi",
    [
        (httpx.Response(500, content=b""), "HTTP 500 sans corps (profil inconnu)"),
        (httpx.Response(500, text="Internal Server Error"), "HTTP 500 avec corps"),
        (httpx.Response(404, text="not found"), "HTTP 404"),
        (httpx.Response(401, text="unauthorized"), "HTTP 401"),
        (httpx.Response(200, content=b""), "corps vide"),
        (httpx.Response(200, content=b"<html>pas du json</html>"), "corps non-JSON"),
        (httpx.Response(200, json=[1, 2, 3]), "JSON inattendu (liste)"),
        (httpx.Response(200, json={"type": "FeatureCollection"}), "sans features"),
        (httpx.Response(200, json={"type": "FeatureCollection", "features": []}), "features vide"),
        (httpx.Response(200, json={"features": [{"properties": {}}]}), "feature sans géométrie"),
        (
            httpx.Response(200, json={"features": [{"geometry": {"coordinates": "n'importe quoi"}}]}),
            "coordinates qui n'est pas une liste",
        ),
    ],
)
def test_une_reponse_hostile_donne_une_erreur_utilisateur(reponse, quoi):
    module = module_brouter
    client, _ = _client(module, reponse)
    with pytest.raises(ErreurUtilisateur) as capture:
        client.itineraire([DEPART, ARRIVEE])
    assert isinstance(capture.value, ErreurConnecteur), (
        f"{quoi} : le contrat demande ErreurConnecteur, reçu {type(capture.value).__name__}"
    )
    assert str(capture.value).strip(), f"{quoi} : message d'erreur vide"
    _verifier_sans_mot_de_passe(capture.value, quoi)


def test_le_profil_inconnu_est_explique():
    """Contrat §1 : un profil absent du serveur donne un 500 sans corps — le dire."""
    module = module_brouter
    client, _ = _client(module, httpx.Response(500, content=b""), profil="fastbike-lowtraffic")
    with pytest.raises(ErreurUtilisateur) as capture:
        client.itineraire([DEPART, ARRIVEE])
    message = str(capture.value).casefold()
    assert "profil" in message or "profile" in message, (
        f"un 500 sans corps doit évoquer le profil, reçu : {capture.value}"
    )


@pytest.mark.parametrize(
    "erreur",
    [
        httpx.ConnectTimeout("délai dépassé"),
        httpx.ReadTimeout("délai dépassé"),
        httpx.ConnectError("connexion refusée"),
    ],
)
def test_un_echec_reseau_devient_une_erreur_utilisateur(erreur):
    module = module_brouter

    def _lever(_requete):
        raise erreur

    client, _ = _client(module, _lever)
    with pytest.raises(ErreurUtilisateur) as capture:
        client.itineraire([DEPART, ARRIVEE])
    _verifier_sans_mot_de_passe(capture.value, "timeout")


def test_geometrie_a_un_seul_point_ne_casse_rien():
    module = module_brouter
    client, _ = _client(module, _reponse(fabriques.ligne(1), tags=[], track_length=0.0))
    trace, erreur = robuste(
        lambda: client.itineraire([DEPART, ARRIVEE]),
        quoi="itineraire(un seul point)",
        erreurs_acceptees=(ErreurUtilisateur,),
    )
    if erreur is None:
        fabriques.verifier_trace(trace, quoi="un seul point", distance_max_km=1.0)
        assert not trace.bornee(), "un point isolé ne fait pas une boucle"


def test_distance_nulle_ne_provoque_pas_de_division_par_zero():
    module = module_brouter
    coords = [(fabriques.LAT0, fabriques.LON0, 10.0)] * 3
    client, _ = _client(module, _reponse(coords, track_length=0.0))
    trace, erreur = robuste(
        lambda: client.itineraire([DEPART, ARRIVEE]),
        quoi="itineraire(distance nulle)",
        erreurs_acceptees=(ErreurUtilisateur,),
    )
    if erreur is None:
        fabriques.verifier_trace(trace, quoi="distance nulle", distance_max_km=1.0)
        assert trace.distance_m == 0 or trace.distance_m > 0


def test_une_boucle_qui_ne_se_referme_pas_n_est_pas_maquillee():
    """Le tri des candidates (L2.3) repose sur `bornee()` : le connecteur ne doit pas mentir."""
    module = module_brouter
    coords = fabriques.ligne(6, pas_m=1000.0, cap_deg=90.0)
    client, _ = _client(module, _reponse(coords))
    trace, erreur = robuste(
        lambda: client.boucle(DEPART, azimut_deg=0.0, rayon_m=8000.0),
        quoi="boucle(non bornée)",
        erreurs_acceptees=(ErreurUtilisateur,),
    )
    if erreur is None:
        assert not trace.bornee(), (
            "la géométrie rendue ne revient pas au départ : `bornee()` doit valoir False"
        )


# --- le mot de passe ---------------------------------------------------------


def test_l_authentification_basique_part_bien_en_en_tete():
    module = module_brouter
    client, espion = _client(module, _reponse(fabriques.ligne(3)))
    client.itineraire([DEPART, ARRIVEE])
    entetes = espion.requetes[0].headers
    assert "authorization" in entetes, (
        "un utilisateur et un mot de passe sont configurés : l'auth basique doit partir"
    )
    assert entetes["authorization"].lower().startswith("basic ")
    _verifier_urls_sans_secret(espion)


def test_le_repr_du_client_ne_montre_pas_le_mot_de_passe():
    module = module_brouter
    client, _ = _client(module, _reponse(fabriques.ligne(3)))
    _verifier_sans_mot_de_passe(client, "ClientBrouter")
    _verifier_sans_mot_de_passe(client.params if hasattr(client, "params") else _params(), "params")


def test_sans_utilisateur_aucune_authentification_n_est_inventee():
    module = module_brouter
    client, espion = _client(
        module, _reponse(fabriques.ligne(3)), utilisateur="", mot_de_passe=""
    )
    client.itineraire([DEPART, ARRIVEE])
    entetes = espion.requetes[0].headers
    assert "authorization" not in entetes or not entetes["authorization"].strip(), (
        "sans identifiants, ne pas envoyer d'en-tête d'authentification vide"
    )


def test_aucune_requete_quand_les_points_manquent():
    """Zéro ou un point : une erreur utilisateur, pas un appel au serveur."""
    module = module_brouter
    client, espion = _client(module, _reponse(fabriques.ligne(3)))
    _, erreur = robuste(
        lambda: client.itineraire([]),
        quoi="itineraire([])",
        erreurs_acceptees=(ErreurUtilisateur,),
    )
    assert erreur is not None, "un itinéraire sans point n'a pas de sens"
    assert not espion.requetes, "aucun appel réseau ne doit partir pour une demande vide"
