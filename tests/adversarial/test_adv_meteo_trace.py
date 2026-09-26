"""Pluie et vent le long du tracé, mis à l'épreuve.

Le client Open-Meteo est le vrai
(`ourouler.meteo.openmeteo.ClientOpenMeteo`) branché sur un
`MockTransport` qui fabrique la réponse **à partir de la requête reçue** : un
bloc par point demandé, les heures de la fenêtre demandée. C'est ce qui permet
de vérifier en aveugle les promesses coûteuses :

* **un seul appel** Open-Meteo pour tous les échantillons ;
* l'heure de passage `depart + dist / vitesse`, et l'**interpolation linéaire**
  entre les deux heures encadrantes (pas la valeur de l'heure la plus proche) ;
* `vent_relatif` calculé sur le **cap local**, avec la règle ±45° de
  `meteo.rapport` et non une seconde règle recopiée ;
* aucune division par zéro (`vitesse_kmh = 0`) ni boucle infinie (`pas_m = 0`).
"""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
from typing import Any

import fabriques
import httpx
import outils
import pytest
from fabriques import EspionHttp
from outils import robuste

from ourouler.boucle import meteo_trace as module_meteo_trace
from ourouler.boucle.horaire import construire_horaire
from ourouler.meteo import rapport
from ourouler.meteo.openmeteo import ClientOpenMeteo
from ourouler.noyau.erreurs import ErreurUtilisateur

BASE_URL = "https://openmeteo.exemple.invalide"
MODELE = "meteofrance_arome_france_hd"
SECOND_AVIS = "icon_seamless"
DEPART_T = datetime(2026, 4, 12, 8, 0, tzinfo=UTC)

CHAMPS_ECHANTILLON = {
    "dist_m",
    "t",
    "lat",
    "lon",
    "cap_deg",
    "pluie_mm",
    "vent_kmh",
    "vent_relatif",
    "ressenti_c",
}
CHAMPS_METEO = {
    "echantillons",
    "pluie_cumulee_mm",
    "minutes_pluie",
    "part_vent_face",
    "part_vent_dos",
    "ressenti_min_c",
    "confiance",
}


def _client(**kwargs) -> tuple[ClientOpenMeteo, EspionHttp]:
    espion = EspionHttp(lambda requete: fabriques.repondre_openmeteo(requete, **kwargs))
    return ClientOpenMeteo(http=espion.client(), base_url=BASE_URL), espion


def _client_par_modele(reponses: dict[str, dict]) -> tuple[ClientOpenMeteo, EspionHttp]:
    """Une réponse différente selon le modèle demandé, pour éprouver le second avis."""

    def _repondre(requete):
        modele = dict(requete.url.params).get("models", "")
        return fabriques.repondre_openmeteo(requete, **reponses.get(modele, {}))

    espion = EspionHttp(_repondre)
    return ClientOpenMeteo(http=espion.client(), base_url=BASE_URL), espion


def _trace(km: float = 12.0, *, cap_deg: float = 0.0, pas_m: float = 50.0):
    """Une trace dense : un point tous les 50 m par défaut.

    L'espacement compte pour les tests d'échantillonnage : le contrat ne dit pas
    si l'implémentation interpole une position à `pas_m` exactement ou se cale
    sur le point du tracé le plus proche. Avec des points tous les 50 m, les
    deux lectures tiennent dans la même tolérance.
    """
    return fabriques.trace_fictive(
        fabriques.ligne(int(km * 1000 / pas_m) + 1, pas_m=pas_m, cap_deg=cap_deg)
    )


def _evaluer(module, trace, client, **surcharges):
    """Appelle `module.evaluer`, en traduisant `depart`/`vitesse_kmh` en `horaire`.

    Le contrat testé ici appelait `evaluer` avec `depart`/`vitesse_kmh` ; le
    lot des pauses lui a substitué un `horaire` (`boucle.horaire`,
    « à quelle heure suis-je au kilomètre X »). Les surcharges historiques
    des tests de ce fichier restent lisibles telles quelles — c'est cette
    fonction qui construit l'horaire, pas chaque test.
    """
    depart = surcharges.pop("depart", DEPART_T)
    vitesse_kmh = surcharges.pop("vitesse_kmh", 20.0)
    arguments: dict[str, Any] = {
        "horaire": construire_horaire(depart, vitesse_kmh),
        "modele": MODELE,
        "pas_m": 5000.0,
    }
    arguments.update(surcharges)
    with fabriques.limite_temps(10.0, "meteo_trace.evaluer"):
        return module.evaluer(trace, client, **arguments)


def _verifier(meteo: Any, quoi: str) -> None:
    outils.exiger_champs(type(meteo), CHAMPS_METEO)
    assert meteo.echantillons, f"{quoi} : aucun échantillon"
    outils.exiger_champs(type(meteo.echantillons[0]), CHAMPS_ECHANTILLON)
    precedent = None
    for i, e in enumerate(meteo.echantillons):
        assert isinstance(e.t, datetime), f"{quoi} : échantillons[{i}].t = {e.t!r}"
        assert e.t.tzinfo is not None, (
            f"{quoi} : échantillons[{i}].t est naïf — il se compare à des heures Open-Meteo UTC"
        )
        assert -90.0 <= e.lat <= 90.0 and -180.0 <= e.lon <= 180.0, (
            f"{quoi} : échantillons[{i}] hors du globe"
        )
        assert 0.0 <= e.cap_deg < 360.0, f"{quoi} : échantillons[{i}].cap_deg = {e.cap_deg}"
        assert e.vent_relatif in (None, rapport.VENT_FACE, rapport.VENT_DOS, rapport.VENT_TRAVERS), (
            f"{quoi} : échantillons[{i}].vent_relatif = {e.vent_relatif!r}"
        )
        for nom in ("dist_m", "pluie_mm", "vent_kmh", "ressenti_c"):
            valeur = getattr(e, nom)
            if valeur is not None:
                assert math.isfinite(valeur), f"{quoi} : échantillons[{i}].{nom} non fini"
        if precedent is not None:
            assert e.dist_m >= precedent.dist_m, f"{quoi} : échantillons[{i}].dist_m recule"
            assert e.t >= precedent.t, f"{quoi} : échantillons[{i}].t recule"
        precedent = e
    for nom in ("pluie_cumulee_mm", "minutes_pluie", "part_vent_face", "part_vent_dos"):
        valeur = getattr(meteo, nom)
        assert isinstance(valeur, (int, float)) and not isinstance(valeur, bool), (
            f"{quoi} : {nom} doit être un nombre, reçu {valeur!r}"
        )
        assert math.isfinite(valeur), f"{quoi} : {nom} non fini"
        assert valeur >= 0, f"{quoi} : {nom} négatif ({valeur})"
    assert meteo.part_vent_face <= 1.0 and meteo.part_vent_dos <= 1.0, (
        f"{quoi} : les parts de vent sont des fractions, reçu face={meteo.part_vent_face} "
        f"dos={meteo.part_vent_dos}"
    )
    assert meteo.part_vent_face + meteo.part_vent_dos <= 1.0 + 1e-9, (
        f"{quoi} : face + dos = {meteo.part_vent_face + meteo.part_vent_dos} > 1"
    )
    assert meteo.confiance in (
        rapport.CONFIANCE_ACCORD,
        rapport.CONFIANCE_DESACCORD,
        rapport.CONFIANCE_INCONNUE,
    ), f"{quoi} : confiance = {meteo.confiance!r}"


# --- promesses du contrat ----------------------------------------------------


def test_un_seul_appel_open_meteo_pour_tout_le_trace():
    """Un **seul** appel Open-Meteo pour tous les échantillons."""
    module = module_meteo_trace
    client, espion = _client()
    meteo = _evaluer(module, _trace(40.0, pas_m=200.0), client, pas_m=2000.0)
    _verifier(meteo, "un seul appel")
    assert len(espion.requetes) == 1, (
        f"{len(espion.requetes)} appels pour {len(meteo.echantillons)} échantillons : "
        "Open-Meteo accepte plusieurs points dans une même requête"
    )
    params = espion.params()
    assert params["latitude"].count(",") == len(meteo.echantillons) - 1, (
        "chaque échantillon doit être un point de l'unique requête"
    )


def test_les_echantillons_couvrent_le_trace_et_finissent_au_dernier_point():
    module = module_meteo_trace
    client, _ = _client()
    trace = _trace(12.0)
    meteo = _evaluer(module, trace, client, pas_m=5000.0)
    _verifier(meteo, "pas de 5 km")

    distances = [e.dist_m for e in meteo.echantillons]
    assert distances[0] == pytest.approx(0.0, abs=1.0), "le premier échantillon est au départ"
    assert distances[-1] == pytest.approx(trace.distance_m, abs=5.0), (
        f"dernier échantillon à {distances[-1]:.0f} m pour une trace de {trace.distance_m:.0f} m "
        "— le contrat demande un échantillon au dernier point"
    )
    for i, d in enumerate(distances[:-1]):
        assert d == pytest.approx(5000.0 * i, abs=60.0), (
            f"échantillon {i} à {d:.0f} m, attendu tous les 5 000 m : {distances}"
        )


def test_l_heure_de_passage_suit_la_vitesse():
    module = module_meteo_trace
    client, _ = _client()
    meteo = _evaluer(module, _trace(12.0), client, vitesse_kmh=20.0, pas_m=5000.0)
    for e in meteo.echantillons:
        attendu = DEPART_T + timedelta(hours=e.dist_m / 1000.0 / 20.0)
        assert abs((e.t - attendu).total_seconds()) <= 60.0, (
            f"échantillon à {e.dist_m:.0f} m daté {e.t}, attendu {attendu} "
            "(depart + dist / vitesse)"
        )


def test_la_valeur_horaire_est_interpolee_lineairement():
    """La valeur horaire s'interpole linéairement entre les deux heures encadrantes."""
    module = module_meteo_trace
    client, _ = _client(pluie=lambda _ip, ih: 2.0 * ih)  # 0 mm à H, 2 mm à H+1, 4 mm à H+2
    meteo = _evaluer(module, _trace(10.0), client, vitesse_kmh=10.0, pas_m=5000.0)
    _verifier(meteo, "interpolation")

    attendus = {0: 0.0, 5000: 1.0, 10000: 2.0}  # 0 h, 30 min, 1 h après le départ
    for e in meteo.echantillons:
        cible = attendus.get(round(e.dist_m / 100.0) * 100)
        if cible is None:
            continue
        assert e.pluie_mm == pytest.approx(cible, abs=0.05), (
            f"à {e.dist_m:.0f} m ({e.t:%H:%M}), pluie = {e.pluie_mm} alors que la série vaut "
            f"0 mm à 08:00 et 2 mm à 09:00 : attendu {cible} par interpolation linéaire"
        )


@pytest.mark.parametrize(
    "cap, vent_depuis, attendu",
    [
        (0.0, 0.0, rapport.VENT_FACE),
        (0.0, 180.0, rapport.VENT_DOS),
        (0.0, 90.0, rapport.VENT_TRAVERS),
        (90.0, 90.0, rapport.VENT_FACE),
        (90.0, 270.0, rapport.VENT_DOS),
        (180.0, 0.0, rapport.VENT_DOS),
    ],
)
def test_le_vent_relatif_suit_le_cap_local(cap, vent_depuis, attendu):
    module = module_meteo_trace
    client, _ = _client(vent_depuis_deg=vent_depuis)
    meteo = _evaluer(module, _trace(12.0, cap_deg=cap), client, pas_m=5000.0)
    relatifs = {e.vent_relatif for e in meteo.echantillons}
    assert relatifs == {attendu}, (
        f"cap {cap}°, vent venant de {vent_depuis}° : attendu « {attendu} » partout, reçu {relatifs} "
        "(règle ±45° de meteo.rapport, à réutiliser et non à redéfinir)"
    )
    assert rapport.vent_relatif(cap, vent_depuis) == attendu, "la règle du sprint 1 a changé"


def test_les_minutes_de_pluie_comptent_le_seuil_du_contrat():
    module = module_meteo_trace
    trace = _trace(20.0)
    client_mouille, _ = _client(pluie=0.5)
    mouille = _evaluer(module, trace, client_mouille, vitesse_kmh=20.0, pas_m=5000.0)
    _verifier(mouille, "pluie 0,5 mm/h")
    duree_min = trace.distance_m / 1000.0 / 20.0 * 60.0
    assert mouille.minutes_pluie > 0, "0,5 mm/h est au-dessus du seuil de 0,2 mm/h"
    assert mouille.minutes_pluie <= duree_min + 60.0, (
        f"{mouille.minutes_pluie:.0f} min de pluie pour une sortie de {duree_min:.0f} min"
    )

    client_sec, _ = _client(pluie=0.1)
    sec = _evaluer(module, trace, client_sec, vitesse_kmh=20.0, pas_m=5000.0)
    assert sec.minutes_pluie == 0, (
        f"0,1 mm/h est sous le seuil de 0,2 mm/h, mais {sec.minutes_pluie} min sont comptées"
    )
    assert sec.pluie_cumulee_mm >= 0


def test_le_ressenti_minimal_est_bien_le_minimum():
    module = module_meteo_trace
    client, _ = _client(ressenti_c=lambda _ip, ih: 10.0 - ih)
    meteo = _evaluer(module, _trace(20.0), client, vitesse_kmh=20.0, pas_m=5000.0)
    ressentis = [e.ressenti_c for e in meteo.echantillons if e.ressenti_c is not None]
    assert meteo.ressenti_min_c == pytest.approx(min(ressentis), abs=0.01), (
        f"ressenti_min_c = {meteo.ressenti_min_c}, minimum des échantillons = {min(ressentis)}"
    )


# --- second avis --------------------------------------------------------------


def test_sans_second_avis_la_confiance_est_inconnue():
    module = module_meteo_trace
    client, espion = _client(pluie=1.0)
    meteo = _evaluer(module, _trace(12.0), client, second_avis=None)
    assert meteo.confiance == rapport.CONFIANCE_INCONNUE, (
        f"sans second modèle, la confiance ne peut pas être « {meteo.confiance} »"
    )
    assert len(espion.requetes) == 1, "un seul modèle demandé = un seul appel"


def test_un_desaccord_entre_modeles_est_signale():
    module = module_meteo_trace
    client, espion = _client_par_modele({MODELE: {"pluie": 1.0}, SECOND_AVIS: {"pluie": 0.0}})
    meteo = _evaluer(module, _trace(12.0), client, second_avis=SECOND_AVIS)
    _verifier(meteo, "second avis")
    assert len(espion.requetes) == 2, (
        f"{len(espion.requetes)} appels : un par modèle, pas un par point"
    )
    modeles = {dict(r.url.params).get("models") for r in espion.requetes}
    assert modeles == {MODELE, SECOND_AVIS}, f"modèles interrogés : {modeles}"
    assert meteo.confiance == rapport.CONFIANCE_DESACCORD, (
        "1 mm/h contre 0 mm/h : les deux modèles sont en désaccord (règle du sprint 1)"
    )
    assert meteo.pluie_cumulee_mm > 0, (
        "le cumul de pluie reste celui du modèle principal (1 mm/h), il ne se moyenne pas "
        "avec le second avis (règle absolue 5 de CLAUDE.md)"
    )


def test_un_accord_entre_modeles_est_signale():
    module = module_meteo_trace
    client, _ = _client_par_modele({MODELE: {"pluie": 1.0}, SECOND_AVIS: {"pluie": 1.2}})
    meteo = _evaluer(module, _trace(12.0), client, second_avis=SECOND_AVIS)
    assert meteo.confiance == rapport.CONFIANCE_ACCORD, (
        "1 mm/h contre 1,2 mm/h : les deux modèles disent la même chose"
    )


# --- entrées hostiles ---------------------------------------------------------


@pytest.mark.parametrize("vitesse", [0.0, -12.0])
def test_une_vitesse_absurde_ne_divise_pas_par_zero(vitesse):
    module = module_meteo_trace
    client, _ = _client()
    meteo, erreur = robuste(
        lambda: _evaluer(module, _trace(12.0), client, vitesse_kmh=vitesse),
        quoi=f"evaluer(vitesse_kmh={vitesse})",
        erreurs_acceptees=(ErreurUtilisateur,),
    )
    if erreur is None:
        _verifier(meteo, f"vitesse {vitesse}")


@pytest.mark.parametrize("pas_m", [0.0, -5000.0])
def test_un_pas_absurde_ne_fait_pas_tourner_la_boucle_a_vide(pas_m):
    """Un `pas_m` nul fige la génération des échantillons : `limite_temps` le prouve."""
    module = module_meteo_trace
    client, espion = _client()
    meteo, erreur = robuste(
        lambda: _evaluer(module, _trace(12.0), client, pas_m=pas_m),
        quoi=f"evaluer(pas_m={pas_m})",
        erreurs_acceptees=(ErreurUtilisateur,),
    )
    if erreur is None:
        _verifier(meteo, f"pas_m {pas_m}")
        assert len(meteo.echantillons) <= 1000, (
            f"{len(meteo.echantillons)} échantillons pour 12 km : un point tous les 12 m ?"
        )
    assert len(espion.requetes) <= 2, "pas d'appel par échantillon"


def test_une_trace_d_un_seul_point_ne_casse_rien():
    module = module_meteo_trace
    client, _ = _client()
    trace = fabriques.trace_fictive(fabriques.ligne(1))
    meteo, erreur = robuste(
        lambda: _evaluer(module, trace, client),
        quoi="evaluer(trace d'un point)",
        erreurs_acceptees=(ErreurUtilisateur,),
    )
    if erreur is None:
        _verifier(meteo, "trace d'un point")
        assert len(meteo.echantillons) == 1
        assert meteo.pluie_cumulee_mm == pytest.approx(0.0, abs=1e-6) or meteo.minutes_pluie == 0


def test_une_trace_vide_ne_part_pas_interroger_open_meteo():
    module = module_meteo_trace
    client, espion = _client()
    trace = fabriques.trace_fictive([])
    _, erreur = robuste(
        lambda: _evaluer(module, trace, client),
        quoi="evaluer(trace vide)",
        erreurs_acceptees=(ErreurUtilisateur,),
    )
    assert erreur is not None or not espion.requetes, (
        "une trace sans point n'a aucun échantillon à interroger"
    )


def test_une_pluie_absente_ne_devient_pas_zero():
    """`null` veut dire « le modèle ne sait pas », pas « il ne pleut pas »."""
    module = module_meteo_trace
    client, _ = _client(pluie=None)
    meteo = _evaluer(module, _trace(12.0), client)
    _verifier(meteo, "pluie nulle")
    assert all(e.pluie_mm is None for e in meteo.echantillons), (
        f"pluie inventée : {[e.pluie_mm for e in meteo.echantillons]}"
    )
    assert meteo.minutes_pluie == 0, "aucune minute de pluie ne se compte sans donnée"
    assert meteo.pluie_cumulee_mm == pytest.approx(0.0, abs=1e-9)


def test_un_trace_plus_long_que_l_horizon_ne_ment_pas():
    """Une trace plus longue que l'horizon météo le dit au lieu d'inventer."""
    module = module_meteo_trace
    client, _ = _client(heures_max=3)  # trois heures de prévision pour vingt heures de vélo
    trace = _trace(400.0, pas_m=5000.0)
    meteo, erreur = robuste(
        lambda: _evaluer(module, trace, client, vitesse_kmh=20.0, pas_m=25_000.0),
        quoi="evaluer(trace plus longue que l'horizon)",
        erreurs_acceptees=(ErreurUtilisateur,),
    )
    if erreur is None:
        _verifier(meteo, "hors horizon")
        tardifs = [e for e in meteo.echantillons if e.t > DEPART_T + timedelta(hours=3)]
        assert tardifs, "la sortie dure vingt heures : il y a bien des échantillons hors horizon"
        assert all(e.pluie_mm is None for e in tardifs), (
            "au-delà de la dernière heure connue, la prévision est inconnue, pas nulle"
        )


def test_un_depart_naif_ne_provoque_pas_de_comparaison_impossible():
    module = module_meteo_trace
    client, _ = _client()
    meteo, erreur = robuste(
        lambda: _evaluer(module, _trace(12.0), client, depart=datetime(2026, 4, 12, 8, 0)),
        quoi="evaluer(depart naïf)",
        erreurs_acceptees=(ErreurUtilisateur,),
    )
    if erreur is None:
        _verifier(meteo, "depart naïf")


def test_le_point_de_depart_ne_part_pas_dans_un_message_d_erreur():
    """Les messages Open-Meteo ne publient jamais les coordonnées."""
    module = module_meteo_trace
    espion = EspionHttp(httpx.Response(500, text="boom"))
    client = ClientOpenMeteo(http=espion.client(), base_url=BASE_URL)
    _, erreur = robuste(
        lambda: _evaluer(module, _trace(12.0), client),
        quoi="evaluer(Open-Meteo en panne)",
        erreurs_acceptees=(ErreurUtilisateur,),
    )
    assert erreur is not None, "un HTTP 500 doit remonter en erreur utilisateur"
    assert f"{fabriques.LAT0}" not in str(erreur), f"le départ fuit dans « {erreur} »"
