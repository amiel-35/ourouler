"""Ce qu'un propriétaire peut récupérer de ses données, et en demander l'effacement.

Lot L7.B du sprint 7 (`docs/sprint7_contrat.md`). Doctrine §10.2 : « RGPD par
construction : export de toutes ses données et suppression du compte (profil,
fichiers, calibrations, clés) […] » — calendrier révisé le 17/09/2026 (le
principe ne bouge pas, seul le moment où il devient obligatoire change), mais
rien n'empêche de l'écrire dès que le sprint le demande.

**La frontière, posée par le mainteneur le 17/09/2026 et non renégociable
ici** ([[Q46]] dans `docs/questions_mainteneur.md`, doctrine §10.2) : le
**tracé** — la géographie d'une route, ses tags, son coût — est collectif ;
le **lien** — qui l'a roulée, quand, sur quelle sortie — est personnel. Et une
chose est déjà tranchée dans la doctrine, en toutes lettres : « les poids de
routes appris restent collectifs […] et ne repartent pas avec un compte
supprimé ». Ce module **exporte** donc un résumé en lecture seule de la
contribution du propriétaire aux routes apprises (c'est encore « à lui », au
sens où ce sont ses sorties qui l'ont produit), mais **n'efface jamais**
`apprentissage.routes.BaseRoutes` — ni les tronçons, ni les sorties.

**Mise à jour du lot RGPD-compte, qui ferme [[Q46]] côté effacement** : la
table de correspondance compte/propriétaire existe désormais
(`comptes_proprietaires`, `migrations/0001_comptes.sql`, lot L7.2-A du
18/09/2026), et c'est justement ce lot-ci qui la branche à `effacer_donnees`
— « c'est **elle** qu'on efface à la suppression d'un compte » (doctrine
§10.2) est maintenant vrai en code, pas seulement en intention. Quand un
`DepotComptes` est fourni, `effacer_donnees` retrouve le compte lié à ce
propriétaire et l'efface ; la cascade du schéma (`ON DELETE CASCADE` sur
`invitations.compte`, `sessions.compte` et `comptes_proprietaires.compte`)
emporte avec lui l'invitation, les sessions ouvertes et la correspondance
elle-même — un compte « supprimé » ne peut donc plus s'authentifier ni
rouvrir de session. Rien ne change pour un déploiement sans base de comptes
(mode personnel, ou hébergé sans `SessionParCookie`) : `comptes` reste
facultatif, et son absence laisse le comportement d'avant ce lot.

Ce qui part dans l'export : le profil (la surcharge JSON, jamais le socle du
serveur), le journal des services, les fichiers déposés et générés, l'index
et les fichiers bruts du cache d'activités, et un résumé de la part du
propriétaire dans les routes apprises. Ce que la suppression efface : tout ce
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

from ourouler.activites.cache import Cache
from ourouler.api.comptes import DepotComptes
from ourouler.api.depots import DepotFichiers, DepotGenerations, DepotProfils, JournalServices
from ourouler.api.proprietaire import Proprietaire
from ourouler.apprentissage.commande import NOM_BASE
from ourouler.apprentissage.routes import BaseRoutes
from ourouler.config import Config

#: Le fichier qui dit ce que chaque entrée de l'archive est — sans lui, un
#: export RGPD n'est lisible que par qui a écrit le code (contrat §L7.B :
#: « un export que personne ne sait ouvrir ne remplit pas son office »).
GABARIT_LISEZ_MOI = """Export ourouler — {proprietaire}
Généré le {quand}

Ce que contient cette archive :

- profil.json : ce que vous avez modifié depuis l'interface (départ, poids,
  FTP, vélos, position dans la zone, identifiants Intervals.icu). Le socle du
  serveur (URL de BRouter, modèles météo) n'y figure pas : il n'appartient à
  personne en particulier.
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

Ce que la suppression du compte efface : le profil, le journal des services,
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
    config: Config,
) -> bytes:
    """L'archive ZIP de tout ce que ce propriétaire possède. Voir le module."""
    tampon = io.BytesIO()
    with zipfile.ZipFile(tampon, mode="w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr(
            "LISEZ-MOI.txt",
            GABARIT_LISEZ_MOI.format(
                proprietaire=qui, quand=datetime.now(UTC).isoformat(timespec="seconds")
            ),
        )
        archive.writestr(
            "profil.json",
            json.dumps(profils.surcharge(qui), ensure_ascii=False, indent=2, sort_keys=True),
        )
        archive.writestr(
            "journal_services.json",
            json.dumps(journal.tout(qui), ensure_ascii=False, indent=2, sort_keys=True),
        )
        _ajouter_fichiers(archive, qui, fichiers)
        _ajouter_activites(archive, qui, config)
        _ajouter_routes_apprises(archive, qui, config)
    return tampon.getvalue()


def effacer_donnees(
    qui: Proprietaire,
    *,
    profils: DepotProfils,
    fichiers: DepotFichiers,
    journal: JournalServices,
    generations: DepotGenerations,
    config: Config,
    comptes: DepotComptes | None = None,
) -> dict:
    """Efface les données personnelles de ce propriétaire. Voir le module pour ce qui reste.

    `comptes` est **facultatif** : un déploiement sans base de comptes (mode
    personnel, ou hébergé sans `SessionParCookie`) n'a aucun compte à fermer,
    et l'appelant passe alors `None` — le résultat ne porte simplement pas la
    clé `"compte"`. Quand il est fourni, `DepotComptes.supprimer_compte_du_proprietaire`
    ferme le compte lié (mot de passe compris) et révoque du même coup ses
    sessions ouvertes, par la cascade du schéma (voir cette méthode).
    """
    cache = Cache(config.cache.dossier, proprietaire=str(qui))
    supprime = {
        "profil": profils.supprimer_profil(qui),
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
                "docs/questions_mainteneur.md"
            )
        },
    }


def _ajouter_fichiers(archive: zipfile.ZipFile, qui: Proprietaire, fichiers: DepotFichiers) -> None:
    manifeste = []
    for fichier in fichiers.lister(qui):
        archive.write(fichier.chemin, f"fichiers/{fichier.identifiant}_{fichier.nom}")
        manifeste.append(
            {"id": fichier.identifiant, "nom": fichier.nom, "type": fichier.type_contenu}
        )
    archive.writestr("fichiers/manifest.json", json.dumps(manifeste, ensure_ascii=False, indent=2))


def _ajouter_activites(archive: zipfile.ZipFile, qui: Proprietaire, config: Config) -> None:
    cache = Cache(config.cache.dossier, proprietaire=str(qui))
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


def _ajouter_routes_apprises(archive: zipfile.ZipFile, qui: Proprietaire, config: Config) -> None:
    base = BaseRoutes(config.cache.dossier / NOM_BASE, proprietaire=str(qui))
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
    archive.writestr(
        "routes_apprises/statistiques.json", json.dumps(resume, ensure_ascii=False, indent=2)
    )
    archive.writestr(
        "routes_apprises/sorties.json", json.dumps(base.sorties(), ensure_ascii=False, indent=2)
    )


__all__ = ["construire_export", "effacer_donnees"]
