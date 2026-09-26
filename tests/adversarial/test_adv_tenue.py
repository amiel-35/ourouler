"""L4.3 — la tenue conseillée, mise à l'épreuve.

Cible : contrat du sprint 4 §3 et §5, et la règle du 13/09 : **la base se
décide sur le départ**, parce que c'est là qu'on a froid ; le reste du tracé
ne produit que des « prévoir d'enlever », « emporter », « garder ».

Ce qui est traqué :

* les **bornes exactes** : `bornes_c = (3, 9, 15, 22, 30)` se lit « très froid
  < 3 », donc 3,0 °C n'est plus « très froid ». Un `<=` au lieu d'un `<`
  décale toute la grille d'une catégorie, sans jamais lever ;
* les **valeurs absentes** : aucun échantillon, ressenti `None`, pluie `None`.
  Une météo dont l'horizon de prévision s'arrête au milieu du tracé est le cas
  normal, pas le cas rare ;
* la **règle du départ** : deux sorties qui commencent pareil et divergent
  ensuite doivent partir avec la même base. Un module qui décide la base sur
  la moyenne du tracé passe tous les autres tests ;
* le **vent seul** : au-delà de `vent_veste_kmh`, la veste se déclenche sans
  une goutte de pluie ;
* les **paramètres de configuration**, testables sans attendre le lot :
  bornes non croissantes, bornes en chaîne, vent négatif.
"""

from __future__ import annotations

import dataclasses
from typing import Any

import fabriques_seance
import pytest
from outils import robuste, sans_accents, verifier_json

from ourouler import config as module_config
from ourouler.boucle import meteo_trace
from ourouler.config import ParametresSeance, ParametresTenue
from ourouler.noyau.erreurs import ErreurConfig, ErreurUtilisateur

MOTIF_ABSENT = "module attendu par le contrat L4.3 absent (ourouler.seance.tenue)"

ERREURS = (ErreurUtilisateur, ValueError)

DEFAUT = ParametresTenue()
#: Un ressenti franchement au milieu de chaque catégorie de `bornes_c`.
RESSENTIS_PAR_CATEGORIE = (-2.0, 6.0, 12.0, 18.0, 26.0, 34.0)


def _tenue() -> Any:
    return fabriques_seance.module("tenue", motif=MOTIF_ABSENT)


def _conseiller(meteo: Any, p: ParametresTenue = DEFAUT) -> Any:
    tenue = _tenue().conseiller(meteo, p)
    _verifier(tenue)
    return tenue


def _verifier(tenue: Any) -> None:
    for nom in ("categorie_temp", "categorie_humidite"):
        valeur = getattr(tenue, nom)
        assert isinstance(valeur, str) and valeur.strip(), f"Tenue.{nom} : catégorie lisible attendue"
    for nom in ("base", "a_emporter", "a_enlever", "motifs"):
        fabriques_seance.liste_de_chaines(getattr(tenue, nom), f"Tenue.{nom}")
    if tenue.a_emporter or tenue.a_enlever:
        assert tenue.motifs, (
            "un conseil sans motif n'est pas actionnable : le contrat demande des motifs lisibles"
        )
    verifier_json(dataclasses.asdict(tenue), "Tenue")


def _meteo(**kwargs: Any) -> Any:
    return fabriques_seance.meteo_uniforme(meteo_trace, **kwargs)


def _contient(morceaux: Any, mot: str) -> bool:
    cible = sans_accents(mot).casefold()
    return any(cible in sans_accents(m).casefold() for m in morceaux)


# --- entrées vides ou incomplètes ---------------------------------------------


def test_une_meteo_sans_echantillon_ne_casse_pas():
    """Tracé hors horizon de prévision : aucun échantillon exploitable."""
    mod = _tenue()
    meteo = fabriques_seance.meteo_fictive(meteo_trace, [], confiance="aucune")
    tenue, erreur = robuste(
        lambda: mod.conseiller(meteo, DEFAUT), quoi="conseiller sans échantillon", erreurs_acceptees=ERREURS
    )
    if erreur is None:
        _verifier(tenue)


@pytest.mark.parametrize(
    ("ressenti", "pluie", "vent"),
    [(12.0, None, 10.0), (None, None, None)],
    ids=["sans_pluie", "rien_du_tout"],
)
def test_des_valeurs_absentes_ne_fabriquent_pas_de_conseil_faux(ressenti, pluie, vent):
    mod = _tenue()
    meteo = _meteo(ressenti=ressenti, pluie=pluie, vent=vent)
    tenue, erreur = robuste(
        lambda: mod.conseiller(meteo, DEFAUT),
        quoi=f"conseiller(ressenti={ressenti}, pluie={pluie}, vent={vent})",
        erreurs_acceptees=ERREURS,
    )
    if erreur is None:
        _verifier(tenue)


def test_un_seul_echantillon_suffit_a_habiller_le_cycliste():
    echantillons = [fabriques_seance.echantillon(meteo_trace, 0.0, ressenti=6.0)]
    meteo = fabriques_seance.meteo_fictive(meteo_trace, echantillons)
    tenue = _conseiller(meteo)
    assert tenue.base, "avec un échantillon au départ, la base doit être décidée"
    assert tenue.a_enlever == [], "rien à enlever quand rien ne change : il n'y a qu'un point"


def test_des_echantillons_en_desordre_ne_levent_pas():
    mod = _tenue()
    echantillons = [
        fabriques_seance.echantillon(meteo_trace, 20_000.0, minute=40.0, ressenti=18.0),
        fabriques_seance.echantillon(meteo_trace, 0.0, minute=0.0, ressenti=6.0),
    ]
    meteo = fabriques_seance.meteo_fictive(meteo_trace, echantillons)
    tenue, erreur = robuste(
        lambda: mod.conseiller(meteo, DEFAUT), quoi="échantillons en désordre", erreurs_acceptees=ERREURS
    )
    if erreur is None:
        _verifier(tenue)


# --- les catégories et leurs bornes --------------------------------------------


def test_chaque_tranche_de_temperature_a_sa_categorie():
    categories = [_conseiller(_meteo(ressenti=r)).categorie_temp for r in RESSENTIS_PAR_CATEGORIE]
    assert len(set(categories)) == len(RESSENTIS_PAR_CATEGORIE), (
        f"six tranches de `bornes_c`, {len(set(categories))} catégories distinctes : {categories}"
    )


@pytest.mark.parametrize("borne", (DEFAUT.bornes_c[0], DEFAUT.bornes_c[2], DEFAUT.bornes_c[-1]))
def test_une_borne_de_temperature_appartient_a_la_tranche_du_dessus(borne):
    """`bornes_c = (3, …)` se lit « très froid **<** 3 » : 3,0 est déjà la tranche suivante."""
    exacte = _conseiller(_meteo(ressenti=float(borne))).categorie_temp
    dessus = _conseiller(_meteo(ressenti=float(borne) + 0.5)).categorie_temp
    dessous = _conseiller(_meteo(ressenti=float(borne) - 0.5)).categorie_temp
    assert exacte == dessus, f"ressenti {borne} classé {exacte!r}, {borne + 0.5} classé {dessus!r}"
    assert exacte != dessous, f"la borne {borne} ne sépare rien : {dessous!r} des deux côtés"


@pytest.mark.parametrize("borne", DEFAUT.bornes_pluie_mmh)
def test_une_borne_de_pluie_appartient_a_la_tranche_du_dessus(borne):
    exacte = _conseiller(_meteo(pluie=float(borne))).categorie_humidite
    dessus = _conseiller(_meteo(pluie=float(borne) + 0.05)).categorie_humidite
    dessous = _conseiller(_meteo(pluie=max(float(borne) - 0.05, 0.0))).categorie_humidite
    assert exacte == dessus and exacte != dessous, (
        f"pluie {borne} mm/h : {dessous!r} en dessous, {exacte!r} à la borne, {dessus!r} au-dessus"
    )


def test_les_bornes_viennent_de_la_configuration():
    """Les seuils sont réglables à l'usage (Q3) : le module ne doit pas les figer."""
    p = ParametresTenue(bornes_c=(10.0,), bornes_pluie_mmh=(5.0,), vent_veste_kmh=99.0)
    froid = _conseiller(_meteo(ressenti=5.0), p).categorie_temp
    chaud = _conseiller(_meteo(ressenti=25.0), p).categorie_temp
    assert froid != chaud, "une borne unique à 10 °C doit séparer 5 °C et 25 °C"
    assert _conseiller(_meteo(ressenti=12.0), p).categorie_temp == chaud, (
        "12 °C et 25 °C sont du même côté de la seule borne : les bornes par défaut ont été réutilisées"
    )


# --- la base se décide sur le départ --------------------------------------------


def test_la_base_se_decide_sur_le_depart():
    """Règle du 13/09 : « la base se décide sur le départ, parce que c'est là qu'on a froid »."""
    depart = fabriques_seance.echantillon(meteo_trace, 0.0, minute=0.0, ressenti=4.0)
    froide = fabriques_seance.meteo_fictive(
        meteo_trace,
        [depart, fabriques_seance.echantillon(meteo_trace, 20_000.0, minute=45.0, ressenti=4.0)],
    )
    rechauffee = fabriques_seance.meteo_fictive(
        meteo_trace,
        [depart, fabriques_seance.echantillon(meteo_trace, 20_000.0, minute=45.0, ressenti=24.0)],
    )
    a, b = _conseiller(froide), _conseiller(rechauffee)
    assert a.base == b.base, (
        f"base {a.base} contre {b.base} : la base a été décidée sur la moyenne du tracé, "
        "pas sur le départ"
    )
    assert b.a_enlever, "un ressenti qui monte de 20 °C doit produire un « prévoir d'enlever »"
    assert not a.a_enlever, "rien ne change sur le tracé : rien à enlever"


def test_un_ressenti_qui_baisse_ne_fait_pas_enlever():
    depart = fabriques_seance.echantillon(meteo_trace, 0.0, minute=0.0, ressenti=20.0)
    refroidie = fabriques_seance.meteo_fictive(
        meteo_trace,
        [depart, fabriques_seance.echantillon(meteo_trace, 20_000.0, minute=45.0, ressenti=2.0)],
    )
    tenue = _conseiller(refroidie)
    assert not tenue.a_enlever, f"le ressenti baisse de 18 °C et le conseil est d'enlever {tenue.a_enlever}"
    assert tenue.motifs, "un refroidissement de 18 °C en cours de route doit se dire"


# --- la veste -------------------------------------------------------------------


def test_la_pluie_annoncee_plus_loin_fait_emporter_la_veste():
    sec = fabriques_seance.echantillon(meteo_trace, 0.0, minute=0.0, pluie=0.0)
    averse = fabriques_seance.echantillon(meteo_trace, 20_000.0, minute=45.0, pluie=2.0)
    tenue = _conseiller(fabriques_seance.meteo_fictive(meteo_trace, [sec, averse]))
    assert _contient(tenue.a_emporter + tenue.motifs, "veste"), (
        f"2 mm/h annoncés au km 20 et rien à emporter : {tenue.a_emporter}, motifs {tenue.motifs}"
    )


@pytest.mark.parametrize("vent", [35.0], ids=["au_dessus_du_seuil"])
def test_le_vent_seul_declenche_la_veste(vent):
    """« Le vent entre dans le ressenti et déclenche seul la veste au-delà de `vent_veste_kmh`. »"""
    tenue = _conseiller(_meteo(vent=vent, pluie=0.0, ressenti=14.0))
    assert _contient(tenue.a_emporter + tenue.base + tenue.motifs, "veste"), (
        f"{vent} km/h de vent pour un seuil à {DEFAUT.vent_veste_kmh} km/h, et aucune veste : "
        f"base {tenue.base}, à emporter {tenue.a_emporter}"
    )


def test_un_vent_faible_ne_declenche_pas_la_veste_par_lui_meme():
    tenue = _conseiller(_meteo(vent=8.0, pluie=0.0, ressenti=20.0))
    assert not _contient(tenue.a_emporter, "veste"), (
        f"8 km/h de vent, 20 °C ressentis, temps sec, et pourtant : {tenue.a_emporter}"
    )


# --- les paramètres de configuration (testables sans le lot) ---------------------


def test_les_valeurs_par_defaut_sont_celles_du_contrat(ecrire_config):
    config = module_config.charger(ecrire_config())
    assert config.tenue.bornes_c == (3.0, 9.0, 15.0, 22.0, 30.0)
    assert config.tenue.bornes_pluie_mmh == (0.2, 0.5, 1.0)
    assert config.tenue.vent_veste_kmh == 30.0
    assert config.seance.elasticite_z2_max == 0.20 and config.seance.elasticite_z2_min == -0.05
    assert config.seance.elasticite_calme_max == 1.5 and config.seance.elasticite_calme_min == -0.05
    assert config.seance.demi_tour_penalite == 1.0


@pytest.mark.parametrize(
    "corps",
    [
        '[tenue]\nbornes_c = [9.0, 3.0]\n',
        '[tenue]\nvent_veste_kmh = -5.0\n',
        '[seance]\nelasticite_z2_max = 2.0\n',
        '[seance]\nelasticite_calme_max = 50.0\n',
        '[seance]\nelasticite_calme_min = 0.5\n',
        '[seance]\ndemi_tour_penalite = -1.0\n',
    ],
    ids=[
        "bornes_decroissantes",
        "vent_negatif",
        "elasticite_demesuree",
        "calme_demesure",
        "calme_min_positif",
        "penalite_negative",
    ],
)
def test_une_configuration_de_seance_ou_de_tenue_invalide_est_refusee(ecrire_config, corps):
    with pytest.raises(ErreurConfig):
        module_config.charger(ecrire_config(corps))


def test_les_parametres_de_seance_disent_la_decision_du_13_09():
    """Une élasticité par défaut qui encadre zéro : la Z2 peut s'allonger ou se raccourcir."""
    p = ParametresSeance()
    assert p.elasticite_z2_min <= 0.0 <= p.elasticite_z2_max
    # Q14 (13/09) : le retour au calme absorbe, il n'est pas un levier — sa
    # fenêtre s'ouvre largement vers le haut, et pas vers le bas.
    assert p.elasticite_calme_min <= 0.0 <= p.elasticite_calme_max
    assert p.elasticite_calme_max > p.elasticite_z2_max
    assert p.elasticite_calme_min == p.elasticite_z2_min
    assert p.demi_tour_penalite >= 0.0, "un demi-tour ne peut pas améliorer une note"
