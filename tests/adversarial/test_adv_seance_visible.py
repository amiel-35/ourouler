"""L5.2 — la séance entière visible, mise à l'épreuve **en aveugle**.

Écrit contre `docs/journal/sprints/sprint5_contrat.md` §2, Q13 et CLAUDE.md
(voir `docs/journal/questions/questions_mainteneur.md`), à partir de la branche `essai-l5.1`, **sans avoir lu
l'implémentation du lot** : elle s'écrit dans un autre worktree pendant que ce
fichier se rédige. Le seul code lu est celui que le lot va modifier, tel qu'il
était avant lui.

Ce que ce fichier surveille, par ordre de gravité décroissante.

1. **La continuité** (§2.2 a). Les emplacements se suivent sans trou ni
   recouvrement, du départ à l'arrivée, et la somme de leurs longueurs vaut
   `distance_totale_m` **au sens du parcours réellement roulé**. C'est
   l'invariant qui prouve qu'on montre toute la séance et pas des morceaux.
   `fabriques_seance_visible.verifier_continuite` l'applique ; son docstring explique
   pourquoi il passe par `jalons_m` et non par `debut_m` seul.

2. **Les demi-tours.** La figure du sprint 4 — « bloc → moitié de récup →
   demi-tour → moitié de récup → bloc » — roule `2b` mètres pour une empreinte
   de `b` mètres sur le tracé, et la récupération finit là où elle a commencé.
   C'est le piège du lot : afficher `b` (la distance entre deux points du
   tracé) au lieu de `2b` (ce qui est roulé) est l'erreur naturelle, et elle
   laisse la continuité *presque* vraie.

3. **La note des non-blocs.** Elle ne doit pas exister. Un `0.0` qui se
   glisserait dans `_note_ponderee` diviserait `note_terrain` par trois sur la
   séance d'essai sans que rien ne le signale — c'est la régression la plus
   silencieuse possible de ce lot, et les tests du sprint 4 ne la voient pas :
   ils ne regardent que les blocs.

4. **La non-régression du tri et des notes.** `GOLDEN` a été relevé sur
   `essai-l5.1` (commit `f4f0cb5`) **avant** le lot, le 16/09/2026, par
   `placer` sur les fixtures de ce fichier. Les valeurs ne sont pas recopiées
   d'une exécution postérieure au lot, ce qui les rendrait vides de sens. Le
   lot est un lot d'affichage : elles ne doivent pas bouger d'un iota.

5. **Les compteurs de l'affichage.** `Proposition.blocs_bien_places`,
   `Proposition.demi_tours` et le dénominateur « x/y blocs bien placés » se
   calculent aujourd'hui sur `placement.emplacements` tout entier. Le jour où
   cette liste contient toutes les étapes, ils comptent faux **sans lever** —
   « 1/5 blocs bien placés » sur une séance qui n'a que deux blocs, un
   demi-tour compté deux fois. Aucun test existant ne l'attrape.

6. **La carte.** `carte._liaisons` déduit les portions non notées des *trous
   entre les blocs*. Nourrie de tous les emplacements, elle n'a plus aucun
   trou à dessiner et la carte perd d'un coup l'échauffement et le retour au
   calme. C'est l'inverse exact du but du lot.

Discipline appliquée à chaque test : quelle mutation du code l'attrape ? Quand
ce n'est pas évident, c'est écrit dans le test. Les marges des comparaisons de
flottants sont motivées (`fabriques_seance_visible.MARGE_M`) : ni comparaison nue, qui
verdit sur du bruit à 10⁻¹² m, ni marge large, qui laisse passer une vraie
faute.

Tant que le lot n'est pas fusionné, tout ce fichier se met en `skip` sauf
`test_sentinelle_l5_2_pas_encore_livre`, qui **échoue** : un dossier
entièrement vert parce qu'entièrement sauté se lit « rien à signaler », ce qui
serait faux. La sentinelle interroge la **vraie interface** — elle déroule un
placement et compte les emplacements — et non la seule existence d'un module.
"""

from __future__ import annotations

import html
import json
import math
import re
from types import SimpleNamespace
from typing import Any

import fabriques
import fabriques_seance_visible as fab
import pytest
from outils import fabriquer

from ourouler.noyau.texte import nombre_fr
from ourouler.rendu import carte as module_carte
from ourouler.rendu import sortie as module_sortie
from ourouler.rendu import sortie_json as rendu_json
from ourouler.seance import placement as module_placement
from ourouler.seance import placement_resultat
from ourouler.sortie import commande as module_commande

# =============================================================================
# Outils du fichier
# =============================================================================


class _Patch:
    """Un `monkeypatch` minimal, utilisable hors d'un test (pour la sonde)."""

    def __init__(self) -> None:
        self._anciens: list[tuple[Any, str, Any]] = []

    def setattr(self, objet: Any, nom: str, valeur: Any) -> None:
        self._anciens.append((objet, nom, getattr(objet, nom)))
        setattr(objet, nom, valeur)

    def undo(self) -> None:
        for objet, nom, ancien in reversed(self._anciens):
            setattr(objet, nom, ancien)
        self._anciens.clear()


def placer(monkeypatch: Any, seance: Any, trace: Any, **kw: Any) -> Any:
    """`placer` sur un terrain factice, avec le refus rangé dans le message d'échec."""
    options = {
        cle: kw.pop(cle) for cle in ("bon", "mauvais", "pente", "demi_tour") if cle in kw
    }
    appels = fab.terrain_factice(monkeypatch, **options)
    module = module_placement
    resultat = module.placer(seance, trace, fab.parametres(), **kw)
    assert resultat is not None, (
        "le placement a échoué alors que la fixture est faite pour tenir : "
        f"{trace.meta.get('placement_motif', trace.meta)}"
    )
    return resultat, appels


#: Résultat de la sonde d'interface, calculé une fois.
_SONDE: list[str] = []


def _sonder() -> str:
    """`''` si le lot est livré, sinon le motif du saut.

    On **déroule un vrai placement** et on compte les emplacements. Sonder
    l'existence d'un module ou d'un attribut ne suffirait pas : le lot ne crée
    aucun module, il change ce que `placer` rend.
    """
    try:
        from ourouler.seance import placement as module
    except Exception as e:  # pragma: no cover - sprint 4 fusionné
        return f"ourouler.seance.placement inimportable : {e!r}"
    patch = _Patch()
    try:
        seance = fab.seance_2x20()
        resultat = module.placer(seance, fab.trace_droite(78_000.0), fab.parametres())
    except Exception as e:  # pragma: no cover
        return f"placer a levé {type(e).__name__} : {e}"
    finally:
        patch.undo()
    if resultat is None:  # pragma: no cover
        return "placer rend None sur la fixture de référence : rien à sonder"
    if len(resultat.emplacements) != len(seance.etapes):
        return (
            "le lot L5.2 n'est pas (encore) livré : `placer` rend "
            f"{len(resultat.emplacements)} emplacements pour {len(seance.etapes)} étapes "
            "(contrat sprint 5 §2.2 a)"
        )
    return ""


def motif_absence() -> str:
    if not _SONDE:
        _SONDE.append(_sonder())
    return _SONDE[0]


def exiger_lot() -> None:
    motif = motif_absence()
    if motif:
        pytest.skip(motif)


# =============================================================================
# 0. Sentinelle
# =============================================================================


def test_sentinelle_l5_2_pas_encore_livre():
    """Le seul test de ce fichier qui échoue quand le lot est absent.

    Sans lui, l'ensemble se lirait « n tests passés » alors qu'aucun n'aurait
    rien vérifié. Il surveille la **vraie interface** du contrat §2.2 a), pas
    l'existence d'un module : le lot n'en crée aucun.

    Trois choses, dans l'ordre où elles cassent :

    1. `placer` rend un emplacement par étape — la sonde ;
    2. les non-blocs n'ont pas de note — sinon huit tests de la section 3
       vérifieraient un contrat qui n'est pas celui qu'on a écrit ;
    3. `Emplacement.note` est déclaré optionnel — le contrat dit « `note`
       devient optionnelle plutôt que d'inventer une valeur neutre », et une
       annotation restée `NoteBloc` est le signe qu'on a mis un `0.0` ailleurs.
    """
    motif = motif_absence()
    if motif:  # pragma: no cover - chemin nominal avant fusion
        pytest.fail(
            f"{motif}. Tous les autres tests de ce fichier sont en skip et ne "
            "vérifient rien."
        )

    module = module_placement
    annotation = str(module.Emplacement.__annotations__.get("note", ""))
    assert "None" in annotation or "Optional" in annotation, (
        "contrat §2.2 a) : « les non-blocs n'ont pas de note […] `note` devient "
        f"optionnelle ». L'annotation de `Emplacement.note` est {annotation!r} : "
        "si elle n'admet pas None, c'est qu'une valeur neutre a été inventée."
    )


# =============================================================================
# 1. La continuité — le cœur du lot
# =============================================================================


def test_continuite_sur_la_seance_de_reference(monkeypatch):
    """Le cas nominal : 2×20', cinq étapes, aucun demi-tour.

    Attrape : une étape oubliée, deux étapes dans le désordre, un échauffement
    posé à `debut_m = 0` mais de longueur nulle, un retour au calme dont la
    longueur serait la durée et non la distance.
    """
    exiger_lot()
    seance = fab.seance_2x20()
    resultat, _ = placer(monkeypatch, seance, fab.trace_droite(78_000.0))
    fab.verifier_continuite(resultat, seance)


def test_continuite_sans_aucun_bloc(monkeypatch):
    """Une sortie d'endurance uniforme : aucune étape n'est un bloc (Q12).

    `emplacements` était **vide** avant le lot — `_essayer` n'y ajoute rien
    hors des blocs — donc tout code qui suppose « au moins un emplacement »
    n'a jamais été exercé. C'est aussi le cas où un `0.0` injecté dans
    `_note_ponderee` se verrait le moins : sans bloc, la moyenne de notes
    nulles vaut zéro, comme avant.
    """
    exiger_lot()
    seance = fab.seance_sans_bloc()
    resultat, appels = placer(monkeypatch, seance, fab.trace_droite(44_000.0))
    assert len(resultat.emplacements) == 3, (
        "trois étapes, aucun bloc : le contrat §2.2 a) demande trois emplacements, "
        f"obtenu {len(resultat.emplacements)}"
    )
    assert appels == [], (
        "contrat §2.4 « pas de nouvelle note » : aucune étape n'est un bloc, "
        f"`evaluer_couloir` ne doit donc pas être appelé ({len(appels)} appels)"
    )
    fab.verifier_continuite(resultat, seance)


def test_continuite_sur_une_seance_d_une_seule_etape(monkeypatch):
    """Une seule étape élastique : elle ferme, il n'y a pas de levier d'ouverture.

    Attrape un déroulé qui poserait le premier emplacement à la fin du premier
    tour de boucle, ou qui traiterait « l'étape qui ferme » à part au point de
    l'oublier : ici la fermeture **est** toute la séance.
    """
    exiger_lot()
    seance = fab.seance_une_etape()
    resultat, _ = placer(monkeypatch, seance, fab.trace_droite(30_000.0))
    assert len(resultat.emplacements) == 1
    unique = resultat.emplacements[0]
    assert unique.etape_idx == 0
    assert unique.debut_m == pytest.approx(0.0, abs=fab.MARGE_M)
    assert unique.longueur_m == pytest.approx(30_000.0, abs=fab.MARGE_M)
    fab.verifier_continuite(resultat, seance)


def test_continuite_avec_des_etapes_de_duree_nulle(monkeypatch):
    """Une récup de 0 s et un bloc de 0 s : deux étapes au même kilomètre.

    Attrape une implémentation qui filtrerait les longueurs nulles « pour ne
    pas afficher de ligne vide » : elle perdrait des étapes, et
    `verifier_continuite` le dit sur l'ordre des `etape_idx`. Attrape aussi une
    division par la longueur (pour une pente moyenne, une vitesse) qui lèverait
    `ZeroDivisionError` sur ces étapes-là.
    """
    exiger_lot()
    seance = fab.seance_etape_nulle()
    resultat, _ = placer(monkeypatch, seance, fab.trace_droite(50_000.0))
    fab.verifier_continuite(resultat, seance)
    nulles = [e for e in resultat.emplacements if e.etape_idx in (2, 3)]
    assert len(nulles) == 2, "les deux étapes de durée nulle doivent être placées quand même"
    for e in nulles:
        assert e.longueur_m == pytest.approx(0.0, abs=fab.MARGE_M), (
            f"étape {e.etape_idx} dure 0 s : elle ne peut pas couvrir {e.longueur_m:.1f} m"
        )
    assert nulles[0].debut_m == pytest.approx(nulles[1].debut_m, abs=fab.MARGE_M), (
        "deux étapes de durée nulle consécutives tombent au même kilomètre"
    )


def test_continuite_quand_le_retour_au_calme_s_allonge(monkeypatch):
    """Q14 : le retour au calme absorbe et déborde largement (+313 % ici).

    Attrape une implémentation qui donnerait au retour au calme la longueur
    **prescrite** (celle que la séance annonce) au lieu de celle qu'il a
    réellement fallu rouler pour refermer : l'écart est de dizaines de
    kilomètres, la somme des longueurs le crie.
    """
    exiger_lot()
    seance = fab.seance_2x20()
    resultat, _ = placer(monkeypatch, seance, fab.trace_droite(120_000.0))
    fab.verifier_continuite(resultat, seance)
    calme = resultat.emplacements[-1]
    assert calme.etape_idx == 4
    # 30 min prescrites à ~8,2 m/s feraient ~15 km ; il en faut trois fois plus.
    assert calme.longueur_m > 40_000.0, (
        f"le retour au calme couvre {calme.longueur_m / 1000:.1f} km : c'est la durée "
        "prescrite qui a été convertie, pas la distance réellement roulée"
    )


def test_continuite_quand_la_seance_est_amputee(monkeypatch):
    """Le retour au calme tombe à 19 min au lieu de 30 : la séance n'est pas roulée entière.

    Le placement est mauvais (pénalité 6,53) mais il existe, et il doit
    s'afficher en entier. Attrape une implémentation qui n'émettrait
    l'emplacement de fermeture que lorsqu'elle tient sa fenêtre.
    """
    exiger_lot()
    seance = fab.seance_2x20()
    resultat, _ = placer(monkeypatch, seance, fab.trace_droite(62_000.0))
    assert any("raccourci" in a for a in resultat.avertissements), (
        "cette fixture doit produire une séance amputée, sinon elle ne teste rien : "
        f"{resultat.avertissements}"
    )
    fab.verifier_continuite(resultat, seance)


def test_continuite_sur_une_seance_a_trente_et_une_etapes(monkeypatch):
    """15 blocs, 14 récups, deux extrémités : 31 étapes, 31 emplacements."""
    exiger_lot()
    seance = fab.seance_longue()
    resultat, _ = placer(monkeypatch, seance, fab.trace_droite(78_000.0))
    assert len(resultat.emplacements) == 31
    fab.verifier_continuite(resultat, seance)


def test_les_longueurs_ne_recouvrent_rien_deux_fois(monkeypatch):
    """Le contrôle « sans recouvrement », dit dans l'autre sens.

    `verifier_continuite` vérifie que chaque emplacement commence là où le
    précédent finit **sur le compteur kilométrique**. Ici on vérifie qu'aucun
    emplacement n'a une longueur qui dépasse ce que sa durée permet de rouler :
    un recouvrement se traduirait par un emplacement plus long que sa durée à
    la vitesse maximale du jeu d'essai.

    Mutation attrapée : `debut_m` recopié du bloc précédent au lieu d'être
    avancé — la somme resterait juste, la continuité aussi, mais une étape
    couvrirait deux fois sa part.
    """
    exiger_lot()
    seance = fab.seance_2x20()
    resultat, _ = placer(monkeypatch, seance, fab.trace_droite(78_000.0))
    # Sur le plat, la vitesse la plus haute du jeu d'essai est celle du bloc.
    plafond = fab.vitesse_plate(fab.PUISSANCE_BLOC)
    for e in resultat.emplacements:
        duree = float(seance.etapes[e.etape_idx].duree_s)
        if e.etape_idx == 4:
            continue  # le retour au calme est recalculé, sa durée prescrite ne borne rien
        marge = 1.0 + (0.25 if e.etape_idx == 0 else 0.0)  # la Z2 d'ouverture est élastique
        assert e.longueur_m <= duree * plafond * marge + fab.MARGE_M, (
            f"étape {e.etape_idx} : {e.longueur_m:.0f} m en {duree:.0f} s, soit "
            f"{e.longueur_m / max(duree, 1e-9):.1f} m/s — au-dessus du plafond "
            f"{plafond:.1f} m/s. Un emplacement recouvre le suivant."
        )


# =============================================================================
# 2. Les demi-tours — le piège du lot
# =============================================================================


def _resultat_demi_tour(monkeypatch, trace=None):
    """Un placement qui fait exactement un demi-tour, sur un seul bon couloir."""
    attendues = fab.positions_2x20(720.0)
    seance = fab.seance_2x20()
    resultat, _ = placer(
        monkeypatch,
        seance,
        trace if trace is not None else fab.trace_droite(78_000.0),
        bon=(attendues[0] - 50.0, attendues[1] + 50.0),
        demi_tour=True,
        penalite_demi_tour=1.0,
    )
    blocs = fab.blocs_de(resultat, seance)
    assert [e.demi_tour for e in blocs] == [False, True], (
        "cette fixture a besoin du demi-tour pour avoir quelque chose à vérifier : "
        f"{[e.demi_tour for e in blocs]}"
    )
    return seance, resultat


def test_continuite_avec_un_demi_tour(monkeypatch):
    """L'invariant tient sur la figure « bloc → ½ récup → demi-tour → ½ récup → bloc ».

    C'est le cas que `debut_m` seul ne sait pas décrire : la récupération part
    du km 48,0, monte au km 48,9, redescend au km 48,0. `verifier_continuite`
    projette le compteur kilométrique sur le tracé via `jalons_m`, donc il
    accepte cette figure — et refuse une implémentation qui l'aurait aplatie.
    """
    exiger_lot()
    seance, resultat = _resultat_demi_tour(monkeypatch)
    fab.verifier_continuite(resultat, seance)


def test_la_recuperation_du_demi_tour_compte_l_aller_et_le_retour(monkeypatch):
    """**Le test central du lot.** La longueur affichée est ce qui est roulé.

    La récupération de 4 min se coupe en deux autour du demi-tour : 2 min à
    l'aller, 2 min au retour. Son empreinte sur le tracé vaut `b` ≈ 930 m ;
    ce qu'elle fait rouler vaut `2b` ≈ 1 862 m. Le contrat §2.2 a) dit « au
    sens du parcours réellement roulé », donc `2b`.

    Mutation attrapée : `longueur_m = abs(fin − debut)` sur les positions du
    tracé, qui rendrait **zéro** (on repart d'où l'on est parti) ; ou `b`, la
    distance à vol d'oiseau jusqu'au point de demi-tour. L'écart avec la vérité
    est de 930 m au minimum — franc, jamais du bruit flottant.

    Ce que ce test seul ne verrait pas : une implémentation qui mettrait `2b`
    partout, y compris là où il n'y a pas de demi-tour. D'où
    `test_continuite_sur_la_seance_de_reference`, qui l'attrape.
    """
    exiger_lot()
    seance, resultat = _resultat_demi_tour(monkeypatch)
    recup = next(e for e in resultat.emplacements if e.etape_idx == 2)

    tournant = resultat.jalons_m[1]
    fin_bloc1 = next(e for e in resultat.emplacements if e.etape_idx == 1)
    aller = tournant - (fin_bloc1.debut_m + fin_bloc1.longueur_m)
    assert aller > 500.0, (
        f"la fixture doit laisser une demi-récup franche à parcourir ({aller:.0f} m) ; "
        "sinon la différence entre b et 2b se confondrait avec le bruit"
    )
    assert recup.longueur_m == pytest.approx(2.0 * aller, abs=fab.MARGE_M), (
        f"la récupération autour du demi-tour roule {2 * aller:.0f} m (aller-retour) "
        f"et non {recup.longueur_m:.0f} m. Une longueur de {aller:.0f} m serait "
        "l'empreinte sur le tracé ; une longueur nulle serait l'écart entre le "
        "point de départ et le point d'arrivée, qui sont le même."
    )


def test_le_demi_tour_ne_se_compte_pas_deux_fois(monkeypatch):
    """`Proposition.demi_tours` doit rester à 1 sur un placement à un demi-tour.

    Le contrat §2.2 a) garde `demi_tour` « pour les récupérations qui en
    portent un ». Le compteur de `sortie/commande.py` additionne le drapeau sur
    **tous** les emplacements : si la récupération le porte aussi, il passe de
    1 à 2 sans rien lever, et la colonne « demi-tours » du tableau ment.

    Ce test n'impose pas où le drapeau se pose — c'est au lot de trancher — il
    impose que le **compte affiché** reste juste.
    """
    exiger_lot()
    commande = module_commande
    seance, resultat = _resultat_demi_tour(monkeypatch)
    proposition = _proposition(commande, resultat, fab.trace_droite(78_000.0))
    assert proposition.demi_tours == 1, (
        f"un seul demi-tour dans ce placement, {proposition.demi_tours} comptés — "
        "le compteur additionne le drapeau des récupérations en plus de celui des blocs"
    )


def test_un_demi_tour_ecrete_ne_perd_pas_de_distance(monkeypatch):
    """Boucle fermée de 48 km : `jalons_m` et `distance_totale_m` se contredisent déjà.

    **Constat mesuré le 16/09/2026 sur `essai-l5.1`, avant le lot**, et remonté
    au superviseur : sur une boucle fermée, `_variante_demi_tour` ajoute
    `2 × besoin_m` à `distance_m` mais range dans `jalons_m` le point de
    demi-tour **écrêté** par `_Terrain.dans_le_trace`. Sur une boucle de
    48,0 km, les jalons totalisent 96 000 m quand `distance_totale_m` annonce
    97 814 m : **1 814 m d'écart**. C'est une approximation assumée et
    documentée dans `dans_le_trace`, mais le contrat §2.2 a) fait des deux des
    autorités et elles ne peuvent pas toutes les deux avoir raison.

    Ce test n'arbitre pas — ce n'est pas à lui de le faire. Il vérifie la
    moitié de l'invariant qui, elle, ne dépend d'aucun arbitrage : **la somme
    des longueurs affichées vaut `distance_totale_m`**, et aucune étape ne
    manque. Si le lot choisit de suivre `jalons_m`, il affichera 96 km là où
    le placement en a compté 97,8 et ce test le dira.

    `verifier_continuite`, qui exige les deux, n'est volontairement pas appelé
    ici : il échouerait sur une contradiction antérieure au lot.

    Ce que ce test impose en pratique : la longueur d'une étape se prend dans
    le **déroulé**, où `_variante_demi_tour` connaît son `2 × besoin_m`, et non
    dans la géométrie recollée depuis `jalons_m`. Une implémentation de
    référence bâtie sur les seuls jalons échoue ici — vérifié le 16/09/2026.
    """
    exiger_lot()
    seance = fab.seance_2x20()
    attendues = fab.positions_2x20(720.0)
    trace = fab.boucle_carree(cote_m=12_000.0, pas_m=250.0)
    resultat, _ = placer(
        monkeypatch,
        seance,
        trace,
        bon=(attendues[0] - 50.0, attendues[1] + 50.0),
        demi_tour=True,
        penalite_demi_tour=1.0,
    )
    jalons = sum(
        abs(b - a) for a, b in zip(resultat.jalons_m[:-1], resultat.jalons_m[1:], strict=True)
    )
    assert abs(resultat.distance_totale_m - jalons) > 1_000.0, (
        "cette fixture doit reproduire l'écrêtage du jalon de demi-tour, sinon elle "
        f"ne teste rien : jalons {jalons:.0f} m, distance {resultat.distance_totale_m:.0f} m"
    )
    assert [e.etape_idx for e in resultat.emplacements] == list(range(len(seance.etapes)))
    somme = sum(e.longueur_m for e in resultat.emplacements)
    assert somme == pytest.approx(resultat.distance_totale_m, abs=fab.MARGE_M), (
        f"la somme des longueurs vaut {somme:.1f} m pour un parcours de "
        f"{resultat.distance_totale_m:.1f} m. Les jalons, eux, n'en comptent que "
        f"{jalons:.1f} : le lot a suivi les jalons plutôt que la distance roulée."
    )


def test_le_parcours_reconstruit_fait_la_distance_annoncee(monkeypatch):
    """`trace_parcourue` et la somme des longueurs doivent raconter la même sortie.

    Deux chemins indépendants vers la même distance : `jalons_m` recollés en
    géométrie d'un côté, la somme des longueurs d'emplacement de l'autre. Le
    lot ne touche pas au premier ; s'ils divergent, c'est le second qui a
    bougé.
    """
    exiger_lot()
    trace = fab.boucle_carree()
    seance, resultat = _resultat_demi_tour(monkeypatch, trace)
    parcours = placement_resultat.trace_parcourue(resultat, trace)
    somme = sum(e.longueur_m for e in resultat.emplacements)
    assert parcours.distance_m == pytest.approx(somme, rel=0.01), (
        f"le parcours recollé fait {parcours.distance_m / 1000:.2f} km, la somme des "
        f"longueurs d'étape {somme / 1000:.2f} km — ce n'est pas la même sortie"
    )
    assert parcours.distance_m != pytest.approx(trace.distance_m, rel=0.01), (
        "sans écart avec la boucle d'origine, ce test ne vérifie rien : il faut un "
        "demi-tour pour que les deux distances diffèrent"
    )


# =============================================================================
# 3. La note des non-blocs — la régression la plus silencieuse
# =============================================================================


@pytest.mark.parametrize(
    "fabrique, longueur_m, nom",
    [
        (fab.seance_2x20, 78_000.0, "2x20"),
        (fab.seance_sans_bloc, 44_000.0, "sans bloc"),
        (fab.seance_une_etape, 30_000.0, "une seule étape"),
        (fab.seance_longue, 78_000.0, "31 étapes"),
    ],
)
def test_aucun_non_bloc_ne_porte_de_note(monkeypatch, fabrique, longueur_m, nom):
    """`note is None` pour tout ce qui n'est pas un bloc. Pas `0.0`, pas un objet neutre.

    Mutation attrapée : `note=NoteBloc(0.0)` posé « pour ne pas avoir de None à
    gérer ». Le champ serait alors indiscernable d'un couloir parfait, et il
    entrerait dans toutes les moyennes.

    L'assertion est signée, pas un `is None or isinstance(...)` : celui-là ne
    peut pas échouer et ne vérifie rien.
    """
    exiger_lot()
    seance = fabrique()
    resultat, _ = placer(monkeypatch, seance, fab.trace_droite(longueur_m))
    for e in resultat.emplacements:
        etape = seance.etapes[e.etape_idx]
        if etape.type == "bloc":
            assert e.note is not None, f"{nom} : le bloc {e.etape_idx} a perdu sa note"
        else:
            assert e.note is None, (
                f"{nom} : l'étape {e.etape_idx} ({etape.type}) porte une note "
                f"{fab.note_de(e)!r}. Le contrat §2.2 a) dit « les non-blocs n'ont "
                "**pas** de note » : aucun terrain n'est évalué sous une récupération."
            )


def test_la_note_de_terrain_ne_se_dilue_pas_dans_les_non_blocs(monkeypatch):
    """Le `0.0` silencieux, mesuré : 10,00 attendu, 2,99 si les non-blocs comptent.

    Terrain uniformément mauvais (10,0), donc les deux blocs valent 10 et
    `note_terrain` vaut 10. Si les trois non-blocs entraient dans la moyenne
    pondérée avec une note nulle, elle tomberait à
    `(10×1200 + 10×1200) / (3600+1200+240+1200+1800)` = **2,985**.

    L'écart est de 7 points : aucune marge flottante ne peut l'expliquer. La
    comparaison est faite à `abs=1e-12` — dix ordres de grandeur sous l'écart
    cherché, et bien au-dessus du bruit d'une somme réassociée.
    """
    exiger_lot()
    seance = fab.seance_2x20()
    resultat, _ = placer(
        monkeypatch, seance, fab.trace_droite(78_000.0), bon=(-2.0, -1.0), mauvais=10.0
    )
    dilue = (10.0 * 1200.0 + 10.0 * 1200.0) / (3600.0 + 1200.0 + 240.0 + 1200.0 + 1800.0)
    assert resultat.note_terrain == pytest.approx(10.0, abs=1e-12), (
        f"note_terrain = {resultat.note_terrain!r} au lieu de 10,0. "
        f"La valeur diluée par cinq étapes vaudrait {dilue:.3f} ; "
        f"obtenu {resultat.note_terrain:.3f}."
    )


def test_evaluer_couloir_n_est_appele_que_sur_les_blocs(monkeypatch):
    """§2.4 « pas de nouvelle note » : rien d'autre qu'un bloc ne passe au terrain.

    Contrôle en amont du précédent : même si le lot jetait la note d'un non-bloc
    après l'avoir calculée, le fait de l'avoir calculée prouverait qu'un `0.0`
    existe quelque part — et coûterait le temps d'évaluation d'un couloir à
    chaque décalage essayé.

    On vérifie les **longueurs** évaluées, pas leur nombre : `placer` balaie
    plusieurs décalages, donc chaque bloc est évalué plusieurs fois. Aucune des
    longueurs évaluées ne doit correspondre à une étape non-bloc.
    """
    exiger_lot()
    seance = fab.seance_2x20()
    resultat, appels = placer(monkeypatch, seance, fab.trace_droite(78_000.0))
    non_blocs = {
        round(e.longueur_m, 3)
        for e in resultat.emplacements
        if seance.etapes[e.etape_idx].type != "bloc"
    }
    evaluees = {round(longueur, 3) for _, longueur, _, _ in appels}
    communes = non_blocs & evaluees - {0.0}
    assert not communes, (
        f"des longueurs de non-blocs ont été passées à `evaluer_couloir` : {sorted(communes)}"
    )
    assert appels, "aucun couloir évalué : la fixture ne teste plus rien"


def test_la_note_de_terrain_est_la_moyenne_ponderee_des_seuls_blocs(monkeypatch):
    """Recalcul indépendant de `note_terrain` à partir des blocs et de leurs durées.

    Un bon couloir pour le premier bloc, un mauvais pour le second : la moyenne
    pondérée n'est plus dégénérée, donc une pondération fausse (moyenne simple,
    poids par longueur au lieu de durée) se verrait. Les deux blocs ayant ici
    la même durée, on ajoute un troisième cas — la séance longue, dont les
    blocs sont tous de 3 min — pour ne pas se reposer sur une symétrie.
    """
    exiger_lot()
    seance = fab.seance_2x20()
    attendues = fab.positions_2x20(720.0)
    resultat, _ = placer(
        monkeypatch,
        seance,
        fab.trace_droite(78_000.0),
        bon=(attendues[0] - 50.0, attendues[1] + 50.0),
        mauvais=8.0,
    )
    blocs = fab.blocs_de(resultat, seance)
    poids = [float(seance.etapes[e.etape_idx].duree_s) for e in blocs]
    attendu = sum(fab.note_de(e) * p for e, p in zip(blocs, poids, strict=True)) / sum(poids)
    assert resultat.note_terrain == pytest.approx(attendu, abs=1e-12), (
        f"note_terrain = {resultat.note_terrain!r}, recalculée sur les seuls blocs "
        f"= {attendu!r}"
    )
    assert len({fab.note_de(e) for e in blocs}) == 2, (
        "cette fixture doit produire deux notes différentes, sinon la pondération "
        f"n'est pas testée : {[fab.note_de(e) for e in blocs]}"
    )


def test_la_note_d_un_bloc_reste_lisible_sans_passer_par_un_optionnel(monkeypatch):
    """Les blocs gardent `note.note`, `note.motifs` et le reste de `NoteBloc`.

    Attrape un lot qui aurait remplacé `note` par un flottant nu pour se
    débarrasser du `None` : l'affichage et la carte lisent `note.motifs`,
    `note.pente_moyenne`, `note.km_batis`.
    """
    exiger_lot()
    seance = fab.seance_2x20()
    resultat, _ = placer(monkeypatch, seance, fab.trace_droite(78_000.0), bon=(-2.0, -1.0))
    for e in fab.blocs_de(resultat, seance):
        for champ in ("note", "motifs", "pente_moyenne", "pente_max", "carrefours",
                      "km_batis", "descente_m", "montee_m"):
            assert hasattr(e.note, champ), (
                f"la note du bloc {e.etape_idx} a perdu `{champ}` : l'affichage et la "
                "carte le lisent"
            )
        assert e.note.motifs, "un couloir hors du bon segment doit porter un motif"


# =============================================================================
# 4. Non-régression — valeurs figées sur `essai-l5.1` AVANT le lot
# =============================================================================

#: Relevé le 16/09/2026 sur `essai-l5.1` (`f4f0cb5`), par `placer` sur les
#: fixtures de `fabriques_seance_visible`, **avant** que le lot L5.2 soit écrit. Le lot est
#: un lot d'affichage : aucune de ces valeurs n'a le droit de bouger.
#:
#: La comparaison est **exacte**. Si un jour l'écart constaté est de l'ordre de
#: 10⁻¹⁶, c'est une somme réassociée et non une régression — mais elle doit
#: alors être vue et assumée, pas absorbée par une marge posée d'avance.
GOLDEN: dict[str, dict[str, Any]] = {
    "reference": {
        "trace_m": 78_000.0,
        "options": {},
        "decalage_z2_s": 720.0,
        "note_totale": 0.060107866226901396,
        "note_terrain": 0.0,
        "penalite_seance": 0.060107866226901396,
        "duree_totale_s": 9120.647197361408,
        "distance_totale_m": 78000.0,
        "jalons_m": [0.0, 78000.0],
        "blocs": [(1, 37047.0438, 10929.217), (3, 49837.8623, 10929.217)],
        "n_blocs_bien_places": 2,
        "n_demi_tours": 0,
    },
    "terrain_mauvais": {
        "trace_m": 78_000.0,
        "options": {"bon": (-2.0, -1.0), "mauvais": 10.0},
        "decalage_z2_s": 720.0,
        "note_totale": 10.060107866226902,
        "note_terrain": 10.0,
        "penalite_seance": 0.060107866226901396,
        "duree_totale_s": 9120.647197361408,
        "distance_totale_m": 78000.0,
        "jalons_m": [0.0, 78000.0],
        "blocs": [(1, 37047.0438, 10929.217), (3, 49837.8623, 10929.217)],
        "n_blocs_bien_places": 0,
        "n_demi_tours": 0,
    },
    "demi_tour": {
        "trace_m": 78_000.0,
        "options": {"bon": (37_047.0438 - 50.0, 47_976.2608 + 50.0), "demi_tour": True},
        "kw": {"penalite_demi_tour": 1.0},
        "decalage_z2_s": 720.0,
        "note_totale": 0.9741538496532103,
        "note_terrain": 0.5,
        "penalite_seance": 0.4741538496532103,
        "duree_totale_s": 11604.923097919262,
        "distance_totale_m": 97814.12313337634,
        "jalons_m": [0.0, 48907.06156668817, 0.0],
        "blocs": [(1, 37047.0438, 10929.217), (3, 37047.0438, 10929.217)],
        "n_blocs_bien_places": 1,
        "n_demi_tours": 1,
    },
    "calme_allonge": {
        "trace_m": 120_000.0,
        "options": {},
        "decalage_z2_s": 720.0,
        "note_totale": 0.9377612040429016,
        "note_terrain": 0.0,
        "penalite_seance": 0.9377612040429016,
        "duree_totale_s": 14386.567224257411,
        "distance_totale_m": 120000.0,
        "jalons_m": [0.0, 120000.0],
        "blocs": [(1, 37047.0438, 10929.217), (3, 49837.8623, 10929.217)],
        "n_blocs_bien_places": 2,
        "n_demi_tours": 0,
    },
    "seance_amputee": {
        "trace_m": 62_000.0,
        "options": {},
        "decalage_z2_s": -180.0,
        "note_totale": 6.5302806969214595,
        "note_terrain": 0.0,
        "penalite_seance": 6.5302806969214595,
        "duree_totale_s": 7182.274737277068,
        "distance_totale_m": 62000.0,
        "jalons_m": [0.0, 62000.0],
        "blocs": [(1, 29328.9097, 10929.217), (3, 42119.7281, 10929.217)],
        "n_blocs_bien_places": 2,
        "n_demi_tours": 0,
    },
}


@pytest.mark.parametrize("cas", sorted(GOLDEN))
def test_le_lot_d_affichage_ne_change_aucune_note(monkeypatch, cas):
    """Les notes, la pénalité, le décalage retenu et les jalons, au bit près.

    Mutations attrapées, toutes silencieuses :
    * un `0.0` de non-bloc entré dans la moyenne pondérée → `note_terrain` ;
    * un emplacement de non-bloc compté dans `_penalite_seance` → `penalite` ;
    * un déroulé réécrit qui changerait l'ordre des décalages essayés, donc
      lequel gagne à égalité → `decalage_z2_s` ;
    * un demi-tour arbitré autrement → `jalons_m` et `distance_totale_m`.
    """
    exiger_lot()
    attendu = GOLDEN[cas]
    seance = fab.seance_2x20()
    resultat, _ = placer(
        monkeypatch,
        seance,
        fab.trace_droite(attendu["trace_m"]),
        **attendu["options"],
        **attendu.get("kw", {}),
    )
    assert resultat.decalage_z2_s == attendu["decalage_z2_s"]
    assert resultat.note_terrain == attendu["note_terrain"]
    assert resultat.penalite_seance == attendu["penalite_seance"]
    assert resultat.note_totale == attendu["note_totale"]
    assert resultat.duree_totale_s == attendu["duree_totale_s"]
    assert resultat.distance_totale_m == attendu["distance_totale_m"]
    assert resultat.jalons_m == attendu["jalons_m"]


@pytest.mark.parametrize("cas", sorted(GOLDEN))
def test_les_blocs_gardent_exactement_leur_place(monkeypatch, cas):
    """Le filtre « blocs » rend ce que `emplacements` rendait avant le lot.

    C'est la garantie de compatibilité du contrat §2.2 a) : « les appelants qui
    ne veulent que les blocs doivent le rester simplement ». Les positions sont
    comparées à 0,1 mm, le format dans lequel elles ont été relevées.
    """
    exiger_lot()
    attendu = GOLDEN[cas]
    seance = fab.seance_2x20()
    resultat, _ = placer(
        monkeypatch,
        seance,
        fab.trace_droite(attendu["trace_m"]),
        **attendu["options"],
        **attendu.get("kw", {}),
    )
    blocs = fab.blocs_de(resultat, seance)
    obtenu = [(e.etape_idx, round(e.debut_m, 4), round(e.longueur_m, 4)) for e in blocs]
    assert obtenu == [tuple(t) for t in attendu["blocs"]], (
        f"{cas} : les blocs ont bougé. Le lot L5.2 est un lot d'affichage (§2.4)."
    )


@pytest.mark.parametrize("cas", sorted(GOLDEN))
def test_l_identite_note_totale_terrain_plus_penalite(monkeypatch, cas):
    """`note_totale = note_terrain + penalite_seance`, écrite dans `Placement`.

    Elle tient aujourd'hui **par construction**. Elle peut se casser si le lot
    recalcule `note_terrain` après coup, pour l'affichage, sans refaire la
    somme — auquel cas le tableau et le détail se contrediraient.

    La marge est `abs=1e-12` : la somme de deux flottants déjà arrondis ne
    dérive pas au-delà, et le plus petit désaccord qui vaille la peine d'être
    signalé (une pénalité de demi-tour, 0,5) est 5·10¹¹ fois plus grand.
    """
    exiger_lot()
    attendu = GOLDEN[cas]
    seance = fab.seance_2x20()
    resultat, _ = placer(
        monkeypatch,
        seance,
        fab.trace_droite(attendu["trace_m"]),
        **attendu["options"],
        **attendu.get("kw", {}),
    )
    assert resultat.note_totale == pytest.approx(
        resultat.note_terrain + resultat.penalite_seance, abs=1e-12
    ), (
        f"{cas} : note_totale {resultat.note_totale!r} ≠ terrain "
        f"{resultat.note_terrain!r} + extrémités {resultat.penalite_seance!r}"
    )


def test_l_ordre_des_candidates_ne_bouge_pas(monkeypatch):
    """Trois candidates de qualités distinctes : l'ordre de tri est figé.

    `Proposition.tri` trie sur `note_totale` puis la pluie. Les trois tracés
    donnent 0,060 / 0,938 / 6,530 : trois notes franchement séparées, donc le
    classement ne tient pas à une égalité fragile. Si le lot touchait à la
    note, l'ordre basculerait ici avant de basculer chez le mainteneur.
    """
    exiger_lot()
    commande = module_commande
    seance = fab.seance_2x20()
    propositions = []
    for numero, cas in enumerate(("seance_amputee", "calme_allonge", "reference"), start=1):
        attendu = GOLDEN[cas]
        trace = fab.trace_droite(attendu["trace_m"])
        resultat, _ = placer(monkeypatch, seance, trace, **attendu["options"])
        propositions.append((cas, _proposition(commande, resultat, trace, numero=numero)))

    ordre = [cas for cas, _ in sorted(propositions, key=lambda c: c[1].tri)]
    assert ordre == ["reference", "calme_allonge", "seance_amputee"], (
        f"l'ordre des candidates a changé : {ordre}"
    )
    notes = [p.placement.note_totale for _, p in propositions]
    assert min(abs(a - b) for a in notes for b in notes if a != b) > 0.5, (
        "les notes doivent rester franchement séparées, sinon ce test mesure du bruit"
    )


# =============================================================================
# 5. Les compteurs de l'affichage
# =============================================================================


def _proposition(commande: Any, placement_: Any, trace: Any, *, numero: int = 1) -> Any:
    """Une `Proposition` minimale autour d'un placement réel.

    Construite par introspection (`outils.fabriquer`) : le contrat donne les
    champs, pas leur ordre ni leurs défauts.
    """
    from ourouler.boucle.couts import Couts

    couts = fabriquer(
        Couts,
        {
            "km_trafic": 0.0,
            "km_calme": trace.distance_m / 1000.0,
            "km_non_classe": 0.0,
            "km_non_revetu": 0.0,
            "antennes_m": 0.0,
            "virages_gauche": 0,
            "virages_gauche_trafic": 0,
            "virages_droite": 0,
            "sens": "horaire",
            "score": 0.0,
        },
    )
    return fabriquer(
        commande.Proposition,
        {
            "numero": numero,
            "trace": trace,
            "placement": placement_,
            "couts": couts,
            "meteo": None,
            "azimut_deg": 0.0,
            "ecart_relatif": 0.0,
            "part_connue": None,
            "vitesse_kmh": 25.0,
        },
    )


@pytest.mark.parametrize("cas", sorted(GOLDEN))
def test_le_compte_de_blocs_bien_places_ne_compte_que_des_blocs(monkeypatch, cas):
    """`Proposition.blocs_bien_places` lit `e.note.note` sur tous les emplacements.

    Deux façons de se tromper, et le lot doit éviter les deux :

    * ne rien changer → `AttributeError: 'NoneType' object has no attribute
      'note'` dès qu'un non-bloc arrive. Bruyant, donc pas le vrai danger ;
    * remplacer par `e.note.note if e.note else 0.0` → tous les non-blocs
      passent sous le seuil de 1,0 et sont comptés « bien placés ». Sur le cas
      `terrain_mauvais`, le compte passerait de **0 à 3** : silencieux, faux, et
      c'est précisément la mesure que le mainteneur lit pour choisir.
    """
    exiger_lot()
    commande = module_commande
    attendu = GOLDEN[cas]
    seance = fab.seance_2x20()
    trace = fab.trace_droite(attendu["trace_m"])
    resultat, _ = placer(
        monkeypatch, seance, trace, **attendu["options"], **attendu.get("kw", {})
    )
    proposition = _proposition(commande, resultat, trace)
    assert proposition.blocs_bien_places == attendu["n_blocs_bien_places"], (
        f"{cas} : {proposition.blocs_bien_places} blocs bien placés annoncés pour "
        f"{attendu['n_blocs_bien_places']} réels — le compteur ratisse les non-blocs"
    )
    assert proposition.demi_tours == attendu["n_demi_tours"], (
        f"{cas} : {proposition.demi_tours} demi-tours annoncés pour "
        f"{attendu['n_demi_tours']} réels"
    )


def test_le_denominateur_du_tableau_est_le_nombre_de_blocs(monkeypatch):
    """La cellule « x/y blocs bien placés » : `y` est un nombre de **blocs**.

    Aujourd'hui `y = len(placement.emplacements)`. Sur la séance d'essai, cette
    cellule passerait de « 2/2 » à « 2/5 » le jour où les emplacements portent
    toutes les étapes : le mainteneur lirait que trois blocs sont mal placés
    alors que la séance n'en compte que deux.

    C'est du texte, donc l'assertion porte sur la chaîne rendue : elle est ce
    que le mainteneur lit.
    """
    exiger_lot()
    commande = module_commande
    seance = fab.seance_2x20()
    trace = fab.trace_droite(78_000.0)
    resultat, _ = placer(monkeypatch, seance, trace)
    proposition = _proposition(commande, resultat, trace)
    cellules = module_sortie._cellules(proposition, set())
    fractions = [c for c in cellules if re.fullmatch(r"\d+/\d+", c)]
    assert fractions == ["2/2"], (
        f"la cellule « blocs bien placés » vaut {fractions} ; la séance a 2 blocs "
        f"et {len(seance.etapes)} étapes, donc « 2/2 » et non « 2/{len(seance.etapes)} »"
    )


# =============================================================================
# 6. L'affichage texte (§2.2 b)
# =============================================================================


def _lignes_seance(commande: Any, proposition: Any, seance: Any) -> list[str]:
    """`_seance_placee`, qui ne lit du contexte que `contexte.seance`."""
    assert hasattr(module_sortie, "_seance_placee"), (
        "`rendu.sortie._seance_placee` a disparu : c'est la fonction que le "
        "contrat §2.2 b) fait évoluer, et six tests de ce fichier la visent"
    )
    return module_sortie._seance_placee(proposition, SimpleNamespace(seance=seance))


def test_toutes_les_etapes_sont_listees_avec_leur_kilometrage(monkeypatch):
    """§2.2 b) : une ligne par étape, avec son kilomètre de début et de fin.

    Le défaut d'origine (Q13) : « t'as pas oublié l'échauffement ? » — 13,2 km
    invisibles. On exige donc, pour **chaque** étape, une ligne portant à la
    fois son km de début et son km de fin, au format français du module
    (`_fr`), le même qu'à l'écran.

    L'assertion ne suppose ni le séparateur (« → »), ni l'ordre des colonnes,
    ni le libellé : seulement que les deux nombres tombent sur la même ligne.
    """
    exiger_lot()
    commande = module_commande
    seance = fab.seance_2x20()
    trace = fab.trace_droite(78_000.0)
    resultat, _ = placer(monkeypatch, seance, trace)
    lignes = _lignes_seance(commande, _proposition(commande, resultat, trace), seance)

    vues = []
    for e in resultat.emplacements:
        debut = nombre_fr(e.debut_m / 1000.0, 1)
        fin = nombre_fr((e.debut_m + e.longueur_m) / 1000.0, 1)
        portantes = [ligne for ligne in lignes if debut in ligne and fin in ligne]
        assert portantes, (
            f"étape {e.etape_idx} ({seance.etapes[e.etape_idx].type}) : aucune ligne ne "
            f"porte « km {debut} » et « km {fin} ». Lignes rendues :\n"
            + "\n".join(lignes)
        )
        vues.append(portantes[0])
    assert len(set(vues)) == len(seance.etapes), (
        "chaque étape doit avoir sa propre ligne ; deux étapes se partagent la même :\n"
        + "\n".join(lignes)
    )


def test_la_colonne_de_note_reste_vide_pour_les_non_blocs(monkeypatch):
    """§2.2 b) : « les autres n'en ont pas et la colonne reste vide plutôt que
    de porter un tiret ambigu ».

    Terrain uniformément mauvais : la note des blocs vaut 10,00, chaîne
    distinctive. Elle doit apparaître exactement deux fois — une par bloc — et
    aucune ligne d'étape ne doit porter « 0,00 », qui serait la valeur neutre
    inventée.
    """
    exiger_lot()
    commande = module_commande
    seance = fab.seance_2x20()
    trace = fab.trace_droite(78_000.0)
    resultat, _ = placer(monkeypatch, seance, trace, bon=(-2.0, -1.0), mauvais=10.0)
    lignes = _lignes_seance(commande, _proposition(commande, resultat, trace), seance)

    lignes_etapes = []
    for e in resultat.emplacements:
        debut = nombre_fr(e.debut_m / 1000.0, 1)
        fin = nombre_fr((e.debut_m + e.longueur_m) / 1000.0, 1)
        lignes_etapes.append(
            (e, next(ligne for ligne in lignes if debut in ligne and fin in ligne))
        )

    for e, ligne in lignes_etapes:
        if seance.etapes[e.etape_idx].type == "bloc":
            assert "10,00" in ligne, f"le bloc {e.etape_idx} doit garder sa note : {ligne!r}"
        else:
            assert "note" not in ligne.casefold(), (
                f"l'étape {e.etape_idx} n'est pas un bloc et sa ligne annonce une "
                f"note : {ligne!r}"
            )
            assert "0,00" not in ligne, (
                f"l'étape {e.etape_idx} porte « 0,00 » : la valeur neutre a été "
                f"inventée quelque part. {ligne!r}"
            )


def test_l_affichage_d_une_seance_tres_longue_reste_coherent(monkeypatch):
    """31 étapes : autant de lignes, aucune tronquée en silence.

    Attrape une pagination discrète (« … et 21 autres ») qui reproduirait le
    défaut de Q13 sous une autre forme : ce qu'on ne voit pas, on ne le vérifie
    pas.
    """
    exiger_lot()
    commande = module_commande
    seance = fab.seance_longue()
    trace = fab.trace_droite(78_000.0)
    resultat, _ = placer(monkeypatch, seance, trace)
    lignes = _lignes_seance(commande, _proposition(commande, resultat, trace), seance)
    texte = "\n".join(lignes)
    for e in resultat.emplacements:
        debut = nombre_fr(e.debut_m / 1000.0, 1)
        fin = nombre_fr((e.debut_m + e.longueur_m) / 1000.0, 1)
        assert any(debut in ligne and fin in ligne for ligne in lignes), (
            f"étape {e.etape_idx} absente de l'affichage d'une séance à 31 étapes"
        )
    assert "…" not in texte and "..." not in texte, (
        "une séance longue ne se tronque pas : c'est le défaut de Q13 sous une autre forme"
    )


def test_l_affichage_supporte_deux_etapes_au_meme_kilometre(monkeypatch):
    """Deux étapes de durée nulle tombent au même km : l'affichage ne doit pas lever.

    Attrape une division par la longueur pour une vitesse moyenne, et un
    `min()`/`max()` sur une plage vide.
    """
    exiger_lot()
    commande = module_commande
    seance = fab.seance_etape_nulle()
    trace = fab.trace_droite(50_000.0)
    resultat, _ = placer(monkeypatch, seance, trace)
    lignes = _lignes_seance(commande, _proposition(commande, resultat, trace), seance)
    assert len(lignes) >= len(seance.etapes), (
        f"{len(lignes)} lignes pour {len(seance.etapes)} étapes"
    )
    assert all(isinstance(ligne, str) for ligne in lignes)


def test_le_json_porte_toutes_les_etapes_et_aucune_note_inventee(monkeypatch):
    """`--json` : la sortie machine doit dire la même chose que le texte.

    Elle porte aujourd'hui `"note": round(e.note.note, 4)` sans condition. Le
    lot doit y mettre `null` pour les non-blocs — un `0.0` y serait lu par un
    script comme un couloir parfait.

    La clé « note » est cherchée où qu'elle soit dans la structure, sans
    supposer le chemin : le contrat ne fige pas le schéma.
    """
    exiger_lot()
    commande = module_commande
    seance = fab.seance_2x20()
    trace = fab.trace_droite(78_000.0)
    resultat, _ = placer(monkeypatch, seance, trace, bon=(-2.0, -1.0), mauvais=10.0)
    charge = rendu_json._candidate_json(_proposition(commande, resultat, trace))
    json.dumps(charge, ensure_ascii=False)  # doit rester sérialisable tel quel

    emplacements = charge["placement"]["emplacements"]
    assert len(emplacements) == len(seance.etapes), (
        f"{len(emplacements)} emplacements en JSON pour {len(seance.etapes)} étapes"
    )
    for entree in emplacements:
        etape = seance.etapes[entree["etape_idx"]]
        if etape.type == "bloc":
            assert entree.get("note") == pytest.approx(10.0), entree
        else:
            assert entree.get("note") is None, (
                f"l'étape {entree['etape_idx']} ({etape.type}) porte une note en JSON : "
                f"{entree.get('note')!r}. Un script la lirait comme un couloir parfait."
            )


# =============================================================================
# 7. La carte (§2.2 c)
# =============================================================================


def _charge_de_la_page(page: str) -> dict:
    """Le JSON que la page embarque, relu depuis le HTML.

    On ne suppose pas le nom des nouvelles clés : on relit l'objet entier.
    """
    bruts = re.findall(r"=\s*(\{.*?\});?\s*\n", page, flags=re.S)
    for brut in sorted(bruts, key=len, reverse=True):
        try:
            return json.loads(brut)
        except json.JSONDecodeError:
            continue
    raise AssertionError("aucune charge JSON lisible dans la page de la carte")


def _points_dessines(noeud: Any, cle: str | None = None, sauf: str = "trace") -> list[tuple[float, float]]:
    """Toutes les paires (lat, lon) de la charge, hors de la clé `sauf`.

    Le tracé complet est dessiné en gris sous tout le reste : c'est lui qui
    représente « ce que la séance ne parcourt pas ». On collecte donc ce qui
    est dessiné **en plus**, quel que soit le nom que le lot lui donne.
    """
    if cle == sauf:
        return []
    if isinstance(noeud, dict):
        points: list[tuple[float, float]] = []
        for k, v in noeud.items():
            points += _points_dessines(v, k, sauf)
        return points
    if isinstance(noeud, list):
        if (
            len(noeud) == 2
            and all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in noeud)
            and abs(noeud[0]) <= 90.0
            and abs(noeud[1]) <= 180.0
        ):
            return [(float(noeud[0]), float(noeud[1]))]
        points = []
        for element in noeud:
            points += _points_dessines(element, cle, sauf)
        return points
    return []


def _distance_min(points: list[tuple[float, float]], cible: Any) -> float:
    from ourouler.noyau.trace import PointTrace, distance_m

    return min(
        (
            distance_m(PointTrace(lat=lat, lon=lon, alt_m=None, dist_m=0.0), cible)
            for lat, lon in points
        ),
        default=math.inf,
    )


def test_la_carte_distingue_ce_qui_est_roule_de_ce_qui_ne_l_est_pas(monkeypatch):
    """§2.2 c) : le cœur du reproche de Q13, rendu mesurable.

    Placement à un demi-tour sur une droite de 78 km : on roule de 0 au km 48,9
    puis on revient. Les 29 km au-delà du demi-tour ne sont **jamais
    parcourus**.

    Deux exigences, l'une positive, l'autre négative :

    * le km 18, en plein échauffement, doit être couvert par une géométrie
      dessinée en plus du tracé gris ;
    * le km 65, jamais parcouru, ne doit l'être par aucune.

    Aujourd'hui la seconde échoue : `carte._liaisons` prend « du dernier bloc à
    la fin du tracé » et peint donc en liaison 29 km qu'on ne roule pas.

    Après le lot, la mutation la plus probable est l'inverse — nourrie de tous
    les emplacements, `_liaisons` ne trouve plus aucun trou entre deux blocs et
    ne dessine plus rien du tout : c'est la première exigence qui tombe.
    Les deux moitiés sont donc nécessaires.
    """
    exiger_lot()
    carte = module_carte
    trace = fab.trace_droite(78_000.0)
    seance, resultat = _resultat_demi_tour(monkeypatch, trace)
    page = carte.construire(trace, seance, resultat)
    charge = _charge_de_la_page(page)
    dessines = _points_dessines(charge)
    assert dessines, "la carte ne dessine rien en plus du tracé gris"

    tournant = resultat.jalons_m[1]
    roule = trace.points[int(18_000.0 // 500.0)]
    jamais = trace.points[int(65_000.0 // 500.0)]
    assert 18_000.0 < tournant < 65_000.0, "la fixture doit encadrer le demi-tour"

    assert _distance_min(dessines, roule) < 200.0, (
        "le km 18 est en plein échauffement : il est roulé, et la carte doit le "
        "montrer autrement que par le tracé gris de fond (§2.2 c)"
    )
    assert _distance_min(dessines, jamais) > 500.0, (
        f"le km 65 est au-delà du demi-tour (km {tournant / 1000:.1f}) : il n'est "
        "jamais parcouru, et la carte le peint pourtant comme une portion roulée — "
        "c'est exactement ce que Q13 reproche"
    )


HOSTILE = (
    "</script><img src=x onerror=alert(1)> & \"guillemets\" 'simples' "
    "<b>gras</b>   sentinelle-l52"
)


def test_un_libelle_hostile_ne_casse_pas_le_html_de_la_carte(monkeypatch):
    """Un libellé d'étape qui essaie de sortir du `<script>` et d'ouvrir une balise.

    Le lot ajoute à la carte des étapes qui n'y entraient pas : leur libellé
    vient d'Intervals.icu, donc d'une source que le projet ne contrôle pas.

    **Ce que ce test attrape, mesuré par mutation le 16/09/2026 :** un libellé
    (ou un titre, ou une note) interpolé dans le HTML **hors** de la charge
    JSON — une légende des étapes assemblée à la f-string, par exemple. C'est
    le chemin que le lot ouvre, et il n'est protégé par rien.

    **Ce qu'il n'attrape pas, et pourquoi c'est correct :** la carte a
    aujourd'hui deux défenses indépendantes sur le chemin de la charge JSON —
    `html.escape` dans `_infobulle` et la neutralisation de `<`, `>`, `&` dans
    `_charge_json`. En retirer **une** laisse la page saine ; ce test reste
    donc vert, et c'est le comportement juste : il vérifie la propriété qui
    compte (la page n'est pas injectable), pas l'implémentation. Il vire au
    rouge dès que les deux tombent — vérifié.
    """
    exiger_lot()
    carte = module_carte

    def _seance_libellee(libelle: str) -> Any:
        return fab.seance(
            [
                fab.etape("echauffement", 60, fab.PUISSANCE_Z2, elastique=True, libelle=libelle),
                fab.etape("bloc", 20, fab.PUISSANCE_BLOC, libelle=libelle),
                fab.etape("recuperation", 4, fab.PUISSANCE_RECUP, libelle=libelle),
                fab.etape("bloc", 20, fab.PUISSANCE_BLOC, libelle=libelle),
                fab.etape("calme", 30, fab.PUISSANCE_CALME, elastique=True, libelle=libelle),
            ],
            nom=libelle,
        )

    seance = _seance_libellee(HOSTILE)
    trace = fab.trace_droite(78_000.0)
    resultat, _ = placer(monkeypatch, seance, trace)
    page = carte.construire(trace, seance, resultat, sous_titre=HOSTILE, notes=[HOSTILE])

    assert page.count("<script") == page.count("</script>"), (
        "une balise </script> s'est échappée d'une chaîne : la page est injectable"
    )
    assert "<img" not in page, "la balise <img> du libellé n'a pas été échappée"
    assert "<b>gras</b>" not in page, "un libellé ne doit pas pouvoir injecter de balise"

    # Le contrôle sans liste blanche : la même carte avec un libellé inerte doit
    # porter exactement les mêmes balises. `<b>` et `<svg>` sont légitimes (la
    # page les fabrique) ; ce qui compte est qu'un libellé n'en **ajoute** aucune.
    inerte = "etape inerte"
    seance_inerte = _seance_libellee(inerte)
    temoin_placement, _ = placer(monkeypatch, seance_inerte, trace)
    temoin = carte.construire(
        trace, seance_inerte, temoin_placement, sous_titre=inerte, notes=[inerte]
    )
    balises = sorted(nom.casefold() for nom in re.findall(r"<\s*([A-Za-z][\w-]*)", page))
    balises_temoin = sorted(
        nom.casefold() for nom in re.findall(r"<\s*([A-Za-z][\w-]*)", temoin)
    )
    assert balises == balises_temoin, (
        "un libellé hostile a ajouté ou retiré des balises à la page : "
        f"{sorted(set(balises) ^ set(balises_temoin))}"
    )
    # Et la page doit rester lisible : la charge JSON se relit.
    charge = _charge_de_la_page(page)
    assert isinstance(charge, dict) and charge


def test_un_libelle_hostile_ne_casse_pas_l_affichage_texte(monkeypatch):
    """Le même libellé côté terminal : aucune exception, aucun retour à la ligne volé.

    `\\u2028` et `\\u2029` sont des séparateurs de ligne Unicode : un `splitlines()`
    les traite comme des sauts de ligne, ce qui découperait une ligne d'étape en
    deux et ferait mentir tous les comptes de ce fichier.
    """
    exiger_lot()
    commande = module_commande
    etapes = [
        fab.etape("echauffement", 60, fab.PUISSANCE_Z2, elastique=True, libelle=HOSTILE),
        fab.etape("bloc", 20, fab.PUISSANCE_BLOC, libelle=HOSTILE),
        fab.etape("calme", 30, fab.PUISSANCE_CALME, elastique=True, libelle=HOSTILE),
    ]
    seance = fab.seance(etapes, nom=HOSTILE)
    trace = fab.trace_droite(78_000.0)
    resultat, _ = placer(monkeypatch, seance, trace)
    lignes = _lignes_seance(commande, _proposition(commande, resultat, trace), seance)
    assert all(isinstance(ligne, str) for ligne in lignes)
    for ligne in lignes:
        assert "\n" not in ligne, f"une ligne en contient une autre : {ligne!r}"


def test_la_carte_accepte_une_seance_sans_aucun_bloc(monkeypatch):
    """Aucun bloc : `COULEURS_BLOCS[(numero - 1) % 8]` n'a rien à colorer.

    Avant le lot, `placement.emplacements` était vide dans ce cas et
    `_liaisons` peignait le tracé entier. Après, elle contient trois étapes
    dont aucune n'a de note : `_blocs` lirait `emplacement.note.note` sur un
    `None`.
    """
    exiger_lot()
    carte = module_carte
    seance = fab.seance_sans_bloc()
    trace = fab.trace_droite(44_000.0)
    resultat, _ = placer(monkeypatch, seance, trace)
    page = carte.construire(trace, seance, resultat)
    assert page.count("<script") == page.count("</script>")
    charge = _charge_de_la_page(page)
    assert _points_dessines(charge), (
        "une sortie d'endurance est roulée d'un bout à l'autre : la carte doit la "
        "montrer comme parcourue, pas comme un tracé gris"
    )


# =============================================================================
# 8. Les invariants du produit
# =============================================================================


def test_aucune_fixture_de_ce_fichier_ne_porte_de_coordonnee_reelle():
    """Règle absolue 1 : les tracés d'essai sont en pleine mer, au large du Guinée.

    Le scanner global (`test_adv_invariants`) cherche les coordonnées
    françaises ; ce test-ci est positif — il exige que **tout** point de mes
    fixtures reste dans une boîte de 10° autour de `fabriques.LAT0/LON0`, donc
    qu'aucune coordonnée réelle ne puisse s'y glisser ailleurs que dans
    l'Atlantique.
    """
    traces = [fab.trace_droite(78_000.0), fab.trace_droite(120_000.0), fab.boucle_carree()]
    for trace in traces:
        for point in trace.points:
            assert abs(point.lat - fabriques.LAT0) < 10.0, (trace.nom, point)
            assert abs(point.lon - fabriques.LON0) < 10.0, (trace.nom, point)


def test_le_placement_et_la_carte_ne_touchent_ni_disque_ni_horloge(monkeypatch):
    """Règle absolue 2 : le cœur ne sait pas où il tourne.

    `open`, `Path.open`, `datetime.now` et `os.environ.get` sont remplacés par
    des refus le temps d'un placement complet et d'une construction de carte.
    Le lot ajoute du code à `seance/placement.py` et à `rendu/carte.py` ; un
    `datetime.now()` glissé pour dater une étiquette, ou un chemin lu pour
    choisir une palette, tomberait ici.
    """
    exiger_lot()
    carte = module_carte

    import builtins
    import os
    import pathlib

    class Interdit(BaseException):
        """Volontairement hors d'`Exception` : aucun `except` ne peut l'avaler."""

    def refuser(*_a, **_k):
        raise Interdit("le cœur a touché au disque ou à l'environnement")

    seance = fab.seance_2x20()
    trace = fab.trace_droite(78_000.0)
    appels = fab.terrain_factice(monkeypatch)
    module = module_placement

    monkeypatch.setattr(builtins, "open", refuser)
    monkeypatch.setattr(pathlib.Path, "open", refuser)
    monkeypatch.setattr(os.environ, "get", refuser)

    resultat = module.placer(seance, trace, fab.parametres())
    assert resultat is not None
    page = carte.construire(trace, seance, resultat)
    assert page and appels


def test_les_libelles_de_ce_fichier_restent_du_texte_inerte():
    """Contrôle positif du détecteur : `HOSTILE` contient bien de quoi casser une page.

    Sans lui, une chaîne hostile vidée par erreur (un copier-coller malheureux)
    rendrait les deux tests d'échappement verts sans rien vérifier.
    """
    assert "</script>" in HOSTILE
    assert "<img" in HOSTILE
    assert " " in HOSTILE
    assert html.escape(HOSTILE) != HOSTILE
