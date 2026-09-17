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
    DEMANDE_PARCOURS_MINIMALE,
    appeler_route,
    cherche_profond,
    client_api,
    client_brouter_ordinaire,
    client_meteo_ordinaire,
    client_seance_ordinaire,
    config_d_essai,
    corps_json,
    noms_de_parametres,
    parametre_nomme,
    route_pour,
    routes,
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

    **Corrigé le 17/09/2026.** La liste de motifs commençait par « profil », et
    `route_pour` rend la première route dont le chemin le porte : le test
    interrogeait le profil et non l'écran de FTP, où vivent les trois valeurs
    liées. « zones » d'abord, et il tombe sur le bon écran.
    """
    client = client_api(config=config_d_essai())
    schema = schema_openapi(client)
    chemin, methode, _ = route_pour(schema, "zones", "ftp", "profil", "reglage")
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


def test_le_profil_stocke_une_position_dans_la_zone_et_pas_des_watts():
    """Protège la décision 7 du contrat UX, la plus structurante de la journée.

    « On stocke la position dans la zone, pas la valeur — comme ça la FTP
    change ou les zones décalent, on suit. » Une route d'écriture qui accepte
    des watts recrée exactement la dette qu'on vient de retirer : une valeur
    figée à côté d'une table qui bouge. `puissance_endurance_pct` cesse
    d'être un réglage ; il devient une conséquence.

    **Corrigé le 17/09/2026, deux fois.** Le test lisait les paramètres de la
    *première* route dont le chemin porte « profil » — celle qui **lit** le
    profil, qui n'en déclare aucun — et concluait que la décision 7 n'était
    pas tenue. Il vise maintenant la route qui **écrit**, et il y regarde en
    profondeur : les champs modifiables y sont rangés par section, pas à plat.
    Côté API, cette route ne publiait effectivement rien — son corps est lu à
    la main — et ce qu'elle accepte est désormais engendré de la liste blanche
    de `depots.CHAMPS_MODIFIABLES`.
    """
    client = client_api(config=config_d_essai())
    schema = schema_openapi(client)
    ecritures = [
        (chemin, methode, operation)
        for chemin, methode, operation in routes(schema)
        if methode in {"POST", "PUT", "PATCH"} and "profil" in chemin.lower()
        and not chemin.lower().endswith(("apercu", "preview"))
    ]
    assert ecritures, "aucune route n'écrit le profil : rien ne peut y stocker une position"
    chemin, methode, operation = ecritures[0]
    champs = _champs_declares(schema, operation)
    assert champs, (
        f"{methode} {chemin} ne déclare pas ce qu'elle accepte. Un front ne peut pas savoir "
        "qu'on enregistre une position plutôt que des watts s'il doit lire le code pour "
        "l'apprendre."
    )
    assert parametre_nomme(champs, "position", "pct", "part", "fraction"), (
        f"aucun champ de position dans la zone ; déclarés : {sorted(champs)}. "
        "Stocker des watts ferait diverger le réglage et la table de zones."
    )
    # La FTP, elle, **est** un réglage en watts, et le reste : c'est la
    # référence qui fait bouger toute la table. Ce que la décision 7 interdit
    # de stocker, c'est la puissance d'endurance — la valeur *dérivée* de la
    # position, qui figerait le réglage à côté d'une table qui bouge.
    derivees = [nom for nom in champs if "endurance" in nom.lower()]
    assert not derivees, (
        f"la route d'écriture du profil accepte la valeur dérivée : {derivees}. Décision 7 — "
        "on stocke la position dans la zone, la puissance en est une conséquence."
    )


def _champs_declares(schema: dict, operation: dict) -> set[str]:
    """Tous les noms de champs du corps déclaré, sections traversées.

    `noms_de_parametres` s'arrête au premier niveau, et c'est le bon défaut
    pour une demande à plat. Un profil, lui, est rangé par section
    (`seance.position_zone`) : sans descendre, on ne voit que les sections.
    """
    noms: set[str] = set()

    def descendre(noeud, profondeur: int = 0) -> None:
        if profondeur > 5 or not isinstance(noeud, dict):
            return
        for nom, sous in (noeud.get("properties") or {}).items():
            noms.add(str(nom))
            descendre(sous, profondeur + 1)
        descendre(noeud.get("items") or {}, profondeur + 1)

    for type_media in ((operation.get("requestBody") or {}).get("content") or {}).values():
        descendre(type_media.get("schema") or {})
    del schema
    return noms


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


def test_un_geocodage_sans_resultat_est_un_succes_vide_et_pas_une_panne():
    """Protège E10, cas « adresse introuvable ».

    Zéro candidat est un résultat légitime : l'adresse est mal tapée. Rendre
    404 ferait dessiner un écran d'erreur générique là où il faut un « aucune
    adresse ne correspond, vérifiez l'orthographe » sous le champ.

    **Corrigé le 17/09/2026.** Le test donnait le **même** corps aux deux
    services (`client_geocodage=`), c'est-à-dire un GeoJSON vide à Nominatim,
    qui rend une liste JSON. La BAN ne trouvait rien, le recours Nominatim
    recevait une forme qu'il ne sait pas lire, et le 502 constaté venait de là
    — pas d'une API qui prendrait zéro résultat pour une panne. Chaque service
    reçoit maintenant sa propre forme de « rien trouvé ».
    """
    client = client_api(
        config=config_d_essai(),
        client_ban=httpx.Client(transport=transport_constant(200, {"features": []})),
        client_nominatim=httpx.Client(transport=transport_constant(200, [])),
    )
    schema = schema_openapi(client)
    chemin, methode, operation = route_pour(schema, "geocod", "adresse")
    cle = parametre_nomme(noms_de_parametres(schema, operation), "adresse", "requete", "q")
    reponse = client.requete(methode, chemin, params={cle or "adresse": "zzzz introuvable"})
    assert reponse.status_code == 200, (
        f"statut {reponse.status_code} pour zéro résultat : une recherche vide n'est pas une panne"
    )


# --- E15 · l'horizon du vent s'arrête à trois jours ---------------------------


def _client_de_parcours():
    """Une API dont les trois services d'amont répondent normalement."""
    return client_api(
        config=config_d_essai(),
        client_brouter=client_brouter_ordinaire(),
        client_meteo=client_meteo_ordinaire(),
        client_intervals=client_seance_ordinaire(),
    )


def _demander_un_parcours(client, **champs):
    """Demande un parcours **en remplissant la demande**, et rend la réponse.

    Corrigé le 17/09/2026 : ces tests posaient leurs valeurs en `params=` sur
    une route qui déclare un corps. La réponse était un 422 « body : champ
    requis » — dont aucun des champs cherchés ensuite ne pouvait sortir.
    """
    schema = schema_openapi(client)
    chemin, methode, operation = route_pour(schema, "sortie", "parcours", "meteo")
    return appeler_route(
        client, schema, chemin, methode, operation, DEMANDE_PARCOURS_MINIMALE | champs
    )


@pytest.mark.parametrize("jours", [0, 1, HORIZON_ORIENTATION_J], ids=["aujourdhui", "demain", "j3"])
def test_l_orientation_au_vent_est_servie_jusqu_a_trois_jours(jours: int):
    """Protège E15 (« Ma semaine ») et E16 (« Orientation au vent »).

    La mesure du 16/09/2026 : la direction tombe dans le bon secteur 93 %,
    92 % et 88 % du temps à un, deux et trois jours. `HORIZON_ORIENTATION_J =
    3` reste — et c'est la mesure qui l'emporte sur l'intuition, y compris
    celle du mainteneur (règle absolue 5).
    """
    client = _client_de_parcours()
    schema = schema_openapi(client)
    _, _, operation = route_pour(schema, "sortie", "parcours", "meteo")
    jour = parametre_nomme(noms_de_parametres(schema, operation), "jour", "date")
    quand = (date.today() + timedelta(days=jours)).isoformat()
    corps = corps_json(_demander_un_parcours(client, **{jour or "jour": quand}))
    question = corps["donnees"]["question_vent"]
    assert question["horizon_jours"] == HORIZON_ORIENTATION_J, (
        f"l'API annonce un horizon de {question['horizon_jours']} jours ; la mesure du "
        f"16/09/2026 en donne {HORIZON_ORIENTATION_J}."
    )
    assert question["vent_depuis_deg"] is not None, (
        f"aucune direction de vent à J+{jours}, alors que l'horizon en couvre "
        f"{HORIZON_ORIENTATION_J} : {question['motif']!r}"
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
    client = _client_de_parcours()
    schema = schema_openapi(client)
    _, _, operation = route_pour(schema, "sortie", "parcours", "meteo")
    jour = parametre_nomme(noms_de_parametres(schema, operation), "jour", "date")
    quand = (date.today() + timedelta(days=HORIZON_ORIENTATION_J + 1)).isoformat()
    corps = corps_json(_demander_un_parcours(client, **{jour or "jour": quand}))
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


# **Marque retirée le 17/09/2026, et son motif était faux.** Il disait « aucune
# géométrie lat/lon dans le JSON » : il y en a, sous `candidates[].trace.points`,
# 129 points rendus sur 401 d'origine. Le trou décrit par `discovery_donnees.md`
# §5 a été comblé avant F1 ; ce que le test constatait était un 422 « body :
# champ requis », parce qu'il appelait la route de parcours sans corps.
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
    client = _client_de_parcours()


    corps = corps_json(_demander_un_parcours(client))
    geometries = cherche_profond(corps, "geometrie", "trace", "points", "coordonnees", "polyligne")
    assert geometries, (
        "aucune géométrie de tracé dans la réponse. Écrans bloqués : E14 (carte), "
        "E19 (trois tracés superposés), E20 (blocs dessinés sur le tracé)."
    )
    # Une clé qui s'appelle « points » et qui porte un compte n'est pas une
    # géométrie : il faut des couples de coordonnées, sinon le test se
    # contenterait de `points_rendus: 129`.
    suites = [
        valeur
        for _, valeur in geometries
        if isinstance(valeur, list)
        and valeur
        and isinstance(valeur[0], (list, tuple))
        and len(valeur[0]) >= 2
        and all(isinstance(n, (int, float)) for n in valeur[0][:2])
    ]
    assert suites, (
        f"des champs portent le mot mais aucun ne porte des couples lat/lon : "
        f"{sorted({cle for cle, _ in geometries})}"
    )


def test_le_compte_de_feux_est_un_nombre_absolu_et_pas_une_densite():
    """Protège E14 et E19, où « 10 feux » est l'un des quatre chiffres retenus.

    Les maquettes portent la note en toutes lettres : « Le compte de feux
    existe en texte ; le JSON n'expose qu'une densité de marqueurs. » Et la
    raison du choix : « Les feux se comptent en nombre absolu, jamais "1,7 au
    kilomètre" : sur 100 km, personne ne croise 170 feux. » Laisser le front
    multiplier la densité par la distance lui ferait refaire un calcul du
    cœur, avec l'arrondi en prime.

    **`xfail` levé le 17/09/2026.** Ce test décrivait un trou, et il disait
    déjà comment le combler : « le **cœur** compte et publie — pas l'API qui
    multiplie une densité par une distance ». C'est ce qui a été fait :
    `contraste.Profil` portait `feux` et `stops` depuis le sprint 3 sans
    jamais les sérialiser, `sortie/commande.rendre_json` les rend maintenant.
    Le front, lui, a cessé de multiplier (relecture F2 · C1).
    """
    client = _client_de_parcours()


    corps = corps_json(_demander_un_parcours(client))
    feux = cherche_profond(corps, "feux", "marqueurs")
    assert feux, "aucun compte de feux : c'est l'un des quatre chiffres de E14"
    absolus = [valeur for cle, valeur in feux if "densite" not in cle.lower()]
    assert any(isinstance(valeur, int) for valeur in absolus), (
        f"seulement des densités : {feux!r}. E14 affiche « 10 feux », pas « 1,7 au kilomètre »."
    )


@pytest.mark.xfail(
    strict=True,
    reason="Vérifié le 17/09/2026 sur une génération complète : une proposition porte son "
    "numéro, sa distinction et ses chiffres, jamais de GPX — `rendre_json` n'écrit que celui "
    "de la candidate retenue (`discovery_donnees.md` §3). L'API pourrait réserver un fichier "
    "par proposition, mais c'est le **cœur** qui écrit les GPX, et écrire trois traces au lieu "
    "d'une à chaque génération se décide en connaissance du coût. Q36 de "
    "docs/questions_mainteneur.md. La géométrie, elle, est bien là "
    "(`candidates[].trace.points`) : un front peut déjà tracer les trois, il ne peut pas "
    "encore en télécharger deux.",
)
def test_chaque_proposition_porte_son_propre_gpx():
    """Protège E19 et E20 (« Télécharger le GPX », « Envoyer vers mon compteur »).

    Les trois propositions sont contrastées exprès : celle qu'on emporte n'est
    pas forcément la première. Si seul le GPX de la retenue est exposé,
    choisir « la plus sèche » puis l'envoyer au compteur envoie la mauvaise
    trace — et l'erreur ne se voit qu'une fois dehors.
    """
    client = _client_de_parcours()


    corps = corps_json(_demander_un_parcours(client))
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
    reason="Le piège de `seance --json` traverse l'API : la réponse d'un jour sans séance perd "
    "les champs de la forme nominale au lieu de les rendre nuls, et un front doit donc tester "
    "la présence de `seance` avant de lire quoi que ce soit. Combler ce trou veut dire poser "
    "une forme de réponse **de référence** pour la séance — donc décider ce qui vaut `null` et "
    "ce qui disparaît — et cette forme est aussi celle que la ligne de commande rend : la "
    "changer n'est pas un correctif d'API. Q36 de docs/questions_mainteneur.md.",
)
def test_l_absence_de_seance_garde_la_meme_forme_de_reponse():
    """Protège E14 et E15, et la relecture adverse qui a relevé le cas.

    `discovery_donnees.md` §2 le dit sans détour : sans séance ce jour-là,
    `seance --json` rend `{"jour": ..., "seance": null}` — « forme
    **différente** de la forme nominale, un front doit tester la présence de
    `seance` avant de lire `etapes` ». Un contrat à deux formes est un contrat
    que le front oubliera de tester une fois sur deux ; c'est précisément
    l'écran vide que E15 · échec passe son temps à corriger.

    **Corrigé le 17/09/2026.** Le test visait la route de la *semaine*, qui ne
    déclare pas de `jour` : le paramètre était ignoré, les deux appels étaient
    le même, et la comparaison portait en plus sur l'enveloppe — identique par
    construction. Il vise maintenant la route d'un jour, compare les
    **données**, et sépare un jour avec séance d'un jour sans.
    """
    module = __import__("test_sortie_commande")
    client = client_api(
        config=config_d_essai(), client_intervals=client_seance_ordinaire(ce_jour_la=True)
    )
    schema = schema_openapi(client)
    chemin, methode, _ = route_pour(schema, "seances/{")
    avec = corps_json(client.requete(methode, chemin.replace("{jour}", module.JOUR.isoformat())))
    sans = corps_json(client.requete(methode, chemin.replace("{jour}", "2026-01-01")))
    assert cherche_profond(avec, "bloc", "etape"), (
        "le jour de la séance bouchonnée n'en décrit aucune : le test ne compare plus deux cas "
        "différents. Le relire plutôt que le supprimer."
    )
    manquantes = set(avec["donnees"]) - set(sans["donnees"])
    assert not manquantes, (
        f"la réponse sans séance perd {sorted(manquantes)}. Une seule forme, des champs nuls."
    )
