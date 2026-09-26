"""Le terrain sous un bloc : notes, motifs, route au-delà, demi-tour.

Toutes les traces sont **fabriquées** autour de (0.0, 0.0), en pleine mer dans
le golfe de Guinée : aucune coordonnée réelle, aucun réseau (règles absolues 1
et 3).
"""

from __future__ import annotations

import math
from dataclasses import replace
from pathlib import Path

import pytest

from ourouler.noyau.trace import PointTrace, Segment, Trace
from ourouler.seance import terrain
from ourouler.seance.placement import PENTE_DEMI_TOUR_MAX
from ourouler.seance.terrain import (
    PENALITE_BLOC_TRONQUE,
    POIDS_CARREFOUR,
    POIDS_KM_BATI,
    demi_tour_faisable,
    evaluer_couloir,
    route_au_dela,
)

RACINE = Path(__file__).resolve().parents[1]
LAT_FICTIVE = 0.0
LON_FICTIVE = 0.0
#: Un degré de longitude à l'équateur, en mètres (sphère de rayon 6 371 km).
DEGRE_M = math.radians(1.0) * 6_371_000.0
PAS_M = 50.0


def ligne_droite(
    longueur_m: float, altitudes=None, pas_m: float = PAS_M
) -> list[PointTrace]:
    """Une ligne droite plein est depuis (0, 0), un point tous les `pas_m`.

    `altitudes` est une fonction distance → altitude ; sans elle, l'altitude
    est plate à 100 m.
    """
    altitudes = altitudes or (lambda _d: 100.0)
    nombre = int(round(longueur_m / pas_m)) + 1
    points = []
    for i in range(nombre):
        distance = i * pas_m
        points.append(
            PointTrace(
                lat=LAT_FICTIVE,
                lon=LON_FICTIVE + distance / DEGRE_M,
                alt_m=altitudes(distance),
                dist_m=distance,
            )
        )
    return points


def anneau(rayon_deg: float = 0.01, nombre: int = 120) -> list[PointTrace]:
    """Une boucle fermée : le dernier point est exactement le premier."""
    bruts = []
    for i in range(nombre):
        angle = 2 * math.pi * i / nombre
        bruts.append(
            (LAT_FICTIVE + rayon_deg * math.cos(angle), LON_FICTIVE + rayon_deg * math.sin(angle))
        )
    bruts.append(bruts[0])
    points, cumul = [], 0.0
    for i, (lat, lon) in enumerate(bruts):
        if i:
            precedent = points[-1]
            cumul += math.hypot(
                (lat - precedent.lat) * DEGRE_M, (lon - precedent.lon) * DEGRE_M
            )
        points.append(PointTrace(lat=lat, lon=lon, alt_m=100.0, dist_m=cumul))
    return points


def trace_de(points: list[PointTrace], segments: list[Segment] | None = None) -> Trace:
    return Trace(
        nom="fabriquée",
        points=points,
        segments=segments if segments is not None else [],
        distance_m=points[-1].dist_m,
        denivele_m=0.0,
        temps_moteur_s=None,
    )


def un_segment(points: list[PointTrace], **tags: str) -> list[Segment]:
    """Un unique tronçon couvrant tout le tracé."""
    return [
        Segment(
            debut_idx=0,
            fin_idx=len(points) - 1,
            longueur_m=points[-1].dist_m,
            tags=dict(tags) or {"highway": "tertiary"},
        )
    ]


def decouper(points: list[PointTrace], coupes: list[int], tags: dict[str, str]) -> list[Segment]:
    """Des tronçons consécutifs finissant aux indices `coupes`, tous avec `tags`."""
    segments, debut = [], 0
    for fin in coupes:
        segments.append(
            Segment(
                debut_idx=debut,
                fin_idx=fin,
                longueur_m=points[fin].dist_m - points[debut].dist_m,
                tags=dict(tags),
            )
        )
        debut = fin
    return segments


# --- un couloir parfait -------------------------------------------------------


def test_couloir_plat_et_calme_note_zero():
    points = ligne_droite(3000.0)
    trace = trace_de(points, un_segment(points, highway="tertiary", maxspeed="80"))
    note = evaluer_couloir(trace, 500.0, 2000.0)
    assert note.note == pytest.approx(0.0)
    assert note.motifs == []
    assert note.carrefours == 0
    assert note.km_batis == pytest.approx(0.0)
    assert note.descente_m == pytest.approx(0.0)
    assert note.montee_m == pytest.approx(0.0)
    assert note.pente_moyenne == pytest.approx(0.0)


# --- deux feux ----------------------------------------------------------------


def test_deux_feux_dans_le_bloc():
    points = ligne_droite(3000.0)
    segments = decouper(points, [20, 30, 40, len(points) - 1], {"highway": "tertiary"})
    segments[0].node_tags = {"highway": "traffic_signals"}  # au km 1,0
    segments[1].node_tags = {"highway": "traffic_signals"}  # au km 1,5
    segments[2].node_tags = {"highway": "traffic_signals"}  # au km 2,0, hors du bloc
    trace = trace_de(points, segments)

    note = evaluer_couloir(trace, 500.0, 1200.0)  # de 500 m à 1 700 m
    assert note.carrefours == 2
    assert note.note == pytest.approx(2 * POIDS_CARREFOUR)
    assert "deux feux" in note.motifs


def test_un_stop_se_dit_au_singulier():
    points = ligne_droite(2000.0)
    segments = decouper(points, [20, len(points) - 1], {"highway": "tertiary"})
    segments[0].node_tags = {"highway": "stop"}
    trace = trace_de(points, segments)

    note = evaluer_couloir(trace, 0.0, 1500.0)
    assert note.carrefours == 1
    assert "un stop" in note.motifs


def test_un_noeud_sans_highway_connu_ne_compte_pas():
    points = ligne_droite(2000.0)
    segments = decouper(points, [20, len(points) - 1], {"highway": "tertiary"})
    segments[0].node_tags = {"barrier": "gate"}
    trace = trace_de(points, segments)

    assert evaluer_couloir(trace, 0.0, 1500.0).carrefours == 0


# --- une descente -------------------------------------------------------------


def test_descente_de_un_kilometre():
    # Plat jusqu'au km 1, puis −3 % sur 1 km, puis plat.
    def altitude(d: float) -> float:
        if d <= 1000.0:
            return 100.0
        if d >= 2000.0:
            return 70.0
        return 100.0 - 0.03 * (d - 1000.0)

    points = ligne_droite(3000.0, altitude)
    trace = trace_de(points, un_segment(points, highway="tertiary"))

    note = evaluer_couloir(trace, 0.0, 3000.0)
    assert note.descente_m == pytest.approx(30.0, abs=1.0)
    # Une pente est une tangente, comme partout ailleurs dans le dépôt.
    assert note.pente_max == pytest.approx(-0.03, abs=0.002)
    assert note.montee_m == pytest.approx(0.0)
    assert any("descente de 1,0 km" in motif for motif in note.motifs)
    assert note.note > 1.5


def test_les_pentes_sont_des_tangentes_pas_des_pourcentages():
    """Convention du dépôt (`physique.modele`, `--pente-max`, `placement`).

    `placement.PENTE_DEMI_TOUR_MAX` compare directement `note.pente_moyenne`
    à 0,015 : une pente rendue en pourcentage y refuserait tout demi-tour dès
    le premier faux-plat.
    """
    points = ligne_droite(2000.0, lambda d: 100.0 + 0.04 * d)  # +4 % d'un bout à l'autre
    trace = trace_de(points, un_segment(points, highway="tertiary"))

    note = evaluer_couloir(trace, 0.0, 2000.0)
    assert note.pente_moyenne == pytest.approx(0.04, abs=0.002)
    assert note.pente_max == pytest.approx(0.04, abs=0.002)
    # Le pourcentage ne survit que dans les motifs, qui se lisent.
    assert any("2,0 %" in motif for motif in note.motifs)


# --- ce que coûte une descente dépend de l'intensité du bloc -------------------


def _trace_descente_de_un_km() -> Trace:
    """3 km de tracé dont un kilomètre à −3 % au milieu : 30 m de descente."""

    def altitude(d: float) -> float:
        if d <= 1000.0:
            return 100.0
        if d >= 2000.0:
            return 70.0
        return 100.0 - 0.03 * (d - 1000.0)

    points = ligne_droite(3000.0, altitude)
    return trace_de(points, un_segment(points, highway="tertiary"))


def test_la_table_des_facteurs_de_zone_est_croissante_et_couvre_tout():
    """La table doit être lisible de haut en bas et ne laisser aucun trou.

    Bornes strictement croissantes, facteurs strictement croissants (« son
    poids négatif augmente avec la zone »), dernière borne infinie : sans quoi
    une intensité tomberait entre deux lignes, ou une zone plus dure coûterait
    moins cher qu'une zone plus facile.
    """
    bornes = [borne for borne, _, _ in terrain.FACTEURS_ZONE_DESCENTE]
    facteurs = [facteur for _, facteur, _ in terrain.FACTEURS_ZONE_DESCENTE]
    adjectifs = [adjectif for _, _, adjectif in terrain.FACTEURS_ZONE_DESCENTE]

    assert bornes == sorted(bornes) and len(set(bornes)) == len(bornes)
    assert facteurs == sorted(facteurs) and len(set(facteurs)) == len(facteurs)
    assert bornes[-1] == math.inf, "la dernière ligne doit attraper toutes les intensités"
    assert all(adjectifs), "chaque ligne doit porter de quoi écrire un motif"


@pytest.mark.parametrize(
    ("fraction", "attendu"),
    [
        (0.50, 0.4),  # bien en dessous de la zone de travail
        (0.7499, 0.4),
        (0.75, 1.0),  # borne haute exclue : 75 % est déjà le Z3 « tolérable »
        (0.85, 1.0),  # « faire du Z3 en descente, ça reste possible »
        (0.90, 2.0),
        (1.00, 2.0),
        (1.05, 4.0),  # « Z5 en descente, pas possible ou presque »
        (1.30, 4.0),
    ],
)
def test_le_facteur_de_zone_suit_la_table(fraction, attendu):
    assert terrain.facteur_zone(fraction) == pytest.approx(attendu)


@pytest.mark.parametrize("fraction", [None, 0.0, -1.0, math.nan, math.inf])
def test_une_intensite_illisible_laisse_le_facteur_neutre(fraction):
    """Une ignorance n'est ni une excuse ni un soupçon : le poids reste nu."""
    assert terrain.facteur_zone(fraction) == terrain.FACTEUR_ZONE_INCONNUE


def test_sans_intensite_la_note_est_exactement_celle_d_avant():
    """Aucun appelant existant ne change de comportement (contrat du point 1)."""
    trace = _trace_descente_de_un_km()

    muette = evaluer_couloir(trace, 0.0, 3000.0)
    explicite = evaluer_couloir(trace, 0.0, 3000.0, puissance_w=None, ftp_w=None)

    assert muette.note == pytest.approx(explicite.note)
    assert muette.facteur_descente == terrain.FACTEUR_ZONE_INCONNUE
    assert muette.motifs == explicite.motifs
    assert not any("intensité" in motif for motif in muette.motifs)


@pytest.mark.parametrize(
    ("puissance", "ftp"),
    [(210.0, None), (None, 260.0), (210.0, 0.0), (210.0, -260.0), (math.nan, 260.0)],
)
def test_une_intensite_a_moitie_donnee_ne_change_rien(puissance, ftp):
    """Puissance sans FTP, FTP nulle, valeur non finie : on ne devine pas."""
    trace = _trace_descente_de_un_km()
    nue = evaluer_couloir(trace, 0.0, 3000.0)

    note = evaluer_couloir(trace, 0.0, 3000.0, puissance_w=puissance, ftp_w=ftp)

    assert note.note == pytest.approx(nue.note)
    assert note.facteur_descente == terrain.FACTEUR_ZONE_INCONNUE


def test_la_meme_descente_coute_quatre_fois_plus_cher_en_z5_qu_en_z3():
    """Décision du mainteneur du 13/09 : « son poids négatif augmente avec la zone ».

    Même couloir, même descente de 30 m : seule l'intensité demandée change.
    L'écart de note doit valoir exactement l'écart des facteurs appliqué au
    seul poste « descente », le reste de la note étant identique.
    """
    trace = _trace_descente_de_un_km()
    ftp = 260.0

    z2 = evaluer_couloir(trace, 0.0, 3000.0, puissance_w=0.65 * ftp, ftp_w=ftp)
    z3 = evaluer_couloir(trace, 0.0, 3000.0, puissance_w=0.85 * ftp, ftp_w=ftp)
    seuil = evaluer_couloir(trace, 0.0, 3000.0, puissance_w=1.00 * ftp, ftp_w=ftp)
    z5 = evaluer_couloir(trace, 0.0, 3000.0, puissance_w=1.10 * ftp, ftp_w=ftp)

    assert z2.note < z3.note < seuil.note < z5.note
    assert (z2.facteur_descente, z3.facteur_descente) == (0.4, 1.0)
    assert (seuil.facteur_descente, z5.facteur_descente) == (2.0, 4.0)
    # Le supplément est celui de la descente, et de rien d'autre.
    descente = z3.descente_m * terrain.POIDS_M_DESCENTE
    assert z5.note - z3.note == pytest.approx(3.0 * descente)
    assert z3.note - z2.note == pytest.approx(0.6 * descente)
    # Les mètres mesurés, eux, ne bougent pas : c'est leur prix qui change.
    assert {note.descente_m for note in (z2, z3, seuil, z5)} == {z3.descente_m}


def test_seule_la_descente_depend_de_l_intensite():
    """Village, virages et montées se paient pareil quelle que soit la zone.

    Le mainteneur n'a tranché que la descente ; élargir le facteur au reste de
    la note serait décider à sa place.
    """
    points = ligne_droite(2000.0, lambda d: 100.0 + 0.04 * d)  # +4 %, aucune descente
    trace = trace_de(points, un_segment(points, highway="residential"))

    facile = evaluer_couloir(trace, 0.0, 2000.0, puissance_w=150.0, ftp_w=260.0)
    dur = evaluer_couloir(trace, 0.0, 2000.0, puissance_w=300.0, ftp_w=260.0)

    assert facile.descente_m == pytest.approx(0.0)
    assert dur.note == pytest.approx(facile.note)
    assert dur.motifs == facile.motifs


def test_le_motif_dit_ce_que_la_descente_vaut_a_cette_intensite():
    """« descente de 1,0 km, rédhibitoire à cette intensité » — et pas seulement
    « descente de 1,0 km » : deux notes très différentes portaient le même mot."""
    trace = _trace_descente_de_un_km()
    ftp = 260.0

    z5 = evaluer_couloir(trace, 0.0, 3000.0, puissance_w=1.10 * ftp, ftp_w=ftp)
    z3 = evaluer_couloir(trace, 0.0, 3000.0, puissance_w=0.85 * ftp, ftp_w=ftp)
    z2 = evaluer_couloir(trace, 0.0, 3000.0, puissance_w=0.65 * ftp, ftp_w=ftp)

    assert "descente de 1,0 km, rédhibitoire à cette intensité" in z5.motifs
    assert "descente de 1,0 km, tolérable à cette intensité" in z3.motifs
    assert "descente de 1,0 km, peu gênante à cette intensité" in z2.motifs


def test_le_motif_de_plusieurs_descentes_s_accorde_au_pluriel():
    def altitude(d: float) -> float:
        """Deux descentes de 400 m à −4 %, séparées par un plat."""
        if d <= 500.0:
            return 100.0
        if d <= 900.0:
            return 100.0 - 0.04 * (d - 500.0)
        if d <= 1400.0:
            return 84.0
        if d <= 1800.0:
            return 84.0 - 0.04 * (d - 1400.0)
        return 68.0

    points = ligne_droite(2500.0, altitude)
    trace = trace_de(points, un_segment(points, highway="tertiary"))

    note = evaluer_couloir(trace, 0.0, 2500.0, puissance_w=286.0, ftp_w=260.0)

    assert len([m for m in note.motifs if "descentes" in m]) == 1
    assert any("descentes" in m and "rédhibitoires à cette intensité" in m for m in note.motifs)


# --- chaque poids doit être auditable par la validation rétrospective ---------

#: Les poids que le script de validation **ne peut pas** mesurer, et qui le
#: disent en toutes lettres dans leur commentaire. `POIDS_CARREFOUR` tarife un
#: feu ou un stop sous un bloc : une sortie enregistrée est une trace GPS, elle
#: ne porte aucun nœud OSM. Ce poids reste un raisonnement produit, et la règle
#: absolue 5 demande qu'il soit annoncé comme tel, pas qu'il disparaisse.
POIDS_NON_MESURABLES = {"POIDS_CARREFOUR"}


def _validation():
    """Le script `scripts/validation/terrain_retrospectif.py`, chargé par chemin.

    Il n'est pas collecté par pytest (il vit hors de `tests/`) et
    c'est voulu : il lit le cache réel du mainteneur. On l'importe quand même
    ici, parce que son **contenu** — la liste des postes qu'il diagnostique —
    est ce qui rend les poids auditables, et qu'un poids qui sort de cette
    liste redevient une opinion.
    """
    import importlib.util
    import sys

    if "terrain_retrospectif" in sys.modules:
        return sys.modules["terrain_retrospectif"]
    chemin = RACINE / "scripts" / "validation" / "terrain_retrospectif.py"
    spec = importlib.util.spec_from_file_location("terrain_retrospectif", chemin)
    module = importlib.util.module_from_spec(spec)
    sys.modules["terrain_retrospectif"] = module
    spec.loader.exec_module(module)
    return module


def test_chaque_poids_de_la_note_est_mesure_par_le_script_de_validation():
    """D1 : un poids qu'aucun mode du script ne mesure ne peut pas être justifié.

    Les docstrings des poids citent des chiffres. Ces chiffres doivent être
    reproductibles en relançant le script versionné — sinon ils redeviennent
    des opinions (règle absolue 5), et c'est exactement ce qui était arrivé à
    `POIDS_IRREGULARITE`, dont l'écart-type n'était pas lisible depuis
    `NoteBloc`.
    """
    poids = {nom for nom in dir(terrain) if nom.startswith("POIDS_")}
    assert poids, "aucun poids trouvé : le test ne mesure rien"
    mesures = {nom_poids for _, nom_poids, _ in _validation().POSTES}
    orphelins = sorted(poids - mesures - POIDS_NON_MESURABLES)
    assert not orphelins, (
        f"poids qu'aucun poste du script de validation ne mesure : {orphelins} — "
        "soit le script les diagnostique, soit leur commentaire déclare qu'ils ne "
        "sont pas mesurables, comme POIDS_CARREFOUR"
    )


def test_chaque_poste_du_script_lit_un_champ_distinct_de_la_note():
    """Le corollaire : un poste qui ne lirait rien passerait inaperçu.

    On fabrique une `NoteBloc` neutre, on met **un seul** champ à une valeur
    reconnaissable, et on vérifie que le poste correspondant est le seul à
    bouger. Un poste branché sur le mauvais champ, ou sur rien, tombe ici.
    """
    validation = _validation()
    neutre = terrain.NoteBloc(note=0.0)
    reference = validation._par_km(neutre, 1000.0)
    champs = {
        "carrefours": ("carrefours", 7),
        "km bâtis": ("km_batis", 0.5),
        "descente (m)": ("descente_m", 42.0),
        "montée (m)": ("montee_m", 23.0),
        "irrégularité %": ("irregularite", 0.017),
    }
    postes = [nom for nom, _, _ in validation.POSTES]
    assert sorted(champs) == sorted(postes), (
        f"postes du script : {postes}, champs couverts par ce test : {sorted(champs)}"
    )
    for poste, (champ, valeur) in champs.items():
        modifiee = replace(neutre, **{champ: valeur})
        mesure = validation._par_km(modifiee, 1000.0)
        bouges = sorted(nom for nom in postes if mesure[nom] != reference[nom])
        assert bouges == [poste], (
            f"mettre {champ}={valeur} fait bouger {bouges} au lieu de [{poste!r}] : "
            "un poste du diagnostic ne lit pas le champ qu'il annonce"
        )


def test_le_script_echoue_quand_les_deux_modes_divergent(capsys):
    """D2 : le mode dégradé n'a le droit ni de conclure seul, ni de se taire.

    Il conclut NON là où le mode nominal conclut OUI, parce qu'il devine les
    blocs à partir de la puissance et en découpe d'autres. Laisser ce NON
    passer pour un verdict — ou le laisser sortir en 1 avec « les poids sont
    faux » — revient à laisser croire que les deux modes se valent. Le script
    échoue donc **sur la divergence**, et le message la nomme.
    """
    validation = _validation()
    attendu = bool(validation.REFERENCE_NOMINALE["verdict"])

    assert validation._confronter_au_nominal(attendu, blocs=11) == 0
    accord = capsys.readouterr()
    assert "ACCORD DES DEUX MODES" in accord.out

    assert validation._confronter_au_nominal(not attendu, blocs=15) == 1
    divergence = capsys.readouterr()
    assert "LES DEUX MODES DIVERGENT" in divergence.err, divergence
    assert "c'est lui qui fait foi" in divergence.err
    assert "Ce n'est pas un désaveu des poids" in divergence.err


def _bilan_qui_echoue(validation):
    """Un bilan de blocs courts dont la note vaut 80 % du hasard : verdict NON."""
    bloc = validation.Bloc(
        libelle="bloc 1", debut_m=0.0, longueur_m=1500.0, duree_s=300.0, puissance_w=210.0
    )
    comparaison = validation.Comparaison(
        sortie="sortie fabriquée",
        bloc=bloc,
        note=terrain.NoteBloc(note=0.8),
        au_hasard=[terrain.NoteBloc(note=1.0) for _ in range(20)],
        part_tags=1.0,
    )
    return [validation.Bilan(validation.categorie(bloc.longueur_m), [comparaison])]


def test_le_mode_degrade_n_accuse_jamais_les_poids(capsys):
    """« Les poids sont faux » est une affirmation sur le modèle.

    Un mode qui ne borne pas correctement les blocs n'est pas en position de la
    faire : il conclut NON sur ce qu'il a mesuré, et dit que ce n'est pas le
    même objet. Seul le mode qui fait foi accuse.
    """
    validation = _validation()
    bilans = _bilan_qui_echoue(validation)

    assert validation._juger_les_placables(bilans, fait_foi=True) is False
    qui_fait_foi = capsys.readouterr().out
    assert "Les poids sont faux" in qui_fait_foi

    assert validation._juger_les_placables(bilans, fait_foi=False) is False
    degrade = capsys.readouterr().out
    assert "Les poids sont faux" not in degrade, degrade
    assert "ce mode ne juge pas les poids" in degrade
    # Et le pourcentage n'est plus arrondi à l'unité : « 70 % pour un seuil de
    # 70 % » se lisait comme une conclusion qui se contredit.
    assert "80.0%" in degrade, degrade


def test_la_conclusion_de_la_validation_est_ecrite_dans_la_demarche():
    """D2 : la *definition of done* dit « le script tourne et **conclut** ».

    Le résultat n'existait nulle part dans le dépôt, hors des docstrings de
    constantes : un lecteur sans la clé d'API du mainteneur ne pouvait pas
    savoir ce que le mode qui fait foi avait conclu. Il est écrit dans
    `docs/demarche.md` (§5), avec son critère, le mode qui fait foi et ses
    deux limites ; le README, devenu court, y renvoie.
    """
    demarche = (RACINE / "docs" / "demarche.md").read_text(encoding="utf-8")
    assert "scripts/validation/terrain_retrospectif.py" in demarche
    for morceau in ("70 %", "mode nominal", "carrefour", "6 km"):
        assert morceau in demarche, f"docs/demarche.md ne dit pas « {morceau} »"


def test_la_pente_moyenne_se_divise_par_la_longueur_du_profil_pas_du_couloir():
    """D4 : sur un couloir partiellement dépourvu d'altitude, la pente était divisée par deux.

    `_releve_pentes` ne garde dans son profil que les points qui portent une
    altitude. Diviser le dénivelé par la longueur **du couloir** sous-estimait
    donc la pente d'autant que le couloir était mal renseigné — et c'est cette
    pente-là que `placement.PENTE_DEMI_TOUR_MAX` compare à 0,015 pour
    autoriser un demi-tour. Une côte à 4 % lue à 2 % passait le seuil des 1,5 %
    dès que les trois quarts du couloir manquaient d'altitude.

    Ici : 2 km de couloir, mais seuls les 500 premiers mètres portent une
    altitude, et ils montent de 20 m. La pente mesurée est celle de ces 500 m
    (+4 %), pas celle qu'on obtiendrait en étalant les 20 m sur 2 km (+1 %).
    """
    points = ligne_droite(2000.0, lambda d: 100.0 + 0.04 * d if d <= 500.0 else None)
    trace = trace_de(points, un_segment(points, highway="tertiary"))

    note = evaluer_couloir(trace, 0.0, 2000.0)
    assert note.pente_moyenne == pytest.approx(0.04, abs=0.002)
    assert note.pente_moyenne > PENTE_DEMI_TOUR_MAX, (
        "une côte à 4 % ne doit pas passer pour un faux-plat propice au demi-tour"
    )


def test_un_faux_plat_descendant_court_ne_compte_pas():
    # 200 m à −3 %, moins que `LONGUEUR_DESCENTE_M`.
    def altitude(d: float) -> float:
        return 100.0 - 0.03 * min(max(d - 500.0, 0.0), 200.0)

    points = ligne_droite(2000.0, altitude)
    trace = trace_de(points, un_segment(points, highway="tertiary"))
    assert evaluer_couloir(trace, 0.0, 2000.0).descente_m == pytest.approx(0.0)


def test_montee_douce_non_penalisee():
    points = ligne_droite(2000.0, lambda d: 100.0 + 0.015 * d)  # +1,5 %
    trace = trace_de(points, un_segment(points, highway="tertiary"))
    note = evaluer_couloir(trace, 0.0, 2000.0)
    assert note.montee_m == pytest.approx(0.0)
    assert note.note == pytest.approx(0.0, abs=0.01)


# --- zone bâtie ---------------------------------------------------------------


def test_zone_batie_comptee_au_kilometre():
    points = ligne_droite(3000.0)
    milieu = 20  # au km 1,0
    fin = 40  # au km 2,0
    segments = [
        Segment(0, milieu, points[milieu].dist_m, {"highway": "tertiary"}),
        Segment(
            milieu,
            fin,
            points[fin].dist_m - points[milieu].dist_m,
            {"highway": "residential"},
        ),
        Segment(fin, len(points) - 1, points[-1].dist_m - points[fin].dist_m, {"highway": "tertiary"}),
    ]
    trace = trace_de(points, segments)

    note = evaluer_couloir(trace, 0.0, 3000.0)
    assert note.km_batis == pytest.approx(1.0, abs=0.06)
    assert any("zone bâtie" in motif for motif in note.motifs)
    assert note.note == pytest.approx(POIDS_KM_BATI, abs=0.15)


def test_un_village_qui_s_arrete_avant_le_bloc_ne_lui_est_pas_facture():
    """Décision du 13/09 : aucune évaluation sous une récupération.

    Le village occupe le premier kilomètre — là où tombe la récup — et le
    bloc commence exactement là où il finit. Le point de jonction appartient
    aux deux tronçons : lui demander ses tags faisait payer le village au bloc.
    """
    points = ligne_droite(3000.0)
    jonction = 20  # au km 1,0
    segments = [
        Segment(0, jonction, points[jonction].dist_m, {"highway": "residential"}),
        Segment(
            jonction,
            len(points) - 1,
            points[-1].dist_m - points[jonction].dist_m,
            {"highway": "tertiary"},
        ),
    ]
    trace = trace_de(points, segments)

    note = evaluer_couloir(trace, 1000.0, 2000.0)
    assert note.km_batis == pytest.approx(0.0)
    assert note.note == pytest.approx(0.0)


def test_maxspeed_50_vaut_zone_batie():
    points = ligne_droite(2000.0)
    trace = trace_de(points, un_segment(points, highway="tertiary", maxspeed="50"))
    assert evaluer_couloir(trace, 0.0, 2000.0).km_batis == pytest.approx(2.0, abs=0.06)


def test_maxspeed_illisible_ne_bat_rien():
    points = ligne_droite(2000.0)
    trace = trace_de(points, un_segment(points, highway="tertiary", maxspeed="FR:rural"))
    assert evaluer_couloir(trace, 0.0, 2000.0).km_batis == pytest.approx(0.0)


def test_sans_segments_les_routes_sont_dites_inconnues():
    points = ligne_droite(2000.0)
    note = evaluer_couloir(trace_de(points), 0.0, 1000.0)
    assert note.km_batis == pytest.approx(0.0)
    assert "routes inconnues" in note.motifs


def test_sans_altitude_le_motif_le_dit():
    points = [
        PointTrace(lat=p.lat, lon=p.lon, alt_m=None, dist_m=p.dist_m)
        for p in ligne_droite(2000.0)
    ]
    note = evaluer_couloir(trace_de(points, un_segment(points, highway="tertiary")), 0.0, 1000.0)
    assert note.pente_moyenne == pytest.approx(0.0)
    assert "altitude inconnue" in note.motifs


# --- bloc plus long que le tracé ----------------------------------------------


def test_bloc_plus_long_que_le_trace():
    points = ligne_droite(1000.0)
    trace = trace_de(points, un_segment(points, highway="tertiary"))
    note = evaluer_couloir(trace, 0.0, 5000.0)
    assert note.note >= PENALITE_BLOC_TRONQUE
    assert "bloc plus long que le tracé disponible" in note.motifs


def test_bloc_plus_long_que_la_boucle():
    points = anneau()
    trace = trace_de(points, un_segment(points, highway="tertiary"))
    assert trace.bornee()
    note = evaluer_couloir(trace, 0.0, 10 * points[-1].dist_m)
    assert "bloc plus long que le tracé disponible" in note.motifs


def test_trace_de_deux_points_ne_leve_pas():
    points = ligne_droite(100.0, pas_m=100.0)
    note = evaluer_couloir(trace_de(points), 0.0, 50.0)
    assert note.note >= 0.0


def test_trace_vide_rend_une_note_sans_lever():
    trace = Trace(
        nom="vide", points=[], segments=[], distance_m=0.0, denivele_m=None, temps_moteur_s=None
    )
    note = evaluer_couloir(trace, 0.0, 1000.0)
    assert note.note == pytest.approx(PENALITE_BLOC_TRONQUE)
    assert note.motifs == ["aucun tracé sous le bloc"]


def test_position_negative_est_ramenee_dans_le_trace():
    points = ligne_droite(2000.0)
    trace = trace_de(points, un_segment(points, highway="tertiary"))
    note = evaluer_couloir(trace, -500.0, 1000.0)
    assert note.note == pytest.approx(0.0)
    assert note.motifs == []


def test_bloc_a_cheval_sur_la_fermeture_dune_boucle():
    points = anneau()
    total = points[-1].dist_m
    trace = trace_de(points, un_segment(points, highway="tertiary"))
    # Un bloc qui commence à 300 m de la fin et qui déborde sur le début.
    note = evaluer_couloir(trace, total - 300.0, 1000.0)
    assert "bloc plus long que le tracé disponible" not in note.motifs
    # Le même bloc, demandé au-delà d'un tour complet, tombe au même endroit.
    memo = evaluer_couloir(trace, total * 2 - 300.0, 1000.0)
    assert memo.note == pytest.approx(note.note)


# --- route au-delà ------------------------------------------------------------


def test_route_au_dela_sur_trace_ouvert():
    points = ligne_droite(2000.0)
    trace = trace_de(points)
    assert route_au_dela(trace, 1000.0, 800.0) is True
    assert route_au_dela(trace, 1500.0, 800.0) is False
    assert route_au_dela(trace, 1500.0, 0.0) is True


def test_route_au_dela_sur_boucle_fermee():
    points = anneau()
    total = points[-1].dist_m
    trace = trace_de(points)
    assert trace.bornee()
    # Où qu'on soit sur la boucle, on peut continuer : la route ne s'arrête pas.
    assert route_au_dela(trace, total - 10.0, 800.0) is True
    # Y compris pour un besoin plus long que le tour lui-même (« ou si le
    # tracé est une boucle fermée ») : on repasse au même endroit,
    # mais on roule. En pratique le besoin vaut une demi-récup, jamais un tour.
    assert route_au_dela(trace, 0.0, total * 2) is True


def test_route_au_dela_sur_trace_sans_longueur():
    trace = Trace(
        nom="vide", points=[], segments=[], distance_m=0.0, denivele_m=None, temps_moteur_s=None
    )
    assert route_au_dela(trace, 0.0, 300.0) is False


# --- demi-tour ----------------------------------------------------------------


def test_demi_tour_refuse_sur_une_secondary():
    points = ligne_droite(2000.0)
    trace = trace_de(points, un_segment(points, highway="secondary"))
    assert demi_tour_faisable(trace, 1000.0) is False


def test_demi_tour_accepte_sur_une_tertiary():
    points = ligne_droite(2000.0)
    trace = trace_de(points, un_segment(points, highway="tertiary"))
    assert demi_tour_faisable(trace, 1000.0) is True


def test_demi_tour_accepte_quand_on_ne_sait_pas():
    points = ligne_droite(2000.0)
    assert demi_tour_faisable(trace_de(points), 1000.0) is True


def test_demi_tour_lit_le_troncon_de_la_position():
    points = ligne_droite(2000.0)
    coupe = 20  # au km 1,0
    segments = [
        Segment(0, coupe, points[coupe].dist_m, {"highway": "secondary"}),
        Segment(
            coupe,
            len(points) - 1,
            points[-1].dist_m - points[coupe].dist_m,
            {"highway": "unclassified"},
        ),
    ]
    trace = trace_de(points, segments)
    assert demi_tour_faisable(trace, 500.0) is False
    assert demi_tour_faisable(trace, 1500.0) is True
    # Dix mètres après la jonction, on est déjà sur l'unclassified : le point
    # de jonction porte les tags des deux tronçons, c'est celui qu'on parcourt
    # qui décide.
    assert demi_tour_faisable(trace, 1010.0) is True
