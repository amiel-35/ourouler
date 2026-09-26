"""L3.3 — archive météo (`connecteurs/openmeteo_archive.py`), mise à l'épreuve.

Cible : contrat du sprint 3 §3 et §4. La calibration repose entièrement sur ce
connecteur : un vent mal lu se retrouve dans le CdA, et le rapport d'erreur du
sprint ne veut alors plus rien dire.

Ce qui est traqué :

* le **jour futur** : l'archive ne sait rien de demain. Le contrat §4 dit
  « jour futur refusé » — et refusé **sans** appeler le service ;
* le **jour antérieur à 1940** : la réanalyse ERA5 commence là ; en deçà, la
  réponse est vide et le cache mémorise le vide ;
* les **coordonnées hors du globe** : une latitude de 91° est une faute de
  l'appelant, elle n'a pas à devenir une requête HTTP ;
* les **heures manquantes** : `time` porte 24 heures et `wind_speed_10m` dix.
  Un `zip` strict lève, un `zip` laxiste tronque en silence, un accès par
  indice lève `IndexError` — le contrat §4 cite explicitement ce cas ;
* la **mémoïsation** : « l'archive du passé ne change pas ». Deux fois le même
  jour au même point, c'est un seul appel — sinon la calibration sur 160
  sorties refait 160 appels à chaque lancement.

Le contrat ne fixe pas *comment* le cache est passé (« le cache est passé en
paramètre ») : ces tests le découvrent par introspection de la signature.
"""

from __future__ import annotations

import inspect
import math
from datetime import UTC, date, datetime, timedelta
from typing import Any

import fabriques
import fabriques_physique
import httpx
import pytest
from outils import robuste, sans_accents, verifier_utc

from ourouler.connecteurs import openmeteo_archive as module_openmeteo_archive
from ourouler.noyau.erreurs import ErreurConnecteur, ErreurUtilisateur

CHAMPS_HEURE = {"t", "vent_kmh", "vent_depuis_deg", "temp_c", "pression_hpa"}

#: Début de la réanalyse ERA5 sur laquelle repose l'archive Open-Meteo.
PREMIERE_ANNEE = 1940

ERREURS = (ErreurConnecteur, ErreurUtilisateur, ValueError)

#: Jetons qui trahissent un paramètre de mémoïsation dans une signature.
JETONS_CACHE = ("cache", "memo", "chemin", "sqlite", "base")


def _parametre_cache(fonction) -> str | None:
    """Le nom du paramètre qui reçoit le chemin de mémoïsation, s'il y en a un."""
    for nom in inspect.signature(fonction).parameters:
        if nom in ("self", "http", "base_url"):
            continue
        reduit = sans_accents(nom).casefold()
        if any(jeton in reduit for jeton in JETONS_CACHE):
            return nom
    return None


def _client(module, espion, *, memo=None):
    """Un `ClientArchive` branché sur le transport bouchon, avec mémo si possible."""
    kwargs: dict[str, Any] = {"base_url": fabriques_physique.URL_ARCHIVE}
    if memo is not None:
        nom = _parametre_cache(module.ClientArchive.__init__)
        if nom is None:
            pytest.skip(
                "ClientArchive ne prend pas de chemin de mémoïsation : le contrat §3 le veut "
                "en paramètre (« le cœur ne connaît pas le chemin »)"
            )
        kwargs[nom] = memo
    return module.ClientArchive(espion.client(), **kwargs)


def _espion(**options):
    return fabriques.EspionHttp(lambda requete: fabriques_physique.repondre_archive(requete, **options))


# --- vérificateurs ------------------------------------------------------------


def _verifier_heures(heures: Any, quoi: str) -> list[Any]:
    assert isinstance(heures, list), f"{quoi} : liste attendue, reçu {type(heures).__name__}"
    precedent: datetime | None = None
    for i, h in enumerate(heures):
        manquants = CHAMPS_HEURE - {n for n in dir(h) if not n.startswith("_")}
        assert not manquants, f"{quoi}[{i}] : champs du contrat absents {sorted(manquants)}"
        instant = verifier_utc(h.t, f"{quoi}[{i}].t")
        if precedent is not None:
            assert instant > precedent, f"{quoi}[{i}].t = {instant} après {precedent} : heures en désordre"
        precedent = instant
        for nom in ("vent_kmh", "vent_depuis_deg", "temp_c", "pression_hpa"):
            valeur = getattr(h, nom)
            if valeur is None:
                continue  # « le modèle ne sait pas » reste une réponse valable
            assert isinstance(valeur, (int, float)) and not isinstance(valeur, bool), (
                f"{quoi}[{i}].{nom} : nombre ou None attendu, reçu {valeur!r}"
            )
            assert not math.isnan(valeur), f"{quoi}[{i}].{nom} : NaN (un `null` lu comme nombre ?)"
            assert math.isfinite(valeur), f"{quoi}[{i}].{nom} : infini"
        if h.vent_kmh is not None:
            assert 0 <= h.vent_kmh < 400, f"{quoi}[{i}].vent_kmh = {h.vent_kmh}"
        if h.vent_depuis_deg is not None:
            assert 0 <= h.vent_depuis_deg <= 360, (
                f"{quoi}[{i}].vent_depuis_deg = {h.vent_depuis_deg}, hors de [0, 360]"
            )
        if h.temp_c is not None:
            assert -90 <= h.temp_c <= 60, f"{quoi}[{i}].temp_c = {h.temp_c}"
    return list(heures)


# --- nominal ------------------------------------------------------------------


def test_une_journee_complete_se_relit():
    module = module_openmeteo_archive
    espion = _espion()
    client = _client(module, espion)
    heures = _verifier_heures(
        client.horaires(fabriques.LAT0, fabriques.LON0, fabriques_physique.JOUR_ARCHIVE),
        "horaires(jour passé)",
    )
    assert len(heures) == 24, f"{len(heures)} heures pour une journée de 24 heures"
    assert espion.requetes, "aucune requête émise"
    assert heures[0].vent_depuis_deg == pytest.approx(230.0), (
        f"vent_depuis_deg = {heures[0].vent_depuis_deg} pour 230° dans la réponse — "
        "direction confondue avec la vitesse ?"
    )
    assert heures[0].vent_kmh == pytest.approx(18.0), (
        f"vent_kmh = {heures[0].vent_kmh} pour 18 km/h dans la réponse"
    )


def test_les_heures_sont_datees_en_utc():
    """Le reste du produit range tout en UTC ; une heure naïve décale le vent d'une sortie."""
    module = module_openmeteo_archive
    espion = _espion()
    heures = _verifier_heures(
        _client(module, espion).horaires(fabriques.LAT0, fabriques.LON0, fabriques_physique.JOUR_ARCHIVE),
        "horaires",
    )
    assert heures[0].t.date() == fabriques_physique.JOUR_ARCHIVE, (
        f"première heure au {heures[0].t.date()} pour un appel sur {fabriques_physique.JOUR_ARCHIVE}"
    )
    assert heures[0].t.hour == 0, f"la journée commence à {heures[0].t.hour} h UTC"


def test_la_requete_demande_bien_le_jour_voulu():
    module = module_openmeteo_archive
    espion = _espion()
    _client(module, espion).horaires(fabriques.LAT0, fabriques.LON0, fabriques_physique.JOUR_ARCHIVE)
    params = espion.params(0)
    jour = fabriques_physique.JOUR_ARCHIVE.isoformat()
    assert any(jour in str(v) for v in params.values()), (
        f"le jour demandé ({jour}) n'apparaît pas dans les paramètres : {params}"
    )


# --- dates et coordonnées refusées --------------------------------------------


def test_un_jour_futur_est_refuse_sans_appel():
    """Contrat §4 : « jour futur refusé »."""
    module = module_openmeteo_archive
    espion = _espion()
    client = _client(module, espion)
    demain = datetime.now(UTC).date() + timedelta(days=3)
    with pytest.raises((ErreurConnecteur, ErreurUtilisateur)) as capture:
        client.horaires(fabriques.LAT0, fabriques.LON0, demain)
    assert not espion.requetes, (
        f"{len(espion.requetes)} requête(s) émise(s) pour un jour futur : "
        "le refus doit venir avant le réseau"
    )
    assert demain.isoformat() in str(capture.value) or "futur" in sans_accents(
        str(capture.value)
    ).casefold(), f"le message ne dit pas ce qui cloche : « {capture.value} »"


def test_un_jour_anterieur_a_1940_est_refuse():
    """Angle obligatoire : la réanalyse ERA5 commence en 1940, avant c'est un vide mémorisé."""
    module = module_openmeteo_archive
    espion = _espion(heures=0)
    client = _client(module, espion)
    ancien = date(PREMIERE_ANNEE - 11, 6, 15)
    resultat, erreur = robuste(
        lambda: client.horaires(fabriques.LAT0, fabriques.LON0, ancien),
        quoi=f"horaires({ancien})",
        erreurs_acceptees=(ErreurConnecteur, ErreurUtilisateur),
    )
    if resultat is None:
        assert not espion.requetes, (
            "le jour est refusé, mais après avoir appelé le service : "
            f"{len(espion.requetes)} requête(s)"
        )
        assert str(PREMIERE_ANNEE) in str(erreur) or ancien.isoformat() in str(erreur), (
            f"le message ne dit pas la borne de l'archive : « {erreur} »"
        )
        return
    heures = _verifier_heures(resultat, f"horaires({ancien})")
    assert heures == [], (
        f"{len(heures)} heure(s) rendues pour {ancien}, antérieur au début de l'archive"
    )


@pytest.mark.parametrize(
    ("lat", "lon"),
    [(91.0, 0.0), (-90.5, 0.0), (0.0, 180.5), (0.0, -181.0), (float("nan"), 0.0)],
)
def test_des_coordonnees_hors_du_globe_sont_refusees_sans_appel(lat, lon):
    """Angle obligatoire : lat/lon hors bornes. Une faute d'appelant n'est pas une requête."""
    module = module_openmeteo_archive
    espion = _espion()
    client = _client(module, espion)
    resultat, _ = robuste(
        lambda: client.horaires(lat, lon, fabriques_physique.JOUR_ARCHIVE),
        quoi=f"horaires({lat}, {lon})",
        erreurs_acceptees=(ErreurConnecteur, ErreurUtilisateur),
    )
    assert resultat is None, (
        f"horaires({lat}, {lon}) a rendu un résultat pour une coordonnée hors du globe"
    )
    assert not espion.requetes, (
        f"requête émise pour ({lat}, {lon}) : la validation vient après le réseau"
    )


# --- réponses hostiles --------------------------------------------------------


def test_une_reponse_aux_heures_manquantes():
    """Angle obligatoire : `time` a 24 entrées, les mesures 10."""
    module = module_openmeteo_archive
    espion = _espion(colonnes_courtes=10)
    resultat, _ = robuste(
        lambda: _client(module, espion).horaires(
            fabriques.LAT0, fabriques.LON0, fabriques_physique.JOUR_ARCHIVE
        ),
        quoi="horaires(colonnes tronquées)",
        erreurs_acceptees=(ErreurConnecteur,),
    )
    if resultat is None:
        return
    heures = _verifier_heures(resultat, "horaires(colonnes tronquées)")
    assert len(heures) <= 24, f"{len(heures)} heures rendues pour 24 horodatages"
    for i, h in enumerate(heures[10:], start=10):
        assert h.vent_kmh is None, (
            f"heures[{i}].vent_kmh = {h.vent_kmh} alors que la colonne s'arrête à la 10ᵉ heure — "
            "une valeur inventée par recyclage du dernier indice"
        )


@pytest.mark.parametrize(
    "options",
    [
        pytest.param({"hourly": {}}, id="hourly vide"),
        pytest.param({"hourly": None}, id="hourly null"),
        pytest.param({"hourly": []}, id="hourly liste"),
        pytest.param({"heures": 0}, id="aucune heure"),
        pytest.param({"sans": ("wind_speed_10m",)}, id="sans vent"),
        pytest.param(
            {"sans": ("wind_direction_10m", "surface_pressure", "pressure_msl")},
            id="sans direction",
        ),
    ],
)
def test_des_reponses_incompletes(options):
    """Contrat §4 : « archive météo vide/partielle »."""
    module = module_openmeteo_archive
    espion = _espion(**options)
    resultat, _ = robuste(
        lambda: _client(module, espion).horaires(
            fabriques.LAT0, fabriques.LON0, fabriques_physique.JOUR_ARCHIVE
        ),
        quoi=f"horaires({options})",
        erreurs_acceptees=(ErreurConnecteur,),
    )
    if resultat is not None:
        _verifier_heures(resultat, f"horaires({options})")


def test_des_valeurs_nulles_restent_nulles():
    """Contrat §4 : « null ». `None` n'est pas `0.0` : un vent inconnu n'est pas un vent nul."""
    module = module_openmeteo_archive
    espion = _espion(vent_kmh=None, vent_depuis_deg=None, temp_c=None, pression_hpa=None)
    resultat, _ = robuste(
        lambda: _client(module, espion).horaires(
            fabriques.LAT0, fabriques.LON0, fabriques_physique.JOUR_ARCHIVE
        ),
        quoi="horaires(valeurs null)",
        erreurs_acceptees=(ErreurConnecteur,),
    )
    if resultat is None:
        return
    heures = _verifier_heures(resultat, "horaires(valeurs null)")
    for i, h in enumerate(heures):
        assert h.vent_kmh is None, (
            f"heures[{i}].vent_kmh = {h.vent_kmh} pour un `null` : un vent inconnu devient "
            "un vent nul, et la calibration croit à un jour sans vent"
        )


@pytest.mark.parametrize("code", [400, 404, 429, 500, 503])
def test_une_erreur_http_devient_une_erreur_utilisateur(code):
    module = module_openmeteo_archive
    espion = fabriques.EspionHttp(httpx.Response(code, json={"reason": "essai"}))
    client = _client(module, espion)
    with pytest.raises(ErreurConnecteur) as capture:
        client.horaires(fabriques.LAT0, fabriques.LON0, fabriques_physique.JOUR_ARCHIVE)
    message = str(capture.value)
    assert str(code) in message, f"le code HTTP n'est pas dit : « {message} »"
    assert fabriques_physique.URL_ARCHIVE.split("//")[1] in message, (
        f"le message ne dit pas quel service a refusé : « {message} »"
    )


@pytest.mark.parametrize(
    "reponse",
    [
        pytest.param(httpx.Response(200, content=b"pas du json"), id="non-JSON"),
        pytest.param(httpx.Response(200, content=b""), id="corps vide"),
        pytest.param(httpx.Response(200, json=[]), id="liste vide"),
        pytest.param(httpx.Response(200, json={"error": True, "reason": "hors domaine"}), id="erreur métier"),
    ],
)
def test_des_corps_de_reponse_inexploitables(reponse):
    module = module_openmeteo_archive
    espion = fabriques.EspionHttp(reponse)
    resultat, _ = robuste(
        lambda: _client(module, espion).horaires(
            fabriques.LAT0, fabriques.LON0, fabriques_physique.JOUR_ARCHIVE
        ),
        quoi="horaires(corps inexploitable)",
        erreurs_acceptees=(ErreurConnecteur,),
    )
    if resultat is not None:
        _verifier_heures(resultat, "horaires(corps inexploitable)")


def test_un_reseau_qui_tombe_devient_une_erreur_utilisateur():
    module = module_openmeteo_archive

    def couper(_requete):
        raise httpx.ConnectError("serveur injoignable")

    espion = fabriques.EspionHttp(couper)
    client = _client(module, espion)
    with pytest.raises(ErreurConnecteur):
        client.horaires(fabriques.LAT0, fabriques.LON0, fabriques_physique.JOUR_ARCHIVE)


# --- mémoïsation ---------------------------------------------------------------


def test_le_meme_jour_au_meme_point_n_est_demande_qu_une_fois():
    """Contrat §3 : « un appel par (jour, point arrondi à 0,05°) »."""
    module = module_openmeteo_archive
    espion = _espion()
    client = _client(module, espion)
    for _ in range(3):
        client.horaires(fabriques.LAT0, fabriques.LON0, fabriques_physique.JOUR_ARCHIVE)
    assert len(espion.requetes) == 1, (
        f"{len(espion.requetes)} requêtes pour trois fois le même (jour, point) : "
        "l'archive du passé ne change pas, elle se mémorise"
    )


def test_deux_points_de_la_meme_maille_ne_font_qu_un_appel():
    """Contrat §3 : « point arrondi à 0,05° » — soit environ 5,5 km."""
    module = module_openmeteo_archive
    espion = _espion()
    client = _client(module, espion)
    client.horaires(0.0011, 0.0017, fabriques_physique.JOUR_ARCHIVE)
    client.horaires(0.0155, 0.0180, fabriques_physique.JOUR_ARCHIVE)
    assert len(espion.requetes) == 1, (
        f"{len(espion.requetes)} requêtes pour deux points distants de moins de 3 km, qui "
        "s'arrondissent au même 0,05°"
    )


def test_deux_mailles_distinctes_font_deux_appels():
    """Le pendant du test précédent : l'arrondi ne doit pas tout écraser sur un seul point."""
    module = module_openmeteo_archive
    espion = _espion()
    client = _client(module, espion)
    client.horaires(0.0011, 0.0017, fabriques_physique.JOUR_ARCHIVE)
    client.horaires(0.4011, 0.4017, fabriques_physique.JOUR_ARCHIVE)
    assert len(espion.requetes) == 2, (
        f"{len(espion.requetes)} requête(s) pour deux points distants de 60 km"
    )


def test_deux_jours_distincts_font_deux_appels():
    module = module_openmeteo_archive
    espion = _espion()
    client = _client(module, espion)
    client.horaires(fabriques.LAT0, fabriques.LON0, fabriques_physique.JOUR_ARCHIVE)
    client.horaires(fabriques.LAT0, fabriques.LON0, fabriques_physique.JOUR_ARCHIVE - timedelta(days=1))
    assert len(espion.requetes) == 2, (
        f"{len(espion.requetes)} requête(s) pour deux jours différents : la mémoïsation "
        "ignore la date"
    )


def test_la_memoisation_survit_a_un_nouveau_client(tmp_path):
    """Contrat §3 : mémoïsé « dans cache.dossier / archive_meteo.sqlite »."""
    module = module_openmeteo_archive
    memo = tmp_path / "archive_meteo.sqlite"
    premier = _espion()
    _client(module, premier, memo=memo).horaires(
        fabriques.LAT0, fabriques.LON0, fabriques_physique.JOUR_ARCHIVE
    )
    assert len(premier.requetes) == 1
    second = _espion()
    heures = _client(module, second, memo=memo).horaires(
        fabriques.LAT0, fabriques.LON0, fabriques_physique.JOUR_ARCHIVE
    )
    _verifier_heures(heures, "horaires(depuis le fichier de mémoïsation)")
    assert not second.requetes, (
        "un second client redemande au service ce qu'un premier a déjà rangé dans "
        f"{memo.name} : la mémoïsation ne vit qu'en mémoire"
    )
    assert len(heures) == 24, f"{len(heures)} heures relues du cache pour 24 écrites"


def test_un_fichier_de_memoisation_corrompu(tmp_path):
    """Le fichier appartient à l'utilisateur : message ou contournement, pas de trace."""
    module = module_openmeteo_archive
    memo = tmp_path / "archive_meteo.sqlite"
    memo.write_bytes(b"ni sqlite ni json\x00\xff" * 50)
    espion = _espion()
    resultat, _ = robuste(
        lambda: _client(module, espion, memo=memo).horaires(
            fabriques.LAT0, fabriques.LON0, fabriques_physique.JOUR_ARCHIVE
        ),
        quoi="horaires(mémo corrompu)",
        erreurs_acceptees=(ErreurConnecteur, ErreurUtilisateur),
    )
    if resultat is not None:
        _verifier_heures(resultat, "horaires(mémo corrompu)")


def test_une_reponse_en_erreur_n_est_pas_memorisee_comme_une_journee():
    """Mémoriser un échec transforme un incident passager en trou permanent."""
    module = module_openmeteo_archive
    espion = fabriques.EspionHttp(httpx.Response(500, json={"reason": "essai"}))
    client = _client(module, espion)
    for _ in range(2):
        robuste(
            lambda: client.horaires(fabriques.LAT0, fabriques.LON0, fabriques_physique.JOUR_ARCHIVE),
            quoi="horaires(HTTP 500)",
            erreurs_acceptees=(ErreurConnecteur, ErreurUtilisateur),
        )
    assert len(espion.requetes) == 2, (
        f"{len(espion.requetes)} requête(s) : un échec HTTP a été mémorisé comme une réponse"
    )
