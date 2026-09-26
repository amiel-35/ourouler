"""Ce qu'un propriétaire peut récupérer de ses données, et en demander l'effacement.

Doctrine §10.2 : « RGPD par construction : export de toutes ses données et
suppression du compte (profil, fichiers, calibrations, clés) […] ».

**La frontière, non renégociable ici** (décision Q46, `docs/journal/questions/questions_mainteneur.md`,
doctrine §10.2) : le
**tracé** — la géographie d'une route, ses tags, son coût — est collectif ;
le **lien** — qui l'a roulée, quand, sur quelle sortie — est personnel. Et une
chose est déjà tranchée dans la doctrine, en toutes lettres : « les poids de
routes appris restent collectifs […] et ne repartent pas avec un compte
supprimé ». Ce module **exporte** donc un résumé en lecture seule de la
contribution du propriétaire aux routes apprises (c'est encore « à lui », au
sens où ce sont ses sorties qui l'ont produit), mais **n'efface jamais**
`apprentissage.routes.BaseRoutes` — ni les tronçons, ni les sorties.

**La correspondance compte/propriétaire, côté effacement** : la table
`comptes_proprietaires` (`migrations/0001_comptes.sql`) est branchée à
`effacer_donnees` — « c'est **elle** qu'on efface à la suppression d'un
compte » (doctrine §10.2). Quand un
`DepotComptes` est fourni, `effacer_donnees` retrouve le compte lié à ce
propriétaire et l'efface ; la cascade du schéma (`ON DELETE CASCADE` sur
`invitations.compte`, `sessions.compte` et `comptes_proprietaires.compte`)
emporte avec lui l'invitation, les sessions ouvertes et la correspondance
elle-même — un compte « supprimé » ne peut donc plus s'authentifier ni
rouvrir de session. Rien ne change pour un déploiement sans base de comptes
(mode personnel, ou hébergé sans `SessionParCookie`) : `comptes` reste
facultatif, et son absence n'efface que les données.

Ce qui part dans l'export : le profil (la surcharge JSON, jamais le socle du
serveur), sa calibration, le journal des services, les fichiers déposés
et générés, l'index et les fichiers bruts du cache d'activités, et un résumé
de la part du propriétaire dans les routes apprises. Ce que la suppression efface : tout ce
qui précède, sauf justement ce résumé des routes apprises, qui reste.

**Format de l'archive : ZIP, `ZIP_STORED` — non compressé, volontairement.**
Une archive personnelle ici pèse au pire quelques centaines de mégaoctets
(les fichiers bruts d'activités, en l'état du seul propriétaire mesuré) : le
gain de la compression est marginal face à ce que non-compressé achète —
`tests/api/test_api_isolation_proprietaire.py` cherche une sentinelle par
sous-chaîne dans le texte brut d'une réponse pour prouver qu'aucune donnée
d'un propriétaire ne fuit vers un autre ; un octet dans un flux `DEFLATE` ne
se retrouve plus tel quel dans le texte de la réponse, ce qui rendrait cette
preuve-là aveugle pour cette route précisément. Non compressée, l'archive
reste un flux d'octets où une sous-chaîne JSON en clair se cherche, et le
balayage existant la couvre sans rien y ajouter.
"""

from __future__ import annotations

import io
import json
import zipfile
from datetime import UTC, datetime
from pathlib import Path

from ourouler.activites.cache import Cache
from ourouler.api import taches_fond
from ourouler.api.comptes import DepotComptes
from ourouler.api.depots import DepotFichiers, DepotGenerations, DepotProfils, JournalServices
from ourouler.api.proprietaire import Proprietaire
from ourouler.apprentissage.commande import NOM_BASE
from ourouler.apprentissage.routes import BaseRoutes
from ourouler.physique.commande import NOM_CALIBRATION

#: Le fichier qui dit ce que chaque entrée de l'archive est — sans lui, un
#: export RGPD n'est lisible que par qui a écrit le code, et un export que
#: personne ne sait ouvrir ne remplit pas son office.
GABARIT_LISEZ_MOI = """Export ourouler — {proprietaire}
Généré le {quand}

Ce que contient cette archive :

- profil.json : ce que vous avez modifié depuis l'interface (départ, poids,
  FTP, vélos, position dans la zone, identifiants Intervals.icu). Le socle du
  serveur (URL de BRouter, modèles météo) n'y figure pas : il n'appartient à
  personne en particulier.
- {nom_calibration} : la calibration de vos vélos, si vous en avez lancé une
  depuis l'écran — ce que le calcul a trouvé sur vos sorties (paramètres,
  erreur de validation, fourchette du porte à porte).
- journal_services.json : la date du dernier succès de chaque service externe
  pour vous (Intervals.icu, Open-Meteo…) — sert uniquement à l'écran « plus lu
  depuis le… ».
- fichiers/ : vos séances déposées (.zwo, .mrc) et les GPX ou cartes que vous
  avez générés et gardés. fichiers/manifest.json liste chacun avec son nom
  d'origine et son type.
- activites/index.json : l'index de votre cache d'activités (date, durée,
  distance, sport, vélo…), une ligne par activité. activites/bruts/ contient
  les fichiers d'origine (.fit, .gpx, .tcx) tels qu'importés ou synchronisés.
- routes_apprises/ : un résumé de ce que vos sorties ont appris des routes —
  statistiques.json (kilomètres roulés par classe de route, de revêtement, de
  vitesse) et sorties.json (vos sorties apprises, avec leur jour). **Fourni
  pour information, et ceci ne part JAMAIS avec la suppression de votre
  compte : le mainteneur a tranché que les routes apprises restent
  collectives (doctrine du projet, §10.2), justement parce qu'elles décrivent
  la géographie plus que vous.**

Ce que la suppression du compte efface : le profil, la calibration, le journal des services,
les fichiers déposés et générés, et votre cache d'activités listés
ci-dessus. Ce qu'elle ne touche jamais : les routes apprises (paragraphe
précédent).
"""


def construire_export(
    qui: Proprietaire,
    *,
    profils: DepotProfils,
    fichiers: DepotFichiers,
    journal: JournalServices,
    dossier_cache: Path,
) -> bytes:
    """L'archive ZIP de tout ce que ce propriétaire possède. Voir le module.

    **`dossier_cache`, pas une `Config` entière** : ce module ne se sert que
    du dossier de cache, un réglage **serveur** qui ne
    dépend d'aucun profil de cycliste. Exiger une `Config` complète aurait
    fait échouer l'export d'un propriétaire qui n'a pas encore écrit son
    départ ou son cycliste — exactement le cas RGPD le plus élémentaire,
    « exporter les données de quelqu'un qui n'en a aucune ».
    """
    tampon = io.BytesIO()
    with zipfile.ZipFile(tampon, mode="w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr(
            "LISEZ-MOI.txt",
            GABARIT_LISEZ_MOI.format(
                proprietaire=qui,
                quand=datetime.now(UTC).isoformat(timespec="seconds"),
                nom_calibration=NOM_CALIBRATION,
            ),
        )
        archive.writestr(
            "profil.json",
            json.dumps(profils.surcharge(qui), ensure_ascii=False, indent=2, sort_keys=True),
        )
        calibration = profils.dossier(qui) / NOM_CALIBRATION
        if calibration.is_file():
            archive.write(calibration, NOM_CALIBRATION)
        archive.writestr(
            "journal_services.json",
            json.dumps(journal.tout(qui), ensure_ascii=False, indent=2, sort_keys=True),
        )
        _ajouter_fichiers(archive, qui, fichiers)
        _ajouter_activites(archive, qui, dossier_cache)
        _ajouter_routes_apprises(archive, qui, dossier_cache)
    return tampon.getvalue()


class TacheNonArretee(Exception):  # un état, pas une faute
    """Une tâche de fond du compte n'a pas rendu la main à temps : rien n'a été effacé.

    Une exception ordinaire, traduite en `ErreurApi` par la route **hors** de
    son bloc `with` : une `ErreurApi` (dataclass figée) qui traverse un
    `@contextmanager` fait échouer celui-ci sur l'écriture de son
    `__traceback__`, et le refus sortait en 500.
    """

    code = "tache_lourde_en_cours"
    message = (
        "une tâche de votre compte (import ou calibration) ne s'est pas encore arrêtée — "
        "rien n'a été effacé, réessayez dans une minute"
    )


def effacer_donnees(
    qui: Proprietaire,
    *,
    profils: DepotProfils,
    fichiers: DepotFichiers,
    journal: JournalServices,
    generations: DepotGenerations,
    dossier_cache: Path,
    comptes: DepotComptes | None = None,
) -> dict:
    """Efface les données personnelles de ce propriétaire. Voir le module pour ce qui reste.

    **`dossier_cache`, pas une `Config`** : même raison que
    `construire_export` — la suppression doit rester idempotente pour un
    propriétaire qui n'a jamais complété son profil, ce qu'exiger une
    `Config` entière casserait, puisque le socle partagé ne fournit pas les
    sections personnelles.

    `comptes` est **facultatif** : un déploiement sans base de comptes (mode
    personnel, ou hébergé sans `SessionParCookie`) n'a aucun compte à fermer,
    et l'appelant passe alors `None` — le résultat ne porte simplement pas la
    clé `"compte"`. Quand il est fourni, `DepotComptes.supprimer_compte_du_proprietaire`
    ferme le compte lié (mot de passe compris) et révoque du même coup ses
    sessions ouvertes, par la cascade du schéma (voir cette méthode).
    """
    # **Une seule suppression à la fois, par compte** : sans ce
    # verrou, un second `DELETE /moi` du même compte pendant que le premier
    # attend `annuler_et_attendre` (jusqu'à 120 s) attendrait lui aussi, sur
    # un second fil du serveur, pour un travail que le premier fait déjà —
    # voir `taches_fond.debuter_effacement`. Il refuse tout de suite.
    proprietaire = str(qui)
    taches_fond.debuter_effacement(proprietaire)
    try:
        # **Les tâches de fond ensuite** : un import en cours réécrirait sinon
        # ses lignes et ses fichiers bruts après l'effacement. On les annule, on attend qu'elles aient rendu
        # la main, et rien ne se relance pour ce compte tant que
        # l'effacement dure.
        with taches_fond.suspendre(proprietaire):
            if not taches_fond.annuler_et_attendre(proprietaire):
                raise TacheNonArretee
            return _effacer(
                qui,
                profils=profils,
                fichiers=fichiers,
                journal=journal,
                generations=generations,
                dossier_cache=dossier_cache,
                comptes=comptes,
            )
    finally:
        taches_fond.finir_effacement(proprietaire)


def _effacer(
    qui: Proprietaire,
    *,
    profils: DepotProfils,
    fichiers: DepotFichiers,
    journal: JournalServices,
    generations: DepotGenerations,
    dossier_cache: Path,
    comptes: DepotComptes | None,
) -> dict:
    cache = Cache(dossier_cache, proprietaire=str(qui))
    supprime = {
        "profil": profils.supprimer_profil(qui),
        "calibration": _supprimer_calibration(profils, qui),
        "journal_services": journal.supprimer(qui),
        "fichiers": fichiers.supprimer_tout(qui),
        "activites": cache.supprimer_tout(),
        "generations_en_memoire": generations.supprimer(qui),
    }
    if comptes is not None:
        supprime["compte"] = comptes.supprimer_compte_du_proprietaire(qui)
    # Rangement, sans conséquence s'il échoue : `fichiers/` a déjà disparu
    # (supprimer_tout le fait), il ne reste donc à retirer que le dossier
    # racine du propriétaire s'il est devenu vide.
    try:
        profils.dossier(qui).rmdir()
    except OSError:
        pass
    return {
        "supprime": supprime,
        "conserve": {
            "routes_apprises": (
                "les routes apprises de vos sorties restent : le mainteneur a tranché "
                "qu'elles sont collectives (doctrine du projet, §10.2) et elles ne "
                "repartent donc jamais avec un compte supprimé — voir aussi [[Q46]] dans "
                "docs/journal/questions/questions_mainteneur.md"
            )
        },
    }


def _supprimer_calibration(profils: DepotProfils, qui: Proprietaire) -> bool:
    """Efface la calibration de ce compte, rangée dans son dossier. Vrai si elle existait.

    En mode personnel, ce fichier n'existe pas : la calibration du
    cycliste local vit dans le dossier de cache, écrite par la ligne de commande,
    et n'appartient à aucun compte du service.
    """
    chemin = profils.dossier(qui) / NOM_CALIBRATION
    existait = chemin.is_file()
    chemin.unlink(missing_ok=True)
    return existait


def _ajouter_fichiers(archive: zipfile.ZipFile, qui: Proprietaire, fichiers: DepotFichiers) -> None:
    manifeste = []
    for fichier in fichiers.lister(qui):
        archive.write(fichier.chemin, f"fichiers/{fichier.identifiant}_{fichier.nom}")
        manifeste.append({"id": fichier.identifiant, "nom": fichier.nom, "type": fichier.type_contenu})
    archive.writestr("fichiers/manifest.json", json.dumps(manifeste, ensure_ascii=False, indent=2))


def _ajouter_activites(archive: zipfile.ZipFile, qui: Proprietaire, dossier_cache: Path) -> None:
    cache = Cache(dossier_cache, proprietaire=str(qui))
    entrees = cache.lister()
    index = [
        {
            "identifiant": e.identifiant,
            "source": e.source,
            "id_externe": e.id_externe,
            "debut": e.debut.isoformat() if e.debut else None,
            "duree_s": e.duree_s,
            "distance_m": e.distance_m,
            "puissance_moy_w": e.puissance_moy_w,
            "sport": e.sport,
            "appareil": e.appareil,
            "equipement": e.equipement,
            "meta": e.meta,
        }
        for e in entrees
    ]
    archive.writestr("activites/index.json", json.dumps(index, ensure_ascii=False, indent=2))
    for entree in entrees:
        if entree.chemin.is_file():
            archive.write(entree.chemin, f"activites/bruts/{entree.chemin.name}")


def _ajouter_routes_apprises(archive: zipfile.ZipFile, qui: Proprietaire, dossier_cache: Path) -> None:
    base = BaseRoutes(dossier_cache / NOM_BASE, proprietaire=str(qui))
    stats = base.statistiques()
    resume = {
        "km_total": stats.km_total,
        "km_semaine": stats.km_semaine,
        "mailles": stats.mailles,
        "sorties": stats.sorties,
        "km_par_highway": stats.km_par_highway,
        "km_par_maxspeed": stats.km_par_maxspeed,
        "km_par_surface": stats.km_par_surface,
        "cout_km_moyen": stats.cout_km_moyen,
    }
    archive.writestr("routes_apprises/statistiques.json", json.dumps(resume, ensure_ascii=False, indent=2))
    archive.writestr("routes_apprises/sorties.json", json.dumps(base.sorties(), ensure_ascii=False, indent=2))


__all__ = ["TacheNonArretee", "construire_export", "effacer_donnees"]
