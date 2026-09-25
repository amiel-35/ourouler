"""Ports : ce que le domaine demande aux services extérieurs, sans les connaître.

Le domaine (`boucle`, `seance`, `sortie`…) reçoit un objet qui sait répondre
à ces questions ; il n'importe jamais le client HTTP qui y répond
(`docs/ouverture_plan.md` §2, lot 9). Les clients concrets de `connecteurs/`
et `meteo/openmeteo.py` satisfont ces protocoles **tels quels**, sans en
hériter : c'est une conformité de forme, que
`tests/test_ports.py` vérifie signature par signature.

Chaque protocole ne porte que les méthodes que le code appelle vraiment, avec
les seuls paramètres qu'il passe. Un client concret peut en accepter d'autres,
pourvu qu'ils aient une valeur par défaut.

Aucune implémentation ici : des `typing.Protocol`, rien d'autre.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime
from typing import Protocol

from ourouler.noyau.meteo import PrevisionPoint
from ourouler.noyau.trace import Trace


class Routeur(Protocol):
    """Un moteur de tracé : BRouter, aujourd'hui (`connecteurs.brouter.ClientBrouter`).

    Les points sont des couples `(lat, lon)` en degrés. Une panne, un refus du
    moteur ou une réponse illisible lèvent `ErreurConnecteur`.
    """

    def boucle(
        self,
        depart: tuple[float, float],
        *,
        azimut_deg: float,
        rayon_m: float,
        profil: str | None = None,
    ) -> Trace:
        """Une boucle partant de `depart` vers `azimut_deg`.

        `rayon_m` est le rayon demandé au moteur, pas la longueur de la boucle :
        c'est `boucle.candidates` qui ajuste l'un sur l'autre.
        """
        ...

    def itineraire(
        self, points: Sequence[tuple[float, float]], *, profil: str | None = None
    ) -> Trace:
        """Un itinéraire A→B passant par `points`, au moins deux."""
        ...


class SourcePrevisions(Protocol):
    """Une source de prévisions horaires : Open-Meteo (`meteo.openmeteo.ClientOpenMeteo`).

    Une panne lève `ErreurConnecteur` ; une fenêtre hors de la portée du
    modèle, `ErreurHorsDomaine`.
    """

    def previsions(
        self,
        points: Sequence[tuple[float, float]],
        *,
        modele: str,
        debut: datetime,
        horizon_h: int,
    ) -> list[PrevisionPoint]:
        """Les prévisions de `horizon_h` heures à partir de `debut`, pour chaque point."""
        ...


class SourceSeances(Protocol):
    """Un calendrier de séances planifiées : Intervals.icu (`connecteurs.intervals.ClientIntervals`)."""

    def evenements(self, depuis: date, jusqua: date | None = None) -> list[dict]:
        """Les événements bruts d'une plage de jours locaux, bornes incluses."""
        ...
