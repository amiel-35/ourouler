"""L'isolation par propriétaire, écrite avant qu'il y ait des utilisateurs.

Doctrine §10.2 : « Isolation des données : par utilisateur, vérifiée côté
serveur à chaque requête, jamais seulement côté front. **Aucune requête sans
clause de propriétaire.** »

`front_contrat.md`, F1 : « Isolation par propriétaire **dès maintenant** dans
la forme des requêtes, même sans comptes : c'est gratuit à écrire et
impossible à rattraper après. »

C'est le seul thème de ce dossier où le coût d'attendre n'est pas linéaire.
Une route écrite aujourd'hui sans paramètre de propriétaire devra, en F3,
être retrouvée une par une — et celle qu'on oubliera servira les données d'un
autre. Ces tests posent la forme pendant qu'elle ne coûte rien.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from outils_api import (
    PROPRIETAIRE_A,
    PROPRIETAIRE_B,
    SOURCES,
    client_api,
    config_d_essai,
    fichiers_python_de_l_api,
    noms_de_parametres,
    parametre_nomme,
    routes,
    schema_openapi,
)

#: Les noms acceptables pour la clause de propriétaire. On n'impose pas le mot :
#: on impose qu'il y en ait un, et qu'il soit déclaré dans le contrat.
MOTS_PROPRIETAIRE = ("proprietaire", "utilisateur", "profil_id", "compte", "owner")

#: Routes qui n'ont légitimement pas de propriétaire : elles ne lisent aucune
#: donnée de profil. La liste est courte exprès — toute route qui n'y est pas
#: doit porter la clause.
CHEMINS_SANS_PROPRIETAIRE = ("/openapi", "/docs", "/redoc", "/sante", "/health", "/version")


def _porte_la_clause(schema, chemin: str, operation: dict) -> bool:
    if any(mot in chemin.lower() for mot in MOTS_PROPRIETAIRE):
        return True
    noms = noms_de_parametres(schema, operation)
    if parametre_nomme(noms, *MOTS_PROPRIETAIRE):
        return True
    for parametre in operation.get("parameters") or []:
        nom = str(parametre.get("name", "")).lower()
        if parametre.get("in") == "header" and any(mot in nom for mot in MOTS_PROPRIETAIRE):
            return True
    return bool(operation.get("security"))


@pytest.mark.xfail(
    strict=True, reason="F1 non livré : aucune route déclarée, donc aucune clause à vérifier."
)
def test_chaque_route_de_donnees_declare_une_clause_de_proprietaire():
    """Protège tous les écrans de F3, écrits pendant F1 parce que c'est gratuit maintenant.

    Le test lit le contrat publié, pas le code : une clause qui n'est pas dans
    le schéma n'existe pas pour le front, et ne sera pas branchée.
    """
    schema = schema_openapi(client_api(config=config_d_essai()))
    nues = [
        f"{methode} {chemin}"
        for chemin, methode, operation in routes(schema)
        if not any(exclu in chemin.lower() for exclu in CHEMINS_SANS_PROPRIETAIRE)
        and not _porte_la_clause(schema, chemin, operation)
    ]
    assert not nues, (
        "routes sans clause de propriétaire :\n  "
        + "\n  ".join(sorted(nues))
        + f"\nAccepté : un segment de chemin, un paramètre ou un en-tête parmi {MOTS_PROPRIETAIRE}, "
        "ou une exigence `security`. Doctrine §10.2 : aucune requête sans clause de propriétaire."
    )


@pytest.mark.xfail(
    strict=True,
    reason="F1 non livré. Exigence : le propriétaire implicite doit être nommé, pas supposé.",
)
def test_une_requete_sans_proprietaire_ne_sert_pas_silencieusement_le_mainteneur():
    """Protège F3 contre la dette la plus chère du lot.

    Tant qu'il n'y a qu'un utilisateur, servir son profil par défaut « marche ».
    Le jour où il y en a deux, ce défaut devient une fuite, et il est réparti
    dans toutes les routes. Deux réponses acceptables : refuser la requête, ou
    l'accepter en **nommant** dans la réponse le propriétaire retenu — ce qui
    rend l'oubli visible au lieu de le rendre confortable.
    """
    client = client_api(config=config_d_essai())
    schema = schema_openapi(client)
    chemin, methode, operation = next(
        (c, m, o)
        for c, m, o in routes(schema)
        if not any(exclu in c.lower() for exclu in CHEMINS_SANS_PROPRIETAIRE)
    )
    reponse = client.requete(methode, chemin)
    if reponse.status_code in (401, 403, 422):
        return
    assert any(
        mot in reponse.text.lower() for mot in MOTS_PROPRIETAIRE
    ), (
        f"{methode} {chemin} répond {reponse.status_code} sans propriétaire demandé ni nommé. "
        "Le rattachement implicite est exactement ce qui ne se rattrape pas en F3."
    )


@pytest.mark.xfail(
    strict=True,
    reason="F1 non livré. Exigence : une ressource d'un propriétaire n'est pas lisible par un autre.",
)
def test_une_ressource_d_un_proprietaire_n_est_pas_lisible_par_un_autre():
    """Protège E20 (« Télécharger le GPX ») et E21 (« Mes données »).

    Le GPX est servi par identifiant — c'est le point d'énumération classique.
    Demander la ressource de A en se présentant comme B doit rendre 403 ou
    404, jamais 200.
    """
    client = client_api(config=config_d_essai())
    schema = schema_openapi(client)
    candidates = [
        (c, m, o)
        for c, m, o in routes(schema)
        if m == "GET" and any(mot in c.lower() for mot in ("gpx", "parcours", "sortie", "carte"))
    ]
    assert candidates, "aucune route de téléchargement : E20 ne peut rien emporter"
    chemin, methode, operation = candidates[0]
    cle = parametre_nomme(noms_de_parametres(schema, operation), *MOTS_PROPRIETAIRE)
    assert cle, f"{methode} {chemin} ne prend pas de propriétaire : l'isolation n'est pas testable"
    chemin_concret = re.sub(r"\{[^}]+\}", "1", chemin)
    a = client.requete(methode, chemin_concret, params={cle: PROPRIETAIRE_A})
    b = client.requete(methode, chemin_concret, params={cle: PROPRIETAIRE_B})
    assert not (a.status_code == 200 and b.status_code == 200 and a.content == b.content), (
        f"{methode} {chemin} rend le même contenu à deux propriétaires distincts"
    )


# --- la forme du stockage, vérifiable dès aujourd'hui ------------------------


def _tables_declarees() -> list[tuple[Path, str, str]]:
    """[(fichier, nom de table, corps du CREATE TABLE)] dans tout `src/ourouler/`."""
    motif = re.compile(
        r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(\w+)\s*\((.*?)\)\s*;", re.IGNORECASE | re.DOTALL
    )
    trouvees = []
    for fichier in sorted(SOURCES.rglob("*.py")):
        if "__pycache__" in fichier.parts:
            continue
        texte = fichier.read_text(encoding="utf-8")
        for nom, corps in motif.findall(texte):
            trouvees.append((fichier, nom, corps))
    return trouvees


def test_il_y_a_bien_des_tables_a_verifier():
    """Contre-épreuve : sans elle, le test suivant passerait sur une liste vide."""
    tables = {nom for _, nom, _ in _tables_declarees()}
    assert {"troncons", "sorties", "activites"} <= tables, tables


def test_chaque_table_porte_une_colonne_proprietaire():
    """Protège la migration vers l'hébergé (doctrine §10.1).

    « Le schéma de l'index local est écrit avec une colonne "propriétaire" en
    tête, pour que la migration soit un déplacement, pas une réécriture. »

    Ce test était en `xfail(strict)` : `apprentissage/routes.py` était seul à
    porter la colonne — et avait dû écrire une migration 1→2 pour rattraper
    l'oubli, la preuve par l'exemple que le rattrapage coûte. Le 17/09/2026,
    `activites/cache.py` et `connecteurs/openmeteo_archive.py` l'ont à leur
    tour ; le `xfail` a donc sauté. Ce qu'il vérifie est structurel et vaut
    pour toute table future, y compris celles de F3.
    """
    sans = [
        f"{fichier.relative_to(SOURCES)}:{nom}"
        for fichier, nom, corps in _tables_declarees()
        if "proprietaire" not in corps.lower()
    ]
    assert not sans, "tables sans colonne propriétaire :\n  " + "\n  ".join(sorted(sans))


@pytest.mark.xfail(
    strict=True, reason="F1 non livré : src/ourouler/api/ n'existe pas, aucun SQL à analyser."
)
def test_aucune_requete_sql_de_l_api_ne_lit_sans_filtrer_par_proprietaire():
    """Protège F3 (doctrine §10.2, « vérifiée côté serveur à chaque requête »).

    Une clause de propriétaire dans l'URL qui ne redescend pas dans le `WHERE`
    est une isolation de façade. Ce test lit le SQL des sources de l'API : tout
    SELECT/UPDATE/DELETE doit nommer `proprietaire` dans la même instruction.
    """
    fichiers = fichiers_python_de_l_api()
    assert fichiers, "aucune source d'API trouvée sous src/ourouler/{api,web,serveur}"
    motif = re.compile(r"\b(SELECT|UPDATE|DELETE)\b(.{0,400}?)(?:;|\"\"\"|'''|\Z)", re.IGNORECASE | re.DOTALL)
    nues = []
    for fichier in fichiers:
        for verbe, corps in motif.findall(fichier.read_text(encoding="utf-8")):
            if "proprietaire" not in corps.lower():
                nues.append(f"{fichier.name}: {verbe} {corps.strip()[:60]}…")
    assert not nues, "requêtes SQL sans clause de propriétaire :\n  " + "\n  ".join(nues)
