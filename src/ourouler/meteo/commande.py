"""Sous-commande `ourouler meteo` : couronne → deux appels Open-Meteo → rapport.

Ce module est appelé par `cli.py` et ne lit rien : il reçoit `args` et
`config`. Le client est injectable pour que les tests ne touchent jamais le
réseau.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime

from ourouler.config import HORIZON_MAX_H, Config
from ourouler.erreurs import ErreurConnecteur, ErreurUtilisateur
from ourouler.meteo.couronne import couronne
from ourouler.meteo.openmeteo import ClientOpenMeteo
from ourouler.meteo.rapport import construire, rendre_json, rendre_texte

#: Horizon maximal accepté : au-delà, AROME HD n'a plus rien à dire. Défini
#: dans `config`, qui valide `[meteo] horizon_h` au chargement ; importé ici
#: pour que `--horizon` applique exactement la même borne.


def executer(args: argparse.Namespace, config: Config, client: ClientOpenMeteo | None = None) -> int:
    """Exécute `ourouler meteo`. Renvoie le code de sortie (0 = succès)."""
    modele = getattr(args, "modele", None) or config.meteo.modele
    second_avis = getattr(args, "second_avis", None) or config.meteo.second_avis
    # `or` ne conviendrait pas : --horizon 0 doit être refusé, pas remplacé par la config.
    demande = getattr(args, "horizon", None)
    horizon_h = config.meteo.horizon_h if demande is None else demande
    if horizon_h < 1 or horizon_h > HORIZON_MAX_H:
        raise ErreurUtilisateur(
            f"horizon de {horizon_h} h : attendu entre 1 et {HORIZON_MAX_H} "
            "(option --horizon, ou [meteo] horizon_h dans la configuration)"
        )

    # Heure locale, consciente du fuseau : le client la convertit en UTC lui-même.
    debut = heure_depart(getattr(args, "depart", None))

    points = couronne(config.depart, config.meteo.directions, config.meteo.distances_km)
    coordonnees = [(p.lat, p.lon) for p in points]

    client = client if client is not None else ClientOpenMeteo()
    principale = client.previsions(coordonnees, modele=modele, debut=debut, horizon_h=horizon_h)

    second = None
    if second_avis and second_avis != modele:
        try:
            second = client.previsions(coordonnees, modele=second_avis, debut=debut, horizon_h=horizon_h)
        except ErreurConnecteur as e:
            print(
                f"ourouler : second avis « {second_avis} » indisponible ({e}) — "
                "confiance « inconnu » sur toutes les cellules",
                file=sys.stderr,
            )

    rapport = construire(
        config.depart,
        points,
        principale,
        second,
        debut,
        horizon_h,
        modele=modele,
        second_avis=second_avis,
    )

    if getattr(args, "json", False):
        print(json.dumps(rendre_json(rapport), ensure_ascii=False, indent=2))
    else:
        print(rendre_texte(rapport, distance_km=getattr(args, "distance", None)))
    return 0


def heure_depart(depart: str | None, maintenant: datetime | None = None) -> datetime:
    """Interprète `--heure-depart` en **heure locale**, ramenée au début de l'heure.

    `None` → l'heure courante. `HH:MM` → aujourd'hui à cette heure.
    `AAAA-MM-JJTHH:MM` → cette date et cette heure. Les minutes sont
    tronquées : les prévisions Open-Meteo sont horaires.

    Le piège : `datetime.now().astimezone()` porte un fuseau à décalage
    **fixe** (CEST +02:00 en septembre). Recopier ce décalage sur une date
    demandée de l'autre côté d'un changement d'heure décalait toute la
    fenêtre de prévision d'une heure. On ne recopie donc pas le décalage
    d'aujourd'hui : `astimezone()` sur l'horodatage naïf applique le
    décalage réel du fuseau du système **pour cette date-là**. Quand
    l'appelant injecte `maintenant` (tests), c'est son fuseau qui sert : un
    `ZoneInfo` calcule ses changements d'heure tout seul.
    """
    if maintenant is None:
        reference = datetime.now().astimezone()
        zone = None  # « fuseau du système », résolu date par date via astimezone()
    else:
        reference = maintenant if maintenant.tzinfo is not None else maintenant.astimezone()
        zone = reference.tzinfo
    if depart is None:
        return reference.replace(minute=0, second=0, microsecond=0)
    texte = depart.strip()
    if not texte:
        # `--heure-depart ''` (ou que des blancs) n'est pas « pas d'option » : c'est
        # une valeur fournie et illisible. C'était confondu avec `None`, donc
        # la commande partait interroger Open-Meteo comme si de rien n'était,
        # au lieu de refuser avant tout appel comme pour « 25:00 ».
        raise ErreurUtilisateur(
            f"--heure-depart {depart!r} : valeur vide, attendu HH:MM ou AAAA-MM-JJTHH:MM "
            "(heure locale) — omettre l'option pour partir à l'heure courante"
        )

    essais = (
        lambda: datetime.combine(reference.date(), datetime.strptime(texte, "%H:%M").time()),
        lambda: datetime.fromisoformat(texte),
    )
    for essai in essais:
        try:
            t = essai()
        except ValueError:
            continue
        # Tronquer avant d'attacher le fuseau : le décalage est celui de l'heure retenue.
        t = t.replace(minute=0, second=0, microsecond=0)
        if t.tzinfo is not None:
            return t
        return t.astimezone() if zone is None else t.replace(tzinfo=zone)
    raise ErreurUtilisateur(
        f"--heure-depart {depart!r} : attendu HH:MM ou AAAA-MM-JJTHH:MM (heure locale)"
    )
