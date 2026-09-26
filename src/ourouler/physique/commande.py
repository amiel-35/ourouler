"""Sous-commandes `ourouler calibrer`, `ourouler simuler` et `ourouler analyser`.

Ce module est l'adaptateur de la ligne de commande : il lit les options
(argparse), résout les chemins (`calibration.json`, l'archive météo du
cache), appelle le cas d'usage et imprime son rendu. Depuis le lot 8, choisir
et lire les sorties à calibrer est `services.calibrer`, le calcul
`physique.calibration` (qui ne connaît ni chemin, ni cache, ni
configuration), et le texte comme le JSON `rendu.physique`.

`calibrer` enchaîne : choix des sorties → archives météo (mémoïsées) →
échantillons → deux passes d'ajustement → validation sur les sorties les plus
récentes → rapport et JSON. Les appels réseau sont ceux de l'archive, un par
jour de sortie, et une seule fois dans la vie du cache.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections.abc import Sequence
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path

from ourouler.activites.cache import Cache
from ourouler.boucle.gpx import lire_gpx_parcours, lire_gpx_trace
from ourouler.boucle.horaire import Pause, analyser_pause, construire_horaire, valider_pauses
from ourouler.boucle.meteo_trace import MeteoTrace
from ourouler.boucle.meteo_trace import evaluer as evaluer_meteo
from ourouler.config import Config
from ourouler.connecteurs.openmeteo_archive import ClientArchive
from ourouler.meteo import portee
from ourouler.meteo.openmeteo import ClientOpenMeteo
from ourouler.noyau.erreurs import ErreurConnecteur, ErreurUtilisateur
from ourouler.noyau.profil import Velo
from ourouler.physique import parametres_velo
from ourouler.physique.modele import (
    FourchettePorteAPorte,
    Parametres,
    puissance_a_plat_w,
    simuler,
    temps_ecoule,
    vent_au_cycliste,
)

# Réexports temporaires (lot 7) : l'ancien emplacement de ce qui touche à
# `calibration.json`, retirés avec les autres réexports au lot final.
from ourouler.physique.parametres_velo import (
    ALERTE_PNEU_CHANGE,
    CDA_DEFAUT,
    CRR_DEFAUT,
    Calibration,
    crr_du_velo,
    fourchette_defaut,
)

# Réexports temporaires (lot 8) : le rendu (`rendu.physique`) et le cas
# d'usage de la calibration (`services.calibrer`) à leur ancien emplacement,
# pour les appelants que ce lot ne touche pas (`boucle/commande.py`, les
# scripts de `tests/validation/`) ; retirés avec les autres au lot final.
# Ils sont liés **par nom** : remplacer l'un d'eux ici ne change rien à qui
# l'appelle ailleurs. Un monkeypatch de test vise donc `services.calibrer`
# pour ce que l'API appelle (`calibrer_velo`), et `physique.commande` pour ce
# que la ligne de commande appelle depuis ce module.
from ourouler.rendu.physique import (
    MENTION_MODELE,
    MENTION_MODELE_LITTERATURE,
    lignes_litterature,
    litterature_json,
    rendre_json_analyse,
    rendre_json_calibration,
    rendre_json_simulation,
    rendre_texte_analyse,
    rendre_texte_calibration,
    rendre_texte_simulation,
)
from ourouler.services.calibrer import (
    ETAPE_AJUSTEMENT,
    ETAPE_LECTURE,
    ETAPE_METEO,
    Progres,
    ResultatCalibration,
    calibrer_velo,
    crr_de_l_usage,
    masse_totale_kg,
)
from ourouler.stockage.calibrations import (
    VERSION_CALIBRATION,
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
# signatures d'avant — une `Config` et un chemin — pour les appelants : elles
# lisent et délèguent.


def chemin_calibration(config: Config) -> Path:
    """Le `calibration.json` de cette configuration.

    Dans le dossier de cache pour la ligne de commande ; à l'endroit que la
    couche web a posé pour un compte hébergé (`ParametresCache.fichier_calibration`,
    L9.4) — c'est ce qui fait que les boucles, les sorties et les simulations
    d'un compte lisent **sa** calibration, et jamais celle d'un autre.
    """
    if config.cache.fichier_calibration is not None:
        return config.cache.fichier_calibration
    return config.cache.dossier / NOM_CALIBRATION


def parametres_du_velo(config: Config, velo: Velo, chemin: Path) -> tuple[Parametres, str]:
    """(paramètres, provenance) du vélo : voir `physique.parametres_velo.parametres_du_velo`."""
    return parametres_velo.parametres_du_velo(
        velo, masse_totale_kg(config, velo), lire_calibration(chemin, velo.nom)
    )


def alerte_calibration(velo: Velo, chemin: Path) -> str | None:
    """L'alerte « pneu changé » : voir `physique.parametres_velo.alerte_calibration`."""
    return parametres_velo.alerte_calibration(velo, lire_calibration(chemin, velo.nom))


def fourchette_du_velo(velo: Velo, chemin: Path) -> FourchettePorteAPorte:
    """La fourchette du porte à porte : voir `physique.parametres_velo.fourchette_du_velo`."""
    return parametres_velo.fourchette_du_velo(lire_calibration(chemin, velo.nom))



def puissance_voulue(args: argparse.Namespace, parametres: Parametres) -> float | None:
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
    puissance = getattr(args, "puissance", None)
    vitesse = getattr(args, "vitesse_a_plat", None)
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


def velo_demande(config: Config, nom: str | None) -> Velo:
    """Le vélo nommé, ou le premier vélo d'usage route (`parametres_velo.velo_demande`)."""
    return parametres_velo.velo_demande(config, nom)



# --- ourouler calibrer --------------------------------------------------------


def executer_calibrer(
    args: argparse.Namespace,
    config: Config,
    client_archive: ClientArchive | None = None,
    cache: Cache | None = None,
) -> int:
    """Calibre un vélo sur les sorties réelles du cache. Code de sortie 0 si ça a marché.

    **`cache` s'injecte** (L9.4), sur le patron d'`activites/commande.executer` :
    absent — la ligne de commande —, la commande construit celui du
    propriétaire local sur `config.cache.dossier`, comme avant. Le calcul
    lui-même est `calibrer_velo`, qui n'imprime rien : c'est lui que la tâche
    de fond de l'API appelle (`api/calibrations.py`), parce qu'une commande
    qui écrit sur la sortie standard ne peut pas tourner dans un fil pendant
    que d'autres requêtes capturent la leur (`api/adaptateur.py`).
    """
    velo = velo_demande(config, getattr(args, "velo", None))
    cache = cache if cache is not None else Cache(config.cache.dossier)
    client = (
        client_archive
        if client_archive is not None
        else ClientArchive(chemin_cache=config.cache.dossier / NOM_CACHE)
    )
    resultat = calibrer_velo(
        config,
        velo,
        cache,
        client,
        depuis=_date_option(getattr(args, "depuis", None), config.historique_depuis),
        maximum=getattr(args, "max", None),
        crr_libre=bool(getattr(args, "crr_libre", False)),
    )

    chemin = chemin_calibration(config)
    ecrire_calibration(chemin, velo.nom, resultat.contenu())
    for panne in resultat.pannes:
        print(f"ourouler : {panne}", file=sys.stderr)
    options = {
        "depuis": config.historique_depuis,
        "fichier": chemin,
        "archives_appels": client.appels,
        "archives_cache": client.lectures_cache,
        "motifs": resultat.motifs,
        "n_calibrables": resultat.n_calibrables,
        "crr_source": resultat.crr_source,
    }
    if getattr(args, "json", False):
        print(
            json.dumps(
                rendre_json_calibration(resultat.rapport, velo, **options),
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print(rendre_texte_calibration(resultat.rapport, velo, **options))
    return 0



# --- ourouler simuler ---------------------------------------------------------


def executer_simuler(
    args: argparse.Namespace, config: Config, client_meteo: ClientOpenMeteo | None = None
) -> int:
    """Simule un GPX à puissance constante, avec le vent prévu si un départ est donné."""
    chemin_gpx = getattr(args, "gpx", None)
    if not chemin_gpx:
        raise ErreurUtilisateur("simuler : --gpx FICHIER.GPX est obligatoire")
    chemin_gpx = Path(chemin_gpx)
    if not chemin_gpx.is_file():
        raise ErreurUtilisateur(f"--gpx {chemin_gpx} : fichier introuvable")

    # Les paramètres du vélo sont résolus **avant** la puissance : une vitesse
    # à plat ne se convertit en watts qu'avec eux (L8.5, lot C).
    velo = velo_demande(config, getattr(args, "velo", None))
    parametres, provenance = parametres_du_velo(config, velo, chemin_calibration(config))
    alerte = alerte_calibration(velo, chemin_calibration(config))
    puissance = puissance_voulue(args, parametres)
    if puissance is None:
        raise ErreurUtilisateur(
            "simuler : donner --puissance W, ou --vitesse-a-plat KMH pour qui ne connaît "
            "pas sa puissance"
        )
    if not (0 < float(puissance) <= 2000):
        vitesse = getattr(args, "vitesse_a_plat", None)
        if vitesse is not None:
            raise ErreurUtilisateur(
                f"--vitesse-a-plat {vitesse} : il faudrait {puissance:.0f} W pour la tenir "
                f"à plat sur le {velo.nom}, au-delà des 2000 W que le modèle accepte"
            )
        raise ErreurUtilisateur(
            f"--puissance {puissance} : une puissance en watts entre 1 et 2000 est attendue"
        )
    trace = lire_gpx_trace(chemin_gpx)

    pauses = tuple(analyser_pause(p) for p in getattr(args, "pause", None) or [])
    valider_pauses(pauses, distance_m=trace.distance_m)

    vent = None
    panne = None
    depart_brut = getattr(args, "depart", None)
    depart_dt: datetime | None = None
    if depart_brut:
        from ourouler.meteo.commande import heure_depart

        depart_dt = heure_depart(depart_brut)
        client = client_meteo if client_meteo is not None else ClientOpenMeteo()
        try:
            vent, resume = vent_prevu(trace, client, config, depart_dt, pauses=pauses)
        except ErreurConnecteur as e:
            panne, resume = str(e), None
    else:
        resume = None
        if pauses:
            # Une pause décale l'heure de passage météo ; sans départ, il n'y
            # a pas d'heure à décaler — le signaler plutôt que de laisser
            # croire que `--pause` a joué un rôle.
            print(
                "ourouler : --pause sans --heure-depart n'a aucun effet "
                "(rien à dater sans heure de départ)",
                file=sys.stderr,
            )

    simulation = simuler(trace, float(puissance), parametres, vent=vent)
    arrivee = (
        depart_dt + timedelta(seconds=simulation.temps_s + _duree_pauses_s(pauses))
        if depart_dt is not None
        else None
    )
    if panne is not None:
        print(f"ourouler : météo indisponible ({panne}) — simulation à vent nul", file=sys.stderr)
    if getattr(args, "json", False):
        print(
            json.dumps(
                rendre_json_simulation(
                    simulation, trace, velo, parametres, provenance, float(puissance),
                    meteo=resume, pauses=pauses, arrivee=arrivee, alerte=alerte,
                ),
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print(
            rendre_texte_simulation(
                simulation, trace, velo, parametres, provenance, float(puissance),
                meteo=resume, pauses=pauses, arrivee=arrivee, alerte=alerte,
            )
        )
    return 0


def _duree_pauses_s(pauses: Sequence[Pause]) -> float:
    return sum(p.duree_s for p in pauses)


def vent_prevu(
    trace, client: ClientOpenMeteo, config: Config, depart: datetime, *, pauses: Sequence[Pause] = ()
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
        horaire=construire_horaire(depart, config.boucle.vitesse_moyenne_kmh, pauses),
        modele=config.meteo.modele,
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


def executer_analyser(
    args: argparse.Namespace, config: Config, client_meteo: ClientOpenMeteo | None = None
) -> int:
    """Analyse un parcours **déjà en main** (BRM, Flèche, boucle de club) : durée porte à
    porte en fourchette, météo par tronçon à l'heure où on y passe, heure d'arrivée.

    C'est `ourouler simuler` retourné dans l'autre sens : `simuler` chronomètre un GPX à
    puissance constante et prend la météo en option ; `analyser` part d'un parcours qu'on
    n'a pas choisi (l'imposé d'un brevet, la boucle du club) et veut savoir **quand** on
    y passera et ce qu'on y trouvera — `--heure-depart` y est donc obligatoire, là où
    `simuler` s'en passe.

    **La puissance, par défaut, est celle de l'endurance du profil** :
    `config.seance.puissance_endurance_pct × config.cycliste.ftp_w` — le même calcul que
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

    **Horizon météo** : au-delà de `config.meteo.horizon_jours`, aucun appel n'est fait —
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
    chemin_gpx = getattr(args, "gpx", None)
    if not chemin_gpx:
        raise ErreurUtilisateur("analyser : --gpx FICHIER.GPX est obligatoire")
    chemin_gpx = Path(chemin_gpx)
    if not chemin_gpx.is_file():
        raise ErreurUtilisateur(f"--gpx {chemin_gpx} : fichier introuvable")

    depart_brut = getattr(args, "depart", None)
    if not depart_brut:
        raise ErreurUtilisateur(
            "analyser : --heure-depart est obligatoire (sans elle, rien à caler dans le "
            "temps — ni la météo, ni l'heure d'arrivée)"
        )
    from ourouler.meteo.commande import heure_depart

    depart_dt = heure_depart(depart_brut)

    trace, avertissements_trace = lire_gpx_parcours(chemin_gpx)
    for avertissement in avertissements_trace:
        print(f"ourouler : {avertissement}", file=sys.stderr)
    if trace.distance_m > DISTANCE_MAX_ANALYSE_M:
        raise ErreurUtilisateur(
            f"analyser : {trace.distance_m / 1000:.0f} km, au-delà des "
            f"{DISTANCE_MAX_ANALYSE_M / 1000:.0f} km qu'un parcours à analyser accepte"
        )

    velo = velo_demande(config, getattr(args, "velo", None))
    parametres, provenance = parametres_du_velo(config, velo, chemin_calibration(config))
    alerte = alerte_calibration(velo, chemin_calibration(config))

    puissance = puissance_voulue(args, parametres)
    if puissance is None:
        if config.cycliste.ftp_w is None:
            raise ErreurUtilisateur(
                "analyser : donner --puissance W ou --vitesse-a-plat KMH — aucune FTP dans "
                "le profil pour calculer par défaut la puissance d'endurance"
            )
        puissance = config.seance.puissance_endurance_pct * config.cycliste.ftp_w
    if not (0 < float(puissance) <= 2000):
        raise ErreurUtilisateur(
            f"--puissance {puissance} : une puissance en watts entre 1 et 2000 est attendue"
        )
    puissance = float(puissance)

    client = client_meteo if client_meteo is not None else ClientOpenMeteo()
    fourchette = fourchette_du_velo(velo, chemin_calibration(config))

    dernier_jour = portee.dernier_jour_couvert(config.meteo.horizon_jours, aujourdhui=date.today())
    jour_demande = depart_dt.date()
    meteo_absente = (
        portee.constater(jour_demande, dernier_jour) if jour_demande > dernier_jour else None
    )

    meteo: MeteoTrace | None = None
    panne: str | None = None
    vitesse_a_vent_nul = _vitesse_a_vent_nul(trace, puissance, parametres, config)
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
                modele=config.meteo.modele,
                second_avis=config.meteo.second_avis,
                # Même repli que `boucle`/`sortie` (Q19) : un parcours plus
                # long que la portée horaire du modèle régional ne perd pas
                # toute sa météo, seulement la partie que le repli ne couvre
                # pas non plus.
                modele_repli=config.meteo.second_avis,
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
        print(f"ourouler : météo indisponible ({panne}) — durée rendue sans météo", file=sys.stderr)
    elif meteo_absente is not None:
        print(f"ourouler : {meteo_absente.message} — durée rendue sans météo", file=sys.stderr)

    if getattr(args, "json", False):
        print(
            json.dumps(
                rendre_json_analyse(
                    simulation, trace, velo, parametres, provenance, puissance,
                    meteo=meteo, ecoule=ecoule, depart=depart_dt, arrivee_bas=arrivee_bas,
                    arrivee_mediane=arrivee_mediane, arrivee_haut=arrivee_haut,
                    alerte=alerte, meteo_absente=meteo_absente, fourchette=fourchette,
                    panne=panne, avertissements_trace=avertissements_trace,
                    vitesse_a_vent_nul_kmh=vitesse_a_vent_nul,
                ),
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print(
            rendre_texte_analyse(
                simulation, trace, velo, parametres, provenance, puissance,
                meteo=meteo, ecoule=ecoule, depart=depart_dt, arrivee_mediane=arrivee_mediane,
                alerte=alerte, meteo_absente=meteo_absente, panne=panne,
            )
        )
    return 0


def _vitesse_a_vent_nul(
    trace, puissance_w: float, parametres: Parametres, config: Config
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
        return config.boucle.vitesse_moyenne_kmh
    if not math.isfinite(vitesse) or vitesse <= 0:
        return config.boucle.vitesse_moyenne_kmh
    return vitesse


# --- options ------------------------------------------------------------------


def _date_option(texte: str | None, defaut: date) -> date:
    if not texte:
        return defaut
    try:
        return date.fromisoformat(str(texte).strip())
    except ValueError as e:
        raise ErreurUtilisateur(f"--depuis {texte!r} : date AAAA-MM-JJ attendue") from e


__all__ = [
    "DISTANCE_MAX_ANALYSE_M",
    "NOM_CALIBRATION",
    "VERSION_CALIBRATION",
    "CDA_DEFAUT",
    "CRR_DEFAUT",
    "ALERTE_PNEU_CHANGE",
    "ETAPE_AJUSTEMENT",
    "ETAPE_LECTURE",
    "ETAPE_METEO",
    "MENTION_MODELE",
    "MENTION_MODELE_LITTERATURE",
    "Calibration",
    "Progres",
    "ResultatCalibration",
    "alerte_calibration",
    "calibrer_velo",
    "chemin_calibration",
    "crr_de_l_usage",
    "crr_du_velo",
    "ecrire_calibration",
    "executer_analyser",
    "executer_calibrer",
    "executer_simuler",
    "fourchette_defaut",
    "fourchette_du_velo",
    "lignes_litterature",
    "lire_calibration",
    "litterature_json",
    "masse_totale_kg",
    "parametres_du_velo",
    "puissance_voulue",
    "rendre_json_analyse",
    "rendre_json_calibration",
    "rendre_json_simulation",
    "rendre_texte_analyse",
    "rendre_texte_calibration",
    "rendre_texte_simulation",
    "velo_demande",
    "vent_depuis_meteo",
]
