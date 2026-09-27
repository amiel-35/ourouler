"""`GET`/`PUT /moi/fichiers-origine` contre une vraie base de comptes.

Fiche « choix de garder ou d'effacer ses fichiers d'origine », sprint 12.
Même infrastructure que `test_vie_privee_comptes.py` (vrai compte, vraie
invitation, vraie session par cookie) : `SessionDEssai`
(`tests/api/`) n'a pas de base de comptes, donc pas de choix à lire ou
écrire — c'est justement ce que ce fichier éprouve.

Relecture indépendante : passer à « ne pas garder » lance une tâche de fond
(dérive puis efface, `services.derive.purger_avec_derivation`) — comme un
import, elle appelle l'archive météo. `_ArchiveConstante` en tient lieu ici
(vent non nul, pour ne pas laisser passer une dérivation qui perdrait le
vent en silence) : aucun réseau (règle absolue 3).
"""

from __future__ import annotations

import time
from datetime import UTC, date, datetime
from pathlib import Path

import donnees_synthetiques as synth
from test_vie_privee_comptes import PREFIXE, _app, _entrer, _requete

from ourouler.activites.cache import Cache
from ourouler.api import taches_fond
from ourouler.api.base_de_donnees import ouvrir
from ourouler.api.comptes import DepotComptes
from ourouler.api.proprietaire import Proprietaire
from ourouler.noyau.meteo import HeureArchive

COURRIEL = "conservation-fichiers@exemple.invalid"


class _ArchiveConstante:
    """Un vent de face constant et non nul, sans réseau — voir le module."""

    def horaires(self, lat: float, lon: float, jour: date) -> list[HeureArchive]:
        del lat, lon
        debut = datetime(jour.year, jour.month, jour.day, tzinfo=UTC)
        return [
            HeureArchive(
                t=debut.replace(hour=h),
                vent_kmh=18.0,
                vent_depuis_deg=90.0,
                temp_c=15.0,
                pression_hpa=1013.25,
            )
            for h in range(24)
        ]


def _inviter_et_entrer(url_base: str, tmp_path: Path, *, client_archive: object | None = None):
    with ouvrir(url_base) as cx:
        emise = DepotComptes(cx).inviter(COURRIEL)
    app = _app(url_base, tmp_path, client_archive=client_archive)
    proprietaire_id, cookies = _entrer(app, emise.jeton)
    return app, proprietaire_id, cookies


def _attendre_conservation(app, cookies: dict[str, str], id_tache: str, delai_max_s: float = 10.0) -> dict:
    debut = time.monotonic()
    while True:
        reponse = _requete(app, "GET", f"{PREFIXE}/moi/fichiers-origine/{id_tache}", cookies=cookies)
        assert reponse.status_code == 200, reponse.text
        donnees = reponse.json()["donnees"]
        if donnees["statut"] != "en_cours":
            return donnees
        if time.monotonic() - debut > delai_max_s:
            raise AssertionError(f"effacement {id_tache} toujours en_cours après {delai_max_s} s")
        time.sleep(0.02)


def test_l_etat_par_defaut_est_garder(url_base, tmp_path):
    app, _, cookies = _inviter_et_entrer(url_base, tmp_path)
    reponse = _requete(app, "GET", f"{PREFIXE}/moi/fichiers-origine", cookies=cookies)
    assert reponse.status_code == 200, reponse.text
    donnees = reponse.json()["donnees"]
    assert donnees["garder"] is True
    assert donnees["nombre_fichiers"] == 0
    # Personne n'a jamais posé ce choix : pas de date fictive prise à la
    # création du compte (`migrations/0004_conservation_fichiers.sql`).
    assert donnees["depuis"] is None


def test_passer_a_ne_pas_garder_derive_puis_efface_les_fichiers_deja_deposes(url_base, tmp_path):
    """Le geste central de la fiche : `PUT {garder: false}` dérive chaque sortie
    calibrable (l'archive météo est encore appelée), puis efface tout ce qui a
    déjà été déposé, sans toucher aux lignes de l'index."""
    app, proprietaire_id, cookies = _inviter_et_entrer(url_base, tmp_path, client_archive=_ArchiveConstante())
    qui = Proprietaire(proprietaire_id)

    # Un fichier brut déposé directement dans le cache du compte (comme le
    # ferait un import réel), assez long pour être candidat à la calibration.
    dossier_cache = app.state.ourouler.dossier_cache
    cache = Cache(dossier_cache, proprietaire=str(qui))
    cache.ajouter(
        synth.tcx_synthetique(synth.ROUTE, date(2026, 1, 1)),
        source="fichier",
        id_externe="sortie-essai",
        extension="tcx",
        meta={"fichier": "sortie-essai.tcx", "sport": "Ride", "puissance_moy_w": 180.0},
    )
    assert cache.brut.is_dir() and any(cache.brut.iterdir()), (
        "le fichier de test ne s'est pas écrit là où le test croit le chercher"
    )

    reponse = _requete(app, "PUT", f"{PREFIXE}/moi/fichiers-origine", cookies=cookies, json={"garder": False})
    assert reponse.status_code == 202, reponse.text
    donnees = reponse.json()["donnees"]
    assert donnees["garder"] is False
    assert donnees["tache"] is not None

    fini = _attendre_conservation(app, cookies, donnees["tache"]["id"])
    assert fini["statut"] == "fini", fini
    assert fini["rapport"]["derivees"] == 1
    assert fini["rapport"]["fichiers_effaces"] >= 1

    cache_apres = Cache(dossier_cache, proprietaire=str(qui))
    assert len(cache_apres.lister()) == 1  # l'index garde la ligne
    dossier_brut = cache_apres.brut
    assert not dossier_brut.exists() or not any(dossier_brut.iterdir())
    # Le dérivé, lui, est là : la sortie n'est pas « à redéposer ».
    lu = cache_apres.lire_derive(cache_apres.lister()[0].identifiant)
    assert lu is not None and lu[2] is not None

    # L'état se relit bien, y compris après le retour à « garder » — synchrone,
    # rien à dériver ni à effacer pour revenir en arrière.
    reponse_retour = _requete(
        app, "PUT", f"{PREFIXE}/moi/fichiers-origine", cookies=cookies, json={"garder": True}
    )
    assert reponse_retour.status_code == 200, reponse_retour.text
    assert reponse_retour.json()["donnees"]["garder"] is True
    etat = _requete(app, "GET", f"{PREFIXE}/moi/fichiers-origine", cookies=cookies)
    assert etat.json()["donnees"]["garder"] is True


def test_bascule_refusee_tant_qu_une_tache_lourde_tourne(url_base, tmp_path):
    """Le verrou serveur entier (`api/taches_fond.VERROU`) protège aussi l'effacement :
    un import ou une calibration en cours refuse le passage à « ne pas garder »,
    exactement comme `test_api_calibration.test_une_tache_lourde_en_cours_refuse…`."""
    app, _, cookies = _inviter_et_entrer(url_base, tmp_path, client_archive=_ArchiveConstante())
    assert taches_fond.VERROU.acquire(blocking=False)
    try:
        reponse = _requete(
            app, "PUT", f"{PREFIXE}/moi/fichiers-origine", cookies=cookies, json={"garder": False}
        )
    finally:
        taches_fond.VERROU.release()
    assert reponse.status_code == 409, reponse.text
    assert reponse.json()["erreur"]["code"] == "tache_lourde_en_cours"
    # Le choix lui-même n'a pas été posé : le refus est complet, pas à moitié.
    etat = _requete(app, "GET", f"{PREFIXE}/moi/fichiers-origine", cookies=cookies)
    assert etat.json()["donnees"]["garder"] is True
    # Le verrou rendu, la bascule passe.
    reponse_apres = _requete(
        app, "PUT", f"{PREFIXE}/moi/fichiers-origine", cookies=cookies, json={"garder": False}
    )
    assert reponse_apres.status_code == 202, reponse_apres.text


def test_isolation_entre_deux_comptes_reels_dont_un_fichier_commun(url_base, tmp_path):
    """A passe à « ne pas garder », B garde les siens — y compris un fichier au
    contenu identique à celui de A, déposé par les deux avant la séparation
    par compte (`brut/` commun, `activites/cache.py`). B ne doit rien perdre.
    """
    app, proprietaire_a, cookies_a = _inviter_et_entrer(
        url_base, tmp_path, client_archive=_ArchiveConstante()
    )
    with ouvrir(url_base) as cx:
        emise_b = DepotComptes(cx).inviter("conservation-fichiers-b@exemple.invalid")
    proprietaire_b, cookies_b = _entrer(app, emise_b.jeton)

    dossier_cache = app.state.ourouler.dossier_cache
    cache_a = Cache(dossier_cache, proprietaire=proprietaire_a)
    contenu_commun = synth.tcx_synthetique(synth.ROUTE, date(2026, 1, 1))
    identifiant = cache_a.ajouter(
        contenu_commun,
        source="fichier",
        id_externe="sortie-commune",
        extension="tcx",
        meta={"fichier": "commune.tcx", "sport": "Ride", "puissance_moy_w": 180.0},
    )
    # Simule le dépôt d'avant la séparation par compte : B cite le même
    # fichier, dans le `brut/` commun — voir `activites/cache.py`,
    # `test_cache.test_effacer_bruts_ne_touche_pas_le_fichier_partage_d_un_autre_compte`.
    partage = dossier_cache / "brut" / f"{identifiant}.tcx"
    cache_a.chemin(identifiant).replace(partage)
    cache_b_sans_ecriture = Cache(dossier_cache, proprietaire=proprietaire_b, conserver_brut=False)
    cache_b_sans_ecriture.ajouter(
        contenu_commun, source="fichier", id_externe="sortie-commune", extension="tcx", meta={}
    )
    # Et un fichier propre à B, sans rapport avec A.
    cache_b = Cache(dossier_cache, proprietaire=proprietaire_b)
    cache_b.ajouter(
        synth.tcx_synthetique(synth.ROUTE, date(2026, 1, 2)),
        source="fichier",
        id_externe="sortie-b",
        extension="tcx",
        meta={"fichier": "b.tcx", "sport": "Ride", "puissance_moy_w": 180.0},
    )
    reponse = _requete(
        app, "PUT", f"{PREFIXE}/moi/fichiers-origine", cookies=cookies_a, json={"garder": False}
    )
    assert reponse.status_code == 202, reponse.text
    id_tache = reponse.json()["donnees"]["tache"]["id"]
    fini = _attendre_conservation(app, cookies_a, id_tache)
    assert fini["statut"] == "fini", fini

    # B n'a rien perdu : ni le fichier partagé, ni le sien.
    cache_b_apres = Cache(dossier_cache, proprietaire=proprietaire_b)
    for entree in cache_b_apres.lister():
        assert entree.chemin.is_file(), entree.identifiant
        assert cache_b_apres.relire(entree.identifiant) is not None
    # B garde toujours ses fichiers : l'état de son compte n'a pas bougé.
    etat_b = _requete(app, "GET", f"{PREFIXE}/moi/fichiers-origine", cookies=cookies_b)
    assert etat_b.json()["donnees"]["garder"] is True


def test_sans_compte_lie_le_put_est_refuse(url_base, tmp_path):
    """`SessionDEssai` — pas de base de comptes — répond `comptes_indisponibles` ;
    ici, une session par cookie mais servie sans jamais passer par `/entrer` :
    même refus, cette fois parce qu'aucun cookie n'est fourni du tout."""
    app = _app(url_base, tmp_path)
    reponse = _requete(app, "PUT", f"{PREFIXE}/moi/fichiers-origine", json={"garder": False})
    assert reponse.status_code == 401
