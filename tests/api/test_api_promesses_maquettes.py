"""Ce que les vingt écrans promettent et qu'une API pressée oublierait.

Ce fichier ne cherche pas les pannes : il cherche les **silences**. Chaque
test part d'un chiffre ou d'une phrase effectivement dessinée sur un écran et
demande d'où il vient. Trois d'entre eux sont des promesses que rien dans le
JSON actuel ne tient (`discovery_donnees.md` §5) — ils sont donc en `xfail`
avec le trou nommé, ce qui en fait une liste de travail pour F1 plutôt qu'un
reproche.
"""

from __future__ import annotations

from datetime import date, timedelta

import httpx
import pytest
from outils_api import (
    cherche_profond,
    client_api,
    config_d_essai,
    corps_json,
    noms_de_parametres,
    parametre_nomme,
    route_pour,
    schema_openapi,
    texte_entier,
    transport_constant,
)

#: **Sans l'extra `api`, ce module se saute au lieu de casser la collecte.**
#: `uv sync && uv run pytest` sur un dépôt fraîchement cloné n'installe pas
#: FastAPI (extra `api`) : sans cette ligne, la construction de l'application
#: levait une erreur au lieu de laisser des tests ignorés.
#: (La garde est posée par module et non dans `conftest.py` : un `Skipped`
#: levé dans un conftest fait planter pytest au lieu d'ignorer le dossier.)
pytest.importorskip("fastapi", reason="extra « api » absent — uv sync --all-extras")

#: Décision 2 du contrat UX : « L'horizon du vent reste à trois jours. » Mesuré
#: sur 2 064 heures : 93 %, 92 %, 88 % à un, deux et trois jours.
HORIZON_ORIENTATION_J = 3


# --- E9 · la troisième valeur, et ce qu'elle vaut ----------------------------


# Marque « F1 non livré » retirée le 17/09/2026 : la fabrique accepte désormais
# une Config et des clients injectés, et ce test passe. `strict` l'a signalé.
def test_l_ecran_de_ftp_recoit_bien_ses_trois_valeurs_liees():
    """Protège E9 (« Quelle est votre FTP ? ») et la décision 7 du contrat UX.

    Le contrat décrit trois valeurs, pas deux : la puissance visée (éditable),
    la vitesse à plat sans vent lancé (éditable), et **la moyenne compteur
    attendue, non éditable — la réconciliation**. La décision 8 explique
    pourquoi la troisième est obligatoire : sans elle, quelqu'un tape dans le
    champ « à plat » la moyenne lue sur son compteur, et tout l'escalier des
    zones se décale vers le bas — mesuré chez le mainteneur à −27 % de sa
    bande de Z2, qui se propage ensuite à la Z3 et à la Z4.
    """
    client = client_api(config=config_d_essai())
    schema = schema_openapi(client)
    chemin, methode, _ = route_pour(schema, "config", "profil", "reglage", "ftp")
    corps = corps_json(client.requete(methode, chemin))
    puissance = cherche_profond(corps, "puissance", "ftp", "watt")
    plat = cherche_profond(corps, "plat", "vitesse")
    compteur = cherche_profond(corps, "compteur", "moyenne")
    assert puissance, "E9 : pas de puissance visée"
    assert plat, "E9 : pas de vitesse à plat, sans vent, lancé"
    assert compteur, (
        "E9 : pas de moyenne compteur attendue. C'est la valeur qui empêche la saisie "
        "de fausser tout l'escalier des zones (décision 8)."
    )


@pytest.mark.xfail(
    strict=True,
    reason="F1 non livré. Exigence la plus facile à oublier : dire si le facteur compteur est "
    "mesuré sur l'historique ou seulement supposé.",
)

def test_la_moyenne_compteur_dit_si_son_facteur_est_mesure_ou_suppose():
    """Protège E9, et la question ouverte n° 1 (« l'invité sans historique »).

    Le contrat UX mesure le facteur sur l'historique du mainteneur : 87 % pour
    le RCR sur 69 sorties, 90 % pour le BMC sur 22, « le facteur dépend du
    vélo ». `config.example.toml` le dit dans les mêmes termes : sans
    `facteur_compteur`, la valeur « est dérivée du modèle et de la masse — une
    supposition, pas une mesure », et `ourouler config` « dit laquelle des deux
    situations est la vôtre ».

    Les maquettes posent la même question autrement : « les chiffres qu'on
    affiche à Amiel sont des mesures, ceux qu'on afficherait à l'invité
    seraient des suppositions. Les afficher pareil serait un mensonge par mise
    en page. » L'API ne tranche pas ce que le front en fait — elle doit
    seulement lui donner de quoi le distinguer. Sans ce champ, F2 *ne peut
    pas* trancher, et affichera les deux pareil par défaut.

    La `Config` d'essai n'a **pas** de `facteur_compteur` : le cas attendu ici
    est donc « supposé ».
    """
    client = client_api(config=config_d_essai())
    schema = schema_openapi(client)
    chemin, methode, _ = route_pour(schema, "config", "profil", "reglage", "ftp")
    corps = corps_json(client.requete(methode, chemin))
    marques = cherche_profond(corps, "provenance", "mesure", "suppose", "calibre", "origine")
    assert marques, (
        "rien ne dit si le facteur compteur est mesuré ou supposé. "
        "`seance --json` porte déjà `vitesses.provenance` : c'est le même besoin."
    )
    valeurs = texte_entier([valeur for _, valeur in marques]).lower()
    assert any(mot in valeurs for mot in ("suppos", "defaut", "derive", "estim", "mesur")), (
        f"le champ existe mais sa valeur ne distingue rien : {marques!r}"
    )


@pytest.mark.xfail(
    strict=True,
    reason="F1 non livré. Décision 7 : on stocke la position dans la zone, jamais la valeur.",
)
def test_le_profil_stocke_une_position_dans_la_zone_et_pas_des_watts():
    """Protège la décision 7 du contrat UX, la plus structurante de la journée.

    « On stocke la position dans la zone, pas la valeur — comme ça la FTP
    change ou les zones décalent, on suit. » Une route d'écriture qui accepte
    des watts recrée exactement la dette qu'on vient de retirer : une valeur
    figée à côté d'une table qui bouge. `puissance_endurance_pct` cesse
    d'être un réglage ; il devient une conséquence.
    """
    client = client_api(config=config_d_essai())
    schema = schema_openapi(client)
    chemin, methode, operation = route_pour(schema, "config", "profil", "reglage", "ftp")
    noms = noms_de_parametres(schema, operation)
    position = parametre_nomme(noms, "position", "pct", "part", "fraction")
    assert position, (
        f"aucun champ de position dans la zone ; déclarés : {sorted(noms)}. "
        "Stocker des watts ferait diverger le réglage et la table de zones."
    )


# --- E10 · le géocodage ne choisit pas -----------------------------------------


# Marque « F1 non livré » retirée le 17/09/2026 : la fabrique accepte désormais
# une Config et des clients injectés, et ce test passe. `strict` l'a signalé.
def test_le_geocodage_rend_tous_les_candidats_et_n_en_choisit_aucun():
    """Protège E10 (« D'où partez-vous ? »).

    « La carte confirme qu'on a compris l'adresse — un géocodage qui se trompe
    de commune est indétectable dans un champ texte. » Une API qui rend le
    premier résultat rend cette vérification impossible : l'utilisateur voit un
    point, il le croit, et il découvre l'erreur en roulant. Le tri est permis,
    le choix ne l'est pas.

    Le service est bouchonné avec trois homonymes inventés, tous au large.
    """
    trois_homonymes = {
        "features": [
            {
                "properties": {"label": f"Rue d'Essai, Commune {suffixe}", "score": note},
                "geometry": {"type": "Point", "coordinates": [0.0004, 0.0009]},
            }
            for suffixe, note in (("A", 0.9), ("B", 0.8), ("C", 0.7))
        ]
    }
    client = client_api(
        config=config_d_essai(),
        client_geocodage=httpx.Client(transport=transport_constant(200, trois_homonymes)),
    )
    schema = schema_openapi(client)
    chemin, methode, operation = route_pour(schema, "geocod", "adresse")
    cle = parametre_nomme(noms_de_parametres(schema, operation), "adresse", "requete", "q")
    corps = corps_json(client.requete(methode, chemin, params={cle or "adresse": "rue d'essai"}))
    listes = [valeur for _, valeur in cherche_profond(corps, "candidat", "resultat", "adresse")]
    listes += [corps] if isinstance(corps, list) else []
    trouvee = next((v for v in listes if isinstance(v, list)), None)
    assert trouvee is not None, f"le géocodage ne rend pas une liste : {corps!r}"
    assert len(trouvee) == 3, (
        f"{len(trouvee)} candidat(s) rendu(s) sur 3 : l'API a choisi à la place de l'utilisateur"
    )
    retenus = cherche_profond(corps, "retenu", "choisi", "defaut", "principal")
    assert not any(valeur is True for _, valeur in retenus), (
        f"un candidat est marqué comme retenu : {retenus!r}. E10 laisse l'utilisateur confirmer."
    )


@pytest.mark.xfail(
    strict=True, reason="F1 non livré. Zéro résultat est une réponse, pas une erreur."
)
def test_un_geocodage_sans_resultat_est_un_succes_vide_et_pas_une_panne():
    """Protège E10, cas « adresse introuvable ».

    Zéro candidat est un résultat légitime : l'adresse est mal tapée. Rendre
    404 ferait dessiner un écran d'erreur générique là où il faut un « aucune
    adresse ne correspond, vérifiez l'orthographe » sous le champ.
    """
    client = client_api(
        config=config_d_essai(),
        client_geocodage=httpx.Client(transport=transport_constant(200, {"features": []})),
    )
    schema = schema_openapi(client)
    chemin, methode, operation = route_pour(schema, "geocod", "adresse")
    cle = parametre_nomme(noms_de_parametres(schema, operation), "adresse", "requete", "q")
    reponse = client.requete(methode, chemin, params={cle or "adresse": "zzzz introuvable"})
    assert reponse.status_code == 200, (
        f"statut {reponse.status_code} pour zéro résultat : une recherche vide n'est pas une panne"
    )


# --- E15 · l'horizon du vent s'arrête à trois jours ---------------------------


@pytest.mark.xfail(
    strict=True,
    reason="F1 non livré. Décision 2 : trois jours inclus, quatre non, et l'API doit le dire.",
)
@pytest.mark.parametrize("jours", [0, 1, HORIZON_ORIENTATION_J], ids=["aujourdhui", "demain", "j3"])
def test_l_orientation_au_vent_est_servie_jusqu_a_trois_jours(jours: int):
    """Protège E15 (« Ma semaine ») et E16 (« Orientation au vent »).

    La mesure du 16/09/2026 : la direction tombe dans le bon secteur 93 %,
    92 % et 88 % du temps à un, deux et trois jours. `HORIZON_ORIENTATION_J =
    3` reste — et c'est la mesure qui l'emporte sur l'intuition, y compris
    celle du mainteneur (règle absolue 5).
    """
    client = client_api(config=config_d_essai())
    schema = schema_openapi(client)
    chemin, methode, operation = route_pour(schema, "sortie", "parcours", "meteo")
    jour = parametre_nomme(noms_de_parametres(schema, operation), "jour", "date")
    quand = (date.today() + timedelta(days=jours)).isoformat()
    corps = corps_json(client.requete(methode, chemin, params={jour or "jour": quand}))
    vent = cherche_profond(corps, "vent", "orientation")
    assert vent, f"aucune donnée de vent à J+{jours}, alors que l'horizon en couvre 3"


@pytest.mark.xfail(
    strict=True,
    reason="F1 non livré. Au-delà de trois jours, l'API doit dire qu'elle ne sait pas, "
    "pas omettre le champ en silence.",
)
def test_au_dela_de_trois_jours_l_api_dit_qu_elle_ne_sait_pas():
    """Protège E15, ligne « Dim. 20 — Endurance », à quatre jours.

    L'écran affiche : « Sans le vent : à quatre jours, on ne sait pas encore
    d'où il soufflera. » Les maquettes soulignent le geste : « L'orientation au
    vent disparaît, et l'écran dit **pourquoi** plutôt que de l'omettre en
    silence. » Un champ simplement absent est indistinguable d'un champ oublié
    par l'API — et le front, dans le doute, n'affiche rien du tout.

    Le motif réel est double, et il doit l'être dans la réponse : la mesure
    (88 % à trois jours, et ça continue de baisser) et la portée du modèle
    régional, qui s'arrête de toute façon à 67 heures.
    """
    client = client_api(config=config_d_essai())
    schema = schema_openapi(client)
    chemin, methode, operation = route_pour(schema, "sortie", "parcours", "meteo")
    jour = parametre_nomme(noms_de_parametres(schema, operation), "jour", "date")
    quand = (date.today() + timedelta(days=HORIZON_ORIENTATION_J + 1)).isoformat()
    corps = corps_json(client.requete(methode, chemin, params={jour or "jour": quand}))
    entier = texte_entier(corps).lower()
    assert "horizon" in entier or "ne sait pas" in entier or "hors_horizon" in entier, (
        "à J+4, rien n'explique l'absence d'orientation. Les maquettes exigent le pourquoi, "
        "pas le silence."
    )
    directions = cherche_profond(corps, "vent_depuis_deg", "orientation_vent", "direction_vent")
    assert all(valeur in (None, "", []) for _, valeur in directions), (
        f"une direction de vent est servie à J+4 : {directions!r}. Règle absolue 5 — "
        "ne rien affirmer sans mesure."
    )


# --- les trous nommés de discovery_donnees.md §5 -----------------------------


@pytest.mark.xfail(
    strict=True,
    reason="Trou F0 connu : aucune géométrie lat/lon dans le JSON, ni pour `boucle` ni pour "
    "`sortie` — elle ne vit que dans le GPX et dans la page Leaflet.",
)
def test_une_proposition_porte_la_geometrie_de_son_trace():
    """Protège E14, E19 et E20 — c'est-à-dire la moitié des écrans.

    `discovery_donnees.md` §5 le classe troisième des trous les plus
    bloquants : « coordonnées, blocs positionnés et flèches de vent n'existent
    qu'à l'intérieur du HTML Leaflet, jamais en JSON consommable ». E19
    superpose trois tracés sur une carte, E20 dessine les blocs *sur* le tracé
    — « c'est la seule façon de voir qu'un bloc tombe sur une portion plate et
    sans carrefour, ce qui est la raison d'être de l'outil ». Sans géométrie
    en JSON, F2 ne peut qu'encadrer la page HTML déjà générée.
    """
    client = client_api(config=config_d_essai())
    schema = schema_openapi(client)
    chemin, methode, _ = route_pour(schema, "sortie", "parcours", "boucle")
    corps = corps_json(client.requete(methode, chemin))
    geometries = cherche_profond(corps, "geometrie", "trace", "points", "coordonnees", "polyligne")
    assert geometries, (
        "aucune géométrie de tracé dans la réponse. Écrans bloqués : E14 (carte), "
        "E19 (trois tracés superposés), E20 (blocs dessinés sur le tracé)."
    )


@pytest.mark.xfail(
    strict=True,
    reason="Trou connu : le JSON n'expose qu'une densité de marqueurs, l'écran affiche un compte "
    "absolu. Les maquettes le signalent elles-mêmes sous E14.",
)
def test_le_compte_de_feux_est_un_nombre_absolu_et_pas_une_densite():
    """Protège E14 et E19, où « 10 feux » est l'un des quatre chiffres retenus.

    Les maquettes portent la note en toutes lettres : « Le compte de feux
    existe en texte ; le JSON n'expose qu'une densité de marqueurs. » Et la
    raison du choix : « Les feux se comptent en nombre absolu, jamais "1,7 au
    kilomètre" : sur 100 km, personne ne croise 170 feux. » Laisser le front
    multiplier la densité par la distance lui ferait refaire un calcul du
    cœur, avec l'arrondi en prime.
    """
    client = client_api(config=config_d_essai())
    schema = schema_openapi(client)
    chemin, methode, _ = route_pour(schema, "sortie", "parcours", "boucle")
    corps = corps_json(client.requete(methode, chemin))
    feux = cherche_profond(corps, "feux", "marqueurs")
    assert feux, "aucun compte de feux : c'est l'un des quatre chiffres de E14"
    absolus = [valeur for cle, valeur in feux if "densite" not in cle.lower()]
    assert any(isinstance(valeur, int) for valeur in absolus), (
        f"seulement des densités : {feux!r}. E14 affiche « 10 feux », pas « 1,7 au kilomètre »."
    )


@pytest.mark.xfail(
    strict=True,
    reason="Trou connu (`discovery_donnees.md` §3) : `rendre_json` n'expose que le GPX de la "
    "candidate retenue, pas un par proposition.",
)
def test_chaque_proposition_porte_son_propre_gpx():
    """Protège E19 et E20 (« Télécharger le GPX », « Envoyer vers mon compteur »).

    Les trois propositions sont contrastées exprès : celle qu'on emporte n'est
    pas forcément la première. Si seul le GPX de la retenue est exposé,
    choisir « la plus sèche » puis l'envoyer au compteur envoie la mauvaise
    trace — et l'erreur ne se voit qu'une fois dehors.
    """
    client = client_api(config=config_d_essai())
    schema = schema_openapi(client)
    chemin, methode, _ = route_pour(schema, "sortie", "parcours")
    corps = corps_json(client.requete(methode, chemin))
    propositions = next(
        (v for _, v in cherche_profond(corps, "proposition") if isinstance(v, list)), None
    )
    assert propositions, f"aucune liste de propositions dans {corps!r}"
    sans_gpx = [
        numero
        for numero, proposition in enumerate(propositions, start=1)
        if not cherche_profond(proposition, "gpx", "telechargement")
    ]
    assert not sans_gpx, f"propositions sans GPX propre : {sans_gpx} sur {len(propositions)}"


@pytest.mark.xfail(
    strict=True,
    reason="F1 non livré. `seance --json` change de forme quand il n'y a pas de séance : l'API "
    "ne doit pas transmettre ce piège au front.",
)
def test_l_absence_de_seance_garde_la_meme_forme_de_reponse():
    """Protège E14 et E15, et la relecture adverse qui a relevé le cas.

    `discovery_donnees.md` §2 le dit sans détour : sans séance ce jour-là,
    `seance --json` rend `{"jour": ..., "seance": null}` — « forme
    **différente** de la forme nominale, un front doit tester la présence de
    `seance` avant de lire `etapes` ». Un contrat à deux formes est un contrat
    que le front oubliera de tester une fois sur deux ; c'est précisément
    l'écran vide que E15 · échec passe son temps à corriger.
    """
    client = client_api(config=config_d_essai())
    schema = schema_openapi(client)
    chemin, methode, operation = route_pour(schema, "seance", "semaine")
    jour = parametre_nomme(noms_de_parametres(schema, operation), "jour", "date")
    sans = corps_json(client.requete(methode, chemin, params={jour or "jour": "2026-01-01"}))
    avec = corps_json(client.requete(methode, chemin))
    assert isinstance(sans, dict) and isinstance(avec, dict)
    manquantes = set(avec) - set(sans)
    assert not manquantes, (
        f"la réponse sans séance perd {sorted(manquantes)}. Une seule forme, des champs nuls."
    )
