"""L5.3 — trois propositions contrastées, mises à l'épreuve **en aveugle**.

Écrit contre `docs/sprint5_contrat.md` §3 et CLAUDE.md, sans avoir lu
l'implémentation : ces tests sont datés d'avant elle, sur une branche partie de
`sprint-5` au commit `b2b0a3c`.

## Par où l'on entre

Le contrat §3.3 ne nomme **aucune interface** : ni module, ni fonction, ni
champ. Ces tests passent donc par la seule surface que le contrat promet
vraiment — ce que `ourouler sortie --json` publie — en réutilisant le harnais
de bouchons du sprint 4 (`tests/test_sortie_commande.py` : trois clients
`httpx.MockTransport`, départ fictif à (0, 0), aucune socket). Deux points
d'entrée que le JSON ne peut pas porter, la densité de marqueurs et la question
du vent, sont cherchés par découverte de nom, et la recherche dit ce qu'elle a
cherché quand elle échoue. **Rien n'est deviné en silence** : les endroits où
le contrat ne tranche pas sont remontés au mainteneur, pas comblés ici.

## Ce que ce fichier surveille, par ordre de gravité décroissante

1. **Trois propositions qui se ressemblent.** C'est le défaut que le lot existe
   pour éviter, et le plus facile à livrer sans le voir. On fabrique des
   candidates rigoureusement identiques (le même anneau rendu à chaque azimut)
   et on exige que la commande ne prétende pas qu'elles sont contrastées. Le
   chemin « n'en proposer que deux et le dire » doit exister pour de vrai.
2. **Les phrases.** Vides, partagées, en langage de note, ou fausses. Une
   phrase est une affirmation ; sur un vivier où une seule chose distingue une
   proposition, sa phrase doit parler de cette chose-là.
3. **La séance sans bloc**, cas courant du mainteneur (contrat §3.1.3 b) :
   `note_terrain` vaut zéro partout, le classement est dégénéré, et une
   normalisation min-max sans garde y divise par zéro.
4. **Les deux gardes de la question du vent**, aux bords : seuil, 3 jours
   pile, météo absente, direction inconnue.
5. **La densité de marqueurs**, y compris l'invariant qui se retourne : une
   portion sans nœud tagué n'est pas « la campagne prouvée ».

La non-régression a son propre fichier (`test_adv_l53_non_regression.py`), et
les vérificateurs employés ici sont eux-mêmes éprouvés par vingt-deux mutations
dans `test_adv_l53_autocontrole.py`. Sans ce dernier, rien ne garantirait que
les assertions ci-dessous ne sont pas creuses — c'est la leçon du lot L5.2.

Tant que le lot n'est pas livré, tout ce fichier se met en `skip` sauf
`test_sentinelle_l53_pas_encore_livre`, qui **échoue**, et qui surveille la
vraie interface (la phrase publiée, le nombre de propositions, la densité, la
question du vent) et non la seule existence d'un module.
"""

from __future__ import annotations

import builtins
import math
from pathlib import Path
from typing import Any

import fabriques_l53 as f53
import pytest

MOTIF_PHRASE = (
    "le lot L5.3 n'est pas livré : `ourouler sortie --json` ne publie aucune phrase par "
    "proposition (contrat §3.3.3)"
)
MOTIF_DENSITE = (
    "la densité de marqueurs au kilomètre du contrat §3.3.2 n'est pas trouvable — "
    "aucun appelable public d'ourouler dont le nom évoque « densité » ou « marqueurs/km »"
)
MOTIF_QUESTION = (
    "la question d'orientation au vent du contrat §3.3.4 n'est pas trouvable — aucun "
    "appelable public d'ourouler dont le nom évoque « question/orientation » et « vent »"
)


# --- accès ------------------------------------------------------------------


def _doc(tmp_path: Path, monkeypatch, capsys, **kw) -> dict:
    return f53.lancer_json(tmp_path, monkeypatch, capsys, **kw)


def _choix_ou_skip(doc: dict) -> f53.VueChoix:
    choix = f53.choix_depuis_json(doc)
    if not choix.retenues:
        pytest.skip(MOTIF_PHRASE)
    return choix


def _densite_ou_skip() -> Any:
    fn = f53.decouvrir_callable(f53.MOTIFS_DENSITE, quoi="densité de marqueurs")
    if fn is None:
        pytest.skip(MOTIF_DENSITE)
    return fn


def _question_ou_skip() -> Any:
    fn = f53.decouvrir_callable(f53.MOTIFS_QUESTION_VENT, quoi="question d'orientation au vent")
    if fn is None:
        pytest.skip(MOTIF_QUESTION)
    return fn


# =============================================================================
# Sentinelle
# =============================================================================


def test_sentinelle_l53_pas_encore_livre(tmp_path: Path, monkeypatch, capsys):
    """Le seul test de ce fichier qui échoue quand le lot est absent.

    Il surveille **les trois portes** du lot, pas l'existence d'un module : une
    implémentation qui livrerait les phrases mais pas la densité, ou la densité
    mais pas les gardes du vent, fait échouer la sentinelle sur la ligne qui
    manque. Sans elle, le dossier se lirait « 60 tests passés » alors qu'aucun
    n'aurait rien vérifié.
    """
    manque: list[str] = []

    doc = _doc(tmp_path, monkeypatch, capsys, candidates=4)
    proposees = f53.propositions_du_json(doc)
    if not proposees:
        manque.append(
            "aucune proposition ne porte de phrase dans `sortie --json` (clés cherchées : "
            f"{list(f53.CLES_PHRASE)}) — contrat §3.3.3"
        )
    elif len(proposees) > 3:
        manque.append(
            f"{len(proposees)} propositions publiées : le contrat §3.3.3 en demande **trois** "
            "au plus (« et il vaut mieux n'en proposer que deux »)"
        )

    if f53.decouvrir_callable(f53.MOTIFS_DENSITE, quoi="densité") is None:
        manque.append(MOTIF_DENSITE)
    if f53.decouvrir_callable(f53.MOTIFS_QUESTION_VENT, quoi="question vent") is None:
        manque.append(MOTIF_QUESTION)

    if manque:
        pytest.fail(
            "L5.3 n'est pas (encore) livré, ou son interface a changé de nom. Manquent :\n  - "
            + "\n  - ".join(manque)
            + "\nTous les autres tests de ce fichier sont en skip et ne vérifient rien."
        )


# =============================================================================
# 1. Le cœur du lot : trois propositions qui se ressemblent
# =============================================================================


def test_des_candidates_identiques_ne_font_pas_trois_propositions(
    tmp_path: Path, monkeypatch, capsys
):
    """Le moteur rend **le même anneau** à chaque direction : rien à contraster.

    Même tracé, donc même pluie, même relief, même orientation au vent, mêmes
    demi-tours, même durée, mêmes routes connues. Aucune lecture du contrat ne
    permet d'appeler ces propositions-là contrastées. Le lot doit soit en
    proposer moins, soit dire qu'elles se ressemblent — « il vaut mieux n'en
    proposer que deux et le dire » (§3.3.3).

    Ce test est formulé **sans seuil** : le contrat ne chiffre pas « éloignées »
    (voir les points remontés au mainteneur). On n'exige donc rien de chiffré,
    seulement qu'on ne présente pas deux fois la même sortie comme deux choix.
    """
    doc = _doc(
        tmp_path, monkeypatch, capsys, brouter=f53.moteur_brouter_clone(), candidates=5
    )
    choix = _choix_ou_skip(doc)
    f53.verifier_retenues_bien_formees(choix)
    f53.verifier_pas_de_trio_de_clones(choix)


def test_le_chemin_deux_propositions_existe_vraiment(tmp_path: Path, monkeypatch, capsys):
    """Le contrat autorise à n'en rendre que deux : ce chemin n'est pas théorique.

    Sur des candidates rigoureusement identiques, une implémentation honnête ne
    peut pas en proposer trois. Si elle en propose trois quand même, c'est que
    la porte de sortie n'a jamais été empruntée — le cas qu'elle couvre est
    précisément celui-là.
    """
    doc = _doc(
        tmp_path, monkeypatch, capsys, brouter=f53.moteur_brouter_clone(), candidates=5
    )
    choix = _choix_ou_skip(doc)
    assert len(choix.retenues) < 3, (
        f"{len(choix.retenues)} propositions rendues sur cinq candidates au tracé **identique**. "
        "Le contrat §3.3.3 : « Si aucune phrase n'est écrivable, c'est que les trois ne sont pas "
        "contrastées — et il vaut mieux n'en proposer que deux et le dire. » Trois ici veut dire "
        "que ce chemin n'est jamais emprunté."
    )


def test_les_propositions_ne_sont_pas_le_sommet_d_un_tri_unique(
    tmp_path: Path, monkeypatch, capsys
):
    """Cinq directions contrastables : les retenues doivent être éloignées.

    Le relief et la pluie sont réglés par direction pour que le classement par
    note mette en tête des candidates voisines, et que les extrêmes soient plus
    bas. Un lot qui prend les trois premières du tri rend trois cartes
    jumelles ; un lot qui choisit des représentants va chercher les extrêmes.
    """
    h = f53.harnais()
    reglages = {
        0.0: {"amplitude_m": 1.0},
        72.0: {"amplitude_m": 1.1},
        144.0: {"amplitude_m": 1.2},
        216.0: {"amplitude_m": 25.0, "rayon_deg": h.RAYON_DEG * 1.35},
        288.0: {"amplitude_m": 30.0, "rayon_deg": h.RAYON_DEG * 0.7},
    }
    doc = _doc(
        tmp_path,
        monkeypatch,
        capsys,
        brouter=h.moteur_brouter(reglages),
        meteo=h.moteur_meteo(pluie=h.pluie_au_nord),
        candidates=5,
    )
    choix = _choix_ou_skip(doc)
    f53.verifier_retenues_bien_formees(choix)
    if len(choix.retenues) < 2:
        pytest.skip(
            "le lot n'a rendu qu'une proposition sur ce vivier : l'étalement ne se pose pas"
        )
    f53.verifier_pas_de_trio_de_clones(choix)


def test_aucune_proposition_n_est_publiee_deux_fois(tmp_path: Path, monkeypatch, capsys):
    """Deux propositions qui portent le même tracé sont une seule proposition."""
    h = f53.harnais()
    doc = _doc(
        tmp_path,
        monkeypatch,
        capsys,
        brouter=h.moteur_brouter({0.0: {"amplitude_m": 20.0}}),
        candidates=4,
    )
    proposees = f53.propositions_du_json(doc)
    if not proposees:
        pytest.skip(MOTIF_PHRASE)
    empreintes = [
        (c.get("nom"), c.get("azimut_deg"), c.get("distance_km")) for c in proposees
    ]
    assert len(set(map(repr, empreintes))) == len(empreintes), (
        f"la même boucle est proposée plusieurs fois : {empreintes}"
    )


# =============================================================================
# 2. Les phrases
# =============================================================================


def test_chaque_proposition_porte_une_phrase_utilisable(tmp_path: Path, monkeypatch, capsys):
    """Non vide, unique, en langage de cycliste — jamais « note 1,93 »."""
    h = f53.harnais()
    doc = _doc(
        tmp_path,
        monkeypatch,
        capsys,
        brouter=h.moteur_brouter({216.0: {"amplitude_m": 25.0}, 288.0: {"amplitude_m": 30.0}}),
        meteo=h.moteur_meteo(pluie=h.pluie_au_nord),
        candidates=5,
    )
    choix = _choix_ou_skip(doc)
    f53.verifier_phrases(choix)


def test_aucune_phrase_n_affirme_ce_qui_est_faux(tmp_path: Path, monkeypatch, capsys):
    """« la plus sèche » sur la plus arrosée : l'affirmation doit être vraie.

    Toute tournure du lexique reconnue dans une phrase engage la proposition
    sur l'axe correspondant, et elle doit vraiment y être la meilleure des
    retenues. Une phrase dont aucune tournure n'est reconnue n'est pas
    sanctionnée ici — c'est le test suivant qui s'en charge, sur un vivier où
    une seule chose distingue.
    """
    h = f53.harnais()
    doc = _doc(
        tmp_path,
        monkeypatch,
        capsys,
        brouter=h.moteur_brouter({216.0: {"amplitude_m": 25.0}, 288.0: {"amplitude_m": 30.0}}),
        meteo=h.moteur_meteo(pluie=h.pluie_au_nord),
        candidates=5,
    )
    choix = _choix_ou_skip(doc)
    f53.verifier_phrases_vraies(choix)


def test_la_phrase_parle_de_la_pluie_quand_la_pluie_est_la_seule_difference(
    tmp_path: Path, monkeypatch, capsys
):
    """Un vivier où seule la pluie discrimine : la phrase doit parler de pluie.

    Toutes les directions rendent le même relief ; seule la pluie change, et
    franchement (0 mm au sud, 2 mm/h au nord). La proposition la plus sèche ne
    peut être distinguée que par là. Si sa phrase n'en parle pas, ou si sa
    tournure est absente du lexique de `fabriques_l53.AFFIRMATIONS`, le message
    d'échec dit laquelle des deux hypothèses vérifier — on n'étend pas le
    lexique en silence.
    """
    h = f53.harnais()
    doc = _doc(
        tmp_path,
        monkeypatch,
        capsys,
        meteo=h.moteur_meteo(pluie=h.pluie_au_nord),
        candidates=4,
    )
    choix = _choix_ou_skip(doc)
    if len(choix.retenues) < 2:
        pytest.skip("une seule proposition : aucune phrase ne distingue de quoi que ce soit")
    pluies = [p.axe("pluie_mm") for p in choix.retenues]
    if max(pluies) - min(pluies) < 0.5:
        pytest.skip(
            f"les propositions retenues ne diffèrent pas assez en pluie ({pluies}) pour que la "
            "phrase doive en parler"
        )
    f53.verifier_phrase_parle_du_bon_axe(choix, "pluie_mm", "min")


def test_une_phrase_n_est_jamais_du_langage_de_note(tmp_path: Path, monkeypatch, capsys):
    """Le contrat §3.3.3 : « en langage de cycliste et jamais en langage de note ».

    Contrôle séparé de `verifier_phrases` pour que l'échec dise précisément
    ceci : une note de placement n'est pas une différence perceptible (§3.3.1),
    donc elle n'a rien à faire dans la phrase qui dit ce qui distingue.
    """
    h = f53.harnais()
    doc = _doc(
        tmp_path, monkeypatch, capsys, meteo=h.moteur_meteo(pluie=h.pluie_au_nord), candidates=5
    )
    choix = _choix_ou_skip(doc)
    for p in choix.retenues:
        assert not f53.phrase_est_en_langage_de_note(p.phrase or ""), (
            f"proposition {p.cle!r} : « {p.phrase} ». Le contrat donne les tournures attendues : "
            "« vous rentrez avec le vent dans le dos », « aucun demi-tour », « la plus sèche », "
            "« 20 minutes de moins », « elle évite les villages »."
        )


# =============================================================================
# 3. La séance sans bloc — le cas courant du mainteneur
# =============================================================================


def _seance_endurance():
    """Une EF sans aucun bloc, dans la forme réelle du compte du mainteneur.

    `workouts.sortie_libre()` est la fixture qui reproduit ce que son
    planificateur envoie : un seul groupe marqué `warmup` de bout en bout,
    7 200 s, **aucun bloc**. Contrat §3.1.3 b) : « sur 85 jours, toutes les
    séances vélo planifiées dehors sont des EF ou des sorties cool » — le cas
    endurance n'est pas secondaire, c'est **son cas courant**.

    On ne fabrique pas une séance à blocs artificielle : c'est sur cette
    forme-là que le contraste doit tenir, sans quoi il ne sert jamais.
    """
    f53.harnais()  # met `tests/` sur le chemin d'import
    from test_seance_intervals import W

    return [W.evenement(W.sortie_libre(), nom="EF 2 h fabriquée")]


def test_une_seance_sans_bloc_ne_fait_pas_tomber_la_commande(
    tmp_path: Path, monkeypatch, capsys
):
    """`note_terrain` vaut zéro pour toutes : le classement est dégénéré.

    C'est le cas qui casse une normalisation min-max écrite sans garde — toutes
    les valeurs de l'axe « terrain » sont égales, donc son étendue est nulle, et
    la division tombe. Et c'est **le cas courant** du mainteneur, pas un cas
    limite. On exige ici le minimum incontestable : la commande répond 0, elle
    ne lève pas, et elle ne rend pas trois fois la même chose.
    """
    h = f53.harnais()
    evenements = _seance_endurance()
    doc = _doc(
        tmp_path,
        monkeypatch,
        capsys,
        intervals=h.client_intervals(evenements),
        candidates=5,
    )
    choix = _choix_ou_skip(doc)
    f53.verifier_retenues_bien_formees(choix)
    f53.verifier_pas_de_trio_de_clones(choix)
    f53.verifier_phrases(choix)


def test_une_seance_sans_bloc_note_bien_zero_de_terrain_partout(
    tmp_path: Path, monkeypatch, capsys
):
    """La prémisse de tout le §3.3.2, vérifiée sans dépendre du lot.

    Ce test **ne saute jamais** : il tourne dès aujourd'hui et continuera après
    le lot. Il fige la situation de départ — sur une EF, le terrain ne note
    rien, donc le classement est plat et une normalisation min-max y trouve une
    étendue nulle.

    Il est séparé du test précédent exprès : un `pytest.skip` en milieu de test
    marque **tout** le test « sauté », y compris les assertions déjà exécutées.
    Ces deux-là ne doivent jamais disparaître d'un rapport.
    """
    h = f53.harnais()
    doc = _doc(
        tmp_path,
        monkeypatch,
        capsys,
        intervals=h.client_intervals(_seance_endurance()),
        candidates=5,
    )
    assert (doc.get("seance") or {}).get("n_blocs") == 0, (
        f"la séance fabriquée devait n'avoir aucun bloc : {doc.get('seance')}"
    )
    candidates = doc.get("candidates") or []
    assert candidates, "aucune candidate : la commande n'a rien évalué"
    for candidate in candidates:
        terrain = (candidate.get("placement") or {}).get("note_terrain")
        assert terrain == 0.0, (
            f"séance sans bloc : note_terrain = {terrain!r}, attendu 0,0 exactement "
            "(contrat §3.3.2 : « vaut zéro sur une séance sans bloc, donc jamais seul »)"
        )
    notes = [(c.get("placement") or {}).get("note_totale") for c in candidates]
    assert all(n is not None and math.isfinite(n) for n in notes), (
        f"notes de placement non finies sur une EF : {notes}"
    )


def test_une_seance_sans_bloc_contraste_sur_autre_chose_que_le_terrain(
    tmp_path: Path, monkeypatch, capsys
):
    """Contrat §3.3.2 : les axes ne peuvent pas reposer sur la seule note de terrain.

    Sur une EF, `note_terrain` vaut zéro partout. Si le lot ne sait contraster
    que par là, il rend forcément des propositions jumelles — « sans quoi les
    trois propositions seront identiques sur une EF, c'est-à-dire sur la
    majorité des sorties ». On fait donc varier la pluie franchement, et on
    exige que les propositions en tiennent compte.
    """
    h = f53.harnais()
    evenements = _seance_endurance()
    doc = _doc(
        tmp_path,
        monkeypatch,
        capsys,
        intervals=h.client_intervals(evenements),
        meteo=h.moteur_meteo(pluie=h.pluie_au_nord),
        candidates=5,
    )
    choix = _choix_ou_skip(doc)
    if len(choix.retenues) < 2:
        pytest.skip("une seule proposition rendue : le contraste ne se pose pas")
    pluies = [p.axe("pluie_mm") for p in choix.retenues]
    assert max(pluies) - min(pluies) > 0.1, (
        f"séance sans bloc, pluie franchement variable selon la direction, et les propositions "
        f"retenues portent toutes la même pluie ({pluies}). Le contraste s'est appuyé sur la "
        "seule note de terrain, qui vaut zéro ici — exactement ce que le contrat §3.3.2 "
        "interdit. La marge (0,1 mm) est très au-dessus du bruit d'arrondi du JSON (10⁻³) et "
        "très en dessous de l'écart fabriqué (≈ 2 mm)."
    )


# =============================================================================
# 4. Les deux gardes de la question du vent
# =============================================================================


def _binder(fn: Any):
    """Adapte `fn` à l'appel `(vent_kmh=…, direction_deg=…, jours_a_l_avance=…)`.

    Les noms de paramètres du lot sont inconnus : on les rapproche par mot-clé.
    Un paramètre qu'on ne sait pas nourrir fait **échouer** le test avec la
    signature trouvée — jamais deviner, jamais sauter en silence.
    """
    import inspect

    signature = inspect.signature(fn)
    correspondances = {
        "vent_kmh": ("vent", "vitesse"),
        "direction_deg": ("direction", "depuis", "azimut", "provenance"),
        "jours_a_l_avance": ("jour", "horizon", "avance", "echeance", "delai"),
    }
    plan: dict[str, str] = {}
    for concept, mots in correspondances.items():
        for nom in signature.parameters:
            plat = f53._sans_accents_bas(nom)
            if any(mot in plat for mot in mots) and nom not in plan.values():
                plan[concept] = nom
                break
    manquants = [c for c in correspondances if c not in plan]
    if manquants:
        pytest.fail(
            f"la question du vent ({fn.__module__}.{fn.__name__}{signature}) n'expose pas de "
            f"paramètre reconnaissable pour {manquants}. Les deux gardes du contrat §3.3.4 ne "
            "peuvent pas être vérifiées : à reconcilier avec le mainteneur plutôt qu'à deviner."
        )

    def poser(**kw):
        return fn(**{plan[c]: v for c, v in kw.items() if c in plan})

    return poser


def test_les_deux_gardes_de_la_question_du_vent():
    """Seuil de vent, horizon de 3 jours, météo absente, direction inconnue.

    Le contrat ne chiffre pas le seuil : il dit seulement que 2,5 km/h est
    dessous. Le vérificateur n'exige donc que cela, plus deux propriétés qui ne
    dépendent d'aucune valeur — pas de question à vent nul, et une seule
    bascule sur tout le balayage. L'horizon, lui, est chiffré : 3 jours pile est
    dedans, au-delà l'outil dit qu'il ne sait pas.
    """
    f53.verifier_gardes_vent(_binder(_question_ou_skip()))


def test_la_question_du_vent_ne_lit_ni_configuration_ni_chemin_utilisateur():
    """Règle absolue 2 : seul `cli.py` (et `config.py`) touche au disque.

    Contrôle **d'exécution**, complémentaire du contrôle statique de
    `test_adv_invariants.py` : une fonction qui reçoit un `Config` peut fort
    bien rouvrir un fichier au passage, ce qu'aucune analyse d'imports ne voit.
    """
    poser = _binder(_question_ou_skip())
    _interdire_le_disque(
        lambda: poser(vent_kmh=14.0, direction_deg=250.0, jours_a_l_avance=1.0),
        quoi="la question d'orientation au vent",
    )


def _interdire_le_disque(appel, *, quoi: str) -> None:
    import os

    monkey = pytest.MonkeyPatch()
    try:
        def refus(*a, **kw):
            raise AssertionError(
                f"{quoi} ouvre un fichier : le cœur ne sait pas où il tourne (CLAUDE.md règle 2)"
            )

        monkey.setattr(builtins, "open", refus)
        monkey.setattr(Path, "home", lambda: (_ for _ in ()).throw(AssertionError(
            f"{quoi} lit le foyer de l'utilisateur (CLAUDE.md règle 2)"
        )))
        monkey.setattr(os, "environ", _EnvironInterdit(quoi))
        appel()
    finally:
        monkey.undo()


class _EnvironInterdit(dict):
    def __init__(self, quoi: str):
        super().__init__()
        self._quoi = quoi

    def __getitem__(self, cle):  # pragma: no cover - chemin d'échec
        raise AssertionError(f"{self._quoi} lit l'environnement (CLAUDE.md règle 2)")

    def get(self, *a, **kw):  # pragma: no cover - chemin d'échec
        raise AssertionError(f"{self._quoi} lit l'environnement (CLAUDE.md règle 2)")


# =============================================================================
# 5. La densité de marqueurs au kilomètre
# =============================================================================


def test_la_densite_de_marqueurs_tient_ses_invariants():
    """Longueur nulle, négative, NaN, couloir plus court qu'un pas, nœuds empilés.

    Et surtout la division : 10 marqueurs sur 5 km font 2,0 /km — ni 10 (le
    compte brut, « au kilomètre » oublié), ni 0,002 (divisé par les mètres).
    """
    f53.verifier_densite(_densite_ou_skip(), lire=_lire_densite)


def _lire_densite(valeur: Any) -> f53.Densite:
    """Traduit ce que le lot rend en `Densite(par_km, connue, motif)`.

    Trois formes sont acceptées, parce que le contrat n'en impose aucune et que
    les trois disent honnêtement « je ne sais pas » : `None`, un objet portant
    un drapeau (`connue`, `disponible`, `tags_disponibles`…), ou le nombre
    accompagné d'un motif contenant « inconnu » — c'est l'idiome de
    `terrain.evaluer_couloir`, qui rend zéro et le motif « routes inconnues ».
    """
    if valeur is None:
        return f53.Densite(0.0, connue=False, motif="rendu None")
    if isinstance(valeur, (int, float)):
        return f53.Densite(float(valeur), connue=True)
    if isinstance(valeur, tuple) and len(valeur) == 2:
        return f53.Densite(float(valeur[0]), connue=bool(valeur[1]))
    par_km = None
    for nom in ("par_km", "densite", "valeur", "marqueurs_km", "note"):
        if hasattr(valeur, nom):
            par_km = float(getattr(valeur, nom))
            break
    if par_km is None:
        pytest.fail(
            f"la densité rend {valeur!r} ({type(valeur).__name__}) : impossible d'en lire un "
            "nombre au kilomètre. Interface à reconcilier avec le mainteneur."
        )
    connue = True
    for nom in ("connue", "connu", "disponible", "tags_disponibles", "mesuree"):
        if hasattr(valeur, nom):
            connue = bool(getattr(valeur, nom))
            break
    else:
        motifs = getattr(valeur, "motifs", None) or []
        texte = " ".join(str(m) for m in motifs) if isinstance(motifs, (list, tuple)) else ""
        if "inconnu" in f53._sans_accents_bas(texte):
            connue = False
    return f53.Densite(par_km, connue=connue)


def test_une_portion_sans_noeud_tague_n_est_pas_la_campagne_prouvee():
    """L'invariant qui se retourne, et c'est le plus facile à manquer.

    Le contrat du sprint 3 dit qu'une classe inconnue n'est jamais un malus.
    Ici la faute est symétrique et pire : une portion **sans aucun tag** rendue
    à zéro marqueur au kilomètre devient « la campagne », c'est-à-dire un
    **bonus**, et le lot proposerait par préférence les tracés qu'il ne connaît
    pas. `terrain.evaluer_couloir` fait déjà la distinction (motif « routes
    inconnues ») : la densité doit la faire aussi.
    """
    import fabriques4

    fn = _densite_ou_skip()
    coords = fabriques4.droite(200, pas_m=100.0, cap_deg=90.0, pentes=0.0, alt0=50.0)
    sans_segments = fabriques4.trace_taguee(
        coords, tags={"highway": "tertiary"}, sans_segments=True
    )
    tague_sans_marqueur = fabriques4.trace_taguee(
        coords, tags={"highway": "tertiary"}, node_tags={}
    )
    inconnue = _lire_densite(fn(sans_segments, 2000.0, 5000.0))
    mesuree = _lire_densite(fn(tague_sans_marqueur, 2000.0, 5000.0))
    assert mesuree.connue and mesuree.par_km == 0.0, (
        f"des tronçons tagués sans marqueur : zéro **mesuré** ({mesuree!r})"
    )
    assert not inconnue.connue, (
        f"un tracé sans segments rend {inconnue!r}, indiscernable du précédent. Les deux zéros "
        "ne veulent pas dire la même chose : l'un est « aucun feu », l'autre « aucun tag »."
    )


def test_la_densite_ne_lit_ni_configuration_ni_chemin_utilisateur():
    """Règle absolue 2, contrôle d'exécution."""
    import fabriques4

    fn = _densite_ou_skip()
    trace = f53.boucle_avec_marqueurs(8)
    _interdire_le_disque(
        lambda: fn(trace, 0.0, 5000.0), quoi="la densité de marqueurs"
    )
    assert fabriques4 is not None  # l'import sert la lisibilité de l'échec ci-dessus


def test_la_densite_est_finie_sur_un_trace_sans_point():
    """Un tracé vide : pas de division par une longueur nulle, pas de NaN."""
    from ourouler.boucle.trace import Trace

    fn = _densite_ou_skip()
    vide = Trace(
        nom="vide", points=[], segments=[], distance_m=0.0, denivele_m=None,
        temps_moteur_s=None, meta={},
    )
    lue = _lire_densite(fn(vide, 0.0, 0.0))
    assert math.isfinite(lue.par_km), f"tracé vide : densité {lue.par_km!r}"
    assert not lue.connue, "un tracé vide ne porte aucune densité connue"


def test_la_densite_de_marqueurs_est_publiee(tmp_path: Path, monkeypatch, capsys):
    """Le contrat §3.3.2 en fait un axe : il doit se lire, pas seulement se calculer.

    Un axe qui n'apparaît nulle part dans `--json` ne peut ni être vérifié par
    le mainteneur, ni servir d'explication à une phrase « elle évite les
    villages ». La règle absolue 5 — ne rien affirmer sans mesure — vaut aussi
    pour ce que l'outil affirme de lui-même.
    """
    _densite_ou_skip()  # tant que la mesure n'existe pas, rien à publier
    doc = _doc(tmp_path, monkeypatch, capsys, candidates=3)
    proposees = f53.propositions_du_json(doc) or (doc.get("candidates") or [])
    if not proposees:
        pytest.skip(MOTIF_PHRASE)
    trouves = [
        v
        for c in proposees
        for nom in ("densite", "marqueur")
        for v in f53._profond(c, nom)
        if isinstance(v, (int, float))
    ]
    assert trouves, (
        "aucune densité de marqueurs publiée par candidate dans `sortie --json` (clés "
        "cherchées : « densite », « marqueur »). C'est la seule mesure nouvelle du lot "
        "(contrat §3.3.2) et elle remplace la détection de zone bâtie."
    )
    for valeur in trouves:
        assert math.isfinite(valeur) and valeur >= 0, (
            f"densité publiée non exploitable : {valeur!r}"
        )


# =============================================================================
# 6. Invariants du produit
# =============================================================================


def test_la_sortie_json_reste_serialisable_et_sans_coordonnee_reelle(
    tmp_path: Path, monkeypatch, capsys
):
    """Le lot ajoute des champs : ils doivent rester du JSON, et rien de réel.

    Le départ du harnais est (0, 0) et les anneaux sont fabriqués autour : si
    une coordonnée du document sort de la zone fictive, c'est qu'une donnée
    réelle a été introduite quelque part (CLAUDE.md règle 1).
    """
    import json

    import outils

    doc = _doc(tmp_path, monkeypatch, capsys, candidates=3)
    outils.verifier_json(doc, "sortie --json de `ourouler sortie`")
    # Clés **exactes** : une recherche par sous-chaîne attraperait `longueur_m`
    # (qui contient « lon ») et ferait crier le test sur une longueur en mètres.
    for cle, valeur in f53.valeurs_par_cle_exacte(doc, ("latitude", "longitude", "lat", "lon")):
        if isinstance(valeur, (int, float)) and not isinstance(valeur, bool):
            assert abs(valeur) < 1.0, (
                f"coordonnée {cle} = {valeur} dans la sortie : hors de la zone fictive "
                "(le harnais part de (0, 0) et fabrique ses anneaux autour)"
            )
    assert json.dumps(doc, ensure_ascii=False)


def test_aucune_cle_ni_mot_de_passe_dans_la_sortie(tmp_path: Path, monkeypatch, capsys):
    """La clé Intervals bouchonnée ne doit apparaître nulle part dans le document."""
    import json

    from test_seance_intervals import CLE

    doc = _doc(tmp_path, monkeypatch, capsys, candidates=3)
    texte = json.dumps(doc, ensure_ascii=False)
    assert CLE not in texte, "la clé d'API se retrouve dans la sortie JSON"


# =============================================================================
# 7. Contrôles des outils de ce fichier — ils ne doivent pas être creux
# =============================================================================
#
# `_interdire_le_disque` et `_binder` ne servent qu'à des tests aujourd'hui en
# `skip`. Sans les deux contrôles ci-dessous, rien ne dirait qu'ils marchent le
# jour où le lot arrive — et un outil cassé ferait passer ces tests-là pour de
# mauvaises raisons. Ces deux contrôles, eux, ne sautent jamais.


@pytest.mark.parametrize(
    "fautif",
    [
        pytest.param(lambda: builtins.open("/etc/hosts"), id="ouvre-un-fichier"),
        pytest.param(lambda: Path.home(), id="lit-le-foyer"),
        pytest.param(lambda: __import__("os").environ.get("HOME"), id="lit-l-environnement"),
    ],
)
def test_l_interdiction_du_disque_mord(fautif):
    """Contrôle positif : l'interdiction attrape les trois façons de tricher."""
    with pytest.raises(AssertionError):
        _interdire_le_disque(fautif, quoi="un cobaye")


def test_l_interdiction_du_disque_laisse_passer_un_calcul_pur():
    """Contrôle négatif : elle ne doit pas crier sur du calcul honnête."""
    _interdire_le_disque(lambda: math.sqrt(2.0), quoi="un cobaye")


@pytest.mark.parametrize(
    "signature",
    [
        "vent_kmh, direction_deg, jours_a_l_avance",
        "vitesse_vent_kmh, vent_depuis_deg, horizon_jours",
        "vent_moyen_kmh, direction_vent_deg, jours_avance",
        "vent, direction, echeance_jours",
    ],
)
def test_le_binder_de_la_question_du_vent_sait_se_brancher(signature):
    """Le binder doit reconnaître les noms plausibles, pas seulement les miens.

    Si le lot appelle ses paramètres autrement que ces quatre familles, le
    binder **échoue** en imprimant la signature trouvée — c'est un point à
    reconcilier avec le mainteneur, jamais à deviner. Ce contrôle prouve au
    moins que le rapprochement par mot-clé fonctionne.
    """
    espace: dict[str, Any] = {}
    exec(  # noqa: S102 - fabrique une signature de cobaye, rien d'extérieur
        f"def cobaye({signature}):\n"
        "    return (args_recus.update(locals()) or True)",
        {"args_recus": espace},
        espace,
    )
    poser = _binder(espace["cobaye"])
    assert poser(vent_kmh=14.0, direction_deg=250.0, jours_a_l_avance=1.0) is True
    assert len(espace) >= 3, f"le binder n'a nourri que {espace}"


def test_la_commande_ne_touche_pas_au_reseau(tmp_path: Path, monkeypatch, capsys):
    """Les trois clients sont bouchonnés ; la fixture `reseau_interdit` fait le reste.

    Ce test ne prouve pas l'absence de réseau à lui seul — c'est la fixture
    *autouse* du dossier qui coupe les sockets. Il vérifie que le lot n'a pas
    ajouté un **quatrième** appel qui contournerait l'injection : la commande
    passe, donc aucune socket n'a été ouverte.
    """
    doc = _doc(tmp_path, monkeypatch, capsys, candidates=3)
    assert doc.get("candidates") is not None, "la commande a bien rendu un document"
