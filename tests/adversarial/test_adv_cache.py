"""L1.3 — cache local (fichiers bruts + index SQLite), mis à l'épreuve.

Cible : contrat §2. Le contrat ne dit pas d'où `ajouter` tire `debut`,
`duree_s`, `distance_m`, `puissance_moy_w` et `sport` — sa signature ne les
reçoit pas — donc on suppose ici qu'il relit le fichier avec le lecteur
L1.2. `equipement`, lui, n'est dans aucun fichier d'activité : il ne peut
venir que de `meta`, sous une clé que le contrat ne nomme pas. Les tests de
rattachement construisent donc leurs `EntreeCache` directement
(`test_adv_inventaire.py`) et ceux d'ici n'affirment rien sur `equipement`.
"""

from __future__ import annotations

import hashlib
import os
import sqlite3
import stat
from datetime import UTC, date, datetime
from pathlib import Path

import outils
import pytest

from ourouler.activites import cache as module_cache
from ourouler.noyau.erreurs import ErreurUtilisateur

CHAMPS_ENTREE = {
    "identifiant", "source", "id_externe", "debut", "duree_s", "distance_m",
    "puissance_moy_w", "sport", "appareil", "equipement", "chemin", "meta",
}


def _gpx(generateur, *, jours: int = 0, nb_points: int = 6) -> bytes:
    """Un GPX valide décalé de `jours` : contenu (donc sha256) différent à chaque décalage."""
    decalages = dict.fromkeys(range(nb_points), 86400 * jours)
    return generateur.gpx(nb_points=nb_points, decalages=decalages)


def _ajouter(cache, contenu: bytes, **surcharges) -> str:
    parametres = {"source": "fichier", "id_externe": None, "extension": "gpx", "meta": {}}
    parametres.update(surcharges)
    return cache.ajouter(contenu, **parametres)


# --- création du dossier -----------------------------------------------------


def test_dossier_absent_est_cree(tmp_path):
    """Contrat : `Cache(dossier)` crée `dossier/` et `dossier/index.sqlite`."""
    module = module_cache
    dossier = tmp_path / "jamais" / "cree" / "cache"
    cache = module.Cache(dossier)
    assert dossier.is_dir(), "le dossier de cache doit être créé, y compris ses parents"
    assert (dossier / "index.sqlite").is_file(), "l'index SQLite doit être créé"
    assert cache.lister() == [], "un cache neuf liste zéro entrée, il ne plante pas"


def test_cache_reouvert_retrouve_ses_entrees(tmp_path, generateur):
    module = module_cache
    dossier = tmp_path / "cache"
    identifiant = _ajouter(module.Cache(dossier), _gpx(generateur))
    autre = module.Cache(dossier)
    assert [e.identifiant for e in autre.lister()] == [identifiant], (
        "l'index doit être persistant d'une instance à l'autre"
    )


def test_index_corrompu_ne_remonte_pas_d_erreur_sqlite(tmp_path, generateur):
    """Un fichier texte à la place de l'index : erreur utilisateur, ou cache réparé.

    Ce qui est refusé, c'est qu'une `sqlite3.DatabaseError` brute remonte
    jusqu'à la CLI (code 1 + trace au lieu du code 2 et d'une ligne lisible).
    """
    module = module_cache
    dossier = tmp_path / "cache"
    dossier.mkdir()
    (dossier / "index.sqlite").write_text(
        "ceci n'est pas une base SQLite, c'est du texte\n" * 40, encoding="utf-8"
    )

    def _utiliser():
        cache = module.Cache(dossier)
        cache.lister()
        _ajouter(cache, _gpx(generateur))
        return cache

    cache, erreur = outils.robuste(
        _utiliser, quoi="Cache sur index corrompu", erreurs_acceptees=(ErreurUtilisateur,)
    )
    if erreur is None:  # le cache s'est réparé : il doit alors être utilisable
        assert len(cache.lister()) == 1
        with sqlite3.connect(dossier / "index.sqlite") as connexion:
            connexion.execute("select 1")


@pytest.mark.skipif(os.geteuid() == 0, reason="root écrit partout, le test n'a pas de sens")
def test_dossier_non_inscriptible(tmp_path):
    module = module_cache
    parent = tmp_path / "lecture_seule"
    parent.mkdir()
    parent.chmod(stat.S_IRUSR | stat.S_IXUSR)
    try:
        _, erreur = outils.robuste(
            lambda: module.Cache(parent / "cache"),
            quoi="Cache dans un dossier non inscriptible",
            erreurs_acceptees=(ErreurUtilisateur,),
        )
        assert erreur is not None, "un cache impossible à créer doit être signalé à l'utilisateur"
    finally:
        parent.chmod(stat.S_IRWXU)


# --- ajout -------------------------------------------------------------------


def test_identifiant_est_le_sha256_du_contenu(tmp_path, generateur):
    module = module_cache
    contenu = _gpx(generateur)
    identifiant = _ajouter(module.Cache(tmp_path / "cache"), contenu)
    assert identifiant == hashlib.sha256(contenu).hexdigest(), "contrat §2 : sha256 du contenu"


def test_ajout_idempotent(tmp_path, generateur):
    module = module_cache
    cache = module.Cache(tmp_path / "cache")
    contenu = _gpx(generateur)
    premier = _ajouter(cache, contenu, id_externe="a1")
    second = _ajouter(cache, contenu, id_externe="a1")
    assert premier == second
    assert len(cache.lister()) == 1, "ajouter deux fois le même contenu ne crée pas deux entrées"
    bruts = list((tmp_path / "cache" / "brut").iterdir())
    assert len(bruts) == 1, f"un seul fichier brut attendu, trouvé {[p.name for p in bruts]}"


def test_ajout_meme_contenu_sous_deux_identites(tmp_path, generateur):
    """Mêmes octets, deux `id_externe` : deux entrées, un seul fichier brut.

    Le cas réel est le triathlon : Intervals en fait deux activités, natation
    et vélo, qui citent le même FIT. Le test exigeait l'inverse (« le contenu
    est la clé ») jusqu'à la relecture du sprint 2 (point 2) : c'est ce qui
    faisait perdre une des deux, puis osciller `--synchroniser`.
    L'identifiant, lui, reste le sha256 : c'est le nom du fichier brut,
    partagé.
    """
    module = module_cache
    cache = module.Cache(tmp_path / "cache")
    contenu = _gpx(generateur)
    assert _ajouter(cache, contenu, source="intervals", id_externe="a1") == _ajouter(
        cache, contenu, source="intervals", id_externe="a2"
    )
    entrees = cache.lister()
    assert len(entrees) == 2, "deux activités distinctes = deux entrées"
    assert {e.id_externe for e in entrees} == {"a1", "a2"}
    bruts = list((tmp_path / "cache" / "brut").iterdir())
    assert len(bruts) == 1, f"un seul fichier brut attendu, trouvé {[p.name for p in bruts]}"
    assert cache.contient(source="intervals", id_externe="a1"), "la première ne doit pas s'effacer"
    assert cache.contient(source="intervals", id_externe="a2")


def test_contenus_differents_entrees_differentes(tmp_path, generateur):
    module = module_cache
    cache = module.Cache(tmp_path / "cache")
    identifiants = {_ajouter(cache, _gpx(generateur, jours=n)) for n in (0, 1, 2)}
    assert len(identifiants) == 3
    assert len(cache.lister()) == 3


def test_fichier_brut_stocke_tel_quel(tmp_path, generateur):
    module = module_cache
    dossier = tmp_path / "cache"
    cache = module.Cache(dossier)
    contenu = _gpx(generateur)
    identifiant = _ajouter(cache, contenu, extension="gpx")
    chemin = cache.chemin(identifiant)
    assert isinstance(chemin, Path)
    assert chemin.read_bytes() == contenu, "le brut doit être stocké octet pour octet"
    assert chemin == dossier / "brut" / f"{identifiant}.gpx", "contrat §2 : brut/<identifiant>.<extension>"


def test_chemin_ne_sort_pas_du_cache(tmp_path):
    """Un identifiant hostile ne doit pas permettre d'écrire ou de lire ailleurs."""
    module = module_cache
    dossier = tmp_path / "cache"
    cache = module.Cache(dossier)
    for hostile in ("../../etc/passwd", "/etc/passwd", "..", "a/../../b"):
        chemin, erreur = outils.robuste(
            lambda h=hostile: cache.chemin(h),
            quoi=f"chemin({hostile!r})",
            erreurs_acceptees=(ErreurUtilisateur, KeyError, LookupError),
        )
        if chemin is not None:
            assert dossier.resolve() in Path(chemin).resolve().parents, (
                f"chemin({hostile!r}) sort du cache : {chemin}"
            )


def test_injection_sql_dans_id_externe(tmp_path, generateur):
    module = module_cache
    cache = module.Cache(tmp_path / "cache")
    hostile = "x'); drop table activites; --"
    _ajouter(cache, _gpx(generateur), source="intervals", id_externe=hostile)
    assert cache.contient(source="intervals", id_externe=hostile) is True
    assert len(cache.lister()) == 1, "l'index doit avoir survécu à l'identifiant hostile"


def test_meta_survit_au_passage_par_sqlite(tmp_path, generateur):
    module = module_cache
    cache = module.Cache(tmp_path / "cache")
    meta = {
        "nom": "Sortie « été » — 30 °C",
        "liste": [1, 2.5, None, True],
        "imbrique": {"a": {"b": []}},
        "guillemet": "l'\"un\" et l'autre",
    }
    identifiant = _ajouter(cache, _gpx(generateur), meta=meta)
    (entree,) = [e for e in cache.lister() if e.identifiant == identifiant]
    outils.verifier_json(entree.meta, "EntreeCache.meta")
    for cle, valeur in meta.items():
        assert entree.meta.get(cle) == valeur, f'meta["{cle}"] altéré : {entree.meta.get(cle)!r}'


def test_meta_non_serialisable_refusee_proprement(tmp_path, generateur):
    module = module_cache
    cache = module.Cache(tmp_path / "cache")
    _, erreur = outils.robuste(
        lambda: _ajouter(cache, _gpx(generateur), meta={"t": datetime(2026, 4, 12, tzinfo=UTC)}),
        quoi="ajouter(meta non sérialisable)",
        erreurs_acceptees=(ErreurUtilisateur, TypeError),
    )
    if erreur is None:
        outils.verifier_json(cache.lister()[0].meta, "EntreeCache.meta")


@pytest.mark.parametrize("extension", ["GPX", ".gpx", "gpx"])
def test_extension_en_casse_ou_avec_point(tmp_path, generateur, extension):
    module = module_cache
    cache = module.Cache(tmp_path / "cache")
    identifiant, erreur = outils.robuste(
        lambda: _ajouter(cache, _gpx(generateur), extension=extension),
        quoi=f"ajouter(extension={extension!r})",
        erreurs_acceptees=(ErreurUtilisateur,),
    )
    if identifiant is not None:
        chemin = cache.chemin(identifiant)
        assert chemin.is_file(), f"fichier brut absent pour l'extension {extension!r}"
        assert chemin.suffix.lower() == ".gpx", f"suffixe inattendu : {chemin.name}"


def test_contenu_vide_ou_illisible_refuse_proprement(tmp_path):
    module = module_cache
    cache = module.Cache(tmp_path / "cache")
    for contenu in (b"", b"\x00\x01\x02", b"<gpx"):
        _, erreur = outils.robuste(
            lambda c=contenu: _ajouter(cache, c),
            quoi=f"ajouter({contenu!r})",
            erreurs_acceptees=(ErreurUtilisateur,),
        )
        assert erreur is not None, f"un contenu illisible ({contenu!r}) ne doit pas entrer au cache"


# --- contient ----------------------------------------------------------------


def test_contient_distingue_la_source(tmp_path, generateur):
    module = module_cache
    cache = module.Cache(tmp_path / "cache")
    assert cache.contient(source="intervals", id_externe="a1") is False
    _ajouter(cache, _gpx(generateur), source="intervals", id_externe="a1")
    assert cache.contient(source="intervals", id_externe="a1") is True
    assert cache.contient(source="fichier", id_externe="a1") is False, (
        "la paire (source, id_externe) est la clé, pas l'identifiant seul"
    )
    assert cache.contient(source="intervals", id_externe="a2") is False


def test_contient_sur_cache_vide_et_id_absurde(tmp_path):
    module = module_cache
    cache = module.Cache(tmp_path / "cache")
    for id_externe in ("", "  ", "%", "1 or 1=1"):
        assert cache.contient(source="intervals", id_externe=id_externe) is False


# --- lister ------------------------------------------------------------------


def _remplir_trois_jours(module, dossier, generateur):
    cache = module.Cache(dossier)
    for n in (0, 10, 20):  # 2026-04-12, -22, 2026-05-02
        _ajouter(cache, _gpx(generateur, jours=n), source="fichier", id_externe=f"j{n}")
    return cache


def test_lister_sans_bornes_rend_tout(tmp_path, generateur):
    module = module_cache
    cache = _remplir_trois_jours(module, tmp_path / "cache", generateur)
    entrees = cache.lister()
    assert len(entrees) == 3
    for entree in entrees:
        outils.exiger_champs(type(entree), CHAMPS_ENTREE)
        outils.verifier_utc(entree.debut, "EntreeCache.debut")
        assert Path(entree.chemin).is_file(), "EntreeCache.chemin doit désigner le fichier brut"
        outils.verifier_json(entree.meta, "EntreeCache.meta")
        assert entree.duree_s is None or entree.duree_s >= 0


def test_lister_filtre_sur_les_bornes(tmp_path, generateur):
    module = module_cache
    cache = _remplir_trois_jours(module, tmp_path / "cache", generateur)
    depuis_recent = cache.lister(depuis=date(2026, 4, 20))
    assert len(depuis_recent) == 2, "seules les sorties du 22/04 et du 02/05 sont attendues"
    jusqu_ancien = cache.lister(jusqua=date(2026, 4, 15))
    assert len(jusqu_ancien) == 1
    assert cache.lister(depuis=date(2026, 4, 1), jusqua=date(2026, 12, 31)) == cache.lister()
    assert cache.lister(depuis=date(2030, 1, 1)) == []


def test_lister_bornes_inversees_ne_plante_pas(tmp_path, generateur):
    module = module_cache
    cache = _remplir_trois_jours(module, tmp_path / "cache", generateur)
    assert cache.lister(depuis=date(2026, 12, 31), jusqua=date(2026, 1, 1)) == []


def test_lister_bornes_de_type_inattendu(tmp_path, generateur):
    """`datetime` au lieu de `date`, chaîne ISO : refus propre ou tolérance."""
    module = module_cache
    cache = _remplir_trois_jours(module, tmp_path / "cache", generateur)
    for borne in (datetime(2026, 4, 20, 12, tzinfo=UTC), "2026-04-20"):
        outils.robuste(
            lambda b=borne: cache.lister(depuis=b),
            quoi=f"lister(depuis={borne!r})",
            erreurs_acceptees=(ErreurUtilisateur, TypeError),
        )


# --- indexer_dossier ---------------------------------------------------------


def test_indexer_dossier(tmp_path, hostiles, generateur):
    module = module_cache
    source = tmp_path / "a_importer"
    source.mkdir()
    for nom in ("nominal.fit", "nominal.gpx", "nominal.tcx", "fit_sans_gps.fit"):
        (source / nom).write_bytes(hostiles[nom].read_bytes())
    (source / "notes.txt").write_text("rien à voir", encoding="utf-8")
    (source / "profil.json").write_text("{}", encoding="utf-8")

    cache = module.Cache(tmp_path / "cache")
    assert cache.indexer_dossier(source) == 4, "les 4 fichiers d'activité, et eux seuls"
    assert len(cache.lister()) == 4
    assert cache.indexer_dossier(source) == 0, "réimporter le même dossier n'ajoute rien"
    assert len(cache.lister()) == 4


def test_indexer_dossier_extensions_en_majuscules(tmp_path, hostiles):
    module = module_cache
    source = tmp_path / "majuscules"
    source.mkdir()
    (source / "nominal_maj.GPX").write_bytes(hostiles["nominal_maj.GPX"].read_bytes())
    cache = module.Cache(tmp_path / "cache")
    assert cache.indexer_dossier(source) == 1, "l'extension .GPX doit être reconnue (contrat §1)"


def test_indexer_dossier_deux_noms_un_seul_contenu(tmp_path, hostiles):
    """Deux noms = deux entrées, un seul fichier brut — et le second import n'ajoute rien.

    Le test exigeait « même contenu = une seule entrée » jusqu'à la relecture
    du sprint 2 (point 2) : c'est ce qui faisait disparaître une des deux
    moitiés d'un triathlon. L'identité d'une entrée est désormais
    `(source, id_externe)`, le fichier brut restant partagé par contenu.
    """
    module = module_cache
    source = tmp_path / "doublons"
    source.mkdir()
    octets = hostiles["nominal.gpx"].read_bytes()
    (source / "copie_a.gpx").write_bytes(octets)
    (source / "copie_b.gpx").write_bytes(octets)
    cache = module.Cache(tmp_path / "cache")
    ajoutes = cache.indexer_dossier(source)
    assert ajoutes == 2, f"deux noms, deux entrées, rapporté {ajoutes}"
    assert len(cache.lister()) == 2, "deux noms = deux entrées"
    bruts = list((tmp_path / "cache" / "brut").iterdir())
    assert len(bruts) == 1, f"un seul fichier brut attendu, trouvé {[p.name for p in bruts]}"
    assert cache.indexer_dossier(source) == 0, "le second import ne doit rien ajouter"
    assert len(cache.lister()) == 2, "le second import ne doit rien dupliquer"


def test_indexer_dossier_avec_un_fichier_corrompu(tmp_path, hostiles):
    """Un intrus illisible ne doit ni faire planter l'import ni rester silencieux."""
    module = module_cache
    source = tmp_path / "melange"
    source.mkdir()
    (source / "bon.gpx").write_bytes(hostiles["nominal.gpx"].read_bytes())
    (source / "casse.gpx").write_bytes(hostiles["xml_invalide.gpx"].read_bytes())
    (source / "vide.fit").write_bytes(b"")
    cache = module.Cache(tmp_path / "cache")
    ajoutes, erreur = outils.robuste(
        lambda: cache.indexer_dossier(source),
        quoi="indexer_dossier(dossier contenant des fichiers cassés)",
        erreurs_acceptees=(ErreurUtilisateur,),
    )
    if erreur is None:
        assert ajoutes == 1, f"seul le fichier lisible doit être ajouté, rapporté {ajoutes}"
        assert len(cache.lister()) == 1


def test_indexer_dossier_absent_ou_fichier(tmp_path, hostiles):
    module = module_cache
    cache = module.Cache(tmp_path / "cache")
    with pytest.raises(ErreurUtilisateur):
        cache.indexer_dossier(tmp_path / "jamais_vu")
    with pytest.raises(ErreurUtilisateur):
        cache.indexer_dossier(hostiles["nominal.gpx"])


def test_indexer_dossier_vide(tmp_path):
    module = module_cache
    vide = tmp_path / "vide"
    vide.mkdir()
    cache = module.Cache(tmp_path / "cache")
    assert cache.indexer_dossier(vide) == 0
    assert cache.lister() == []
