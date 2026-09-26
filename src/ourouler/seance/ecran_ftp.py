"""L'écran de FTP côté commande : lit la configuration et la calibration, puis calcule.

Le calcul des trois valeurs liées et de l'escalier est du domaine pur, dans
`seance.ftp`, qui reçoit le profil du cycliste et le modèle physique du vélo
tout faits (lot 7, `docs/ouverture_plan.md` §6). Ce module-ci est la couche
commande qui les lui prépare : il choisit le vélo demandé dans le profil,
lit sa calibration par `physique.commande` (qui résout le chemin de
du fichier de calibration et passe par `stockage.calibrations`) et délègue.

Les signatures sont celles d'avant le lot 7 — un profil et un nom de vélo
—, pour que la ligne de commande, l'API, `boucle` et `sortie` n'aient pas à
changer. L'ordre des vérifications aussi : un vélo inconnu ne se signale que
là où le calcul avait besoin du vélo.

**Lot 10 : le fichier de calibration arrive résolu.** Chaque fonction prend
`fichier_calibration` : un service le lui passe (`Contexte.fichier_calibration`)
et ne lit donc jamais le cache de la configuration. Absent, il est résolu
depuis `profil`, qui doit alors être une `config.Config` entière
(`physique.commande.chemin_calibration`) — c'est le cas de l'API et de
`rendu.profil` jusqu'au lot 11.
"""

from __future__ import annotations

from pathlib import Path

from ourouler.noyau.profil import Profil, Velo
from ourouler.physique.commande import (
    chemin_calibration,
    fourchette_du_velo,
    parametres_du_velo,
    velo_demande,
)
from ourouler.physique.modele import Parametres
from ourouler.seance import ftp
from ourouler.seance.ftp import (
    MAX_ITERATIONS_BISSECTION,
    PUISSANCE_MAXI_BISSECTION_W,
    PUISSANCE_MINI_BISSECTION_W,
    TOLERANCE_PUISSANCE_W,
)


def modele_du_velo(
    config: Profil, nom_velo: str | None = None, *, fichier_calibration: Path | None = None
) -> ftp.ModeleVelo | None:
    """Le vélo demandé et son modèle physique (calibré s'il l'a été), ou `None` sans vélo.

    `None` et non une exception : `ourouler config` doit rester utilisable
    sur une configuration sans `[[velos]]`, et l'écran de FTP doit pouvoir
    afficher la puissance sans la vitesse.
    """
    if not config.velos:
        return None
    velo = velo_demande(config, nom_velo)
    parametres, provenance = parametres_du_velo(config, velo, _fichier(config, fichier_calibration))
    return ftp.ModeleVelo(velo, parametres, provenance)


def _fichier(config, fichier_calibration: Path | None) -> Path:
    """Le fichier donné, ou celui d'une `config.Config` entière (voir le module)."""
    return fichier_calibration if fichier_calibration is not None else chemin_calibration(config)


def contexte(
    config: Profil, nom_velo: str | None = None, *, fichier_calibration: Path | None = None
) -> tuple[Velo, Parametres, str] | None:
    """(vélo, paramètres physiques, provenance du modèle), ou `None` sans vélo."""
    modele = modele_du_velo(config, nom_velo, fichier_calibration=fichier_calibration)
    if modele is None:
        return None
    return (modele.velo, modele.parametres, modele.provenance)


def valeurs_liees(
    config: Profil,
    nom_velo: str | None = None,
    *,
    position: float | None = None,
    fichier_calibration: Path | None = None,
) -> dict | None:
    """Les trois valeurs, à la position donnée : voir `seance.ftp.valeurs_liees`."""
    return ftp.valeurs_liees(
        modele_du_velo(config, nom_velo, fichier_calibration=fichier_calibration),
        config.cycliste,
        config.seance,
        position=position,
    )


def info_compteur(
    config: Profil,
    nom_velo: str | None = None,
    *,
    puissance_w: float | None = None,
    vitesse_a_plat_kmh: float | None = None,
    fichier_calibration: Path | None = None,
) -> dict | None:
    """Le bloc « compteur » que `boucle` et `sortie` publient à côté de `demande`.

    La moyenne compteur qui a dimensionné la distance demandée (« 5 h à
    23 km/h » → 115 km) demande trois des valeurs de cet écran —
    `moyenne_compteur_kmh`, `facteur_compteur`, `facteur_provenance` — plus le
    nom du vélo. Depuis L9.1 (25/09/2026), le bloc porte aussi la fourchette
    du porte à porte du vélo (`porte_a_porte`) : c'est elle, et non plus la
    moyenne compteur, qui chronomètre une candidate
    (`physique.modele.temps_ecoule`). Ce module en est la source
    unique : ceci n'est pas une deuxième lecture de la configuration,
    seulement un sous-ensemble mis en forme pour ce contrat-là, comme
    `rendu.profil.info_vitesse_compteur` l'est pour `ourouler config`.

    **`puissance_w` / `vitesse_a_plat_kmh` (exclusifs entre eux, comme pour
    `position_pour`) : la puissance effectivement demandée pour CE parcours-ci**
    — `--puissance`, ou ce qu'exige `--vitesse-a-plat`, sur `ourouler boucle`.
    Corrige un défaut trouvé le 18/09/2026 : sans ce paramètre, la moyenne
    compteur restait celle de la puissance d'endurance **de la configuration**
    quelle que soit la puissance demandée, et le temps écoulé porte à porte
    n'en suivait donc pas les variations — 150 W et 300 W rendaient le même
    porte à porte alors que le temps en mouvement, lui, changeait bien.

    **Ce que ça ne change pas** : l'écran de FTP lui-même (décision 7 du cycle
    UX) continue de montrer les trois valeurs liées à la position **de la
    configuration** — c'est `valeurs_liees`/`rendu`, appelés sans ces
    paramètres, qui le servent. Seule la moyenne compteur **publiée à côté d'un
    parcours** doit suivre la puissance demandée ; les deux
    usages divergent donc ici plutôt que l'un ne se fasse passer pour l'autre.

    Sans aucun des deux (défaut, et le seul cas pour `sortie`, qui n'a pas
    cette option) : la position de la configuration, comme avant.

    **Le facteur compteur mesuré (`velo.facteur_compteur`) n'est jamais
    recalculé ici** — `valeurs_liees` le garde tel quel dès qu'il est mesuré ;
    seule la vitesse à laquelle il s'applique bouge avec la position.

    `None` si la configuration ne porte aucun vélo : pas de modèle physique,
    pas de facteur, rien à réconcilier — et `temps_ecoule_s` doit alors valoir
    `None` chez l'appelant.
    """
    position = None
    if puissance_w is not None or vitesse_a_plat_kmh is not None:
        position = position_pour(
            config,
            nom_velo,
            puissance_w=puissance_w,
            vitesse_kmh=vitesse_a_plat_kmh,
            fichier_calibration=fichier_calibration,
        )
    liees = valeurs_liees(config, nom_velo, position=position, fichier_calibration=fichier_calibration)
    if liees is None:
        return None
    fourchette = fourchette_du_velo(
        velo_demande(config, nom_velo), _fichier(config, fichier_calibration)
    )
    return ftp.bloc_compteur(liees, fourchette)


def position_pour(
    config: Profil,
    nom_velo: str | None = None,
    *,
    puissance_w: float | None = None,
    vitesse_kmh: float | None = None,
    fichier_calibration: Path | None = None,
) -> float:
    """La position dans la Z2 que désigne une puissance, ou une vitesse à plat.

    Voir `seance.ftp.position_pour`. Le vélo n'est lu que pour convertir une
    vitesse : une puissance seule n'en a pas besoin.
    """
    ftp.verifier_une_seule_saisie(puissance_w, vitesse_kmh)
    modele = (
        modele_du_velo(config, nom_velo, fichier_calibration=fichier_calibration)
        if vitesse_kmh is not None
        else None
    )
    return ftp.position_pour(
        config.cycliste,
        config.seance,
        puissance_w=puissance_w,
        vitesse_kmh=vitesse_kmh,
        modele=modele,
    )


def rendu(
    config: Profil,
    nom_velo: str | None = None,
    *,
    position: float | None = None,
    fichier_calibration: Path | None = None,
) -> dict:
    """Tout ce que l'écran de FTP affiche, pour une position donnée : voir `seance.ftp.rendu`.

    Sans FTP, le vélo n'est pas lu : il n'y a pas de valeurs liées à calculer.
    """
    modele = (
        None
        if config.cycliste.ftp_w is None
        else modele_du_velo(config, nom_velo, fichier_calibration=fichier_calibration)
    )
    return ftp.rendu(modele, config.cycliste, config.seance, position=position)


def ftp_pour_vitesse_compteur(
    config: Profil,
    nom_velo: str | None,
    *,
    vitesse_compteur_kmh: float,
    denivele_m_par_km: float,
    fichier_calibration: Path | None = None,
) -> float:
    """La FTP que désigne une vitesse au compteur et un terrain déclarés (T4).

    Voir `seance.ftp.ftp_pour_vitesse_compteur`. Une saisie invalide est
    refusée avant de lire le vélo.
    """
    ftp.verifier_saisie_compteur(vitesse_compteur_kmh, denivele_m_par_km)
    return ftp.ftp_pour_vitesse_compteur(
        modele_du_velo(config, nom_velo, fichier_calibration=fichier_calibration),
        config.seance,
        vitesse_compteur_kmh=vitesse_compteur_kmh,
        denivele_m_par_km=denivele_m_par_km,
    )


__all__ = [
    "MAX_ITERATIONS_BISSECTION",
    "PUISSANCE_MAXI_BISSECTION_W",
    "PUISSANCE_MINI_BISSECTION_W",
    "TOLERANCE_PUISSANCE_W",
    "contexte",
    "ftp_pour_vitesse_compteur",
    "info_compteur",
    "modele_du_velo",
    "position_pour",
    "rendu",
    "valeurs_liees",
]
