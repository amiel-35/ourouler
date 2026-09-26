"""Sous-commande `ourouler meteo` : couronne → deux appels Open-Meteo → rapport.

Le cas d'usage (`executer`) reçoit une `DemandeMeteo` déjà interprétée par
l'entrée (`commandes/meteo.py`) et un `Contexte` ; il rend le rapport, sans
rien imprimer. Le client est injectable pour que les tests ne touchent
jamais le réseau.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from ourouler.meteo.couronne import couronne
from ourouler.meteo.openmeteo import ClientOpenMeteo
from ourouler.meteo.rapport import RapportMeteo, construire
from ourouler.noyau.erreurs import ErreurConnecteur, ErreurUtilisateur
from ourouler.noyau.profil import HORIZON_MAX_H
from ourouler.services.contexte import Contexte

#: Horizon maximal accepté : au-delà, AROME HD n'a plus rien à dire. Défini
#: dans `config`, qui valide `[meteo] horizon_h` au chargement ; importé ici
#: pour que `--horizon` applique exactement la même borne.


@dataclass(frozen=True)
class DemandeMeteo:
    """Ce que le cycliste demande, déjà interprété : quand, sur combien d'heures, quels modèles."""

    debut: datetime
    horizon_h: int
    modele: str
    second_avis: str | None


def executer(
    demande: DemandeMeteo,
    contexte: Contexte,
    client: ClientOpenMeteo | None = None,
) -> RapportMeteo:
    """Exécute `ourouler meteo` : le rapport par direction et par heure.

    Le point de départ est `contexte.profil.depart` : l'entrée y a déjà mis
    celui de **cette** exécution (`--adresse-depart` géocodée, ou les
    coordonnées que l'API a reçues). Le cœur ne géocode rien, ne lit aucune
    adresse et ne sait pas d'où vient ce point (le cœur ne lit ni configuration ni environnement).
    """
    profil = contexte.profil
    modele, second_avis = demande.modele, demande.second_avis
    points = couronne(profil.depart, profil.meteo.directions, profil.meteo.distances_km)
    coordonnees = [(p.lat, p.lon) for p in points]

    client = client if client is not None else ClientOpenMeteo()
    principale = client.previsions(
        coordonnees, modele=modele, debut=demande.debut, horizon_h=demande.horizon_h
    )

    second = None
    if second_avis and second_avis != modele:
        try:
            second = client.previsions(
                coordonnees, modele=second_avis, debut=demande.debut, horizon_h=demande.horizon_h
            )
        except ErreurConnecteur as e:
            contexte.avertir(
                f"ourouler : second avis « {second_avis} » indisponible ({e}) — "
                "confiance « inconnu » sur toutes les cellules"
            )

    return construire(
        profil.depart,
        points,
        principale,
        second,
        demande.debut,
        demande.horizon_h,
        modele=modele,
        second_avis=second_avis,
    )


def valider_horizon(horizon_h: int) -> int:
    """L'horizon en heures, borné comme `[meteo] horizon_h` l'est au chargement."""
    if horizon_h < 1 or horizon_h > HORIZON_MAX_H:
        raise ErreurUtilisateur(
            f"horizon de {horizon_h} h : attendu entre 1 et {HORIZON_MAX_H} "
            "(option --horizon, ou [meteo] horizon_h dans la configuration)"
        )
    return horizon_h


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
    raise ErreurUtilisateur(f"--heure-depart {depart!r} : attendu HH:MM ou AAAA-MM-JJTHH:MM (heure locale)")
