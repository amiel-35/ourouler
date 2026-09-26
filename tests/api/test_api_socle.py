"""Le socle de l'API : ce sans quoi aucun autre test n'a de sens.

Écrans protégés : tous. Une API qu'on ne peut pas construire sans réseau ne se
teste pas ; une API qui ne publie pas son contrat ne se code pas côté front
(`front_contrat.md`, F1 « l'API expose ce que la CLI rend déjà, une route par
sous-commande ») ; une API qui lit `~/.config` viole la règle absolue 2.
"""

from __future__ import annotations

import ast

import httpx
import pytest
from outils_api import (
    APPLICATIONS_CANDIDATES,
    CLE_INTERVALS_SENTINELLE,
    DEPART_SYNTHETIQUE,
    ApiAbsente,
    ClientApi,
    charger_fabrique,
    client_api,
    client_bouchon,
    config_d_essai,
    fichiers_python_de_l_api,
    noms_de_parametres,
    options_refusees,
    parametre_nomme,
    route_pour,
    routes,
    schema_openapi,
    verifier_refus_exploitable,
)

#: Les dix sous-commandes de `discovery_donnees.md` §1. F1 en expose une route
#: chacune. `routes` et `calibrer` ne sont pas dans la liste dure : elles
#: n'apparaissent sur aucun des vingt écrans.
SOUS_COMMANDES_DES_ECRANS = (
    ("config", ("config", "profil", "reglages")),
    ("seance", ("seance",)),
    ("sortie", ("sortie", "parcours")),
    ("boucle", ("boucle", "parcours")),
    ("meteo", ("meteo",)),
    ("inventaire", ("inventaire", "activites")),
    ("geocodage", ("geocod", "adresse")),
)


# Marque `xfail(strict=True)` posée par le testeur en aveugle avant que F1
# n'existe, retirée le 17/09/2026 à sa livraison. C'est `strict` qui l'a
# signalé : le test s'est mis à passer et la suite a échoué pour le dire,
# au lieu de laisser une marque périmée affirmer que rien ne marche.
def test_l_application_se_construit_par_une_fabrique():
    """Protège la règle absolue 3 : sans fabrique, pas de test sans réseau.

    Une application construite à l'import (`app = FastAPI()` au niveau du
    module, qui lit une config au passage) est intestable : on ne peut ni lui
    passer un `Config` inventé, ni lui substituer un client HTTP bouchonné.
    C'est aussi la même couture qui servira aux comptes en F3, où la Config
    viendra de Postgres et non d'un TOML (doctrine §10.1).
    """
    fabrique = charger_fabrique()
    assert callable(fabrique)


# Marque `xfail(strict=True)` posée par le testeur en aveugle avant que F1
# n'existe, retirée le 17/09/2026 à sa livraison. C'est `strict` qui l'a
# signalé : le test s'est mis à passer et la suite a échoué pour le dire,
# au lieu de laisser une marque périmée affirmer que rien ne marche.
def test_la_fabrique_accepte_une_config_et_des_clients_injectables():
    """Protège la règle absolue 3 et la doctrine §10.1 (« les dépôts sont des interfaces »).

    Le cœur reçoit déjà `Config`, `Velo` et un client HTTP en paramètre. L'API
    est une nouvelle bordure : si elle recrée ses clients elle-même, elle
    annule cette propriété pour tout ce qui passe par elle.
    """
    refusees = options_refusees(
        config=object(),
        client_meteo=object(),
        client_intervals=object(),
        client_brouter=object(),
    )
    assert "config" not in refusees, (
        "la fabrique n'accepte pas de `config` : l'API construirait alors son propre profil, "
        "et aucun test ne pourrait lui en donner un inventé."
    )
    assert len(refusees) <= 2, (
        f"clients non injectables : {sorted(refusees)}. Chaque connecteur doit pouvoir "
        "recevoir un httpx.MockTransport, sinon les tests appellent Internet."
    )


# Marque `xfail(strict=True)` posée par le testeur en aveugle avant que F1
# n'existe, retirée le 17/09/2026 à sa livraison. C'est `strict` qui l'a
# signalé : le test s'est mis à passer et la suite a échoué pour le dire,
# au lieu de laisser une marque périmée affirmer que rien ne marche.
def test_l_application_publie_son_schema_openapi():
    """Protège F2 tout entier : le front se code contre le schéma, pas contre le code.

    `front_contrat.md` : « L'API avant le front ». Un front écrit contre une
    API qui ne publie pas son contrat redécouvre chaque champ par essais, et
    chaque renommage silencieux casse un écran en production.
    """
    schema = schema_openapi(client_api())
    assert routes(schema), "schéma publié mais sans aucune route"


# Marque `xfail(strict=True)` posée par le testeur en aveugle avant que F1
# n'existe, retirée le 17/09/2026 à sa livraison. C'est `strict` qui l'a
# signalé : le test s'est mis à passer et la suite a échoué pour le dire,
# au lieu de laisser une marque périmée affirmer que rien ne marche.
@pytest.mark.parametrize(
    "commande,motifs", SOUS_COMMANDES_DES_ECRANS, ids=[c for c, _ in SOUS_COMMANDES_DES_ECRANS]
)
def test_chaque_sous_commande_des_ecrans_a_sa_route(commande: str, motifs: tuple[str, ...]):
    """Protège les vingt écrans : chaque donnée dessinée vient d'une de ces commandes.

    `front_contrat.md`, F1 : « une route par sous-commande, plus les écritures
    du profil ». Le géocodage n'est pas une sous-commande historique mais F0.2
    l'a livré (`ourouler geocoder`) et E10 en dépend entièrement.
    """
    chemin, methode, _ = route_pour(schema_openapi(client_api()), *motifs)
    assert chemin and methode, commande


# Marque `xfail(strict=True)` posée par le testeur en aveugle avant que F1
# n'existe, retirée le 17/09/2026 à sa livraison. C'est `strict` qui l'a
# signalé : le test s'est mis à passer et la suite a échoué pour le dire,
# au lieu de laisser une marque périmée affirmer que rien ne marche.
def test_le_profil_s_ecrit_et_pas_seulement_se_lit():
    """Protège E9 (assistant : FTP, poids) et E21 (réglages : FTP, poids, départ, vélo).

    `ourouler config --json` ne sait que lire. L'assistant écrit cinq écrans de
    réglages ; sans route d'écriture, E9 à E12 n'existent pas.
    """
    schema = schema_openapi(client_api())
    ecritures = [
        (chemin, methode)
        for chemin, methode, _ in routes(schema)
        if methode in {"POST", "PUT", "PATCH"}
        and any(mot in chemin.lower() for mot in ("config", "profil", "reglage"))
    ]
    assert ecritures, (
        "aucune route d'écriture du profil. Écrans concernés : E9 (FTP), E10 (départ), "
        "E11 (vélo), E12 (clé Intervals), E21 (réglages)."
    )


# Marque `xfail(strict=True)` posée par le testeur en aveugle avant que F1
# n'existe, retirée le 17/09/2026 à sa livraison. C'est `strict` qui l'a
# signalé : le test s'est mis à passer et la suite a échoué pour le dire,
# au lieu de laisser une marque périmée affirmer que rien ne marche.
def test_une_route_inconnue_rend_du_json_et_pas_du_html():
    """Protège tous les écrans : un front ne sait lire qu'une seule forme d'erreur.

    Le 404 par défaut de beaucoup de cadres web est du HTML ou un `{"detail":
    "Not Found"}` en anglais. Les maquettes n'ont pas d'écran « Not Found ».
    """
    reponse = client_api().get("/chemin-qui-n-existe-pas-du-tout")
    verifier_refus_exploitable(reponse, "route inconnue")


# Marque `xfail(strict=True)` posée par le testeur en aveugle avant que F1
# n'existe, retirée le 17/09/2026 à sa livraison. C'est `strict` qui l'a
# signalé : le test s'est mis à passer et la suite a échoué pour le dire,
# au lieu de laisser une marque périmée affirmer que rien ne marche.
def test_aucune_route_n_ouvre_de_connexion_reelle():
    """Protège la règle absolue 3, mesurée plutôt que promise.

    La fixture `reseau_interdit` lève `ReseauInterdit` (qui dérive de
    `BaseException`) au premier `connect`. Si la route sort sur Internet, ce
    test le dit ; s'il passe, c'est que l'injection a bien court-circuité le
    client réel.

    **Corrigé le 17/09/2026 — un test de l'injection doit injecter.** La
    version d'origine construisait l'application par `client_api(config=None)`,
    donc sans `Config` et sans aucun client bouchonné, puis exigeait que le
    géocodage réponde autre chose qu'un 500. Aucune implémentation ne peut
    tenir ça : une route dont le travail est d'interroger la BAN n'a que deux
    façons de répondre sans client — sortir sur le réseau (et la fixture la
    tue, à juste titre) ou refuser faute de configuration. L'assertion ne
    mesurait donc pas l'injection, elle interdisait le géocodage.

    Ce qui était protégé est conservé, et devient vérifiable : on **donne**
    un profil inventé et des clients à transport bouchonné, et on exige que
    la route réponde sans 500. Si la fabrique ignorait les clients injectés,
    la route sortirait sur le réseau et la fixture ferait échouer ce test —
    c'est exactement la propriété visée.
    """
    client = client_api(
        config=config_d_essai(),
        client_ban=client_bouchon(200, {"type": "FeatureCollection", "features": []}),
        client_nominatim=client_bouchon(200, []),
    )
    chemin, methode, operation = route_pour(schema_openapi(client), "geocod", "adresse")
    noms = noms_de_parametres(schema_openapi(client), operation)
    cle = parametre_nomme(noms, "adresse", "requete", "q") or "adresse"
    reponse = client.requete(methode, chemin, params={cle: "rue inventee dessai"})
    assert reponse.status_code != 500, (
        "500 nu sur le géocodage : soit la route a tenté un appel réel (réseau coupé), "
        "soit elle n'a pas de client injectable."
    )


# Marque `xfail(strict=True)` posée par le testeur en aveugle avant que F1
# n'existe, retirée le 17/09/2026 à sa livraison. C'est `strict` qui l'a
# signalé : le test s'est mis à passer et la suite a échoué pour le dire,
# au lieu de laisser une marque périmée affirmer que rien ne marche.
def test_l_api_ne_lit_pas_l_environnement_hors_de_sa_bordure():
    """Protège la règle absolue 2 : « le cœur ne sait pas où il tourne ».

    `CLAUDE.md` n'autorise que `cli.py` et `config.py` à lire un TOML, une
    variable d'environnement ou un chemin utilisateur. Une API a besoin d'une
    bordure équivalente (port, URL de base, secrets d'hébergement) : ce test
    exige qu'elle soit **unique et nommée** — un seul fichier de composition —
    et non dispersée dans les routes. La décision demandée ici a été prise :
    `tests/test_invariants.py` nomme `api/exploitation.py` dans
    `CHEMINS_AUTORISES`, et ce test en est la contre-épreuve côté contrat.

    **Corrigé le 17/09/2026 — la méthode accusait la documentation, pas le
    code.** La version d'origine cherchait les sous-chaînes
    `("tomllib", "environ", "getenv", "expanduser", "home")` dans
    `ast.dump(arbre)`. Or `ast.dump` contient les **docstrings**, `CLAUDE.md`
    impose le français, et « environ » est un préfixe d'« environnement » :
    tout module qui *expliquait* qu'il ne lit pas l'environnement était compté
    coupable. Les quatre fichiers dénoncés le 17/09 étaient `__init__.py`
    (« elle a le droit de lire la configuration et l'environnement »),
    `application.py` (« qui lit l'environnement par exploitation.py »),
    `depots.py` (« Aucun des deux ne lit l'environnement ») et
    `exploitation.py` — seul ce dernier lit quoi que ce soit. Le test
    mesurait la prose, pas la propriété : un module qui appelait vraiment
    `os.environ` sans en parler se serait fondu dans le bruit.

    La correction ne relâche rien, elle resserre : on lit les **nœuds** de
    l'arbre au lieu de son texte, docstrings écartées, sur le vocabulaire
    précis qu'emploie déjà `tests/test_invariants.py` (`os.environ`, et non
    `environ`). Une seule bordure est toujours tolérée, et ce test échoue
    toujours si une deuxième s'ouvre — mais il échoue désormais pour ce qui
    est fait, pas pour ce qui est écrit.
    """
    fichiers = fichiers_python_de_l_api()
    assert fichiers, "aucune source d'API trouvée sous src/ourouler/{api,web,serveur}"
    coupables = sorted(f.name for f in fichiers if _lit_l_environnement(f.read_text("utf-8")))
    assert len(coupables) <= 1, (
        f"{len(coupables)} fichiers de l'API lisent l'environnement : {coupables}. "
        "La bordure doit être unique et nommée (règle absolue 2)."
    )


#: Les gestes qui font qu'un module sait où il tourne. Même vocabulaire que
#: `INTERDITS` de `tests/test_invariants.py` : un module de l'API n'a pas le
#: droit d'en faire plus que le cœur, à une porte près.
GESTES_D_ENVIRONNEMENT = (
    "os.environ",
    "os.getenv",
    "tomllib.load",
    "tomllib.loads",
    "Path.home",
    ".expanduser",
    "load_dotenv",
)


def _lit_l_environnement(source: str) -> bool:
    """Vrai si le module **fait** un de ces gestes — docstrings et commentaires exclus."""
    arbre = ast.parse(source)
    for noeud in ast.walk(arbre):
        # Une docstring est une expression-constante : on ne la lit pas.
        if isinstance(noeud, ast.Expr) and isinstance(noeud.value, ast.Constant):
            continue
        if isinstance(noeud, (ast.Attribute, ast.Call, ast.Name)):
            rendu = ast.unparse(noeud)
            if any(geste in rendu for geste in GESTES_D_ENVIRONNEMENT):
                return True
        if isinstance(noeud, ast.Import) and any(a.name == "tomllib" for a in noeud.names):
            return True
    return False


# --- auto-contrôle : un test négatif sans contre-épreuve ne prouve rien ------


def test_le_verificateur_de_refus_attrape_ce_qu_il_doit_attraper():
    """Contre-épreuve du socle lui-même, sur le modèle de `test_adv_invariants.py`.

    Les tests ci-dessus sont tous en `xfail` tant que l'API n'existe pas : sans
    cette contre-épreuve, rien ne prouverait qu'ils échouent pour la bonne
    raison plutôt que parce que le vérificateur est creux.
    """

    def reponse(corps, statut=400, media="application/json"):
        return httpx.Response(statut, json=corps, headers={"content-type": media})

    verifier_refus_exploitable(
        reponse({"code": "duree_hors_bornes", "message": "La durée doit être positive."}),
        "cas nominal",
    )
    with pytest.raises(AssertionError, match="500"):
        verifier_refus_exploitable(reponse({"code": "x", "message": "La durée."}, 500), "500 nu")
    with pytest.raises(AssertionError, match="code"):
        verifier_refus_exploitable(reponse({"message": "La durée est invalide."}), "sans code")
    with pytest.raises(AssertionError, match="français"):
        verifier_refus_exploitable(reponse({"code": "x", "message": "bad request"}), "anglais")
    with pytest.raises(AssertionError, match="trace Python"):
        verifier_refus_exploitable(reponse({"code": "x", "message": 'La durée.\nFile "boucle.py"'}), "trace")
    with pytest.raises(AssertionError, match="secret"):
        verifier_refus_exploitable(
            reponse({"code": "x", "message": f"La clé {CLE_INTERVALS_SENTINELLE} est refusée"}),
            "fuite",
        )


def test_le_client_asgi_du_socle_marche_bien_sous_la_coupure_reseau():
    """Contre-épreuve décisive : sans elle, tout ce dossier serait faux en silence.

    Les quatre-vingts tests d'API échouent aujourd'hui parce que l'API n'existe
    pas, et `xfail(strict=True)` doit crier quand elle arrivera. Encore
    faut-il qu'ils puissent alors passer : si `asyncio.run` ou
    `httpx.ASGITransport` butaient sur la coupure réseau *autonome* de ce
    dossier, ils continueraient d'échouer pour une raison qui n'a rien à voir
    avec le contrat, et personne ne s'en apercevrait jamais.

    On monte donc une application ASGI de trois lignes, ici, et on vérifie
    qu'elle répond. C'est aussi le seul endroit du dossier où l'on prouve que
    la coupure de `socket.socket.connect` laisse passer le `socketpair()` dont
    `asyncio` a besoin pour son tube interne.
    """

    async def application(scope, recevoir, envoyer):
        assert scope["type"] == "http"
        await envoyer(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"content-type", b"application/json")],
            }
        )
        await envoyer({"type": "http.response.body", "body": b'{"bonjour": "essai"}'})

    reponse = ClientApi(application).get("/quelque-part")
    assert reponse.status_code == 200
    assert reponse.json() == {"bonjour": "essai"}


def test_les_outils_de_decouverte_du_schema_fonctionnent():
    """Contre-épreuve de `route_pour` / `noms_de_parametres` / `parametre_nomme`."""
    schema = {
        "paths": {
            "/api/sortie": {
                "post": {
                    "parameters": [{"name": "proprietaire", "in": "query"}],
                    "requestBody": {
                        "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Demande"}}}
                    },
                }
            }
        },
        "components": {"schemas": {"Demande": {"properties": {"duree_min": {}, "heure_depart": {}}}}},
    }
    chemin, methode, operation = route_pour(schema, "sortie")
    assert (chemin, methode) == ("/api/sortie", "POST")
    noms = noms_de_parametres(schema, operation)
    assert noms == {"proprietaire", "duree_min", "heure_depart"}
    assert parametre_nomme(noms, "duree") == "duree_min"
    assert parametre_nomme(noms, "distance") is None
    with pytest.raises(ApiAbsente, match="aucune route"):
        route_pour(schema, "geocod")


def test_le_detecteur_de_bordure_voit_les_gestes_et_ignore_la_prose():
    """Contre-épreuve de `_lit_l_environnement`, et trace de ce qui a été corrigé.

    Les deux premiers cas sont ceux qui faisaient échouer le test à tort le
    17/09/2026 : une docstring française qui parle d'environnement, et un
    identifiant qui contient « environ » sans rien lire. Les trois suivants
    sont ceux qu'il doit continuer d'attraper.
    """
    assert not _lit_l_environnement('"""Ce module ne lit pas l\'environnement."""\n')
    assert not _lit_l_environnement("def environnement_du_service(environ):\n    return environ\n")
    assert _lit_l_environnement("import os\nx = os.environ.get('A')\n")
    assert _lit_l_environnement("import tomllib\n")
    assert _lit_l_environnement("from pathlib import Path\np = Path('~').expanduser()\n")


def test_le_depart_synthetique_est_en_mer_et_les_sentinelles_sont_inventees():
    """Règle absolue 1, vérifiée ici plutôt que supposée."""
    assert abs(DEPART_SYNTHETIQUE["latitude"]) < 1 and abs(DEPART_SYNTHETIQUE["longitude"]) < 1
    assert "SENTINELLE" in CLE_INTERVALS_SENTINELLE
    assert APPLICATIONS_CANDIDATES  # le repli existe, mais il est documenté comme moins bon
