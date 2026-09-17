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
from typing import get_args, get_type_hints

import pytest
from outils_api import (
    PROPRIETAIRE_A,
    PROPRIETAIRE_B,
    SOURCES,
    charger_application,
    client_api,
    config_d_essai,
    fichiers_python_de_l_api,
    noms_de_parametres,
    parametre_nomme,
    route_pour,
    routes,
    schema_openapi,
)

#: **Sans l'extra `api`, ce module se saute au lieu de casser la collecte.**
#: `uv sync && uv run pytest` sur un dépôt fraîchement cloné n'installe pas
#: FastAPI (extra `api`) : sans cette ligne, la construction de l'application
#: levait une erreur au lieu de laisser des tests ignorés.
#: (La garde est posée par module et non dans `conftest.py` : un `Skipped`
#: levé dans un conftest fait planter pytest au lieu d'ignorer le dossier.)
pytest.importorskip("fastapi", reason="extra « api » absent — uv sync --all-extras")


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


# Marque `xfail(strict=True)` posée par le testeur en aveugle avant que F1
# n'existe, retirée le 17/09/2026 à sa livraison. C'est `strict` qui l'a
# signalé : le test s'est mis à passer et la suite a échoué pour le dire,
# au lieu de laisser une marque périmée affirmer que rien ne marche.
def test_chaque_route_de_donnees_resout_un_proprietaire_cote_serveur():
    """Protège tous les écrans de F3, écrits pendant F1 parce que c'est gratuit maintenant.

    **Corrigé le 17/09/2026 — la clause vit côté serveur, pas dans la requête.**
    Ce test exigeait d'abord que chaque route **déclare** un propriétaire dans
    son schéma OpenAPI : un segment de chemin, un paramètre, un en-tête. C'est
    l'inverse de ce que dit la doctrine, et l'écart n'est pas de forme.

    `doctrine_architecture.md` §10.1 : « le propriétaire entre au constructeur
    du dépôt, et nulle part ailleurs […] **en hébergé, c'est la couche web qui
    construira le dépôt avec l'identifiant de l'utilisateur authentifié.** »
    Et §10.2 : « isolation […] vérifiée côté serveur à chaque requête, jamais
    seulement côté front ». La « clause de propriétaire » y désigne le
    `WHERE proprietaire = …` que le serveur impose, pas un champ que le client
    remplit. Un `?proprietaire=` dans le contrat publié serait le contraire de
    ce qu'on veut : tant que rien n'authentifie personne, un paramètre que
    n'importe qui peut écrire est une référence directe à l'objet d'autrui —
    la faille même que ce fichier prétend fermer. `api/proprietaire.resoudre()`
    le dit dans les mêmes termes : « rien dans la requête HTTP ne doit pouvoir
    désigner un autre propriétaire ».

    Ce que le test vérifie donc maintenant, et qui est plus fort : **toute**
    route résout un propriétaire côté serveur — sa fonction reçoit la
    dépendance qui l'établit — et **aucune** ne le laisse choisir au client.
    Aucune liste d'exceptions : la doctrine §10.1 note qu'« une liste
    d'exceptions se remplit toute seule », et une route de données oubliée
    dedans est exactement l'oubli qu'on paie en F3.
    """
    resolues, nues = [], []
    for chemin, fonction in _routes_servies(charger_application(config=config_d_essai())):
        if any(exclu in chemin.lower() for exclu in CHEMINS_SANS_PROPRIETAIRE):
            continue
        (resolues if _resout_un_proprietaire(fonction) else nues).append(chemin)
    assert resolues, "aucune route de données trouvée : le test ne mesure rien"
    assert not nues, (
        "routes qui ne résolvent aucun propriétaire :\n  "
        + "\n  ".join(sorted(set(nues)))
        + "\nChaque route doit recevoir la dépendance qui établit le propriétaire côté "
        "serveur (doctrine §10.1)."
    )


def test_aucune_route_ne_laisse_le_client_choisir_son_proprietaire():
    """L'autre moitié de la clause : le serveur la pose, le client ne la dicte pas.

    Séparé du test ci-dessus parce que c'est la propriété de sûreté, et
    qu'elle doit échouer toute seule si quelqu'un « facilite les tests » en
    ajoutant un `?proprietaire=`. Tant qu'il n'y a pas de comptes (F3), un tel
    paramètre serait une usurpation en un mot, offerte dans le contrat publié.
    """
    schema = schema_openapi(client_api(config=config_d_essai()))
    offertes = [
        f"{methode} {chemin} ({cle})"
        for chemin, methode, operation in routes(schema)
        if (cle := parametre_nomme(noms_de_parametres(schema, operation), *MOTS_PROPRIETAIRE))
    ]
    assert not offertes, (
        "le client peut désigner un propriétaire :\n  "
        + "\n  ".join(sorted(offertes))
        + "\nTant que rien n'authentifie personne, ce paramètre sert les données d'autrui à "
        "qui le devine. L'identité se résout côté serveur (api/proprietaire.resoudre)."
    )


def _routes_servies(objet, profondeur: int = 0) -> list[tuple[str, object]]:
    """[(chemin, fonction)] de toutes les routes, routeurs inclus imbriqués compris.

    Selon la version de FastAPI, `include_router` recopie les routes à plat
    dans `app.routes` ou y laisse un `_IncludedRouter` qui garde le routeur
    d'origine à côté : on descend dans les deux cas, sinon le test compterait
    zéro route et passerait en ne mesurant rien — d'où l'assertion `resolues`
    non vide dans l'appelant.
    """
    trouvees: list[tuple[str, object]] = []
    if profondeur > 4:
        return trouvees
    for route in getattr(objet, "routes", []) or []:
        fonction = getattr(route, "endpoint", None)
        if fonction is not None:
            trouvees.append((str(getattr(route, "path", "")), fonction))
            continue
        trouvees += _routes_servies(route, profondeur + 1)
        interne = getattr(route, "original_router", None)
        if interne is not None:
            trouvees += _routes_servies(interne, profondeur + 1)
    return trouvees


def _resout_un_proprietaire(fonction) -> bool:
    """Vrai si la fonction de route reçoit l'identité par une dépendance du serveur.

    On lit les annotations plutôt que les noms : c'est le **type** `Proprietaire`
    qui porte la garantie, et un paramètre qu'on renommerait resterait vu.
    """
    from ourouler.api.proprietaire import Proprietaire

    try:
        indices = get_type_hints(fonction, include_extras=True)
    except Exception:  # noqa: BLE001 — une annotation irrésoluble n'est pas une clause
        return False
    for annotation in indices.values():
        souches = [annotation, *get_args(annotation)]
        if any(souche is Proprietaire for souche in souches):
            return True
    return False


# Marque `xfail(strict=True)` posée par le testeur en aveugle avant que F1
# n'existe, retirée le 17/09/2026 à sa livraison. C'est `strict` qui l'a
# signalé : le test s'est mis à passer et la suite a échoué pour le dire,
# au lieu de laisser une marque périmée affirmer que rien ne marche.
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


# Marque `xfail(strict=True)` posée par le testeur en aveugle avant que F1
# n'existe, retirée le 17/09/2026 à sa livraison. C'est `strict` qui l'a
# signalé : le test s'est mis à passer et la suite a échoué pour le dire,
# au lieu de laisser une marque périmée affirmer que rien ne marche.
def test_une_ressource_d_un_proprietaire_n_est_pas_lisible_par_un_autre(tmp_path):
    """Protège E20 (« Télécharger le GPX ») et E21 (« Mes données »).

    Le fichier est servi par identifiant — c'est le point d'énumération
    classique. Demander la ressource de A en étant B doit être un échec, jamais
    un 200.

    **Corrigé le 17/09/2026 — on ne peut pas se présenter comme B sans ouvrir
    la porte qu'on teste.** La version d'origine exigeait un paramètre de
    requête nommant le propriétaire, pour appeler la même URL une fois en A et
    une fois en B. Ce paramètre ne peut pas exister avant F3 : sans
    authentification, il *serait* la faille (voir
    `test_aucune_route_ne_laisse_le_client_choisir_son_proprietaire`). Le test
    exigeait donc, pour prouver l'isolation, qu'on supprime l'isolation.

    Ce qui était protégé — un identifiant valable pour A ne rend rien à B —
    est vérifié ici **là où la règle est appliquée**, sur le dépôt, seul
    endroit où deux propriétaires distincts existent aujourd'hui. Et la partie
    HTTP qui reste vérifiable l'est aussi : un `?proprietaire=` glissé dans
    l'URL ne change pas qui est servi. Rien n'est retiré, tout est déplacé
    vers ce qui est réellement observable avant les comptes.
    """
    from ourouler.api.depots import DepotFichiers
    from ourouler.api.proprietaire import Proprietaire

    depot = DepotFichiers(tmp_path)
    a, b = Proprietaire(PROPRIETAIRE_A), Proprietaire(PROPRIETAIRE_B)
    fichier = depot.deposer(a, "parcours.gpx", b"<gpx/>")

    with pytest.raises(Exception) as refus:
        depot.trouver(b, fichier.identifiant)
    assert PROPRIETAIRE_A not in str(refus.value), (
        "le refus dit à B chez qui le fichier se trouve : l'échec ne doit pas renseigner"
    )
    assert depot.trouver(a, fichier.identifiant).chemin == fichier.chemin, (
        "le propriétaire lui-même ne retrouve plus son fichier : le test ne prouve rien"
    )

    # Et côté HTTP : le propriétaire ne se choisit pas dans l'URL.
    client = client_api(config=config_d_essai())
    schema = schema_openapi(client)
    chemin, methode, _ = route_pour(schema, "fichier", "gpx", "carte")
    chemin_concret = re.sub(r"\{[^}]+\}", fichier.identifiant, chemin)
    servie = client.requete(methode, chemin_concret, params={"proprietaire": PROPRIETAIRE_A})
    assert servie.status_code != 200, (
        f"{methode} {chemin} a servi le fichier de « {PROPRIETAIRE_A} » à qui a écrit son nom "
        "dans l'URL : le paramètre est pris au mot alors que rien n'authentifie personne"
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


# Marque `xfail(strict=True)` posée par le testeur en aveugle avant que F1
# n'existe, retirée le 17/09/2026 à sa livraison. C'est `strict` qui l'a
# signalé : le test s'est mis à passer et la suite a échoué pour le dire,
# au lieu de laisser une marque périmée affirmer que rien ne marche.
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
