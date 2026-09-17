"""Les quatre états d'échec dessinés dans les maquettes, plus le piège du cinquième.

`cycle_ux_contrat.md`, « Comment les maquettes seront jugées » : « Chaque écran
a ses états dégradés dessinés, pas seulement son état heureux : pas de séance,
météo indisponible, aucune boucle trouvée, une seule proposition au lieu de
trois. » Les maquettes en ont dessiné quatre, section « Quand ça casse » :

| écran | état | ce que l'API doit rendre |
|---|---|---|
| E18 · échec | aucune boucle trouvée | un refus 4xx avec **les deux leviers chiffrés** |
| E14 · dégradé | météo indisponible | un **succès** amputé : le parcours reste servi |
| E19 · dégradé | une seule proposition | un **succès expliqué**, surtout pas une panne |
| E15 · échec | clé Intervals révoquée | l'état *et* la date du dernier succès |

Le piège est au milieu : deux de ces quatre ne sont pas des erreurs. Une API
qui rend 500 sur « une seule proposition » casse un écran qui marche.
"""

from __future__ import annotations

import pytest
from outils_api import (
    cherche_profond,
    client_api,
    client_bouchon,
    config_d_essai,
    corps_json,
    noms_de_parametres,
    parametre_nomme,
    route_pour,
    schema_openapi,
    texte_entier,
    verifier_refus_exploitable,
)

#: Les quatre états, chacun avec les mots qui doivent apparaître quelque part
#: dans le contrat publié. Un état d'échec qui n'est nommé nulle part dans le
#: schéma n'a pas été modélisé : il sera découvert en production.
ETATS_DESSINES = (
    ("aucune boucle trouvée (E18)", ("aucune_boucle", "aucune boucle", "sans_boucle", "introuvable")),
    ("météo indisponible (E14)", ("meteo_indisponible", "météo indisponible", "sans_meteo")),
    ("une seule proposition (E19)", ("une_seule", "seule_proposition", "motif_deux_propositions")),
    ("clé Intervals révoquée (E15)", ("revoqu", "cle_invalide", "intervals_indisponible")),
)


@pytest.mark.xfail(
    strict=True, reason="F1 non livré : aucun schéma OpenAPI, donc aucun vocabulaire d'erreur."
)
@pytest.mark.parametrize("etat,mots", ETATS_DESSINES, ids=[e for e, _ in ETATS_DESSINES])
def test_le_contrat_publie_nomme_chacun_des_quatre_etats(etat: str, mots: tuple[str, ...]):
    """Protège les quatre écrans de la section « Quand ça casse ».

    Un front ne peut pas dessiner un état qu'il ne sait pas reconnaître. Ce
    test ne dit pas *comment* nommer chaque état — il exige seulement que le
    nom existe dans le schéma publié, en tant que code d'erreur, valeur
    d'énumération ou champ de réponse. C'est le minimum pour que F2 soit
    codable sans lire le code de F1.
    """
    schema = schema_openapi(client_api(config=config_d_essai()))
    entier = texte_entier(schema).lower()
    assert any(mot.lower() in entier for mot in mots), (
        f"l'état « {etat} » n'apparaît nulle part dans le contrat publié. "
        f"Cherché : {mots}. Un état d'échec non modélisé se découvre en production."
    )


# --- E18 · échec : aucune boucle trouvée -------------------------------------


@pytest.mark.xfail(
    strict=True, reason="F1 non livré : pas de route de parcours à qui demander l'impossible."
)
def test_aucune_boucle_trouvee_rend_un_refus_exploitable():
    """Protège E18 · échec (« Aucune boucle »).

    Le moteur sait déjà dire qu'il n'a rien trouvé. Ce qui se perd en chemin
    vers un front, c'est la *forme* : une exception qui remonte devient un 500
    nu, et l'écran dessiné devient une page blanche.
    """
    client = client_api(config=config_d_essai(), client_brouter=client_bouchon(200, {}))
    schema = schema_openapi(client)
    chemin, methode, operation = route_pour(schema, "sortie", "boucle", "parcours")
    noms = noms_de_parametres(schema, operation)
    duree = parametre_nomme(noms, "duree", "distance")
    assert duree, f"aucun paramètre de durée ni de distance sur {methode} {chemin} : {sorted(noms)}"
    reponse = client.requete(methode, chemin, params={duree: 2})
    verifier_refus_exploitable(reponse, "aucune boucle trouvée")


@pytest.mark.xfail(
    strict=True,
    reason="F1 non livré, et E18 exige en plus des pistes de repli chiffrées, pas un 'réessayez'.",
)
def test_aucune_boucle_trouvee_propose_les_deux_leviers_avec_leurs_valeurs():
    """Protège E18 · échec, deuxième moitié : « Ce qui peut aider ».

    L'écran ne dit pas « réessayez » : il propose « élargir la durée, 1 h 45 à
    2 h 15 » et « laisser la direction libre », avec un bouton *Essayer* par
    levier. Ces valeurs ne s'inventent pas côté front — le front ne connaît ni
    la tolérance de distance ni le nombre d'essais déjà faits. Elles viennent
    donc de l'API, ou l'écran ment.
    """
    client = client_api(config=config_d_essai(), client_brouter=client_bouchon(200, {}))
    schema = schema_openapi(client)
    chemin, methode, operation = route_pour(schema, "sortie", "boucle", "parcours")
    duree = parametre_nomme(noms_de_parametres(schema, operation), "duree", "distance") or "duree"
    corps = corps_json(client.requete(methode, chemin, params={duree: 2}))
    pistes = cherche_profond(corps, "piste", "repli", "recours", "suggestion", "elargir")
    assert pistes, (
        f"aucune piste de repli dans la réponse ({sorted(corps) if isinstance(corps, dict) else corps}). "
        "E18 en dessine deux, chacune avec sa valeur."
    )
    _, valeurs = pistes[0]
    assert isinstance(valeurs, (list, tuple)) and len(valeurs) >= 2, (
        f"E18 dessine deux leviers (élargir la durée, libérer la direction), reçu : {valeurs!r}"
    )


# --- E14 · dégradé : météo indisponible --------------------------------------


@pytest.mark.xfail(
    strict=True,
    reason="F1 non livré. Exigence : météo en panne = succès amputé, jamais un échec global.",
)
def test_meteo_indisponible_sert_quand_meme_le_parcours():
    """Protège E14 · dégradé (« Pas de météo ce matin »).

    `boucle/commande.py` le dit déjà dans son docstring : « la météo est le
    seul maillon qu'on accepte de perdre ». L'écran le montre : le parcours
    reste là, ce sont les affirmations qui disparaissent. Une API qui répond
    503 parce qu'Open-Meteo est tombé supprime un écran qui marche.
    """
    client = client_api(
        config=config_d_essai(),
        client_meteo=client_bouchon(503, texte="service unavailable"),
    )
    schema = schema_openapi(client)
    chemin, methode, _ = route_pour(schema, "sortie", "parcours")
    reponse = client.requete(methode, chemin)
    assert reponse.status_code == 200, (
        f"statut {reponse.status_code} alors qu'Open-Meteo seul est tombé. "
        "E14 sert le parcours sans la météo : « une boucle sans météo vaut mieux que pas de boucle »."
    )


@pytest.mark.xfail(
    strict=True,
    reason="F1 non livré. Exigence : la tenue se tait *et dit pourquoi* quand la météo manque.",
)
def test_meteo_indisponible_tait_la_tenue_et_dit_pourquoi():
    """Protège E14 · dégradé, bloc « La tenue ».

    « Sans température, on ne conseille rien plutôt que de conseiller au
    hasard » — règle absolue 5. Un `tenue: null` tout seul ne suffit pas : le
    front ne saurait pas distinguer « pas calculé » de « refusé faute de
    mesure », et afficherait un bloc vide qui se lit comme un bug.
    """
    client = client_api(
        config=config_d_essai(),
        client_meteo=client_bouchon(503, texte="service unavailable"),
    )
    schema = schema_openapi(client)
    chemin, methode, _ = route_pour(schema, "sortie", "parcours")
    corps = corps_json(client.requete(methode, chemin))
    tenues = dict(cherche_profond(corps, "tenue"))
    assert tenues, "aucun champ `tenue` dans la réponse : E14 en dessine un, même muet"
    assert all(valeur in (None, {}, []) for valeur in tenues.values()), (
        f"une tenue est conseillée sans température : {tenues!r} (règle absolue 5)"
    )
    motifs = cherche_profond(corps, "motif", "pourquoi", "raison", "indisponible", "inconnu")
    assert motifs, (
        "la météo manque et rien n'explique pourquoi la tenue se tait. "
        "Un bloc vide se lit comme une panne ; une phrase en fait un refus assumé."
    )


# --- E19 · dégradé : une seule proposition — le piège ------------------------


@pytest.mark.xfail(
    strict=True,
    reason="F1 non livré. Piège à ne pas manquer : « une seule » est un succès, pas une panne.",
)
def test_une_seule_proposition_est_un_succes_explique_et_pas_une_erreur():
    """Protège E19 · dégradé (« Un seul parcours »).

    Mot pour mot dans les maquettes : « Ce n'est pas une panne, et c'est tout
    le problème : il faut que l'écran ne ressemble pas à une panne. Le
    comportement existe déjà dans la commande, qui refuse de servir trois
    boucles qui se ressemblent et dit pourquoi. »

    Le champ existe déjà côté CLI : `motif_deux_propositions` dans
    `sortie --json` (`discovery_donnees.md` §2). L'API doit le transmettre,
    avec un statut 200 — pas le convertir en 404 « pas assez de résultats »,
    ni en 422, ni en 500.
    """
    client = client_api(config=config_d_essai(), client_brouter=client_bouchon(200, {}))
    schema = schema_openapi(client)
    chemin, methode, operation = route_pour(schema, "sortie", "parcours")
    noms = noms_de_parametres(schema, operation)
    candidates = parametre_nomme(noms, "candidate")
    params = {candidates: 5} if candidates else {}
    reponse = client.requete(methode, chemin, params=params)
    assert reponse.status_code == 200, (
        f"statut {reponse.status_code} : servir moins de trois propositions est un résultat, "
        "pas une panne. Tout statut hors 200 fait dessiner l'écran d'erreur à la place de E19."
    )
    corps = corps_json(reponse)
    motifs = cherche_profond(corps, "motif", "distinction", "explication")
    assert motifs, (
        "propositions servies sans dire pourquoi elles sont moins de trois. "
        "E19 affiche « toutes empruntaient plus de 25 % des mêmes routes » : ce texte vient d'ici."
    )


@pytest.mark.xfail(
    strict=True,
    reason="F1 non livré. E19 · dégradé propose « Chercher plus loin (8 candidates) » : le nombre "
    "vient de l'API, le front ne peut pas l'inventer.",
)
def test_une_seule_proposition_porte_le_recours_chiffre():
    """Protège E19 · dégradé, bouton du bas.

    « Le bouton du bas est le seul recours honnête : chercher plus large coûte
    plus cher et peut ne rien donner de plus. On le propose, on ne le fait pas
    d'office. » Le « (8 candidates) » est une valeur : combien on a essayé,
    combien on essaierait. Seule l'API les connaît.
    """
    client = client_api(config=config_d_essai(), client_brouter=client_bouchon(200, {}))
    schema = schema_openapi(client)
    chemin, methode, _ = route_pour(schema, "sortie", "parcours")
    corps = corps_json(client.requete(methode, chemin))
    recours = cherche_profond(corps, "recours", "relance", "candidates_suggerees", "elargir")
    assert recours, (
        f"pas de recours chiffré dans {sorted(corps) if isinstance(corps, dict) else corps}. "
        "Sans lui, F2 code « 8 » en dur dans le front et le chiffre se périme en silence."
    )


# --- E15 · échec : clé Intervals révoquée ------------------------------------


@pytest.mark.xfail(
    strict=True,
    reason="F1 non livré. Le 401 d'Intervals doit devenir un état nommé, pas une liste vide.",
)
def test_cle_intervals_revoquee_ne_se_confond_pas_avec_une_semaine_vide():
    """Protège E15 · échec (« intervals.icu ne nous répond plus »).

    Le plus insidieux des quatre, et les maquettes disent pourquoi : « Un
    écran vide se lit comme "rien de prévu cette semaine" — l'utilisateur ne
    va pas rouler. » Rendre `{"seances": []}` sur un 401 est donc pire qu'une
    erreur : c'est une réponse fausse, et personne ne s'en aperçoit.
    """
    client = client_api(
        config=config_d_essai(),
        client_intervals=client_bouchon(401, {"error": "unauthorized"}),
    )
    schema = schema_openapi(client)
    chemin, methode, _ = route_pour(schema, "semaine", "seance")
    reponse = client.requete(methode, chemin)
    corps = corps_json(reponse)
    etat = cherche_profond(corps, "revoqu", "invalide", "indisponible", "erreur", "code")
    assert etat, (
        f"statut {reponse.status_code}, corps {corps!r} : rien ne distingue « clé révoquée » de "
        "« aucune séance cette semaine ». C'est exactement la confusion que E15 corrige."
    )


@pytest.mark.xfail(
    strict=True,
    reason="F1 non livré. E15 exige la date du dernier succès : « La date compte plus que le message ».",
)
def test_cle_intervals_revoquee_donne_la_date_du_dernier_succes():
    """Protège E15 · échec, deuxième ligne de l'encart.

    « "Plus lues depuis le 12 septembre" dit à quelqu'un ce qu'il a manqué ;
    "erreur de connexion" ne dit rien. » Cette date n'est pas déductible côté
    front : elle suppose qu'on ait mémorisé quand la clé marchait encore.
    """
    client = client_api(
        config=config_d_essai(),
        client_intervals=client_bouchon(401, {"error": "unauthorized"}),
    )
    schema = schema_openapi(client)
    chemin, methode, _ = route_pour(schema, "semaine", "seance")
    corps = corps_json(client.requete(methode, chemin))
    dates = cherche_profond(corps, "dernier_succes", "derniere_lecture", "depuis", "lu_le")
    assert dates, (
        "aucune date de dernier succès. Sans elle, l'écran retombe sur « erreur de connexion », "
        "qui est précisément ce que E15 refuse."
    )


@pytest.mark.xfail(
    strict=True,
    reason="F1 non livré. Le reste du produit doit rester servi quand Intervals tombe.",
)
def test_intervals_en_panne_ne_casse_pas_le_reste_du_produit():
    """Protège E15 · échec, bloc « En attendant ».

    « Intervals n'est pas le produit, juste une source. Le reste marche sans
    lui, et c'est le moment de le prouver. » Concrètement : la route de
    demande manuelle et celle de dépôt de fichier doivent rester joignables
    alors que le connecteur Intervals répond 401.
    """
    client = client_api(
        config=config_d_essai(),
        client_intervals=client_bouchon(401, {"error": "unauthorized"}),
    )
    schema = schema_openapi(client)
    chemin, methode, _ = route_pour(schema, "sortie", "boucle", "parcours")
    reponse = client.requete(methode, chemin)
    assert reponse.status_code != 401, (
        "la demande manuelle renvoie 401 parce qu'Intervals est fâché. "
        "E15 promet l'inverse : « Tout le reste fonctionne. »"
    )
