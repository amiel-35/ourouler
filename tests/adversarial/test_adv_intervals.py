"""Connecteur Intervals.icu, mis à l'épreuve.

Tout passe par `httpx.MockTransport` : aucune socket n'est ouverte (fixture
`reseau_interdit`). La clé utilisée est une chaîne inventée
(`outils.CLE_BIDON`) et le fil rouge du fichier est qu'elle ne doit apparaître
**nulle part** dans ce qui sort du connecteur : message, `repr`, exception
chaînée, rapport de synchronisation.
"""

from __future__ import annotations

import base64
import traceback
from datetime import date
from typing import Any

import httpx
import outils
import pytest

from ourouler.activites import cache as module_cache
from ourouler.connecteurs import intervals as module_intervals
from ourouler.noyau.erreurs import ErreurConnecteur, ErreurUtilisateur

AUTORISATION_ATTENDUE = "Basic " + base64.b64encode(f"API_KEY:{outils.CLE_BIDON}".encode()).decode()
JETONS_SECRETS = (outils.CLE_BIDON, AUTORISATION_ATTENDUE, AUTORISATION_ATTENDUE.removeprefix("Basic "))

ACTIVITE = {
    "id": "i1",
    "start_date_local": "2026-04-12T09:00:00",
    "type": "Ride",
    "name": "Sortie fictive",
    "distance": 30000.0,
    "moving_time": 3600,
    "icu_average_watts": 200,
    "device_name": "Compteur Fictif 1000",
    "gear": {"id": "b1", "name": "Alpha"},
}


class Espion:
    """Transport bouchon : enregistre les requêtes, répond selon une fonction."""

    def __init__(self, reponse):
        self.requetes: list[httpx.Request] = []
        self._reponse = reponse

    def __call__(self, requete: httpx.Request) -> httpx.Response:
        self.requetes.append(requete)
        reponse = self._reponse(requete) if callable(self._reponse) else self._reponse
        return reponse

    @property
    def chemins(self) -> list[str]:
        return [r.url.path for r in self.requetes]


def _client(module, reponse, **kwargs):
    espion = Espion(reponse)
    http = httpx.Client(transport=httpx.MockTransport(espion))
    client = module.ClientIntervals(outils.ATHLETE_BIDON, outils.CLE_BIDON, http=http, **kwargs)
    return client, espion


def _verifier_sans_cle(objet: Any, quoi: str) -> None:
    """Ni la clé, ni son encodage base64, où que ce soit dans la chaîne d'erreurs."""
    textes = []
    if isinstance(objet, BaseException):
        vu = set()
        courante: BaseException | None = objet
        while courante is not None and id(courante) not in vu:
            vu.add(id(courante))
            textes += [str(courante), repr(courante)]
            textes += traceback.format_exception_only(type(courante), courante)
            courante = courante.__cause__ or courante.__context__
    else:
        textes += [str(objet), repr(objet)]
    for jeton in JETONS_SECRETS:
        for texte in textes:
            assert jeton not in texte, f"{quoi} : la clé d'API fuit dans « {texte[:200]} »"


# --- authentification et points d'entrée -------------------------------------


def test_auth_basique_et_endpoints():
    module = module_intervals
    client, espion = _client(module, httpx.Response(200, json=[ACTIVITE]))
    resultat = client.activites(date(2026, 4, 1), date(2026, 4, 30))
    assert isinstance(resultat, list) and resultat and isinstance(resultat[0], dict)
    assert espion.requetes, "aucune requête émise"
    for requete in espion.requetes:
        assert requete.headers.get("authorization") == AUTORISATION_ATTENDUE, (
            "auth basique API_KEY:<clé> attendue (contrat §3)"
        )
        assert requete.url.path == f"/api/v1/athlete/{outils.ATHLETE_BIDON}/activities"
        assert requete.url.params.get("oldest"), "paramètre oldest attendu"
        assert requete.url.params.get("newest"), "paramètre newest attendu"


def test_fenetre_demandee_couverte_et_sans_doublon():
    """Si le connecteur découpe par mois, il doit couvrir la fenêtre et dédoublonner."""
    module = module_intervals
    client, espion = _client(module, httpx.Response(200, json=[ACTIVITE]))
    activites = client.activites(date(2026, 1, 1), date(2026, 3, 31))
    bornes_basses = [r.url.params["oldest"][:10] for r in espion.requetes]
    bornes_hautes = [r.url.params["newest"][:10] for r in espion.requetes]
    assert min(bornes_basses) == "2026-01-01", f"oldest le plus ancien : {min(bornes_basses)}"
    assert max(bornes_hautes) == "2026-03-31", f"newest le plus récent : {max(bornes_hautes)}"
    identifiants = [a.get("id") for a in activites]
    assert len(identifiants) == len(set(identifiants)), (
        f"activités en double après découpage : {identifiants}"
    )


def test_base_url_respectee_et_sans_double_slash():
    module = module_intervals
    client, espion = _client(module, httpx.Response(200, json=[]), base_url="https://exemple.invalide/")
    client.activites(date(2026, 4, 1))
    url = espion.requetes[0].url
    assert url.host == "exemple.invalide", f"base_url ignorée : {url}"
    assert "//api" not in url.path, f"chemin mal recollé : {url}"


def test_evenements_du_jour():
    module = module_intervals
    client, espion = _client(module, httpx.Response(200, json=[]))
    assert client.evenements(date(2026, 4, 12)) == []
    requete = espion.requetes[0]
    assert requete.url.path == f"/api/v1/athlete/{outils.ATHLETE_BIDON}/events"
    assert requete.url.params["oldest"][:10] == "2026-04-12"
    assert requete.url.params["newest"][:10] == "2026-04-12"


# --- erreurs HTTP ------------------------------------------------------------


@pytest.mark.parametrize("code", [400, 401, 403, 404, 429, 500, 502, 503])
def test_erreur_http_devient_erreur_connecteur(code):
    module = module_intervals
    client, _ = _client(module, httpx.Response(code, text="refusé"))
    with pytest.raises(ErreurConnecteur) as capture:
        client.activites(date(2026, 4, 1))
    message = str(capture.value)
    assert str(code) in message, f"le message doit nommer le code HTTP : {message!r}"
    assert "activities" in message, f"le message doit nommer l'endpoint : {message!r}"
    _verifier_sans_cle(capture.value, f"erreur {code}")


@pytest.mark.parametrize(
    "reponse",
    [
        httpx.Response(401, text="clé invalide : CLE"),
        httpx.Response(403, json={"error": "bad API_KEY:CLE"}),
        httpx.Response(500, text="Traceback ... Authorization: AUTORISATION ..."),
    ],
    ids=["401 qui répète la clé", "403 en JSON qui répète la clé", "500 qui répète l'entête"],
)
def test_la_cle_ne_fuit_pas_meme_si_le_service_la_renvoie(reponse):
    """Cas classique : `raise ErreurConnecteur(f"… {reponse.text}")`."""
    module = module_intervals
    corps = reponse.text.replace("CLE", outils.CLE_BIDON).replace("AUTORISATION", AUTORISATION_ATTENDUE)
    client, _ = _client(module, httpx.Response(reponse.status_code, text=corps))
    with pytest.raises(ErreurConnecteur) as capture:
        client.activites(date(2026, 4, 1))
    _verifier_sans_cle(capture.value, "réponse qui répète la clé")


def test_pas_de_tempete_de_reessais_sur_429():
    module = module_intervals
    client, espion = _client(module, httpx.Response(429, text="trop de requêtes"))
    with pytest.raises(ErreurConnecteur):
        client.activites(date(2026, 4, 1))
    assert len(espion.requetes) <= 5, f"{len(espion.requetes)} tentatives : réessais non bornés"


def test_erreur_reseau_transformee():
    """Une panne de transport doit devenir une erreur utilisateur, pas une httpx.HTTPError."""
    module = module_intervals

    def tomber(_requete):
        raise httpx.ConnectError("service injoignable")

    client, _ = _client(module, tomber)
    with pytest.raises(ErreurUtilisateur) as capture:
        client.activites(date(2026, 4, 1))
    _verifier_sans_cle(capture.value, "panne de transport")


# --- corps de réponse hostiles ------------------------------------------------


@pytest.mark.parametrize(
    "corps",
    [b"", b"   ", b"null", b"<html>maintenance</html>", b"{", b"[{]"],
    ids=["vide", "blancs", "null", "html", "json tronque", "json casse"],
)
def test_json_inattendu_devient_erreur_connecteur(corps):
    module = module_intervals
    client, _ = _client(module, httpx.Response(200, content=corps))
    with pytest.raises(ErreurConnecteur):
        client.activites(date(2026, 4, 1))


@pytest.mark.parametrize("corps", [ACTIVITE, {"activities": []}], ids=["une activité", "enveloppe"])
def test_un_objet_au_lieu_d_une_liste(corps):
    """Le contrat annonce `list[dict]` : un objet seul est une réponse inattendue.

    Deux lectures défendables — refuser, ou envelopper dans une liste d'un
    élément. Ce qui n'est pas défendable, c'est de rendre autre chose qu'une
    liste de dictionnaires : le reste du lot compte dessus.
    """
    module = module_intervals
    client, _ = _client(module, httpx.Response(200, json=corps))
    resultat, erreur = outils.robuste(
        lambda: client.activites(date(2026, 4, 1)),
        quoi="activites() sur un objet unique",
        erreurs_acceptees=(ErreurConnecteur,),
    )
    if erreur is None:
        assert resultat == [corps], f"objet seul mal enveloppé : {resultat!r}"


@pytest.mark.parametrize("contenu", [[42, "x"], [None], [[]], [{"id": "i1"}, 7]], ids=str)
def test_liste_d_elements_non_dict(contenu):
    module = module_intervals
    client, _ = _client(module, httpx.Response(200, json=contenu))
    with pytest.raises(ErreurConnecteur):
        client.activites(date(2026, 4, 1))


def test_liste_vide_est_une_reponse_valide():
    module = module_intervals
    client, _ = _client(module, httpx.Response(200, json=[]))
    assert client.activites(date(2026, 4, 1)) == []
    assert client.evenements(date(2026, 4, 12)) == []


# --- téléchargement du fichier -----------------------------------------------


def _reponse_fichier(contenu: bytes, *, nom: str | None = "activite.fit", code: int = 200):
    entetes = {"content-type": "application/octet-stream"}
    if nom:
        entetes["content-disposition"] = f'attachment; filename="{nom}"'
    return httpx.Response(code, content=contenu, headers=entetes)


@pytest.mark.parametrize(
    "nom, extension_attendue",
    [("activite.fit", "fit"), ("activite.FIT", "fit"), ("trace.gpx", "gpx"), ("trace.tcx", "tcx")],
)
def test_telecharger_fichier_extension(hostiles, nom, extension_attendue):
    module = module_intervals
    octets = hostiles["nominal.fit"].read_bytes()
    client, espion = _client(module, _reponse_fichier(octets, nom=nom))
    contenu, extension = client.telecharger_fichier("i1")
    assert contenu == octets, "le fichier doit être rendu octet pour octet"
    assert extension.lower().lstrip(".") == extension_attendue, f"extension rendue : {extension!r}"
    assert espion.requetes[0].url.path == "/api/v1/activity/i1/file"


def test_telecharger_fichier_sans_content_disposition(hostiles):
    """Sans nom de fichier annoncé, l'extension doit rester une extension connue."""
    module = module_intervals
    client, _ = _client(module, _reponse_fichier(hostiles["nominal.fit"].read_bytes(), nom=None))
    resultat, erreur = outils.robuste(
        lambda: client.telecharger_fichier("i1"),
        quoi="telecharger_fichier sans content-disposition",
        erreurs_acceptees=(ErreurConnecteur,),
    )
    if erreur is None:
        _, extension = resultat
        assert extension.lower().lstrip(".") in ("fit", "gpx", "tcx"), f"extension {extension!r}"


@pytest.mark.parametrize("code", [401, 404, 429, 500])
def test_telecharger_fichier_en_erreur(code):
    module = module_intervals
    client, _ = _client(module, _reponse_fichier(b"", code=code))
    with pytest.raises(ErreurConnecteur) as capture:
        client.telecharger_fichier("i1")
    assert str(code) in str(capture.value)
    _verifier_sans_cle(capture.value, f"téléchargement {code}")


def test_telecharger_fichier_vide_refuse():
    """Un fichier de 0 octet mis en cache est un déchet : il faut le refuser."""
    module = module_intervals
    client, _ = _client(module, _reponse_fichier(b""))
    with pytest.raises(ErreurConnecteur):
        client.telecharger_fichier("i1")


def test_telecharger_fichier_identifiant_hostile():
    module = module_intervals
    client, espion = _client(module, _reponse_fichier(b"\x00" * 10))
    outils.robuste(
        lambda: client.telecharger_fichier("../athlete/i1/activities"),
        quoi="telecharger_fichier avec un identifiant hostile",
        erreurs_acceptees=(ErreurUtilisateur,),
    )
    for requete in espion.requetes:
        assert ".." not in requete.url.path, f"l'identifiant remonte dans l'URL : {requete.url}"


# --- synchroniser -------------------------------------------------------------


def _synchro(module, tmp_path, reponses, *, depuis=date(2026, 4, 1)):
    cache_module = module_cache
    cache = cache_module.Cache(tmp_path / "cache")
    client, espion = _client(module, reponses)
    rapport = module.synchroniser(client, cache, depuis)
    return rapport, cache, espion


def test_synchroniser_ajoute_et_rapporte(tmp_path, hostiles):
    module = module_intervals
    octets = hostiles["nominal.gpx"].read_bytes()
    activites = [dict(ACTIVITE, id="i1"), dict(ACTIVITE, id="i2")]

    def repondre(requete: httpx.Request) -> httpx.Response:
        if requete.url.path.endswith("/file"):
            return _reponse_fichier(octets if "i1" in requete.url.path else octets + b"\n", nom="a.gpx")
        return httpx.Response(200, json=activites)

    rapport, cache, _ = _synchro(module, tmp_path, repondre)
    assert outils.champ(rapport, "vues") == 2
    assert outils.champ(rapport, "ajout") == 2
    assert not outils.champ(rapport, "echec")
    assert len(cache.lister()) == 2
    assert cache.contient(source="intervals", id_externe="i1")
    _verifier_sans_cle(rapport, "RapportSynchro")


def test_synchroniser_ne_retelecharge_pas_ce_qui_est_en_cache(tmp_path, hostiles):
    module = module_intervals
    cache_module = module_cache
    octets = hostiles["nominal.gpx"].read_bytes()
    cache = cache_module.Cache(tmp_path / "cache")
    cache.ajouter(octets, source="intervals", id_externe="i1", extension="gpx", meta={})

    activites = [dict(ACTIVITE, id="i1"), dict(ACTIVITE, id="i2")]

    def repondre(requete: httpx.Request) -> httpx.Response:
        if requete.url.path.endswith("/file"):
            return _reponse_fichier(octets + b"\n", nom="a.gpx")
        return httpx.Response(200, json=activites)

    client, espion = _client(module, repondre)
    rapport = module.synchroniser(client, cache, date(2026, 4, 1))
    telechargements = [c for c in espion.chemins if c.endswith("/file")]
    assert telechargements == ["/api/v1/activity/i2/file"], (
        f"seule l'activité absente doit être téléchargée, appels : {telechargements}"
    )
    assert outils.champ(rapport, "ignor") == 1


@pytest.mark.parametrize(
    "activite",
    [
        {},
        {"id": None},
        {"id": ""},
        {"id": 17},
        {"id": "i1", "gear": None},
        {"id": "i1", "gear": "Alpha"},
        {"id": "i1", "gear": {"name": None}},
        {"id": "i1", "start_date_local": None},
        {"id": "i1", "start_date_local": "pas une date"},
        {"id": "i1", "icu_average_watts": "beaucoup"},
        {"id": "i1", "type": ["Ride"]},
        {"id": "i1", "device_name": 42},
    ],
    ids=str,
)
def test_synchroniser_survit_aux_activites_mal_formees(tmp_path, hostiles, activite):
    """Chaque champ peut manquer, être nul ou d'un type inattendu : pas de trace."""
    module = module_intervals
    octets = hostiles["nominal.gpx"].read_bytes()

    def repondre(requete: httpx.Request) -> httpx.Response:
        if requete.url.path.endswith("/file"):
            return _reponse_fichier(octets, nom="a.gpx")
        return httpx.Response(200, json=[activite])

    resultat, _ = outils.robuste(
        lambda: _synchro(module, tmp_path, repondre),
        quoi=f"synchroniser sur {activite!r}",
        erreurs_acceptees=(ErreurUtilisateur,),
    )
    if resultat is None:  # refus propre : rien d'autre à vérifier
        return
    rapport, cache, _espion = resultat
    assert outils.champ(rapport, "vues") >= 1
    for entree in cache.lister():
        outils.verifier_utc(entree.debut, "EntreeCache.debut")
        outils.verifier_json(entree.meta, "EntreeCache.meta")


def test_synchroniser_compte_les_echecs_et_continue(tmp_path, hostiles):
    """Un téléchargement qui casse ne doit pas emporter les autres."""
    module = module_intervals
    octets = hostiles["nominal.gpx"].read_bytes()
    activites = [dict(ACTIVITE, id="i1"), dict(ACTIVITE, id="i2"), dict(ACTIVITE, id="i3")]

    def repondre(requete: httpx.Request) -> httpx.Response:
        if requete.url.path.endswith("/file"):
            if "i2" in requete.url.path:
                return _reponse_fichier(b"", code=500)
            if "i3" in requete.url.path:
                return _reponse_fichier(b"pas un fichier d'activite", nom="a.gpx")
            return _reponse_fichier(octets, nom="a.gpx")
        return httpx.Response(200, json=activites)

    rapport, cache, _ = _synchro(module, tmp_path, repondre)
    assert outils.champ(rapport, "vues") == 3
    assert outils.champ(rapport, "ajout") == 1, "seule i1 est exploitable"
    assert outils.champ(rapport, "echec") == 2, "i2 (500) et i3 (fichier illisible)"
    assert len(cache.lister()) == 1
    _verifier_sans_cle(rapport, "RapportSynchro avec échecs")


def test_synchroniser_sur_liste_vide(tmp_path):
    module = module_intervals
    rapport, cache, espion = _synchro(module, tmp_path, httpx.Response(200, json=[]))
    assert outils.champ(rapport, "vues") == 0
    assert outils.champ(rapport, "ajout") == 0
    assert cache.lister() == []
    assert not [c for c in espion.chemins if c.endswith("/file")]


def test_synchroniser_remonte_l_erreur_de_liste(tmp_path):
    module = module_intervals
    with pytest.raises(ErreurConnecteur):
        _synchro(module, tmp_path, httpx.Response(500, text="panne"))
