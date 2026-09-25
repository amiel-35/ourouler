"""L5.1 — le vent dans le placement, mis à l'épreuve **en aveugle**.

Écrit contre `docs/journal/sprints/sprint5_contrat.md` §1 et CLAUDE.md, sans avoir lu
l'implémentation : ces tests sont datés d'avant elle.

Ce que ce fichier surveille, par ordre de gravité décroissante.

1. **La convention d'angle.** `v_face = V · cos(vent_depuis_deg − cap_effectif)`,
   positive de face. Un signe inversé est l'erreur la plus probable du lot et
   la plus silencieuse : il laisse intactes toutes les moyennes, toutes les
   sommes et toutes les valeurs absolues. Seul un cas signé le voit. Les
   quadrants sont donc balayés sur des caps **non cardinaux** (17°, 103°,
   198°, 291°) : sur 0/90/180/270, une confusion latitude/longitude ou un
   décalage de 90° passe par chance.
2. **Le passage par le nord.** 359° et 1° font 0°, pas 180°. C'est la faute
   que `meteo_trace._angulaire` évite déjà et qu'un champ de vent réécrit
   dans son coin réintroduirait.
3. **Le sens.** Le placement fait des demi-tours ; `sens = -1` doit inverser
   la composante exactement, sans quoi un bloc de retour serait calculé vent
   de face alors qu'il l'a dans le dos.
4. **Le vent inconnu qui se déguise en vent nul.** `vent_kmh = 0` et
   `vent_kmh = None` doivent se distinguer : le premier est une mesure, le
   second une absence. `if not vent_kmh` les confond, et le contrat exige
   `complet = False` pour le second seulement.
5. **La non-régression.** `vent=None` doit rendre **exactement** le placement
   d'aujourd'hui. Les valeurs de `GOLDEN` ont été calculées sur le code de
   `sprint-5` **avant** le lot, sur deux cas non triviaux ; elles ne sont pas
   recopiées d'une exécution postérieure au lot, ce qui les rendrait vides de
   sens.

Discipline appliquée à chaque test : quelle mutation du code l'attrape ? Quand
ce n'est pas évident, c'est écrit dans le test. Les contrôles positifs sont
explicites (`test_..._controle_positif`) : sans eux, une implémentation qui
ignorerait purement et simplement le vent passerait toute la section 5.

Tant que `ourouler.seance.vent` n'existe pas, tout ce fichier se met en
`skip` sauf `test_sentinelle_l5_1_pas_encore_livre`, qui **échoue** : un
dossier entièrement vert parce qu'entièrement sauté se lit « rien à
signaler », ce qui serait faux.
"""

from __future__ import annotations

import inspect
import math
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import fabriques
import fabriques4
import fabriques5
import pytest

from ourouler.noyau.erreurs import ErreurUtilisateur

MOTIF_VENT = (
    "module attendu par le contrat L5.1 §1.2 b) absent (ourouler.seance.vent) — "
    "normal tant que le lot n'est pas fusionné"
)
MOTIF_METEO = "module du sprint 2 absent (ourouler.boucle.meteo_trace)"
MOTIF_PLACEMENT = "module du sprint 4 absent (ourouler.seance.placement)"

#: Ce qu'une entrée franchement absurde a le droit de lever. Tout le reste
#: (TypeError, IndexError, ZeroDivisionError…) est un bug, pas un refus.
ERREURS = (ErreurUtilisateur, ValueError)

#: Caps de travail, volontairement non cardinaux (voir le docstring du module).
CAPS = (17.0, 103.0, 198.0, 291.0)


# --- accès aux interfaces du contrat ----------------------------------------


def _meteo() -> Any:
    return pytest.importorskip("ourouler.boucle.meteo_trace", reason=MOTIF_METEO)


def _placement() -> Any:
    return pytest.importorskip("ourouler.seance.placement", reason=MOTIF_PLACEMENT)


def _vent() -> Any:
    return pytest.importorskip("ourouler.seance.vent", reason=MOTIF_VENT)


def _champ(directions, *, pas_m: float = 5000.0, vitesses=None, **kw: Any) -> Any:
    """Un `ChampVent` sur une série d'échantillons construits par écart voulu."""
    echantillons = fabriques5.serie(_meteo(), directions, pas_m=pas_m, vitesses_kmh=vitesses)
    return _vent().ChampVent(echantillons, **kw)


def _parametres() -> Any:
    import fabriques3

    return fabriques3.parametres(pytest.importorskip("ourouler.physique.modele"))


def _placer_accepte_vent() -> bool:
    return "vent" in inspect.signature(_placement().placer).parameters


def _exiger_parametre_vent() -> None:
    if not _placer_accepte_vent():
        pytest.skip(
            "placer(...) n'a pas encore de paramètre `vent` (contrat L5.1 §1.2 b, "
            "« ChampVent optionnel de bout en bout »)"
        )


def _resultat_ou_erreur(appel):
    """(valeur, None) ou (None, exception) — pour les entrées dont le contrat
    ne fixe pas le sort, où l'on exige seulement qu'il n'y ait pas de bug."""
    try:
        return appel(), None
    except ERREURS as e:
        return None, e


# --- sentinelle -------------------------------------------------------------


def test_sentinelle_l5_1_pas_encore_livre():
    """Le seul test de ce fichier qui échoue quand le lot est absent.

    Sans lui, l'ensemble se lirait « 80 tests passés » alors qu'aucun n'aurait
    rien vérifié. Quand L5.1 est fusionné, il devient vert et les autres
    s'exécutent pour de bon.
    """
    try:
        import ourouler.seance.vent as mod
    except ModuleNotFoundError:  # pragma: no cover - chemin nominal avant fusion
        pytest.fail(
            "ourouler.seance.vent est absent : le lot L5.1 n'est pas (encore) livré. "
            "Tous les autres tests de ce fichier sont en skip et ne vérifient rien."
        )
    assert hasattr(mod, "ChampVent"), "le contrat L5.1 §1.2 b) nomme la classe ChampVent"
    champ = mod.ChampVent([])
    assert hasattr(champ, "complet"), "ChampVent doit porter l'attribut `complet` (contrat §1.2 b)"
    assert callable(getattr(champ, "vent_face_ms", None)), (
        "ChampVent doit exposer vent_face_ms(position_m, cap_deg, sens)"
    )
    # La sentinelle ne surveillait que le module. Or huit tests — dont **les
    # deux GOLDEN de non-régression** — sont gardés par `_exiger_parametre_vent`,
    # qui teste la signature de `placer`. Renommer le mot-clé `vent=` les
    # aurait tous fait basculer en skip sans qu'aucun test n'échoue. On
    # surveille donc aussi la signature, ici, au seul endroit qui crie.
    assert _placer_accepte_vent(), (
        "placer(...) doit garder le mot-clé `vent` : huit tests de ce fichier, "
        "dont la non-régression GOLDEN, se mettent en skip sans lui"
    )


# =============================================================================
# 1. La convention d'angle
# =============================================================================


@pytest.mark.parametrize("cap", CAPS)
@pytest.mark.parametrize("ecart", (0.0, 60.0, 90.0, 120.0, 180.0, 240.0, 300.0))
def test_composante_suit_le_cosinus_de_l_ecart(cap: float, ecart: float):
    """`V · cos(vent_depuis − cap)`, sur quatre caps non cardinaux.

    Mutations attrapées :
    * signe global inversé (`cap − vent` au lieu de `vent − cap` **avec** un
      sinus, ou un `-cos`) : écart 0 et 180 s'échangent ;
    * `sin` au lieu de `cos` : écart 0 rendrait 0 au lieu de +V ;
    * facteur 2 sur l'angle : l'écart 60 rendrait −0,5·V au lieu de +0,5·V ;
    * écart mesuré en degrés passé tel quel à `math.cos` (radians oubliés) :
      cos(60) ≈ −0,95 au lieu de +0,5.

    Ce qu'il **ne peut pas** attraper, et c'est inhérent au modèle : le cosinus
    est pair, donc `cos(vent − cap)` et `cos(cap − vent)` sont identiques. Une
    inversion de l'ordre des deux termes est invisible sur la composante
    longitudinale seule ; il n'y a donc rien à tester de ce côté.
    """
    champ = _champ([(cap + ecart) % 360.0] * 3)
    obtenu = champ.vent_face_ms(2500.0, cap, 1)
    assert obtenu == pytest.approx(fabriques5.attendu_ms(ecart), abs=1e-9), (
        f"cap {cap}°, vent venant de {(cap + ecart) % 360.0}° (écart {ecart}°) : "
        f"attendu {fabriques5.attendu_ms(ecart):+.3f} m/s, obtenu {obtenu:+.3f} m/s"
    )


@pytest.mark.parametrize("cap", CAPS)
def test_plein_face_est_positif_et_plein_dos_negatif(cap: float):
    """Le signe, isolé de toute moyenne : c'est lui qui se perd en silence."""
    face = _champ([cap] * 3).vent_face_ms(2500.0, cap, 1)
    dos = _champ([(cap + 180.0) % 360.0] * 3).vent_face_ms(2500.0, cap, 1)
    assert face > 0.0, f"vent venant du cap suivi ({cap}°) : c'est plein face, donc positif"
    assert dos < 0.0, f"vent venant de l'arrière ({(cap + 180.0) % 360.0}°) : négatif"
    assert face == pytest.approx(-dos, abs=1e-9)


@pytest.mark.parametrize("cap", CAPS)
@pytest.mark.parametrize("cote", (+90.0, -90.0))
def test_vent_de_travers_ne_compte_pas(cap: float, cote: float):
    """Approximation assumée du contrat §1.2 b) : le travers ne ralentit pas.

    Attrape une implémentation qui prendrait la norme du vent (|V|) au lieu de
    sa projection, ou qui ajouterait un terme de travers non demandé.
    """
    obtenu = _champ([(cap + cote) % 360.0] * 3).vent_face_ms(2500.0, cap, 1)
    assert obtenu == pytest.approx(0.0, abs=1e-9)


@pytest.mark.parametrize("cap", CAPS)
def test_le_facteur_de_hauteur_du_projet_est_applique(cap: float):
    """Le vent rendu est celui **au cycliste**, pas celui à 10 m (contrat §1.2 b).

    Attrape les deux fautes symétriques : facteur oublié (on rendrait 10 m/s
    au lieu de 6) et facteur appliqué deux fois (3,6 m/s). La constante est
    lue dans `physique.modele`, jamais recopiée ici : si quelqu'un la
    redéfinit dans `seance/vent.py`, `test_le_facteur_n_est_pas_redefini` le
    dit, et celui-ci reste juste.
    """
    obtenu = _champ([cap] * 3).vent_face_ms(2500.0, cap, 1)
    attendu = fabriques5.VENT_MS * fabriques5.facteur_hauteur_du_projet()
    assert obtenu == pytest.approx(attendu, abs=1e-9)
    assert obtenu != pytest.approx(fabriques5.VENT_MS, abs=1e-3), (
        "le vent à 10 m est rendu tel quel : le facteur de hauteur n'est pas appliqué"
    )


def test_le_facteur_de_hauteur_est_un_parametre_effectif():
    """`facteur_hauteur=1.0` doit rendre le vent brut : le paramètre n'est pas décoratif."""
    obtenu = _champ([0.0] * 3, facteur_hauteur=1.0).vent_face_ms(2500.0, 0.0, 1)
    assert obtenu == pytest.approx(fabriques5.VENT_MS, abs=1e-9)


def test_la_composante_ne_lit_pas_le_cap_de_l_echantillon():
    """Le cap qui compte est celui du **pas interrogé**, pas celui du point météo.

    Les fabriques posent un `Echantillon.cap_deg` absurde (123,456°). Si
    `vent_face_ms` s'en servait, la valeur ne suivrait pas `cap_deg` passé en
    argument. Mutation attrapée : `e.cap_deg` utilisé à la place de
    l'argument.
    """
    champ = _champ([40.0] * 3)
    a = champ.vent_face_ms(2500.0, 40.0, 1)
    b = champ.vent_face_ms(2500.0, 130.0, 1)
    assert a == pytest.approx(fabriques5.attendu_ms(0.0), abs=1e-9)
    assert b == pytest.approx(fabriques5.attendu_ms(90.0), abs=1e-9)


# =============================================================================
# 2. Le passage par le nord
# =============================================================================


@pytest.mark.parametrize("a,b", ((359.0, 1.0), (350.0, 10.0), (270.0, 30.0), (-10.0, 10.0)))
def test_interpolation_angulaire_passe_par_le_nord(a: float, b: float):
    """Deux directions encadrant le nord : le milieu est au nord, pas au sud.

    Mutation attrapée, la plus grosse du lot : `(a + b) / 2` en linéaire.
    Sur (359, 1) elle donne 180° — vent de dos annoncé là où il est plein
    face, soit une erreur de 2·V, 12 m/s ici. La valeur attendue est la
    bissectrice angulaire, donc le cap 0 est plein face.
    """
    milieu = (math.degrees(math.atan2(
        (math.sin(math.radians(a)) + math.sin(math.radians(b))) / 2,
        (math.cos(math.radians(a)) + math.cos(math.radians(b))) / 2,
    )) % 360.0)
    champ = _champ([a, b], pas_m=1000.0)
    obtenu = champ.vent_face_ms(500.0, 0.0, 1)
    attendu = fabriques5.attendu_ms(milieu)
    assert obtenu == pytest.approx(attendu, abs=1e-9), (
        f"directions {a}° et {b}° : la bissectrice est {milieu:.1f}°, "
        f"attendu {attendu:+.3f} m/s, obtenu {obtenu:+.3f} m/s"
    )
    assert obtenu > 0.0, "une interpolation linéaire aurait renvoyé le sud : composante négative"


def test_interpolation_compose_direction_et_vitesse_separement():
    """0° et 90° au milieu font 45°, donc 0,707·V — pas la moyenne des composantes.

    Mutation attrapée : interpoler la **composante** déjà projetée (+V et 0
    donneraient 0,5·V) au lieu d'interpoler direction et vitesse puis de
    projeter. Le cas 359/1 ne la voit pas : les deux composantes y sont
    presque identiques.
    """
    obtenu = _champ([0.0, 90.0], pas_m=1000.0).vent_face_ms(500.0, 0.0, 1)
    assert obtenu == pytest.approx(fabriques5.attendu_ms(45.0), abs=1e-9)
    assert obtenu != pytest.approx(fabriques5.attendu_ms(0.0) / 2.0, abs=1e-3)


def test_interpolation_lineaire_de_la_vitesse():
    """La vitesse s'interpole linéairement (contrat §1.2 b) : 10 et 30 font 20."""
    champ = _champ([0.0, 0.0], pas_m=1000.0, vitesses=[10.0, 30.0])
    assert champ.vent_face_ms(500.0, 0.0, 1) == pytest.approx(
        fabriques5.attendu_ms(0.0, vent_kmh=20.0), abs=1e-9
    )
    assert champ.vent_face_ms(0.0, 0.0, 1) == pytest.approx(
        fabriques5.attendu_ms(0.0, vent_kmh=10.0), abs=1e-9
    )
    assert champ.vent_face_ms(1000.0, 0.0, 1) == pytest.approx(
        fabriques5.attendu_ms(0.0, vent_kmh=30.0), abs=1e-9
    )


def test_la_valeur_sur_un_echantillon_est_celle_de_cet_echantillon():
    """Sur les nœuds exacts, pas d'`off-by-one` : chaque position rend son vent.

    Trois échantillons de directions très différentes ; un décalage d'indice
    d'un cran change le signe sur au moins une position.
    """
    champ = _champ([0.0, 90.0, 180.0], pas_m=1000.0)
    for position, ecart in ((0.0, 0.0), (1000.0, 90.0), (2000.0, 180.0)):
        assert champ.vent_face_ms(position, 0.0, 1) == pytest.approx(
            fabriques5.attendu_ms(ecart), abs=1e-9
        ), f"position {position} m"


def test_le_champ_varie_le_long_du_trace_controle_positif():
    """Sans ce contrôle, « prendre toujours le premier échantillon » passerait.

    C'est une mutation très courante d'un champ interpolé (index figé à 0).
    """
    champ = _champ([0.0, 0.0, 180.0, 180.0], pas_m=1000.0)
    debut = champ.vent_face_ms(0.0, 0.0, 1)
    fin = champ.vent_face_ms(3000.0, 0.0, 1)
    assert debut > 0.0 and fin < 0.0, (
        f"le vent doit s'inverser entre le km 0 ({debut:+.2f}) et le km 3 ({fin:+.2f}) : "
        "le champ semble constant, l'interpolation ne regarde peut-être qu'un seul échantillon"
    )


# =============================================================================
# 3. Le sens : les demi-tours du placement
# =============================================================================


@pytest.mark.parametrize("cap", CAPS)
@pytest.mark.parametrize("ecart", (0.0, 37.0, 90.0, 143.0, 180.0))
def test_le_sens_inverse_change_exactement_le_signe(cap: float, ecart: float):
    """`f(pos, cap, -1) == -f(pos, cap, +1)`, à l'exactitude du flottant près.

    Mutation attrapée : `sens` ignoré (les deux valeurs seraient égales, donc
    l'égalité au signe près échouerait dès que la composante est non nulle).
    Le cas `ecart = 90` est volontairement inclus **et** exclu de l'assertion
    forte : à 90°, la composante est nulle et l'antisymétrie est vraie pour
    tout le monde — il ne prouve rien seul, il n'est là que pour vérifier que
    zéro ne devient pas NaN.
    """
    champ = _champ([(cap + ecart) % 360.0] * 3)
    aller = champ.vent_face_ms(2500.0, cap, 1)
    retour = champ.vent_face_ms(2500.0, cap, -1)
    assert math.isfinite(aller) and math.isfinite(retour)
    assert retour == pytest.approx(-aller, abs=1e-9)
    if abs(aller) > 1e-6:
        assert retour != pytest.approx(aller, abs=1e-6), (
            "aller et retour identiques : `sens` n'est pas pris en compte"
        )


@pytest.mark.parametrize("cap", CAPS)
def test_un_demi_tour_change_le_plein_face_en_plein_dos(cap: float):
    """Le cas du contrat : un bloc aller vent de face, le même bloc au retour
    vent de dos, et la valeur exacte de part et d'autre."""
    champ = _champ([cap] * 3)
    assert champ.vent_face_ms(2500.0, cap, 1) == pytest.approx(
        fabriques5.attendu_ms(0.0), abs=1e-9
    )
    assert champ.vent_face_ms(2500.0, cap, -1) == pytest.approx(
        fabriques5.attendu_ms(180.0), abs=1e-9
    )


@pytest.mark.parametrize("cap", CAPS)
def test_sens_inverse_equivaut_au_cap_oppose(cap: float):
    """`cap_effectif = cap + 180` quand `sens <= 0` : les deux écritures coïncident."""
    champ = _champ([44.0] * 3)
    assert champ.vent_face_ms(2500.0, cap, -1) == pytest.approx(
        champ.vent_face_ms(2500.0, (cap + 180.0) % 360.0, 1), abs=1e-9
    )


def test_sens_nul_est_traite_comme_le_sens_inverse():
    """Lecture littérale du contrat : « `cap_deg` si `sens > 0`, `cap_deg + 180`
    sinon ». `sens = 0` tombe donc du côté inverse. Ce n'est pas une devinette
    sur l'intention, c'est le texte ; si l'intention était de refuser `0`, le
    contrat doit le dire (question remontée au mainteneur).
    """
    champ = _champ([0.0] * 3)
    assert champ.vent_face_ms(2500.0, 0.0, 0) == pytest.approx(
        champ.vent_face_ms(2500.0, 0.0, -1), abs=1e-9
    )


# =============================================================================
# 4. Le vent inconnu, qui n'est pas un vent nul
# =============================================================================


def test_champ_entierement_inconnu():
    """Contrat §1.2 b) : composante 0,0 **et** `complet` faux."""
    champ = _champ([0.0, 0.0, 0.0], vitesses=[None, None, None])
    assert champ.complet is False
    for position in (0.0, 2500.0, 10000.0):
        assert champ.vent_face_ms(position, 0.0, 1) == 0.0


def test_champ_sans_direction_est_inconnu():
    """Une vitesse sans direction ne se projette sur rien : c'est un vent inconnu."""
    champ = _champ([None, None, None])
    assert champ.complet is False
    assert champ.vent_face_ms(2500.0, 0.0, 1) == 0.0


def test_champ_sans_aucun_echantillon():
    """Aucun échantillon du tout : pas d'exception, pas de vent, `complet` faux."""
    champ = _vent().ChampVent([])
    assert champ.complet is False
    assert champ.vent_face_ms(0.0, 0.0, 1) == 0.0
    assert champ.vent_face_ms(42000.0, 123.0, -1) == 0.0


def test_champ_partiellement_inconnu_n_est_pas_complet():
    """Un seul trou suffit à retirer `complet` : c'est ce que l'appelant affiche."""
    champ = _champ([0.0, 0.0, 0.0], vitesses=[fabriques5.VENT_KMH, None, fabriques5.VENT_KMH])
    assert champ.complet is False


def test_champ_complet_controle_positif():
    """Sans ce test, `complet = False` en dur passerait les quatre précédents."""
    champ = _champ([0.0, 90.0, 180.0])
    assert champ.complet is True


def test_complet_est_un_vrai_booleen():
    """`complet` se lit `is True` / `is False` : ni 0/1, ni une liste vide.

    Le contrat en fait un drapeau d'affichage ; un appelant qui écrirait
    `if champ.complet is True` ne doit pas être surpris.
    """
    assert isinstance(_champ([0.0] * 3).complet, bool)
    assert isinstance(_champ([0.0] * 3, vitesses=[None, None, None]).complet, bool)
    assert isinstance(_vent().ChampVent([]).complet, bool)


def test_vent_nul_mesure_n_est_pas_un_vent_inconnu():
    """0 km/h est une mesure : composante nulle, mais `complet` **vrai**.

    Mutation attrapée, et elle est classique : `if not vent_kmh` au lieu de
    `if vent_kmh is None`. Elle rend le champ « incomplet » par temps calme,
    donc affiche « vent non pris en compte » le jour où il n'y a pas de vent.
    """
    champ = _champ([0.0, 0.0, 0.0], vitesses=[0.0, 0.0, 0.0])
    assert champ.complet is True, (
        "un vent mesuré à 0 km/h est connu : il ne rend pas le champ incomplet"
    )
    assert champ.vent_face_ms(2500.0, 0.0, 1) == pytest.approx(0.0, abs=1e-12)


# =============================================================================
# 5. Dégénérescences géométriques
# =============================================================================


def test_un_seul_echantillon_vaut_partout():
    """Un point de mesure : le vent est ce qu'il est, sur toute la longueur."""
    champ = _champ([0.0])
    attendu = fabriques5.attendu_ms(0.0)
    for position in (0.0, 1234.0, 99999.0):
        assert champ.vent_face_ms(position, 0.0, 1) == pytest.approx(attendu, abs=1e-9)


@pytest.mark.parametrize("position", (-1.0, -100000.0, 12000.0, 1e9))
def test_position_hors_du_trace_reste_bornee(position: float):
    """Avant le premier échantillon, après le dernier, très loin, négative.

    Le contrat ne tranche pas entre « prolonger la valeur du bout » et
    « rendre zéro » (question remontée au mainteneur). Ce test n'invente donc
    pas de valeur : il exige seulement ce qui est certain dans les deux
    lectures — pas d'exception, un nombre fini, et jamais plus fort que le
    vent lui-même. Il attrape `IndexError` sur un indice négatif et une
    extrapolation linéaire qui s'emballerait hors des bornes (un vent de
    200 m/s au km 1000 ferait exploser `vitesse_regime`).
    """
    champ = _champ([0.0, 90.0, 180.0], pas_m=5000.0)
    valeur = champ.vent_face_ms(position, 33.0, 1)
    plafond = fabriques5.VENT_MS * fabriques5.facteur_hauteur_du_projet()
    assert math.isfinite(valeur), f"position {position} : valeur non finie ({valeur!r})"
    assert abs(valeur) <= plafond + 1e-9, (
        f"position {position} : |{valeur:.3f}| dépasse le vent du champ ({plafond:.3f} m/s) — "
        "extrapolation hors des bornes ?"
    )


def test_deux_echantillons_a_la_meme_position():
    """Deux mesures à la même distance : division par zéro dans l'interpolation.

    Le contrat ne dit pas laquelle gagne ; on exige seulement un résultat fini
    et borné, jamais un NaN (qui ferait lever `vitesse_regime` plus loin).
    """
    mod = _meteo()
    doublons = [
        fabriques5.echantillon(mod, dist_m=0.0, vent_depuis_deg=0.0),
        fabriques5.echantillon(mod, dist_m=0.0, vent_depuis_deg=180.0),
        fabriques5.echantillon(mod, dist_m=5000.0, vent_depuis_deg=0.0),
    ]
    champ = _vent().ChampVent(doublons)
    for position in (0.0, 1.0, 2500.0, 5000.0):
        valeur = champ.vent_face_ms(position, 0.0, 1)
        assert math.isfinite(valeur), f"position {position} : {valeur!r}"


def test_echantillons_en_desordre():
    """Une série non triée par distance ne doit pas produire de valeur aberrante.

    Un tri manquant donne, au mieux, un vent pris au mauvais endroit ; ce qui
    est refusé ici, c'est le non-fini et le dépassement du vent du champ.
    """
    mod = _meteo()
    desordre = [
        fabriques5.echantillon(mod, dist_m=10000.0, vent_depuis_deg=180.0),
        fabriques5.echantillon(mod, dist_m=0.0, vent_depuis_deg=0.0),
        fabriques5.echantillon(mod, dist_m=5000.0, vent_depuis_deg=90.0),
    ]
    champ = _vent().ChampVent(desordre)
    plafond = fabriques5.VENT_MS * fabriques5.facteur_hauteur_du_projet()
    for position in (0.0, 2500.0, 7500.0, 10000.0):
        valeur = champ.vent_face_ms(position, 0.0, 1)
        assert math.isfinite(valeur) and abs(valeur) <= plafond + 1e-9


def test_le_champ_ne_depend_pas_des_horodatages():
    """`ChampVent` est indexé par **position**, pas par heure (contrat §1.2 d).

    Deux séries identiques dont seuls les `t` diffèrent — l'une en UTC,
    l'autre à cheval sur un changement d'heure européen, avec un horodatage
    naïf au milieu — doivent donner exactement les mêmes composantes. Ce test
    couvre l'angle « fuseaux et heure d'été » : la circularité étant coupée en
    amont (les heures de passage sont figées à l'allure d'endurance), aucune
    arithmétique de fuseau ne doit subsister ici.
    """
    mod = _meteo()
    heures = [
        datetime(2026, 3, 29, 1, 30, tzinfo=UTC),
        datetime(2026, 3, 29, 2, 30),  # naïf, et dans l'heure qui n'existe pas à Paris
        datetime(2026, 3, 29, 1, 30, tzinfo=timezone(timedelta(hours=2))),
    ]
    directions = [10.0, 80.0, 200.0]
    reference = _champ(directions, pas_m=5000.0)
    bizarres = [
        fabriques5.echantillon(mod, dist_m=i * 5000.0, vent_depuis_deg=d)
        for i, d in enumerate(directions)
    ]
    for e, t in zip(bizarres, heures, strict=True):
        e.t = t
    champ = _vent().ChampVent(bizarres)
    for position in (0.0, 2500.0, 7500.0, 10000.0):
        assert champ.vent_face_ms(position, 33.0, 1) == pytest.approx(
            reference.vent_face_ms(position, 33.0, 1), abs=1e-12
        ), f"le champ dépend de l'horodatage à la position {position}"


# =============================================================================
# 6. Valeurs hostiles venues d'une réponse d'API abîmée
# =============================================================================


def test_vent_tres_fort():
    """144 km/h : pas de plafonnement silencieux, la formule s'applique.

    Si l'implémentation décide de plafonner, ce n'est pas dans le contrat et
    ce test le signale — c'est le but : un plafond non écrit fausserait la
    comparaison au juge Intervals du §1.3.
    """
    champ = _champ([0.0] * 3, vitesses=[144.0] * 3)
    obtenu = champ.vent_face_ms(2500.0, 0.0, 1)
    assert obtenu == pytest.approx(fabriques5.attendu_ms(0.0, vent_kmh=144.0), abs=1e-9)


@pytest.mark.parametrize("direction", (720.0, 1080.5, -90.0, -450.0))
def test_directions_hors_de_zero_360(direction: float):
    """Un angle non normalisé donne le même vent que son représentant dans [0, 360).

    Contrainte faible et assumée : le cosinus est périodique, donc la plupart
    des implémentations passent sans effort. Ce que ce test attrape vraiment,
    c'est un garde-fou trop zélé (rejet ou remise à zéro d'un angle > 360°
    reçu d'Open-Meteo) et un `clamp` à la place d'un modulo.
    """
    normalisee = direction % 360.0
    attendu = _champ([normalisee] * 3).vent_face_ms(2500.0, 41.0, 1)
    obtenu = _champ([direction] * 3).vent_face_ms(2500.0, 41.0, 1)
    assert obtenu == pytest.approx(attendu, abs=1e-9)


@pytest.mark.parametrize("cap", (720.0, -90.0, 359.9999))
def test_caps_hors_de_zero_360(cap: float):
    """Idem côté cap : `_Terrain` peut rendre 360,0 par arrondi."""
    champ = _champ([0.0] * 3)
    assert champ.vent_face_ms(2500.0, cap, 1) == pytest.approx(
        champ.vent_face_ms(2500.0, cap % 360.0, 1), abs=1e-9
    )


@pytest.mark.parametrize(
    "vitesse,direction",
    (
        (float("nan"), 0.0),
        (float("inf"), 0.0),
        (-float("inf"), 0.0),
        (fabriques5.VENT_KMH, float("nan")),
        (fabriques5.VENT_KMH, float("inf")),
        (-10.0, 0.0),
    ),
)
def test_valeur_non_finie_ne_ressort_jamais(vitesse: float, direction: float):
    """Un NaN d'une réponse abîmée ne doit pas atteindre `vitesse_regime`.

    C'est l'invariant dur, et il ne dépend d'aucun choix de conception :
    `physique.modele._finis` lève `ErreurUtilisateur` sur un `vent_face_ms`
    non fini. Si `ChampVent` laisse passer un NaN, le placement casse au
    milieu du balayage des décalages, sur une entrée que le service météo
    peut très bien produire.

    Deux issues sont acceptables — traiter la valeur comme un vent inconnu
    (0,0 et `complet` faux), ou refuser franchement à la construction. La
    seule issue refusée est le NaN propagé en silence.
    """
    mod = _meteo()
    abimes = [
        fabriques5.echantillon(mod, dist_m=i * 5000.0, vent_kmh=vitesse, vent_depuis_deg=direction)
        for i in range(3)
    ]
    champ, erreur = _resultat_ou_erreur(lambda: _vent().ChampVent(abimes))
    if erreur is not None:
        return  # refus explicite : acceptable
    valeur, erreur = _resultat_ou_erreur(lambda: champ.vent_face_ms(2500.0, 0.0, 1))
    if erreur is not None:
        return
    assert math.isfinite(valeur), (
        f"vent_kmh={vitesse!r}, vent_depuis_deg={direction!r} ressort en {valeur!r} : "
        "vitesse_regime lèvera ErreurUtilisateur au milieu du placement"
    )


def test_un_champ_abime_ne_casse_pas_le_placement():
    """Le même invariant, vu du produit : une météo abîmée dégrade, elle ne plante pas.

    C'est le test qui a le plus de valeur d'usage de ce fichier : il part d'une
    réponse d'API plausible (un `null` devenu NaN) et vérifie que
    `ourouler sortie` ne s'effondre pas dessus.
    """
    _exiger_parametre_vent()
    mod = _meteo()
    trace = fabriques5.boucle_vallonnee(rayon_m=4300.0, n=430)
    abimes = [
        fabriques5.echantillon(
            mod, dist_m=d, vent_kmh=float("nan") if d else fabriques5.VENT_KMH, vent_depuis_deg=0.0
        )
        for d in (0.0, 13000.0, 26000.0)
    ]
    champ, erreur = _resultat_ou_erreur(lambda: _vent().ChampVent(abimes))
    if erreur is not None:
        return
    import fabriques4 as f4

    from ourouler.noyau import seance as seance_modele

    resultat, erreur = _resultat_ou_erreur(
        lambda: _placement().placer(
            f4.seance_deux_blocs(seance_modele), trace, _parametres(), vent=champ
        )
    )
    assert erreur is None or isinstance(erreur, ERREURS)
    if resultat is not None:
        assert math.isfinite(resultat.note_totale), "note NaN : le vent abîmé a contaminé la note"
        assert math.isfinite(resultat.duree_totale_s)


# =============================================================================
# 7. Non-régression : `vent=None` rend exactement le placement d'aujourd'hui
# =============================================================================

#: Placements de référence, **mesurés sur `sprint-5` avant le lot L5.1**
#: (b311d88), sur deux cas non triviaux : une boucle vallonnée de 27 km où le
#: terrain départage vraiment les décalages, et la boucle plate de 60 km des
#: tests du sprint 4. Le contrat §1.2 b) demande l'égalité « au bit près » :
#: au bit près **du code**, pas de la libm. Ces chiffres ont été relevés sur
#: macOS ; la CI Linux (glibc) rend les mêmes à 1 à 10 ulp près (écart relatif
#: mesuré au plus 1,9e-15, run 36149735808), parce que `sin`, `cos`, `atan2`…
#: n'y arrondissent pas le dernier bit de la même façon. D'où `TOLERANCE_GOLDEN`.
GOLDEN = {
    "vallonnee": {
        "decalage_z2_s": -60.0,
        "note_totale": 2.551169820981649,
        "note_terrain": 2.514623389842775,
        "penalite_seance": 0.036546431138874534,
        "duree_totale_s": 3399.278586833242,
        "distance_totale_m": 26987.09875576983,
        "jalons_m": [0.0, 26987.09875576983],
        "emplacements": [
            (1, 8572.825292743448, 5167.46637663, False, 4.678836701295379),
            (3, 16109.44198426167, 4142.337863403103, False, 0.35041007839017135),
        ],
    },
    "plate60": {
        "decalage_z2_s": 240.0,
        "note_totale": 0.6237624470758021,
        "note_terrain": 0.0,
        "penalite_seance": 0.6237624470758021,
        "duree_totale_s": 7222.574682454813,
        "distance_totale_m": 59930.42669131102,
        "jalons_m": [0.0, 59930.42669131102],
        "emplacements": [
            (1, 11617.823785460503, 5670.34827776115, False, 0.0),
            (3, 19224.47602746507, 5670.34827776115, False, 0.0),
        ],
    },
}


#: Écart **relatif** admis entre un flottant mesuré et son golden : 1e-13,
#: cinquante fois l'écart de plateforme observé (1,9e-15), et huit ordres de
#: grandeur sous la plus petite dérive que ce test doit attraper (un pas
#: déplacé d'un mètre sur 27 km, soit 3,7e-5). Pas de tolérance absolue : un
#: zéro du golden (terrain plat, note de bloc nulle) doit rester un zéro exact.
#: Entiers, booléens, décalages en secondes et structure restent comparés à
#: l'identique.
TOLERANCE_GOLDEN = 1e-13


def _ecarts_au_golden(obtenu: Any, attendu: Any, chemin: str = "") -> list[str]:
    """Les écarts entre une mesure et son golden, flottants à `TOLERANCE_GOLDEN` près.

    Vide si tout concorde. `pytest.approx` ne descend pas dans des listes de
    tuples rangées dans un dict : on parcourt donc la structure à la main.
    """
    ecart = [f"{chemin or 'racine'} : {obtenu!r} au lieu de {attendu!r}"]
    if isinstance(attendu, dict):
        if not isinstance(obtenu, dict) or obtenu.keys() != attendu.keys():
            return ecart
        return [e for k in attendu for e in _ecarts_au_golden(obtenu[k], attendu[k], f"{chemin}.{k}")]
    if isinstance(attendu, (list, tuple)):
        if type(obtenu) is not type(attendu) or len(obtenu) != len(attendu):
            return ecart
        return [
            e
            for i, (o, a) in enumerate(zip(obtenu, attendu, strict=True))
            for e in _ecarts_au_golden(o, a, f"{chemin}[{i}]")
        ]
    if type(attendu) is float and type(obtenu) is float:
        proches = math.isclose(obtenu, attendu, rel_tol=TOLERANCE_GOLDEN, abs_tol=0.0)
        return [] if proches else ecart
    return [] if type(obtenu) is type(attendu) and obtenu == attendu else ecart


def _trace_golden(nom: str) -> Any:
    if nom == "vallonnee":
        return fabriques5.boucle_vallonnee(rayon_m=4300.0, n=430)
    return fabriques4.boucle_plate(rayon_m=9549.0, n=600)


def _seance_golden() -> Any:
    from ourouler.noyau import seance as seance_modele

    return fabriques4.seance_deux_blocs(seance_modele)


def _mesure(placement: Any) -> dict:
    return {
        "decalage_z2_s": placement.decalage_z2_s,
        "note_totale": placement.note_totale,
        "note_terrain": placement.note_terrain,
        "penalite_seance": placement.penalite_seance,
        "duree_totale_s": placement.duree_totale_s,
        "distance_totale_m": placement.distance_totale_m,
        "jalons_m": list(placement.jalons_m),
        "emplacements": [
            (e.etape_idx, e.debut_m, e.longueur_m, e.demi_tour, e.note.note)
            for e in placement.blocs()
        ],
    }


@pytest.mark.parametrize("nom", tuple(GOLDEN))
def test_sans_vent_le_placement_est_celui_d_avant_le_lot(nom: str):
    """Le vrai test de non-régression : des chiffres figés avant le lot.

    Comparer `placer(vent=None)` à `placer()` ne prouverait rien — les deux
    changeraient ensemble. Ces valeurs viennent du code de `sprint-5` à
    b311d88 ; toute dérive du placement à vent nul les casse, y compris celle
    qu'un branchement maladroit introduirait « seulement un peu » (un
    `vent_face` de 0,0 arrondi qui change la clé de mémoïsation, une pente
    recalculée au passage, un cap qui déplace un pas d'un mètre).
    """
    _exiger_parametre_vent()
    placement = _placement().placer(
        _seance_golden(), _trace_golden(nom), _parametres(), vent=None
    )
    assert placement is not None, "le placement de référence n'est pas None"
    ecarts = _ecarts_au_golden(_mesure(placement), GOLDEN[nom])
    assert not ecarts, "\n".join(ecarts)


@pytest.mark.parametrize("nom", tuple(GOLDEN))
def test_le_defaut_de_vent_est_none(nom: str):
    """Ne pas passer `vent` doit valoir `vent=None` : pas de champ implicite."""
    _exiger_parametre_vent()
    mod = _placement()
    sans = mod.placer(_seance_golden(), _trace_golden(nom), _parametres())
    explicite = mod.placer(_seance_golden(), _trace_golden(nom), _parametres(), vent=None)
    assert _mesure(sans) == _mesure(explicite)


def test_un_champ_entierement_inconnu_vaut_l_absence_de_champ():
    """Un champ dont rien n'est connu ne doit rien changer au placement.

    Les listes `avertissements` / `informations` sont exclues de la
    comparaison : le contrat prévoit justement que l'appelant puisse dire
    « vent non pris en compte », et ce serait un ajout légitime.
    """
    _exiger_parametre_vent()
    mod = _placement()
    trace = _trace_golden("vallonnee")
    champ = _champ([0.0, 0.0, 0.0], vitesses=[None, None, None])
    assert champ.complet is False
    avec = mod.placer(_seance_golden(), trace, _parametres(), vent=champ)
    sans = mod.placer(_seance_golden(), trace, _parametres(), vent=None)
    assert _mesure(avec) == _mesure(sans)


def test_un_vent_reel_change_le_placement_controle_positif():
    """**Le** test qui empêche de passer la section 7 en ignorant le vent.

    Une implémentation qui accepterait `vent=` et n'en ferait rien passerait
    tous les tests de non-régression ci-dessus, et ne serait démasquée que par
    le script de validation du §1.3 — c'est-à-dire trop tard. Sur une boucle,
    un vent uniforme de 36 km/h accélère la moitié du tour et freine l'autre :
    les durées, donc les positions des blocs, ne peuvent pas rester
    identiques au bit près.
    """
    _exiger_parametre_vent()
    mod = _placement()
    trace = _trace_golden("vallonnee")
    champ = _champ([0.0, 0.0, 0.0], pas_m=13500.0)
    assert champ.complet is True
    avec = mod.placer(_seance_golden(), trace, _parametres(), vent=champ)
    sans = mod.placer(_seance_golden(), trace, _parametres(), vent=None)
    assert avec is not None and sans is not None
    assert _mesure(avec) != _mesure(sans), (
        "un vent de 36 km/h ne change rien au placement : le champ est accepté puis ignoré"
    )


def test_le_placement_ne_modifie_pas_le_champ_recu():
    """Le champ est une donnée d'entrée partagée : `placer` ne le consomme pas.

    Il est construit une fois (contrat §1.2 d) et peut servir à plusieurs
    candidates ; deux appels successifs doivent donner le même résultat.
    """
    _exiger_parametre_vent()
    mod = _placement()
    trace = _trace_golden("vallonnee")
    champ = _champ([0.0, 90.0, 200.0], pas_m=13500.0)
    premier = mod.placer(_seance_golden(), trace, _parametres(), vent=champ)
    second = mod.placer(_seance_golden(), trace, _parametres(), vent=champ)
    assert _mesure(premier) == _mesure(second)
    assert champ.vent_face_ms(2500.0, 0.0, 1) == pytest.approx(
        _champ([0.0, 90.0, 200.0], pas_m=13500.0).vent_face_ms(2500.0, 0.0, 1), abs=1e-12
    )


# =============================================================================
# 8. `_Terrain` : le cap de chaque pas, et la mémoïsation
# =============================================================================


def _terrain(trace: Any) -> Any:
    return _placement()._Terrain(trace, _parametres())


def _caps(terrain: Any) -> list[float]:
    """Les caps des pas, quel que soit le nom que le lot leur a donné.

    Le contrat dit « `_Terrain` connaît le cap de chaque pas » sans nommer
    l'interface ; par symétrie avec `pentes` / `pente_a`, on accepte `caps`
    (liste) ou `cap_a(position_m)`. Un troisième nom fait échouer, et c'est
    voulu : ce n'est pas au test de deviner indéfiniment.
    """
    if hasattr(terrain, "caps"):
        return [float(c) for c in terrain.caps]
    if hasattr(terrain, "cap_a"):
        bornes = terrain.bornes
        return [
            float(terrain.cap_a((bornes[i] + bornes[i + 1]) / 2.0)) for i in range(len(bornes) - 1)
        ]
    pytest.skip(
        "ni `_Terrain.caps` ni `_Terrain.cap_a` : le contrat L5.1 §1.2 a) demande le cap "
        "de chaque pas mais ne nomme pas l'interface (question remontée au mainteneur)"
    )


@pytest.mark.parametrize("cap_voulu", (0.0, 47.0, 103.0, 198.0, 270.0, 291.0, 359.0))
def test_le_cap_de_chaque_pas_suit_la_geometrie(cap_voulu: float):
    """Une droite d'un seul cap : tous les pas portent ce cap, à 1° près.

    Mutations attrapées : caps calculés à l'envers (cap + 180 partout), axes
    latitude/longitude intervertis (les caps 47° et 43° s'échangeraient — d'où
    le choix de caps non symétriques), cap exprimé en radians.
    """
    caps = _caps(_terrain(fabriques5.droite_au_cap(cap_voulu, n_troncons=40)))
    assert caps, "aucun pas : le terrain n'a pas de cap"
    for i, cap in enumerate(caps):
        assert fabriques5.ecart_angulaire(cap, cap_voulu) <= 1.0, (
            f"pas {i} : cap {cap:.1f}° au lieu de {cap_voulu:.1f}°"
        )


def test_les_caps_franchissent_le_nord_sans_detour_par_le_sud():
    """Un tracé qui passe de 350° à 10° ne doit jamais porter un cap vers le sud.

    Mutation attrapée : un cap obtenu en moyennant linéairement les caps de
    deux points (350 et 10 donneraient 180). Le cap d'un pas se calcule par la
    géométrie du pas, jamais par une moyenne d'angles bruts.
    """
    caps = _caps(_terrain(fabriques5.coude_au_nord(cap_avant=350.0, cap_apres=10.0, n=20)))
    pires = [c for c in caps if fabriques5.ecart_au_nord(c) > 45.0]
    assert not pires, (
        f"caps éloignés du nord de plus de 45° sur un tracé qui va de 350° à 10° : {pires[:5]} — "
        "moyenne linéaire d'angles ?"
    )


def test_les_caps_distinguent_les_deux_branches_d_un_coude():
    """Contrôle positif : un cap constant partout passerait le test précédent."""
    caps = _caps(_terrain(fabriques5.coude_au_nord(cap_avant=20.0, cap_apres=110.0, n=20)))
    assert fabriques5.ecart_angulaire(caps[0], 20.0) <= 2.0
    assert fabriques5.ecart_angulaire(caps[-1], 110.0) <= 2.0
    assert fabriques5.ecart_angulaire(caps[0], caps[-1]) >= 80.0, (
        "les deux branches du coude portent le même cap : le cap ne suit pas le tracé"
    )


def test_trace_degenere_deux_points_confondus():
    """Cap indéfini : `_Terrain` ne doit pas lever sur un tracé à points confondus.

    `placer` refuse déjà les tracés de moins de deux points ; deux points
    identiques passent ce filtre et donnent une longueur nulle. Le cap n'y
    existe pas (c'est le cas que `meteo_trace._cap_local` résout par `None`).

    **Ce test échoue aujourd'hui, et pas à cause de L5.1.** Bug préexistant
    trouvé le 15/09/2026 sur `sprint-5` (b311d88) : `_Terrain.__init__` divise
    par `bornes[i+1] - bornes[i]`, nul quand le tracé fait 0 m
    (`placement.py`, calcul de `self.pentes`). Le garde-fou de `placer`
    (« tracé de longueur nulle ») est écrit **après** la construction du
    terrain, donc `placer(seance, trace, p)` lève `ZeroDivisionError` au lieu
    de rendre `None` avec son motif. Le test est gardé ici parce que le lot
    L5.1 ajoute le calcul des caps au même endroit et rencontrera le même
    tracé dégénéré ; la correction, elle, ne lui appartient pas.
    """
    coords = [(fabriques.LAT0, fabriques.LON0, 10.0), (fabriques.LAT0, fabriques.LON0, 10.0)]
    trace = fabriques4.trace_taguee(coords, nom="deux points confondus")
    terrain, erreur = _resultat_ou_erreur(lambda: _terrain(trace))
    assert erreur is None or isinstance(erreur, ERREURS), (
        f"deux points confondus font lever {type(erreur).__name__} : {erreur}"
    )
    if terrain is None:
        return
    for cap in _caps(terrain):
        assert math.isfinite(cap), f"cap non fini sur un tracé dégénéré : {cap!r}"


def _vitesse_accepte_le_vent(terrain: Any) -> bool:
    return len(inspect.signature(terrain.vitesse).parameters) >= 3


def test_le_vent_de_face_ralentit_et_le_vent_de_dos_accelere():
    """Le branchement dans `_Terrain`, vu par son effet, pas par sa clé de cache.

    C'est ici que se voit une inversion de signe **entre** `ChampVent` et
    `vitesse_regime` : la convention pourrait être juste des deux côtés et le
    branchement les recoller à l'envers. Aucun test de `ChampVent` seul ne
    l'attrape.
    """
    terrain = _terrain(fabriques5.boucle_vallonnee(rayon_m=4300.0, n=430))
    if not _vitesse_accepte_le_vent(terrain):
        pytest.skip(
            "_Terrain.vitesse n'a pas encore de paramètre de vent (contrat L5.1 §1.2 c)"
        )
    face = terrain.vitesse(210.0, 0.0, 5.0)
    calme = terrain.vitesse(210.0, 0.0, 0.0)
    dos = terrain.vitesse(210.0, 0.0, -5.0)
    assert face < calme < dos, (
        f"à 210 W sur le plat : face {face:.2f}, calme {calme:.2f}, dos {dos:.2f} m/s — "
        "le signe du vent est inversé quelque part entre ChampVent et vitesse_regime"
    )


def _terrain_avec_vent(trace: Any, champ: Any) -> Any:
    """`_Terrain` construit avec un champ de vent, ou skip si la voie n'existe pas.

    Le contrat §1.2 c) demande le branchement dans `_Terrain` sans dire par où
    le champ y entre ; on accepte un troisième argument positionnel ou un
    mot-clé `vent`.
    """
    classe = _placement()._Terrain
    parametres = inspect.signature(classe.__init__).parameters
    if "vent" in parametres:
        return classe(trace, _parametres(), vent=champ)
    if len(parametres) >= 4:
        return classe(trace, _parametres(), champ)
    pytest.skip(
        "`_Terrain` n'accepte pas encore de champ de vent (contrat L5.1 §1.2 c) — "
        "ni troisième argument, ni mot-clé `vent`"
    )


def test_le_sens_du_pas_arrive_bien_jusqu_au_champ():
    """Le trou que la mémoïsation seule ne voit pas : `sens` perdu en chemin.

    `test_le_vent_de_face_ralentit...` appelle `_Terrain.vitesse` avec un vent
    déjà signé ; il reste donc vert si le branchement oublie de transmettre
    `sens` au champ, ou s'il inverse le signe entre les deux. Vérifié par
    mutation le 15/09/2026 : ces deux fautes-là passaient toute la suite.

    Ici on avance réellement sur le tracé, d'abord dans un sens puis dans
    l'autre, avec un vent uniforme venant du cap du tracé. À l'aller c'est
    plein face, au retour plein dos : la distance couverte en un même temps
    ne peut pas être la même, et c'est l'aller qui doit être le plus court.
    """
    cap = 103.0
    trace = fabriques5.droite_au_cap(cap, n_troncons=400, pas_m=100.0)
    champ = _champ([cap] * 3, pas_m=20000.0)
    terrain = _terrain_avec_vent(trace, champ)
    depart = terrain.total / 2.0
    aller = terrain.avancer(depart, 1, 600.0, 210.0)
    retour = terrain.avancer(depart, -1, 600.0, 210.0)
    assert aller is not None and retour is not None, "600 s tiennent dans la moitié du tracé"
    d_aller, d_retour = abs(aller - depart), abs(retour - depart)
    # La marge n'est pas cosmétique. Relecture du 15/09/2026 : avec un simple
    # `d_aller < d_retour`, neutraliser `_Terrain.vent_face` laissait ce test
    # vert — 5 670,348277761150 m contre 5 670,348277761152 m, soit 1,8e-12 m
    # d'écart, satisfait par le seul sens d'arrondi. Le test annonçait garder
    # le `sens` non transmis au champ ; il ne gardait rien. Un vent de 5 m/s
    # au cap du tracé doit creuser des centaines de mètres sur 600 s, pas des
    # picomètres.
    assert d_aller < d_retour * 0.8, (
        f"vent venant du cap {cap}° : 600 s à 210 W couvrent {d_aller:.0f} m dans le sens "
        f"du tracé et {d_retour:.0f} m en sens inverse — l'aller est vent de face, il doit "
        "être le plus court. Signe inversé au branchement, ou `sens` non transmis au champ."
    )


def test_le_vent_de_dos_mene_plus_loin_que_le_vent_de_face():
    """Le même invariant, vu du produit, à travers `placer`.

    Sur une ligne droite (pas de boucle où le vent se compenserait), un bloc
    de durée prescrite couvre plus de mètres avec le vent dans le dos. C'est
    exactement le chiffre du §0 du contrat : 13,3 km contre 9,2 km pour vingt
    minutes à 210 W.

    La grandeur observée est la **longueur du bloc**, pas la distance totale :
    sur un tracé plus long que la séance, la Z2 de fin absorbe jusqu'au bout
    et la distance totale vaut la longueur du tracé dans les deux cas — elle
    ne dirait rien. Le piège a été vérifié le 15/09/2026 avant d'écrire ce
    test.
    """
    _exiger_parametre_vent()
    cap = 103.0
    trace = fabriques5.droite_au_cap(cap, n_troncons=600, pas_m=100.0)
    face = _champ([cap] * 3, pas_m=30000.0)
    dos = _champ([(cap + 180.0) % 360.0] * 3, pas_m=30000.0)
    mod = _placement()
    avec_face = mod.placer(_seance_golden(), trace, _parametres(), vent=face)
    avec_dos = mod.placer(_seance_golden(), trace, _parametres(), vent=dos)
    assert avec_face is not None and avec_dos is not None, (
        "la séance doit tenir sur 60 km de droite dans les deux cas"
    )
    bloc_face = avec_face.blocs()[0].longueur_m
    bloc_dos = avec_dos.blocs()[0].longueur_m
    assert bloc_dos > bloc_face, (
        f"premier bloc : {bloc_dos:.0f} m vent de dos contre {bloc_face:.0f} m vent de face — "
        "à durée prescrite égale, le vent de dos doit couvrir plus de terrain "
        "(égalité = champ ignoré, inversion = signe inversé au branchement)"
    )


def test_la_vitesse_a_vent_nul_est_celle_d_avant_le_lot():
    """Non-régression de `_Terrain.vitesse` : trois valeurs figées sur `sprint-5`.

    Si le branchement change la vitesse à vent nul, le placement dérive
    partout sans qu'aucun test de vent ne bronche.
    """
    terrain = _terrain(fabriques5.boucle_vallonnee(rayon_m=4300.0, n=430))
    attendus = {
        (210.0, 0.0): 9.45058046293525,
        (210.0, 0.03): 5.749765049031339,
        (140.0, -0.02): 11.217259573613774,
    }
    for (puissance, pente), attendu in attendus.items():
        if _vitesse_accepte_le_vent(terrain):
            obtenue = terrain.vitesse(puissance, pente, 0.0)
        else:
            obtenue = terrain.vitesse(puissance, pente)
        assert obtenue == pytest.approx(attendu, abs=1e-9), (
            f"vitesse({puissance} W, pente {pente}) à vent nul a changé"
        )


def test_le_vent_est_arrondi_pour_la_memoisation():
    """Contrat §1.2 c) : arrondi à 0,25 m/s, sinon le cache ne sert plus à rien.

    Deux vents dans le même seau doivent rendre **exactement** le même
    flottant (le cache les confond) ; deux vents de seaux différents doivent
    rendre des valeurs différentes. Mutation attrapée : arrondi oublié (0,01
    et 0,02 donneraient deux vitesses distinctes, le balayage des décalages
    recalculerait tout et `ourouler sortie` doublerait plus que le budget) ;
    arrondi trop grossier (0,0 et 1,0 confondus) aussi.
    """
    terrain = _terrain(fabriques5.boucle_vallonnee(rayon_m=4300.0, n=430))
    if not _vitesse_accepte_le_vent(terrain):
        pytest.skip("_Terrain.vitesse n'a pas encore de paramètre de vent (contrat L5.1 §1.2 c)")
    assert terrain.vitesse(210.0, 0.0, 0.01) == terrain.vitesse(210.0, 0.0, 0.02), (
        "0,01 et 0,02 m/s tombent dans le même seau de 0,25 : la mémoïsation doit les confondre"
    )
    assert terrain.vitesse(210.0, 0.0, 0.0) != terrain.vitesse(210.0, 0.0, 1.0), (
        "0,0 et 1,0 m/s sont dans des seaux différents : les confondre efface le vent"
    )


# =============================================================================
# 9. Invariants du produit (CLAUDE.md)
# =============================================================================

SOURCE_VENT = "src/ourouler/seance/vent.py"


def _source_vent() -> str:
    from pathlib import Path

    chemin = Path(__file__).resolve().parents[2] / SOURCE_VENT
    if not chemin.exists():
        pytest.skip(f"{SOURCE_VENT} absent : lot L5.1 non livré")
    return chemin.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "interdit", ("tomllib", "os.environ", "getenv", "Path.home()", ".expanduser(", "load_dotenv")
)
def test_le_champ_de_vent_ne_lit_pas_son_environnement(interdit: str):
    """Règle absolue 2 : hors `cli.py` et `config.py`, le cœur reçoit, il ne lit pas.

    `tests/test_invariants.py` balaie déjà tout `src/ourouler/` ; ce doublon
    cible `seance/vent.py` pour que l'échec nomme le module fautif du lot au
    lieu d'un paramétrage anonyme.
    """
    assert interdit not in _source_vent(), (
        f"{SOURCE_VENT} contient « {interdit} » : le cœur ne sait pas où il tourne"
    )


@pytest.mark.parametrize("interdit", ("httpx", "requests", "urllib", "socket"))
def test_le_champ_de_vent_n_appelle_pas_le_reseau(interdit: str):
    """Règle absolue 3 : `ChampVent` reçoit des `Echantillon` déjà téléchargés.

    Un champ de vent qui irait chercher lui-même une prévision manquante
    rendrait le placement non testable et ferait un appel réseau par décalage
    balayé.
    """
    assert interdit not in _source_vent(), f"{SOURCE_VENT} importe « {interdit} »"


def test_le_facteur_n_est_pas_redefini():
    """Contrat §1.2 b) : « Même constante, importée du même endroit, jamais redéfinie ».

    `FACTEUR_VENT_HAUTEUR` vit dans `physique/modele.py` et vaut 0,6. Une
    deuxième définition dans `seance/vent.py` est exactement la faute que le
    contrat interdit : le modèle serait calibré sur un vent et utilisé sur un
    autre le jour où l'une des deux bouge.
    """
    import re

    source = _source_vent()
    doublons = re.findall(r"^\s*[A-Z_]*FACTEUR[A-Z_]*\s*=\s*[0-9]", source, flags=re.M)
    assert not doublons, (
        f"{SOURCE_VENT} redéfinit un facteur numérique ({doublons}) au lieu d'importer "
        "FACTEUR_VENT_HAUTEUR de ourouler.physique.modele"
    )
    assert "FACTEUR_VENT_HAUTEUR" in source or "vent_au_cycliste" in source, (
        f"{SOURCE_VENT} ne fait référence ni à FACTEUR_VENT_HAUTEUR ni à vent_au_cycliste : "
        "d'où vient le facteur de hauteur ?"
    )


def test_les_fixtures_de_ce_fichier_ne_portent_aucune_coordonnee_reelle():
    """Règle absolue 1, appliquée à mes propres fabriques.

    Tout part de `fabriques.LAT0/LON0`, en pleine mer au sud du golfe de
    Guinée. Aucun point de départ du mainteneur n'entre dans le dépôt, pas
    même déguisé en fixture de vent.
    """
    assert abs(fabriques.LAT0) < 0.01 and abs(fabriques.LON0) < 0.01
    echantillon = fabriques5.echantillon(_meteo(), dist_m=5000.0)
    assert abs(echantillon.lat) < 1.0 and abs(echantillon.lon) < 1.0, (
        "un échantillon de test s'éloigne du point fictif : coordonnée réelle ?"
    )
