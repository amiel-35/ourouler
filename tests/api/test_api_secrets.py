"""Les secrets : clé Intervals et mot de passe BRouter, et tout ce qui les fait fuir.

Doctrine §10.1 : « Les clés d'API externes sont des données du profil,
secrètes. Clé Intervals, plus tard GraphHopper, Garmin : jamais en clair dans
un log, une erreur, un JSON de sortie (`ourouler config --json` les masque
déjà). » Règle absolue 1 de `CLAUDE.md` : aucune clé dans le dépôt.

Le mot important est « déjà ». Le masquage existe — et il est écrit **à la
main dans `cli.py`**, deux lignes après un `dataclasses.asdict(config)` qui,
lui, rend tout (`discovery_donnees.md` §2). L'API est une seconde sortie JSON
de la même `Config` : elle refera ce geste, ou elle l'oubliera. Ces tests
cherchent l'oubli, par cinq chemins : la réponse nominale, le message
d'erreur, le schéma publié, le journal, et l'écho d'une écriture.

Toutes les valeurs secrètes de ce fichier sont des sentinelles inventées,
reconnaissables à l'œil nu et présentes nulle part ailleurs que dans les
tests.
"""

from __future__ import annotations

import dataclasses
import logging

import pytest
from outils_api import (
    CLE_INTERVALS_SENTINELLE,
    MDP_BROUTER_SENTINELLE,
    SENTINELLES,
    cherche_profond,
    client_api,
    client_bouchon,
    config_d_essai,
    corps_json,
    noms_de_parametres,
    parametre_nomme,
    route_pour,
    routes,
    schema_openapi,
    texte_entier,
)


# Marque « F1 non livré » retirée le 17/09/2026 : la fabrique accepte désormais
# une Config et des clients injectés, et ce test passe. `strict` l'a signalé.
def test_la_route_de_configuration_masque_les_deux_secrets():
    """Protège E21 (« Réglages ») et E12 (« Brancher Intervals »).

    `ourouler config --json` masque `intervals.api_key` et
    `brouter.mot_de_passe`. La route équivalente sert le même écran : si elle
    part d'un `asdict(config)` sans refaire le masquage, la clé part dans le
    navigateur, dans le cache HTTP et dans les outils de développement.
    """
    client = client_api(config=config_d_essai())
    schema = schema_openapi(client)
    chemin, methode, _ = route_pour(schema, "config", "profil", "reglage")
    reponse = client.requete(methode, chemin)
    entier = texte_entier(corps_json(reponse))
    for sentinelle in SENTINELLES:
        assert sentinelle not in entier, (
            f"secret en clair dans {methode} {chemin}. Doctrine §10.1 : jamais dans un JSON de sortie."
        )


# Marque « F1 non livré » retirée le 17/09/2026 : la fabrique accepte désormais
# une Config et des clients injectés, et ce test passe. `strict` l'a signalé.
def test_la_route_de_configuration_dit_quand_meme_si_la_cle_est_renseignee():
    """Protège E21, ligne « intervals.icu · Branché ».

    Un masquage qui supprime le champ rend l'écran indécidable : « Branché »
    et « Plus tard » deviennent indistinguables. `config.py:104-106` porte
    déjà un booléen `renseigne` — c'est lui qu'il faut transmettre, pas la clé.
    """
    client = client_api(config=config_d_essai())
    schema = schema_openapi(client)
    chemin, methode, _ = route_pour(schema, "config", "profil", "reglage")
    corps = corps_json(client.requete(methode, chemin))
    marques = cherche_profond(corps, "renseigne", "branche", "configure", "present")
    assert marques, (
        "la clé est masquée mais rien ne dit si elle existe. E21 affiche « Branché » ou rien : "
        "ce booléen doit venir de l'API."
    )


# Marque « pas de route qui échoue sur un service authentifié » retirée le
# 17/09/2026 : la route de la semaine échoue sur un Intervals bouchonné à 401
# depuis que la fabrique sait habiller un transport injecté du connecteur qui
# porte la clé (`api/routes/commun.FABRIQUES_CONNECTEUR`).
def test_aucun_secret_ne_fuit_dans_un_message_d_erreur():
    """Protège E15 · échec et E12, et la doctrine §10.1 (« jamais dans une erreur »).

    C'est le chemin de fuite classique : le connecteur lève, le message
    d'erreur cite l'URL appelée, et l'URL porte l'authentification. Intervals
    s'authentifie en basique `API_KEY:<clé>` — une URL complète recopiée dans
    un message suffit à publier la clé.
    """
    client = client_api(
        config=config_d_essai(),
        client_intervals=client_bouchon(401, {"error": "unauthorized"}),
    )
    schema = schema_openapi(client)
    chemin, methode, _ = route_pour(schema, "semaine", "seance")
    reponse = client.requete(methode, chemin)
    entier = texte_entier(reponse.text) + texte_entier(dict(reponse.headers))
    for sentinelle in SENTINELLES:
        assert sentinelle not in entier, f"secret dans la réponse d'erreur de {methode} {chemin}"


# Marque « F1 non livré » retirée le 17/09/2026 : la fabrique accepte désormais
# une Config et des clients injectés, et ce test passe. `strict` l'a signalé.
def test_le_schema_publie_ne_porte_aucun_secret_en_exemple_ni_en_defaut():
    """Protège le dépôt lui-même (règle absolue 1).

    Un `example="ma-vraie-cle"` dans un modèle de requête finit dans le schéma
    public, donc dans la documentation interactive, donc dans le dépôt le jour
    où quelqu'un en committe une copie.
    """
    schema = schema_openapi(client_api(config=config_d_essai()))
    entier = texte_entier(schema)
    for sentinelle in SENTINELLES:
        assert sentinelle not in entier, "un secret du profil s'est retrouvé dans le schéma publié"


# Marque « rien ne journalise encore » retirée le 17/09/2026 : elle était
# fausse. `httpx` journalise chaque requête en INFO (« HTTP Request: GET
# https://intervals.icu/… »), et `uvicorn` journalise chaque réponse : il y a
# donc bien un journal, et c'est précisément celui où une URL authentifiée
# ferait sortir la clé. Le test le surveille maintenant pour de bon.
def test_aucun_secret_ne_fuit_dans_le_journal(caplog: pytest.LogCaptureFixture):
    """Protège la doctrine §10.1 (« jamais en clair dans un log »).

    Le journal est le chemin de fuite le plus discret : personne ne le relit,
    et en hébergé il part chez l'hébergeur. Un `logger.debug("config=%s",
    config)` suffit — `repr(Config)` masque aujourd'hui, mais
    `dataclasses.asdict(config)`, lui, ne masque rien.
    """
    caplog.set_level(logging.DEBUG)
    client = client_api(
        config=config_d_essai(),
        client_intervals=client_bouchon(401, {"error": "unauthorized"}),
    )
    schema = schema_openapi(client)
    chemin, methode, _ = route_pour(schema, "semaine", "seance")
    client.requete(methode, chemin)
    journal = "\n".join(enregistrement.getMessage() for enregistrement in caplog.records)
    for sentinelle in SENTINELLES:
        assert sentinelle not in journal, f"secret journalisé pendant {methode} {chemin}"


# Marque « F1 non livré » retirée le 17/09/2026 : la fabrique accepte désormais
# une Config et des clients injectés, et ce test passe. `strict` l'a signalé.
def test_l_ecriture_d_une_cle_ne_la_renvoie_pas_en_echo():
    """Protège E12 (« Brancher intervals.icu »).

    L'écran affiche la clé en clair pendant la saisie — décision assumée des
    maquettes, « masquer un secret qu'on vient de coller n'ajoute rien ». Mais
    une fois enregistrée, elle ne doit plus jamais revenir : un écho dans la
    réponse d'écriture la remet dans l'historique du navigateur et dans tout
    proxy sur le chemin.
    """
    client = client_api(config=config_d_essai())
    schema = schema_openapi(client)
    ecritures = [
        (chemin, methode, operation)
        for chemin, methode, operation in routes(schema)
        if methode in {"POST", "PUT", "PATCH"}
        and any(mot in chemin.lower() for mot in ("config", "profil", "reglage", "intervals"))
    ]
    assert ecritures, "aucune route d'écriture du profil : E12 ne peut pas enregistrer de clé"
    chemin, methode, operation = ecritures[0]
    champ = parametre_nomme(noms_de_parametres(schema, operation), "api_key", "cle", "key")
    reponse = client.requete(methode, chemin, json={champ or "api_key": CLE_INTERVALS_SENTINELLE})
    assert CLE_INTERVALS_SENTINELLE not in reponse.text, (
        f"{methode} {chemin} renvoie la clé en écho. Une écriture confirme, elle ne recopie pas."
    )


# --- contre-épreuve : le danger est réel, le test n'est pas décoratif --------


def test_asdict_d_une_config_expose_les_secrets_en_clair():
    """Contre-épreuve des tests ci-dessus : mesure le piège au lieu de le supposer.

    `repr(Config)` est déjà masqué — quelqu'un y a pensé. Mais la sortie JSON
    ne passe pas par `repr` : `cli.py` fait `dataclasses.asdict(config)` puis
    remasque les deux champs **à la main**. Ce test constate que le premier
    geste fuit, ce qui est la raison d'être du second. Le jour où `asdict`
    cesserait de fuir, ce test tombe et il faudra le relire, pas le supprimer.
    """
    config = config_d_essai()
    assert CLE_INTERVALS_SENTINELLE not in repr(config), "repr(Config) masque, et c'est acquis"
    a_plat = str(dataclasses.asdict(config))
    assert CLE_INTERVALS_SENTINELLE in a_plat, "asdict ne fuit plus : relire le masquage de l'API"
    assert MDP_BROUTER_SENTINELLE in a_plat


# Écrit en `xfail(strict=True)` par le testeur en aveugle, le masquage étant
# alors deux lignes recopiées dans `cli.py`. La marque est tombée le
# 17/09/2026 avec l'extraction de `config.en_dict_public` — et c'est `strict`
# qui l'a signalé : le test s'est mis à passer, et la suite a échoué pour le
# dire au lieu de laisser une marque périmée derrière elle.
def test_le_masquage_des_secrets_est_une_fonction_partagee():
    """Protège E21, E12 et toute sortie JSON future (doctrine §10.1).

    Un invariant qui tient parce que deux lignes ont été recopiées au bon
    endroit n'est pas un invariant, c'est une chance. La fonction doit vivre
    hors de `cli.py` pour que l'API, et demain l'export RGPD de E21
    (« Mes données · Tout exporter »), s'en servent au lieu de la réécrire.
    """
    from importlib import import_module

    candidats = ("ourouler.config", "ourouler.noyau.erreurs", "ourouler.rendu.profil")
    noms = ("masquer_secrets", "sans_secrets", "en_dict_public", "masquer", "public")
    trouvee = None
    for module_nom in candidats:
        module = import_module(module_nom)
        for nom in noms:
            objet = getattr(module, nom, None)
            if callable(objet):
                trouvee = objet
                break
    assert trouvee, (
        f"aucune fonction de masquage partagée. Cherché {noms} dans {candidats}. "
        "Aujourd'hui le masquage vit dans cli.py, inatteignable depuis l'API."
    )
    a_plat = texte_entier(trouvee(config_d_essai()))
    for sentinelle in SENTINELLES:
        assert sentinelle not in a_plat, "la fonction de masquage partagée ne masque pas"
