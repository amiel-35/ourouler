"""Le dérivé d'une sortie, de bout en bout — fiche « choix de garder ou d'effacer ses fichiers d'origine ».

Ce que ce module prouve, sur des fichiers TCX synthétiques (`donnees_synthetiques`,
point fictif en mer) : l'import d'un compte qui ne garde pas ses fichiers
d'origine (`Cache(conserver_brut=False)`) dérive chaque sortie plutôt que
d'écrire le fichier, et `services.calibrer.calibrer_velo` calibre sur ce seul
dérivé un résultat **identique à 1e-9** à celui d'un compte qui garde ses
fichiers.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import donnees_synthetiques as synth
import pytest

from ourouler.activites.cache import Cache
from ourouler.activites.import_archive import importer
from ourouler.config import depuis_dict
from ourouler.noyau.meteo import HeureArchive
from ourouler.noyau.proprietaire import PROPRIETAIRE_LOCAL
from ourouler.services import calibrer, derive

COMPTE = "compte-essai"


class _ArchiveConstante:
    """Un vent de face constant et **non nul** — sans réseau (règle absolue 3).

    Un vent nul ne prouverait rien : une dérivation qui perdrait le vent en
    route (mauvais cap gardé, projection oubliée) donnerait le même résultat
    qu'une dérivation correcte si le vent qu'on lui fournit est déjà nul. Les
    deux branches (fichiers gardés ou pas) doivent voir le **même** vent pour
    que la comparaison à 1e-9 porte sur la dérivation, pas sur une archive
    qui répondrait à l'une et pas à l'autre.
    """

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


def _profil():
    return depuis_dict(
        {
            "depart": {"nom": "Point en mer", "latitude": 0.0, "longitude": 0.0},
            "cycliste": {"masse_kg": 72.5, "ftp_w": 250},
            "velos": [{"nom": "RCR", "usage": "route"}],
            "calibration": {"part_validation": 0.5},
            "historique_depuis": "2026-01-01",
        }
    )


def _depots(jours: list[date]) -> list[tuple[str, bytes]]:
    return [(f"sortie_{jour.isoformat()}.tcx", synth.tcx_synthetique(synth.ROUTE, jour)) for jour in jours]


def test_import_sans_conserver_brut_ne_laisse_aucun_fichier(tmp_path: Path):
    """`Cache(conserver_brut=False)` indexe sans jamais écrire le fichier — et
    dérive chaque sortie candidate (`services.derive.Derivateur`)."""
    cache = Cache(tmp_path, proprietaire=COMPTE, conserver_brut=False)
    jours = [date(2026, 1, j) for j in range(1, 13)]
    deriver = derive.Derivateur(cache=cache, client_archive=_ArchiveConstante())
    rapport = importer(cache, _depots(jours), deriver=deriver)

    assert rapport.importees == len(jours)
    assert rapport.fichiers_conserves is False
    assert rapport.derivees == len(jours)
    assert rapport.sans_vent == 0  # l'archive répond, le vent est bien capté
    # Aucun fichier brut sous le dossier du compte.
    assert not cache.brut.exists() or not any(cache.brut.iterdir())
    # Mais chaque sortie a bien un dérivé exploitable.
    entrees = cache.lister()
    gardees, motifs = derive.trier(cache, entrees)
    assert len(gardees) == len(jours), motifs


def test_calibration_identique_a_1e_9_selon_le_choix_de_conservation(tmp_path: Path):
    """La même archive, importée dans deux caches — l'un qui garde les
    fichiers, l'autre pas — donne la même calibration à 1e-9."""
    profil = _profil()
    velo = profil.velos[0]
    jours = [date(2026, 1, j) for j in range(1, 17)]
    depots = _depots(jours)

    cache_avec = Cache(tmp_path / "avec", proprietaire=COMPTE, conserver_brut=True)
    importer(cache_avec, depots)

    cache_sans = Cache(tmp_path / "sans", proprietaire=COMPTE, conserver_brut=False)
    deriver = derive.Derivateur(cache=cache_sans, client_archive=_ArchiveConstante())
    rapport_import = importer(cache_sans, depots, deriver=deriver)
    assert rapport_import.derivees == len(jours)
    assert rapport_import.sans_vent == 0  # même vent des deux côtés, voir `_ArchiveConstante`
    assert not any(cache_sans.brut.glob("*")) if cache_sans.brut.exists() else True

    resultat_avec = calibrer.calibrer_velo(profil, velo, cache_avec, client_archive=_ArchiveConstante())
    resultat_sans = calibrer.calibrer_velo(profil, velo, cache_sans, client_archive=_ArchiveConstante())

    a, s = resultat_avec.rapport.ajustement, resultat_sans.rapport.ajustement
    assert s.cda_m2 == pytest.approx(a.cda_m2, rel=1e-9)
    assert s.crr == pytest.approx(a.crr, rel=1e-9)
    assert s.rmse_w == pytest.approx(a.rmse_w, rel=1e-9)
    assert s.mae_w == pytest.approx(a.mae_w, rel=1e-9)
    assert resultat_sans.rapport.validation.mae == pytest.approx(
        resultat_avec.rapport.validation.mae, rel=1e-9
    )
    assert resultat_sans.n_calibrables == resultat_avec.n_calibrables


def test_calibration_par_sortie_mele_fichiers_gardes_et_derives(tmp_path: Path):
    """Le choix se lit **sortie par sortie**, jamais par compte : un compte qui a
    gardé, puis pas gardé, puis regardé ses fichiers a des sorties des deux
    sortes dans le même cache — la calibration doit les compter toutes."""
    profil = _profil()
    velo = profil.velos[0]
    cache = Cache(tmp_path, proprietaire=COMPTE, conserver_brut=True)

    # Huit sorties gardées (conserver_brut=True, comme avant tout choix).
    premieres = [date(2026, 1, j) for j in range(1, 9)]
    importer(cache, _depots(premieres))
    assert cache.brut.is_dir() and len(list(cache.brut.iterdir())) == len(premieres)

    # Passage à « ne pas garder » : dérive puis efface celles déjà là (le
    # geste de `services.derive.purger_avec_derivation`), puis huit sorties
    # de plus arrivent sans jamais avoir de fichier.
    rapport_purge = derive.purger_avec_derivation(cache, _ArchiveConstante())
    assert rapport_purge["fichiers_effaces"] == len(premieres)
    assert not any(cache.brut.iterdir()) if cache.brut.exists() else True
    cache.conserver_brut = False
    secondes = [date(2026, 2, j) for j in range(1, 9)]
    deriver = derive.Derivateur(cache=cache, client_archive=_ArchiveConstante())
    importer(cache, _depots(secondes), deriver=deriver)

    # Retour à « garder » : les imports suivants garderaient leur fichier,
    # mais rien ne revient sur les seize sorties déjà là.
    cache.conserver_brut = True

    resultat = calibrer.calibrer_velo(profil, velo, cache, client_archive=_ArchiveConstante())
    assert resultat.n_calibrables == len(premieres) + len(secondes)


def test_effacer_bruts_efface_tout_de_suite_sans_toucher_a_l_index(tmp_path: Path):
    """Le geste du bouton « ne plus garder » : `Cache.effacer_bruts` efface les
    fichiers déjà déposés, l'index et les entrées restent."""
    cache = Cache(tmp_path, proprietaire=COMPTE, conserver_brut=True)
    jours = [date(2026, 2, j) for j in range(1, 4)]
    importer(cache, _depots(jours))
    assert cache.brut.is_dir() and any(cache.brut.iterdir())
    entrees_avant = cache.lister()

    cache.conserver_brut = False
    effaces = cache.effacer_bruts()

    assert effaces == len(jours)
    assert not cache.brut.exists() or not any(cache.brut.iterdir())
    assert [e.identifiant for e in cache.lister()] == [e.identifiant for e in entrees_avant]


def test_effacer_bruts_ne_touche_pas_le_proprietaire_local(tmp_path: Path):
    """Le cache du mainteneur (ligne de commande) n'est jamais purgé par ce geste :
    ce n'est pas une archive, il n'y a rien à « ne plus garder »."""
    cache = Cache(tmp_path, proprietaire=PROPRIETAIRE_LOCAL)
    importer(cache, _depots([date(2026, 3, 1)]))
    assert cache.effacer_bruts() == 0
    assert any(cache.brut.iterdir())
