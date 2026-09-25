"""Tests du connecteur Intervals.icu (L1.4).

Aucun test ne touche le réseau : `httpx` ne reçoit jamais autre chose qu'un
`MockTransport`. Toutes les réponses JSON sont fabriquées, avec des
identifiants et des valeurs inventés — jamais une réponse réelle.
"""

from __future__ import annotations

import base64
from datetime import date
from pathlib import Path

import httpx
import pytest

from ourouler.activites.cache import Cache
from ourouler.activites.modele import TYPES_VELO, est_sport_velo
from ourouler.connecteurs.intervals import (
    USER_AGENT,
    ClientIntervals,
    RapportSynchro,
    metadonnees,
    resoudre_athlete_id,
    synchroniser,
)
from ourouler.erreurs import ErreurConnecteur, ErreurUtilisateur

# Clé et identifiant d'athlète entièrement inventés pour les tests.
ATHLETE = "i000000"
CLE = "cle-de-test-inventee"

ACTIVITE_1 = {
    "id": "a111",
    "name": "Sortie inventee 1",
    "type": "Ride",
    "start_date_local": "2024-03-30T09:00:00",
    "device_name": "Appareil de test",
    "gear": {"id": "b000", "name": "Route"},
    "icu_average_watts": 205,
    "trainer": False,
    "power_meter": "CAPTEUR 0001",
    "power_meter_serial": "SN-0001",
}

#: Réponse de `GET /api/v1/athlete/{id}/gear` : noms entièrement inventés.
EQUIPEMENTS = [
    {"id": "b000", "name": "Route inventee", "type": "Bike", "retired": False},
    {"id": "b001", "name": "CLM inventee", "type": "Bike", "retired": False},
]

#: Une course à pied : l'API en renvoie, la synchronisation ne doit pas la prendre.
ACTIVITE_COURSE = {
    "id": "a333",
    "name": "Footing invente",
    "type": "Run",
    "start_date_local": "2024-03-31T18:00:00",
}
ACTIVITE_2 = {
    "id": "a222",
    "name": "Sortie inventee 2",
    "type": "VirtualRide",
    "start_date_local": "2024-04-02T08:00:00",
    "device_name": "Zwift",
    "gear": None,
    "trainer": True,
}


# --- outils -------------------------------------------------------------------


class Espion:
    """Transport bouchonné : enregistre les requêtes, rend des réponses fabriquées."""

    def __init__(self, reponses):
        self.reponses = reponses  # callable(requete) -> httpx.Response
        self.requetes: list[httpx.Request] = []

    def __call__(self, requete: httpx.Request) -> httpx.Response:
        self.requetes.append(requete)
        return self.reponses(requete)

    @property
    def chemins(self) -> list[str]:
        return [r.url.path for r in self.requetes]

    def fenetres(self, chemin_partiel: str) -> list[tuple[str, str]]:
        return [
            (r.url.params.get("oldest"), r.url.params.get("newest"))
            for r in self.requetes
            if chemin_partiel in r.url.path
        ]


def client(reponses, **kw) -> tuple[ClientIntervals, Espion]:
    espion = Espion(reponses)
    http = httpx.Client(transport=httpx.MockTransport(espion))
    return ClientIntervals(ATHLETE, CLE, http=http, **kw), espion


def json_fixe(charge, code: int = 200):
    def reponses(requete: httpx.Request) -> httpx.Response:
        return httpx.Response(code, json=charge)

    return reponses


# --- authentification et confidentialité de la clé ----------------------------


def test_auth_basique_api_key():
    c, espion = client(json_fixe([]))
    c.activites(date(2024, 3, 1), date(2024, 3, 31))
    entete = espion.requetes[0].headers["authorization"]
    attendu = base64.b64encode(f"API_KEY:{CLE}".encode()).decode()
    assert entete == f"Basic {attendu}"


def test_la_cle_n_apparait_ni_dans_le_repr_ni_dans_les_attributs_visibles():
    c, _ = client(json_fixe([]))
    assert CLE not in repr(c)
    assert CLE not in str(vars(c))


@pytest.mark.parametrize("code", [400, 401, 403, 404, 429, 500, 502, 503])
def test_la_cle_n_apparait_dans_aucun_message_d_erreur(code: int):
    c, _ = client(json_fixe({"message": "refuse"}, code=code))
    with pytest.raises(ErreurConnecteur) as e:
        c.activites(date(2024, 3, 1), date(2024, 3, 31))
    message = str(e.value)
    assert CLE not in message
    assert str(code) in message
    assert "activities" in message


def test_erreurs_http_sont_des_erreurs_utilisateur():
    assert issubclass(ErreurConnecteur, ErreurUtilisateur)


def test_401_et_500_sont_expliques():
    c, _ = client(json_fixe({}, code=401))
    with pytest.raises(ErreurConnecteur) as e:
        c.activites(date(2024, 3, 1))
    assert "clé d'API refusée" in str(e.value)

    c, _ = client(json_fixe({}, code=500))
    with pytest.raises(ErreurConnecteur) as e:
        c.activites(date(2024, 3, 1))
    assert "Intervals.icu" in str(e.value)


def test_client_refuse_une_configuration_vide():
    with pytest.raises(ErreurConnecteur):
        ClientIntervals("", "", http=httpx.Client(transport=httpx.MockTransport(json_fixe([]))))


def test_panne_reseau_devient_une_erreur_connecteur():
    def coupe(requete: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("injoignable", request=requete)

    c, _ = client(coupe)
    with pytest.raises(ErreurConnecteur) as e:
        c.activites(date(2024, 3, 1))
    assert "appel impossible" in str(e.value)
    assert CLE not in str(e.value)


# --- liste des activités ------------------------------------------------------


def test_activites_appelle_le_bon_endpoint():
    c, espion = client(json_fixe([ACTIVITE_1, ACTIVITE_2]))
    activites = c.activites(date(2024, 3, 1), date(2024, 4, 30))
    assert [a["id"] for a in activites] == ["a111", "a222"]
    # Deux mois civils demandés, donc deux appels au même endpoint, dédoublonnés.
    assert espion.chemins == [f"/api/v1/athlete/{ATHLETE}/activities"] * 2
    assert espion.fenetres("activities") == [
        ("2024-03-01", "2024-03-31"),
        ("2024-04-01", "2024-04-30"),
    ]


def test_activites_reponse_vide():
    c, _ = client(json_fixe([]))
    assert c.activites(date(2024, 3, 1), date(2024, 3, 31)) == []


def test_activites_reponse_null():
    """`null` n'est pas « aucune activité » : c'est une réponse inattendue.

    C'était traduit en liste vide. Un inventaire vide parce que le service a
    renvoyé `null` est indiscernable d'un inventaire vide parce qu'on n'a pas
    roulé — donc on refuse, en nommant l'endpoint.
    """

    def nul(requete: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"null", headers={"content-type": "application/json"})

    c, _ = client(nul)
    with pytest.raises(ErreurConnecteur) as e:
        c.activites(date(2024, 3, 1), date(2024, 3, 31))
    assert "activities" in str(e.value) and "tableau attendu" in str(e.value)


def test_activites_fenetre_a_l_envers_n_appelle_rien():
    c, espion = client(json_fixe([]))
    assert c.activites(date(2024, 4, 1), date(2024, 3, 1)) == []
    assert espion.requetes == []


def test_activites_type_inattendu():
    c, _ = client(json_fixe({"activities": []}))
    with pytest.raises(ErreurConnecteur) as e:
        c.activites(date(2024, 3, 1), date(2024, 3, 31))
    assert "tableau attendu" in str(e.value)


def test_activites_json_illisible():
    def texte(requete: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="ceci n'est pas du JSON")

    c, _ = client(texte)
    with pytest.raises(ErreurConnecteur) as e:
        c.activites(date(2024, 3, 1), date(2024, 3, 31))
    assert "JSON illisible" in str(e.value)


def test_activites_refuse_les_elements_non_dictionnaires():
    """Un tableau mêlant activités et bruit est refusé, pas filtré en silence.

    Filtrer laissait passer une réponse à moitié comprise : on aurait
    synchronisé « a111 » en croyant avoir tout vu.
    """
    c, _ = client(json_fixe([ACTIVITE_1, "bruit", 42, None]))
    with pytest.raises(ErreurConnecteur) as e:
        c.activites(date(2024, 3, 1), date(2024, 3, 31))
    assert "activities" in str(e.value)
    assert CLE not in str(e.value)


# --- découpe systématique par mois --------------------------------------------
#
# Tests qui auraient attrapé D3 : la découpe mensuelle n'avait lieu qu'au-delà
# de `SEUIL_TRONCATURE = 100` activités dans une réponse, une constante
# devinée. Si la vraie limite de l'API est plus basse, des sorties manquaient
# en silence. La découpe est maintenant systématique, et c'est le **nombre de
# requêtes** qui le mesure — pas le comportement d'un seuil.


def un_par_mois(requete: httpx.Request) -> httpx.Response:
    """Une activité par fenêtre mensuelle, identifiée par le mois demandé."""
    oldest = requete.url.params.get("oldest")
    return httpx.Response(
        200, json=[{"id": f"m{oldest[:7]}", "start_date_local": f"{oldest}T09:00:00"}]
    )


def test_une_requete_par_mois_civil_sur_une_fenetre_de_trois_mois():
    """Trois mois demandés = trois appels, aux bornes des mois civils."""
    c, espion = client(un_par_mois)
    activites = c.activites(date(2024, 1, 1), date(2024, 3, 31))
    assert espion.fenetres("activities") == [
        ("2024-01-01", "2024-01-31"),
        ("2024-02-01", "2024-02-29"),  # 2024 est bissextile
        ("2024-03-01", "2024-03-31"),
    ]
    assert len(espion.fenetres("activities")) == 3, "ni plus ni moins d'un appel par mois"
    assert [a["id"] for a in activites] == ["m2024-01", "m2024-02", "m2024-03"]


def test_la_decoupe_ne_depend_pas_de_la_taille_des_reponses():
    """Une seule activité par mois : la découpe a lieu quand même."""
    c, espion = client(un_par_mois)
    c.activites(date(2024, 1, 15), date(2024, 3, 10))
    assert espion.fenetres("activities") == [
        ("2024-01-15", "2024-01-31"),  # le premier mois part du jour demandé
        ("2024-02-01", "2024-02-29"),
        ("2024-03-01", "2024-03-10"),  # le dernier s'arrête au jour demandé
    ]


@pytest.mark.parametrize(
    "depuis, jusqua, appels_attendus",
    [
        (date(2024, 3, 5), date(2024, 3, 20), 1),  # tient dans un mois
        (date(2024, 3, 1), date(2024, 3, 31), 1),
        (date(2024, 3, 31), date(2024, 4, 1), 2),  # deux jours, deux mois civils
        (date(2024, 1, 1), date(2024, 3, 31), 3),
        (date(2023, 12, 1), date(2024, 11, 30), 12),
        (date(2023, 12, 1), date(2025, 12, 31), 25),  # deux ans d'historique
    ],
)
def test_nombre_d_appels_egal_au_nombre_de_mois_civils(
    depuis: date, jusqua: date, appels_attendus: int
):
    c, espion = client(un_par_mois)
    c.activites(depuis, jusqua)
    assert len(espion.fenetres("activities")) == appels_attendus


def test_le_passage_decembre_janvier_est_correct():
    c, espion = client(un_par_mois)
    c.activites(date(2023, 12, 15), date(2024, 1, 15))
    assert espion.fenetres("activities") == [
        ("2023-12-15", "2023-12-31"),
        ("2024-01-01", "2024-01-15"),
    ]


def test_aucun_appel_si_la_fenetre_est_vide():
    c, espion = client(un_par_mois)
    assert c.activites(date(2024, 3, 31), date(2024, 3, 1)) == []
    assert espion.fenetres("activities") == []


def test_la_decoupe_dedoublonne_les_activites_a_cheval():
    """Deux fenêtres mensuelles peuvent renvoyer la même activité : un seul exemplaire."""
    doublon = {"id": "a111", "start_date_local": "2024-02-15T09:00:00"}
    c, espion = client(json_fixe([doublon]))  # le même mois après mois
    activites = c.activites(date(2024, 1, 1), date(2024, 3, 31))
    assert len(espion.fenetres("activities")) == 3
    assert [a["id"] for a in activites] == ["a111"]


def test_le_dedoublonnage_garde_toutes_les_activites_distinctes():
    def trois_par_mois(requete: httpx.Request) -> httpx.Response:
        oldest = requete.url.params.get("oldest")
        mois = oldest[:7]
        return httpx.Response(
            200,
            json=[
                {"id": f"{mois}-{k}", "start_date_local": f"{oldest}T0{k}:00:00"} for k in (1, 2, 3)
            ],
        )

    c, _ = client(trois_par_mois)
    activites = c.activites(date(2024, 1, 1), date(2024, 3, 31))
    assert len(activites) == 9
    assert len({a["id"] for a in activites}) == 9


# --- téléchargement du fichier ------------------------------------------------


def fichier(contenu: bytes, entetes: dict | None = None):
    def reponses(requete: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=contenu, headers=entetes or {})

    return reponses


def test_telecharger_fichier_endpoint_et_contenu(activites: Path):
    octets = (activites / "boucle.fit").read_bytes()
    c, espion = client(fichier(octets))
    contenu, extension = c.telecharger_fichier("a111")
    assert contenu == octets
    assert extension == "fit"
    assert espion.chemins == ["/api/v1/activity/a111/file"]


def test_extension_depuis_content_disposition(activites: Path):
    c, _ = client(
        fichier(b"peu importe", {"content-disposition": 'attachment; filename="12345.tcx"'})
    )
    assert c.telecharger_fichier("a111")[1] == "tcx"


@pytest.mark.parametrize(
    ("nom", "extension"),
    [("boucle.fit", "fit"), ("boucle.gpx", "gpx"), ("boucle.tcx", "tcx")],
)
def test_extension_devinee_depuis_le_contenu(activites: Path, nom: str, extension: str):
    c, _ = client(fichier((activites / nom).read_bytes()))
    assert c.telecharger_fichier("a111")[1] == extension


def test_extension_par_defaut_si_rien_ne_dit_le_format():
    c, _ = client(fichier(b"\x00\x01\x02\x03 contenu opaque"))
    assert c.telecharger_fichier("a111")[1] == "fit"


def test_telecharger_fichier_vide():
    c, _ = client(fichier(b""))
    with pytest.raises(ErreurConnecteur) as e:
        c.telecharger_fichier("a111")
    assert "réponse vide" in str(e.value)


def test_telecharger_fichier_404():
    c, _ = client(json_fixe({}, code=404))
    with pytest.raises(ErreurConnecteur) as e:
        c.telecharger_fichier("a111")
    assert "404" in str(e.value) and "file" in str(e.value)


# --- événements ---------------------------------------------------------------


def test_evenements_du_jour():
    seance = {"id": 9001, "name": "Seance inventee", "category": "WORKOUT"}
    c, espion = client(json_fixe([seance]))
    assert c.evenements(date(2024, 3, 30)) == [seance]
    assert espion.chemins == [f"/api/v1/athlete/{ATHLETE}/events"]
    assert espion.fenetres("events") == [("2024-03-30", "2024-03-30")]


def test_evenements_vides():
    c, _ = client(json_fixe([]))
    assert c.evenements(date(2024, 3, 30)) == []


def test_evenements_plage_un_seul_appel():
    """Une plage se lit en un seul appel HTTP, jamais un par jour (F0.3)."""
    seance = {"id": 9002, "name": "Seance inventee", "category": "WORKOUT"}
    c, espion = client(json_fixe([seance]))
    rendu = c.evenements(date(2024, 3, 25), date(2024, 3, 31))
    assert rendu == [seance]
    assert espion.chemins == [f"/api/v1/athlete/{ATHLETE}/events"]
    assert espion.fenetres("events") == [("2024-03-25", "2024-03-31")]


def test_evenements_jusqua_omis_vaut_un_seul_jour():
    """`jusqua` omis retombe sur `depuis` : c'est le comportement mono-jour d'avant F0.3."""
    c, espion = client(json_fixe([]))
    c.evenements(date(2024, 3, 30))
    assert espion.fenetres("events") == [("2024-03-30", "2024-03-30")]


def test_evenements_plage_inversee_refusee():
    c, _ = client(json_fixe([]))
    with pytest.raises(ErreurUtilisateur):
        c.evenements(date(2024, 3, 31), date(2024, 3, 25))


# --- métadonnées --------------------------------------------------------------


def test_metadonnees_recopie_l_essentiel():
    m = metadonnees(ACTIVITE_1)
    assert m["source_id"] == "a111"
    assert m["sport"] == "Ride"
    assert m["equipement"] == "Route"  # gear.name
    assert m["appareil"] == "Appareil de test"
    assert m["puissance_moy_w"] == 205
    assert m["interieur"] is False


def test_metadonnees_marque_l_interieur():
    assert metadonnees(ACTIVITE_2)["interieur"] is True
    assert metadonnees({"id": 1, "type": "Ride", "trainer": True})["interieur"] is True


def test_metadonnees_tolere_les_valeurs_nulles_et_inattendues():
    assert metadonnees({"id": 1})["equipement"] is None
    assert metadonnees({"id": 1, "gear": None})["equipement"] is None
    assert metadonnees({"id": 1, "gear": "Route"})["equipement"] == "Route"
    assert metadonnees({"id": 1, "gear": 7})["equipement"] == "7"


# --- synchronisation ----------------------------------------------------------


@pytest.fixture
def cache(tmp_path: Path) -> Cache:
    return Cache(tmp_path / "cache")


def connecteur_complet(activites_dossier: Path, liste: list[dict], gear: list[dict] | None = None):
    """Transport qui sert la liste d'activités, l'équipement, puis un FIT valide."""
    fit = (activites_dossier / "boucle.fit").read_bytes()

    def reponses(requete: httpx.Request) -> httpx.Response:
        if requete.url.path.endswith("/activities"):
            return httpx.Response(200, json=liste)
        if requete.url.path.endswith("/gear"):
            return httpx.Response(200, json=gear if gear is not None else EQUIPEMENTS)
        return httpx.Response(200, content=fit)

    return reponses


def test_synchroniser_ajoute_et_recopie_les_metadonnees(cache: Cache, activites: Path):
    c, espion = client(connecteur_complet(activites, [ACTIVITE_1]))
    rapport = synchroniser(c, cache, date(2024, 3, 1))
    assert (rapport.vues, rapport.ajoutees, rapport.ignorees, rapport.echecs) == (1, 1, 0, 0)
    (entree,) = cache.lister()
    assert entree.source == "intervals" and entree.id_externe == "a111"
    assert entree.equipement == "Route inventee"  # résolu par l'endpoint gear
    assert entree.meta["power_meter"] == "CAPTEUR 0001"
    assert entree.meta["gear_id"] == "b000"
    assert entree.sport == "Ride"  # le type Intervals prime sur le « cycling » du FIT
    assert entree.meta["nom"] == "Sortie inventee 1"
    assert entree.extension == "fit"
    assert entree.chemin.is_file()
    assert espion.chemins.count("/api/v1/activity/a111/file") == 1


def test_synchroniser_ne_retelecharge_pas_ce_qui_est_en_cache(cache: Cache, activites: Path):
    c, espion = client(connecteur_complet(activites, [ACTIVITE_1]))
    synchroniser(c, cache, date(2024, 3, 1))
    telechargements = espion.chemins.count("/api/v1/activity/a111/file")

    rapport = synchroniser(c, cache, date(2024, 3, 1))
    assert (rapport.vues, rapport.ajoutees, rapport.ignorees) == (1, 0, 1)
    assert espion.chemins.count("/api/v1/activity/a111/file") == telechargements


def test_synchroniser_converge_quand_deux_activites_partagent_le_fichier(
    cache: Cache, activites: Path
):
    """Deux activités, un seul fichier d'origine (le cas du triathlon).

    Point 2 de la relecture du sprint 2 : le cache était indexé par le sha256
    du contenu, donc les deux segments d'un triathlon (natation et vélo dans
    le même FIT) n'avaient qu'une ligne, celle de la dernière. `contient()`
    devenait faux pour la première, qui était retéléchargée à chaque passe en
    faisant disparaître la seconde : la synchronisation n'a jamais convergé.
    """
    premiere = {**ACTIVITE_1, "id": "t1", "name": "Segment invente 1"}
    seconde = {**ACTIVITE_1, "id": "t2", "name": "Segment invente 2"}
    c, espion = client(connecteur_complet(activites, [premiere, seconde]))

    rapport = synchroniser(c, cache, date(2024, 3, 1))
    assert (rapport.vues, rapport.ajoutees, rapport.ignorees) == (2, 2, 0)
    entrees = cache.lister()
    assert {e.id_externe for e in entrees} == {"t1", "t2"}, "lister() doit rendre les deux"
    assert len({e.identifiant for e in entrees}) == 1, "même contenu = même identifiant"
    assert len(list(cache.brut.iterdir())) == 1, "un seul fichier brut"
    assert cache.contient(source="intervals", id_externe="t1")
    assert cache.contient(source="intervals", id_externe="t2")
    telechargements = [chemin for chemin in espion.chemins if chemin.endswith("/file")]
    assert len(telechargements) == 2

    rapport = synchroniser(c, cache, date(2024, 3, 1))
    assert (rapport.vues, rapport.ajoutees, rapport.ignorees) == (2, 0, 2), "seconde passe : 0 ajout"
    assert [
        chemin for chemin in espion.chemins if chemin.endswith("/file")
    ] == telechargements, "seconde passe : aucun appel /file"
    assert {e.id_externe for e in cache.lister()} == {"t1", "t2"}, "aucune des deux ne disparaît"


def test_synchroniser_compte_les_echecs_sans_s_arreter(cache: Cache, activites: Path):
    """Un fichier illisible ou en erreur ne doit pas interrompre la synchro."""
    fit = (activites / "boucle.fit").read_bytes()

    def reponses(requete: httpx.Request) -> httpx.Response:
        if requete.url.path.endswith("/activities"):
            return httpx.Response(200, json=[ACTIVITE_1, ACTIVITE_2])
        if requete.url.path.endswith("/gear"):
            return httpx.Response(200, json=EQUIPEMENTS)
        if "a111" in requete.url.path:
            return httpx.Response(500, json={})
        return httpx.Response(200, content=fit)

    c, _ = client(reponses)
    rapport = synchroniser(c, cache, date(2024, 3, 1))
    assert (rapport.vues, rapport.ajoutees, rapport.echecs) == (2, 1, 1)
    assert rapport.messages and rapport.messages[0].startswith("a111")
    assert CLE not in " ".join(rapport.messages)
    assert [e.id_externe for e in cache.lister()] == ["a222"]


def test_synchroniser_echoue_proprement_sur_un_fichier_illisible(cache: Cache):
    def reponses(requete: httpx.Request) -> httpx.Response:
        if requete.url.path.endswith("/activities"):
            return httpx.Response(200, json=[ACTIVITE_1])
        if requete.url.path.endswith("/gear"):
            return httpx.Response(200, json=EQUIPEMENTS)
        return httpx.Response(200, content=b"\x00 pas un fichier d'activite")

    c, _ = client(reponses)
    rapport = synchroniser(c, cache, date(2024, 3, 1))
    assert (rapport.ajoutees, rapport.echecs) == (0, 1)
    assert cache.lister() == []


def test_synchroniser_activite_sans_identifiant(cache: Cache):
    def un_seul_mois(requete: httpx.Request) -> httpx.Response:
        """L'activité sans id n'existe qu'en mars : la découpe mensuelle interroge tous les mois."""
        if requete.url.params.get("oldest") == "2024-03-01":
            return httpx.Response(200, json=[{"name": "sans id"}])
        return httpx.Response(200, json=[])

    c, _ = client(un_seul_mois)
    rapport = synchroniser(c, cache, date(2024, 3, 1))
    assert (rapport.vues, rapport.echecs) == (1, 1)
    assert "sans identifiant" in rapport.messages[0]


def test_synchroniser_liste_vide(cache: Cache):
    c, _ = client(json_fixe([]))
    assert synchroniser(c, cache, date(2024, 3, 1)) == RapportSynchro()


# --- L2.7 : équipements, métadonnées de rattachement, rafraîchissement --------


def test_equipements_resout_les_noms_et_n_appelle_qu_une_fois():
    """Un seul appel à `athlete/{id}/gear` par client, quel que soit l'usage."""
    c, espion = client(json_fixe(EQUIPEMENTS))
    assert c.equipements() == {"b000": "Route inventee", "b001": "CLM inventee"}
    assert c.equipements() == {"b000": "Route inventee", "b001": "CLM inventee"}
    assert espion.chemins == [f"/api/v1/athlete/{ATHLETE}/gear"]


def test_equipements_ignore_les_entrees_sans_id_ni_nom():
    c, _ = client(json_fixe([{"id": "b1"}, {"name": "sans id"}, {"id": "b2", "name": "Vu"}]))
    assert c.equipements() == {"b2": "Vu"}


def test_equipements_liste_vide():
    c, _ = client(json_fixe([]))
    assert c.equipements() == {}


def test_equipements_erreur_http_ne_laisse_pas_fuir_la_cle():
    c, _ = client(json_fixe({}, code=403))
    with pytest.raises(ErreurConnecteur) as e:
        c.equipements()
    assert "gear" in str(e.value) and CLE not in str(e.value)


def test_metadonnees_recopie_les_champs_de_rattachement():
    """Contrat §7 : power_meter, power_meter_serial, bilateral, gear_id, trainer,
    device_name."""
    m = metadonnees(ACTIVITE_1)
    assert m["power_meter"] == "CAPTEUR 0001"
    assert m["power_meter_serial"] == "SN-0001"
    assert m["gear_id"] == "b000"
    assert m["trainer"] is False
    assert m["device_name"] == "Appareil de test"


def test_metadonnees_bilateral_depend_de_avg_lr_balance():
    """Un capteur unilatéral ne renvoie pas `avg_lr_balance` ; un bilatéral, si."""
    assert metadonnees({"id": 1})["bilateral"] is False
    assert metadonnees({"id": 1, "avg_lr_balance": None})["bilateral"] is False
    assert metadonnees({"id": 1, "avg_lr_balance": 49.7})["bilateral"] is True
    assert metadonnees({"id": 1, "avg_lr_balance": 0})["bilateral"] is True


def test_metadonnees_resout_l_equipement_par_l_endpoint_gear():
    """La liste d'activités ne porte qu'un `gear.id` : le nom vient de la table."""
    sans_nom = {"id": "a1", "gear": {"id": "b001"}}
    assert metadonnees(sans_nom)["equipement"] is None
    assert metadonnees(sans_nom, {"b001": "CLM inventee"})["equipement"] == "CLM inventee"
    assert metadonnees(sans_nom, {})["equipement"] is None
    # Un identifiant absent de la table laisse le nom porté par l'activité.
    assert metadonnees(ACTIVITE_1, {"b999": "Autre"})["equipement"] == "Route"


def test_synchroniser_ne_rapatrie_que_le_velo(cache: Cache, activites: Path):
    """Le compte contient d'autres sports : ils sont comptés, jamais téléchargés."""
    c, espion = client(connecteur_complet(activites, [ACTIVITE_1, ACTIVITE_COURSE]))
    rapport = synchroniser(c, cache, date(2024, 3, 1))
    assert (rapport.vues, rapport.ajoutees, rapport.autres_sports) == (2, 1, 1)
    assert "/api/v1/activity/a333/file" not in espion.chemins
    assert [e.id_externe for e in cache.lister()] == ["a111"]


def test_synchroniser_filtre_velo_desactive_elargit_a_tout(cache: Cache, activites: Path):
    c, _ = client(connecteur_complet(activites, [ACTIVITE_COURSE]))
    rapport = synchroniser(c, cache, date(2024, 3, 1), filtre_velo=False)
    assert (rapport.ajoutees, rapport.autres_sports) == (1, 0)


def test_les_deux_filtres_de_sport_sont_le_meme(cache: Cache, activites: Path):
    """Point 7 de la relecture : le connecteur et l'inventaire se contredisaient.

    Le connecteur écartait tout `type` absent de `TYPES_VELO` — un type vide
    ou absent compris —, là où `est_sport_velo` compte comme du vélo un sport
    que la source n'a pas nommé : « on ne jette pas une sortie parce que la
    source s'est tue ». Une activité sans type, ou d'un type nouveau
    (« Gravel » plutôt que « GravelRide »), n'était donc jamais rapatriée, et
    se retrouvait comptée en `autres_sports`, perdue en silence.
    """
    sans_type = {**ACTIVITE_1, "id": "s1"}
    sans_type.pop("type")
    type_vide = {**ACTIVITE_1, "id": "s2", "type": ""}
    course = {**ACTIVITE_COURSE, "id": "s3"}

    c, espion = client(connecteur_complet(activites, [sans_type, type_vide, course]))
    rapport = synchroniser(c, cache, date(2024, 3, 1))

    assert (rapport.vues, rapport.ajoutees, rapport.autres_sports) == (3, 2, 1)
    assert {e.id_externe for e in cache.lister()} == {"s1", "s2"}
    assert "/api/v1/activity/s3/file" not in espion.chemins, "« Run » reste écarté"
    # Rapatriée sans type, l'activité est classée par ce que dit le fichier.
    (entree,) = [e for e in cache.lister() if e.id_externe == "s1"]
    assert entree.sport == "cycling", "à défaut de type Intervals, le FIT tranche"
    assert est_sport_velo(entree.sport), "et l'inventaire la compte bien en vélo"


@pytest.mark.parametrize(
    "libelle", [None, "", "Ride", "VirtualRide", "GravelRide", "Run", "Swim", "Triathlon"]
)
def test_le_connecteur_rapatrie_exactement_ce_que_l_inventaire_compte(
    cache: Cache, activites: Path, libelle
):
    """Point 7 : un seul filtre, donc la même réponse des deux côtés, libellé par libellé."""
    activite = {**ACTIVITE_1, "id": "u1"}
    if libelle is None:
        activite.pop("type")
    else:
        activite["type"] = libelle
    c, _ = client(connecteur_complet(activites, [activite]))
    rapport = synchroniser(c, cache, date(2024, 3, 1))
    assert (rapport.ajoutees == 1) is est_sport_velo(libelle), (
        f"{libelle!r} : le connecteur et `est_sport_velo` doivent dire la même chose"
    )


def test_types_velo_contient_les_types_cyclistes_d_intervals():
    assert "Ride" in TYPES_VELO and "VirtualRide" in TYPES_VELO
    assert "Run" not in TYPES_VELO and "Swim" not in TYPES_VELO


def test_rafraichir_meta_met_a_jour_sans_retelecharger(cache: Cache, activites: Path):
    """Le cœur de L2.7 : enrichir un cache déjà rempli sans repayer les téléchargements."""
    pauvre = {k: v for k, v in ACTIVITE_1.items() if k not in ("power_meter", "power_meter_serial")}
    c, espion = client(connecteur_complet(activites, [pauvre]))
    synchroniser(c, cache, date(2024, 3, 1))
    telechargements = espion.chemins.count("/api/v1/activity/a111/file")
    assert cache.lister()[0].meta.get("power_meter") is None

    c2, espion2 = client(connecteur_complet(activites, [ACTIVITE_1]))
    rapport = synchroniser(c2, cache, date(2024, 3, 1), rafraichir_meta=True)
    assert (rapport.ajoutees, rapport.ignorees, rapport.mises_a_jour) == (0, 1, 1)
    assert espion2.chemins.count("/api/v1/activity/a111/file") == 0
    assert espion.chemins.count("/api/v1/activity/a111/file") == telechargements
    (entree,) = cache.lister()
    assert entree.meta["power_meter"] == "CAPTEUR 0001"
    assert entree.equipement == "Route inventee"
    assert entree.chemin.is_file()


def test_sans_rafraichir_meta_ne_touche_a_rien(cache: Cache, activites: Path):
    pauvre = {k: v for k, v in ACTIVITE_1.items() if k != "power_meter"}
    c, _ = client(connecteur_complet(activites, [pauvre]))
    synchroniser(c, cache, date(2024, 3, 1))

    c2, _ = client(connecteur_complet(activites, [ACTIVITE_1]))
    rapport = synchroniser(c2, cache, date(2024, 3, 1), rafraichir_meta=False)
    assert (rapport.ignorees, rapport.mises_a_jour) == (1, 0)
    assert cache.lister()[0].meta.get("power_meter") is None


def test_equipement_injoignable_n_arrete_pas_la_synchronisation(cache: Cache, activites: Path):
    """Le nom d'équipement manque : le rattachement dégrade, la synchro continue — et le dit."""
    fit = (activites / "boucle.fit").read_bytes()

    def reponses(requete: httpx.Request) -> httpx.Response:
        if requete.url.path.endswith("/activities"):
            return httpx.Response(200, json=[ACTIVITE_1])
        if requete.url.path.endswith("/gear"):
            return httpx.Response(500, json={})
        return httpx.Response(200, content=fit)

    c, _ = client(reponses)
    rapport = synchroniser(c, cache, date(2024, 3, 1))
    assert rapport.ajoutees == 1 and rapport.echecs == 0
    assert any("équipements non résolus" in m for m in rapport.messages)
    assert CLE not in " ".join(rapport.messages)


def test_synchroniser_n_appelle_pas_gear_sur_une_liste_vide(cache: Cache):
    c, espion = client(json_fixe([]))
    synchroniser(c, cache, date(2024, 3, 1))
    assert not [c for c in espion.chemins if c.endswith("/gear")]


def test_une_entree_creuse_n_est_jamais_telechargee(cache: Cache, activites: Path):
    """Décision du superviseur (13/09/2026) : le compte du mainteneur contient des
    entrées Strava creuses — ni type, ni nom, ni durée, ni distance — dont le
    téléchargement répond 422 à chaque synchronisation. Une entrée sans
    contenu n'a pas de fichier : comptée dans `sans_contenu`, jamais appelée.
    Une activité sans type mais avec une durée reste rapatriée (point 7)."""
    creuse = {"id": "c1", "start_date_local": ACTIVITE_1["start_date_local"]}
    sans_type = {**ACTIVITE_1, "id": "s1"}
    sans_type.pop("type")
    c, espion = client(connecteur_complet(activites, [creuse, sans_type]))
    rapport = synchroniser(c, cache, date(2024, 3, 1))
    assert (rapport.vues, rapport.ajoutees, rapport.sans_contenu, rapport.echecs) == (2, 1, 1, 0)
    assert "/api/v1/activity/c1/file" not in espion.chemins
    assert [e.id_externe for e in cache.lister()] == ["s1"]


# --- intervalles d'une activité ------------------------------------------------


INTERVALLES_FABRIQUES = [
    {"type": "WORK", "start_index": 600, "end_index": 1080, "average_watts": 250},
    {"type": "RECOVERY", "start_index": 1080, "end_index": 1200, "average_watts": 120},
]


def test_intervalles_lus_depuis_un_objet_icu_intervals():
    c, espion = client(json_fixe({"id": "a111", "icu_intervals": INTERVALLES_FABRIQUES}))
    assert c.intervalles("a111") == INTERVALLES_FABRIQUES
    assert espion.chemins == ["/api/v1/activity/a111/intervals"]


def test_intervalles_lus_depuis_un_tableau_nu():
    c, _ = client(json_fixe(INTERVALLES_FABRIQUES))
    assert c.intervalles("a111") == INTERVALLES_FABRIQUES


def test_intervalles_absents_donnent_une_liste_vide():
    c, _ = client(json_fixe({"id": "a111"}))
    assert c.intervalles("a111") == []


def test_intervalles_de_forme_inattendue_sont_une_erreur():
    c, _ = client(json_fixe({"icu_intervals": "deux"}))
    with pytest.raises(ErreurConnecteur, match="intervals"):
        c.intervalles("a111")


def test_intervalles_http_en_erreur_remonte():
    c, _ = client(json_fixe({}, code=404))
    with pytest.raises(ErreurConnecteur, match="404"):
        c.intervalles("a111")


# --- profil_athlete (T1 de l'accueil, [[Q64]]) --------------------------------
#
# Les noms de champs ci-dessous sont **inventés**, sur le modèle plausible
# documenté dans `docs/journal/questions/questions_mainteneur.md` Q64 — jamais une réponse
# relue sur un vrai compte (règle absolue 4 : ce lot n'est pas vérifié sur les
# vraies données d'Intervals.icu, et cli/docs le disent).


def test_profil_athlete_appelle_le_bon_endpoint():
    c, espion = client(json_fixe({}))
    c.profil_athlete()
    assert espion.chemins == [f"/api/v1/athlete/{ATHLETE}"]


def test_profil_athlete_lit_ftp_et_poids_dans_sport_settings():
    """La forme documentée par Intervals.icu : un seuil par sport, sous `sportSettings`."""
    c, _ = client(
        json_fixe(
            {
                "id": ATHLETE,
                "weight": 68.4,
                "sportSettings": [
                    {"types": ["Ride", "VirtualRide"], "ftp": 231},
                    {"types": ["Run"], "ftp": 999},  # un autre sport : jamais pris
                ],
            }
        )
    )
    assert c.profil_athlete() == {"ftp_w": 231.0, "masse_kg": 68.4}


def test_profil_athlete_lit_ftp_a_la_racine_en_repli():
    """Un compte sans réglage par sport : repli sur un champ de racine plausible."""
    c, _ = client(json_fixe({"icu_ftp": 205, "icu_weight": 71.0}))
    assert c.profil_athlete() == {"ftp_w": 205.0, "masse_kg": 71.0}


def test_profil_athlete_ignore_un_sport_qui_n_est_pas_le_velo():
    """`sportSettings` sans aucun sport vélo : aucune FTP prise dans ce bloc-là."""
    c, _ = client(
        json_fixe(
            {
                "sportSettings": [{"types": ["Run"], "ftp": 300}],
                "icu_ftp": 190,  # repli de racine, lui, s'applique
            }
        )
    )
    assert c.profil_athlete()["ftp_w"] == 190.0


def test_profil_athlete_sans_ftp_ni_poids_rend_deux_none():
    c, _ = client(json_fixe({"id": ATHLETE}))
    assert c.profil_athlete() == {"ftp_w": None, "masse_kg": None}


def test_profil_athlete_ignore_un_zero_comme_une_absence():
    """`{"weight": 0}` n'est pas un poids de zéro kilo — c'est un champ vide."""
    c, _ = client(json_fixe({"weight": 0, "sportSettings": [{"types": ["Ride"], "ftp": 0}]}))
    assert c.profil_athlete() == {"ftp_w": None, "masse_kg": None}


def test_profil_athlete_reponse_qui_n_est_pas_un_objet():
    c, _ = client(json_fixe(["pas", "un", "objet"]))
    with pytest.raises(ErreurConnecteur, match="objet"):
        c.profil_athlete()


def test_profil_athlete_json_illisible():
    def reponses(requete: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"pas du json")

    c, _ = client(reponses)
    with pytest.raises(ErreurConnecteur, match="JSON"):
        c.profil_athlete()


def test_profil_athlete_erreur_http_ne_laisse_pas_fuir_la_cle():
    c, _ = client(json_fixe({}, code=401))
    with pytest.raises(ErreurConnecteur) as e:
        c.profil_athlete()
    assert CLE not in str(e.value)


# --- resoudre_athlete_id (correctif de prod du 25/09/2026) -------------------


def _transport_athlete_0(reponses):
    """Espion + transport pour `resoudre_athlete_id` : pas de `ClientIntervals`,
    donc pas de fabrique `client()` (qui exige déjà un athlete_id)."""
    espion = Espion(reponses)
    http = httpx.Client(transport=httpx.MockTransport(espion))
    return http, espion


def test_resoudre_athlete_id_lit_l_identifiant_de_la_reponse():
    http, espion = _transport_athlete_0(json_fixe({"id": "i999999"}))
    assert resoudre_athlete_id(CLE, http=http) == "i999999"
    assert espion.requetes[0].url.path == "/api/v1/athlete/0"


def test_resoudre_athlete_id_pose_un_user_agent_explicite():
    """Constaté en vrai : Intervals.icu répond 403 sans User-Agent explicite."""
    http, espion = _transport_athlete_0(json_fixe({"id": "i999999"}))
    resoudre_athlete_id(CLE, http=http)
    assert espion.requetes[0].headers["user-agent"] == USER_AGENT


def test_resoudre_athlete_id_authentifie_avec_la_cle_donnee():
    http, espion = _transport_athlete_0(json_fixe({"id": "i999999"}))
    resoudre_athlete_id(CLE, http=http)
    entete = espion.requetes[0].headers["authorization"]
    attendu = base64.b64encode(f"API_KEY:{CLE}".encode()).decode()
    assert entete == f"Basic {attendu}"


@pytest.mark.parametrize("code", [401, 403])
def test_resoudre_athlete_id_cle_refusee_est_une_erreur_connecteur(code: int):
    http, _ = _transport_athlete_0(json_fixe({"message": "refuse"}, code=code))
    with pytest.raises(ErreurConnecteur, match="clé d'API refusée"):
        resoudre_athlete_id(CLE, http=http)


def test_resoudre_athlete_id_cle_refusee_ne_laisse_pas_fuir_la_cle():
    http, _ = _transport_athlete_0(json_fixe({}, code=401))
    with pytest.raises(ErreurConnecteur) as e:
        resoudre_athlete_id(CLE, http=http)
    assert CLE not in str(e.value)


def test_resoudre_athlete_id_service_injoignable():
    def transport(requete: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("injoignable", request=requete)

    http = httpx.Client(transport=httpx.MockTransport(transport))
    with pytest.raises(ErreurConnecteur, match="appel impossible"):
        resoudre_athlete_id(CLE, http=http)


def test_resoudre_athlete_id_reponse_sans_identifiant():
    http, _ = _transport_athlete_0(json_fixe({"weight": 70}))
    with pytest.raises(ErreurConnecteur, match="identifiant absent"):
        resoudre_athlete_id(CLE, http=http)


def test_resoudre_athlete_id_json_illisible():
    def transport(requete: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"pas du json")

    http = httpx.Client(transport=httpx.MockTransport(transport))
    with pytest.raises(ErreurConnecteur, match="JSON"):
        resoudre_athlete_id(CLE, http=http)


def test_resoudre_athlete_id_sans_cle_est_un_refus_immediat():
    with pytest.raises(ErreurConnecteur, match="api_key"):
        resoudre_athlete_id("")


def test_get_pose_aussi_un_user_agent_explicite():
    """Pas seulement `resoudre_athlete_id` : tous les appels du connecteur."""
    c, espion = client(json_fixe([]))
    c.activites(date(2024, 3, 1), date(2024, 3, 31))
    assert espion.requetes[0].headers["user-agent"] == USER_AGENT
