"""Export et suppression des données personnelles d'un compte.

Deux exigences de fond, une pour l'export, une pour la suppression — et
chacune a son piège.

**L'export** doit être lisible par la personne, et ne rendre **rien** de qui
que ce soit d'autre. `test_export_dun_proprietaire_ne_contient_rien_dun_autre`
plante deux propriétaires distincts et fouille l'archive du premier octet à
l'octet du dernier, comme le fait déjà `test_api_isolation_proprietaire.py`
pour les réponses JSON.

**La suppression** doit être vérifiable, et le piège est déjà arrivé une fois
dans ce sprint : le premier test d'isolation de L7.A passait au vert sur une
fuite totale, parce qu'un propriétaire écrasait les données de l'autre avant
le balayage. Les tests d'ici vérifient donc systématiquement, **par dépôt**,
que la donnée existait avant, puis qu'elle n'existe plus — jamais seulement
la seconde moitié.

Les outils du service à deux propriétaires (`_service_pour_deux`, `_planter`,
les sentinelles, `SessionDEssai`) viennent de `test_api_isolation_proprietaire`,
qui les a déjà écrits et prouvés : les redéfinir ici les ferait diverger en
silence. `activites`/`octets` viennent de `tests/conftest.py` (fixtures
partagées) et `tests/test_cache.py`. `droite`/`LUNDI` viennent de
`test_apprentissage_routes.py`.

**Aucun de ces tests ne touche les données réelles du mainteneur** — CLAUDE.md,
règle absolue 1 et 3. La vérification sur les vraies données (taille et liste
des entrées de l'export, jamais son contenu) est faite à part, hors suite de
tests, et rapportée dans le résumé du lot.
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest
from outils_api import PROPRIETAIRE_A, PROPRIETAIRE_B
from test_api_isolation_proprietaire import (
    MARQUE_A,
    MARQUE_B,
    PREFIXE_API,
    _planter,
    _service_pour_deux,
)
from test_apprentissage_routes import LUNDI, droite

from ourouler.activites.cache import Cache
from ourouler.api import vie_privee
from ourouler.api.depots import (
    DepotFichiers,
    DepotGenerations,
    DepotProfils,
    JournalServices,
    SocleVide,
)
from ourouler.api.proprietaire import Proprietaire
from ourouler.apprentissage.routes import BaseRoutes
from ourouler.services.apprentissage import NOM_BASE

#: Un propriétaire tiers, qui n'a jamais rien fait : sert de témoin « jamais
#: existé » — voir `test_la_suppression_rend_le_profil_comme_neuf`.
PROPRIETAIRE_JAMAIS_VU = "essai-proprietaire-jamais-vu"


# =============================================================================
# L'export ne montre rien d'un autre
# =============================================================================


def test_export_dun_proprietaire_ne_contient_rien_dun_autre(tmp_path: Path):
    """La preuve octet par octet, pas seulement champ par champ.

    On déballe l'archive entière (JSON, `.zwo`, `.gpx`) et on y cherche la
    sentinelle de l'autre comme sous-chaîne — la même méthode que
    `tests/api/test_api_isolation_proprietaire.py` applique aux réponses
    JSON. C'est pour que cette recherche reste possible que l'archive n'est
    pas compressée (`api/vie_privee.py`).
    """
    client = _service_pour_deux(tmp_path)
    ids_a = _planter(client, PROPRIETAIRE_A, MARQUE_A)
    _planter(client, PROPRIETAIRE_B, MARQUE_B)

    reponse = client.requete(
        "GET", f"{PREFIXE_API}/moi/export", headers={"x-essai-proprietaire": PROPRIETAIRE_A}
    )
    assert reponse.status_code == 200, reponse.text
    assert "zip" in reponse.headers.get("content-type", "")

    archive = zipfile.ZipFile(io.BytesIO(reponse.content))
    noms = archive.namelist()
    assert "LISEZ-MOI.txt" in noms, "un export que personne ne sait ouvrir ne remplit pas son office"
    assert "profil.json" in noms

    contenu = "\n".join(archive.read(nom).decode("utf-8", errors="replace") for nom in noms)
    assert MARQUE_A in contenu, (
        "l'export de A ne montre même pas ses propres données : le test ne prouve rien"
    )
    assert MARQUE_B not in contenu, "l'export de A contient une donnée de B"
    assert PROPRIETAIRE_B not in contenu, "l'export de A nomme B"
    assert ids_a["fichier"] in "\n".join(noms), "le fichier déposé par A n'est pas dans son export"


def test_export_dun_proprietaire_sans_rien_ne_plante_pas(tmp_path: Path):
    """Un propriétaire qui n'a jamais rien écrit reçoit quand même une archive valide."""
    client = _service_pour_deux(tmp_path)
    reponse = client.requete(
        "GET",
        f"{PREFIXE_API}/moi/export",
        headers={"x-essai-proprietaire": PROPRIETAIRE_JAMAIS_VU},
    )
    assert reponse.status_code == 200, reponse.text
    archive = zipfile.ZipFile(io.BytesIO(reponse.content))
    assert "LISEZ-MOI.txt" in archive.namelist()


# =============================================================================
# La suppression, par l'API — vérifiable route par route
# =============================================================================


def test_la_suppression_efface_le_profil_et_les_fichiers_de_ce_proprietaire(tmp_path: Path):
    """Le profil et les fichiers de A existaient, puis n'existent plus — et ses routes le disent.

    Ordre du test, et il compte : on prouve d'abord que la donnée **était**
    servie, puis qu'elle ne l'est plus. C'est exactement le piège que L7.A a
    rencontré une fois avec un test d'isolation qui passait au vert sur une
    fuite totale.
    """
    client = _service_pour_deux(tmp_path)
    ids = _planter(client, PROPRIETAIRE_A, MARQUE_A)
    entetes = {"x-essai-proprietaire": PROPRIETAIRE_A}

    avant_profil = client.requete("GET", f"{PREFIXE_API}/profil", headers=entetes)
    assert MARQUE_A in avant_profil.text, "le semis n'a pas pris : le test ne prouverait rien"
    avant_fichier = client.requete("GET", f"{PREFIXE_API}/fichiers/{ids['fichier']}", headers=entetes)
    assert avant_fichier.status_code == 200, "le fichier de A n'est pas servi avant suppression"

    suppression = client.requete("DELETE", f"{PREFIXE_API}/moi", headers=entetes)
    assert suppression.status_code == 200, suppression.text
    corps = suppression.json()
    assert corps["proprietaire"] == PROPRIETAIRE_A
    supprime = corps["donnees"]["supprime"]
    assert supprime["profil"] is True
    assert supprime["fichiers"] >= 1

    apres_profil = client.requete("GET", f"{PREFIXE_API}/profil", headers=entetes)
    assert MARQUE_A not in apres_profil.text, "le profil de A survit à sa propre suppression"
    apres_fichier = client.requete("GET", f"{PREFIXE_API}/fichiers/{ids['fichier']}", headers=entetes)
    assert apres_fichier.status_code == 404, (
        "le fichier de A est encore servi après suppression : la route ne répond pas "
        "comme si la personne n'avait jamais existé"
    )
    assert apres_fichier.json()["erreur"]["code"] == "fichier_introuvable"


def test_la_suppression_rend_le_profil_comme_neuf(tmp_path: Path):
    """Après suppression, A voit exactement ce qu'un inconnu qui n'a jamais rien écrit verrait.

    Plus fort qu'« absence de sentinelle » : le contenu du profil est comparé
    à celui d'un troisième propriétaire qui n'a jamais existé — `proprietaire`
    est exclu de la comparaison, seule ligne qui doit légitimement différer.

    **`GET /profil` répond 200 pour les deux, et c'est voulu** (Q66,
    `docs/journal/questions/questions_mainteneur.md` — décidé le 22/09/2026, après la fuite
    fermée le 21/09/2026 pour `depart`/`cycliste`/`velos`/`intervals`) : un
    compte hébergé sans surcharge — tout juste activé, ou tout juste
    supprimé — reste lisible, avec le **même comblement neutre**
    (`COMBLEMENT_EMBARQUEMENT`) que n'importe quel autre compte à ce stade.
    Ce que ce test prouve n'est donc plus « les deux échouent pareil », mais
    « les deux montrent exactement le même rien » — aucune trace de A ne
    reste dans ce que la route rend après sa suppression.
    """
    client = _service_pour_deux(tmp_path)
    _planter(client, PROPRIETAIRE_A, MARQUE_A)
    client.requete("DELETE", f"{PREFIXE_API}/moi", headers={"x-essai-proprietaire": PROPRIETAIRE_A})

    apres_a = client.requete("GET", f"{PREFIXE_API}/profil", headers={"x-essai-proprietaire": PROPRIETAIRE_A})
    jamais_vu = client.requete(
        "GET", f"{PREFIXE_API}/profil", headers={"x-essai-proprietaire": PROPRIETAIRE_JAMAIS_VU}
    )
    assert apres_a.status_code == jamais_vu.status_code == 200
    assert apres_a.json()["donnees"] == jamais_vu.json()["donnees"], (
        "le profil de A, après suppression, diffère encore de celui de quelqu'un qui n'a jamais existé"
    )


def test_la_suppression_dun_proprietaire_ne_touche_pas_l_autre(tmp_path: Path):
    """B existait avant la suppression de A, et existe encore après — rien n'est mis en commun."""
    client = _service_pour_deux(tmp_path)
    _planter(client, PROPRIETAIRE_A, MARQUE_A)
    ids_b = _planter(client, PROPRIETAIRE_B, MARQUE_B)
    entetes_b = {"x-essai-proprietaire": PROPRIETAIRE_B}

    avant = client.requete("GET", f"{PREFIXE_API}/profil", headers=entetes_b)
    assert MARQUE_B in avant.text

    client.requete("DELETE", f"{PREFIXE_API}/moi", headers={"x-essai-proprietaire": PROPRIETAIRE_A})

    apres = client.requete("GET", f"{PREFIXE_API}/profil", headers=entetes_b)
    assert MARQUE_B in apres.text, "la suppression de A a emporté le profil de B"
    fichier_b = client.requete("GET", f"{PREFIXE_API}/fichiers/{ids_b['fichier']}", headers=entetes_b)
    assert fichier_b.status_code == 200, "la suppression de A a emporté le fichier de B"


def test_supprimer_un_proprietaire_sans_donnees_ne_plante_pas(tmp_path: Path):
    """Idempotent : rien à effacer n'est pas une panne, c'est un compte à zéro."""
    client = _service_pour_deux(tmp_path)
    entetes = {"x-essai-proprietaire": PROPRIETAIRE_JAMAIS_VU}
    reponse = client.requete("DELETE", f"{PREFIXE_API}/moi", headers=entetes)
    assert reponse.status_code == 200, reponse.text
    assert reponse.json()["donnees"]["supprime"] == {
        "profil": False,
        "calibration": False,
        "journal_services": False,
        "fichiers": 0,
        "activites": 0,
        "generations_en_memoire": 0,
    }
    # Rejouable : une seconde suppression rend exactement la même chose.
    reponse2 = client.requete("DELETE", f"{PREFIXE_API}/moi", headers=entetes)
    assert reponse2.status_code == 200
    assert reponse2.json() == reponse.json()


def test_la_suppression_nomme_ce_qui_reste(tmp_path: Path):
    """Ce qui n'est pas effacé n'est jamais tu : `donnees.conserve` le dit."""
    client = _service_pour_deux(tmp_path)
    _planter(client, PROPRIETAIRE_A, MARQUE_A)
    reponse = client.requete("DELETE", f"{PREFIXE_API}/moi", headers={"x-essai-proprietaire": PROPRIETAIRE_A})
    conserve = reponse.json()["donnees"]["conserve"]
    assert "routes_apprises" in conserve
    assert "collectiv" in conserve["routes_apprises"]


# =============================================================================
# La suppression, dépôt par dépôt — pour ce que l'API n'expose pas en écriture
# =============================================================================
#
# `activites.cache.Cache` et `apprentissage.routes.BaseRoutes` n'ont pas de
# route d'écriture dans l'API (`/inventaire` et `/routes/{action}` sont en
# lecture seule). C'est déjà le choix de
# `test_une_ressource_d_un_proprietaire_n_est_pas_lisible_par_un_autre` dans
# `test_api_isolation_proprietaire.py` : on vérifie au dépôt, seul endroit où
# deux propriétaires distincts existent pour de vrai avant les comptes.


def test_suppression_du_cache_d_activites_efface_les_entrees_de_ce_proprietaire(
    tmp_path: Path, activites: Path
):
    a = Proprietaire(PROPRIETAIRE_A)
    cache_a = Cache(tmp_path / "cache", proprietaire=str(a))
    contenu = (activites / "boucle.gpx").read_bytes()
    identifiant = cache_a.ajouter(contenu, source="fichier", id_externe="essai-a", extension="gpx", meta={})

    assert cache_a.contient_identifiant(identifiant), "l'entrée n'a pas été écrite : rien à prouver"
    assert cache_a.chemin(identifiant).is_file()

    efface = cache_a.supprimer_tout()

    assert efface == 1
    assert not cache_a.contient_identifiant(identifiant)
    assert cache_a.lister() == []
    with pytest.raises(KeyError):
        cache_a.chemin(identifiant)


def test_suppression_du_cache_epargne_le_fichier_brut_encore_reference(tmp_path: Path, activites: Path):
    """Deux propriétaires aux octets identiques : effacer l'un ne prive pas l'autre.

    Depuis la contre-lecture Fable du 25/09/2026, chacun a **son** fichier
    brut (`Cache.__init__`) : la suppression de A efface le sien, jamais celui
    de B — et une fois les deux effacés, plus rien ne reste.
    """
    a, b = Proprietaire(PROPRIETAIRE_A), Proprietaire(PROPRIETAIRE_B)
    dossier = tmp_path / "cache"
    cache_a = Cache(dossier, proprietaire=str(a))
    cache_b = Cache(dossier, proprietaire=str(b))
    contenu = (activites / "boucle.gpx").read_bytes()
    id_a = cache_a.ajouter(contenu, source="fichier", id_externe="chez-a", extension="gpx", meta={})
    id_b = cache_b.ajouter(contenu, source="fichier", id_externe="chez-b", extension="gpx", meta={})
    assert id_a == id_b, "le test suppose un contenu identique — même sha256"
    brut_a, brut_b = cache_a.chemin(id_a), cache_b.chemin(id_b)
    assert brut_a.is_file() and brut_b.is_file()
    assert brut_a != brut_b, "le même contenu ne se partage plus entre comptes"

    cache_a.supprimer_tout()
    assert not brut_a.is_file(), "le fichier de A aurait dû partir avec lui"
    assert brut_b.is_file(), "la suppression de A a touché le fichier de B"
    assert cache_b.contient_identifiant(id_b), "B a perdu son activité à cause de la suppression de A"
    assert cache_b.relire(id_b) is not None

    cache_b.supprimer_tout()
    assert not brut_b.is_file()


def test_la_suppression_via_effacer_donnees_laisse_intactes_les_routes_apprises(tmp_path: Path):
    """`vie_privee.effacer_donnees` de bout en bout : les routes apprises ne bougent pas.

    C'est la doctrine (§10.2) : « les poids de routes appris restent
    collectifs […] et ne repartent pas avec un compte supprimé. » Le test
    vérifie que le chemin réel de suppression du lot la respecte, pas
    seulement qu'aucune méthode de suppression n'existe sur `BaseRoutes`.
    """
    a = Proprietaire(PROPRIETAIRE_A)
    chemin_base = tmp_path / "cache" / NOM_BASE
    base = BaseRoutes(chemin_base, proprietaire=str(a))
    base.ajouter_trace(droite(5), jour=LUNDI, id_sortie="sortie-1")
    assert base.troncons(), "rien à protéger : la trace n'a pas été enregistrée"
    assert base.sorties()

    # Un socle vide suffit : `effacer_donnees` n'a besoin que d'un dossier de
    # cache (changé le 21/09/2026 : `dossier_cache`, plus une `Config` —
    # voir `api/vie_privee.py`), pas d'un profil valide.
    dossier_donnees = tmp_path / "donnees"
    profils = DepotProfils(SocleVide(), dossier_donnees)
    fichiers = DepotFichiers(dossier_donnees)
    journal = JournalServices(dossier_donnees)
    generations = DepotGenerations()

    vie_privee.effacer_donnees(
        a,
        profils=profils,
        fichiers=fichiers,
        journal=journal,
        generations=generations,
        dossier_cache=tmp_path / "cache",
    )

    apres = BaseRoutes(chemin_base, proprietaire=str(a))
    assert apres.troncons(), "les tronçons de A ont disparu à la suppression"
    assert apres.sorties(), "les sorties de A ont disparu à la suppression"
