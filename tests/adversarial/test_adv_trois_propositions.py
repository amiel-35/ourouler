"""Trois propositions contrastées, mises à l'épreuve.

Écrit **en aveugle** de l'implémentation, contre ce que la commande promet.

## Par où l'on entre

La règle des propositions ne nomme aucune interface interne. Ces tests passent
donc par la surface promise — ce que `ourouler sortie --json` publie — avec le
harnais de bouchons des tests de `sortie` (`tests/outils_sortie_commande.py` :
trois clients `httpx.MockTransport`, départ fictif à (0, 0), aucune socket).
Deux points d'entrée que le JSON ne porte pas sont atteints directement, avec
leurs dépendances injectées : `boucle.marqueurs.compter` pour la densité,
`sortie.vent_demande.interroger` pour la question du vent (client bouchonné et
`aujourdhui` passé en argument, donc aucune horloge).

## Ce que ce fichier surveille, par ordre de gravité décroissante

1. **Trois propositions qui se ressemblent.** Le défaut que le contraste existe
   pour éviter. On fabrique des candidates rigoureusement identiques (le même
   anneau rendu à chaque azimut) et on exige que la commande ne prétende pas
   qu'elles sont contrastées. Le chemin « n'en proposer que deux et le dire »
   doit exister pour de vrai.
2. **Les phrases.** Vides, partagées, en langage de note, ou fausses. Une
   phrase de vent est **descriptive** et se vérifie contre l'orientation
   publiée ; les autres sont des superlatifs et se vérifient contre les axes.
3. **Les sept axes de contraste**, et ce qu'ils valent sur une séance sans
   bloc — le cas courant du mainteneur.
4. **Les deux gardes de la question du vent**, aux bords : seuil, 3 jours pile,
   météo absente, direction inconnue ou non finie.
5. **La densité de marqueurs**, y compris l'invariant qui se retourne : une
   portion sans nœud tagué n'est pas « la campagne prouvée ».

## Ce que les adaptateurs savent lire

* **les phrases vivent dans `propositions[]`**, un bloc plat, et
  `candidates[]` garde la forme imbriquée : l'adaptateur lit les deux, et
  **échoue bruyamment** quand il ne lit aucun axe (`exiger_axes_lus`) au lieu
  de comparer des valeurs neutres et de conclure « trois clones » à tort ;
* **une proposition seule n'a pas de phrase** — et c'est correct : une phrase
  dit ce qui distingue « des deux autres ». Filtrer « les entrées portant une
  phrase » jetterait le cas des clones, celui que ce fichier travaille le plus ;
* **la densité porte sur le tracé entier**, `compter(trace)`, sans fenêtre :
  sur une endurance il n'y a aucun bloc sous lequel découper un couloir ;
* **l'horizon se balaye en jours entiers** — l'entrée est une paire de dates,
  une demi-journée d'avance n'existe pas dans ce domaine ;
* **les réglages du moteur bouchonné suivent les azimuts réellement demandés**
  (`i × 360 / nb`) : codés en dur sur 0/90/180/270, ils ne s'appliqueraient
  jamais à cinq candidates.

## Les constats en `xfail(strict=True)`

Un constat retenu par le mainteneur et pas encore corrigé se marque
`xfail(strict=True)` : l'assertion est intacte, le test s'exécute vraiment, et
le jour où la correction arrive il passe — ce que `strict` transforme en échec,
pour qu'on vienne retirer le marqueur. Un constat marqué ainsi ne se périme pas
en silence.

`part_connue` n'est **pas** un axe de contraste : les routes déjà roulées sont
un instrument de mesure, jamais un critère (doctrine). Un test la garde dans ce
sens-là.

La non-régression a son fichier (`test_adv_propositions_non_regression.py`), et
les vérificateurs employés ici sont éprouvés par vingt-sept mutations dans
`test_adv_propositions_autocontrole.py` : sans lui, rien ne garantirait que les
assertions ci-dessous ne sont pas creuses.
"""

from __future__ import annotations

import builtins
import math
from pathlib import Path
from typing import Any

import fabriques_propositions as f53
import pytest

from ourouler.boucle.marqueurs import compter
from ourouler.sortie import contraste
from ourouler.sortie.vent_demande import interroger

# Le fuseau que les bouchons Open-Meteo de ce module supposent (voir
# `fuseau_de_paris` dans conftest.py) : dit ici, pas emprunté à la machine.
pytestmark = pytest.mark.usefixtures("fuseau_de_paris")


MOTIF_PHRASE = (
    "le lot L5.3 n'est pas livré : `ourouler sortie --json` ne publie aucune phrase par "
    "proposition (contrat §3.3.3)"
)

# --- accès ------------------------------------------------------------------


#: Longueur de l'anneau que le moteur bouchonné rend, quel que soit le rayon.
#:
#: Depuis Q41 (d), une boucle trop loin de la distance demandée est refusée au
#: lieu d'être servie en silence : la bande acceptée vaut la tolérance (10 %)
#: plus au plus un élargissement de même ampleur, soit ±20 %. Or certaines
#: séances fabriquées ici visent 55 km, que cet anneau de 33,9 km ne peut pas
#: approcher (−38 %) — la commande refuserait avant d'avoir rien à contraster,
#: et le sujet de ces tests (le contraste entre propositions) ne serait plus
#: atteignable. On fixe donc la distance au lieu de la subir : elle n'a jamais
#: été leur sujet.
DISTANCE_ANNEAU_KM = 34.0


def _doc(tmp_path: Path, monkeypatch, capsys, **kw) -> dict:
    kw.setdefault("distance", DISTANCE_ANNEAU_KM)
    return f53.lancer_json(tmp_path, monkeypatch, capsys, **kw)


def _choix_ou_skip(doc: dict) -> f53.VueChoix:
    choix = f53.choix_depuis_json(doc)
    if not choix.retenues:
        pytest.skip(MOTIF_PHRASE)
    return choix


#: Les trois constats retenus par le mainteneur le 16/09/2026, en attente de
#: correction. `strict=True` est le point qui compte : le test **doit** échouer.
#: Le jour où la correction arrive, il passe, `xfail(strict)` transforme ce
#: succès en échec, et la suite réclame qu'on retire le marqueur. Un constat
#: ainsi marqué ne se périme pas en silence — c'est la différence entre
#: « connu » et « oublié ».
#:
#: Ce n'est **pas** une façon d'assouplir : l'assertion est intacte, le
#: mécanisme est dans le docstring de chaque test, et rien n'est sauté.
DEFAUT_RETENU = "défaut retenu par le mainteneur le 16/09/2026, correction en cours"


# =============================================================================
# Garde d'entrée
# =============================================================================


def test_sortie_json_publie_au_plus_trois_propositions_avec_une_phrase(tmp_path: Path, monkeypatch, capsys):
    """`sortie --json` publie des propositions, trois au plus, chacune avec sa phrase.

    Garde d'entrée du fichier : sans propositions publiées, les tests qui
    lisent les phrases se sauteraient et le dossier se lirait « tout passe »
    alors qu'aucun n'aurait rien vérifié.
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

    if manque:
        pytest.fail(
            "L5.3 n'est pas (encore) livré, ou son interface a changé de nom. Manquent :\n  - "
            + "\n  - ".join(manque)
            + "\nTous les autres tests de ce fichier sont en skip et ne vérifient rien."
        )


# =============================================================================
# 1. Le cœur du lot : trois propositions qui se ressemblent
# =============================================================================


def test_des_candidates_identiques_ne_font_pas_trois_propositions(tmp_path: Path, monkeypatch, capsys):
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
    doc = _doc(tmp_path, monkeypatch, capsys, brouter=f53.moteur_brouter_clone(), candidates=5)
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
    doc = _doc(tmp_path, monkeypatch, capsys, brouter=f53.moteur_brouter_clone(), candidates=5)
    choix = _choix_ou_skip(doc)
    assert len(choix.retenues) < 3, (
        f"{len(choix.retenues)} propositions rendues sur cinq candidates au tracé **identique**. "
        "Le contrat §3.3.3 : « Si aucune phrase n'est écrivable, c'est que les trois ne sont pas "
        "contrastées — et il vaut mieux n'en proposer que deux et le dire. » Trois ici veut dire "
        "que ce chemin n'est jamais emprunté."
    )


def test_les_propositions_ne_sont_pas_le_sommet_d_un_tri_unique(tmp_path: Path, monkeypatch, capsys):
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
        pytest.skip("le lot n'a rendu qu'une proposition sur ce vivier : l'étalement ne se pose pas")
    f53.verifier_pas_de_trio_de_clones(choix)


def test_les_propositions_respectent_le_verrou_de_recouvrement(tmp_path: Path, monkeypatch, capsys):
    """La condition qui reste du §3.3.3 bis, et qui porte désormais tout.

    **Ce test gardait la règle retirée le 17/09/2026** (Q43) : il exigeait
    a) que chacune soit la meilleure des retenues sur au moins un axe, et
    b) sur un axe différent des autres. Le mainteneur a tranché l'inverse —
    *« le parcours lui-même est distinctif en soi »* —, et cette exigence
    jetait des tracés à 1,4 % de recouvrement faute de savoir les résumer.

    Reste c), le recouvrement de routes, et il est maintenant seul : si lui ne
    mord pas, plus rien ne garantit que les propositions diffèrent. Ce qui
    restait vrai des marges est vérifié ailleurs, sur les **phrases** —
    `test_aucune_phrase_ne_se_donne_un_avantage_qu_elle_n_a_pas`.

    Les chiffres sont ceux du contrat, pas les miens : le seuil de recouvrement
    se lit chez le lot, que le contrat renvoie explicitement à « la mesure du
    lot » — inventer un chiffre là où le contrat refuse d'en inventer un serait
    pire que de lire le sien.
    """
    h = f53.harnais()
    doc = _doc(
        tmp_path,
        monkeypatch,
        capsys,
        brouter=h.moteur_brouter(_rayons_contrastes(5)),
        meteo=h.moteur_meteo(pluie=h.pluie_au_nord),
        candidates=5,
    )
    choix = _choix_ou_skip(doc)
    f53.verifier_verrou_de_recouvrement(choix)


def test_aucune_phrase_ne_se_donne_un_avantage_qu_elle_n_a_pas(tmp_path: Path, monkeypatch, capsys):
    """Ce que les marges du §3.3.3 bis gardent après Q43 : le droit d'écrire.

    Elles ne décident plus qui entre dans le trio. Elles décident toujours ce
    qu'on a le droit d'affirmer : « la plus sèche » avec 0,05 mm d'avance est
    la phrase exacte que le contrat refuse — « être meilleur de 1 % n'est pas
    une différence pour un cycliste ».
    """
    h = f53.harnais()
    doc = _doc(
        tmp_path,
        monkeypatch,
        capsys,
        brouter=h.moteur_brouter(_rayons_contrastes(5)),
        meteo=h.moteur_meteo(pluie=h.pluie_au_nord),
        candidates=5,
    )
    choix = _choix_ou_skip(doc)
    # Sans phrase, ce vérificateur n'a rien à vérifier et le test serait muet.
    # Le vivier doit donc en produire au moins une — c'est ce qui rend le
    # contrôle non vide, et ça se constate au lieu de s'espérer.
    assert any((p.phrase or "").strip() for p in choix.retenues), (
        "aucune proposition ne porte de phrase sur ce vivier : le contrôle des marges "
        f"n'éprouve rien. Relire `_rayons_contrastes`. Retenues : {choix.retenues}"
    )
    f53.verifier_phrases_meritees(choix)


def test_les_pas_de_contraste_ne_sont_pas_plus_laxistes_que_la_regle():
    """Un pas plus étroit que celui de la règle laisserait passer l'indiscernable.

    Contrôle structurel, complémentaire du précédent : le test de comportement
    ne voit que les viviers qu'on lui donne, celui-ci voit la règle elle-même.
    Un pas plus **large** que la règle est une exigence renforcée et passe ;
    un pas plus **étroit** échoue.
    """
    f53.verifier_pas_de_marge_relachee()


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

    # L'identité se lit sur les champs **présents**. Ma première rédaction
    # lisait (nom, azimut_deg, distance_km) : trois clés que `propositions[]`
    # ne porte pas, donc trois tuples (None, None, None), donc « doublon ! »
    # affirmé sans avoir rien constaté. Un test qui ne sait pas identifier ses
    # objets doit refuser de conclure, jamais conclure au pire.
    cles_utiles = ("numero", "nom", "azimut_deg", "distance_km", "duree_s", "pluie_mm")
    empreintes = [tuple(c.get(k) for k in cles_utiles) for c in proposees]
    lisibles = [e for e in empreintes if any(v is not None for v in e)]
    assert len(lisibles) == len(empreintes), (
        f"{len(empreintes) - len(lisibles)} proposition(s) sans aucun champ d'identité parmi "
        f"{cles_utiles} : impossible de dire si deux propositions sont la même boucle. "
        "Interface à reconcilier — ce test ne conclut pas au doublon faute de savoir lire."
    )
    assert len(set(map(repr, empreintes))) == len(empreintes), (
        f"la même boucle est proposée plusieurs fois : {empreintes}"
    )


#: Des anneaux de rayons franchement différents : les durées s'écartent de bien
#: plus que le pas de dix minutes du lot, si bien qu'une proposition peut se
#: distinguer par la durée pendant qu'une autre se distingue par la pluie.
#:
#: **À quoi cet étalement sert depuis Q43** (17/09/2026). Avant, il servait à
#: ce que le lot puisse rendre trois propositions du tout : un vivier où seule
#: la pluie varie n'en donnait qu'une, puisqu'une seule peut être « la plus
#: sèche ». Cette exigence est retirée, et un tel vivier rend maintenant trois
#: propositions muettes. L'étalement sert donc à autre chose, et le test le
#: constate au lieu de l'espérer : il faut des **phrases** pour que le contrôle
#: des marges éprouve quelque chose.
def _rayons_contrastes(nb: int, base_deg: float = 0.0485) -> dict[float, dict]:
    """Un rayon différent par direction, **pour les azimuts réellement demandés**.

    Sans `--direction`, `commande._candidates` interroge le moteur sur
    `i × 360 / nb` : avec cinq candidates ce sont 0, 72, 144, 216 et 288°, pas
    0, 90, 180 et 270. Ma première rédaction codait ces derniers en dur ; aucun
    réglage ne correspondait, le bouchon rendait partout le rayon par défaut,
    et les cinq candidates faisaient toutes 33,885 km. Le test échouait alors
    en accusant le lot de ne pas contraster sur la durée, alors qu'aucune durée
    ne variait — le vivier n'était pas celui que le test décrivait.
    """
    # Facteurs resserrés le 17/09/2026 (Q41 d), **relus le 17/09/2026 au soir**
    # à la demande du mainteneur (« un vivier réglé pour que le test passe ne
    # teste plus que le réglage »). Verdict : le resserrement est justifié par
    # un changement produit indépendant, pas par le test. Les chiffres tiennent
    # — l'anneau de base fait 33,885 km, donc 0,84 → 28,5 km et 1,18 → 40,0 km,
    # tous deux dans la bande ±20 % — et l'étalement de durée reste franc. Ce
    # qui a changé, c'est ce que l'étalement sert à éprouver (voir ci-dessus).
    # Ils allaient de 0,65 à 1,6,
    # soit ±60 % autour de l'anneau de base : depuis que les boucles trop loin
    # de la distance demandée sont refusées au lieu d'être servies en silence,
    # ces extrêmes ne rentrent plus dans la bande acceptée (±20 % : la
    # tolérance de 10 %, plus au plus un élargissement de même ampleur). Le
    # vivier ne rendait plus qu'une candidate, et le contraste n'avait plus
    # rien à contraster. Resserrés à ±18 %, ils tiennent tous dans la bande et
    # le contraste de durée reste franc : 28,5 km contre 40 km, soit un bon
    # quart d'heure d'écart. Certains demandent un palier d'élargissement,
    # donc ce vivier éprouve aussi le marquage.
    facteurs = (1.0, 1.18, 0.84, 1.12, 0.88, 1.06)
    # Le relief prend le relais de ce que le rayon ne peut plus donner : il
    # fait varier la durée et le terrain **sans toucher à la distance**, donc
    # sans sortir de la bande acceptée. Sans lui, les propositions resserrées
    # ne se distinguaient plus que par l'orientation au vent, et le contrat
    # §3.3.3 bis a) — « sur un axe différent de celles des deux autres » —
    # n'avait plus assez d'axes à distribuer.
    reliefs = (1.0, 55.0, 8.0, 38.0, 15.0, 26.0)
    pas = 360.0 / nb
    return {
        i * pas: {
            "rayon_deg": base_deg * facteurs[i % len(facteurs)],
            "amplitude_m": reliefs[i % len(reliefs)],
        }
        for i in range(nb)
    }


#: Rayon de l'anneau bouchonné qui rend 33,9 km, et la distance correspondante.
#:
#: Les deux vont désormais ensemble : depuis Q41 (d), demander une distance
#: que l'anneau ne sait pas approcher fait refuser la boucle au lieu de la
#: servir en silence. Un vivier doit donc être **dimensionné pour la séance
#: qu'on lui donne** — une EF de 2 h vise 55 km, pas 34.
RAYON_BASE_DEG = 0.0485
DISTANCE_BASE_KM = 33.9


def _rayons_pour(nb: int, distance_km: float) -> dict[float, dict]:
    """`_rayons_contrastes`, mis à l'échelle d'une distance visée."""
    return _rayons_contrastes(nb, base_deg=RAYON_BASE_DEG * distance_km / DISTANCE_BASE_KM)


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
    tournure est absente du lexique de `fabriques_propositions.AFFIRMATIONS`, le message
    d'échec dit laquelle des deux hypothèses vérifier — on n'étend pas le
    lexique en silence.

    **Le vent est coupé à 2 km/h, et c'est le cœur du test.** Ma première
    rédaction laissait le vent bouchonné à 14 km/h : les anneaux partant dans
    des directions différentes, l'orientation au vent variait d'une candidate
    à l'autre, et les phrases parlaient — très justement — de vent. Le test
    criait alors sur une prémisse fausse, la sienne : la pluie n'était pas la
    seule chose qui distinguait. Sous le seuil de vent sensible, l'axe du vent
    ne nomme plus rien, et la prémisse redevient vraie.
    """
    h = f53.harnais()
    doc = _doc(
        tmp_path,
        monkeypatch,
        capsys,
        brouter=h.moteur_brouter(_rayons_contrastes(4)),
        meteo=h.moteur_meteo(pluie=h.pluie_au_nord, vent_kmh=2.0),
        candidates=4,
    )
    choix = _choix_ou_skip(doc)
    assert len(choix.retenues) >= 2, (
        f"une seule proposition ({choix.motif}) sur un vivier où la pluie **et** la durée "
        "varient franchement : le contraste devrait pouvoir en distinguer deux."
    )
    pluies = [p.axe("pluie_mm") for p in choix.retenues]
    if max(pluies) - min(pluies) < 0.5:
        pytest.skip(
            f"les propositions retenues ne diffèrent pas assez en pluie ({pluies}) pour que la "
            "phrase doive en parler"
        )
    f53.verifier_phrase_parle_du_bon_axe(choix, "pluie_mm", "min")


def test_une_phrase_n_est_jamais_du_langage_de_note(tmp_path: Path, monkeypatch, capsys):
    """Une phrase parle « en langage de cycliste et jamais en langage de note ».

    Contrôle séparé de `verifier_phrases` pour que l'échec dise précisément
    ceci : une note de placement n'est pas une différence perceptible (§3.3.1),
    donc elle n'a rien à faire dans la phrase qui dit ce qui distingue.
    """
    h = f53.harnais()
    doc = _doc(tmp_path, monkeypatch, capsys, meteo=h.moteur_meteo(pluie=h.pluie_au_nord), candidates=5)
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
    7 200 s, **aucun bloc**. Mesuré chez le mainteneur : « sur 85 jours, toutes les
    séances vélo planifiées dehors sont des EF ou des sorties cool » — le cas
    endurance n'est pas secondaire, c'est **son cas courant**.

    On ne fabrique pas une séance à blocs artificielle : c'est sur cette
    forme-là que le contraste doit tenir, sans quoi il ne sert jamais.
    """
    f53.harnais()  # met `tests/` sur le chemin d'import
    from test_seance_intervals import W

    return [W.evenement(W.sortie_libre(), nom="EF 2 h fabriquée")]


def test_une_seance_sans_bloc_ne_fait_pas_tomber_la_commande(tmp_path: Path, monkeypatch, capsys):
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


def _couts(classe, km_trafic: float, km_total: float):
    """Des `Couts` construits par introspection : la structure gagne des champs.

    Les nommer un par un ferait casser ce fichier au prochain champ ajouté, pour
    une raison qui n'a rien à voir avec ce qu'il teste.
    """
    import dataclasses

    # `km_par_highway` (Q21 c) porte maintenant le détail par classe que
    # `sortie.contraste._part_trafic` lit directement (`primary` seul) —
    # un `0.0` par défaut (comme avant que ce champ existe) casserait son
    # `.get(...)` avec un `AttributeError`, pas un simple faux zéro.
    valeurs = {
        "km_trafic": km_trafic,
        "km_calme": max(km_total - km_trafic, 0.0),
        "km_par_highway": {"primary": km_trafic},
    }
    for champ in dataclasses.fields(classe):
        if champ.name in valeurs:
            continue
        if champ.name == "sens":
            valeurs[champ.name] = "horaire"
        elif champ.type in ("int", int):
            valeurs[champ.name] = 0
        elif str(champ.type).startswith(("dict", "typing.Dict")):
            valeurs[champ.name] = {}
        else:
            valeurs[champ.name] = 0.0
    return classe(**valeurs)


def _proposition_factice(
    *,
    part_connue: float = 0.5,
    km_trafic: float = 0.0,
    marqueurs: int = 0,
    duree_s: float = 7200.0,
    pluie_mm: float | None = None,
    longueur_m: float = 30_000.0,
    cap_deg: float = 90.0,
):
    """Une `Proposition` réduite à ce dont `contraste.profil` a besoin.

    Aucune donnée réelle : le tracé part du large du golfe de Guinée comme
    toutes les fabriques du dossier.
    """
    from types import SimpleNamespace

    from ourouler.boucle.couts import Couts

    trace = f53.trace_pour_densite(longueur_m, marqueurs, cap_deg=cap_deg)
    meteo = None
    if pluie_mm is not None:
        meteo = SimpleNamespace(pluie_cumulee_mm=pluie_mm, echantillons=[])
    return SimpleNamespace(
        trace=trace,
        placement=SimpleNamespace(duree_totale_s=duree_s, note_terrain=0.0),
        demi_tours=0,
        meteo=meteo,
        part_connue=part_connue,
        couts=_couts(Couts, km_trafic, trace.distance_m / 1000.0),
    )


def test_l_axe_duree_compare_l_ecart_a_la_seance_pas_la_duree_brute():
    """**Défaut constaté sur `sprint-5` au 16/09/2026**, et le plus lourd des trois.

    La règle définit le deuxième axe ainsi : « **Durée tenue** | écart
    entre `duree_totale_s` **et la séance** | Mesuré trois fois : le tri retient
    des dépassements de 29 à 43 min ». L'axe est un **écart à une consigne**.

    `contraste.Profil` porte `duree_s`, la durée brute, et `contraste.profil()`
    ne reçoit jamais la séance : l'axe compare donc des durées entre elles, et
    déclare gagnante **la plus courte**. Sur une séance élastique — l'endurance,
    cas courant du mainteneur — la plus courte est celle qui **ampute la
    séance**. Relevé dans le scénario EF de ce fichier, les cinq candidates :

        54,2 km  7151 s  retour au calme entier          (séance : 7200 s)
        42,4 km  5587 s  retour au calme raccourci -22 %
        33,9 km  4470 s  retour au calme raccourci -38 %
        27,1 km  3575 s  retour au calme raccourci -50 %
        22,0 km  2905 s  retour au calme raccourci -60 %

    La dernière gagne l'axe « durée » et se voit proposer avec la phrase
    « 71 minutes de moins », présentée comme un avantage — alors qu'elle veut
    dire « vous ne roulez pas votre séance ». Et comme la seule candidate qui
    tient la séance ne gagne plus aucun axe, la sélection s'effondre à une
    proposition (voir le test suivant).

    Ce test fabrique la même situation en deux candidates, avec la pluie pour
    que le groupe de deux soit valide, et regarde la phrase attribuée.
    """
    prescrite = 7200.0
    tient = _proposition_factice(duree_s=7151.0, pluie_mm=0.0, longueur_m=54_000.0, cap_deg=90.0)
    ampute = _proposition_factice(duree_s=2905.0, pluie_mm=5.0, longueur_m=22_000.0, cap_deg=270.0)

    selection = contraste.choisir([tient, ampute], combien=2)
    par_duree = {r.proposition.placement.duree_totale_s: r for r in selection.retenues}
    retenue_amputee = par_duree.get(2905.0)
    if retenue_amputee is None:
        # Depuis le correctif du 16/09/2026, la candidate amputée n'est plus
        # retenue **du tout** : c'est plus fort que « pas distinguée sur la
        # durée », et c'est le comportement voulu. Ce chemin était un `skip` —
        # donc le test cessait de garder quoi que ce soit dès que le défaut
        # était corrigé, ce qui est exactement la façon dont une preuve
        # disparaît avec le défaut qu'elle prouvait.
        #
        # On exige donc la contrepartie : celle qui **tient** la séance doit,
        # elle, être proposée. Sans cette ligne, « aucune candidate retenue »
        # passerait pour un succès.
        assert 7151.0 in par_duree, (
            "ni la candidate amputée ni celle qui tient la séance ne sont retenues : "
            "la sélection ne rend rien, ce qui n'est pas la correction attendue"
        )
        return
    ecart_tient = abs(7151.0 - prescrite)
    ecart_ampute = abs(2905.0 - prescrite)
    assert retenue_amputee.axe_distinctif != "duree", (
        f"la candidate qui roule {2905 / 60:.0f} min au lieu des {prescrite / 60:.0f} "
        f"prescrites (écart {ecart_ampute / 60:.0f} min) est distinguée sur l'axe « durée » "
        f"avec la phrase « {retenue_amputee.distinction} », devant celle qui tient la séance "
        f"à {ecart_tient / 60:.0f} min près. Le contrat §3.3.2 définit cet axe comme l'écart "
        "**à la séance**, pas la durée brute : `contraste.profil()` ne reçoit pas la séance "
        "et `Profil.duree_s` porte la durée nue. « 71 minutes de moins » se lit comme un "
        "avantage et veut dire « vous ne roulez pas votre séance »."
    )


def test_la_part_de_routes_connues_ne_doit_jamais_entrer_dans_la_selection():
    """La doctrine, gardée **dans le bon sens** — et l'erreur que je répare ici.

    Le test inverse — exiger que `part_connue` devienne un axe de contraste —
    serait faux, pour deux raisons :

    * la docstring de `BaseRoutes.part_connue`, que j'avais lue et **citée
      dans ma propre non-régression** — « Informatif seulement. Le contrat
      l'interdit dans tout score » ;
    * la raison de fond, montée en doctrine : les routes déjà roulées sont un
      **instrument de mesure**, jamais un critère. Le jour où elles entrent
      dans le score, l'outil cesse de mesurer quoi que ce soit — il renvoie au
      cycliste ses propres habitudes en prétendant les avoir trouvées, et
      toute validation rétrospective devient circulaire. Dans les mots du
      mainteneur : « ça permet de comparer les critères de BRouter à ma
      réalité dans ses choix, **pas du tout de privilégier mes choix** ».

    Un test adversarial n'est pas plus infaillible que le code qu'il attaque :
    celui-là se serait trompé avec la même assurance que mon adaptateur muet,
    et aurait poussé l'implémentation à violer la doctrine. D'où ce miroir, qui
    garde la règle au lieu de la casser.

    Trois contrôles, du plus structurel au plus observable.
    """

    # 1. Aucun axe déclaré ne porte les routes connues.
    axes = [str(a) for a in getattr(contraste, "ORDRE_AXES", ())]
    suspects = [a for a in axes if "connu" in f53._sans_accents_bas(a)]
    assert not suspects, (
        f"axes de contraste {suspects} : les routes déjà roulées ne sont pas un critère "
        "(contrat §3.3.2, ligne rayée le 16/09/2026 ; doctrine « ce qu'on refuse et "
        "pourquoi »)."
    )

    # 2. Le profil d'une proposition ne la porte pas non plus.
    import dataclasses

    profil_cls = getattr(contraste, "Profil", None)
    if profil_cls is not None and dataclasses.is_dataclass(profil_cls):
        champs = [f.name for f in dataclasses.fields(profil_cls)]
        assert not [c for c in champs if "connu" in f53._sans_accents_bas(c)], (
            f"`contraste.Profil` porte {champs} : la part de routes connues n'a rien à faire "
            "dans ce qui sert à sélectionner."
        )

    # 3. Et le comportement : deux boucles qui ne diffèrent **que** par la part
    #    de routes connues ne sont pas contrastées. C'est l'inverse exact de ce
    #    que mon test retiré exigeait.
    connue = _proposition_factice(part_connue=0.98, cap_deg=90.0)
    inconnue = _proposition_factice(part_connue=0.05, cap_deg=90.0)
    selection = contraste.choisir([connue, inconnue], combien=2)
    assert len(selection.retenues) == 1, (
        f"{len(selection.retenues)} propositions retenues pour deux boucles identiques en tout "
        "sauf la part de routes déjà roulées (98 % contre 5 %). Cette part ne doit pas "
        "départager : elle est un instrument de mesure, pas un critère."
    )


def test_la_part_de_routes_connues_reste_publiee():
    """…mais elle reste **affichée**, et c'est tout aussi important.

    La règle : « La part connue reste affichée, peut servir à décrire une
    proposition retenue pour une autre raison, et n'entre ni dans une note ni
    dans la sélection. » La retirer de la sortie serait l'autre façon de se
    tromper — on perdrait l'instrument de mesure qui justifie l'apprentissage
    des routes connues.
    """
    from ourouler.sortie.commande import Proposition

    assert "part_connue" in Proposition.__dataclass_fields__, (
        "`Proposition.part_connue` a disparu : la part de routes connues n'est pas un "
        "critère, mais elle reste l'instrument qui permet de comparer les choix de BRouter "
        "à la réalité du mainteneur."
    )


def test_aucune_phrase_ne_distingue_par_les_routes_connues(tmp_path: Path, monkeypatch, capsys):
    """Le contrôle observable de la même règle, sur la vraie sortie."""
    h = f53.harnais()
    doc = _doc(
        tmp_path,
        monkeypatch,
        capsys,
        brouter=h.moteur_brouter(_rayons_contrastes(5)),
        meteo=h.moteur_meteo(pluie=h.pluie_au_nord),
        candidates=5,
    )
    f53.verifier_part_connue_hors_selection(_choix_ou_skip(doc))


def test_une_seance_sans_bloc_note_bien_zero_de_terrain_partout(tmp_path: Path, monkeypatch, capsys):
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


def test_une_seance_sans_bloc_contraste_sur_autre_chose_que_le_terrain(tmp_path: Path, monkeypatch, capsys):
    """**L'effet produit des deux écarts ci-dessus**, sur le cas courant du mainteneur.

    La règle : « les axes de contraste ne peuvent pas reposer sur la
    seule note de terrain, qui vaut zéro la plupart du temps. Ils doivent
    couvrir le trafic, la part de routes connues, l'orientation au vent et la
    pluie. **Sans quoi les trois propositions seront identiques sur une EF,
    c'est-à-dire sur la majorité des sorties.** »

    Le scénario est une journée ordinaire : EF sans bloc, vent calme (2 km/h,
    sous le seuil de 8), routes de campagne sans marqueur ni grand axe, et cinq
    boucles de tailles très différentes. Cinq candidates sont bien évaluées, et
    le lot n'en propose **qu'une**.

    Le mécanisme, et il enchaîne les deux écarts déjà nommés :

    1. l'axe « durée » compare des durées brutes, donc couronne la boucle la
       plus courte — celle qui ampute le retour au calme de 60 %
       (`test_l_axe_duree_compare_l_ecart_a_la_seance_pas_la_duree_brute`) ;
    2. la seule candidate qui tient la séance entière est aussi la plus
       arrosée : elle ne gagne donc ni la durée ni la pluie, ni rien d'autre
       (terrain, ville, trafic, demi-tours sont nuls partout) ;
    3. `choisir` l'impose pourtant dans le groupe — c'est la recommandation du
       tri — et aucun groupe valide ne se forme autour d'elle ;
    L'axe « durée » explique le symptôme **à lui seul**, et il part en
    correction. J'avais d'abord mis en cause l'absence de `part_connue` : c'était
    faux deux fois — elle n'est pas un axe du contrat (elle en a été retirée le
    16/09/2026), et elle ne doit pas en être un (doctrine : instrument de
    mesure, pas critère). Voir
    `test_la_part_de_routes_connues_ne_doit_jamais_entrer_dans_la_selection`.

    Résultat : sur la sortie la plus fréquente du mainteneur, l'outil propose
    une seule boucle là où le lot entier existe pour en proposer trois.
    """
    h = f53.harnais()
    doc = _doc(
        tmp_path,
        monkeypatch,
        capsys,
        # L'EF de 2 h vise 55 km : le vivier est mis à cette échelle, sinon
        # ses anneaux de 34 km seraient refusés pour être trop loin de la
        # distance demandée (Q41 d) et il n'y aurait plus rien à contraster.
        brouter=h.moteur_brouter(_rayons_pour(5, 55.0)),
        intervals=h.client_intervals(_seance_endurance()),
        meteo=h.moteur_meteo(pluie=h.pluie_au_nord, vent_kmh=2.0),
        candidates=5,
        distance=55.0,
    )
    candidates = doc.get("candidates") or []
    assert len(candidates) >= 3, f"{len(candidates)} candidates évaluées, au moins 3 attendues"

    pluies = [(c.get("meteo") or {}).get("pluie_cumulee_mm") for c in candidates]
    durees = [(c.get("placement") or {}).get("duree_totale_s") for c in candidates]
    prescrite = float((doc.get("seance") or {}).get("duree_s") or 0.0)
    etendue_pluie = max(pluies) - min(pluies)
    etendue_duree = max(durees) - min(durees)

    # Les prémisses, vérifiées et non supposées : sans elles, le diagnostic
    # ci-dessus parlerait d'un vivier qui n'existe pas.
    assert etendue_pluie > 1.0, (
        f"la pluie devait varier franchement entre les directions, étendue mesurée "
        f"{etendue_pluie:.3f} mm : le scénario ne teste pas ce qu'il annonce"
    )
    assert etendue_duree > 600.0, (
        f"les durées devaient s'écarter de bien plus que le pas de dix minutes du lot, "
        f"étendue mesurée {etendue_duree:.0f} s : le scénario ne teste pas ce qu'il annonce"
    )

    choix = _choix_ou_skip(doc)
    ecarts = sorted(abs(d - prescrite) / 60.0 for d in durees)
    assert len(choix.retenues) >= 2, (
        f"une seule proposition sur une EF au vent calme, avec cinq candidates évaluées. "
        f"Étendues mesurées : pluie {etendue_pluie:.2f} mm, durée {etendue_duree:.0f} s — les "
        f"deux varient largement. Écarts à la séance prescrite ({prescrite / 60:.0f} min), en "
        f"minutes : {[round(e) for e in ecarts]}. La candidate qui tient la séance est la plus "
        "arrosée et ne gagne donc aucun axe ; la plus courte gagne « durée » en amputant le "
        "retour au calme. L'axe « durée » explique ce symptôme à lui seul. "
        f"Motif rendu par le lot : « {choix.motif} »"
    )
    pluies_retenues = [p.axe("pluie_mm") for p in choix.retenues]
    assert max(pluies_retenues) - min(pluies_retenues) > 0.1, (
        f"les propositions retenues portent toutes la même pluie ({pluies_retenues}) alors "
        "qu'elle varie largement. La marge (0,1 mm) est très au-dessus du bruit d'arrondi du "
        "JSON (10 puissance -3) et très en dessous de l'écart fabriqué."
    )


# =============================================================================
# 4. Les deux gardes de la question du vent
# =============================================================================


def _binder(fn: Any):
    """Adapte le point d'entrée du lot à `(vent_kmh, direction_deg, jours_a_l_avance)`.

    Réécrit à la réconciliation. Ma première version rapprochait les noms de
    paramètres par mot-clé ; c'était le mauvais angle. `vent_demande.interroger`
    ne **reçoit** ni le vent ni la direction : il les va chercher lui-même chez
    Open-Meteo, et ne reçoit que le client, le jour et `aujourdhui`. On lui
    injecte donc un client bouchonné qui rend le vent voulu — ce qui est
    exactement la forme que CLAUDE.md règle 3 impose à tout connecteur, et donc
    la forme qu'un test doit utiliser.

    Le décalage en jours se fabrique par la paire `(jour, aujourdhui)`, tous
    deux paramètres de la fonction : aucun gel d'horloge, aucune dépendance à
    la date d'exécution.
    """
    import inspect
    from datetime import UTC, date, datetime, timedelta
    from types import SimpleNamespace

    from ourouler.config import Depart

    signature = inspect.signature(fn)
    attendus = {"jour", "aujourdhui", "depart_heure", "modele"}
    manquants = sorted(attendus - set(signature.parameters))
    if manquants:
        pytest.fail(
            f"{fn.__module__}.{fn.__name__}{signature} n'expose pas {manquants} : les deux "
            "gardes du contrat §3.3.4 ne peuvent pas être pilotées sans horloge ni réseau. "
            "À reconcilier avec le mainteneur plutôt qu'à deviner."
        )

    aujourdhui = date(2026, 9, 8)

    def poser(*, vent_kmh=14.0, direction_deg=250.0, jours_a_l_avance=1.0):
        heure = SimpleNamespace(vent_kmh=vent_kmh, vent_depuis_deg=direction_deg)
        client = SimpleNamespace(previsions=lambda *a, **kw: [SimpleNamespace(heures=[heure])])
        if not math.isfinite(jours_a_l_avance):
            # Un horizon illisible ne se fabrique pas par une date : on
            # l'exprime par un jour absurdement lointain, ce qui est la seule
            # forme qu'une date puisse prendre.
            jour = date(9999, 12, 31)
        else:
            jour = aujourdhui + timedelta(days=int(jours_a_l_avance))
        question = fn(
            client,
            Depart(nom="point fictif", latitude=0.0, longitude=0.0),
            depart_heure=datetime(2026, 9, 8, 9, 0, tzinfo=UTC),
            jour=jour,
            modele="modele_de_test",
            aujourdhui=aujourdhui,
        )
        return bool(question.posee)

    return poser


def test_les_deux_gardes_de_la_question_du_vent():
    """Seuil de vent, horizon de 3 jours, météo absente, direction inconnue.

    Le contrat ne chiffre pas le seuil : il dit seulement que 2,5 km/h est
    dessous. Le vérificateur n'exige donc que cela, plus deux propriétés qui ne
    dépendent d'aucune valeur — pas de question à vent nul, et une seule
    bascule sur tout le balayage. L'horizon, lui, est chiffré : 3 jours pile est
    dedans, au-delà l'outil dit qu'il ne sait pas.
    """
    f53.verifier_gardes_vent(_binder(interroger))


def test_une_direction_de_vent_non_finie_ne_doit_pas_poser_la_question():
    """**Défaut constaté sur `sprint-5` au 16/09/2026.**

    `vent_demande.interroger` filtre la vitesse par `math.isfinite` mais la
    direction par le seul `is None`. Une direction NaN ou infinie passe donc
    les deux gardes, `posee` vaut `True`, et `QuestionVent.azimuts_pour(...)`
    rend `(nan + décalage) % 360 = nan`. Cet azimut descend ensuite dans
    `boucle.candidates.generer` — qui le passe à `azimuts()`, où `nan % 360`
    reste `nan` — puis dans le paramètre `roundTripStartDirection` de l'appel
    BRouter.

    Le reste du module traite pourtant ce cas exactement comme il faut :
    `seance.vent._utilisable` écarte un échantillon dont l'un des trois champs
    n'est pas fini, et son docstring en fait un invariant dur. C'est une
    asymétrie d'une ligne, pas un choix.
    """
    f53.verifier_direction_non_finie(_binder(interroger))


def test_la_question_du_vent_ne_lit_ni_configuration_ni_chemin_utilisateur():
    """Règle absolue 2 : seul `cli/` (et `config.py`) touche au disque.

    Contrôle **d'exécution**, complémentaire du contrôle statique de
    `test_adv_invariants.py` : une fonction qui reçoit un `Config` peut fort
    bien rouvrir un fichier au passage, ce qu'aucune analyse d'imports ne voit.
    """
    poser = _binder(interroger)
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
        monkey.setattr(
            Path,
            "home",
            lambda: (_ for _ in ()).throw(
                AssertionError(f"{quoi} lit le foyer de l'utilisateur (CLAUDE.md règle 2)")
            ),
        )
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
    f53.verifier_densite(compter, lire=_lire_densite)


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

    # `boucle.marqueurs.Marqueurs` : `par_km` rend `None` quand la densité n'a
    # pas de sens (aucun segment, aucun kilomètre). C'est un quatrième idiome
    # honnête de « je ne sais pas », et le plus net des quatre — il rend
    # impossible de lire par mégarde un zéro pour une mesure.
    brut = None
    trouve = False
    for nom in ("par_km", "densite", "valeur", "marqueurs_km"):
        if hasattr(valeur, nom):
            brut, trouve = getattr(valeur, nom), True
            break
    if not trouve:
        pytest.fail(
            f"la densité rend {valeur!r} ({type(valeur).__name__}) : impossible d'en lire un "
            "nombre au kilomètre. Interface à reconcilier avec le mainteneur."
        )
    connue = brut is not None
    for nom in ("connue", "connu", "disponible", "tags_disponibles", "mesuree"):
        if hasattr(valeur, nom):
            connue = connue and bool(getattr(valeur, nom))
            break
    else:
        motifs = getattr(valeur, "motifs", None) or []
        texte = " ".join(str(m) for m in motifs) if isinstance(motifs, (list, tuple)) else ""
        if "inconnu" in f53._sans_accents_bas(texte):
            connue = False
    return f53.Densite(0.0 if brut is None else float(brut), connue=connue)


def test_une_portion_sans_noeud_tague_n_est_pas_la_campagne_prouvee():
    """L'invariant qui se retourne, et c'est le plus facile à manquer.

    Une classe inconnue n'est jamais un malus.
    Ici la faute est symétrique et pire : une portion **sans aucun tag** rendue
    à zéro marqueur au kilomètre devient « la campagne », c'est-à-dire un
    **bonus**, et le lot proposerait par préférence les tracés qu'il ne connaît
    pas. `terrain.evaluer_couloir` fait déjà la distinction (motif « routes
    inconnues ») : la densité doit la faire aussi.
    """
    fn = compter
    sans_segments = f53.trace_pour_densite(5000.0, 0, sans_segments=True)
    tague_sans_marqueur = f53.trace_pour_densite(5000.0, 0)
    inconnue = _lire_densite(fn(sans_segments))
    mesuree = _lire_densite(fn(tague_sans_marqueur))
    assert mesuree.connue and mesuree.par_km == 0.0, (
        f"des tronçons tagués sans marqueur : zéro **mesuré** ({mesuree!r})"
    )
    assert not inconnue.connue, (
        f"un tracé sans segments rend {inconnue!r}, indiscernable du précédent. Les deux zéros "
        "ne veulent pas dire la même chose : l'un est « aucun feu », l'autre « aucun tag »."
    )


def test_la_densite_ne_lit_ni_configuration_ni_chemin_utilisateur():
    """Règle absolue 2, contrôle d'exécution."""
    fn = compter
    trace = f53.boucle_avec_marqueurs(8)
    _interdire_le_disque(lambda: fn(trace), quoi="la densité de marqueurs")


def test_la_densite_est_finie_sur_un_trace_sans_point():
    """Un tracé vide : pas de division par une longueur nulle, pas de NaN."""
    from ourouler.noyau.trace import Trace

    fn = compter
    vide = Trace(
        nom="vide",
        points=[],
        segments=[],
        distance_m=0.0,
        denivele_m=None,
        temps_moteur_s=None,
        meta={},
    )
    lue = _lire_densite(fn(vide))
    assert math.isfinite(lue.par_km), f"tracé vide : densité {lue.par_km!r}"
    assert not lue.connue, "un tracé vide ne porte aucune densité connue"


def test_la_densite_de_marqueurs_est_publiee(tmp_path: Path, monkeypatch, capsys):
    """La densité est un axe : elle doit se lire, pas seulement se calculer.

    Un axe qui n'apparaît nulle part dans `--json` ne peut ni être vérifié par
    le mainteneur, ni servir d'explication à une phrase « elle évite les
    villages ». La règle absolue 5 — ne rien affirmer sans mesure — vaut aussi
    pour ce que l'outil affirme de lui-même.
    """
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
        assert math.isfinite(valeur) and valeur >= 0, f"densité publiée non exploitable : {valeur!r}"


# =============================================================================
# 6. Invariants du produit
# =============================================================================


def test_aucun_champ_de_candidate_n_est_perpetuellement_nul(tmp_path: Path, monkeypatch, capsys):
    """Un champ toujours `null` est un piège pour qui lit la sortie.

    Demandé par le mainteneur après la réconciliation : `candidates[]` ne doit
    pas porter `distinction`, `axe_distinctif` ni `densite_marqueurs_km` s'ils
    y valent toujours `null`. Un consommateur — script, page L5.4, ou moi lisant
    le JSON — conclut « le lot ne publie pas de phrase » là où la phrase existe,
    dans `propositions[]`. Soit le champ est rempli, soit il n'est pas là.

    Le test est écrit pour être vrai des deux côtés : il passe quand la clé est
    **absente** (l'état constaté sous bouchons) et quand elle est **remplie**,
    et il échoue seulement si elle est présente et nulle pour toutes les
    candidates. C'est ce qui le rend utile pendant que L5.4 réécrit
    `sortie/commande.py`.
    """
    doc = _doc(tmp_path, monkeypatch, capsys, candidates=4)
    candidates = doc.get("candidates") or []
    assert candidates, "aucune candidate : la commande n'a rien évalué"
    surveilles = ("distinction", "axe_distinctif", "densite_marqueurs_km", "orientation_vent")
    coupables = []
    for cle in surveilles:
        presentes = [c for c in candidates if cle in c]
        if presentes and all(c.get(cle) is None for c in presentes):
            coupables.append(cle)
    assert not coupables, (
        f"`candidates[]` porte {coupables} toujours à `null` sur les {len(candidates)} "
        "candidates. Un champ perpétuellement nul se lit « le lot ne le publie pas » — c'est "
        "précisément ce qui m'a fait conclure à tort que les phrases n'existaient pas, alors "
        "qu'elles vivent dans `propositions[]`. Remplir ou retirer, pas laisser à null."
    )


def test_la_sortie_json_reste_serialisable_et_sans_coordonnee_reelle(tmp_path: Path, monkeypatch, capsys):
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


@pytest.mark.parametrize("avance", [0, 1, 3, 4, 9])
def test_le_binder_de_la_question_du_vent_injecte_bien_ce_qu_il_annonce(avance):
    """Le binder doit nourrir le vent par le client et l'avance par les deux dates.

    Contrôle positif du harnais, et il compte : si le binder injectait mal, la
    batterie des gardes testerait autre chose que ce qu'elle annonce — par
    exemple toujours le même jour, et l'horizon ne serait jamais franchi.
    """
    from types import SimpleNamespace

    recus: dict[str, Any] = {}

    def cobaye(client, depart_lieu, *, depart_heure, jour, modele, aujourdhui=None):
        heure = client.previsions([(0.0, 0.0)], modele=modele, debut=depart_heure, horizon_h=1)
        recus["vent_kmh"] = heure[0].heures[0].vent_kmh
        recus["direction_deg"] = heure[0].heures[0].vent_depuis_deg
        recus["avance"] = (jour - aujourdhui).days
        recus["depart"] = (depart_lieu.latitude, depart_lieu.longitude)
        return SimpleNamespace(posee=True)

    poser = _binder(cobaye)
    assert poser(vent_kmh=23.0, direction_deg=117.0, jours_a_l_avance=avance) is True
    assert recus["vent_kmh"] == 23.0, f"vent mal injecté : {recus}"
    assert recus["direction_deg"] == 117.0, f"direction mal injectée : {recus}"
    assert recus["avance"] == avance, (
        f"avance demandée {avance} j, reçue {recus['avance']} j — l'horizon ne serait pas "
        "franchi là où le test croit le franchir"
    )
    assert recus["depart"] == (0.0, 0.0), (
        f"départ {recus['depart']} : aucune coordonnée réelle dans un test (CLAUDE.md règle 1)"
    )


def test_le_binder_refuse_une_signature_qu_il_ne_sait_pas_piloter():
    """Contrôle négatif : une fonction sans `aujourdhui` ne se pilote pas sans horloge.

    Le binder doit alors **échouer** en disant ce qui manque, pas se rabattre
    sur `date.today()` — un test dont le résultat dépend du jour où il tourne
    est un test qui mentira un jour.
    """

    def sans_aujourdhui(client, depart_lieu, *, depart_heure, jour, modele):  # pragma: no cover
        raise AssertionError("ne doit jamais être appelée")

    with pytest.raises(BaseException, match="aujourdhui"):
        _binder(sans_aujourdhui)


def test_la_commande_ne_touche_pas_au_reseau(tmp_path: Path, monkeypatch, capsys):
    """Les trois clients sont bouchonnés ; la fixture `reseau_interdit` fait le reste.

    Ce test ne prouve pas l'absence de réseau à lui seul — c'est la fixture
    *autouse* du dossier qui coupe les sockets. Il vérifie que le lot n'a pas
    ajouté un **quatrième** appel qui contournerait l'injection : la commande
    passe, donc aucune socket n'a été ouverte.
    """
    doc = _doc(tmp_path, monkeypatch, capsys, candidates=3)
    assert doc.get("candidates") is not None, "la commande a bien rendu un document"
