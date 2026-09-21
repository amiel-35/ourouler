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

**Mis à jour le 18/09/2026 (lot L7.A).** Le fichier vérifiait la *forme* —
chaque route reçoit la dépendance, aucune ne laisse le client se nommer — et
c'était vrai pendant que `proprietaire()` rendait le mainteneur à n'importe
quel visiteur. Il vérifie maintenant aussi le *comportement*, et **route par
route** plutôt que par échantillon :

- sans session, chaque route de données répond 401 (`SessionHebergee`) ;
- deux cyclistes distincts ne voient jamais rien l'un de l'autre, contre le
  service réel, sur toutes les routes ;
- une route ajoutée sans clause de propriétaire, ou ajoutée sans entrer dans
  le balayage, fait échouer la suite — vérifié en le faisant.

Les trois listes qui pilotent tout cela sont `ROUTES_HORS_DONNEES` (les
dispenses, exactes et justifiées) et `_appels` (comment appeler chaque route
pour de vrai). Elles sont comparées à ce que l'application déclare : aucune
ne peut se périmer en silence.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import get_args, get_type_hints

import pytest
from outils_api import (
    PROPRIETAIRE_A,
    PROPRIETAIRE_B,
    SOURCES,
    ClientApi,
    charger_application,
    client_api,
    client_bouchon,
    client_brouter_ordinaire,
    client_meteo_ordinaire,
    client_seance_ordinaire,
    config_d_essai,
    fichiers_python_de_l_api,
    noms_de_parametres,
    parametre_nomme,
    route_pour,
    routes,
    schema_openapi,
    texte_entier,
    transports_du_depot,
)

#: **Sans l'extra `api`, ce module se saute au lieu de casser la collecte.**
#: `uv sync && uv run pytest` sur un dépôt fraîchement cloné n'installe pas
#: FastAPI (extra `api`) : sans cette ligne, la construction de l'application
#: levait une erreur au lieu de laisser des tests ignorés.
#: (La garde est posée par module et non dans `conftest.py` : un `Skipped`
#: levé dans un conftest fait planter pytest au lieu d'ignorer le dossier.)
#: Elle est **avant** les imports d'`ourouler.api` ci-dessous, qui n'ont de
#: sens que si le paquet est installable.
pytest.importorskip("fastapi", reason="extra « api » absent — uv sync --all-extras")

from ourouler.activites.cache import Cache  # noqa: E402
from ourouler.api.depots import SocleTOML  # noqa: E402
from ourouler.api.proprietaire import PROPRIETAIRE_LOCAL, Proprietaire  # noqa: E402

#: Importés **au niveau du module**, et pas dans les tests qui s'en servent :
#: `get_type_hints` résout les annotations dans les globales du module où la
#: fonction est définie. Les routes de contre-épreuve de
#: `test_une_route_sans_clause_de_proprietaire_est_bien_detectee` sont définies
#: ici ; avec un import local, `Ctx` et `Qui` seraient irrésolubles et le
#: détecteur déclarerait « sans clause » une route qui en a une.
from ourouler.api.routes import Ctx, Qui  # noqa: E402
from ourouler.api.session import (  # noqa: E402
    MODE_HEBERGE,
    MODE_PERSONNEL,
    SessionHebergee,
    SessionPersonnelle,
)
from ourouler.apprentissage.commande import NOM_BASE  # noqa: E402
from ourouler.apprentissage.routes import BaseRoutes  # noqa: E402
from ourouler.boucle.trace import PointTrace, Segment, Trace  # noqa: E402

#: Les noms acceptables pour la clause de propriétaire. On n'impose pas le mot :
#: on impose qu'il y en ait un, et qu'il soit déclaré dans le contrat.
MOTS_PROPRIETAIRE = ("proprietaire", "utilisateur", "profil_id", "compte", "owner")

#: Les routes qui n'ont légitimement pas de propriétaire, **nommées une par
#: une avec leur raison** (lot L7.A, 18/09/2026).
#:
#: C'était auparavant un tuple de fragments (`"/openapi"`, `"/docs"`,
#: `"/sante"`, `"/version"`…) comparés par `in` : un motif large, qui
#: dispensait d'avance des routes qui n'existent pas et qui aurait dispensé
#: `/api/v1/sante-du-cycliste` le jour où quelqu'un l'aurait écrite. Une liste
#: d'exceptions se remplit toute seule (doctrine §10.1) ; celle-ci est donc
#: **exacte**, courte, justifiée, et `test_la_liste_des_routes_hors_donnees_ne_ment_pas`
#: vérifie qu'elle ne contient rien d'inventé ni rien sous `/api/v1`.
#:
#: **`/systeme` et `/systeme/budgets` n'y sont pas**, alors que le contrat du
#: sprint les cite comme exemples plausibles. Ils résolvent un propriétaire
#: aujourd'hui et doivent continuer : `/systeme` rend les capacités **du
#: profil** (« Intervals est-il renseigné ? », la liste des vélos), qui sont
#: des données de cycliste ; et `budgets` le dit déjà en toutes lettres —
#: « dispenser la seule route qui n'en a pas besoin ouvrirait une liste
#: d'exceptions ». Les dispenser serait un recul, pas une simplification.
ROUTES_HORS_DONNEES: dict[str, str] = {
    "/openapi.json": "le contrat publié — une description de l'API, aucune donnée de cycliste",
    "/docs": "la page de documentation interactive de FastAPI, statique",
    "/docs/oauth2-redirect": "une page statique de FastAPI, servie avec /docs",
    "/redoc": "l'autre lecteur du même contrat, page statique",
    "/sante": (
        "la sonde de santé du paquetage (lot L7.E) — un orchestrateur qui "
        "l'interroge sans session ne doit pas croire le service mort ; "
        "hors /api/v1 précisément pour ne jamais entrer dans cette liste-ci "
        "sous ce préfixe, voir /systeme qui, lui, reste une route de données"
    ),
}

#: **Les quatre routes qui précèdent l'existence d'une session** (lot
#: L7.2-C, 19/09/2026) : `test_la_liste_des_routes_hors_donnees_ne_ment_pas`
#: interdit à raison toute route de `/api/v1` dans `ROUTES_HORS_DONNEES` —
#: « sous /api/v1, tout sert les données de quelqu'un » était vrai le
#: 18/09/2026, avant que ce lot n'ajoute des routes qui *fabriquent* ou
#: *détruisent* la session dont dépend cette phrase, au lieu de servir la
#: donnée d'un cycliste déjà identifié. Leur demander la clause de
#: `Qui` serait circulaire, exactement comme `TABLES_IDENTITE` l'est déjà pour
#: `comptes` et `invitations` côté SQL (même lot, même frontière).
#:
#: **Ce n'est PAS un blanc-seing « aucune fuite possible ».** La contre-épreuve
#: n'est pas ici mais par l'effet, à trois endroits :
#: `tests/comptes/test_comptes.py` (deux `entrer` concurrents sur le même
#: jeton n'ouvrent qu'une session, un jeton inconnu/expiré/consommé rend une
#: réponse indistinguable, un secret faux et un compte inexistant aussi, une
#: session détruite ou expirée rend `None`), `tests/comptes/test_routes_session.py`
#: (les mêmes propriétés rejouées contre le **service réel**, par HTTP), et
#: `test_les_routes_avant_session_ne_servent_jamais_les_donnees_d_un_proprietaire`
#: ci-dessous, qui vérifie qu'aucune des quatre ne peut recevoir `Qui` — donc
#: qu'aucune ne pourrait, même par erreur, se mettre à rendre le profil de
#: quelqu'un.
ROUTES_AVANT_SESSION: dict[str, str] = {
    "/api/v1/invitation": "l'état d'un jeton d'invitation, avant qu'aucun compte ne soit actif",
    "/api/v1/entrer": "active un compte et ouvre sa première session — aucun propriétaire "
    "n'est résolu avant cet appel, c'est lui qui le produit",
    "/api/v1/connexion": "ouvre une session sur un compte existant — le propriétaire n'est "
    "pas encore résolu au moment de l'appel, c'est lui qui le produit",
    "/api/v1/sortir": "détruit la session en cours — efface un cookie, ne lit aucune donnée",
}


def _est_une_route_de_donnees(chemin: str) -> bool:
    """Vrai si cette route doit porter la clause. Correspondance **exacte**."""
    return chemin not in ROUTES_HORS_DONNEES and chemin not in ROUTES_AVANT_SESSION


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
    la faille même que ce fichier prétend fermer. `api/routes.proprietaire()`
    le dit dans les mêmes termes : rien dans la requête HTTP ne doit pouvoir
    désigner un autre propriétaire — c'est le fournisseur de session qui
    tranche, jamais le client.

    Ce que le test vérifie donc maintenant, et qui est plus fort : **toute**
    route résout un propriétaire côté serveur — sa fonction reçoit la
    dépendance qui l'établit — et **aucune** ne le laisse choisir au client.
    Aucune liste d'exceptions : la doctrine §10.1 note qu'« une liste
    d'exceptions se remplit toute seule », et une route de données oubliée
    dedans est exactement l'oubli qu'on paie en F3.
    """
    resolues, nues = [], []
    for chemin, fonction in _routes_servies(charger_application(config=config_d_essai())):
        if not _est_une_route_de_donnees(chemin):
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
        "qui le devine. L'identité se résout côté serveur (api/session.py)."
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
        (c, m, o) for c, m, o in routes(schema) if _est_une_route_de_donnees(c)
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


def _invariants_du_depot():
    """`tests/test_invariants.py`, chargé par chemin (trois conftest.py coexistent)."""
    if "test_invariants" in sys.modules:
        return sys.modules["test_invariants"]
    chemin = Path(__file__).resolve().parents[1] / "test_invariants.py"
    spec = importlib.util.spec_from_file_location("test_invariants", chemin)
    module = importlib.util.module_from_spec(spec)
    sys.modules["test_invariants"] = module
    spec.loader.exec_module(module)
    return module


#: Les tables d'identité et d'accès, qui **précèdent** le propriétaire au lieu
#: de lui appartenir (doctrine §10.2, [[Q46]], lot L7.2-A). Un compte se crée
#: avant que son propriétaire existe : lui demander une colonne `proprietaire`
#: reviendrait à dire que l'identité appartient à la clé pseudonyme dont elle
#: est justement séparée. **`sessions` les rejoint le 19/09/2026 (lot L7.2-C)**,
#: même raison : une session est retrouvée pour produire un propriétaire, elle
#: n'en appartient à aucun.
#:
#: La même liste vit dans `tests/test_invariants.py`, et un test ci-dessous
#: échoue si les deux divergent : une exception qui n'existe qu'à un endroit
#: est une exception qu'on oublie de justifier au second.
TABLES_IDENTITE = ("comptes", "invitations", "sessions", "migrations")

#: Le motif qui repère une instruction SQL de données dans un texte.
#:
#: Une seule exclusion ici, payée par un faux positif rencontré : `(?!\()`
#: écarte `@routeur.delete("/moi")`, un appel Python (lot L7.B). Une vraie
#: instruction SQL a toujours une espace après son verbe.
MOTIF_SQL = re.compile(
    r"\b(SELECT|UPDATE|DELETE)\b(?!\()(.{0,400}?)(?:;|\Z)", re.IGNORECASE | re.DOTALL
)

#: Ce qu'une clé étrangère promet quand la ligne visée bouge. Ce n'est **pas**
#: une instruction : `REFERENCES comptes (id) ON DELETE CASCADE` décrit ce que
#: la base fera, elle n'efface rien par elle-même. Ces phrases sont retirées du
#: texte avant de le lire.
#:
#: Écrit en toutes lettres depuis le 18/09/2026 : le motif disait auparavant
#: `(?<!ON )` devant le verbe, ce qui aurait aussi bien silencé un vrai
#: `DELETE` précédé de n'importe quel « ON » — la fin d'un `JOIN … ON`, par
#: exemple. Une exclusion doit nommer ce qu'elle exclut.
ACTION_REFERENTIELLE = re.compile(
    r"\bON\s+(?:DELETE|UPDATE)\s+"
    r"(?:CASCADE|RESTRICT|SET\s+NULL|SET\s+DEFAULT|NO\s+ACTION)\b",
    re.IGNORECASE,
)


def _texte_a_lire(texte: str) -> str:
    """Le texte débarrassé de ce qui n'est pas une instruction.

    Deux retraits, et l'ordre compte peu : les **commentaires SQL** (`--`,
    `/* */`), parce qu'un commentaire est de la prose et qu'un
    « `SELECT * FROM activites -- pose avec les migrations` » se dispensait de
    la clause par le seul mot posé après le tiret ; et les **actions
    référentielles**, qui décrivent au lieu d'agir.
    """
    return ACTION_REFERENTIELLE.sub(" ", _invariants_du_depot().sans_commentaires_sql(texte))


def _dispensee(verbe: str, corps: str) -> bool:
    """Vrai si cette instruction n'adresse que des tables d'identité.

    **Par table réellement adressée, jamais par mention du mot** (corrigé le
    18/09/2026 sur relecture adverse). Écrite par mention, la dispense
    blanchissait `SELECT a.trace FROM activites a JOIN comptes c …` : une
    jointure qui lit bel et bien une table de données, et que la première
    branche des comptes sur les données écrira naturellement. Le détail de la
    lecture des tables, et de son échec du bon côté, est dans
    `tests/test_invariants.py` (`dispensee_par_ses_tables`).
    """
    return _invariants_du_depot().dispensee_par_ses_tables(f"{verbe} {corps}", TABLES_IDENTITE)


def _tables_declarees() -> list[tuple[Path, str, str]]:
    """[(fichier, nom de table, corps du CREATE TABLE)] dans tout `src/ourouler/`.

    **Les fichiers `.sql` comptent autant que les `.py`** (ajouté le
    18/09/2026, lot L7.2-A). Avant, ce test ne regardait que les sources
    Python : sortir le schéma dans `api/migrations/*.sql` — ce que la doctrine
    §10.2 demande pour l'hébergé — l'aurait fait passer sur une base dont il
    n'aurait plus vu une seule table. Un invariant qu'un changement de format
    de fichier désarme ne garde rien.
    """
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
    for fichier in sorted(SOURCES.rglob("*.sql")):
        texte = fichier.read_text(encoding="utf-8")
        # **Le découpage est naïf, et il l'assume à voix haute.** Un `;` posé
        # dans un littéral, ou un corps de fonction `$$ … $$`, couperait une
        # instruction en morceaux dont aucun ne ressemblerait plus à un
        # `CREATE TABLE` — et ce test deviendrait aveugle *sans bruit*, ce qui
        # est la pire façon pour un invariant de cesser de garder. Tant qu'il
        # n'y a pas de raison d'écrire un vrai analyseur, on refuse d'avance le
        # seul cas qui se voit : le jour où une migration porte un `$$`, ce
        # test échoue et demande qu'on choisisse.
        assert "$$" not in texte, (
            f"{fichier.name} porte « $$ » : le découpage sur « ; » ci-dessous ne sait pas "
            "le lire, et ce test cesserait de voir les tables sans le dire"
        )
        # Découpé instruction par instruction : sans ça, le `.*?` non gourmand
        # s'arrête à la première parenthèse fermante d'une contrainte et le
        # corps de la table est tronqué.
        for instruction in texte.split(";"):
            for nom, corps in motif.findall(instruction + ";"):
                trouvees.append((fichier, nom, corps))
    return trouvees


def test_les_migrations_sql_entrent_bien_dans_le_champ_du_controle():
    """Contre-épreuve du point ci-dessus : les tables du `.sql` sont bien vues.

    Sans elle, l'extension de `_tables_declarees` aux `.sql` pourrait être
    silencieusement fausse (mauvaise expression régulière, mauvais motif de
    fichiers) et le test suivant continuerait de passer sur les seules tables
    Python, sans que rien ne le dise.
    """
    par_table = {nom: fichier.suffix for fichier, nom, _ in _tables_declarees()}
    for attendue in ("comptes", "invitations", "comptes_proprietaires"):
        assert par_table.get(attendue) == ".sql", par_table


def test_les_deux_listes_de_tables_d_identite_ne_divergent_pas():
    """La même exception, écrite deux fois, doit dire la même chose.

    `tests/test_invariants.py` dispense `comptes` et `invitations` de la
    **clause** SQL ; ce fichier-ci les dispense de la **colonne**. `migrations`
    n'apparaît pas là-bas parce que l'exemption `_migrer`, plus ancienne, la
    couvre déjà — d'où une comparaison qui exige l'inclusion dans un sens et
    nomme l'unique écart toléré dans l'autre.
    """
    ailleurs = set(_invariants_du_depot().TABLES_IDENTITE)
    ici = set(TABLES_IDENTITE)
    assert ailleurs <= ici, f"exemptée dans test_invariants.py mais pas ici : {ailleurs - ici}"
    assert ici - ailleurs == {"migrations"}, (
        f"une table est exemptée ici sans l'être dans test_invariants.py : {ici - ailleurs}"
    )


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

    **Les tables d'identité en sont dispensées** depuis le 18/09/2026, et
    nommément : voir `TABLES_IDENTITE`. Un compte n'appartient pas à un
    propriétaire, il en **désigne** un ; `comptes_proprietaires`, qui fait le
    lien, porte la colonne comme les autres et n'est pas dispensée.
    """
    sans = [
        f"{fichier.relative_to(SOURCES)}:{nom}"
        for fichier, nom, corps in _tables_declarees()
        if "proprietaire" not in corps.lower() and nom.lower() not in TABLES_IDENTITE
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

    **`(?!\\()` après le verbe (L7.B)** : sans lui, `@routeur.delete("/moi")` —
    un appel Python, `DELETE` immédiatement suivi d'une parenthèse — se lisait
    comme une requête SQL nue. Une vraie instruction SQL a toujours un espace
    après son verbe (`DELETE FROM …`), jamais une parenthèse ouvrante.

    **Deux corrections du 18/09/2026 (lot L7.2-A), quand l'API a eu son
    premier vrai SQL.** Jusque-là elle n'en avait aucun, et la grossièreté du
    procédé ne coûtait rien :

    1. le motif était appliqué au **texte brut** du fichier, donc aux
       docstrings : la phrase « un `UPDATE … WHERE … AND consomme_le IS NULL`,
       jamais un `SELECT` suivi d'un `UPDATE` » — qui explique précisément
       comment on évite la faute — était comptée comme la faute. Un invariant
       qui punit sa propre documentation se fait désarmer par la première
       personne pressée. Il ne lit désormais que les chaînes **exécutées**,
       docstrings exclues, et le contenu des `.sql` ;
    2. les tables d'identité sont dispensées, nommément (`TABLES_IDENTITE`),
       pour la raison écrite avec la constante.

    **Troisième correction, le soir même, sur relecture adverse** : cette
    dispense était écrite « par mention du mot » et blanchissait donc une
    requête qui touche **à la fois** une table d'identité et une table de
    données. Elle porte désormais sur les tables réellement adressées
    (`_dispensee`), et les commentaires SQL partent avant la lecture
    (`_texte_a_lire`).
    """
    fichiers = fichiers_python_de_l_api()
    assert fichiers, "aucune source d'API trouvée sous src/ourouler/{api,web,serveur}"
    nues = []
    for origine, texte in _sql_execute_par_l_api(fichiers):
        for verbe, corps in MOTIF_SQL.findall(_texte_a_lire(texte)):
            if "proprietaire" in corps.lower() or _dispensee(verbe, corps):
                continue
            nues.append(f"{origine}: {verbe} {corps.strip()[:60]}…")
    assert not nues, "requêtes SQL sans clause de propriétaire :\n  " + "\n  ".join(nues)


def _sql_execute_par_l_api(
    fichiers: list[Path], migrations: list[Path] | None = None
) -> list[tuple[str, str]]:
    """[(origine, texte)] : les chaînes de code de l'API, et ses migrations `.sql`.

    « Chaîne de code » veut dire : littéral de chaîne qui n'est pas une
    docstring. C'est volontairement plus large que « ce qui arrive dans un
    `execute` » — le procédé reste grossier, et c'est sa force : une requête
    assemblée par un détour tortueux reste vue. Ce qu'il ne voit plus, c'est la
    prose.

    Le découpage lui-même est **emprunté** à `tests/test_invariants.py`
    (`chaines_de_code`) depuis le 18/09/2026 : il y en avait ici une copie mot
    pour mot, et deux copies finissent toujours par diverger.
    """
    chaines_de_code = _invariants_du_depot().chaines_de_code
    morceaux: list[tuple[str, str]] = [
        (fichier.name, chaine) for fichier in fichiers for chaine in chaines_de_code(fichier)
    ]
    if migrations is None:
        migrations = sorted(SOURCES.rglob("*.sql"))
    morceaux += [(fichier.name, fichier.read_text(encoding="utf-8")) for fichier in migrations]
    return morceaux


def test_l_invariant_sql_de_l_api_voit_encore_une_requete_nue(tmp_path: Path):
    """Contre-épreuve des corrections ci-dessus : il ne doit pas être devenu aveugle.

    On lui donne les cas qui comptent : la prose (tolérée), une requête sur une
    table d'identité (tolérée), une clé étrangère `ON DELETE CASCADE`
    (tolérée : elle décrit, elle n'efface pas), une requête correcte (tolérée),
    une jointure correctement filtrée (tolérée) — et, **refusées**, une lecture
    nue d'une table de données ainsi que les trois formes que la relecture
    adverse du 18/09/2026 a trouvées silencieusement dispensées :

    - `jointure` : une table de données jointe à une table d'identité ;
    - `sous_requete` : un `DELETE` sur une table de données dont seule la
      sous-requête touche une table d'identité ;
    - `commentaire` : un `SELECT` nu suivi d'un commentaire qui prononce le mot
      « migrations ».

    Et, dans l'autre sens, une **migration dont la prose parle de SQL** : elle
    ne doit rien produire du tout, sinon la seule façon de faire taire
    l'invariant serait d'effacer l'explication.

    Une contre-épreuve qui ne teste que les cas auxquels l'auteur a pensé ne
    prouve rien : c'est la leçon que ce dépôt a déjà payée ([[Q58]]).
    """
    faute = tmp_path / "essai.py"
    faute.write_text(
        '"""On évite un SELECT nu sur activites en nommant la clause."""\n'
        "def identite(cx):\n"
        '    cx.execute("SELECT id FROM comptes WHERE lower(email) = %s", ("a",))\n'
        "def schema(cx):\n"
        '    cx.execute("CREATE TABLE t (c TEXT REFERENCES autre (id) ON DELETE CASCADE)")\n'
        "def correcte(cx):\n"
        '    cx.execute("SELECT a FROM activites WHERE proprietaire = %s", ("a",))\n'
        "def jointure_correcte(cx):\n"
        '    cx.execute("SELECT a.trace FROM activites a JOIN comptes c ON c.id = a.compte "\n'
        '               "WHERE a.proprietaire = %s", ("a",))\n'
        "def nue(cx):\n"
        '    cx.execute("SELECT a FROM activites WHERE debut > %s", (1,))\n'
        "def jointure(cx):\n"
        '    cx.execute("SELECT a.trace FROM activites a JOIN comptes c ON c.id = a.compte")\n'
        "def sous_requete(cx):\n"
        '    cx.execute("DELETE FROM routes_connues WHERE compte IN (SELECT id FROM comptes)")\n'
        "def commentaire(cx):\n"
        '    cx.execute("SELECT * FROM activites -- pose avec les migrations")\n',
        encoding="utf-8",
    )
    # Et une migration dont la **prose** parle de SQL, comme le fait
    # `0001_comptes.sql`. Elle ne doit produire aucune ligne : un commentaire
    # n'est pas une requête. Sans le retrait des commentaires, ce fichier-ci
    # ferait apparaître une faute qui n'existe pas — et l'invariant se ferait
    # désarmer par la première personne pressée d'effacer l'explication.
    migration = tmp_path / "0001_essai.sql"
    migration.write_text(
        "-- On n'écrit jamais un SELECT a FROM activites sans clause.\n"
        "CREATE TABLE t (c TEXT REFERENCES autre (id) ON DELETE CASCADE);\n",
        encoding="utf-8",
    )
    vues = [
        " ".join(corps.split())
        for _, texte in _sql_execute_par_l_api([faute], migrations=[migration])
        for verbe, corps in MOTIF_SQL.findall(_texte_a_lire(texte))
        if "proprietaire" not in corps.lower() and not _dispensee(verbe, corps)
    ]
    assert vues == [
        "a FROM activites WHERE debut > %s",
        "a.trace FROM activites a JOIN comptes c ON c.id = a.compte",
        "FROM routes_connues WHERE compte IN (SELECT id FROM comptes)",
        "* FROM activites",
    ], vues


# =============================================================================
# L7.A — la session, et l'isolation prouvée route par route
# =============================================================================
#
# Ce qui précède vérifie la **forme** : chaque route reçoit la dépendance, et
# aucune ne laisse le client nommer son propriétaire. C'était déjà vrai le
# 17/09 et ça ne suffisait pas : `proprietaire()` rendait le mainteneur à
# n'importe qui. Ce qui suit vérifie le **comportement**, contre le service
# réel — sans session, 401 ; avec deux sessions, aucune fuite — et le fait
# **route par route**, pas par échantillon.


#: La sentinelle plantée chez A. Un jeton inventé, reconnaissable dans
#: n'importe quelle réponse, et qui n'est la donnée personnelle de personne
#: (règle absolue 1) : ni nom réel, ni adresse, ni coordonnée française.
MARQUE_A = "sentinelle-a-7k2"

#: La même chez B, pour que la contre-épreuve soit symétrique.
MARQUE_B = "sentinelle-b-3v9"

#: La sentinelle du **propriétaire local** : ce qu'un serveur hébergé trouve
#: déjà dans son cache, c'est-à-dire les sorties du mainteneur. Aucune session
#: ne doit jamais en voir la moindre trace (Q58).
#:
#: Inventée comme les deux autres (règle absolue 1) : ni nom réel, ni adresse,
#: ni coordonnée française.
MARQUE_LOCALE = "sentinelle-locale-8p5"

#: Le jour des semis locaux. Postérieur à `historique_depuis` par défaut
#: (1ᵉʳ décembre 2023, règle 6 de CLAUDE.md), sans quoi l'inventaire les
#: écarterait et le balayage ne mesurerait rien. Un mercredi quelconque.
JOUR_LOCAL = date(2024, 6, 5)


@dataclass(frozen=True)
class SessionDEssai:
    """Un fournisseur de session **de test**, injecté par le seul chemin prévu.

    **Pourquoi ceci ne rouvre pas la porte que ce fichier ferme.** Un en-tête
    qui désigne le propriétaire serait une usurpation en un mot — c'est
    exactement ce que `test_aucune_route_ne_laisse_le_client_choisir_son_proprietaire`
    interdit. La différence n'est pas de degré :

    - ce fournisseur n'existe **que dans les tests** ; aucun module de
      `src/ourouler/` ne le nomme, et `exploitation.fournisseur_session` ne
      sait en construire que deux, `SessionPersonnelle` et `SessionHebergee` ;
    - l'en-tête n'apparaît **pas dans le schéma publié**, parce qu'il n'est
      lu par aucune route : il est lu par le fournisseur, en amont. Le test
      du contrat publié reste donc entier et continue de mordre.

    C'est précisément ce à quoi sert l'interface : pouvoir présenter deux
    cyclistes distincts au **vrai** service, sans que le vrai service apprenne
    à en distinguer deux tout seul avant que le mainteneur ait tranché la
    méthode d'authentification.
    """

    entete: str = "x-essai-proprietaire"
    mode = MODE_HEBERGE

    def ouvrir(self, requete: object) -> Proprietaire | None:
        valeur = requete.headers.get(self.entete)
        return Proprietaire(valeur) if valeur else None


def _routes_de_donnees(application: object) -> set[tuple[str, str]]:
    """{(méthode, gabarit)} de toutes les routes qui doivent porter la clause.

    `HEAD` et `OPTIONS` sont écartés : ils sont ajoutés par le cadre web à
    côté du `GET` qu'on teste déjà, et les compter doublerait le tableau
    d'appels sans rien prouver de plus.
    """
    trouvees: set[tuple[str, str]] = set()
    for route in _toutes_les_routes(application):
        chemin = str(getattr(route, "path", ""))
        if not _est_une_route_de_donnees(chemin):
            continue
        for methode in sorted(getattr(route, "methods", None) or ()):
            if methode in ("HEAD", "OPTIONS"):
                continue
            trouvees.add((methode, chemin))
    return trouvees


def _toutes_les_routes(objet: object, profondeur: int = 0) -> list[object]:
    """Les objets de route eux-mêmes — même descente que `_routes_servies`."""
    trouvees: list[object] = []
    if profondeur > 4:
        return trouvees
    for route in getattr(objet, "routes", []) or []:
        if getattr(route, "endpoint", None) is not None:
            trouvees.append(route)
            continue
        trouvees += _toutes_les_routes(route, profondeur + 1)
        interne = getattr(route, "original_router", None)
        if interne is not None:
            trouvees += _toutes_les_routes(interne, profondeur + 1)
    return trouvees


#: Le préfixe sous lequel vit tout ce qui sert un cycliste.
PREFIXE_API = "/api/v1"


def _concret(gabarit: str) -> str:
    """Un gabarit (`/fichiers/{identifiant}`) devient une URL appelable.

    La valeur mise à la place n'a pas à exister : pour le balayage des 401,
    ce qui compte est que la requête **atteigne** la route, pas qu'elle
    trouve quelque chose.
    """
    return re.sub(r"\{[^}]+\}", "1", gabarit)


def _corps(reponse) -> dict:
    """Le JSON d'une réponse, ou `{}` quand ce n'en est pas (un GPX, une page)."""
    try:
        charge = reponse.json()
    except ValueError:
        return {}
    return charge if isinstance(charge, dict) else {}


def _toml_d_essai(tmp_path: Path) -> str:
    """Un fichier de configuration entièrement inventé (règle absolue 1).

    Départ au large du golfe de Guinée, à quelques centaines de mètres du
    point (0, 0) : aucune coordonnée française, aucun lieu réel, et rien qui
    ressemble au départ du mainteneur.
    """
    return (
        "[depart]\n"
        f'nom = "{DEPART_D_ESSAI["nom"]}"\n'
        f'latitude = {DEPART_D_ESSAI["latitude"]}\n'
        f'longitude = {DEPART_D_ESSAI["longitude"]}\n'
        "\n[cycliste]\nmasse_kg = 70.0\nftp_w = 200\n"
        '\n[[velos]]\nnom = "Essai"\nusage = "route"\nmasse_kg = 9.0\ncda_m2 = 0.3\n'
        # Le moteur de tracé et la vitesse de la boucle sont de
        # l'infrastructure : ils appartiennent au service, pas à un cycliste,
        # et c'est bien le fond commun qu'un socle sans propriétaire
        # représente. Le serveur n'existe pas (`.invalid`) et tous les appels
        # sont bouchonnés — aucun réseau (règle absolue 3).
        '\n[brouter]\nurl = "http://brouter.essai.invalid"\nprofil = "fastbike"\ntimeout_s = 5.0\n'
        "\n[boucle]\nvitesse_moyenne_kmh = 27.0\ncandidates = 2\n"
        f'\n[cache]\ndossier = "{tmp_path / "cache"}"\n'
    )


#: Le départ synthétique, repris tel quel du socle de test.
DEPART_D_ESSAI = {"nom": "Départ d'essai", "latitude": 0.0009, "longitude": 0.0004}


def _service_pour_deux(tmp_path: Path) -> ClientApi:
    """Le **vrai** service, monté une fois, capable de distinguer deux cyclistes.

    Les cinq connecteurs sont les bouchons ordinaires du dépôt (règle
    absolue 3, aucun réseau) ; tout le reste — routes, dépôts, cœur — est le
    code de production. C'est le point de la formule « contre le service réel
    et pas un bouchon » : ce qu'on remplace est ce qui sortirait de la
    machine, pas ce qu'on prétend tester.

    Le socle vient d'un **fichier** et non d'une `Config` injectée : une
    configuration injectée est servie en lecture seule (`SocleFixe`), et
    `PATCH /profil` — la principale écriture du produit, donc la principale
    occasion de fuite — serait hors de l'épreuve.

    Et ce socle **n'appartient à personne** (`proprietaire=None`), ce qui est
    la forme hébergée : un fond commun — la vitesse de la boucle, l'URL du
    moteur de tracé — sur lequel chaque cycliste pose son profil. Le défaut,
    `PROPRIETAIRE_LOCAL`, est l'inverse et c'est voulu : un TOML de serveur
    porte d'ordinaire le départ et la clé Intervals de quelqu'un, et
    `DepotProfils` refuse alors de le servir à un autre. Le TOML écrit ici ne
    porte ni clé ni lieu réel (règle absolue 1), donc rien à protéger — et
    c'est justement ce refus-là que le test précédent a rencontré, ce qui
    montre qu'il fonctionne.
    """
    return _monter(tmp_path, SessionDEssai())


def _monter(tmp_path: Path, session: object) -> ClientApi:
    """Le service réel, sur le socle et le cache de `tmp_path`, avec ce fournisseur.

    Extrait de `_service_pour_deux` le 18/09/2026 (lot Q58) pour que la
    contre-épreuve du balayage des données locales puisse monter **le même
    service** en mode personnel : sans cela, elle aurait vérifié la visibilité
    des sentinelles sur autre chose que ce qu'elle éprouve.
    """
    chemin = tmp_path / "config.toml"
    chemin.write_text(_toml_d_essai(tmp_path), encoding="utf-8")
    return ClientApi(
        charger_application(
            socle=SocleTOML(chemin, proprietaire=None),
            dossier_donnees=tmp_path / "donnees",
            session=session,
            client_brouter=client_brouter_ordinaire(),
            client_meteo=client_meteo_ordinaire(),
            client_intervals=client_seance_ordinaire(),
            # La BAN et Nominatim d'un coup : un géocodeur qui **répond** et
            # ne trouve rien. Sans lui, `/geocodage` sortait sur le réseau et
            # la garde de `conftest.py` l'a refusé — règle absolue 3, et la
            # preuve au passage qu'elle sert.
            client_geocodage=client_bouchon(200, {"features": []}),
        )
    )


def _zwo(nom: str) -> bytes:
    """Un `.ZWO` minimal et valide, dont le nom porte la sentinelle."""
    return (
        "<?xml version='1.0'?>\n<workout_file>\n"
        f"<name>{nom}</name>\n<description>Fabriquée pour les tests</description>\n"
        '<workout><SteadyState Duration="600" Power="0.7"/></workout>\n'
        "</workout_file>\n"
    ).encode()


def _gpx(marque: str) -> bytes:
    """Un GPX minimal et horodaté, au large du golfe de Guinée (règle absolue 1)."""
    points = "\n".join(
        f'<trkpt lat="{0.0009 + i * 0.0009:.4f}" lon="0.0004">'
        f"<time>{JOUR_LOCAL.isoformat()}T08:{i:02d}:00Z</time></trkpt>"
        for i in range(6)
    )
    return (
        "<?xml version='1.0'?>\n"
        '<gpx version="1.1" creator="essai">\n'
        f"<trk><name>{marque}</name><trkseg>\n{points}\n</trkseg></trk>\n</gpx>\n"
    ).encode()


def _trace_taguee(classe: str) -> Trace:
    """Un quadrillage autour du départ d'essai, dont la classe de route est `classe`.

    Deux effets recherchés, d'un seul semis :

    * la classe ressort **telle quelle** dans `par_highway[].classe` de
      `GET /routes/stats` — c'est une chaîne choisie par celui qui a roulé,
      donc une sentinelle lisible dans la réponse ;
    * le quadrillage couvre les mailles que les boucles du BRouter bouchonné
      traversent, donc la part « déjà connue » d'une boucle y est non nulle.
      Sans cela, la fuite de `part_connue` — que les sentinelles textuelles ne
      peuvent pas voir, puisque c'est un nombre — resterait invisible.

    ±0,054° ≈ ±6 km autour de (0, 0), soit largement de quoi contenir une
    boucle de 30 km ; aucune coordonnée française (règle absolue 1).
    """
    pas = 0.0009  # ~100 m
    points = [
        PointTrace(lat=i * pas, lon=j * pas, alt_m=None, dist_m=100.0 * (abs(i) + abs(j)))
        for i in range(-60, 60)
        for j in range(-6, 6)
    ]
    segments = [Segment(k, k + 1, 100.0, {"highway": classe}) for k in range(len(points) - 1)]
    return Trace(
        nom=classe,
        points=points,
        segments=segments,
        distance_m=100.0 * (len(points) - 1),
        denivele_m=None,
        temps_moteur_s=None,
    )


def _semer_chez_le_proprietaire_local(dossier_cache: Path) -> None:
    """Plante les sentinelles du mainteneur **dans ses dépôts**, sous la peau.

    C'est le seul semis du fichier qui ne passe pas par l'API, et c'est faute
    de route : l'index des activités se remplit par `ourouler inventaire
    --importer/--synchroniser` et la base des routes par `ourouler routes
    apprendre`, trois gestes de ligne de commande que l'API n'expose
    délibérément pas (voir `api/routes.py`). Exiger un semis « par le
    produit » reviendrait donc à ne jamais éprouver ces deux lectures-là —
    et c'est exactement par elles que Q58 est entrée.

    **Le propriétaire n'est pas nommé, et c'est le sujet** : les deux dépôts
    sont construits avec leur défaut, `PROPRIETAIRE_LOCAL`. C'est ce qu'un
    serveur hébergé trouve dans son cache dès que le mainteneur a roulé sur la
    même machine — et ce que `GET /inventaire` et `GET /routes/{action}`
    servaient à tout le monde jusqu'au 18/09/2026.
    """
    cache = Cache(dossier_cache)
    cache.ajouter(
        _gpx(MARQUE_LOCALE),
        source="fichier",
        id_externe=f"{MARQUE_LOCALE}.gpx",
        extension="gpx",
        # `power_meter` ressort tel quel dans `par_velo[].capteurs` de
        # l'inventaire : le nom que le cycliste a donné à son capteur.
        meta={"sport": "Ride", "power_meter": MARQUE_LOCALE},
    )
    BaseRoutes(dossier_cache / NOM_BASE).ajouter_trace(
        _trace_taguee(MARQUE_LOCALE), jour=JOUR_LOCAL, id_sortie=MARQUE_LOCALE
    )


#: Les deux routes que le semis local rend observables, et par lesquelles la
#: contre-épreuve passe. Elles ne sont pas une liste d'exceptions : le balayage
#: ci-dessous, lui, porte sur **toutes** les routes de `_appels`.
ROUTES_DU_SEMIS_LOCAL = (f"{PREFIXE_API}/inventaire", f"{PREFIXE_API}/routes/stats")


def _completer_profil_local(local: ClientApi) -> None:
    """Le propriétaire local écrit son propre tiers 3 (Q35), comme tout autre profil.

    Le socle de `_toml_d_essai` n'appartient à personne (`proprietaire=None`) :
    même le propriétaire local, qui monte ici sa propre session
    (`SessionPersonnelle`), n'hérite plus de son départ ni de son cycliste
    depuis ce socle partagé — il doit désormais les écrire, exactement comme
    A et B le font par `_planter`. Sans cet appel, les routes qui calculent
    (`POST /boucles`) échoueraient sur un profil incomplet, ce qui est le
    comportement voulu (Q35) mais pas ce que ces deux tests-ci éprouvent.
    """
    reponse = local.requete(
        "PATCH",
        f"{PREFIXE_API}/profil",
        json={"depart": DEPART_D_ESSAI, "cycliste": {"masse_kg": 70.0}},
    )
    assert reponse.status_code == 200, (
        f"le propriétaire local n'a pas pu écrire son profil : {reponse.text[:300]}"
    )


def test_aucune_session_ne_voit_les_donnees_du_proprietaire_local(tmp_path):
    """**Q58 : le balayage vérifiait une forme, il vérifie ici un effet.**

    `GET /inventaire` et `GET /routes/{action}` recevaient bien `qui: Qui` —
    donc le détecteur de clause les déclarait conformes — mais appelaient des
    commandes de ligne de commande qui construisent leurs dépôts avec le
    défaut `PROPRIETAIRE_LOCAL`. Quel que soit le demandeur, elles servaient
    les données du mainteneur.

    Ce que les sentinelles de A et de B ne pouvaient pas voir : elles sont
    plantées **par l'API**, donc sous l'identité de A ou de B, et ces deux
    routes ne lisaient ni l'une ni l'autre — elles lisaient une troisième
    identité que personne n'incarnait. D'où cette sentinelle-ci, plantée chez
    le propriétaire local, qui est précisément celle qui fuyait.

    Le balayage porte sur **toutes** les routes, pas sur les deux connues :
    une route qui retomberait demain sur le propriétaire local par un autre
    chemin serait attrapée ici sans que personne y pense.
    """
    dossier_cache = tmp_path / "cache"
    client = _service_pour_deux(tmp_path)
    _semer_chez_le_proprietaire_local(dossier_cache)

    # **Contre-épreuve d'abord**, et sur le même service : les sentinelles
    # sont bien lisibles par le propriétaire local, par les routes mêmes qu'on
    # va éprouver. Sans elle, un semis qui n'aurait pas pris rendrait tout ce
    # qui suit vert sans rien mesurer — le mode d'échec ordinaire de ce genre
    # de balayage, et celui qui a déjà frappé ce fichier le 18/09/2026.
    local = _monter(tmp_path, SessionPersonnelle())
    _completer_profil_local(local)
    muettes = sorted(
        chemin for chemin in ROUTES_DU_SEMIS_LOCAL if MARQUE_LOCALE not in local.get(chemin).text
    )
    assert not muettes, (
        f"le propriétaire local ne voit pas ses propres données sur {muettes} : le semis "
        "n'a pas pris, ou ces routes ont cessé de servir le mainteneur sur sa machine — "
        "dans les deux cas le balayage ci-dessous ne prouverait rien."
    )

    # Et maintenant deux sessions, dont aucune n'est le propriétaire local.
    # Les identifiants sont inventés : ces routes-là répondront 404, ce qui
    # n'empêche pas de lire leur réponse — on ne cherche qu'une chaîne.
    ids = {"generation": "inexistante", "gpx": "inexistant", "fichier": "inexistant"}
    fuites = [
        f"{route} montre les données du propriétaire local à « {qui} »"
        for qui in (PROPRIETAIRE_A, PROPRIETAIRE_B)
        for route, texte in _balayer(client, qui, ids).items()
        if MARQUE_LOCALE in texte
    ]
    assert not fuites, (
        "fuites du propriétaire local vers une session :\n  "
        + "\n  ".join(sorted(fuites))
        + "\nCes routes portent la clause de propriétaire sans l'honorer jusqu'au dépôt "
        "(Q58). Doctrine §10.1 : « le propriétaire entre au constructeur du dépôt, et "
        "nulle part ailleurs »."
    )


def test_une_boucle_n_est_jamais_deja_connue_pour_qui_n_a_rien_roule(tmp_path):
    """La même fuite, sous une forme que le balayage textuel ne peut pas voir.

    `POST /boucles` et `POST /sorties` rendent `part_connue` — la part du
    tracé que le cycliste a déjà roulée — et la calculaient contre la base du
    **propriétaire local**. Ce n'est pas une chaîne, c'est un nombre : aucune
    sentinelle ne pouvait l'attraper, et c'est pour ça que ce test-ci existe à
    côté du balayage plutôt que dedans.

    Ce que le nombre disait : « 2,7 % de cette boucle, vous la connaissez
    déjà » à quelqu'un qui n'a jamais rien enregistré — donc quelque chose des
    endroits où le mainteneur roule. Mesuré le 18/09/2026 avant correction.

    La contre-épreuve est le premier volet : sur le même service, le
    propriétaire local voit bien une part non nulle. Sans elle, une base mal
    semée rendrait le second volet vert en ne mesurant rien.
    """
    client = _service_pour_deux(tmp_path)
    _semer_chez_le_proprietaire_local(tmp_path / "cache")
    demande = {"json": {"distance_km": 30.0, "candidates": 1}}

    local = _monter(tmp_path, SessionPersonnelle())
    _completer_profil_local(local)
    part_locale = _part_connue(local.post(f"{PREFIXE_API}/boucles", **demande))
    assert part_locale, (
        f"le propriétaire local ne reconnaît rien de sa propre boucle (part_connue = "
        f"{part_locale}) : le quadrillage semé ne recouvre pas les tracés du BRouter "
        "bouchonné, et le volet suivant ne prouverait rien."
    )

    # PROPRIETAIRE_A doit lui aussi écrire son propre départ et son propre
    # cycliste (Q35, tiers 3) : le socle partagé ne les lui fournit plus,
    # « n'a jamais rien enregistré » porte sur les **routes**, pas sur le
    # profil, qui doit être complet pour que `POST /boucles` calcule quoi
    # que ce soit.
    profil_a = client.requete(
        "PATCH",
        f"{PREFIXE_API}/profil",
        headers={"x-essai-proprietaire": PROPRIETAIRE_A},
        json={"depart": DEPART_D_ESSAI, "cycliste": {"masse_kg": 70.0}},
    )
    assert profil_a.status_code == 200, profil_a.text[:300]

    reponse = client.post(
        f"{PREFIXE_API}/boucles", headers={"x-essai-proprietaire": PROPRIETAIRE_A}, **demande
    )
    assert _part_connue(reponse) == 0.0, (
        f"une boucle est annoncée connue à {_part_connue(reponse):.1%} à un cycliste qui "
        "n'a jamais rien enregistré : la colonne « connu % » est calculée contre les "
        "routes du propriétaire local, donc contre les endroits où quelqu'un d'autre roule."
    )


def _part_connue(reponse) -> float:
    """La part « déjà connue » de la première candidate d'une réponse `/boucles`."""
    assert reponse.status_code == 200, reponse.text[:300]
    candidates = reponse.json()["donnees"]["candidates"]
    assert candidates, "aucune candidate : la boucle n'a pas été générée"
    return candidates[0]["part_connue"] or 0.0


def _planter(client: ClientApi, qui: str, marque: str) -> dict[str, str]:
    """Plante les sentinelles de `qui` **par l'API**, et rend ses identifiants.

    On n'écrit pas dans les dépôts en passant par-dessous : ce que le
    balayage doit prouver est qu'un cycliste ne voit pas ce qu'un autre a
    déposé **en se servant du produit**. Écrire sous la route reviendrait à
    tester le dépôt, ce que `test_une_ressource_d_un_proprietaire_n_est_pas_lisible_par_un_autre`
    fait déjà, et à laisser la route hors de l'épreuve.

    **`depart.latitude`/`.longitude` et `cycliste.masse_kg` sont désormais
    écrits ici aussi** (Q35, tiers 3, fermé le 21/09/2026) : le socle partagé
    de `_toml_d_essai` ne les fournit plus à qui ne les a pas écrits, donc
    `qui` doit écrire un profil complet pour que sa `Config` se construise du
    tout — ce n'était pas le cas avant cette date, `latitude`/`longitude`
    manquants s'y trouvaient hérités du socle sans que ce test le voie.
    """
    entetes = {"x-essai-proprietaire": qui}
    profil = client.requete(
        "PATCH",
        f"{PREFIXE_API}/profil",
        headers=entetes,
        json={
            "depart": {"nom": f"depart-{marque}", "latitude": 0.0007, "longitude": 0.0003},
            "cycliste": {"masse_kg": 70.0},
            "velos": [
                {"nom": f"velo-{marque}", "usage": "route", "masse_kg": 9.0, "cda_m2": 0.3}
            ],
            # La clé porte elle aussi la sentinelle : c'est le secret du
            # profil, et une fuite de clé d'un cycliste vers un autre serait la
            # pire de toutes. Inventée, comme le reste (règle absolue 1).
            "intervals": {"athlete_id": "i000000", "api_key": f"cle-{marque}"},
        },
    )
    assert profil.status_code == 200, f"{qui} n'a pas pu écrire son profil : {profil.text[:300]}"

    depot = client.post(
        f"{PREFIXE_API}/seances/fichier",
        headers=entetes,
        files={"fichier": (f"seance-{marque}.zwo", _zwo(f"seance-{marque}"), "application/xml")},
    )
    assert depot.status_code == 200, f"{qui} n'a pas pu déposer sa séance : {depot.text[:300]}"

    sortie = client.post(
        f"{PREFIXE_API}/sorties",
        headers=entetes,
        json={"jour": _jour(), "candidates": 2},
    )
    assert sortie.status_code == 200, f"{qui} n'a pas pu générer sa sortie : {sortie.text[:300]}"

    # `POST /sorties` laisse ses GPX en mémoire tant que le cycliste n'a pas
    # choisi (Q40 g) : c'est `POST /boucles` qui en écrit un dans le dépôt, et
    # c'est de celui-là que `POST /simulations` a besoin.
    boucle = client.post(
        f"{PREFIXE_API}/boucles",
        headers=entetes,
        json={"distance_km": 30.0, "candidates": 1},
    )
    assert boucle.status_code == 200, f"{qui} n'a pas pu générer sa boucle : {boucle.text[:300]}"

    return {
        "fichier": _corps(depot)["fichier"]["id"],
        "generation": sortie.json()["donnees"]["generation"],
        "gpx": boucle.json()["donnees"]["gpx"]["id"],
    }


def _jour() -> str:
    """Le jour que les bouchons de séance connaissent."""
    return transports_du_depot().JOUR.isoformat()


def _appels(ids: dict[str, str]) -> dict[tuple[str, str], dict]:
    """**Comment appeler chaque route de données pour de vrai.**

    Clé : `(méthode, gabarit déclaré)`, exactement ce que
    `_routes_de_donnees` énumère — et
    `test_le_balayage_couvre_toutes_les_routes_de_donnees` vérifie que les
    deux ensembles coïncident. C'est là que le filet mord : une route ajoutée
    demain **doit** entrer dans ce tableau, donc quelqu'un doit se demander ce
    qu'elle sert et à qui.

    Les identifiants passés sont ceux de **A** : chaque appel est rejoué tel
    quel sous l'identité de B, et c'est précisément ce qu'on veut voir échouer.
    """
    jour = _jour()
    velo = {"nom": "Essai", "usage": "route", "masse_kg": 9.0, "cda_m2": 0.3}
    return {
        ("GET", f"{PREFIXE_API}/systeme"): {},
        ("GET", f"{PREFIXE_API}/systeme/budgets"): {},
        ("GET", f"{PREFIXE_API}/profil"): {},
        ("PATCH", f"{PREFIXE_API}/profil"): {"json": {"cycliste": {"masse_kg": 71.0}}},
        ("GET", f"{PREFIXE_API}/profil/zones"): {},
        ("POST", f"{PREFIXE_API}/profil/zones/apercu"): {"json": {"position_zone": 0.5}},
        # Sans clé Intervals renseignée pour A comme pour B, cette route
        # répond `intervals_absent` (409) dans les deux cas — générique,
        # sans rien de l'un ni de l'autre : c'est un balayage de couverture,
        # pas un test du connecteur (voir tests/test_ecran_ftp.py et
        # tests/connecteurs/test_intervals.py pour ça).
        ("GET", f"{PREFIXE_API}/profil/intervals"): {},
        ("POST", f"{PREFIXE_API}/profil/ftp/apercu"): {
            "json": {"vitesse_kmh": 24.0, "denivele_m_par_km": 10.0}
        },
        ("GET", f"{PREFIXE_API}/profil/ftp/generique"): {},
        ("GET", f"{PREFIXE_API}/geocodage"): {"params": {"adresse": "rue d'essai"}},
        ("GET", f"{PREFIXE_API}/vent-depart"): {"params": {"jour": jour}},
        ("GET", f"{PREFIXE_API}/meteo"): {},
        ("GET", f"{PREFIXE_API}/seances"): {},
        ("GET", f"{PREFIXE_API}/seances/{{jour}}"): {"chemin": f"{PREFIXE_API}/seances/{jour}"},
        ("POST", f"{PREFIXE_API}/seances/fichier"): {
            "files": {"fichier": ("visiteur.zwo", _zwo("visiteur"), "application/xml")}
        },
        ("POST", f"{PREFIXE_API}/sorties"): {"json": {"jour": jour, "candidates": 2}},
        ("GET", f"{PREFIXE_API}/sorties/{{generation}}/propositions/{{numero}}/gpx"): {
            "chemin": f"{PREFIXE_API}/sorties/{ids['generation']}/propositions/1/gpx"
        },
        ("POST", f"{PREFIXE_API}/boucles"): {"json": {"distance_km": 30.0, "candidates": 2}},
        ("POST", f"{PREFIXE_API}/simulations"): {
            "json": {"gpx": ids["gpx"], "puissance_w": 180.0}
        },
        ("GET", f"{PREFIXE_API}/inventaire"): {},
        ("GET", f"{PREFIXE_API}/routes/{{action}}"): {"chemin": f"{PREFIXE_API}/routes/stats"},
        ("GET", f"{PREFIXE_API}/fichiers/{{identifiant}}"): {
            "chemin": f"{PREFIXE_API}/fichiers/{ids['fichier']}",
            # Sert aussi de rappel : le vélo d'essai existe chez les deux, et
            # ce n'est donc pas lui qui distingue A de B.
            "note": velo,
        },
        # L7.B : export et suppression des données personnelles. `DELETE`
        # efface le compte de qui l'appelle — `_balayer` le passe en dernier
        # (voir sa docstring) pour que les routes de lecture de la même
        # identité aient déjà été éprouvées quand il s'exécute.
        ("GET", f"{PREFIXE_API}/moi/export"): {},
        ("DELETE", f"{PREFIXE_API}/moi"): {},
    }


def test_le_balayage_de_bout_en_bout_couvre_toutes_les_routes_de_donnees():
    """**Le filet du lot L7.A : une route nouvelle ne peut pas passer inaperçue.**

    Le tableau `_appels` est comparé à ce que l'application déclare vraiment.
    Ajouter une route sans l'y inscrire fait échouer ce test ; l'y inscrire
    la fait entrer d'office dans le balayage des 401 **et** dans celui des
    deux propriétaires. Il n'y a pas de chemin qui mène à une route de
    données non éprouvée — c'est ce que « prouvée, pas échantillonnée »
    veut dire.
    """
    declarees = _routes_de_donnees(charger_application(config=config_d_essai()))
    couvertes = set(_appels({"generation": "x", "gpx": "x", "fichier": "x"}))
    oubliees = sorted(declarees - couvertes)
    assert not oubliees, (
        "routes de données absentes du balayage d'isolation :\n  "
        + "\n  ".join(f"{m} {c}" for m, c in oubliees)
        + "\nAjouter une entrée dans `_appels` : une route qu'aucun test n'appelle sous "
        "deux identités est une route dont personne ne sait si elle isole."
    )
    fantomes = sorted(couvertes - declarees)
    assert not fantomes, (
        "le balayage appelle des routes qui n'existent plus :\n  "
        + "\n  ".join(f"{m} {c}" for m, c in fantomes)
        + "\nUn balayage qui vise des routes mortes se croit exhaustif sans l'être."
    )


def test_deux_proprietaires_ne_voient_jamais_rien_l_un_de_l_autre(tmp_path):
    """**L'isolation prouvée route par route, contre le service réel.**

    A plante trois sentinelles par l'API — un nom de départ, un nom de vélo,
    un fichier de séance — puis B rejoue **chaque** route de données, y
    compris avec les identifiants de A dans l'URL. Aucune réponse servie à B
    ne doit porter la moindre sentinelle de A, et aucune ne doit se dire
    servie au nom de A.

    La contre-épreuve est dans le même test, et elle est indispensable : on
    vérifie que les sentinelles de A sont bel et bien **visibles par A**. Sans
    elle, un plantage silencieux du semis rendrait le test vert en ne
    mesurant rien — le mode d'échec le plus courant de ce genre de balayage.
    """
    client = _service_pour_deux(tmp_path)
    ids = _planter(client, PROPRIETAIRE_A, MARQUE_A)

    # **Premier temps, et le plus important : B arrive et n'a rien écrit.**
    # C'est l'ordre qui fait la preuve. Balayer seulement *après* que B se
    # soit installé laisserait passer un stockage entièrement mis en commun :
    # l'écriture de B écraserait celle de A, et la sentinelle de A aurait
    # disparu au lieu d'être visible — un test vert sur une fuite totale.
    # Vérifié le 18/09/2026 en mettant `DepotProfils.dossier` en commun : sans
    # ce premier temps, la suite restait verte.
    fuites = [
        f"{route} montre {MARQUE_A} à un cycliste qui vient d'arriver"
        for route, texte in _balayer(client, PROPRIETAIRE_B, ids).items()
        if MARQUE_A in texte
    ]

    # **Second temps : B s'installe, et rejoue tout avec les identifiants de A.**
    _planter(client, PROPRIETAIRE_B, MARQUE_B)
    vues_de_a = _balayer(client, PROPRIETAIRE_A, ids)
    vues_de_b = _balayer(client, PROPRIETAIRE_B, ids)

    fuites += [
        f"{route} porte {MARQUE_A}" for route, texte in vues_de_b.items() if MARQUE_A in texte
    ]
    fuites += [
        f"{route} se dit servie au nom de « {PROPRIETAIRE_A} »"
        for route, texte in vues_de_b.items()
        if f'"proprietaire": "{PROPRIETAIRE_A}"' in texte or f"'{PROPRIETAIRE_A}'" in texte
    ]
    assert not fuites, (
        "fuites d'un propriétaire vers l'autre :\n  "
        + "\n  ".join(sorted(fuites))
        + "\nDoctrine §10.2 : l'isolation est vérifiée côté serveur, à chaque requête."
    )

    # Contre-épreuve, en deux volets. Sans elle, un semis qui n'aurait pas
    # pris rendrait tout ce qui précède vert sans rien mesurer — le mode
    # d'échec le plus courant de ce genre de balayage.
    for marque, vues, qui in ((MARQUE_A, vues_de_a, "A"), (MARQUE_B, vues_de_b, "B")):
        porteuses = sorted(route for route, texte in vues.items() if marque in texte)
        assert porteuses, (
            f"aucune route ne montre la sentinelle de {qui} à {qui} lui-même : le semis "
            "n'a pas pris, et le balayage ne prouverait rien."
        )
    # Et le profil de A a **survécu** à l'arrivée de B : l'isolation n'est pas
    # obtenue en écrasant l'un par l'autre.
    profil_de_a = vues_de_a[f"GET {PREFIXE_API}/profil"]
    assert MARQUE_A in profil_de_a and MARQUE_B not in profil_de_a, (
        "le profil de A ne porte plus sa propre sentinelle, ou porte celle de B : "
        "les deux profils partagent le même stockage."
    )


def _ordre_de_balayage(item: tuple[tuple[str, str], dict]) -> tuple[bool, tuple[str, str]]:
    """Trie `_appels` en gardant les `DELETE` pour la fin. Voir `_balayer`."""
    (methode, gabarit), _appel = item
    return (methode == "DELETE", (methode, gabarit))


def _balayer(client: ClientApi, qui: str, ids: dict[str, str]) -> dict[str, str]:
    """{`MÉTHODE chemin`: tout le texte de la réponse} pour une identité donnée.

    **Les `DELETE` sont rejoués en dernier.** `_appels` couvre maintenant
    `DELETE /api/v1/moi` (L7.B), qui efface le compte de `qui` l'appelle : trié
    alphabétiquement, il serait passé *avant* les `GET` (« D » < « G »/« P »)
    et aurait effacé l'identité en cours de route avant que ses propres
    routes de lecture n'aient été éprouvées. Trier les `DELETE` après tout le
    reste garde chaque appel de lecture intact au moment où il s'exécute ; la
    suppression, elle, n'a plus rien après elle dans ce balayage.
    """
    vues: dict[str, str] = {}
    for (methode, gabarit), appel in sorted(_appels(ids).items(), key=_ordre_de_balayage):
        options = {cle: valeur for cle, valeur in appel.items() if cle not in ("chemin", "note")}
        reponse = client.requete(
            methode,
            appel.get("chemin", gabarit),
            headers={"x-essai-proprietaire": qui},
            **options,
        )
        corps = _corps(reponse)
        vues[f"{methode} {gabarit}"] = texte_entier(corps) if corps else reponse.text
    return vues


# --- la preuve que le filet mord ---------------------------------------------


def test_une_route_sans_clause_de_proprietaire_est_bien_detectee():
    """**La contre-épreuve du détecteur lui-même.**

    Le 18/09/2026, la manœuvre a d'abord été faite à la main : une route
    `GET /api/v1/essai-sans-clause` ajoutée dans `routes.py` sans `qui: Qui`,
    la suite échoue, la route retirée. Une vérification manuelle ne se rejoue
    pas ; celle-ci, si.

    On fabrique ici une route de données sans clause et on vérifie que le
    détecteur la refuse — et, symétriquement, qu'il accepte la même route
    munie de sa clause. Sans ce second volet, un détecteur qui refuserait
    *tout* passerait pour vigilant.
    """
    from fastapi import APIRouter

    routeur_fautif = APIRouter(prefix=PREFIXE_API)

    @routeur_fautif.get("/essai-sans-clause")
    def _sans_clause(ctx: Ctx) -> dict:  # pragma: no cover — jamais appelée
        del ctx
        return {}

    @routeur_fautif.get("/essai-avec-clause")
    def _avec_clause(ctx: Ctx, qui: Qui) -> dict:  # pragma: no cover — jamais appelée
        del ctx, qui
        return {}

    application = charger_application(config=config_d_essai())
    application.include_router(routeur_fautif)

    nues = [
        chemin
        for chemin, fonction in _routes_servies(application)
        if _est_une_route_de_donnees(chemin) and not _resout_un_proprietaire(fonction)
    ]
    assert nues == [f"{PREFIXE_API}/essai-sans-clause"], (
        f"le détecteur n'a pas vu la route sans clause (il a vu {nues}) : la suite "
        "resterait verte pendant qu'une route sert les données de n'importe qui."
    )


def test_une_route_ajoutee_hors_du_balayage_fait_echouer_la_suite():
    """L'autre moitié du filet : exister ne suffit pas, il faut être éprouvée.

    Une route peut porter sa clause **et** n'être appelée par aucun test sous
    deux identités. `test_le_balayage_de_bout_en_bout_couvre_toutes_les_routes_de_donnees`
    ferme ce trou ; on vérifie ici qu'il le ferme vraiment.
    """
    from fastapi import APIRouter

    routeur_neuf = APIRouter(prefix=PREFIXE_API)

    @routeur_neuf.get("/essai-hors-balayage")
    def _neuve(ctx: Ctx, qui: Qui) -> dict:  # pragma: no cover — jamais appelée
        del ctx, qui
        return {}

    application = charger_application(config=config_d_essai())
    application.include_router(routeur_neuf)

    declarees = _routes_de_donnees(application)
    couvertes = set(_appels({"generation": "x", "gpx": "x", "fichier": "x"}))
    assert declarees - couvertes == {("GET", f"{PREFIXE_API}/essai-hors-balayage")}, (
        "une route neuve n'est pas signalée comme absente du balayage : le filet ne "
        "mord pas, et la prochaine route ajoutée ne sera éprouvée par personne."
    )


def test_la_liste_des_routes_hors_donnees_ne_ment_pas():
    """Une liste d'exceptions qui nomme des routes inexistantes ne protège rien.

    Deux façons de se tromper, toutes deux fermées ici : inscrire un chemin
    qui n'existe pas (l'exception devient une incantation), et inscrire un
    chemin de l'API (la dispense devient une fuite). Une route de `/api/v1`
    sert par construction les données d'un cycliste ; aucune n'a sa place
    dans cette liste.
    """
    servies = {
        str(getattr(r, "path", ""))
        for r in _toutes_les_routes(charger_application(config=config_d_essai()))
    }
    inventees = sorted(set(ROUTES_HORS_DONNEES) - servies)
    assert not inventees, (
        f"routes dispensées qui n'existent pas : {inventees}. Une exception qui ne "
        "correspond à rien ne fait que masquer la suivante."
    )
    de_l_api = sorted(c for c in ROUTES_HORS_DONNEES if c.startswith(PREFIXE_API))
    assert not de_l_api, (
        f"routes de l'API dispensées de clause de propriétaire : {de_l_api}. "
        "Sous /api/v1, tout sert les données de quelqu'un."
    )


def test_la_liste_des_routes_avant_session_ne_ment_pas():
    """Le même garde-fou que ci-dessus, pour `ROUTES_AVANT_SESSION` (lot L7.2-C).

    Trois façons de se tromper, fermées ici : inscrire un chemin qui n'existe
    pas (l'exception devient une incantation) ; en oublier une, servie mais
    non dispensée, qui échouerait alors sur `_resout_un_proprietaire` pour la
    mauvaise raison ; ou dispenser une route qui **peut** recevoir `Qui` — ce
    qui prouverait que l'exemption couvre une route de données ordinaire et
    pas seulement les quatre qui précèdent la session. Ce troisième point est
    la contre-épreuve que le brief demande : une exemption qui dispenserait
    une route capable de résoudre un propriétaire serait la fuite que
    `test_une_route_sans_clause_de_proprietaire_est_bien_detectee` existe pour
    attraper ailleurs — elle ne doit pas pouvoir se glisser ici à l'abri de ce
    détecteur-là.
    """
    servies = {
        str(getattr(r, "path", ""))
        for r in _toutes_les_routes(charger_application(config=config_d_essai()))
    }
    inventees = sorted(set(ROUTES_AVANT_SESSION) - servies)
    assert not inventees, (
        f"routes dispensées qui n'existent pas : {inventees}. Une exception qui ne "
        "correspond à rien ne fait que masquer la suivante."
    )

    par_chemin = {
        chemin: fonction
        for chemin, fonction in _routes_servies(charger_application(config=config_d_essai()))
    }
    capables = sorted(
        chemin
        for chemin in ROUTES_AVANT_SESSION
        if chemin in par_chemin and _resout_un_proprietaire(par_chemin[chemin])
    )
    assert not capables, (
        f"routes dispensées de la clause qui pourraient pourtant la porter : {capables}. "
        "Une route qui reçoit `Qui` n'a pas sa place dans ROUTES_AVANT_SESSION — elle "
        "sert (ou pourrait servir) les données d'un propriétaire déjà résolu, ce n'est "
        "pas ce que cette dispense couvre."
    )


# --- sans session, rien ------------------------------------------------------


def test_sans_session_chaque_route_de_donnees_repond_401():
    """Le point du lot, et la régression la plus chère s'il saute.

    Avant le 18/09/2026, `proprietaire()` rendait `PROPRIETAIRE_LOCAL` sans
    rien demander : **une requête anonyme obtenait les données du
    mainteneur**. Le service ci-dessous est monté en mode hébergé, c'est-à-dire
    avec un fournisseur qui n'ouvre aucune session, et chaque route de données
    doit refuser.

    Le balayage est exhaustif par construction : il part des routes que
    l'application déclare, pas d'une liste écrite à la main. Une route ajoutée
    demain y entre toute seule.

    On n'envoie **ni corps valide ni paramètre requis** : le refus doit
    précéder la validation. Une route qui répondrait 422 « champ manquant »
    avant de refuser dirait à un inconnu quels champs elle attend, et
    surtout prouverait que la clause n'est pas la première chose vérifiée.
    """
    client = ClientApi(charger_application(config=config_d_essai(), session=SessionHebergee()))
    servies = _routes_de_donnees(client.application)
    assert servies, "aucune route de données trouvée : le test ne mesure rien"

    fautives = []
    for methode, gabarit in sorted(servies):
        reponse = client.requete(methode, _concret(gabarit))
        code = (_corps(reponse).get("erreur") or {}).get("code")
        if reponse.status_code != 401 or code != "session_absente":
            fautives.append(f"{methode} {gabarit} → {reponse.status_code} ({code})")
    assert not fautives, (
        "routes servies sans session ouverte :\n  "
        + "\n  ".join(fautives)
        + "\nSans session, une route de données répond 401 — jamais un profil par "
        "défaut, jamais le propriétaire local en silence."
    )


def test_le_refus_sans_session_ne_nomme_aucun_proprietaire():
    """Un 401 qui dit « local » apprend à l'inconnu le nom du compte à viser."""
    client = ClientApi(charger_application(config=config_d_essai(), session=SessionHebergee()))
    corps = client.get(f"{PREFIXE_API}/profil").text.lower()
    assert "session" in corps, "le refus ne dit pas ce qui manque"
    assert str(PROPRIETAIRE_LOCAL) not in re.findall(r"[a-z0-9_-]+", corps), (
        "le refus nomme le propriétaire local : il renseigne au lieu de refuser"
    )


# --- le mode personnel, qui ne meurt pas -------------------------------------


def test_le_mode_personnel_explicite_rend_toujours_le_meme_proprietaire():
    """`ourouler api` sur la machine du cycliste : un seul, et toujours le même.

    Ce qui disparaît avec L7.A est le **défaut implicite** d'un service
    exposé, pas l'usage d'origine du projet. Un fournisseur personnel
    explicitement configuré rend le même propriétaire à chaque requête, quoi
    que le client raconte — y compris s'il tente de se nommer lui-même.
    """
    client = ClientApi(charger_application(config=config_d_essai(), session=SessionPersonnelle()))
    vus = {
        client.get(
            f"{PREFIXE_API}/systeme",
            headers={"x-essai-proprietaire": PROPRIETAIRE_B},
        ).json()["proprietaire"]
        for _ in range(3)
    }
    assert vus == {str(PROPRIETAIRE_LOCAL)}, (
        f"le mode personnel a rendu {vus} : il doit rendre un seul propriétaire, "
        "toujours le même, et ignorer ce que le client envoie"
    )


def test_ourouler_api_sert_toujours_le_mainteneur(tmp_path, monkeypatch):
    """La sous-commande de la ligne de commande n'a pas changé de comportement.

    Vérifié **sur la vraie commande**, pas sur une intention : `uvicorn.run`
    est intercepté, l'application qu'il aurait servie est récupérée telle
    quelle, et on l'interroge. Sans cela, on croirait tester `ourouler api` en
    ne testant que `creer_application`.
    """
    uvicorn = pytest.importorskip("uvicorn", reason="extra « api » absent")

    from ourouler.cli import main

    chemin = tmp_path / "config.toml"
    chemin.write_text(_toml_d_essai(tmp_path), encoding="utf-8")
    servies: list[object] = []
    monkeypatch.setattr(uvicorn, "run", lambda app, **_: servies.append(app))

    assert main(["--config", str(chemin), "api"]) == 0
    assert servies, "ourouler api n'a servi aucune application"

    reponse = ClientApi(servies[0]).get(f"{PREFIXE_API}/systeme")
    assert reponse.status_code == 200, (
        f"ourouler api répond {reponse.status_code} sur sa propre machine : le mode "
        "personnel a été perdu en route"
    )
    assert reponse.json()["proprietaire"] == str(PROPRIETAIRE_LOCAL)


# --- d'où vient le choix du fournisseur --------------------------------------


def test_le_mode_se_lit_dans_l_environnement_et_refuse_par_defaut():
    """La seule frontière d'environnement nommée du projet (règle absolue 2).

    Le défaut est le point : un processus lancé sans qu'on ait dit qui il sert
    **refuse**. Servir le mainteneur « en attendant » est exactement la fuite
    que ce lot ferme, et un défaut permissif est celle qu'on n'aurait jamais
    vue passer.
    """
    from ourouler.api import exploitation
    from ourouler.erreurs import ErreurConfig

    assert exploitation.fournisseur_session({}).mode == MODE_HEBERGE
    assert exploitation.fournisseur_session({"OUROULER_MODE": ""}).mode == MODE_HEBERGE
    assert exploitation.fournisseur_session({"OUROULER_MODE": "personnel"}).mode == MODE_PERSONNEL
    with pytest.raises(ErreurConfig) as refus:
        exploitation.fournisseur_session({"OUROULER_MODE": "ouvert"})
    assert "ouvert" in str(refus.value), "le refus ne dit pas quelle valeur a été lue"


def test_aucun_autre_module_de_l_api_ne_choisit_le_fournisseur():
    """Le choix se lit à **un** endroit, sans quoi la frontière n'en est plus une.

    `exploitation.py` est la seule porte d'environnement du paquet, et le
    produit servi — une personne, ou plusieurs — en fait partie au même titre
    que le chemin du fichier de configuration. Un second module qui lirait
    `OUROULER_MODE` rendrait la question « ce déploiement sert-il plusieurs
    cyclistes ? » impossible à répondre en lisant un fichier.
    """
    coupables = [
        fichier.name
        for fichier in fichiers_python_de_l_api()
        if fichier.name != "exploitation.py" and _nomme_la_variable(fichier, "OUROULER_MODE")
    ]
    assert not coupables, f"modules qui lisent OUROULER_MODE hors de la porte : {coupables}"
    assert _nomme_la_variable(SOURCES / "api" / "exploitation.py", "OUROULER_MODE"), (
        "exploitation.py ne nomme plus OUROULER_MODE : la porte est là, mais elle ne "
        "sert plus — un invariant qui encadre une permission que personne n'utilise "
        "n'encadre rien."
    )


def _nomme_la_variable(fichier: Path, nom: str) -> bool:
    """Vrai si le **code** de ce fichier cite `nom` — les docstrings ne comptent pas.

    On lit l'arbre syntaxique et non le texte : `application.py` et
    `session.py` *expliquent* ce que `OUROULER_MODE` fait, en prose, et c'est
    exactement ce qu'on veut qu'ils fassent. Une recherche textuelle les
    accuserait de lire l'environnement pour l'avoir documenté, et la seule
    façon de faire taire un tel test serait d'effacer l'explication.

    Les commentaires n'apparaissent pas dans l'arbre, et les docstrings y
    apparaissent comme des `Expr` de constante : les deux sont donc écartés,
    et il ne reste que les chaînes dont le code se sert vraiment.
    """
    import ast

    arbre = ast.parse(fichier.read_text(encoding="utf-8"))
    prose = {
        id(noeud.value)
        for noeud in ast.walk(arbre)
        if isinstance(noeud, ast.Expr) and isinstance(noeud.value, ast.Constant)
    }
    return any(
        isinstance(noeud, ast.Constant)
        and isinstance(noeud.value, str)
        and nom in noeud.value
        and id(noeud) not in prose
        for noeud in ast.walk(arbre)
    )
