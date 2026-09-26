"""Le nouveau chemin de l'API (lot 11) : la demande, le service, le rendu JSON.

Chaque fonction de ce module est ce que l'ancien chemin faisait en passant
par la ligne de commande (`api/adaptateur.py` : un `argparse.Namespace`, la
commande, la sortie standard capturée sous un verrou global), écrit
directement :

1. la `Demande` du service, construite par la **même** fonction que la
   ligne de commande (`commandes.<commande>.demande`) sur les **mêmes**
   valeurs brutes — mêmes refus, mêmes messages, dans le même ordre ;
2. le `Contexte` du service, dont le canal `avertir` est celui que
   `double_chemin.executer_service` lui passe : les avertissements
   aboutissent au même champ `avertissements` qu'avant, sans passer par la
   sortie d'erreur du processus ;
3. l'appel au service (`service.executer(demande, contexte, clients…)`) ;
4. le rendu JSON, par les mêmes fonctions que `--json`.

Rien n'est imprimé ni capturé, aucun verrou n'est pris : deux requêtes
peuvent calculer en même temps.

**Les paramètres portent les noms des options de l'ancien chemin**
(`depart` pour l'heure de départ, `max`, `puissance`…) : une route décrit
son calcul une fois (`double_chemin.calculer`), et les deux chemins
reçoivent exactement les mêmes valeurs. C'est ce qui rend la comparaison du
mode `double` probante.
"""

from __future__ import annotations

from collections.abc import Callable

from ourouler.commandes import boucle as cmd_boucle
from ourouler.commandes import geocoder as cmd_geocoder
from ourouler.commandes import inventaire as cmd_inventaire
from ourouler.commandes import meteo as cmd_meteo
from ourouler.commandes import physique as cmd_physique
from ourouler.commandes import routes as cmd_routes
from ourouler.commandes import seance as cmd_seance
from ourouler.commandes import sortie as cmd_sortie
from ourouler.commandes.commun import contexte
from ourouler.config import Config

Avertir = Callable[[str], None]


def geocoder(
    config: Config,
    avertir: Avertir,
    *,
    adresse: str,
    max: int | None = None,  # noqa: A002 — le nom de l'option `--max`
    ban: object | None = None,
    nominatim: object | None = None,
) -> dict:
    """`GET /geocodage` : tous les candidats, notés. Rien du cycliste n'est lu."""
    from ourouler.geocodage import commande as service
    from ourouler.geocodage.commande import rendre_json

    del config, avertir  # le géocodage ne lit aucun réglage et n'avertit de rien
    resultat = service.executer(
        cmd_geocoder.demande(adresse, maximum=max), None, ban=ban, nominatim=nominatim
    )
    return rendre_json(resultat.adresse, resultat.candidats)


def vent_depart(
    config: Config,
    avertir: Avertir,
    *,
    jour: str | None = None,
    depart: str | None = None,
    client_meteo: object | None = None,
    lieu_depart: object | None = None,
) -> dict:
    """`GET /vent-depart` : d'où vient le vent au départ (Q44)."""
    from ourouler.rendu.sortie import vent_depart_json
    from ourouler.sortie import commande as service

    demande = cmd_sortie.demande_vent(jour=jour, depart=depart)
    ctx = contexte(config, lieu_depart=lieu_depart, avertir=avertir)
    r = service.executer_vent(demande, ctx, client_meteo=client_meteo)
    return vent_depart_json(r.question, r.jour, r.depart)


def meteo(
    config: Config,
    avertir: Avertir,
    *,
    depart: str | None = None,
    horizon: int | None = None,
    distance: float | None = None,
    modele: str | None = None,
    second_avis: str | None = None,
    client: object | None = None,
    lieu_depart: object | None = None,
) -> dict:
    """`GET /meteo` : pluie, vent et ressenti par direction et par heure."""
    from ourouler.meteo import commande as service
    from ourouler.meteo.rapport import rendre_json

    del distance  # ne sert qu'au texte de la ligne de commande
    ctx = contexte(config, lieu_depart=lieu_depart, avertir=avertir)
    demande = cmd_meteo.demande(
        ctx.profil, depart=depart, horizon=horizon, modele=modele, second_avis=second_avis
    )
    return rendre_json(service.executer(demande, ctx, client=client))


def inventaire(
    config: Config,
    avertir: Avertir,
    *,
    depuis: str | None = None,
    cache: object | None = None,
) -> dict:
    """`GET /inventaire` : les sorties par vélo et par mois, sans synchroniser."""
    from ourouler.activites import commande as service

    ctx = contexte(config, avertir=avertir)
    demande = cmd_inventaire.demande(ctx.profil, depuis=depuis)
    return cmd_inventaire.json_inventaire(service.executer(demande, ctx, cache=cache))


def routes(
    config: Config,
    avertir: Avertir,
    *,
    action: str,
    appliquer: bool = False,
    client_brouter: object | None = None,
    base: object | None = None,
) -> dict:
    """`GET /routes/{action}` : `stats` ou `poids`, en lecture seule."""
    from ourouler.apprentissage import commande as service

    demande = cmd_routes.demande(action, appliquer=appliquer)
    resultat = service.executer(
        demande, contexte(config, avertir=avertir), client_brouter=client_brouter, base=base
    )
    return cmd_routes.json_routes(resultat)


def seance(
    config: Config,
    avertir: Avertir,
    *,
    jour: str | None = None,
    depuis: str | None = None,
    jusqua: str | None = None,
    fichier_seance: str | None = None,
    client: object | None = None,
) -> dict:
    """`GET /seances`, `GET /seances/{jour}`, `POST /seances/fichier`."""
    from ourouler.seance import commande as service

    demande = cmd_seance.demande(
        jour=jour, depuis=depuis, jusqua=jusqua, fichier_seance=fichier_seance
    )
    resultat = service.executer(demande, contexte(config, avertir=avertir), client=client)
    return cmd_seance.json_seance(resultat)


def simuler(
    config: Config,
    avertir: Avertir,
    *,
    gpx: str | None,
    puissance: float | None = None,
    velo: str | None = None,
    depart: str | None = None,
    client_meteo: object | None = None,
) -> dict:
    """`POST /simulations` : le temps d'un GPX à puissance constante."""
    from ourouler.physique import commande as service

    demande = cmd_physique.demande_simulation(
        gpx=gpx, velo=velo, puissance=puissance, depart=depart
    )
    r = service.executer_simuler(
        demande, contexte(config, avertir=avertir), client_meteo=client_meteo
    )
    return cmd_physique.json_simulation(r)


def analyser(
    config: Config,
    avertir: Avertir,
    *,
    gpx: str | None,
    puissance: float | None = None,
    velo: str | None = None,
    depart: str | None = None,
    client_meteo: object | None = None,
) -> dict:
    """`POST /parcours/analyser` : météo et durée porte à porte d'un parcours en main."""
    from ourouler.physique import commande as service

    demande = cmd_physique.demande_analyse(
        gpx=gpx, depart=depart, velo=velo, puissance=puissance
    )
    r = service.executer_analyser(
        demande, contexte(config, avertir=avertir), client_meteo=client_meteo
    )
    return cmd_physique.json_analyse(r)


def sortie(
    config: Config,
    avertir: Avertir,
    *,
    jour: str | None = None,
    depart: str | None = None,
    distance: float | None = None,
    direction: str | None = None,
    candidates: int | None = None,
    vent: str | None = None,
    velo: str | None = None,
    profil: str | None = None,
    fichier_seance: str | None = None,
    carte: str | None = None,
    ecraser: bool = False,
    client_brouter: object | None = None,
    client_meteo: object | None = None,
    client_intervals: object | None = None,
    lieu_depart: object | None = None,
    recueil_gpx: Callable | None = None,
    base_routes: object | None = None,
) -> dict:
    """`POST /sorties` : la séance du jour posée sur une boucle, page du jour écrite.

    Même ordre que la commande : le contexte (départ de cette requête), la
    demande validée sur la configuration, le service, puis `terminer`, qui
    écrit la page du jour et rend le JSON.
    """
    from ourouler.sortie import commande as service

    ctx = contexte(config, lieu_depart=lieu_depart, avertir=avertir)
    demande = cmd_sortie.demande(
        config,
        jour=jour,
        distance=distance,
        direction=direction,
        candidates=candidates,
        velo=velo,
        vent=vent,
        profil=profil,
        depart=depart,
        carte=carte,
        ecraser=ecraser,
        fichier_seance=fichier_seance,
    )
    resultat = service.executer(
        demande,
        ctx,
        client_brouter,
        client_meteo,
        client_intervals,
        recueil_gpx=recueil_gpx,
        base_routes=base_routes,
    )
    donnees, _ = cmd_sortie.terminer(demande, ctx, resultat, en_json=True)
    return donnees  # type: ignore[return-value]  # `en_json` : jamais `None`


def boucle(
    config: Config,
    avertir: Avertir,
    *,
    distance: float | None = None,
    direction: str | None = None,
    depart: str | None = None,
    candidates: int | None = None,
    profil: str | None = None,
    velo: str | None = None,
    puissance: float | None = None,
    sortie: str | None = None,
    ecraser: bool = False,
    client_brouter: object | None = None,
    client_meteo: object | None = None,
    lieu_depart: object | None = None,
    base_routes: object | None = None,
) -> dict:
    """`POST /boucles` : candidates, coûts, météo le long du tracé, GPX écrit."""
    from ourouler.boucle import commande as service

    ctx = contexte(config, lieu_depart=lieu_depart, avertir=avertir)
    demande = cmd_boucle.demande(
        ctx.profil,
        distance=distance,
        direction=direction,
        depart=depart,
        candidates=candidates,
        profil=profil,
        velo=velo,
        puissance=puissance,
        sortie=sortie,
        ecraser=ecraser,
    )
    r = service.executer(demande, ctx, client_brouter, client_meteo, base_routes=base_routes)
    cmd_boucle.avertir_meteo(r, ctx)
    return cmd_boucle.json_boucle(r)
