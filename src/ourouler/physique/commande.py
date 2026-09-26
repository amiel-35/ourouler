"""Sous-commandes `ourouler calibrer`, `ourouler simuler` et `ourouler analyser`.

Ce module porte les trois cas d'usage : chacun reçoit une demande déjà
interprétée par l'entrée (`commandes/physique.py`, qui lit argparse) et un
`services.contexte.Contexte` (profil, dossier de cache et fichier de
calibration résolus), et rend un résultat sans rien imprimer. Depuis le
lot 8, choisir et lire les sorties à calibrer est `services.calibrer`, le
calcul `physique.calibration` (qui ne connaît ni chemin, ni cache, ni
configuration), et le texte comme le JSON `rendu.physique` — que l'entrée
appelle depuis le lot 10.

`calibrer` enchaîne : choix des sorties → archives météo (mémoïsées) →
échantillons → deux passes d'ajustement → validation sur les sorties les plus
récentes → rapport et JSON. Les appels réseau sont ceux de l'archive, un par
jour de sortie, et une seule fois dans la vie du cache.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path

from ourouler.activites.cache import Cache
from ourouler.boucle.gpx import lire_gpx_parcours, lire_gpx_trace
from ourouler.boucle.horaire import Pause, construire_horaire, duree_pauses_s, valider_pauses
from ourouler.boucle.meteo_trace import MeteoTrace
from ourouler.boucle.meteo_trace import evaluer as evaluer_meteo
from ourouler.connecteurs.openmeteo_archive import ClientArchive
from ourouler.meteo import portee
from ourouler.meteo.openmeteo import ClientOpenMeteo
from ourouler.noyau.erreurs import ErreurConnecteur, ErreurUtilisateur
from ourouler.noyau.profil import Profil, Velo
from ourouler.physique import parametres_velo
from ourouler.physique.modele import (
    FourchettePorteAPorte,
    Parametres,
    PorteAPorte,
    Simulation,
    puissance_a_plat_w,
    simuler,
    temps_ecoule,
    vent_au_cycliste,
)
from ourouler.services.calibrer import (
    ResultatCalibration,
    calibrer_velo,
    masse_totale_kg,
)
from ourouler.services.contexte import Contexte
from ourouler.stockage.calibrations import (
    ecrire_calibration,
    lire_calibration,
)

#: Distance maximale d'un GPX déposé pour `ourouler analyser` : la même borne
#: que `DemandeBoucle.distance_km` (`api/modeles.py`) — au-delà, ni une
#: Flèche ni un BRM ne va plus loin, et un tracé plus long a de bonnes
#: chances d'être une erreur de dépôt plutôt qu'un vrai parcours.
DISTANCE_MAX_ANALYSE_M = 1_000_000.0

#: Borne haute d'une vitesse à plat saisie à la main, en km/h. Au-delà, ce
#: n'est plus un cycliste lancé sur le plat sans vent, c'est une faute de
#: frappe — et la puissance déduite serait délirante.
VITESSE_A_PLAT_MAXI_KMH = 80.0

#: Nom du fichier de mémoïsation des archives météo, dans le dossier de cache (lu par la CLI seule).
NOM_CACHE = "archive_meteo.sqlite"


# --- calibration.json : la commande résout le chemin, le stockage lit ---------

#: Nom du fichier où la calibration est écrite, dans le dossier de cache.
NOM_CALIBRATION = "calibration.json"
#
# Depuis le lot 7, la lecture et l'écriture vivent dans `stockage.calibrations`
# et le calcul (quels paramètres pour quel vélo) dans `physique.parametres_velo`,
# qui reçoit la `Calibration` déjà lue. Les fonctions ci-dessous gardent leurs
# signatures d'avant — un profil et un chemin — pour les appelants : elles
# lisent et délèguent.


def chemin_calibration(config) -> Path:
    """Le `calibration.json` d'une `config.Config` (lue sans importer l'entrée).

    Depuis le lot 10, les services reçoivent ce chemin déjà résolu
    (`Contexte.fichier_calibration`) ; ce sont les entrées qui appellent
    cette fonction — `commandes/commun.py`, et l'API
    (`api/calibrations.py`) en attendant le lot 11.

    Dans le dossier de cache pour la ligne de commande ; à l'endroit que la
    couche web a posé pour un compte hébergé (`ParametresCache.fichier_calibration`,
    L9.4) — c'est ce qui fait que les boucles, les sorties et les simulations
    d'un compte lisent **sa** calibration, et jamais celle d'un autre.
    """
    if config.cache.fichier_calibration is not None:
        return config.cache.fichier_calibration
    return config.cache.dossier / NOM_CALIBRATION


def parametres_du_velo(profil: Profil, velo: Velo, chemin: Path) -> tuple[Parametres, str]:
    """(paramètres, provenance) du vélo : voir `physique.parametres_velo.parametres_du_velo`."""
    return parametres_velo.parametres_du_velo(
        velo, masse_totale_kg(profil, velo), lire_calibration(chemin, velo.nom)
    )


def alerte_calibration(velo: Velo, chemin: Path) -> str | None:
    """L'alerte « pneu changé » : voir `physique.parametres_velo.alerte_calibration`."""
    return parametres_velo.alerte_calibration(velo, lire_calibration(chemin, velo.nom))


def fourchette_du_velo(velo: Velo, chemin: Path) -> FourchettePorteAPorte:
    """La fourchette du porte à porte : voir `physique.parametres_velo.fourchette_du_velo`."""
    return parametres_velo.fourchette_du_velo(lire_calibration(chemin, velo.nom))



def puissance_voulue(
    puissance: float | None, vitesse: float | None, parametres: Parametres
) -> float | None:
    """La puissance demandée : `--puissance`, ou celle que `--vitesse-a-plat` exige.

    `None` si aucune des deux options n'est donnée — c'est à l'appelant de
    décider ce qu'il en fait (`boucle` retombe sur une part de la FTP,
    `simuler` refuse).

    **Les deux options disent la même chose de deux façons et sont exclusives.**
    Le mainteneur, le 18/09/2026 : « et s'il n'a pas de FTP ? » Pour chronométrer
    un parcours, le produit n'a pas besoin d'une FTP mais d'une puissance ; la
    vitesse à plat, sans vent, lancé, en est l'autre chemin — c'est la
    décision 7 du cycle UX, et l'inversion est celle qu'emploie déjà l'écran de
    FTP (`physique.modele.puissance_a_plat_w`), pas une seconde.

    La conversion dépend des `parametres` du vélo : la même vitesse ne demande
    pas la même puissance à un cycliste calibré et à un vélo servi par la
    littérature. C'est pourquoi cette fonction les reçoit au lieu de les lire.
    """
    if puissance is not None and vitesse is not None:
        raise ErreurUtilisateur(
            "--puissance et --vitesse-a-plat disent la même chose de deux façons "
            "(la seconde se convertit en watts par le modèle du vélo) : n'en donner qu'une."
        )
    if vitesse is None:
        return None if puissance is None else float(puissance)
    if not math.isfinite(float(vitesse)) or not (0 < float(vitesse) <= VITESSE_A_PLAT_MAXI_KMH):
        raise ErreurUtilisateur(
            f"--vitesse-a-plat {vitesse} : une vitesse à plat en km/h entre 0 et "
            f"{VITESSE_A_PLAT_MAXI_KMH:g} est attendue (sans vent, lancé — pas une "
            "moyenne de compteur)"
        )
    return puissance_a_plat_w(float(vitesse), parametres)


def velo_demande(profil: Profil, nom: str | None) -> Velo:
    """Le vélo nommé, ou le premier vélo d'usage route (`parametres_velo.velo_demande`)."""
    return parametres_velo.velo_demande(profil, nom)



# --- ourouler calibrer --------------------------------------------------------


@dataclass(frozen=True)
class DemandeCalibration:
    """Le vélo à calibrer (déjà trouvé dans le profil) et le choix des sorties."""

    velo: Velo
    depuis: date
    maximum: int | None = None
    crr_libre: bool = False


@dataclass(frozen=True)
class CalibrationEcrite:
    """Ce que `calibrer` a mesuré, où il l'a écrit, et ce que l'archive a coûté."""

    velo: Velo
    resultat: ResultatCalibration
    fichier: Path
    archives_appels: int
    archives_cache: int


def executer_calibrer(
    demande: DemandeCalibration,
    contexte: Contexte,
    client_archive: ClientArchive | None = None,
    cache: Cache | None = None,
) -> CalibrationEcrite:
    """Calibre un vélo sur les sorties réelles du cache et écrit `calibration.json`.

    **`cache` s'injecte** (L9.4), sur le patron d'`activites/commande.executer` :
    absent — la ligne de commande —, le service construit celui du
    propriétaire local sur `contexte.dossier_cache`, comme avant. Le calcul
    lui-même est `calibrer_velo`, qui n'imprime rien : c'est lui que la tâche
    de fond de l'API appelle (`api/calibrations.py`), parce qu'une commande
    qui écrit sur la sortie standard ne peut pas tourner dans un fil pendant
    que d'autres requêtes capturent la leur (`api/adaptateur.py`).
    """
    velo = demande.velo
    cache = cache if cache is not None else Cache(contexte.dossier_cache)
    client = (
        client_archive
        if client_archive is not None
        else ClientArchive(chemin_cache=contexte.dossier_cache / NOM_CACHE)
    )
    resultat = calibrer_velo(
        contexte.profil,
        velo,
        cache,
        client,
        depuis=demande.depuis,
        maximum=demande.maximum,
        crr_libre=demande.crr_libre,
    )

    chemin = contexte.fichier_calibration
    ecrire_calibration(chemin, velo.nom, resultat.contenu())
    for panne in resultat.pannes:
        contexte.avertir(f"ourouler : {panne}")
    return CalibrationEcrite(
        velo=velo,
        resultat=resultat,
        fichier=chemin,
        archives_appels=client.appels,
        archives_cache=client.lectures_cache,
    )



# --- ourouler simuler ---------------------------------------------------------


@dataclass(frozen=True)
class DemandeSimulation:
    """Un GPX à chronométrer, à puissance constante (ou à la vitesse à plat qui la donne)."""

    gpx: Path
    velo: str | None = None
    puissance_w: float | None = None
    vitesse_a_plat_kmh: float | None = None
    pauses: tuple[Pause, ...] = ()
    #: L'heure de départ, si elle est donnée : c'est elle qui fait venir le vent prévu.
    depart: datetime | None = None


@dataclass(frozen=True)
class ResultatSimulation:
    simulation: Simulation
    trace: object
    velo: Velo
    parametres: Parametres
    provenance: str
    puissance_w: float
    meteo: MeteoTrace | None
    pauses: tuple[Pause, ...]
    arrivee: datetime | None
    alerte: str | None


def executer_simuler(
    demande: DemandeSimulation, contexte: Contexte, client_meteo: ClientOpenMeteo | None = None
) -> ResultatSimulation:
    """Simule un GPX à puissance constante, avec le vent prévu si un départ est donné."""
    # Les paramètres du vélo sont résolus **avant** la puissance : une vitesse
    # à plat ne se convertit en watts qu'avec eux (L8.5, lot C).
    velo = velo_demande(contexte.profil, demande.velo)
    parametres, provenance = parametres_du_velo(contexte.profil, velo, contexte.fichier_calibration)
    alerte = alerte_calibration(velo, contexte.fichier_calibration)
    puissance = puissance_voulue(demande.puissance_w, demande.vitesse_a_plat_kmh, parametres)
    if puissance is None:
        raise ErreurUtilisateur(
            "simuler : donner --puissance W, ou --vitesse-a-plat KMH pour qui ne connaît "
            "pas sa puissance"
        )
    if not (0 < float(puissance) <= 2000):
        vitesse = demande.vitesse_a_plat_kmh
        if vitesse is not None:
            raise ErreurUtilisateur(
                f"--vitesse-a-plat {vitesse} : il faudrait {puissance:.0f} W pour la tenir "
                f"à plat sur le {velo.nom}, au-delà des 2000 W que le modèle accepte"
            )
        raise ErreurUtilisateur(
            f"--puissance {puissance} : une puissance en watts entre 1 et 2000 est attendue"
        )
    trace = lire_gpx_trace(demande.gpx)

    pauses = demande.pauses
    valider_pauses(pauses, distance_m=trace.distance_m)

    vent = None
    panne = None
    depart_dt = demande.depart
    if depart_dt is not None:
        client = client_meteo if client_meteo is not None else ClientOpenMeteo()
        try:
            vent, resume = vent_prevu(trace, client, contexte.profil, depart_dt, pauses=pauses)
        except ErreurConnecteur as e:
            panne, resume = str(e), None
    else:
        resume = None
        if pauses:
            # Une pause décale l'heure de passage météo ; sans départ, il n'y
            # a pas d'heure à décaler — le signaler plutôt que de laisser
            # croire que `--pause` a joué un rôle.
            contexte.avertir(
                "ourouler : --pause sans --heure-depart n'a aucun effet "
                "(rien à dater sans heure de départ)"
            )

    simulation = simuler(trace, float(puissance), parametres, vent=vent)
    arrivee = (
        depart_dt + timedelta(seconds=simulation.temps_s + duree_pauses_s(pauses))
        if depart_dt is not None
        else None
    )
    if panne is not None:
        contexte.avertir(f"ourouler : météo indisponible ({panne}) — simulation à vent nul")
    return ResultatSimulation(
        simulation=simulation,
        trace=trace,
        velo=velo,
        parametres=parametres,
        provenance=provenance,
        puissance_w=float(puissance),
        meteo=resume,
        pauses=pauses,
        arrivee=arrivee,
        alerte=alerte,
    )


def vent_prevu(
    trace, client: ClientOpenMeteo, profil: Profil, depart: datetime, *, pauses: Sequence[Pause] = ()
):
    """(fonction de vent pour `simuler`, résumé lisible) à partir de la prévision.

    Le vent vient de `boucle.meteo_trace`, échantillonné le long du tracé : le
    modèle a besoin de la composante de face en m/s, que la direction
    interpolée et le cap local donnent. `pauses` décale l'heure de passage de
    chaque échantillon situé après elles (`boucle.horaire`), jamais le temps
    en mouvement que `simuler` calcule par ailleurs.
    """
    from ourouler.boucle.meteo_trace import evaluer as evaluer_meteo

    meteo = evaluer_meteo(
        trace,
        client,
        horaire=construire_horaire(depart, profil.boucle.vitesse_moyenne_kmh, pauses),
        modele=profil.meteo.modele,
        second_avis=None,
    )
    return (vent_depuis_meteo(meteo), meteo)


def vent_depuis_meteo(meteo):
    """`vent(dist_m, cap_deg)` en m/s de face, depuis les échantillons météo d'un tracé.

    L'échantillon le plus proche en distance sert tel quel : les échantillons
    sont espacés de 5 km, le vent d'une prévision horaire ne varie pas plus
    vite que ça.

    La prévision, comme l'archive, donne le vent à 10 m du sol :
    `vent_au_cycliste` le ramène à la hauteur où il est subi. C'est le **seul**
    endroit où la prévision est convertie — `ourouler simuler --heure-depart` et la
    colonne « temps » de `ourouler boucle` passent toutes deux par ici — et
    c'est le pendant exact de ce que fait la calibration sur l'archive. Les
    échantillons météo, eux, gardent la valeur du bulletin : la colonne
    « vent » d'un rapport météo doit rester comparable à ce qu'annonce
    Météo-France.
    """
    connus = [
        (e.dist_m, e.vent_kmh, e.vent_depuis_deg)
        for e in meteo.echantillons
        if e.vent_kmh is not None and e.vent_depuis_deg is not None
    ]
    if not connus:
        return None

    def face(dist_m: float, cap: float) -> float:
        _, vitesse, depuis = min(connus, key=lambda c: abs(c[0] - dist_m))
        return vent_au_cycliste((vitesse / 3.6) * math.cos(math.radians(depuis - cap)))

    return face


# --- ourouler analyser --------------------------------------------------------


@dataclass(frozen=True)
class DemandeAnalyse:
    """Un parcours déjà en main, l'heure du départ, et la puissance si elle n'est pas celle du profil."""

    gpx: Path
    depart: datetime
    velo: str | None = None
    puissance_w: float | None = None
    vitesse_a_plat_kmh: float | None = None


@dataclass(frozen=True)
class ResultatAnalyse:
    simulation: Simulation
    trace: object
    velo: Velo
    parametres: Parametres
    provenance: str
    puissance_w: float
    meteo: MeteoTrace | None
    ecoule: PorteAPorte
    depart: datetime
    arrivee_bas: datetime
    arrivee_mediane: datetime
    arrivee_haut: datetime
    alerte: str | None
    meteo_absente: object
    fourchette: FourchettePorteAPorte
    panne: str | None
    avertissements_trace: list[str]
    vitesse_a_vent_nul_kmh: float


def executer_analyser(
    demande: DemandeAnalyse, contexte: Contexte, client_meteo: ClientOpenMeteo | None = None
) -> ResultatAnalyse:
    """Analyse un parcours **déjà en main** (BRM, Flèche, boucle de club) : durée porte à
    porte en fourchette, météo par tronçon à l'heure où on y passe, heure d'arrivée.

    C'est `ourouler simuler` retourné dans l'autre sens : `simuler` chronomètre un GPX à
    puissance constante et prend la météo en option ; `analyser` part d'un parcours qu'on
    n'a pas choisi (l'imposé d'un brevet, la boucle du club) et veut savoir **quand** on
    y passera et ce qu'on y trouvera — `--heure-depart` y est donc obligatoire, là où
    `simuler` s'en passe.

    **La puissance, par défaut, est celle de l'endurance du profil** :
    `profil.seance.puissance_endurance_pct × profil.cycliste.ftp_w` — le même calcul que
    l'écran de FTP (`seance.ecran_ftp.apercu_zones`). `--puissance`/`--vitesse-a-plat`
    la remplacent pour qui veut un autre rythme (Q7, même inversion que `simuler`).

    **La vitesse qui date les échantillons météo est celle du modèle, pas la moyenne
    configurée** : `physique.modele.simuler` à vent nul donne une vitesse moyenne qui
    tient compte du relief de *ce* parcours-ci — exactement `boucle.commande._vitesse_meteo`,
    rejoué ici pour un GPX déposé plutôt que pour une candidate générée. Sur un parcours
    vallonné, c'est très différent d'une vitesse moyenne plate, et c'est tout l'intérêt :
    la météo d'un col à 12 km/h n'est pas celle d'une plaine à 30.

    **Les heures de passage sont celles du porte à porte** (L9.8, relecture) : le
    temps en mouvement à vent nul, multiplié par la médiane de la fourchette L9.1
    du vélo (mesurée ou convention). Sur un 600 km, caler la météo sur le seul
    temps en mouvement la décalait de plusieurs heures — les arrêts arrivent
    bien, eux aussi.

    **Horizon météo** : au-delà de `profil.meteo.horizon_jours`, aucun appel n'est fait —
    la durée est rendue sans météo, et le dit (même mécanisme que `ourouler boucle`,
    `meteo.portee`). Un 600 km dépasse presque toujours la portée horaire utile du modèle
    régional (AROME) avant son arrivée : `boucle.meteo_trace.evaluer` bascule alors sur
    `second_avis` pour la fin du parcours, et chaque échantillon dit lequel a répondu
    (`Echantillon.modele`) — jamais mélangé en silence (règle absolue 5). Un
    parcours parti le dernier jour couvert qui arrive le lendemain : les
    échantillons d'après la fin de ce jour sont vides et marqués
    `au_dela_prevision`, jamais présentés comme une prévision.

    **Plusieurs traces** : lues toutes, enchaînées (`boucle.gpx.lire_gpx_parcours`),
    et chaque trou franchi en ligne droite est dit.
    """
    profil = contexte.profil
    depart_dt = demande.depart
    trace, avertissements_trace = lire_gpx_parcours(demande.gpx)
    for avertissement in avertissements_trace:
        contexte.avertir(f"ourouler : {avertissement}")
    if trace.distance_m > DISTANCE_MAX_ANALYSE_M:
        raise ErreurUtilisateur(
            f"analyser : {trace.distance_m / 1000:.0f} km, au-delà des "
            f"{DISTANCE_MAX_ANALYSE_M / 1000:.0f} km qu'un parcours à analyser accepte"
        )

    velo = velo_demande(profil, demande.velo)
    parametres, provenance = parametres_du_velo(profil, velo, contexte.fichier_calibration)
    alerte = alerte_calibration(velo, contexte.fichier_calibration)

    puissance = puissance_voulue(demande.puissance_w, demande.vitesse_a_plat_kmh, parametres)
    if puissance is None:
        if profil.cycliste.ftp_w is None:
            raise ErreurUtilisateur(
                "analyser : donner --puissance W ou --vitesse-a-plat KMH — aucune FTP dans "
                "le profil pour calculer par défaut la puissance d'endurance"
            )
        puissance = profil.seance.puissance_endurance_pct * profil.cycliste.ftp_w
    if not (0 < float(puissance) <= 2000):
        raise ErreurUtilisateur(
            f"--puissance {puissance} : une puissance en watts entre 1 et 2000 est attendue"
        )
    puissance = float(puissance)

    client = client_meteo if client_meteo is not None else ClientOpenMeteo()
    fourchette = fourchette_du_velo(velo, contexte.fichier_calibration)

    dernier_jour = portee.dernier_jour_couvert(profil.meteo.horizon_jours, aujourdhui=date.today())
    jour_demande = depart_dt.date()
    meteo_absente = (
        portee.constater(jour_demande, dernier_jour) if jour_demande > dernier_jour else None
    )

    meteo: MeteoTrace | None = None
    panne: str | None = None
    vitesse_a_vent_nul = _vitesse_a_vent_nul(trace, puissance, parametres, profil)
    if meteo_absente is None:
        # Porte à porte, pas en mouvement : la vitesse « de montre », arrêts
        # compris, à la médiane de la fourchette du vélo.
        vitesse_montre = vitesse_a_vent_nul / fourchette.mediane
        fuseau = depart_dt.tzinfo or UTC
        fin_de_prevision = datetime.combine(
            dernier_jour + timedelta(days=1), time(0), tzinfo=fuseau
        )
        try:
            meteo = evaluer_meteo(
                trace,
                client,
                horaire=construire_horaire(depart_dt, vitesse_montre),
                limite=fin_de_prevision,
                modele=profil.meteo.modele,
                second_avis=profil.meteo.second_avis,
                # Même repli que `boucle`/`sortie` (Q19) : un parcours plus
                # long que la portée horaire du modèle régional ne perd pas
                # toute sa météo, seulement la partie que le repli ne couvre
                # pas non plus.
                modele_repli=profil.meteo.second_avis,
            )
        except ErreurConnecteur as e:
            panne = str(e)

    vent = vent_depuis_meteo(meteo) if meteo is not None else None
    simulation = simuler(trace, puissance, parametres, vent=vent)

    ecoule = temps_ecoule(simulation.temps_s, fourchette)
    arrivee_bas = depart_dt + timedelta(seconds=ecoule.bas_s)
    arrivee_mediane = depart_dt + timedelta(seconds=ecoule.mediane_s)
    arrivee_haut = depart_dt + timedelta(seconds=ecoule.haut_s)

    if panne is not None:
        contexte.avertir(f"ourouler : météo indisponible ({panne}) — durée rendue sans météo")
    elif meteo_absente is not None:
        contexte.avertir(f"ourouler : {meteo_absente.message} — durée rendue sans météo")

    return ResultatAnalyse(
        simulation=simulation,
        trace=trace,
        velo=velo,
        parametres=parametres,
        provenance=provenance,
        puissance_w=puissance,
        meteo=meteo,
        ecoule=ecoule,
        depart=depart_dt,
        arrivee_bas=arrivee_bas,
        arrivee_mediane=arrivee_mediane,
        arrivee_haut=arrivee_haut,
        alerte=alerte,
        meteo_absente=meteo_absente,
        fourchette=fourchette,
        panne=panne,
        avertissements_trace=avertissements_trace,
        vitesse_a_vent_nul_kmh=vitesse_a_vent_nul,
    )


def _vitesse_a_vent_nul(
    trace, puissance_w: float, parametres: Parametres, profil: Profil
) -> float:
    """La vitesse qui date les échantillons météo — le pendant, pour un GPX déposé, de
    `boucle.commande._vitesse_meteo` : une simulation à vent nul (la météo qu'on cherche
    dépendrait sinon de l'heure, qui dépend de la vitesse, qui dépend du vent — second
    ordre, voir la docstring de `_vitesse_meteo`). Retombe sur la vitesse moyenne
    configurée si la simulation échoue (tracé dégénéré) : la météo reste utilisable.
    """
    try:
        vitesse = simuler(trace, puissance_w, parametres).vitesse_moy_kmh
    except ErreurUtilisateur:
        return profil.boucle.vitesse_moyenne_kmh
    if not math.isfinite(vitesse) or vitesse <= 0:
        return profil.boucle.vitesse_moyenne_kmh
    return vitesse


# --- options ------------------------------------------------------------------


def date_option(texte: str | None, defaut: date) -> date:
    if not texte:
        return defaut
    try:
        return date.fromisoformat(str(texte).strip())
    except ValueError as e:
        raise ErreurUtilisateur(f"--depuis {texte!r} : date AAAA-MM-JJ attendue") from e


__all__ = [
    "CalibrationEcrite",
    "DemandeAnalyse",
    "DemandeCalibration",
    "DemandeSimulation",
    "ResultatAnalyse",
    "ResultatSimulation",
    "date_option",
    "DISTANCE_MAX_ANALYSE_M",
    "NOM_CALIBRATION",
    "ResultatCalibration",
    "alerte_calibration",
    "calibrer_velo",
    "chemin_calibration",
    "ecrire_calibration",
    "executer_analyser",
    "executer_calibrer",
    "executer_simuler",
    "fourchette_du_velo",
    "lire_calibration",
    "masse_totale_kg",
    "parametres_du_velo",
    "puissance_voulue",
    "velo_demande",
    "vent_depuis_meteo",
]
