"""L'écart à la distance demandée cesse d'être tu (Q41 d, 17/09/2026).

**Le défaut corrigé.** `tolerance` ne servait qu'à *arrêter* la recherche :
`generer` gardait `meilleure`, la candidate la plus proche de la cible, et
`if abs(ecart) <= tolerance: break` ne faisait que cesser d'affiner le rayon.
Quand aucun essai ne rentrait dans la tolérance, la meilleure était **servie
quand même, avec son écart, sans un mot**. Le mainteneur l'a trouvé en
utilisant le produit : « j'ai demandé 6 h et j'ai 3 boucles de 5 h ».

Mesuré le 17/09/2026 sur son serveur BRouter, tolérance réglée à 10 % :
2 km demandés, 2,69 km servis, soit **+34,7 %**, et rien ne le disait.

**Sa décision.** « On n'a pas trouvé de boucle dans les contraintes, on a
élargi de X %. Et on incrémente de 5 % en 5 %. Comme ça on explique. » Aucun
seuil à inventer : le chiffre devient un résultat à montrer.

Ces tests gardent les trois choses qui en découlent : le marquage, les
paliers, et le refus au-delà du plafond — plafond dont ils vérifient qu'il
**suit la configuration** au lieu d'être un chiffre posé là.
"""

from __future__ import annotations

import pytest
from test_boucle_candidates import DEPART, moteur

from ourouler.boucle.candidates import (
    PAS_ELARGISSEMENT,
    elargissement_max,
    generer,
    palier,
)
from ourouler.noyau.erreurs import ErreurDistanceInatteignable
from ourouler.rendu.boucle import lignes_elargissement

# --- le palier lui-même -------------------------------------------------------


@pytest.mark.parametrize(
    ("ecart", "tolerance", "attendu"),
    [
        (0.03, 0.10, 0.0),  # dans la tolérance : aucun élargissement
        (0.10, 0.10, 0.0),  # pile sur la borne : elle est inclusive
        (-0.10, 0.10, 0.0),  # le signe ne change pas le palier
        (0.11, 0.10, 0.05),  # un point de trop coûte un palier entier
        (0.15, 0.10, 0.05),  # pile deux bandes : un seul palier suffit
        (-0.17, 0.10, 0.10),  # le cas du mainteneur : 6 h demandées, 5 h servies
        (0.347, 0.10, 0.25),  # le cas mesuré sur son serveur, 2 km demandés
    ],
)
def test_le_palier_est_le_plus_petit_multiple_de_cinq_pourcent_qui_suffit(
    ecart, tolerance, attendu
):
    assert palier(ecart, tolerance) == pytest.approx(attendu)


def test_un_palier_est_toujours_un_multiple_du_pas():
    """Aucun « élargi de 7,3 % » : le mainteneur a demandé 5 % en 5 %."""
    for millieme in range(0, 1200):
        marche = palier(millieme / 1000.0, 0.10)
        reste = round(marche / PAS_ELARGISSEMENT, 6) % 1
        assert reste == pytest.approx(0.0), f"écart {millieme / 10:.1f} % : palier {marche}"


# --- le plafond, et ce qui le distingue d'un seuil inventé ---------------------


def test_le_plafond_suit_la_configuration_au_lieu_d_etre_un_chiffre():
    """La preuve qu'il n'est pas un seuil déguisé : il bouge avec le réglage.

    Un seuil arbitraire reste où on l'a posé quoi que dise la configuration.
    Celui-ci est `tolerance_distance` réemployée comme unité — la bande
    acceptée peut au plus doubler —, donc il se déplace avec elle.
    """
    assert elargissement_max(0.10) == pytest.approx(0.10)
    assert elargissement_max(0.20) == pytest.approx(0.20)
    assert elargissement_max(0.50) == pytest.approx(0.50)


def test_on_ne_refuse_personne_sans_lui_avoir_offert_au_moins_un_palier():
    """Sous 5 % de tolérance, le double resterait plus étroit que le pas.

    `config` accepte des tolérances jusqu'à 1 % : sans ce plancher, le
    mécanisme d'élargissement que le mainteneur a demandé n'aurait jamais
    lieu d'être pour ces réglages-là — un escalier sans première marche.
    """
    assert elargissement_max(0.01) == pytest.approx(PAS_ELARGISSEMENT)
    assert elargissement_max(0.0) == pytest.approx(PAS_ELARGISSEMENT)


# --- la mesure qui justifie de ne pas relancer la recherche --------------------


def test_elargir_la_tolerance_ne_rend_jamais_une_meilleure_boucle():
    """Règle absolue 5 : on ne l'affirme pas, on le mesure.

    Le mainteneur décrit l'élargissement comme une reprise (« on incrémente
    de 5 % en 5 % »). L'implémentation ne relance pourtant rien, et ce test
    dit pourquoi c'est légitime : dans `generer`, `tolerance` ne sert qu'à
    **arrêter** l'affinage du rayon. Une tolérance plus large arrête plus
    tôt, donc rend une boucle égale ou pire — jamais meilleure. Relancer
    dépenserait des appels au serveur du mainteneur pour rien.

    Le moteur choisi ne converge pas d'un coup : il faut les corrections par
    proportion pour approcher la cible, ce qui rend l'effet visible.
    """
    ecarts = {}
    appels_par_tolerance = {}
    for tolerance in (0.02, 0.10, 0.30, 0.50):
        client, appels = moteur(lambda rayon: rayon * 4.0)
        trouvees = generer(
            client, DEPART, distance_km=60, azimut_deg=45, nb=1, tolerance=tolerance
        )
        assert trouvees, f"tolérance {tolerance} : le moteur converge, il doit rendre une boucle"
        ecarts[tolerance] = abs(trouvees[0].ecart_relatif)
        appels_par_tolerance[tolerance] = len(appels)

    serrees = sorted(ecarts)
    for etroite, large in zip(serrees, serrees[1:], strict=False):
        assert ecarts[etroite] <= ecarts[large] + 1e-12, (
            f"tolérance {large:.0%} rend un écart de {ecarts[large]:.3f}, meilleur que les "
            f"{ecarts[etroite]:.3f} de {etroite:.0%} : élargir aurait donc un intérêt, "
            "et le palier ne pourrait plus se lire sur le réglage le plus serré"
        )
        assert appels_par_tolerance[large] <= appels_par_tolerance[etroite], (
            "une tolérance plus large ne peut pas coûter plus d'appels qu'une plus serrée"
        )


def test_l_elargissement_converge_et_ne_monte_pas_indefiniment():
    """« Un palier qui monterait indéfiniment finirait par servir n'importe quoi. »

    Il ne le peut pas : le palier est **lu** sur un écart déjà mesuré, jamais
    cherché par essais successifs. Quel que soit l'écart, il se calcule en
    une fois, il est fini, et il est majoré par l'écart lui-même arrondi au
    palier supérieur.
    """
    for ecart in (0.11, 0.5, 1.0, 12.0, 1e6):
        marche = palier(ecart, 0.10)
        assert marche == pytest.approx(palier(ecart, 0.10)), "le palier n'est pas déterministe"
        assert 0.0 <= marche <= abs(ecart) + PAS_ELARGISSEMENT, (
            f"écart {ecart} : palier {marche} hors de toute borne raisonnable"
        )


# --- le marquage, cœur du lot -------------------------------------------------


def test_une_boucle_servie_hors_tolerance_est_marquee_et_chiffree():
    """Le cas du mainteneur, reproduit sur un moteur bouchonné.

    66 km rendus pour 60 demandés à tolérance 5 % : hors tolérance d'un point,
    donc servie — un palier de 5 % suffit — mais elle le dit.

    Le moteur rend **une longueur fixe**, indépendante du rayon demandé : un
    moteur linéaire, lui, se corrigerait par proportion et tomberait juste. Ce
    qu'on veut ici, c'est le cas où le terrain ne sait pas faire la distance.
    """
    client, _ = moteur(66_000)
    trouvees = generer(client, DEPART, distance_km=60, azimut_deg=45, nb=1, tolerance=0.05)

    assert trouvees, "une boucle dans le plafond reste servie : elle est utile, pas fautive"
    candidate = trouvees[0]
    assert candidate.hors_tolerance is True
    assert candidate.elargissement == pytest.approx(0.05)
    assert candidate.tolerance == pytest.approx(0.05)


def test_une_boucle_dans_la_tolerance_ne_porte_aucun_elargissement():
    """La symétrie compte autant : rien ne doit se dire quand il n'y a rien à dire."""
    client, _ = moteur(lambda rayon: rayon * 5.0)
    trouvees = generer(client, DEPART, distance_km=60, azimut_deg=45, nb=3, tolerance=0.10)

    assert trouvees, "un moteur qui tombe juste doit rendre des boucles"
    for candidate in trouvees:
        assert candidate.hors_tolerance is False
        assert candidate.elargissement == pytest.approx(0.0)


# --- le refus au-delà du plafond ----------------------------------------------


def test_au_dela_du_plafond_on_refuse_et_on_dit_avec_quels_chiffres():
    """Un refus qui ne porte pas ses mesures est une impasse, pas une réponse."""
    # Longueur fixe, insensible au rayon : aucune correction ne rattrape.
    client, appels = moteur(24_000)  # 24 km pour 60 demandés, soit −60 %
    with pytest.raises(ErreurDistanceInatteignable) as capture:
        generer(client, DEPART, distance_km=60, azimut_deg=45, nb=2, tolerance=0.10)

    assert appels, "le moteur a bien été interrogé : le refus est mesuré, pas supposé"
    refus = capture.value
    assert refus.distance_cible_km == pytest.approx(60.0)
    assert refus.tolerance == pytest.approx(0.10)
    assert refus.elargissement_max == pytest.approx(0.10)
    assert refus.elargissement_requis > refus.elargissement_max, (
        "on ne refuse que lorsque l'élargissement nécessaire dépasse le plafond"
    )
    assert refus.distance_obtenue_km > 0
    # Le message parle au cycliste, en pourcentages et en kilomètres.
    assert "élargir" in str(refus)


def test_un_azimut_hors_plafond_ne_condamne_pas_les_autres():
    """Le refus n'a lieu que si **aucune** candidate ne tient.

    Un moteur qui ne sait pas travailler dans une direction ne doit pas faire
    perdre les directions où il sait — même raison que pour les pannes par
    azimut, déjà traitées ainsi.
    """
    # Le premier azimut exploré est celui demandé (45°) ; on le rend stérile.
    def longueur(rayon: float) -> float:
        return rayon * 5.0

    client, appels = moteur(longueur, echec_sur=45.0)
    trouvees = generer(client, DEPART, distance_km=60, azimut_deg=45, nb=3, tolerance=0.10)

    assert appels, "le moteur a été interrogé"
    assert trouvees, "les azimuts qui marchent doivent survivre à celui qui échoue"
    assert all(not c.hors_tolerance for c in trouvees)


def test_une_direction_refusee_ne_condamne_pas_les_autres_dans_sortie(monkeypatch):
    """Sans `--direction`, chaque azimut fait son propre appel à `generer`.

    Le refus sur la distance est donc **par direction**. Sans précaution, la
    première direction où le terrain ne sait pas faire la distance faisait
    tomber toute la recherche — y compris les directions où il savait. C'est
    un défaut que ce lot a failli introduire, et que ce test garde fermé.
    """
    from ourouler.sortie import commande as sortie_commande

    appels: list[float] = []

    def faux_generer(_client, _depart, *, azimut_deg, **_reste):
        appels.append(azimut_deg)
        if azimut_deg < 180.0:
            raise ErreurDistanceInatteignable(
                "terrain impraticable dans cette direction",
                distance_cible_km=60.0,
                distance_obtenue_km=20.0,
                ecart_relatif=-0.666,
                tolerance=0.10,
                elargissement_requis=0.60,
                elargissement_max=0.10,
            )
        return [object()]

    class _Demande:
        azimut_deg = None
        nb_candidates = 4
        profil = None
        direction = None

    class _Boucle:
        tolerance_distance = 0.10

    class _Config:
        depart = DEPART
        boucle = _Boucle()

    monkeypatch.setattr(sortie_commande, "generer", faux_generer)
    trouvees = sortie_commande._candidates(object(), _Config(), _Demande(), 60.0)
    assert len(appels) == 4, "les quatre directions doivent être tentées"
    assert len(trouvees) == 2, "les deux directions praticables doivent survivre"


def test_toutes_les_directions_refusees_relancent_le_refus_le_moins_severe(monkeypatch):
    """Quand rien ne marche nulle part, le message doit être le plus utile.

    C'est le refus qui demandait le plus petit élargissement : c'est lui qui
    dit le plus justement de combien il aurait fallu élargir.
    """
    from ourouler.sortie import commande as sortie_commande

    def faux_generer(_client, _depart, *, azimut_deg, **_reste):
        requis = 0.60 if azimut_deg < 180.0 else 0.20
        raise ErreurDistanceInatteignable(
            "terrain impraticable",
            distance_cible_km=60.0,
            distance_obtenue_km=20.0,
            ecart_relatif=-0.666,
            tolerance=0.10,
            elargissement_requis=requis,
            elargissement_max=0.10,
        )

    class _Demande:
        azimut_deg = None
        nb_candidates = 4
        profil = None
        direction = None

    class _Boucle:
        tolerance_distance = 0.10

    class _Config:
        depart = DEPART
        boucle = _Boucle()

    monkeypatch.setattr(sortie_commande, "generer", faux_generer)
    with pytest.raises(ErreurDistanceInatteignable) as capture:
        sortie_commande._candidates(object(), _Config(), _Demande(), 60.0)
    assert capture.value.elargissement_requis == pytest.approx(0.20)


# --- le même garde-fou, côté `boucle` (Q47) ------------------------------------
#
# `boucle` refusait sans `--direction` au lieu de balayer comme `sortie` — une
# contrainte héritée, pas un choix (le mainteneur l'a relevé lui-même, Q47).
# `_generer_candidates` reprend exactement l'algorithme de `sortie._candidates`
# pour le cas « pas de direction demandée », et ces deux tests sont la copie
# conforme des deux ci-dessus, sur `boucle` cette fois.


def test_une_direction_refusee_ne_condamne_pas_les_autres_dans_boucle(monkeypatch):
    """Sans `--direction`, chaque azimut fait son propre appel à `generer` (Q47).

    Même garde-fou que dans `sortie` : la première direction où le terrain ne
    sait pas faire la distance ne doit pas faire tomber les directions où il
    sait.
    """
    from ourouler.boucle import commande as boucle_commande

    appels: list[float] = []

    def faux_generer(_client, _depart, *, azimut_deg, **_reste):
        appels.append(azimut_deg)
        if azimut_deg < 180.0:
            raise ErreurDistanceInatteignable(
                "terrain impraticable dans cette direction",
                distance_cible_km=60.0,
                distance_obtenue_km=20.0,
                ecart_relatif=-0.666,
                tolerance=0.10,
                elargissement_requis=0.60,
                elargissement_max=0.10,
            )
        return [object()]

    class _Demande:
        azimut_deg = None
        nb_candidates = 4
        profil = None
        direction = None
        distance_km = 60.0

    class _Boucle:
        tolerance_distance = 0.10

    class _Config:
        depart = DEPART
        boucle = _Boucle()

    monkeypatch.setattr(boucle_commande, "generer", faux_generer)
    trouvees = boucle_commande._generer_candidates(object(), _Config(), _Demande())
    assert len(appels) == 4, "les quatre directions doivent être tentées"
    assert len(trouvees) == 2, "les deux directions praticables doivent survivre"


def test_toutes_les_directions_refusees_relancent_le_refus_le_moins_severe_dans_boucle(
    monkeypatch,
):
    """Quand rien ne marche nulle part, `boucle` continue de refuser (Q47).

    Le lot sur l'écart de distance a introduit `ErreurDistanceInatteignable` :
    ça n'a rien à voir avec l'absence de direction, et ça doit continuer à
    refuser — avec le message le plus utile, celui du plus petit élargissement
    requis.
    """
    from ourouler.boucle import commande as boucle_commande

    def faux_generer(_client, _depart, *, azimut_deg, **_reste):
        requis = 0.60 if azimut_deg < 180.0 else 0.20
        raise ErreurDistanceInatteignable(
            "terrain impraticable",
            distance_cible_km=60.0,
            distance_obtenue_km=20.0,
            ecart_relatif=-0.666,
            tolerance=0.10,
            elargissement_requis=requis,
            elargissement_max=0.10,
        )

    class _Demande:
        azimut_deg = None
        nb_candidates = 4
        profil = None
        direction = None
        distance_km = 60.0

    class _Boucle:
        tolerance_distance = 0.10

    class _Config:
        depart = DEPART
        boucle = _Boucle()

    monkeypatch.setattr(boucle_commande, "generer", faux_generer)
    with pytest.raises(ErreurDistanceInatteignable) as capture:
        boucle_commande._generer_candidates(object(), _Config(), _Demande())
    assert capture.value.elargissement_requis == pytest.approx(0.20)


def test_avec_direction_un_seul_appel_est_fait_dans_boucle(monkeypatch):
    """`--direction` reste prioritaire et n'ouvre qu'un seul appel (comportement inchangé)."""
    from ourouler.boucle import commande as boucle_commande

    appels: list[float] = []

    def faux_generer(_client, _depart, *, azimut_deg, nb, **_reste):
        appels.append(azimut_deg)
        return [object()] * nb

    class _Demande:
        azimut_deg = 45.0
        nb_candidates = 3
        profil = None
        direction = "NE"
        distance_km = 60.0

    class _Boucle:
        tolerance_distance = 0.10

    class _Config:
        depart = DEPART
        boucle = _Boucle()

    monkeypatch.setattr(boucle_commande, "generer", faux_generer)
    trouvees = boucle_commande._generer_candidates(object(), _Config(), _Demande())
    assert appels == [45.0], "une direction demandée ne doit déclencher qu'un seul appel"
    assert len(trouvees) == 3


# --- ce que l'écran en dit ----------------------------------------------------


class _Fausse:
    """Le strict nécessaire pour `lignes_elargissement` : ni Trace ni moteur."""

    def __init__(self, numero, distance_m, ecart, elargissement, tolerance):
        self.numero = numero
        self.trace = type("T", (), {"distance_m": distance_m})()
        self.ecart_relatif = ecart
        self.elargissement = elargissement
        self.tolerance_distance = tolerance


def test_le_texte_dit_de_combien_on_a_elargi_et_dans_quel_sens():
    lignes = lignes_elargissement(
        [
            _Fausse(1, 34_000.0, -0.177, 0.10, 0.10),
            _Fausse(2, 44_000.0, 0.065, 0.0, 0.10),
        ],
        distance_km=41.3,
    )
    texte = "\n".join(lignes)
    assert "±10%" in texte, "la tolérance demandée doit être rappelée"
    assert "élargie de 10%" in texte, "le palier est le chiffre que le mainteneur veut voir"
    assert "±20%" in texte, "la bande réellement atteinte se dit aussi"
    assert "-18%" in texte, "le signe compte : plus court n'est pas plus long"
    assert "n° 2" not in texte, "la candidate qui tenait dans la tolérance n'a rien à dire"


def test_l_api_traduit_le_refus_en_gardant_ses_mesures():
    """E18 · échec a besoin des nombres, pas seulement d'un code.

    Le code reste `aucune_boucle` — c'est le même écran, déjà dessiné — mais
    `details` est rempli, et le motif permet à un client de savoir quoi lire.
    La reconnaissance se fait **sur le type**, pas sur un préfixe de message :
    un message reformulé ne doit pas vider l'écran de ses chiffres.
    """
    from ourouler.api.erreurs import classer

    refus = ErreurDistanceInatteignable(
        "message qui pourrait être réécrit demain",
        distance_cible_km=150.0,
        distance_obtenue_km=96.4,
        ecart_relatif=-0.3573,
        tolerance=0.10,
        elargissement_requis=0.30,
        elargissement_max=0.10,
    )
    traduite = classer(refus, secrets=())

    assert traduite.code == "aucune_boucle", "c'est l'écran E18 · échec, pas une panne de service"
    assert traduite.statut == 422
    assert traduite.details["motif"] == "distance_inatteignable"
    assert traduite.details["distance_obtenue_km"] == pytest.approx(96.4)
    assert traduite.details["elargissement_requis"] == pytest.approx(0.30)
    assert traduite.details["elargissement_max"] == pytest.approx(0.10)


def test_le_texte_se_tait_quand_tout_tient_dans_la_tolerance():
    """Une ligne qui signale ce qui ne compte pas apprend à ne plus lire la ligne.

    C'est la même raison que `SEUIL_ECART_DUREE` côté séance, et les deux ne
    se recouvrent pas : celui-ci parle de la **distance d'une boucle**, l'autre
    de la **durée d'une séance**.
    """
    assert lignes_elargissement([_Fausse(1, 42_000.0, 0.017, 0.0, 0.10)], distance_km=41.3) == []
    assert lignes_elargissement([], distance_km=41.3) == []
