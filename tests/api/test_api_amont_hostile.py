"""Quand ce sont les services d'en face qui répondent mal.

L'API dépend de trois services extérieurs — Open-Meteo, BRouter,
intervals.icu — et les maquettes le disent en toutes lettres : « un produit
qui dépend de trois services extérieurs passe une partie de sa vie en panne ».

Les signatures testées ici ne sont pas inventées : elles viennent de ce que le
dépôt a déjà rencontré en vrai et consigné.

* Open-Meteo, docstring d'`ErreurHorsDomaine` : « un corps HTTP 200 truffé de
  littéraux `nan` » et « un bloc entièrement à `null` » — la seconde étant
  aussi ce qu'il rend au-delà de la portée du modèle, pas seulement hors de sa
  grille. **Deux causes, un seul message**, et E14 · dégradé documente le
  malentendu que ça a produit.
* BRouter, `config.example.toml` : « un profil absent se manifeste par un
  HTTP 500 sans corps ».
* intervals.icu : 401 sur clé révoquée (E15 · échec), et des champs d'un type
  inattendu dès qu'un compte n'est pas rempli comme celui du mainteneur.

Le contrat commun : l'API ne recopie jamais le mot d'un service tiers à
l'écran, et ne transforme jamais une panne d'amont en 500 nu.
"""

from __future__ import annotations

import pytest
from outils_api import (
    DEMANDE_PARCOURS_MINIMALE,
    ApiAbsente,
    appeler_route,
    cherche_profond,
    client_api,
    client_bouchon,
    client_brouter_ordinaire,
    client_meteo_ordinaire,
    client_seance_ordinaire,
    config_d_essai,
    route_pour,
    schema_openapi,
    texte_entier,
)

#: Un bloc horaire entièrement nul : ce qu'Open-Meteo rend au-delà de la portée
#: du modèle régional, et aussi hors de sa grille.
METEO_TOUT_NUL = {
    "hourly": {
        "time": ["2026-09-17T09:00", "2026-09-17T10:00"],
        "temperature_2m": [None, None],
        "precipitation": [None, None],
        "wind_speed_10m": [None, None],
        "wind_direction_10m": [None, None],
    }
}

#: Un bloc partiel : la moitié des heures manquent. Le pire cas, parce qu'il a
#: l'air exploitable.
METEO_PARTIELLE = {
    "hourly": {
        "time": ["2026-09-17T09:00", "2026-09-17T10:00"],
        "temperature_2m": [15],
        "precipitation": [],
    }
}

#: Des types inattendus là où le code attend des nombres.
METEO_MAL_TYPEE = {
    "hourly": {
        "time": "2026-09-17T09:00",
        "temperature_2m": "quinze",
        "precipitation": {"valeur": 0},
        "wind_speed_10m": [True],
    }
}


def _route_de_parcours(client):
    schema = schema_openapi(client)
    return route_pour(schema, "sortie", "parcours", "meteo")


def _demander_un_parcours(client, **champs):
    """Demande un parcours **en remplissant la demande**, et rend la réponse.

    Corrigé le 17/09/2026. Ces tests appelaient `client.requete(methode,
    chemin)` sans rien : la route de parcours déclare un corps de requête, et
    une demande vide revenait en 422 « body : champ requis » — un 4xx, donc
    des assertions vertes, mais sans qu'aucun service d'amont ait été appelé.
    Le bouchon hostile n'était jamais lu. `appeler_route` met les champs là
    où le schéma dit qu'ils vont.
    """
    schema = schema_openapi(client)
    chemin, methode, operation = route_pour(schema, "sortie", "parcours", "meteo")
    return appeler_route(
        client, schema, chemin, methode, operation, DEMANDE_PARCOURS_MINIMALE | champs
    )


# Marque « F1 non livré » retirée le 17/09/2026 : la fabrique accepte désormais
# une Config et des clients injectés, et ce test passe. `strict` l'a signalé.
@pytest.mark.parametrize(
    "statut,corps,texte,quoi",
    [
        (200, METEO_TOUT_NUL, None, "bloc horaire entièrement nul"),
        (200, METEO_PARTIELLE, None, "bloc horaire à moitié rempli"),
        (200, METEO_MAL_TYPEE, None, "champs d'un type inattendu"),
        (200, {}, None, "corps vide"),
        (200, None, "nan nan nan", "corps non JSON"),
        (429, {"reason": "Minutely API request limit exceeded"}, None, "quota minute dépassé"),
        (500, None, "", "500 sans corps"),
        (503, None, "", "service indisponible"),
    ],
    ids=["nuls", "partiel", "types", "vide", "non_json", "429", "500", "503"],
)
def test_une_reponse_meteo_hostile_ne_remonte_jamais_en_500(statut, corps, texte, quoi: str):
    """Protège E14 · dégradé (« Pas de météo ce matin »).

    « La météo est le seul maillon qu'on accepte de perdre » — donc aucune de
    ces huit réponses ne doit casser la requête. Celle qui mérite le plus
    d'attention est la troisième ligne : un bloc *partiel* a l'air exploitable,
    et c'est comme ça qu'une moyenne se calcule sur trois points au lieu de
    quatorze sans que personne ne le voie.
    """
    client = client_api(
        config=config_d_essai(),
        client_meteo=client_bouchon(statut, corps, texte=texte),
        client_brouter=client_brouter_ordinaire(),
        client_intervals=client_seance_ordinaire(),
    )
    reponse = _demander_un_parcours(client)
    assert reponse.status_code < 500, f"{quoi} : l'API rend {reponse.status_code}"


# Marque « F1 non livré » retirée le 17/09/2026. Elle était fausse deux fois :
# l'API est livrée, et le test ne lisait de toute façon pas les bouchons —
# il appelait la route de parcours sans corps. Voir `_demander_un_parcours`.
@pytest.mark.parametrize(
    "statut,corps,texte,quoi",
    [
        (429, {"reason": "Minutely API request limit exceeded"}, None, "quota Open-Meteo"),
        (500, None, "", "BRouter, profil absent (500 sans corps)"),
        (401, {"error": "unauthorized"}, None, "Intervals, clé révoquée"),
    ],
    ids=["quota", "brouter_500", "intervals_401"],
)
def test_le_message_d_un_service_tiers_n_arrive_pas_tel_quel_a_l_ecran(statut, corps, texte, quoi):
    """Protège les quatre écrans d'échec, et la convention de langue de CLAUDE.md.

    « Minutely API request limit exceeded » n'est pas une phrase qu'un cycliste
    lit un dimanche matin. Et le cas du 429 est instructif : la doctrine §10.1
    raconte qu'un agent l'a vu passer et en a tiré une conclusion fausse. Un
    message d'amont recopié transporte le malentendu jusqu'à l'utilisateur.
    """
    bouchon = client_bouchon(statut, corps, texte=texte)
    client = client_api(
        config=config_d_essai(),
        client_meteo=bouchon,
        client_brouter=bouchon,
        client_intervals=bouchon,
    )
    reponse = _demander_un_parcours(client)
    interdits = ("Minutely", "limit exceeded", "unauthorized", "Internal Server Error", "Bad Gateway")
    for mot in interdits:
        assert mot not in reponse.text, f"{quoi} : « {mot} » recopié tel quel dans la réponse"


def test_hors_de_portee_du_modele_et_hors_de_sa_grille_ne_disent_pas_la_meme_chose():
    """Protège E14 · dégradé, et le défaut nommé dans son commentaire.

    Mot pour mot : « Le cas s'est déjà produit en vrai, et il avait été mal
    traité : la commande rendait "hors de portée" quand le modèle régional ne
    couvrait pas la fenêtre, et l'utilisateur lisait "hors du domaine". Deux
    causes, un seul message. » Open-Meteo rend le **même** bloc nul dans les
    deux cas : c'est donc à l'API de les séparer, en regardant si la demande
    sort de la grille (géographie) ou de l'horizon (temps). Le second a un
    recours — le second avis, le repli de modèle — le premier n'en a aucun.

    **Ce que ce test vérifie, et ce qu'il ne vérifie pas** (17/09/2026). Il
    vérifie que la réponse **nomme** la cause au lieu de se taire :
    `question_vent.motif` dit « hors du domaine, ou hors de sa portée
    temporelle », et cite le repli de modèle tenté. Il ne vérifie pas que les
    deux causes soient *séparées* — et elles ne le sont pas : le cœur refuse
    délibérément de trancher entre elles, parce qu'Open-Meteo rend le même
    bloc nul dans les deux cas et qu'affirmer une cause qu'on n'a pas mesurée
    est ce que la règle absolue 5 interdit (`meteo/openmeteo._hors_domaine`).
    Séparer demanderait que l'API connaisse la portée publiée de chaque
    modèle ; ce chiffre est un arbitrage, posé en Q36 de
    `docs/journal/questions/questions_mainteneur.md`. Écrit ici plutôt que masqué derrière une
    marque : un test vert qui promet plus qu'il ne tient est le même mensonge
    qu'une marque au motif faux.
    """
    client = client_api(
        config=config_d_essai(),
        client_meteo=client_bouchon(200, METEO_TOUT_NUL),
        client_brouter=client_brouter_ordinaire(),
        client_intervals=client_seance_ordinaire(),
    )
    corps = _demander_un_parcours(client).json()
    causes = cherche_profond(corps, "motif", "cause", "repli", "modele_utilise")
    assert causes, "rien ne dit pourquoi la météo manque : E14 en fait un critère"
    entier = texte_entier(causes).lower()
    assert "domaine" in entier or "horizon" in entier or "portee" in entier, (
        f"le motif ne distingue pas géographie et horizon : {causes!r}"
    )


# --- le cache : corrompu, absent, en lecture seule ---------------------------


# Marque « F1 non livré » retirée le 17/09/2026 : la fabrique accepte désormais
# une Config et des clients injectés, et ce test passe. `strict` l'a signalé.
@pytest.mark.parametrize(
    "contenu,quoi",
    [
        (b"", "index SQLite vide"),
        (b"ceci n'est pas une base SQLite", "index corrompu"),
        (b"SQLite format 3\x00" + b"\x00" * 64, "en-tête SQLite sans contenu"),
    ],
    ids=["vide", "corrompu", "tronque"],
)
def test_un_cache_corrompu_ne_casse_pas_la_requete(tmp_path, contenu: bytes, quoi: str):
    """Protège E14 (« Généré à 6:00 ») et la doctrine §10.1.

    « Le cœur parle à une classe `Cache` (ajouter, contient, lister, chemin),
    jamais à un chemin ni à une requête SQL. » Un cache est par définition
    jetable : un index illisible doit se recréer ou se contourner, pas faire
    échouer la demande de parcours. En hébergé, ce même index devient un
    stockage partagé — un plantage y serait une panne de service, pas une gêne.
    """
    index = tmp_path / "index.sqlite"
    index.write_bytes(contenu)
    client = client_api(
        config=config_d_essai(cache={"dossier": str(tmp_path)}),
        client_brouter=client_brouter_ordinaire(),
        client_intervals=client_seance_ordinaire(),
        client_meteo=client_meteo_ordinaire(),
    )
    reponse = _demander_un_parcours(client)
    assert reponse.status_code < 500, f"{quoi} : l'API rend {reponse.status_code}"


# Marque « F1 non livré » retirée le 17/09/2026 : la fabrique accepte désormais
# une Config et des clients injectés, et ce test passe. `strict` l'a signalé.
def test_un_cache_absent_ne_bloque_pas_la_premiere_requete(tmp_path):
    """Protège le premier usage d'un compte neuf (E14, premier jour).

    Un invité qui vient de s'installer n'a aucun cache. Si la première requête
    suppose un index déjà là, tous les écrans de F2 tombent au premier essai —
    et c'est le seul essai qu'un nouveau venu accorde.
    """
    absent = tmp_path / "nulle-part" / "ourouler"
    client = client_api(
        config=config_d_essai(cache={"dossier": str(absent)}),
        client_brouter=client_brouter_ordinaire(),
        client_intervals=client_seance_ordinaire(),
        client_meteo=client_meteo_ordinaire(),
    )
    reponse = _demander_un_parcours(client)
    assert reponse.status_code < 500, f"cache absent : l'API rend {reponse.status_code}"


# Marque « aucun schéma publié » retirée le 17/09/2026 : le schéma existe, et
# le test cherchait un chemin de disque dans une réponse qui n'avait jamais
# été calculée (route de parcours appelée sans corps). Avec une vraie
# génération, il a trouvé ce qu'il cherchait — dans le *message d'erreur* d'un
# dépôt de séance, pas dans `gpx` — et c'est `erreurs.assainir` qui le corrige.
def test_aucune_reponse_n_expose_un_chemin_du_disque_du_serveur():
    """Protège la doctrine §10.2 et E20 (« Télécharger le GPX »).

    `sortie --json` met aujourd'hui un **chemin de fichier** dans les champs
    `gpx` et `carte` (`discovery_donnees.md` §2). Un chemin de disque servi à
    un navigateur est inutilisable, et en hébergé il décrit l'arborescence du
    serveur à quiconque regarde. Ce que le front attend est une URL à appeler.
    """
    client = client_api(
        config=config_d_essai(),
        client_brouter=client_brouter_ordinaire(),
        client_intervals=client_seance_ordinaire(),
        client_meteo=client_meteo_ordinaire(),
    )
    corps = _demander_un_parcours(client).text
    for marque in ("/Users/", "/home/", "/var/folders/", "C:\\\\", "/tmp/"):
        assert marque not in corps, f"chemin du disque du serveur exposé ({marque})"
    if "gpx" not in corps.lower():
        raise ApiAbsente("aucun champ gpx dans la réponse : E20 n'a rien à emporter")
