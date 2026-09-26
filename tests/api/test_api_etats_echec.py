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
    DEMANDE_PARCOURS_MINIMALE,
    appeler_route,
    cherche_profond,
    client_api,
    client_bouchon,
    client_brouter_ordinaire,
    client_brouter_sans_boucle,
    client_brouter_toujours_la_meme_boucle,
    client_meteo_ordinaire,
    client_seance_ordinaire,
    config_d_essai,
    corps_json,
    route_pour,
    schema_openapi,
    texte_entier,
    verifier_refus_exploitable,
)

#: Les quatre états, chacun avec les mots qui doivent apparaître quelque part
#: dans le contrat publié. Un état d'échec qui n'est nommé nulle part dans le
#: schéma n'a pas été modélisé : il sera découvert en production.
#:
#: **Historique.** La marque portait d'abord sur le test entier (« F1 non
#: livré : aucun schéma OpenAPI »), puis, le schéma livré, sur les deux seuls
#: cas qui manquaient : `meteo_indisponible` (E14) et la clé Intervals
#: révoquée (E15) étaient dessinés dans les maquettes et nommés nulle part.
#: Le trou est comblé le 17/09/2026 — `erreurs.CODES_PANNE` est publié dans la
#: description de l'application et dans l'énumération du champ `code` — et les
#: quatre cas tiennent de nouveau dans un seul paramétrage, sans marque.
ETATS_DESSINES = (
    ("aucune boucle trouvée (E18)", ("aucune_boucle", "aucune boucle", "sans_boucle", "introuvable")),
    ("météo indisponible (E14)", ("meteo_indisponible", "météo indisponible", "sans_meteo")),
    ("une seule proposition (E19)", ("une_seule", "seule_proposition", "motif_deux_propositions")),
    ("clé Intervals révoquée (E15)", ("revoqu", "cle_invalide", "intervals_indisponible")),
)


def _demander_un_parcours(client, **champs):
    """Demande un parcours **en remplissant la demande**, et rend la réponse.

    Corrigé le 17/09/2026. Ces tests appelaient la route de parcours sans
    corps, ou avec des `params=` qu'elle ne déclare pas : la réponse était un
    422 « body : champ requis ». C'est bien un 4xx avec un code et un message
    français, donc les assertions passaient — sans qu'aucune boucle ait été
    cherchée ni aucun service appelé. `appeler_route` met les champs là où le
    schéma dit qu'ils vont.
    """
    schema = schema_openapi(client)
    chemin, methode, operation = route_pour(schema, "sortie", "boucle", "parcours")
    return appeler_route(client, schema, chemin, methode, operation, DEMANDE_PARCOURS_MINIMALE | champs)


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


def test_aucune_boucle_trouvee_rend_un_refus_exploitable():
    """Protège E18 · échec (« Aucune boucle »).

    Le moteur sait déjà dire qu'il n'a rien trouvé. Ce qui se perd en chemin
    vers un front, c'est la *forme* : une exception qui remonte devient un 500
    nu, et l'écran dessiné devient une page blanche.

    **Ce que la version précédente ne vérifiait pas.** Elle exigeait un
    paramètre de durée ou de distance déclaré, puis appelait la route avec
    `params={duree: 2}` : la route de parcours attend un corps, le 422 rendu
    était « body : champ requis », et le refus vérifié n'était pas celui d'une
    boucle introuvable. Le BRouter bouchonné à `{}` n'était même pas appelé.
    """
    client = client_api(
        config=config_d_essai(),
        client_brouter=client_brouter_sans_boucle(),
        client_intervals=client_seance_ordinaire(),
        client_meteo=client_meteo_ordinaire(),
    )
    corps = verifier_refus_exploitable(_demander_un_parcours(client), "aucune boucle trouvée")
    assert corps["code"] == "aucune_boucle", (
        f"code {corps['code']!r} : E18 est un état nommé, pas un refus générique. "
        "Un front qui branche son écran sur `requete_invalide` dessinerait « corrigez votre "
        "saisie » là où il n'y a rien à corriger."
    )


@pytest.mark.xfail(
    strict=True,
    reason=(
        "E18 exige des pistes de repli chiffrées (« élargir la durée, 1 h 45 à 2 h 15 ») et l'API ne rend "
        "que le code `aucune_boucle` et son message : de combien élargir, et sur quel levier en premier, "
        "est un arbitrage produit non rendu (Q36 de docs/journal/questions/questions_mainteneur.md). "
        "Chiffrer un élargissement ici serait une affirmation sans mesure (règle absolue 5)."
    ),
)
def test_aucune_boucle_trouvee_propose_les_deux_leviers_avec_leurs_valeurs():
    """Protège E18 · échec, deuxième moitié : « Ce qui peut aider ».

    L'écran ne dit pas « réessayez » : il propose « élargir la durée, 1 h 45 à
    2 h 15 » et « laisser la direction libre », avec un bouton *Essayer* par
    levier. Ces valeurs ne s'inventent pas côté front — le front ne connaît ni
    la tolérance de distance ni le nombre d'essais déjà faits. Elles viennent
    donc de l'API, ou l'écran ment.
    """
    client = client_api(
        config=config_d_essai(),
        client_brouter=client_brouter_sans_boucle(),
        client_intervals=client_seance_ordinaire(),
        client_meteo=client_meteo_ordinaire(),
    )
    corps = corps_json(_demander_un_parcours(client))
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


def test_meteo_indisponible_sert_quand_meme_le_parcours():
    """Protège E14 · dégradé (« Pas de météo ce matin »).

    `services/boucle.py` le dit déjà dans son docstring : « la météo est le
    seul maillon qu'on accepte de perdre ». L'écran le montre : le parcours
    reste là, ce sont les affirmations qui disparaissent. Une API qui répond
    503 parce qu'Open-Meteo est tombé supprime un écran qui marche.
    """
    client = client_api(
        config=config_d_essai(),
        client_meteo=client_bouchon(503, texte="service unavailable"),
        client_brouter=client_brouter_ordinaire(),
        client_intervals=client_seance_ordinaire(),
    )
    reponse = _demander_un_parcours(client)
    assert reponse.status_code == 200, (
        f"statut {reponse.status_code} alors qu'Open-Meteo seul est tombé. "
        "E14 sert le parcours sans la météo : « une boucle sans météo vaut mieux que pas de boucle »."
    )
    assert corps_json(reponse)["donnees"].get("propositions"), (
        "200 rendu, mais aucune proposition : « une boucle sans météo » suppose une boucle."
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
        client_brouter=client_brouter_ordinaire(),
        client_intervals=client_seance_ordinaire(),
    )
    corps = corps_json(_demander_un_parcours(client))
    # `cherche_profond` cherche une sous-chaîne : « tenue » attrape aussi
    # `retenue`, le drapeau de la proposition mise en avant, dont la valeur
    # booléenne ferait échouer l'assertion suivante pour une raison qui n'a
    # rien à voir avec la tenue. On ne garde que le champ qui s'appelle
    # vraiment `tenue`.
    tenues = {cle: valeur for cle, valeur in cherche_profond(corps, "tenue") if cle.lower() == "tenue"}
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

    **Bouchon changé le 17/09/2026**, comme ce test demandait qu'on le fasse
    plutôt que de le supprimer. Q43 a retiré l'exigence de se distinguer sur un
    axe mesuré, qui était ce par quoi le bouchon d'avant produisait E19 ; il
    reste le recouvrement de routes, et un BRouter qui rend toujours la même
    boucle l'atteint franchement. Le cas protégé n'a pas changé — « une seule
    proposition est un succès expliqué » — seul le chemin pour y arriver.
    """
    client = client_api(
        config=config_d_essai(),
        client_brouter=client_brouter_toujours_la_meme_boucle(),
        client_intervals=client_seance_ordinaire(),
        client_meteo=client_meteo_ordinaire(),
    )
    reponse = _demander_un_parcours(client, candidates=5)
    assert reponse.status_code == 200, (
        f"statut {reponse.status_code} : servir moins de trois propositions est un résultat, "
        "pas une panne. Tout statut hors 200 fait dessiner l'écran d'erreur à la place de E19."
    )
    corps = corps_json(reponse)
    propositions = corps["donnees"].get("propositions") or []
    assert len(propositions) < 3, (
        f"{len(propositions)} propositions servies : le bouchon ne reproduit plus le cas de E19, "
        "et ce test ne protège plus rien. Le relire plutôt que le supprimer."
    )
    assert corps["donnees"].get("motif_deux_propositions"), (
        "propositions servies sans dire pourquoi elles sont moins de trois. "
        "E19 affiche « toutes empruntaient plus de 25 % des mêmes routes » : ce texte vient d'ici."
    )


@pytest.mark.xfail(
    strict=True,
    reason=(
        "E19 · dégradé propose « Chercher plus loin (8 candidates) » et l'API ne rend que le nombre "
        "de candidates essayées : combien en réessayer est un arbitrage produit non rendu (Q36 de "
        "docs/journal/questions/questions_mainteneur.md). Chercher plus large coûte plus cher et peut "
        "ne rien donner de plus ; poser le chiffre ici serait le décider à la place du mainteneur."
    ),
)
def test_une_seule_proposition_porte_le_recours_chiffre():
    """Protège E19 · dégradé, bouton du bas.

    « Le bouton du bas est le seul recours honnête : chercher plus large coûte
    plus cher et peut ne rien donner de plus. On le propose, on ne le fait pas
    d'office. » Le « (8 candidates) » est une valeur : combien on a essayé,
    combien on essaierait. Seule l'API les connaît.
    """
    client = client_api(
        config=config_d_essai(),
        client_brouter=client_brouter_ordinaire(),
        client_intervals=client_seance_ordinaire(),
        client_meteo=client_meteo_ordinaire(),
    )
    corps = corps_json(_demander_un_parcours(client, candidates=5))
    recours = cherche_profond(corps, "recours", "relance", "candidates_suggerees", "elargir")
    assert recours, (
        f"pas de recours chiffré dans {sorted(corps) if isinstance(corps, dict) else corps}. "
        "Sans lui, F2 code « 8 » en dur dans le front et le chiffre se périme en silence."
    )


# --- E15 · échec : clé Intervals révoquée ------------------------------------


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
    assert corps["erreur"]["code"] == "intervals_refuse", (
        f"code {corps['erreur']['code']!r} : une clé refusée n'est pas une panne du service. "
        "E15 renvoie vers l'écran de la clé, pas vers « réessayer plus tard »."
    )


def test_cle_intervals_revoquee_donne_la_date_du_dernier_succes(tmp_path):
    """Protège E15 · échec, deuxième ligne de l'encart.

    « "Plus lues depuis le 12 septembre" dit à quelqu'un ce qu'il a manqué ;
    "erreur de connexion" ne dit rien. » Cette date n'est pas déductible côté
    front : elle suppose qu'on ait mémorisé quand la clé marchait encore.

    **Le test joue les deux temps**, parce qu'un seul ne prouverait rien : une
    API qui rendrait toujours `dernier_succes: null` passerait un test qui se
    contente de trouver le champ. Ici, la clé marche, puis elle est révoquée,
    et c'est la date du premier appel qui doit revenir. Les deux applications
    partagent le même dossier de données : c'est là que la mémoire vit.
    """
    donnees = tmp_path / "donnees"
    qui_marche = client_api(
        config=config_d_essai(),
        dossier_donnees=donnees,
        client_intervals=client_seance_ordinaire(),
    )
    schema = schema_openapi(qui_marche)
    chemin, methode, _ = route_pour(schema, "semaine", "seance")
    assert qui_marche.requete(methode, chemin).status_code == 200, (
        "le premier appel devait réussir : sans succès, il n'y a pas de date à retenir"
    )

    revoquee = client_api(
        config=config_d_essai(),
        dossier_donnees=donnees,
        client_intervals=client_bouchon(401, {"error": "unauthorized"}),
    )
    corps = corps_json(revoquee.requete(methode, chemin))
    dates = cherche_profond(corps, "dernier_succes", "derniere_lecture", "depuis", "lu_le")
    assert dates, (
        "aucune date de dernier succès. Sans elle, l'écran retombe sur « erreur de connexion », "
        "qui est précisément ce que E15 refuse."
    )
    assert any(isinstance(valeur, str) and valeur for _, valeur in dates), (
        f"le champ existe mais reste vide : {dates!r}. Un champ toujours nul ne dit rien de "
        "plus qu'un champ absent."
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
        client_brouter=client_brouter_ordinaire(),
        client_meteo=client_meteo_ordinaire(),
    )
    schema = schema_openapi(client)
    # **Corrigé le 17/09/2026** : la version précédente visait la route de
    # *sortie*, qui pose la séance du jour sur une boucle et a donc besoin
    # d'Intervals — la voir échouer ne prouvait rien. « Le reste », dans E15,
    # c'est la boucle libre : demander un parcours sans séance.
    chemin, methode, operation = route_pour(schema, "boucle")
    reponse = appeler_route(client, schema, chemin, methode, operation, dict(DEMANDE_PARCOURS_MINIMALE))
    assert reponse.status_code == 200, (
        f"statut {reponse.status_code} : la boucle libre ne demande rien à Intervals et tombe "
        "quand même. E15 promet l'inverse : « Tout le reste fonctionne. »"
    )
    assert corps_json(reponse)["donnees"].get("candidates"), (
        "200 rendu, mais aucune candidate : « le reste marche » suppose un parcours."
    )
