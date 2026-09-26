"""Les paramètres physiques d'un vélo : calibrés, configurés ou de littérature.

Du domaine pur : ce module **reçoit** la calibration déjà lue (une
`Calibration`, ou `None` quand le vélo n'en a pas) et ne connaît aucun
chemin. C'est `stockage.calibrations` qui lit et écrit le fichier de calibration,
et la couche commande (`services.physique`) qui fait le lien entre les deux.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from ourouler.noyau.erreurs import ErreurConfig, ErreurUtilisateur
from ourouler.noyau.profil import PorteVelos, Velo
from ourouler.physique import litterature
from ourouler.physique.modele import FourchettePorteAPorte, Parametres

#: CdA et Crr de dernier recours, pour un vélo dont l'usage n'est **pas** dans
#: la table de `physique.litterature` (aucun aujourd'hui, `config.USAGES_VELO`
#: ne portant que « route » et « clm » — mais le jour où un gravel s'y
#: ajoutera, mieux vaut un défaut muet qu'un jeu emprunté à une autre
#: catégorie). Ils ne sont **pas** une mesure : toute commande qui s'en sert le
#: dit, et `boucle` refuse d'en faire un temps « modèle ».
CDA_DEFAUT = 0.32
CRR_DEFAUT = 0.005

#: Ce que dit l'écran quand le pneu (ou le Crr écrit à la main) du vélo n'est
#: plus celui avec lequel la calibration a été faite. La calibration est
#: gardée — elle reste la meilleure mesure disponible —, mais le cycliste doit
#: savoir qu'elle ne suit plus son vélo.
ALERTE_PNEU_CHANGE = "pneu changé depuis la calibration, relancez-la"


@dataclass(frozen=True)
class Calibration:
    """Ce que le fichier de calibration garde d'un vélo."""

    velo: str
    parametres: Parametres
    date: str = ""
    n_sorties: int = 0
    mae: float | None = None
    #: La fourchette du porte à porte mesurée sur ce vélo, ou `None` pour une
    #: calibration ancienne qui ne la porte pas ou faite sur trop peu de
    #: sorties roulées seul : l'appelant retombe alors sur la convention.
    porte_a_porte: FourchettePorteAPorte | None = None
    #: D'où vient le Crr : « pneu », « configuration » ou « ajuste » (cherché
    #: avec le CdA, l'ancienne méthode). Vide pour une calibration ancienne.
    crr_source: str = ""
    #: Le pneu déclaré au moment de la calibration (`crr_source` « pneu »).
    pneu: str | None = None
    #: Le biais de validation (temps simulé sur réel − 1, signé) et le nombre
    #: de sorties de validation — ce que l'écran montre à côté de la MAE.
    biais: float | None = None
    n_validation: int = 0

    @property
    def resume(self) -> str:
        mae = f", MAE {self.mae * 100:.1f} %" if self.mae is not None else ""
        return (
            f"CdA {self.parametres.cda_m2:.3f} m², Crr {self.parametres.crr:.5f}, "
            f"{self.parametres.masse_totale_kg:.1f} kg (calibré le {self.date or '?'} "
            f"sur {self.n_sorties} sortie(s){mae})"
        )


def velo_demande(profil: PorteVelos, nom: str | None) -> Velo:
    """Le vélo nommé (sans égard à la casse), ou le premier vélo d'usage route."""
    if nom:
        for velo in profil.velos:
            if velo.nom.casefold() == nom.casefold():
                return velo
        raise ErreurConfig(f"velos : aucun vélo nommé « {nom} »")
    for velo in profil.velos:
        if velo.usage == "route":
            return velo
    if not profil.velos:
        raise ErreurUtilisateur("aucun vélo dans la configuration : ajouter une section [[velos]]")
    return profil.velos[0]


def parametres_du_velo(
    velo: Velo, masse_totale_kg: float, calibration: Calibration | None
) -> tuple[Parametres, str]:
    """(paramètres, provenance) : la calibration, sinon la configuration, sinon la littérature.

    Provenance vaut « calibration », « configuration », « littérature » ou
    « défaut ». Elle est affichée telle quelle : un CdA de littérature n'est
    pas une mesure, et la commande ne doit jamais laisser croire le contraire
    (on ne présente jamais une estimation comme une mesure).

    **L'ordre ne change pas** : une calibration mesurée prime toujours sur ce
    que la table générique propose. La littérature ne sert qu'à celui qui n'a
    encore rien mesuré — la littérature plutôt que la précision (décision
    Q52).

    Comme avant, une valeur donnée en configuration est **gardée** même quand
    l'autre manque : la provenance nomme alors d'où vient la moitié complétée.
    Un tel couple mi-configuré, mi-générique n'est pas un des couples dont
    `physique.litterature` a mesuré la dérive — ce qui s'y mesure est une
    somme, pas un CdA isolé.
    """
    if calibration is not None:
        return (calibration.parametres, "calibration")
    masse = masse_totale_kg
    if velo.cda_m2 is not None and velo.crr is not None:
        return (Parametres(masse, velo.cda_m2, velo.crr), "configuration")
    # Le Crr du pneu déclaré passe avant celui du jeu de l'usage, mais
    # jamais avant une valeur écrite à la main dans la configuration.
    connu = crr_du_velo(velo)
    crr = connu[0] if connu is not None else None
    choix = litterature.pour_usage(velo.usage)
    if choix is not None:
        return (
            Parametres(
                masse,
                velo.cda_m2 if velo.cda_m2 is not None else choix.jeu.cda_m2,
                crr if crr is not None else choix.jeu.crr,
            ),
            "littérature",
        )
    return (
        Parametres(
            masse,
            velo.cda_m2 if velo.cda_m2 is not None else CDA_DEFAUT,
            crr if crr is not None else CRR_DEFAUT,
        ),
        "défaut",
    )


def crr_du_velo(velo: Velo) -> tuple[float, str] | None:
    """(Crr, provenance) quand le Crr du vélo est **connu** sans calibration, sinon `None`.

    Provenance « configuration » (un `crr` écrit à la main, qui prime) ou
    « pneu » (la catégorie déclarée, `physique.litterature.PNEUS`). `None` :
    ni l'un ni l'autre, et la calibration ajuste alors le Crr avec le CdA.
    """
    if velo.crr is not None:
        return (velo.crr, "configuration")
    pneu = litterature.pour_pneu(velo.pneu)
    if pneu is not None:
        return (pneu.crr, "pneu")
    return None


def alerte_calibration(velo: Velo, calibration: Calibration | None) -> str | None:
    """`ALERTE_PNEU_CHANGE` si le Crr connu du vélo ne suit plus sa calibration, sinon `None`.

    Compare ce que le vélo déclare aujourd'hui (`crr_du_velo`) à ce que
    la calibration a noté (`crr_source`, `pneu`, `crr`). Une calibration
    ancienne (sans `crr_source`) sur un vélo sans pneu ni Crr déclaré ne
    dit rien : rien n'a changé. Pas de calibration : `None`.
    """
    if calibration is None:
        return None
    connu = crr_du_velo(velo)
    if connu is None:
        change = calibration.crr_source in ("pneu", "configuration")
    else:
        crr, source = connu
        if source == "pneu":
            change = calibration.crr_source != "pneu" or calibration.pneu != velo.pneu
        else:
            change = calibration.crr_source != "configuration" or not math.isclose(
                calibration.parametres.crr, crr
            )
    return ALERTE_PNEU_CHANGE if change else None


def fourchette_du_velo(calibration: Calibration | None) -> FourchettePorteAPorte:
    """La fourchette du porte à porte d'un vélo : mesurée si elle l'a été, sinon la convention.

    Mesurée : écrite par `ourouler calibrer` dans le fichier de calibration
    (provenance « mesure »). Sinon — vélo jamais calibré, calibration
    ancienne qui ne la porte pas, ou trop peu de sorties roulées seul —
    `litterature.FOURCHETTE_PORTE_A_PORTE_DEFAUT` (provenance « defaut »),
    une convention mesurée sur un seul cycliste, et dite comme telle.
    """
    if calibration is not None and calibration.porte_a_porte is not None:
        return calibration.porte_a_porte
    return fourchette_defaut()


def fourchette_defaut() -> FourchettePorteAPorte:
    """La convention de `physique.litterature`, en objet."""
    bas, mediane, haut = litterature.FOURCHETTE_PORTE_A_PORTE_DEFAUT
    return FourchettePorteAPorte(bas=bas, mediane=mediane, haut=haut, provenance="defaut", n=0)
