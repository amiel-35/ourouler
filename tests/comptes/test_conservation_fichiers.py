"""`GET`/`PUT /moi/fichiers-origine` contre une vraie base de comptes.

Fiche « choix de garder ou d'effacer ses fichiers d'origine », sprint 12.
Même infrastructure que `test_vie_privee_comptes.py` (vrai compte, vraie
invitation, vraie session par cookie) : `SessionDEssai`
(`tests/api/`) n'a pas de base de comptes, donc pas de choix à lire ou
écrire — c'est justement ce que ce fichier éprouve.
"""

from __future__ import annotations

from pathlib import Path

from test_vie_privee_comptes import PREFIXE, _app, _entrer

from ourouler.activites.cache import Cache
from ourouler.api.base_de_donnees import ouvrir
from ourouler.api.comptes import DepotComptes

COURRIEL = "conservation-fichiers@exemple.invalid"


def _inviter_et_entrer(url_base: str, tmp_path: Path):
    with ouvrir(url_base) as cx:
        emise = DepotComptes(cx).inviter(COURRIEL)
    app = _app(url_base, tmp_path)
    proprietaire_id, cookies = _entrer(app, emise.jeton)
    return app, proprietaire_id, cookies


def test_l_etat_par_defaut_est_garder(url_base, tmp_path):
    from test_vie_privee_comptes import _requete

    app, _, cookies = _inviter_et_entrer(url_base, tmp_path)
    reponse = _requete(app, "GET", f"{PREFIXE}/moi/fichiers-origine", cookies=cookies)
    assert reponse.status_code == 200, reponse.text
    donnees = reponse.json()["donnees"]
    assert donnees["garder"] is True
    assert donnees["nombre_fichiers"] == 0
    # Personne n'a jamais posé ce choix : pas de date fictive prise à la
    # création du compte (`migrations/0003_conservation_fichiers.sql`).
    assert donnees["depuis"] is None


def test_passer_a_ne_pas_garder_efface_les_fichiers_deja_deposes(url_base, tmp_path):
    """Le geste central de la fiche : `PUT {garder: false}` efface tout de suite
    ce qui a déjà été déposé, sans toucher aux lignes de l'index."""
    from test_vie_privee_comptes import _requete

    from ourouler.api.proprietaire import Proprietaire

    app, proprietaire_id, cookies = _inviter_et_entrer(url_base, tmp_path)
    qui = Proprietaire(proprietaire_id)

    # Un fichier brut déposé directement dans le cache du compte (comme le
    # ferait un import réel) : c'est lui qui doit disparaître.
    from datetime import date

    import donnees_synthetiques as synth

    dossier_cache = app.state.ourouler.dossier_cache
    cache = Cache(dossier_cache, proprietaire=str(qui))
    cache.ajouter(
        synth.tcx_synthetique(synth.ROUTE, date(2026, 1, 1)),
        source="fichier",
        id_externe="sortie-essai",
        extension="tcx",
        meta={"fichier": "sortie-essai.tcx"},
    )
    assert any(cache.brut.iterdir()) or any((dossier_cache / "brut" / "comptes" / str(qui)).glob("*")), (
        "le fichier de test ne s'est pas écrit là où le test croit le chercher"
    )

    reponse = _requete(app, "PUT", f"{PREFIXE}/moi/fichiers-origine", cookies=cookies, json={"garder": False})
    assert reponse.status_code == 200, reponse.text
    donnees = reponse.json()["donnees"]
    assert donnees["garder"] is False
    assert donnees["fichiers_effaces"] >= 1

    cache_apres = Cache(dossier_cache, proprietaire=str(qui))
    assert len(cache_apres.lister()) == 1  # l'index garde la ligne
    dossier_brut = cache_apres.brut
    assert not dossier_brut.exists() or not any(dossier_brut.iterdir())

    # L'état se relit bien, y compris après le retour à « garder ».
    reponse_retour = _requete(
        app, "PUT", f"{PREFIXE}/moi/fichiers-origine", cookies=cookies, json={"garder": True}
    )
    assert reponse_retour.json()["donnees"]["garder"] is True
    etat = _requete(app, "GET", f"{PREFIXE}/moi/fichiers-origine", cookies=cookies)
    assert etat.json()["donnees"]["garder"] is True


def test_sans_compte_lie_le_put_est_refuse(url_base, tmp_path):
    """`SessionDEssai` — pas de base de comptes — répond `comptes_indisponibles` ;
    ici, une session par cookie mais servie sans jamais passer par `/entrer` :
    même refus, cette fois parce qu'aucun cookie n'est fourni du tout."""
    from test_vie_privee_comptes import _requete

    app = _app(url_base, tmp_path)
    reponse = _requete(app, "PUT", f"{PREFIXE}/moi/fichiers-origine", json={"garder": False})
    assert reponse.status_code == 401
