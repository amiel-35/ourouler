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
from ourouler.connecteurs.intervals import (
    ClientIntervals,
    RapportSynchro,
    metadonnees,
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
    """Certaines API rendent `null` plutôt qu'un tableau vide."""

    def nul(requete: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"null", headers={"content-type": "application/json"})

    c, _ = client(nul)
    assert c.activites(date(2024, 3, 1), date(2024, 3, 31)) == []


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


def test_activites_ignore_les_elements_non_dictionnaires():
    c, _ = client(json_fixe([ACTIVITE_1, "bruit", 42, None]))
    assert [a["id"] for a in c.activites(date(2024, 3, 1), date(2024, 3, 31))] == ["a111"]


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


def connecteur_complet(activites_dossier: Path, liste: list[dict]):
    """Transport qui sert une liste d'activités puis un FIT valide pour chacune."""
    fit = (activites_dossier / "boucle.fit").read_bytes()

    def reponses(requete: httpx.Request) -> httpx.Response:
        if requete.url.path.endswith("/activities"):
            return httpx.Response(200, json=liste)
        return httpx.Response(200, content=fit)

    return reponses


def test_synchroniser_ajoute_et_recopie_les_metadonnees(cache: Cache, activites: Path):
    c, espion = client(connecteur_complet(activites, [ACTIVITE_1]))
    rapport = synchroniser(c, cache, date(2024, 3, 1))
    assert (rapport.vues, rapport.ajoutees, rapport.ignorees, rapport.echecs) == (1, 1, 0, 0)
    (entree,) = cache.lister()
    assert entree.source == "intervals" and entree.id_externe == "a111"
    assert entree.equipement == "Route"
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


def test_synchroniser_compte_les_echecs_sans_s_arreter(cache: Cache, activites: Path):
    """Un fichier illisible ou en erreur ne doit pas interrompre la synchro."""
    fit = (activites / "boucle.fit").read_bytes()

    def reponses(requete: httpx.Request) -> httpx.Response:
        if requete.url.path.endswith("/activities"):
            return httpx.Response(200, json=[ACTIVITE_1, ACTIVITE_2])
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
