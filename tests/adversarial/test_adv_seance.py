"""L4.1 — la séance du jour, mise à l'épreuve.

Cible : contrat du sprint 4 §1 et §5. Le document Intervals est une entrée
externe : il vient d'un compte que le mainteneur ne contrôle pas entièrement
(séances poussées par son entraîneur via iDOSport). Tout y est optionnel.

Ce qui est traqué :

* l'**aplatissement** : `doc["steps"]` est une liste de groupes, et rien
  n'interdit un groupe de groupes. Trois niveaux d'imbrication doivent donner
  autant d'étapes que le produit des `reps` ;
* les **répétitions absurdes** : `reps` à 0, négatif, ou assez grand pour
  faire exploser la mémoire ;
* la **puissance absente ou mal unitée** : ni `power` ni `hr`, `units`
  inconnue, `%ftp` sans FTP. Le piège muet est la confusion fraction /
  pourcentage : `0.8 × 200 = 160 W` contre `80 × 200 = 16 000 W` ;
* l'**élasticité**, décision produit du 13/09 : seules la première étape si
  elle est un échauffement et la dernière si elle est un retour au calme.
  Toutes les récupérations sont fixes, courtes comme longues. Un module qui
  marque élastique une récup de 45 min réécrit la prescription du coach ;
* la **cohérence de `duree_s`** avec la somme des étapes : c'est ce total qui
  sert ensuite au placement, une dérive s'y propage sans rien lever.
"""

from __future__ import annotations

import json
from datetime import date
from typing import Any

import fabriques
import fabriques4
import httpx
import pytest
from fabriques4 import FTP_TEST_W, JOUR, ZONES_PUISSANCE, appeler_depuis_workout, etape_doc, groupe
from outils import CLE_BIDON, verifier_json

from ourouler.noyau.erreurs import ErreurUtilisateur

MOTIF_MODELE = "module attendu par le contrat L4.1 absent (ourouler.noyau.seance)"
MOTIF_INTERVALS = "module attendu par le contrat L4.1 absent (ourouler.seance.intervals)"

ERREURS = (ErreurUtilisateur, ValueError)

#: Types du contrat §1, réécrits ici plutôt que lus dans le module testé.
TYPES_CONTRAT = ("echauffement", "bloc", "recuperation", "calme")


def _modele() -> Any:
    return fabriques4.module("modele", motif=MOTIF_MODELE)


def _intervals() -> Any:
    return fabriques4.module("intervals", motif=MOTIF_INTERVALS)


def _robuste(appel, *, quoi: str):
    from outils import robuste

    return robuste(appel, quoi=quoi, erreurs_acceptees=ERREURS)


def _verifier(seance: Any, *, quoi: str = "Seance") -> None:
    fabriques4.verifier_seance(seance, TYPES_CONTRAT, quoi=quoi)


# --- le modèle ---------------------------------------------------------------


def test_les_types_sont_ceux_du_contrat():
    assert tuple(_modele().TYPES) == TYPES_CONTRAT


def test_une_etape_est_immuable():
    """`Etape` est `frozen` : le placement ne doit pas pouvoir réécrire une durée."""
    mod = _modele()
    e = fabriques4.etape(mod, "bloc", 600.0, pmin=200.0, pmax=220.0)
    with pytest.raises(Exception):  # noqa: B017 — FrozenInstanceError dérive d'AttributeError
        e.duree_s = 1.0


@pytest.mark.parametrize(
    ("mini", "maxi", "attendu"),
    [(200.0, 220.0, 210.0), (200.0, 200.0, 200.0), (None, None, None)],
)
def test_la_puissance_cible_est_le_milieu_de_la_fourchette(mini, maxi, attendu):
    mod = _modele()
    e = fabriques4.etape(mod, "bloc", 600.0, pmin=mini, pmax=maxi)
    assert e.puissance_cible_w == attendu


def test_une_seance_sans_bloc_a_une_liste_de_blocs_vide():
    """« Vélo — Sortie EF 2h » : aucune contrainte de terrain, aucun bloc."""
    mod = _modele()
    s = fabriques4.seance(mod, [fabriques4.etape(mod, "echauffement", 7200.0, elastique=True)])
    assert s.blocs() == []


# --- documents hostiles ------------------------------------------------------


@pytest.mark.parametrize(
    "document",
    [
        {},
        {"steps": [None, 3]},
        {"steps": [{"reps": 2, "steps": None}]},
    ],
    ids=["vide", "steps_bruit", "groupe_sans_sous_etape"],
)
def test_un_document_malforme_ne_casse_pas(document):
    """Aucune de ces entrées ne doit remonter une KeyError ou un TypeError."""
    mod = _intervals()
    seance, erreur = _robuste(
        lambda: appeler_depuis_workout(mod, document), quoi=f"depuis_workout_doc({document!r})"
    )
    if erreur is None:
        _verifier(seance)


def test_la_seance_de_reference_est_developpee_telle_quelle():
    """« 4x8min Z4 » : 1 échauffement + 4×(bloc, récup) + 1 calme, dans l'ordre."""
    mod = _intervals()
    seance = appeler_depuis_workout(mod, fabriques4.doc_4x8())
    _verifier(seance)
    types = [e.type for e in seance.etapes]
    assert types == ["echauffement"] + ["bloc", "recuperation"] * 4 + ["calme"], (
        f"étapes développées attendues, reçu {types}"
    )
    assert seance.duree_s == pytest.approx(900.0 + 4 * (480.0 + 240.0) + 600.0)
    assert len(seance.blocs()) == 4
    assert seance.nom == "seance de test" and seance.jour == JOUR
    verifier_json(seance.meta, "Seance.meta")


def test_trois_niveaux_de_groupes_imbriques_sont_aplatis():
    """Rien dans le format n'interdit un groupe de groupes : 2 × 3 × 2 = 12 étapes."""
    mod = _intervals()
    feuille = groupe([etape_doc(60.0, ftp_pct=0.6)], reps=2)
    milieu = groupe([feuille], reps=3)
    document = fabriques4.doc([groupe([milieu], reps=2)])
    seance = appeler_depuis_workout(mod, document)
    _verifier(seance)
    assert len(seance.etapes) == 12, (
        f"12 étapes attendues (2×3×2), reçu {len(seance.etapes)} — les groupes imbriqués "
        "ne sont pas développés récursivement"
    )
    assert seance.duree_s == pytest.approx(720.0)


@pytest.mark.parametrize("reps", [0, -2], ids=["zero", "negatif"])
def test_un_groupe_a_repetitions_nulles_ou_negatives_ne_produit_rien(reps):
    """`reps=0` supprime le groupe ; `reps=-2` ne peut pas en produire moins que rien."""
    mod = _intervals()
    document = fabriques4.doc(
        [
            groupe([etape_doc(600.0, ftp_pct=0.6, warmup=True)]),
            groupe([etape_doc(480.0, ftp_pct=1.05)], reps=reps),
        ]
    )
    seance, erreur = _robuste(lambda: appeler_depuis_workout(mod, document), quoi=f"reps={reps}")
    if erreur is not None:
        return
    _verifier(seance)
    assert len(seance.blocs()) == 0, (
        f"un groupe à reps={reps} a produit {len(seance.blocs())} bloc(s) : "
        "une répétition non positive ne développe rien"
    )
    assert seance.duree_s == pytest.approx(600.0)


@pytest.mark.parametrize(
    ("reps", "cle"),
    [(100_000, "groupes_reps_bornees"), (2.9, "groupes_reps_tronquees")],
    ids=["borne", "tronque"],
)
def test_un_reps_borne_ou_tronque_se_compte_dans_meta(reps, cle):
    """S2 : `reps <= 0` était compté, `reps` borné ou tronqué ne l'était pas.

    `min(int(valeur), REPS_MAX)` ramenait `reps: 100000` à 500 sans rien écrire
    nulle part — une séance amputée de 99 500 répétitions est absurde, donc
    sans conséquence pratique. Mais `int(valeur)` tronque aussi `2.9` en `2`,
    et celui-là supprime un tour bien réel. Le principe du lot est que toute
    perte se compte.
    """
    mod = _intervals()
    document = fabriques4.doc(
        [
            groupe([etape_doc(600.0, ftp_pct=0.6, warmup=True)]),
            groupe([etape_doc(60.0, ftp_pct=1.05)], reps=reps),
        ]
    )
    seance, erreur = _robuste(lambda: appeler_depuis_workout(mod, document), quoi=f"reps={reps}")
    if erreur is not None:
        return
    _verifier(seance)
    assert seance.meta.get(cle), (
        f"reps={reps} a été ramené en silence : « {cle} » absent de meta {sorted(seance.meta)}"
    )


@pytest.mark.parametrize(
    "consigne",
    [
        {"units": "%ftp", "value": -0.5},
        {"units": "%ftp", "value": -80},
        {"units": "watts", "value": -200},
        {"units": "%ftp", "start": -10, "end": 90},
    ],
    ids=["fraction", "pourcentage", "watts", "rampe"],
)
def test_une_puissance_negative_ne_fait_pas_lever_depuis_workout_doc(consigne):
    """`depuis_workout_doc` promet de ne **jamais** lever sur un document mal formé.

    Mesuré : `{"units": "%ftp", "value": -0.5}` donnait −125 W et `Etape`
    levait `ErreurUtilisateur`, en contradiction avec son propre docstring.
    Une puissance négative n'est pas une consigne de freinage, c'est une
    consigne illisible : l'étape est gardée — elle occupe de la route — sans
    puissance, et la perte se compte dans `meta`.
    """
    mod = _intervals()
    document = fabriques4.doc([groupe([{"duration": 600.0, "power": consigne}])])
    seance = appeler_depuis_workout(mod, document)  # ne doit pas lever
    _verifier(seance)
    [lue] = seance.etapes
    assert lue.puissance_min_w is None and lue.puissance_max_w is None, (
        f"puissance {lue.puissance_min_w}-{lue.puissance_max_w} W tirée de {consigne}"
    )
    assert seance.meta.get("etapes_puissance_negative") == 1, sorted(seance.meta)


def test_une_consigne_de_puissance_vide_ne_masque_pas_une_frequence_cardiaque_valide():
    """S3 : `power: {}` s'arrêtait au premier champ présent et perdait le `hr`.

    Une consigne dont l'unité est inconnue mais qui porte des bornes reste une
    consigne — la source a voulu dire quelque chose. Un dictionnaire **sans
    aucune borne** ne dit rien du tout et ne doit pas manger le `hr` qui suit.
    """
    mod = _intervals()
    etape = {"duration": 600.0, "power": {}, "hr": {"units": "hr_zone", "value": 4}}
    document = fabriques4.doc([groupe([etape])])
    seance, erreur = _robuste(
        lambda: appeler_depuis_workout(mod, document), quoi="power vide + hr valide"
    )
    if erreur is not None:
        return
    _verifier(seance)
    [lue] = seance.etapes
    assert lue.puissance_min_w is not None and lue.puissance_max_w is not None, (
        "la consigne de fréquence cardiaque a été perdue derrière un `power: {}` vide"
    )
    assert 0.0 < lue.puissance_min_w <= lue.puissance_max_w <= 5 * FTP_TEST_W


@pytest.mark.parametrize(
    "duree", [None, "abc"], ids=["absente", "chaine"]
)
def test_une_duree_absurde_ne_fabrique_pas_de_seance_incoherente(duree):
    mod = _intervals()
    document = fabriques4.doc(
        [groupe([etape_doc(duree, ftp_pct=0.6), etape_doc(600.0, ftp_pct=1.0)])]
    )
    seance, erreur = _robuste(lambda: appeler_depuis_workout(mod, document), quoi=f"duration={duree!r}")
    if erreur is None:
        _verifier(seance)


def test_une_etape_sans_puissance_ni_frequence_cardiaque_reste_sans_puissance():
    """Ni `power` ni `hr` : la fourchette est inconnue, pas égale à zéro."""
    mod = _intervals()
    document = fabriques4.doc([groupe([etape_doc(600.0, text="rouler")])])
    seance, erreur = _robuste(lambda: appeler_depuis_workout(mod, document), quoi="étape sans puissance")
    if erreur is not None:
        return
    _verifier(seance)
    for i, e in enumerate(seance.etapes):
        assert e.puissance_min_w is None and e.puissance_max_w is None, (
            f"etapes[{i}] : puissance {e.puissance_min_w}-{e.puissance_max_w} W inventée "
            "alors que le document n'en donne aucune"
        )
        assert e.puissance_cible_w is None


@pytest.mark.parametrize("units", ["kj", "rpe", "", "%FTP_BIS"], ids=["kj", "rpe", "vide", "voisin"])
def test_une_unite_inconnue_ne_fabrique_pas_de_puissance_fantaisiste(units):
    """Le module le dit : « une unité absente ou inconnue ne donne aucune puissance ».

    L'assertion d'origine se réduisait à `_verifier(seance)`, dont le contrôle
    de puissance tolère tout jusqu'à 5 × FTP : une unité inconnue traduite en
    un wattage plausible — `{"units": "kj", "value": 250}` lu comme 250 W —
    passait donc malgré le nom du test. On mesure maintenant ce que le nom
    annonce.
    """
    mod = _intervals()
    # Construit à la main : `etape_doc(units="")` retomberait sur « watts »,
    # et le test ne mesurerait alors que sa propre fabrique.
    document = fabriques4.doc([groupe([{"duration": 600.0, "power": {"units": units, "value": 250}}])])
    seance, erreur = _robuste(lambda: appeler_depuis_workout(mod, document), quoi=f"units={units!r}")
    if erreur is not None:
        return
    _verifier(seance)
    [lue] = seance.etapes
    assert lue.puissance_min_w is None and lue.puissance_max_w is None, (
        f"units={units!r} a donné {lue.puissance_min_w}-{lue.puissance_max_w} W : "
        "une unité inconnue ne se devine pas, elle se dit inconnue"
    )
    assert lue.puissance_cible_w is None


def test_un_pourcentage_de_ftp_sans_ftp_ne_devient_pas_zero_watt():
    """FTP inconnu : la puissance reste inconnue. Zéro watt serait un mensonge."""
    mod = _intervals()
    document = fabriques4.doc([groupe([etape_doc(480.0, ftp_pct=1.05)])])
    seance, erreur = _robuste(
        lambda: appeler_depuis_workout(mod, document, ftp_w=None), quoi="%ftp sans FTP"
    )
    if erreur is not None:
        return
    _verifier(seance)
    for i, e in enumerate(seance.etapes):
        assert e.puissance_min_w is None and e.puissance_max_w is None, (
            f"etapes[{i}] : {e.puissance_min_w}-{e.puissance_max_w} W calculés sans FTP"
        )


@pytest.mark.parametrize("valeur", [0.5, 80.0], ids=["fraction", "pourcentage"])
def test_le_pourcentage_de_ftp_reste_dans_un_ordre_de_grandeur_de_cycliste(valeur):
    """`0.8` et `80` désignent tous deux 80 % : aucun des deux ne vaut 16 000 W."""
    mod = _intervals()
    document = fabriques4.doc([groupe([etape_doc(600.0, ftp_pct=valeur)])])
    seance = appeler_depuis_workout(mod, document)
    _verifier(seance)
    cible = seance.etapes[0].puissance_cible_w
    assert cible is not None, "une puissance en %ftp avec un FTP connu doit se calculer"
    assert 0.1 * FTP_TEST_W <= cible <= 3.0 * FTP_TEST_W, (
        f"{valeur} %ftp avec FTP={FTP_TEST_W} W donne {cible} W : fraction et pourcentage confondus"
    )


def test_deux_pourcentages_de_ftp_restent_proportionnels():
    mod = _intervals()
    document = fabriques4.doc(
        [groupe([etape_doc(600.0, ftp_pct=0.5), etape_doc(600.0, ftp_pct=1.0)])]
    )
    seance = appeler_depuis_workout(mod, document)
    faible, forte = (e.puissance_cible_w for e in seance.etapes[:2])
    assert faible and forte
    assert forte / faible == pytest.approx(2.0, rel=1e-6), (
        f"50 % et 100 % du même FTP donnent {faible} W et {forte} W : rapport {forte / faible:.3f}"
    )


def test_une_rampe_de_puissance_donne_une_fourchette_croissante():
    mod = _intervals()
    document = fabriques4.doc([groupe([etape_doc(900.0, rampe=(0.5, 0.75), warmup=True)])])
    seance, erreur = _robuste(lambda: appeler_depuis_workout(mod, document), quoi="rampe start/end")
    if erreur is not None:
        return
    _verifier(seance)
    e = seance.etapes[0]
    if e.puissance_min_w is not None:
        assert e.puissance_min_w <= e.puissance_max_w
        assert e.puissance_cible_w == pytest.approx((e.puissance_min_w + e.puissance_max_w) / 2.0)


def test_une_zone_de_frequence_cardiaque_se_dit_approximee():
    """Contrat §1 : « une approximation se dit » — sinon le chiffre passe pour une mesure."""
    mod = _intervals()
    document = fabriques4.doc([groupe([etape_doc(480.0, zone_fc=4)])])
    seance = appeler_depuis_workout(mod, document)
    _verifier(seance)
    assert seance.meta.get("puissance_approximee") is True, (
        "une puissance déduite d'une zone de FC doit porter meta['puissance_approximee'] = True "
        f"(meta reçu : {seance.meta!r})"
    )
    bas, haut = ZONES_PUISSANCE[4]
    e = seance.etapes[0]
    assert e.puissance_min_w == pytest.approx(bas * FTP_TEST_W, abs=1.0), (
        f"zone 4 approximée à {e.puissance_min_w} W, attendu {bas * FTP_TEST_W} W "
        "(bornes de zones_puissance × FTP)"
    )
    assert e.puissance_max_w == pytest.approx(haut * FTP_TEST_W, abs=1.0)


def test_une_seance_entierement_en_watts_ne_se_declare_pas_approximee():
    mod = _intervals()
    document = fabriques4.doc([groupe([etape_doc(480.0, watts=210.0)])])
    seance = appeler_depuis_workout(mod, document)
    assert not seance.meta.get("puissance_approximee"), (
        "aucune approximation ici : le document donne des watts"
    )
    assert seance.etapes[0].puissance_cible_w == pytest.approx(210.0)


@pytest.mark.parametrize("zone", [9, "Z4"], ids=["hors_table", "chaine"])
def test_une_zone_de_frequence_cardiaque_inconnue_ne_leve_pas_de_keyerror(zone):
    mod = _intervals()
    document = fabriques4.doc([groupe([etape_doc(480.0, zone_fc=zone)])])
    seance, erreur = _robuste(lambda: appeler_depuis_workout(mod, document), quoi=f"hr_zone={zone!r}")
    if erreur is None:
        _verifier(seance)


# --- l'élasticité, décision produit du 13/09 ---------------------------------


def test_seules_les_extremites_sont_elastiques():
    mod = _intervals()
    seance = appeler_depuis_workout(mod, fabriques4.doc_4x8())
    _verifier(seance)
    elastiques = [i for i, e in enumerate(seance.etapes) if e.elastique]
    assert elastiques == [0, len(seance.etapes) - 1], (
        f"étapes élastiques {elastiques} : seules la Z2 d'ouverture et celle de fermeture le sont"
    )


def test_aucune_recuperation_n_est_elastique_meme_longue():
    """« Durabilité » : 45 min de Z2 au milieu, et pourtant fixes (plan, sprint 4)."""
    mod = _intervals()
    document = fabriques4.doc(
        [
            groupe([etape_doc(3600.0, ftp_pct=0.6, warmup=True, intensity="warmup")]),
            groupe(
                [etape_doc(300.0, ftp_pct=1.2), etape_doc(90.0, ftp_pct=0.5, intensity="recovery")], reps=4
            ),
            groupe([etape_doc(2700.0, ftp_pct=0.6, intensity="recovery", text="Z2 longue")]),
            groupe(
                [etape_doc(300.0, ftp_pct=1.2), etape_doc(90.0, ftp_pct=0.5, intensity="recovery")], reps=4
            ),
            groupe([etape_doc(1200.0, ftp_pct=0.55, cooldown=True, intensity="cooldown")]),
        ]
    )
    seance = appeler_depuis_workout(mod, document)
    _verifier(seance)
    longues = [e for e in seance.etapes if e.type == "recuperation" and e.duree_s >= 2700.0]
    assert longues, "la Z2 de 45 min doit rester une récupération, pas devenir un échauffement"
    assert not any(e.elastique for e in seance.etapes if e.type == "recuperation")


def test_un_echauffement_au_milieu_n_est_pas_elastique():
    """Marqueur `warmup` posé sur une étape du milieu : le contrat ne dit que « la première »."""
    mod = _intervals()
    document = fabriques4.doc(
        [
            groupe([etape_doc(600.0, ftp_pct=0.6, warmup=True)]),
            groupe([etape_doc(480.0, ftp_pct=1.05)]),
            groupe([etape_doc(300.0, ftp_pct=0.6, warmup=True, text="re-echauffement")]),
            groupe([etape_doc(600.0, ftp_pct=0.55, cooldown=True)]),
        ]
    )
    seance = appeler_depuis_workout(mod, document)
    _verifier(seance)
    assert not seance.etapes[2].elastique, "seule la première étape peut être un échauffement élastique"


def test_une_seance_qui_commence_par_un_bloc_n_a_pas_de_z2_d_ouverture_elastique():
    mod = _intervals()
    document = fabriques4.doc(
        [groupe([etape_doc(480.0, ftp_pct=1.05)]), groupe([etape_doc(600.0, ftp_pct=0.55, cooldown=True)])]
    )
    seance = appeler_depuis_workout(mod, document)
    _verifier(seance)
    assert not seance.etapes[0].elastique, "un bloc n'est jamais élastique, fût-il en tête"
    assert seance.etapes[-1].elastique, "le retour au calme final reste élastique"


# --- explosion combinatoire ---------------------------------------------------


def test_des_repetitions_gigantesques_ne_font_pas_exploser_la_memoire():
    """40³ = 64 000 étapes : soit le module borne, soit il rend la main vite."""
    mod = _intervals()
    feuille = groupe([etape_doc(60.0, ftp_pct=0.6)], reps=40)
    document = fabriques4.doc([groupe([groupe([feuille], reps=40)], reps=40)])
    with fabriques.limite_temps(20.0, "depuis_workout_doc sur 40³ répétitions"):
        seance, erreur = _robuste(
            lambda: appeler_depuis_workout(mod, document), quoi="reps 40 sur trois niveaux"
        )
    if erreur is None:
        assert len(seance.etapes) <= 40**3, "plus d'étapes que le produit des répétitions"
        assert seance.duree_s == pytest.approx(sum(float(e.duree_s) for e in seance.etapes))


# --- séance du jour ----------------------------------------------------------


def _client(reponse: Any, *, code: int = 200) -> Any:
    """Un `ClientIntervals` branché sur une réponse figée, sans réseau."""
    from ourouler.connecteurs.intervals import ClientIntervals

    def repondre(_requete: httpx.Request) -> httpx.Response:
        if isinstance(reponse, str):
            return httpx.Response(code, text=reponse)
        return httpx.Response(code, json=reponse)

    http = httpx.Client(transport=httpx.MockTransport(repondre))
    return ClientIntervals("i000000", CLE_BIDON, http=http, base_url="https://intervals.exemple.invalide")


def _appeler_seance_du_jour(mod: Any, reponse: Any, *, jour: date = JOUR, code: int = 200):
    return _robuste(
        lambda: mod.seance_du_jour(
            _client(reponse, code=code), jour, ftp_w=FTP_TEST_W, zones_puissance=ZONES_PUISSANCE
        ),
        quoi=f"seance_du_jour({reponse!r:.60})",
    )


def test_aucune_seance_ce_jour_la_rend_none():
    mod = _intervals()
    seance, erreur = _appeler_seance_du_jour(mod, [])
    assert erreur is None and seance is None, "sans événement, le contrat §1 demande None"


@pytest.mark.parametrize(
    "evenements",
    [
        [{"id": 1, "category": "WORKOUT", "name": "sans doc"}],
        [{"id": 1, "category": "WORKOUT", "workout_doc": "{\"steps\": []}"}],
        {"erreur": "pas une liste"},
    ],
    ids=["sans_doc", "doc_en_chaine", "objet"],
)
def test_une_reponse_d_evenements_hostile_ne_casse_pas(evenements):
    mod = _intervals()
    seance, erreur = _appeler_seance_du_jour(mod, evenements)
    if erreur is None and seance is not None:
        _verifier(seance)
        assert seance.jour == JOUR, "la séance rendue doit porter le jour demandé"


@pytest.mark.parametrize("code", [500], ids=["panne"])
def test_une_erreur_http_reste_une_erreur_utilisateur(code):
    mod = _intervals()
    seance, erreur = _appeler_seance_du_jour(mod, {"message": "non"}, code=code)
    assert erreur is not None, f"HTTP {code} doit donner une erreur utilisateur, reçu {seance!r}"


def test_deux_seances_le_meme_jour_ne_produisent_qu_une_seance():
    mod = _intervals()
    evenements = [
        {"id": 1, "category": "WORKOUT", "name": "A", "workout_doc": fabriques4.doc_4x8()},
        {"id": 2, "category": "WORKOUT", "name": "B", "workout_doc": fabriques4.doc_4x8()},
    ]
    seance, erreur = _appeler_seance_du_jour(mod, evenements)
    if erreur is None and seance is not None:
        _verifier(seance)
        assert len(seance.blocs()) == 4, (
            f"{len(seance.blocs())} blocs : les deux séances du jour ont été concaténées"
        )


def test_un_jour_de_changement_d_heure_ne_decale_pas_la_seance():
    """29/03/2026 : 02 h 30 n'existe pas en Europe/Paris. Le jour reste le jour demandé."""
    mod = _intervals()
    jour = date(2026, 3, 29)
    evenements = [
        {
            "id": 1,
            "category": "WORKOUT",
            "name": "matin d'heure d'été",
            "start_date_local": "2026-03-29T02:30:00",
            "workout_doc": fabriques4.doc_4x8(),
        }
    ]
    seance, erreur = _appeler_seance_du_jour(mod, evenements, jour=jour)
    if erreur is None and seance is not None:
        _verifier(seance)
        assert seance.jour == jour, (
            f"séance datée du {seance.jour} pour un appel sur le {jour} : "
            "un horodatage local a été relu comme un instant UTC"
        )


def test_la_cle_d_api_ne_sort_pas_dans_une_erreur_de_seance():
    """Règle absolue 1 : même en panne, la clé ne doit apparaître nulle part."""
    mod = _intervals()
    _seance, erreur = _appeler_seance_du_jour(mod, {"message": "non"}, code=500)
    if erreur is None:
        pytest.skip("le module ne signale pas l'erreur HTTP par une exception")
    for texte in (str(erreur), repr(erreur), json.dumps(getattr(erreur, "args", []), default=str)):
        assert CLE_BIDON not in texte, f"la clé d'API fuit dans « {texte[:200]} »"
