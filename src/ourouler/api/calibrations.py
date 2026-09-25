"""La calibration depuis l'écran (lot L9.4).

Un compte avec capteur de puissance calibre son vélo sans la ligne de
commande du mainteneur : Crr fixé par le pneu, CdA cherché, fourchette du
porte à porte (L9.1), sur les sorties qu'il a importées (L9.2) ou
synchronisées depuis Intervals.icu. Le calcul est celui de `ourouler
calibrer` (`physique.commande.calibrer_velo`) — pas une seconde
implémentation —, lancé en tâche de fond (`api/taches_fond.py`) parce qu'il
dure et appelle l'archive Open-Meteo, une fois par jour de sortie.

**Où la calibration s'écrit.** En mode hébergé, dans le dossier du compte
(`DepotProfils.dossier`, à côté de son profil) : c'est ce chemin que
`api/routes._config` pose dans `Config.cache.fichier_calibration`, donc
celui que les boucles, les sorties, les simulations et l'écran de FTP de ce
compte relisent — et jamais ceux d'un autre. L'export et la suppression
RGPD l'emportent avec le reste du dossier (`api/vie_privee.py`). En mode
personnel, rien ne change : le fichier de calibration du dossier de cache, celui
que la ligne de commande écrit.

**Quelles sorties, pour quel vélo** (rattachement strict, choix du
25/09/2026) :

- un seul vélo dans le profil → toutes ses sorties extérieures, qu'elles
  viennent d'Intervals ou d'un fichier déposé : il n'y a personne d'autre à
  qui les attribuer ;
- plusieurs vélos → seules les sorties qui **désignent** ce vélo : capteur
  de puissance, équipement Intervals, ou période déclarée
  (`inventaire.rattachement_explicite`). Le repli de la ligne de commande
  — « à défaut, le premier vélo de route » — n'est pas suivi : un fichier
  Strava sans équipement, crédité en silence au premier vélo, fausserait la
  calibration de celui-ci avec des sorties faites sur l'autre. Ces sorties
  sont comptées et le refus le dit (« 12 sorties ne disent pas sur quel vélo
  elles ont été faites »), plutôt que de deviner.

**Préconditions**, chacune avec son code (`api/erreurs.CODES_PANNE`) et ce
qu'il faut faire : `velo_absent`, `ftp_absente`, `sorties_insuffisantes`
(combien il en faut, combien il y en a, et pourquoi les autres sont
écartées), `pneu_absent` (choisir le pneu, ou calibrer quand même avec le
Crr de l'usage — `sans_pneu`, et le résultat le dit). Vérifiées **avant**
le quota et avant le verrou : un refus ne coûte rien.

Ce module ne lit ni fichier de configuration ni variable d'environnement : il
reçoit une `Config`, un `Cache` et un client d'archive déjà construits pour
le propriétaire de la requête (`api/routes.py`).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path

from ourouler.activites.cache import Cache
from ourouler.api import taches_fond
from ourouler.api.erreurs import ErreurApi, assainir
from ourouler.config import Config, Velo
from ourouler.noyau.erreurs import ErreurConnecteur, ErreurUtilisateur
from ourouler.physique import calibration as calib
from ourouler.physique import commande as physique
from ourouler.physique import litterature
from ourouler.physique.modele import puissance_a_plat_w
from ourouler.stockage import calibrations as stockage

#: La vitesse à laquelle l'écran dit ce que coûte le vélo : « à 30 km/h sur
#: le plat, sans vent, il vous faut … W ». C'est la grandeur que le contrat
#: de L9.1 juge (puissance par watt affiché), pas le CdA, qui n'est qu'un
#: paramètre de compensation.
VITESSE_REPERE_KMH = 30.0


def sorties_necessaires(config: Config) -> int:
    """Combien de sorties exploitables il faut au moins — voir `calibration.sorties_minimum`."""
    return calib.sorties_minimum(config.calibration.part_validation)


def compter_sorties(config: Config, velo: Velo, cache: Cache) -> tuple[int, dict[str, int]]:
    """(sorties exploitables pour ce vélo, sorties écartées par motif) — sur l'index seul.

    Rapide : ne relit aucun fichier. Le calcul, lui, relira chaque fichier et
    pourra en écarter encore quelques-uns (multisport) ; ce décompte est donc
    un plafond honnête, pas une promesse.
    """
    retenues, motifs = calib.sorties_calibrables_et_motifs(
        cache, config, velo, depuis=config.historique_depuis, strict=True
    )
    return (len(retenues), motifs)


def verifier(
    config: Config,
    nom_velo: str | None,
    cache: Cache,
    *,
    sans_pneu: bool,
    velos_declares: bool = True,
) -> Velo:
    """Le vélo à calibrer, ou le refus qui dit quoi faire. Dans l'ordre où on les lève.

    `velos_declares` : le compte a-t-il déclaré ses vélos lui-même ? Une
    `Config` n'est jamais sans vélo — sans déclaration, `config.depuis_dict`
    en fabrique un générique (« Route », sans poids ni pneu) pour que les
    boucles tournent. Calibrer ce vélo-là n'aurait pas de sens : le résultat
    serait rangé sous un nom que le cycliste n'a jamais choisi. C'est
    l'appelant qui sait si la liste vient du cycliste (`api/routes.py` : sa
    surcharge de profil, en mode hébergé).

    Le pneu vient en dernier : demander de choisir un pneu à quelqu'un qui n'a
    de toute façon pas assez de sorties lui ferait faire un geste pour rien.
    """
    if not config.velos or not velos_declares:
        raise ErreurApi(
            code="velo_absent",
            message="calibration : aucun vélo dans votre profil — ajoutez-en un dans Réglages, "
            "la calibration porte sur un vélo",
            statut=422,
        )
    try:
        velo = physique.velo_demande(config, nom_velo)
    except ErreurUtilisateur as e:
        raise ErreurApi(code="requete_invalide", message=str(e), statut=400) from e
    if config.cycliste.ftp_w is None:
        raise ErreurApi(
            code="ftp_absente",
            message="calibration : votre FTP n'est pas renseignée — elle sert à écarter les "
            "efforts qui ne disent rien du vélo (sprints, relances). Renseignez-la dans "
            "Réglages, puis relancez",
            statut=422,
            details={"velo": velo.nom},
        )
    disponibles, motifs = compter_sorties(config, velo, cache)
    il_en_faut = sorties_necessaires(config)
    if disponibles < il_en_faut:
        raise ErreurApi(
            code="sorties_insuffisantes",
            message=_message_sorties(velo, disponibles, il_en_faut, motifs, config),
            statut=422,
            details={
                "velo": velo.nom,
                "il_en_faut": il_en_faut,
                "disponibles": disponibles,
                "ecartees": motifs,
            },
        )
    if physique.crr_du_velo(velo) is None and not sans_pneu:
        crr = physique.crr_de_l_usage(velo)
        raise ErreurApi(
            code="pneu_absent",
            message=(
                f"calibration de {velo.nom} : aucun pneu déclaré. Choisissez-le dans vos "
                "vélos — le résultat sera plus sûr —, ou calibrez quand même : la "
                f"résistance au roulement typique d'un vélo « {velo.usage} » "
                f"({_fr(crr, 4)}, littérature) sera alors gardée fixe, et le résultat le dira"
            ),
            statut=422,
            details={"velo": velo.nom, "crr_usage": crr},
        )
    return velo


def _message_sorties(
    velo: Velo, disponibles: int, il_en_faut: int, motifs: dict[str, int], config: Config
) -> str:
    lignes = [
        f"calibration de {velo.nom} : {disponibles} sortie(s) exploitable(s), il en faut "
        f"au moins {il_en_faut} — des sorties en extérieur de 20 km et plus, avec un "
        f"capteur de puissance, depuis le {config.historique_depuis.isoformat()}"
    ]
    non_identifiees = motifs.get(calib.MOTIF_VELO_NON_IDENTIFIE, 0)
    autres = {m: n for m, n in motifs.items() if m != calib.MOTIF_VELO_NON_IDENTIFIE}
    if autres:
        detail = ", ".join(f"{n} {m}" for m, n in sorted(autres.items()))
        lignes.append(f"écartées : {detail}")
    if non_identifiees:
        lignes.append(
            f"{non_identifiees} sortie(s) ne disent pas sur quel vélo elles ont été faites : "
            "avec plusieurs vélos, seules comptent celles que rattachent un capteur, un "
            "équipement intervals.icu ou une période déclarée"
        )
    return ". ".join(lignes)


def resume(config: Config, velo: Velo) -> dict | None:
    """Ce que l'écran dit d'une calibration existante, en mots simples — ou `None`.

    La puissance à `VITESSE_REPERE_KMH`, l'erreur de validation, la fourchette
    du porte à porte et le nombre de sorties d'abord ; CdA et Crr seulement
    dans `detail`, repliable côté front : ce sont des paramètres de
    compensation (capteur unilatéral compris), pas des mesures du vélo.
    """
    chemin = physique.chemin_calibration(config)
    lue = stockage.lire_calibration(chemin, velo.nom)
    if lue is None:
        return None
    fourchette = physique.fourchette_du_velo(velo, chemin)
    return {
        "velo": velo.nom,
        "date": lue.date or None,
        "provenance": "mesure",
        "puissance_repere_w": round(puissance_a_plat_w(VITESSE_REPERE_KMH, lue.parametres)),
        "vitesse_repere_kmh": VITESSE_REPERE_KMH,
        "n_sorties": lue.n_sorties,
        "n_validation": lue.n_validation,
        "erreur_validation": lue.mae,
        "biais_validation": lue.biais,
        "porte_a_porte": {
            "bas": fourchette.bas,
            "mediane": fourchette.mediane,
            "haut": fourchette.haut,
            "n": fourchette.n,
            "provenance": fourchette.provenance,
        },
        "crr_source": lue.crr_source or None,
        "pneu": lue.pneu,
        "alerte": physique.alerte_calibration(velo, chemin),
        "detail": {
            "cda_m2": round(lue.parametres.cda_m2, 4),
            "crr": lue.parametres.crr,
            "masse_totale_kg": lue.parametres.masse_totale_kg,
        },
    }


def etat(config: Config, cache: Cache, proprietaire: str) -> dict:
    """Pour chaque vélo : sa calibration, ce qui l'empêcherait, et la tâche en cours ou récente."""
    il_en_faut = sorties_necessaires(config)
    velos = []
    for velo in config.velos:
        disponibles, motifs = compter_sorties(config, velo, cache)
        tache = taches_fond.dernier(proprietaire, taches_fond.NATURE_CALIBRATION, velo.nom)
        pneu = litterature.pour_pneu(velo.pneu)
        velos.append(
            {
                "velo": velo.nom,
                "calibration": resume(config, velo),
                "sorties_disponibles": disponibles,
                "sorties_ecartees": motifs,
                "pneu": pneu.cle if pneu is not None else None,
                "crr_connu": physique.crr_du_velo(velo) is not None,
                "crr_usage": physique.crr_de_l_usage(velo),
                "tache": tache.json() if tache is not None else None,
            }
        )
    return {
        "sorties_necessaires": il_en_faut,
        "ftp_renseignee": config.cycliste.ftp_w is not None,
        "velos": velos,
    }


def lancer(
    config: Config,
    velo: Velo,
    cache: Cache,
    client_archive,
    proprietaire: str,
    *,
    sans_pneu: bool,
    chemins: Mapping[str, str],
    au_echec: Callable[[], None] | None = None,
) -> taches_fond.Job:
    """Lance la calibration de `velo` en tâche de fond. Lève `ErreurTacheEnCours` si occupé.

    `chemins` : les chemins du serveur à ne jamais montrer dans un message
    d'échec, et ce qui les remplace (`erreurs.assainir`).
    """
    chemin = physique.chemin_calibration(config)

    def travailler(job: taches_fond.Job) -> dict:
        try:
            resultat = physique.calibrer_velo(
                config,
                velo,
                cache,
                client_archive,
                crr_usage=sans_pneu,
                rattachement_strict=True,
                progres=lambda etape, faits, total: job.avancer(faits, total, etape),
            )
            # Le compte a pu être supprimé pendant l'ajustement, qui ne
            # s'interrompt pas : on ne réécrit pas sa calibration après coup.
            job.verifier_annulation()
            stockage.ecrire_calibration(chemin, velo.nom, resultat.contenu())
        except (ErreurUtilisateur, ErreurConnecteur) as e:
            echec = taches_fond.EchecLisible(assainir(str(e), (), chemins))
            echec.code = "calibration_impossible"
            raise echec from e
        rapport = resultat.rapport
        return {
            "calibration": resume(config, velo),
            "sorties_lues": resultat.n_calibrables,
            "sorties_apprentissage": rapport.n_apprentissage,
            "sorties_groupe": len(rapport.groupes),
            "archives_meteo_manquantes": len(resultat.pannes),
            "repli": rapport.repli_solo or None,
        }

    return taches_fond.lancer(
        proprietaire,
        taches_fond.NATURE_CALIBRATION,
        travailler,
        sujet=velo.nom,
        au_echec=au_echec,
    )


def fichier_du_compte(dossier_du_compte: Path) -> Path:
    """Où la calibration d'un compte hébergé s'écrit : dans son dossier, à côté de son profil."""
    return dossier_du_compte / stockage.NOM_CALIBRATION


def _fr(valeur: float, decimales: int) -> str:
    return f"{valeur:.{decimales}f}".replace(".", ",")


__all__ = [
    "VITESSE_REPERE_KMH",
    "compter_sorties",
    "etat",
    "fichier_du_compte",
    "lancer",
    "resume",
    "sorties_necessaires",
    "verifier",
]
