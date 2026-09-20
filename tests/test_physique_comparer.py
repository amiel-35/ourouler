"""`ourouler comparer` : deux vélos, la vitesse à puissance égale sur le plat.

Toutes les sorties sont fabriquées : vitesse et puissance constantes, choisies
ici, sur un tracé qui part du point (0, 0) au milieu de l'Atlantique. Aucune
coordonnée réelle, aucun réseau, aucune donnée du mainteneur.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from test_physique_commande import _en_tcx, config_de_test

from ourouler.activites.cache import Cache
from ourouler.activites.modele import Activite, Point
from ourouler.erreurs import ErreurUtilisateur
from ourouler.physique.comparer import (
    CAP_MAX_DEG_SUGGERE,
    LONGUEUR_MIN_M_DEFAUT,
    PENTE_MAX_DEFAUT,
    SERIES_MIN_REGRESSION,
    Serie,
    bornes_bandes,
    comparer,
    executer_comparer,
    regresser,
    series_droites,
)
from ourouler.physique.modele import Parametres, puissance_requise

METRE_EN_DEGRE = 1.0 / 111_194.93
DEPART = datetime(2026, 3, 15, 9, 0, tzinfo=UTC)

#: FTP de `config_de_test` : 258 W, donc Z2 par défaut = 144,5-193,5 W.
FTP_DE_TEST = 258.0
ZONE_TEST = (0.56 * FTP_DE_TEST, 0.75 * FTP_DE_TEST)


def args(**champs) -> argparse.Namespace:
    defauts = {
        "velos": ["RCR", "BMC"],
        "zone": None,
        "pente_max": None,
        "cap_max": None,
        "longueur_min": None,
        "depuis": None,
        "json": False,
    }
    return argparse.Namespace(**{**defauts, **champs})


def sortie_a_allure(
    v_kmh: float,
    puissance_w: float,
    *,
    duree_s: int = 3000,
    lat: float = 0.0,
    pente: float = 0.0,
    nom: str = "sortie fabriquée",
    arret_a_s: int | None = None,
    duree_arret_s: int = 40,
    virage_a_s: int | None = None,
) -> Activite:
    """Une sortie plein est à vitesse et puissance **imposées**, pas déduites.

    C'est l'inverse de `sortie_synthetique` : ici on ne veut pas que le modèle
    décide de la vitesse, on veut savoir exactement quelle moyenne la
    comparaison doit retrouver.

    `arret_a_s` pose un arrêt complet (vitesse nulle, puissance nulle, position
    figée) : la série doit y être coupée. `virage_a_s` fait tourner la route de
    l'est vers le nord : la série doit y être coupée aussi.
    """
    v = v_kmh / 3.6
    points: list[Point] = []
    distance = 0.0
    est = 0.0  # mètres parcourus vers l'est
    nord = 0.0  # mètres parcourus vers le nord
    seconde = 0
    for s in range(duree_s):
        arrete = arret_a_s is not None and arret_a_s <= s < arret_a_s + duree_arret_s
        pas = 0.0 if arrete else v
        if virage_a_s is not None and s >= virage_a_s:
            nord += pas
        else:
            est += pas
        distance += pas
        points.append(
            Point(
                t=DEPART + timedelta(seconds=seconde),
                lat=lat + nord * METRE_EN_DEGRE,
                lon=est * METRE_EN_DEGRE,
                alt_m=100.0 + distance * pente,
                dist_m=distance,
                vitesse_ms=pas,
                puissance_w=0.0 if arrete else puissance_w,
            )
        )
        seconde += 1
    return Activite(
        source="tcx",
        fichier=None,
        debut=DEPART,
        duree_s=float(duree_s - 1),
        duree_mouvement_s=float(duree_s - 1),
        distance_m=points[-1].dist_m,
        denivele_m=max(0.0, points[-1].dist_m * pente),
        puissance_moy_w=puissance_w,
        puissance_np_w=puissance_w,
        sport="cycling",
        appareil=None,
        points=points,
        meta={"nom": nom},
    )


def series(activite, **options) -> list[Serie]:
    defauts = {"zone_w": ZONE_TEST, "ftp_w": FTP_DE_TEST}
    return series_droites(activite, **{**defauts, **options})


# --- découpe d'une sortie en séries -------------------------------------------


def test_une_ligne_droite_plate_donne_une_seule_serie():
    trouvees = series(sortie_a_allure(30.0, 170.0, duree_s=2400))
    assert len(trouvees) == 1
    assert trouvees[0].v_kmh == pytest.approx(30.0, abs=0.2)
    assert trouvees[0].puissance_w == pytest.approx(170.0, abs=0.5)
    assert trouvees[0].longueur_m == pytest.approx(2400 * 30 / 3.6, rel=0.02)


def test_un_arret_coupe_la_serie_en_deux():
    """Un feu rouge au milieu : deux séries, pas une seule à cheval sur l'arrêt."""
    coupee = sortie_a_allure(30.0, 170.0, duree_s=2400, arret_a_s=1200)
    trouvees = series(coupee)
    assert len(trouvees) == 2
    assert all(s.v_kmh == pytest.approx(30.0, abs=0.3) for s in trouvees)
    # Sans l'arrêt, la même sortie ne fait qu'une série : c'est bien lui qui coupe.
    assert len(series(sortie_a_allure(30.0, 170.0, duree_s=2400))) == 1


def test_le_filtre_de_cap_est_desactive_par_defaut():
    """Un virage à 90° ne coupe rien tant que `--cap-max` n'est pas posé."""
    tournante = sortie_a_allure(30.0, 170.0, duree_s=2400, virage_a_s=1200)
    assert len(series(tournante)) == 1


def test_un_virage_coupe_la_serie_quand_le_cap_est_filtre():
    """La route tourne de l'est vers le nord : l'écart de cap dépasse 15°."""
    tournante = sortie_a_allure(30.0, 170.0, duree_s=2400, virage_a_s=1200)
    assert len(series(tournante, cap_max_deg=CAP_MAX_DEG_SUGGERE)) == 2
    # La même sortie sans virage n'est pas coupée par le filtre : c'est bien lui.
    assert len(series(sortie_a_allure(30.0, 170.0, duree_s=2400), cap_max_deg=CAP_MAX_DEG_SUGGERE)) == 1


def test_une_pente_trop_forte_exclut_tout():
    """À 3 %, aucun tronçon n'est plat : aucune série."""
    raide = sortie_a_allure(30.0, 170.0, duree_s=2400, pente=0.03)
    assert series(raide, pente_max=PENTE_MAX_DEFAUT) == []
    # La même sortie, avec un plafond de pente relevé, redevient comparable.
    assert series(raide, pente_max=0.05)


def test_hors_de_la_zone_de_puissance_aucune_serie():
    """220 W : au-dessus de Z2 pour une FTP de 258 W."""
    assert series(sortie_a_allure(30.0, 220.0, duree_s=2400)) == []
    assert series(sortie_a_allure(30.0, 100.0, duree_s=2400)) == []


def test_une_serie_trop_courte_est_ecartee():
    courte = sortie_a_allure(30.0, 170.0, duree_s=90)  # 750 m
    assert len(series(courte, longueur_min_m=500.0)) == 1
    assert series(courte, longueur_min_m=2000.0) == []


def test_sans_puissance_aucune_serie():
    muette = sortie_a_allure(30.0, 170.0, duree_s=2400)
    for point in muette.points:
        point.puissance_w = None
    assert series(muette) == []


def test_la_serie_porte_les_mailles_qu_elle_traverse():
    trouvee = series(sortie_a_allure(30.0, 170.0, duree_s=2400))[0]
    assert len(trouvee.mailles) > 10
    assert all(isinstance(cle, tuple) and len(cle) == 2 for cle in trouvee.mailles)


# --- régression et bandes -----------------------------------------------------


def test_bornes_bandes_decoupe_la_zone_en_trois():
    bandes = bornes_bandes((150.0, 180.0))
    assert bandes == [(150.0, 160.0), (160.0, 170.0), (170.0, 180.0)]


def test_la_regression_retrouve_la_droite_qui_a_servi():
    droites = [
        Serie(v_kmh=28.0 + 0.05 * (p - 169.0), puissance_w=float(p), longueur_m=1000.0 + p)
        for p in range(150, 195, 5)
    ]
    regression = regresser(droites)
    assert regression is not None
    assert regression.pente_kmh_par_w == pytest.approx(0.05, abs=1e-6)
    assert regression.vitesse_kmh(169.0) == pytest.approx(28.0, abs=1e-6)


def test_la_regression_pese_les_series_par_leur_longueur():
    """Une série de 10 km tire la droite bien plus qu'une de 500 m."""
    lourdes = [
        Serie(v_kmh=30.0, puissance_w=float(p), longueur_m=10_000.0) for p in range(160, 180, 2)
    ]
    aberrante = [Serie(v_kmh=5.0, puissance_w=170.0, longueur_m=500.0)]
    regression = regresser(lourdes + aberrante)
    assert regression is not None
    assert regression.vitesse_kmh(170.0) == pytest.approx(30.0, abs=0.3)


def test_pas_de_regression_sur_trop_peu_de_series():
    maigre = [
        Serie(v_kmh=30.0, puissance_w=float(150 + i), longueur_m=1000.0)
        for i in range(SERIES_MIN_REGRESSION - 1)
    ]
    assert regresser(maigre) is None


def test_pas_de_regression_si_toutes_les_series_ont_la_meme_puissance():
    plates = [Serie(v_kmh=30.0 + i, puissance_w=170.0, longueur_m=1000.0) for i in range(10)]
    assert regresser(plates) is None


# --- comparaison de deux vélos ------------------------------------------------


def jeu_de_series(vitesse_au_milieu: float, pente: float = 0.05) -> list[Serie]:
    """Neuf séries exactement alignées sur `v = vitesse_au_milieu + pente·(P − 169)`."""
    return [
        Serie(
            v_kmh=vitesse_au_milieu + pente * (p - 169.0),
            puissance_w=float(p),
            longueur_m=2000.0,
            mailles=frozenset({(p, p)}),
        )
        for p in range(150, 195, 5)
    ]


def test_l_ecart_est_lu_au_milieu_de_la_zone_et_converti_en_watts():
    resultat = comparer(
        {"RCR": jeu_de_series(28.0), "BMC": jeu_de_series(30.5)},
        velos=("RCR", "BMC"),
        zone_w=(144.0, 194.0),
    )
    assert resultat.puissance_milieu_w == pytest.approx(169.0)
    assert resultat.vitesse_lue("RCR") == pytest.approx(28.0, abs=0.01)
    assert resultat.vitesse_lue("BMC") == pytest.approx(30.5, abs=0.01)
    assert resultat.ecart_kmh == pytest.approx(2.5, abs=0.01)
    # Loi en v³ : 3 × 169 × 2,5 / 28,0 = 45,3 W.
    assert resultat.ecart_w_v3 == pytest.approx(3 * 169.0 * 2.5 / 28.0, abs=0.5)
    # Sans calibration passée, pas de seconde conversion : rien n'est inventé.
    assert resultat.ecart_w_modele is None


def test_la_conversion_par_le_modele_se_fait_avec_la_calibration_du_premier_velo():
    parametres = Parametres(masse_totale_kg=91.0, cda_m2=0.30, crr=0.005)
    resultat = comparer(
        {"RCR": jeu_de_series(28.0), "BMC": jeu_de_series(30.5)},
        velos=("RCR", "BMC"),
        zone_w=(144.0, 194.0),
        parametres_reference=parametres,
    )
    attendu = puissance_requise(30.5 / 3.6, 0.0, 0.0, parametres) - puissance_requise(
        28.0 / 3.6, 0.0, 0.0, parametres
    )
    assert resultat.ecart_w_modele == pytest.approx(attendu, abs=0.01)
    # Les deux conversions se rejoignent — mais chacune sur SA puissance : la loi
    # en v³ part de la puissance mesurée (169 W), le modèle de celle qu'il
    # calcule lui-même à 28 km/h avec ces paramètres. C'est pourquoi les deux
    # chiffres diffèrent quand la calibration ne décrit pas le cycliste mesuré.
    p_modele = puissance_requise(28.0 / 3.6, 0.0, 0.0, parametres)
    assert resultat.ecart_w_modele == pytest.approx(3 * p_modele * 2.5 / 28.0, rel=0.25)


def test_les_bandes_separent_les_puissances():
    resultat = comparer(
        {"RCR": jeu_de_series(28.0), "BMC": jeu_de_series(30.5)},
        velos=("RCR", "BMC"),
        zone_w=(144.0, 194.0),
    )
    assert len(resultat.bandes) == 3
    basse, milieu, haute = resultat.bandes
    assert basse.vitesses["RCR"] < milieu.vitesses["RCR"] < haute.vitesses["RCR"]
    assert sum(b.n["RCR"] for b in resultat.bandes) == len(jeu_de_series(28.0))
    assert all(b.vitesses["BMC"] > b.vitesses["RCR"] for b in resultat.bandes)


def test_les_mailles_communes_informent_mais_ne_filtrent_pas():
    """Deux vélos qui n'ont aucune route en commun sont quand même comparés."""
    ailleurs = [
        Serie(s.v_kmh, s.puissance_w, s.longueur_m, frozenset({(9999, 9999)}))
        for s in jeu_de_series(30.5)
    ]
    resultat = comparer(
        {"RCR": jeu_de_series(28.0), "BMC": ailleurs},
        velos=("RCR", "BMC"),
        zone_w=(144.0, 194.0),
    )
    assert resultat.mailles_communes == 0
    assert resultat.ecart_kmh == pytest.approx(2.5, abs=0.01)
    assert resultat.par_velo["BMC"].n_series == len(jeu_de_series(30.5))


def test_sans_serie_aucun_ecart():
    resultat = comparer(
        {"RCR": jeu_de_series(28.0), "BMC": []},
        velos=("RCR", "BMC"),
        zone_w=(144.0, 194.0),
    )
    assert resultat.par_velo["BMC"].n_series == 0
    assert resultat.ecart_kmh is None
    assert resultat.ecart_w_v3 is None
    assert resultat.ecart_w_modele is None


# --- la commande de bout en bout ----------------------------------------------

#: Le jeu fabriqué : deux vélos sur la même droite, 2,5 km/h d'écart à
#: puissance égale, une pente de 0,05 km/h par watt — donc 50 W à vitesse
#: égale, exactement.
PUISSANCES = [150.0, 155.0, 160.0, 165.0, 170.0, 175.0, 180.0, 185.0, 190.0]
PENTE_FABRIQUEE = 0.05
V_RCR_AU_MILIEU = 28.0
V_BMC_AU_MILIEU = 30.5


def _vitesse(au_milieu: float, puissance_w: float) -> float:
    return au_milieu + PENTE_FABRIQUEE * (puissance_w - 169.0)


def cache_de_deux_velos(dossier: Path) -> Cache:
    """Deux vélos, mêmes puissances, vitesses différentes — et un feu rouge à chaque sortie."""
    cache = Cache(dossier)
    plans = [
        ("CAPTEUR 0001", V_RCR_AU_MILIEU, "RCR", 1),
        ("CAPTEUR 0002", V_BMC_AU_MILIEU, "BMC", 2),
    ]
    for capteur, au_milieu, etiquette, mois in plans:
        for index, puissance in enumerate(PUISSANCES):
            jour = date(2026, mois, index + 1)
            activite = sortie_a_allure(
                _vitesse(au_milieu, puissance),
                puissance,
                duree_s=3000,  # ≥ 20 km, sinon la sortie est écartée comme trop courte
                arret_a_s=1500,
                nom=f"{etiquette} {jour}",
            )
            cache.ajouter(
                _en_tcx(activite, jour),
                source="intervals",
                id_externe=f"{etiquette}-{jour.isoformat()}",
                extension="tcx",
                meta={
                    "nom": f"{etiquette} du {jour}",
                    "power_meter": capteur,
                    "sport": "Ride",
                },
            )
    return cache


def test_comparer_de_bout_en_bout(tmp_path: Path, capsys):
    """Les 2,5 km/h fabriqués, et les 50 W qui leur correspondent, sont retrouvés."""
    cache_de_deux_velos(tmp_path / "cache")
    config = config_de_test(tmp_path / "cache", historique_depuis=date(2023, 12, 1))

    assert executer_comparer(args(), config) == 0
    texte = capsys.readouterr().out
    assert "Comparaison RCR / BMC" in texte
    assert "Mesure : BMC roule +2.5 km/h à puissance égale" in texte
    assert "ordre de grandeur (loi en v³) : ΔP ≈ 3·P·Δv/v" in texte
    assert "les watts en sont une conversion, pas une mesure" in texte
    assert "aucun filtre de cap" in texte
    # Le feu rouge coupe chaque sortie en deux séries.
    assert "  RCR " in texte and "  BMC " in texte
    assert "en commun (information" in texte


def test_comparer_en_json(tmp_path: Path, capsys):
    cache_de_deux_velos(tmp_path / "cache")
    config = config_de_test(tmp_path / "cache", historique_depuis=date(2023, 12, 1))

    assert executer_comparer(args(json=True), config) == 0
    charge = json.loads(capsys.readouterr().out)
    assert charge["velos"] == ["RCR", "BMC"]
    assert charge["modele_physique"] is False
    assert charge["zone_ftp"] == [0.56, 0.75]
    assert charge["zone_w"] == [pytest.approx(144.5, abs=0.1), pytest.approx(193.5, abs=0.1)]
    assert charge["velo"]["RCR"]["sorties"] == len(PUISSANCES)
    assert charge["velo"]["RCR"]["series"] == 2 * len(PUISSANCES)
    assert charge["velo"]["RCR"]["regression"]["pente_kmh_par_w"] == pytest.approx(
        PENTE_FABRIQUEE, abs=0.005
    )
    lue = charge["synthese"]["puissance_w"]
    assert charge["synthese"]["vitesse_kmh"]["RCR"] == pytest.approx(
        _vitesse(V_RCR_AU_MILIEU, lue), abs=0.2
    )
    assert charge["synthese"]["ecart_kmh"] == pytest.approx(2.5, abs=0.2)
    assert charge["synthese"]["ecart_w_v3"] == pytest.approx(3 * lue * 2.5 / 28.0, abs=5.0)
    assert charge["synthese"]["ecart_w_modele"] is None  # pas de calibration.json ici
    assert "3 × puissance_w" in charge["synthese"]["formules"]["ecart_w_v3"]
    assert charge["cap_max_deg"] is None
    assert len(charge["bandes"]) == 3
    assert charge["mailles_communes"] > 0  # les deux vélos roulent sur la même droite


def test_la_zone_peut_etre_deplacee(tmp_path: Path, capsys):
    """Hors de la zone demandée, il ne reste rien : la zone est bien un filtre."""
    cache_de_deux_velos(tmp_path / "cache")
    config = config_de_test(tmp_path / "cache", historique_depuis=date(2023, 12, 1))
    with pytest.raises(ErreurUtilisateur, match="aucune série"):
        executer_comparer(args(zone=[0.85, 0.95]), config)


def test_comparer_refuse_deux_fois_le_meme_velo(tmp_path: Path):
    Cache(tmp_path / "cache")
    config = config_de_test(tmp_path / "cache")
    with pytest.raises(ErreurUtilisateur, match="même vélo"):
        executer_comparer(args(velos=["RCR", "rcr"]), config)


def test_comparer_sans_sortie(tmp_path: Path):
    Cache(tmp_path / "cache")
    config = config_de_test(tmp_path / "cache")
    with pytest.raises(ErreurUtilisateur, match="aucune série"):
        executer_comparer(args(), config)


def test_comparer_refuse_sans_ftp(tmp_path: Path):
    """Point 5 (T5) : `zone_w` se construit en multipliant `zone_ftp * ftp_w` —
    `series_droites` garde `ftp_w: float = 250.0` non optionnel, ce n'est pas
    à elle de deviner. Le refus se fait en amont, avec un message qui nomme
    la FTP plutôt qu'un `TypeError` sur la multiplication par `None`."""
    Cache(tmp_path / "cache")
    config = config_de_test(tmp_path / "cache", cycliste={"masse_kg": 91})
    assert config.cycliste.ftp_w is None
    with pytest.raises(ErreurUtilisateur, match="FTP"):
        executer_comparer(args(), config)


@pytest.mark.parametrize(
    ("champs", "message"),
    [
        ({"pente_max": -1.0}, "pente-max"),
        ({"cap_max": -5.0}, "cap-max"),
        ({"longueur_min": 50.0}, "longueur-min"),
        ({"zone": [0.75, 0.56]}, "zone"),
        ({"zone": [0.56]}, "zone"),
    ],
)
def test_options_absurdes_refusees(tmp_path: Path, champs, message):
    Cache(tmp_path / "cache")
    config = config_de_test(tmp_path / "cache")
    with pytest.raises(ErreurUtilisateur, match=message):
        executer_comparer(args(**champs), config)


def test_les_defauts_sont_ceux_du_schema_valide():
    """Le schéma validé le 13/09 : plats, ≥ 500 m, sans arrêt ni relance, Z2 — pas de cap."""
    assert PENTE_MAX_DEFAUT == 0.008
    assert LONGUEUR_MIN_M_DEFAUT == 500.0
    assert CAP_MAX_DEG_SUGGERE == 15.0  # valeur de l'option, pas un défaut


def test_une_serie_pile_sur_la_borne_haute_tombe_dans_la_derniere_bande():
    """La zone est fermée des deux côtés : 194 W est admissible, il lui faut une bande."""
    limite = [Serie(v_kmh=32.0, puissance_w=194.0, longueur_m=1000.0)]
    resultat = comparer(
        {"RCR": limite, "BMC": []}, velos=("RCR", "BMC"), zone_w=(144.0, 194.0)
    )
    assert resultat.bandes[-1].n["RCR"] == 1
    assert resultat.bandes[-1].vitesses["RCR"] == pytest.approx(32.0)
