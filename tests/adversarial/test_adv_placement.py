"""L4.3 — placement de la séance sur le tracé, mis à l'épreuve.

Cible : contrat du sprint 4 §3 et §5, et les décisions produit du 13/09
rapportées dans `docs/plan_sprints_agents.md`. C'est le point le plus facile à
trahir en silence : le placement rend toujours un nombre, et une règle produit
oubliée ne se voit ni dans un test de forme, ni à la lecture d'une note.

Les trois règles que ce fichier surveille en priorité :

1. **Aucune évaluation sous une récupération.** « En récup, village,
   croisement, etc., ce n'est pas grave. » Un village et deux feux placés
   entre deux blocs ne doivent rien changer, ni à la note totale ni aux
   emplacements. Le test compare deux tracés identiques au mètre près, dont
   l'un porte des obstacles **uniquement** dans l'intervalle de récupération
   mesuré sur le premier placement.
2. **Les récupérations sont fixes**, courtes comme longues : elles font partie
   de la prescription. Le placement ne les rallonge pas pour tomber sur un
   meilleur couloir, et ne modifie pas la séance qu'il reçoit.
3. **La Z2 de fin ne place rien.** Elle absorbe, elle ne décale pas. Deux
   tracés identiques jusqu'au dernier bloc et différents après doivent donner
   le même décalage de Z2 d'ouverture.

Et la mécanique du demi-tour, qui exige ses trois conditions : segment plat,
route au-delà, demi-tour faisable. Un test par condition manquante, plus un
contrôle positif — sans lui, trois tests qui « ne trouvent aucun demi-tour »
passeraient sur une implémentation qui n'en propose jamais.
"""

from __future__ import annotations

from typing import Any

import fabriques
import fabriques3
import fabriques4
import pytest
from outils import robuste

from ourouler.erreurs import ErreurUtilisateur

MOTIF_ABSENT = "module attendu par le contrat L4.3 absent (ourouler.seance.placement)"
MOTIF_MODELE = "module attendu par le contrat L4.1 absent (ourouler.seance.modele)"
MOTIF_PHYSIQUE = "module du sprint 3 absent (ourouler.physique.modele)"
MOTIF_NODE_TAGS = "Segment.node_tags absent : prérequis du lot L4.2 (contrat §2)"

ERREURS = (ErreurUtilisateur, ValueError)

#: Séance de test : 20 min de Z2, 10 min de bloc, 4 min de récup, 10 min de
#: bloc, 10 min de calme. Les durées sont celles des tests, pas celles du
#: mainteneur ; seule leur structure compte.
ECHAUFFEMENT_S = 1200.0
BLOC_S = 600.0
RECUP_S = 240.0
CALME_S = 600.0
PUISSANCE_BLOC_W = 210.0
PUISSANCE_Z2_W = 140.0

#: Boucle de 60 km, plate, sur une petite route : de quoi loger la séance et
#: ses ±20 % d'élasticité.
RAYON_BOUCLE_M = 9549.0  # 60 km de tour : la courbure reste très loin d'un virage
N_COTES = 600


def _placement() -> Any:
    return fabriques4.module("placement", motif=MOTIF_ABSENT)


def _modele() -> Any:
    return fabriques4.module("modele", motif=MOTIF_MODELE)


def _physique() -> Any:
    return pytest.importorskip("ourouler.physique.modele", reason=MOTIF_PHYSIQUE)


def _parametres() -> Any:
    return fabriques3.parametres(_physique())


def _vitesse(puissance_w: float) -> float:
    """Vitesse d'équilibre sur le plat, en m/s — la même que celle du placement."""
    return _physique().vitesse_regime(puissance_w, 0.0, 0.0, _parametres())


def _seance(**surcharges: Any) -> Any:
    return fabriques4.seance_deux_blocs(
        _modele(),
        echauffement_s=surcharges.get("echauffement_s", ECHAUFFEMENT_S),
        bloc_s=surcharges.get("bloc_s", BLOC_S),
        recup_s=surcharges.get("recup_s", RECUP_S),
        calme_s=surcharges.get("calme_s", CALME_S),
        puissance_bloc_w=PUISSANCE_BLOC_W,
        puissance_z2_w=PUISSANCE_Z2_W,
    )


def _boucle(**kwargs: Any) -> Any:
    return fabriques4.boucle_plate(rayon_m=RAYON_BOUCLE_M, n=N_COTES, **kwargs)


def _appeler(seance: Any, trace: Any, **kwargs: Any):
    mod = _placement()
    return robuste(
        lambda: mod.placer(seance, trace, _parametres(), **kwargs),
        quoi=f"placer(..., {kwargs})",
        erreurs_acceptees=ERREURS,
    )


def _placer(seance: Any, trace: Any, **kwargs: Any) -> Any:
    """`placer` sur une entrée saine : le contrat exige un résultat, pas une erreur."""
    placement, erreur = _appeler(seance, trace, **kwargs)
    assert erreur is None, f"placer a refusé une entrée saine : {erreur}"
    if placement is not None:
        _verifier(placement, seance, trace)
    return placement


def _verifier(placement: Any, seance: Any, trace: Any) -> None:
    fabriques4.nombre_fini(placement.decalage_z2_s, "Placement.decalage_z2_s")
    fabriques4.nombre_fini(placement.note_totale, "Placement.note_totale", positif=True)
    fabriques4.nombre_fini(placement.duree_totale_s, "Placement.duree_totale_s", positif=True)
    fabriques4.nombre_fini(placement.distance_totale_m, "Placement.distance_totale_m", positif=True)
    fabriques4.liste_de_chaines(placement.avertissements, "Placement.avertissements")
    assert isinstance(placement.emplacements, list), "Placement.emplacements : liste attendue"
    assert len(placement.emplacements) == len(seance.blocs()), (
        f"{len(placement.emplacements)} emplacements pour {len(seance.blocs())} blocs : "
        "chaque bloc de la prescription doit être placé"
    )
    indices_blocs = [i for i, _ in seance.blocs()]
    notes: list[float] = []
    for n, e in enumerate(placement.emplacements):
        assert e.etape_idx in indices_blocs, (
            f"emplacements[{n}].etape_idx = {e.etape_idx} ne désigne pas une étape de type bloc"
        )
        debut = fabriques4.nombre_fini(e.debut_m, f"emplacements[{n}].debut_m", positif=True)
        longueur = fabriques4.nombre_fini(e.longueur_m, f"emplacements[{n}].longueur_m", positif=True)
        assert longueur > 0.0, f"emplacements[{n}] : un bloc de longueur nulle n'existe pas"
        assert debut + longueur <= placement.distance_totale_m + 1.0, (
            f"emplacements[{n}] court de {debut} à {debut + longueur} m alors que la sortie "
            f"n'en fait que {placement.distance_totale_m} : bloc placé après l'arrivée"
        )
        if not trace.bornee():
            assert debut + longueur <= trace.distance_m + 1.0, (
                f"emplacements[{n}] sort du tracé ({trace.distance_m} m), qui n'est pas une boucle"
            )
        assert isinstance(e.demi_tour, bool), f"emplacements[{n}].demi_tour : booléen attendu"
        fabriques4.verifier_note(e.note, quoi=f"emplacements[{n}].note")
        notes.append(float(e.note.note))
    # `note_totale` est la moyenne des notes de couloir pondérée par la durée
    # des blocs (décision du superviseur du 13/09, Q12) : une activation de
    # 40 s ne pèse pas comme un bloc de 20 min. Ce n'est donc plus une somme,
    # et l'invariant porte sur ce qu'une moyenne doit respecter — rester dans
    # l'intervalle des notes, et ne pas effacer une pénalité.
    if notes:
        assert min(notes) - 1e-6 <= placement.note_totale <= max(notes) + 1e-6, (
            f"note_totale = {placement.note_totale} hors de l'intervalle des notes de bloc "
            f"([{min(notes)}, {max(notes)}]) : ce n'est pas une moyenne pondérée"
        )
        if max(notes) > 0.0:
            assert placement.note_totale > 0.0, (
                f"note_totale = {placement.note_totale} alors qu'un bloc porte une pénalité de "
                f"{max(notes)} : une pénalité a été perdue en route"
            )


def _demi_tours(placement: Any) -> list[int]:
    if placement is None:
        return []
    return [n for n, e in enumerate(placement.emplacements) if e.demi_tour]


def _exiger_node_tags() -> None:
    if not fabriques4.segments_disponibles_avec_node_tags():
        pytest.skip(MOTIF_NODE_TAGS)


# --- forme du résultat --------------------------------------------------------


def test_une_seance_tient_sur_une_boucle_propre():
    seance, trace = _seance(), _boucle()
    placement = _placer(seance, trace)
    assert placement is not None, "une séance de 50 min doit tenir sur une boucle de 60 km"
    assert placement.note_totale == pytest.approx(0.0, abs=1e-9), (
        f"note {placement.note_totale} sur une boucle plate sans obstacle — "
        f"motifs : {[m for e in placement.emplacements for m in e.note.motifs]}"
    )
    assert [e.debut_m for e in placement.emplacements] == sorted(
        e.debut_m for e in placement.emplacements
    ), "les blocs doivent être placés dans l'ordre de la séance"


def test_le_placement_ne_modifie_ni_la_seance_ni_le_trace():
    """Décision du 13/09 : les récupérations font partie de la prescription."""
    seance, trace = _seance(), _boucle()
    avant_seance = fabriques4.instantane_seance(seance)
    avant_trace = fabriques4.instantane_trace(trace)
    _placer(seance, trace)
    assert fabriques4.instantane_seance(seance) == avant_seance, (
        "placer a modifié la séance reçue — une durée de récupération ne se renégocie pas"
    )
    assert fabriques4.instantane_trace(trace) == avant_trace, "placer a modifié le tracé reçu"


def test_le_placement_est_deterministe():
    seance, trace = _seance(), _boucle()
    a, b = _placer(seance, trace), _placer(seance, trace)
    assert (a is None) == (b is None)
    if a is None:
        return
    assert a.decalage_z2_s == b.decalage_z2_s and a.note_totale == b.note_totale
    assert [(e.debut_m, e.longueur_m, e.demi_tour) for e in a.emplacements] == [
        (e.debut_m, e.longueur_m, e.demi_tour) for e in b.emplacements
    ], "deux appels identiques donnent deux placements différents"


def test_une_seance_sans_bloc_ne_place_rien():
    mod = _modele()
    seance = fabriques4.seance(
        mod,
        [
            fabriques4.etape(mod, "echauffement", 1800.0, pmin=PUISSANCE_Z2_W, pmax=PUISSANCE_Z2_W,
                             elastique=True),
            fabriques4.etape(mod, "calme", 1800.0, pmin=PUISSANCE_Z2_W, pmax=PUISSANCE_Z2_W,
                             elastique=True),
        ],
    )
    placement = _placer(seance, _boucle())
    if placement is not None:
        assert placement.emplacements == [] and placement.note_totale == pytest.approx(0.0)


@pytest.mark.parametrize(
    "cas",
    ["trace_minuscule", "seance_vide", "seance_trop_longue"],
)
def test_les_entrees_impossibles_ne_levent_pas(cas):
    mod = _modele()
    seance, trace = _seance(), _boucle()
    if cas == "trace_minuscule":
        trace = fabriques4.trace_taguee(fabriques4.droite(1, pas_m=10.0))
    elif cas == "seance_vide":
        seance = fabriques4.seance(mod, [])
    else:
        seance = _seance(echauffement_s=7200.0, bloc_s=3600.0, calme_s=7200.0)
    placement, erreur = _appeler(seance, trace)
    if erreur is None and placement is not None:
        _verifier(placement, seance, trace)
        if cas == "trace_minuscule":
            assert placement.distance_totale_m <= 10.0 * max(trace.distance_m, 1.0), (
                f"{placement.distance_totale_m:.0f} m annoncés sur un tracé de {trace.distance_m:.0f} m : "
                "`Trace.bornee()` est vrai pour tout tracé court (moins de 300 m entre les extrémités), "
                "ce n'est pas une boucle à tourner en rond"
            )


def test_une_seance_qui_ne_tient_pas_le_dit():
    """Contrat §3 : « si la séance ne tient pas sur la boucle, None et le motif »."""
    seance = _seance(echauffement_s=10_800.0, bloc_s=3600.0, calme_s=10_800.0)
    trace = fabriques4.trace_taguee(fabriques4.droite(50, pas_m=100.0))  # 5 km rectilignes
    placement, erreur = _appeler(seance, trace)
    if erreur is not None:
        return
    assert placement is None or placement.avertissements, (
        "une séance de 7 h placée sur 5 km doit rendre None ou dire ce qui cloche"
    )


# --- élasticité : la Z2 d'ouverture, et elle seule -----------------------------


def test_une_elasticite_nulle_ne_decale_rien():
    placement = _placer(_seance(), _boucle(), elasticite=(0.0, 0.0))
    if placement is not None:
        assert placement.decalage_z2_s == pytest.approx(0.0), (
            f"décalage de {placement.decalage_z2_s} s demandé avec une élasticité nulle"
        )


def test_le_decalage_reste_dans_la_fenetre_demandee():
    seance = _seance()
    placement = _placer(seance, _boucle(), elasticite=(-0.05, 0.20), pas_s=30.0)
    if placement is None:
        pytest.skip("aucun placement trouvé : la borne du décalage n'est pas observable")
    z2 = seance.etapes[0].duree_s
    assert -0.05 * z2 - 1e-6 <= placement.decalage_z2_s <= 0.20 * z2 + 1e-6, (
        f"décalage {placement.decalage_z2_s} s hors de [{-0.05 * z2}, {0.20 * z2}] s "
        "— l'élasticité demandée a été dépassée"
    )


@pytest.mark.parametrize(
    ("elasticite", "pas_s"),
    [((-0.05, 0.20), 0.0), ((0.20, -0.05), 60.0), ((-2.0, 5.0), 60.0)],
    ids=["pas_nul", "elasticite_inversee", "elasticite_absurde"],
)
def test_des_reglages_absurdes_ne_levent_pas(elasticite, pas_s):
    seance, trace = _seance(), _boucle()
    placement, erreur = _appeler(seance, trace, elasticite=elasticite, pas_s=pas_s)
    if erreur is None and placement is not None:
        _verifier(placement, seance, trace)


def test_un_pas_plus_grand_que_la_marge_essaie_au_moins_le_decalage_nul():
    """`pas_s = 3600` sur une fenêtre de 300 s : il reste au moins une valeur à essayer.

    Le contrat ne dit pas si la grille part de la borne basse ou de zéro : on
    n'exige donc pas laquelle, seulement qu'il en reste une et qu'elle tienne
    dans la fenêtre.
    """
    seance, trace = _seance(), _boucle()
    placement = _placer(seance, trace, pas_s=3600.0)
    assert placement is not None, (
        "un pas plus grand que la fenêtre d'élasticité ne doit pas empêcher le placement : "
        "il reste au moins une valeur de décalage à essayer"
    )
    z2 = seance.etapes[0].duree_s
    assert -0.05 * z2 - 1e-6 <= placement.decalage_z2_s <= 0.20 * z2 + 1e-6


def test_les_ecarts_entre_blocs_ne_dependent_pas_de_l_elasticite():
    """Les récupérations sont fixes : l'élasticité déplace la série, pas ses intervalles."""
    seance, trace = _seance(), _boucle()
    serre = _placer(seance, trace, elasticite=(0.0, 0.0))
    large = _placer(seance, trace, elasticite=(-0.05, 0.20))
    if serre is None or large is None or len(serre.emplacements) < 2:
        pytest.skip("pas de placement à deux blocs : l'écart n'est pas observable")
    def ecart(p: Any) -> float:
        premier = p.emplacements[0]
        return p.emplacements[1].debut_m - (premier.debut_m + premier.longueur_m)

    if large.emplacements[0].demi_tour or large.emplacements[1].demi_tour:
        pytest.skip("demi-tour choisi : l'écart le long du tracé n'est plus comparable")
    assert ecart(serre) == pytest.approx(ecart(large), rel=0.02), (
        f"écart entre blocs de {ecart(serre):.0f} m sans élasticité contre {ecart(large):.0f} m avec : "
        "la récupération a changé de durée"
    )


# --- aucune évaluation sous une récupération -----------------------------------


def test_un_village_et_des_feux_sous_la_recuperation_ne_changent_rien():
    """La règle produit la plus facile à trahir en silence (décision du 13/09).

    Les deux tracés sont géométriquement identiques : mêmes points, mêmes
    altitudes. Seules les étiquettes OSM changent, et seulement dans
    l'intervalle où tombe la récupération. La note totale et les emplacements
    doivent être rigoureusement les mêmes.
    """
    _exiger_node_tags()
    seance, propre = _seance(), _boucle()
    reference = _placer(seance, propre, elasticite=(0.0, 0.0))
    assert reference is not None and len(reference.emplacements) == 2, (
        "ce test a besoin des deux blocs placés pour savoir où tombe la récupération"
    )
    premier, second = reference.emplacements[0], reference.emplacements[1]
    if premier.demi_tour or second.demi_tour:
        pytest.skip("demi-tour choisi sur une boucle propre : l'intervalle de récup n'est pas un segment")
    debut_recup = premier.debut_m + premier.longueur_m + 20.0
    fin_recup = second.debut_m - 20.0
    assert fin_recup > debut_recup, "récupération trop courte pour y loger un obstacle"

    sale = fabriques4.salir(propre, [(debut_recup, fin_recup)])
    apres = _placer(seance, sale, elasticite=(0.0, 0.0))
    assert apres is not None, "le tracé sali ne diffère que par des étiquettes hors des blocs"
    assert apres.note_totale == pytest.approx(reference.note_totale), (
        f"note {apres.note_totale} contre {reference.note_totale} : le village et les feux traversés "
        "pendant la récupération ont été comptés — décision du 13/09, on n'évalue rien sous une récup"
    )
    assert [(e.debut_m, e.longueur_m, e.demi_tour) for e in apres.emplacements] == [
        (e.debut_m, e.longueur_m, e.demi_tour) for e in reference.emplacements
    ], "les blocs ont bougé à cause d'obstacles situés sous la récupération"


def test_un_village_sous_les_blocs_change_la_note():
    """Contrôle du test précédent : le détecteur de saleté doit détecter."""
    _exiger_node_tags()
    seance, propre = _seance(), _boucle()
    reference = _placer(seance, propre, elasticite=(0.0, 0.0))
    assert reference is not None and reference.emplacements
    zones = [(e.debut_m, e.debut_m + e.longueur_m) for e in reference.emplacements]
    sale = fabriques4.salir(propre, zones)
    apres = _placer(seance, sale, elasticite=(0.0, 0.0))
    assert apres is not None
    assert apres.note_totale > reference.note_totale, (
        "un village et des feux **dans** les blocs doivent se payer : "
        f"note {apres.note_totale} contre {reference.note_totale}"
    )


# --- la Z2 de fin absorbe, elle ne place pas -----------------------------------


def test_ce_qui_suit_le_dernier_bloc_ne_change_pas_le_decalage_d_ouverture():
    """« Z2 de fin = absorption. Elle ne place rien » (plan, sprint 4).

    Le retour au calme dure ici 30 min : la zone salie est franchement roulée
    pendant cette Z2 de fin, et reste hors d'atteinte des blocs quel que soit
    le décalage. Si elle était salie au-delà de l'arrivée, le test ne
    comparerait que du tracé que personne ne parcourt.
    """
    _exiger_node_tags()
    seance, propre = _seance(calme_s=1800.0), _boucle()
    reference = _placer(seance, propre, elasticite=(-0.05, 0.20))
    assert reference is not None and reference.emplacements
    fin_dernier = max(e.debut_m + e.longueur_m for e in reference.emplacements)
    # Marge généreuse : même au décalage maximal, aucun bloc ne peut atteindre
    # cette zone (0,20 × 1200 s à 60 km/h font moins de 4 km).
    marge_m = 0.20 * seance.etapes[0].duree_s * 17.0 + 1000.0
    debut_sale = fin_dernier + marge_m
    if debut_sale >= propre.distance_m - 500.0:
        pytest.skip("pas assez de tracé après le dernier bloc pour y placer des obstacles")

    sale = fabriques4.salir(propre, [(debut_sale, propre.distance_m)])
    apres = _placer(seance, sale, elasticite=(-0.05, 0.20))
    assert apres is not None
    assert apres.decalage_z2_s == pytest.approx(reference.decalage_z2_s), (
        f"décalage {apres.decalage_z2_s} s contre {reference.decalage_z2_s} s : ce qui se trouve "
        "après le dernier bloc a servi à placer la séance"
    )
    assert [(e.debut_m, e.longueur_m) for e in apres.emplacements] == [
        (e.debut_m, e.longueur_m) for e in reference.emplacements
    ], "les blocs ont bougé à cause du terrain traversé pendant la Z2 de fin"
    assert apres.note_totale == pytest.approx(reference.note_totale), (
        f"note {apres.note_totale} contre {reference.note_totale} : le terrain de la Z2 de fin est entré "
        "dans la note de la séance, alors qu'elle ne fait que ramener à la maison"
    )


# --- le demi-tour et ses trois conditions ---------------------------------------


def _boucle_a_couloir_unique(*, pente_couloir: float = 0.0, highway_couloir: str = "tertiary") -> Any:
    """Une boucle sale partout sauf un unique couloir propre, là où tombe le bloc 1.

    C'est la figure du cadrage : « un seul bon tronçon de 3 km suffit pour tout
    un 4×5' », à condition de faire demi-tour à chaque récupération. Le couloir
    reçoit sa pente et son étiquette : c'est là que se jouent les trois
    conditions du demi-tour.
    """
    debut_b1 = _vitesse(PUISSANCE_Z2_W) * ECHAUFFEMENT_S
    fin_b1 = debut_b1 + _vitesse(PUISSANCE_BLOC_W) * BLOC_S
    # De la route au-delà du couloir pour la première moitié de la récupération.
    couloir = (
        max(debut_b1 - 500.0, 0.0),
        fin_b1 + _vitesse(PUISSANCE_Z2_W) * RECUP_S / 2.0 + 500.0,
    )
    propre = _boucle()
    sale = fabriques4.salir(propre, [(0.0, couloir[0]), (couloir[1], propre.distance_m)])
    dans_le_couloir = set(fabriques4.troncon_de(sale, *couloir))
    tags = [dict(s.tags) for s in sale.segments]
    noeuds = {i: dict(getattr(s, "node_tags", {}) or {}) for i, s in enumerate(sale.segments)}
    for i in dans_le_couloir:
        tags[i] = {"highway": highway_couloir}
        noeuds[i] = {}
    coords: list[tuple[float, float, float | None]] = []
    altitude = 50.0
    for i, point in enumerate(sale.points):
        coords.append((point.lat, point.lon, altitude))
        if i in dans_le_couloir and i + 1 < len(sale.points):
            altitude += pente_couloir * (sale.points[i + 1].dist_m - point.dist_m)
    return fabriques4.trace_taguee(coords, tags=tags, node_tags=noeuds, nom="boucle a couloir unique")


def test_un_couloir_unique_et_propre_fait_choisir_le_demi_tour():
    """Contrôle positif : sans lui, les trois tests suivants ne prouvent rien."""
    _exiger_node_tags()
    seance = _seance()
    placement = _placer(seance, _boucle_a_couloir_unique(), elasticite=(0.0, 0.0))
    assert placement is not None, "la séance tient sur la boucle, propre ou non"
    assert _demi_tours(placement), (
        "aucun demi-tour proposé alors que le second bloc tomberait sinon en plein village : "
        "la variante demi-tour du contrat §3 n'est pas essayée"
    )


@pytest.mark.parametrize(
    ("cas", "trace_"),
    [
        ("segment_en_cote", {"pente_couloir": 0.04}),
        ("route_passante", {"highway_couloir": "primary"}),
    ],
    ids=["pas_plat", "demi_tour_infaisable"],
)
def test_le_demi_tour_exige_ses_conditions(cas, trace_):
    """Plan du sprint 4 : plat ou faux-plat, route au-delà, demi-tour faisable."""
    _exiger_node_tags()
    seance = _seance()
    placement = _placer(seance, _boucle_a_couloir_unique(**trace_), elasticite=(0.0, 0.0))
    assert not _demi_tours(placement), (
        f"demi-tour proposé sur un couloir « {cas} » : "
        "les trois conditions du demi-tour doivent être remplies ensemble"
    )


def test_sans_route_au_dela_aucun_demi_tour():
    """Troisième condition : la moitié de la récup doit se rouler après le segment.

    Faiblesse assumée de ce cas en aveugle : couper le tracé juste après le
    premier bloc empêche aussi la séance de tenir, donc `placer` a le droit de
    rendre `None`. La condition elle-même est vérifiée de front sur
    `route_au_dela` dans `test_adv_terrain.py`.
    """
    _exiger_node_tags()
    seance = _seance()
    debut_b1 = _vitesse(PUISSANCE_Z2_W) * ECHAUFFEMENT_S
    fin_b1 = debut_b1 + _vitesse(PUISSANCE_BLOC_W) * BLOC_S
    # Tracé ouvert qui s'arrête 100 m après le premier bloc : il n'y a plus de
    # route pour la première moitié de la récupération.
    n = int((fin_b1 + 100.0) / fabriques4.PAS_M)
    trace = fabriques4.trace_taguee(fabriques4.droite(n, pas_m=fabriques4.PAS_M))
    placement, erreur = _appeler(seance, trace, elasticite=(0.0, 0.0))
    if erreur is None and placement is not None:
        _verifier(placement, seance, trace)
    assert not _demi_tours(placement), (
        "demi-tour proposé alors qu'il ne reste pas de quoi rouler la moitié de la récupération "
        "au-delà du segment"
    )


def test_une_penalite_de_demi_tour_prohibitive_fait_passer_par_le_village():
    """La pénalité est un paramètre : à 1000 km équivalents, le demi-tour ne vaut plus."""
    _exiger_node_tags()
    seance, trace = _seance(), _boucle_a_couloir_unique()
    doux = _placer(seance, trace, elasticite=(0.0, 0.0), penalite_demi_tour=0.0)
    dur = _placer(seance, trace, elasticite=(0.0, 0.0), penalite_demi_tour=1000.0)
    if not _demi_tours(doux):
        pytest.skip("aucun demi-tour même sans pénalité : rien à mesurer ici")
    assert not _demi_tours(dur), (
        "le demi-tour est choisi malgré une pénalité de 1000 : `penalite_demi_tour` n'est pas appliquée"
    )


# --- garde-fou de temps ---------------------------------------------------------


def test_le_placement_rend_la_main_sur_une_longue_boucle():
    """Un pas de 10 s sur une boucle de 40 km ne doit pas partir en exploration exhaustive."""
    seance = _seance()
    trace = _boucle()
    with fabriques.limite_temps(30.0, "placer sur 40 km avec un pas de 10 s"):
        placement, erreur = _appeler(seance, trace, pas_s=10.0)
    if erreur is None and placement is not None:
        _verifier(placement, seance, trace)
