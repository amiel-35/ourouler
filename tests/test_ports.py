"""Les clients concrets satisfont les protocoles du noyau, tels quels.

`ourouler.noyau.ports` décrit ce que le domaine demande ; les connecteurs n'en
héritent pas. La conformité est donc de forme, et elle se vérifie ici,
méthode par méthode : chaque paramètre du protocole existe chez le client,
sous le même nom et de la même sorte (positionnel ou nommé seulement), avec
une valeur par défaut si le protocole en a une ; un paramètre que le client
ajoute doit avoir une valeur par défaut, pour qu'un appel écrit contre le
protocole reste valide.
"""

from __future__ import annotations

import inspect
from typing import Protocol

import pytest

from ourouler.activites.cache import Cache
from ourouler.connecteurs.brouter import ClientBrouter
from ourouler.connecteurs.intervals import ClientIntervals
from ourouler.meteo.openmeteo import ClientOpenMeteo
from ourouler.noyau.ports import DepotActivites, Routeur, SourcePrevisions, SourceSeances

PAIRES = [
    (Routeur, ClientBrouter),
    (SourcePrevisions, ClientOpenMeteo),
    (SourceSeances, ClientIntervals),
    (DepotActivites, Cache),
]


def _methodes(protocole: type) -> list[str]:
    return [nom for nom, valeur in vars(protocole).items() if callable(valeur) and not nom.startswith("_")]


def ecarts(protocole: type, concret: type) -> list[str]:
    """Ce qui empêche `concret` de satisfaire `protocole` ; vide s'il le satisfait."""
    trouves = []
    for nom in _methodes(protocole):
        attendu = getattr(protocole, nom)
        reel = getattr(concret, nom, None)
        if reel is None or not callable(reel):
            trouves.append(f"{concret.__name__}.{nom} manque")
            continue
        voulus = inspect.signature(attendu).parameters
        offerts = inspect.signature(reel).parameters
        for p in voulus.values():
            q = offerts.get(p.name)
            if q is None:
                trouves.append(f"{concret.__name__}.{nom} : pas de paramètre `{p.name}`")
            elif q.kind != p.kind:
                trouves.append(f"{concret.__name__}.{nom} : `{p.name}` est {q.kind.name}, pas {p.kind.name}")
            elif p.default is not inspect.Parameter.empty and q.default is inspect.Parameter.empty:
                trouves.append(f"{concret.__name__}.{nom} : `{p.name}` sans valeur par défaut")
        for q in offerts.values():
            if (
                q.name not in voulus
                and q.default is inspect.Parameter.empty
                and q.kind
                not in (
                    inspect.Parameter.VAR_POSITIONAL,
                    inspect.Parameter.VAR_KEYWORD,
                )
            ):
                trouves.append(f"{concret.__name__}.{nom} : `{q.name}` en plus, sans valeur par défaut")
        ordre_voulu = [n for n, p in voulus.items() if p.kind is not inspect.Parameter.KEYWORD_ONLY]
        ordre_offert = [n for n, p in offerts.items() if p.kind is not inspect.Parameter.KEYWORD_ONLY]
        if ordre_offert[: len(ordre_voulu)] != ordre_voulu:
            trouves.append(f"{concret.__name__}.{nom} : positionnels {ordre_offert}, attendu {ordre_voulu}")
    return trouves


@pytest.mark.parametrize(("protocole", "concret"), PAIRES, ids=lambda x: x.__name__)
def test_le_client_concret_satisfait_le_protocole(protocole, concret):
    assert issubclass(protocole, Protocol)
    assert _methodes(protocole), "un protocole sans méthode ne vérifie rien"
    assert ecarts(protocole, concret) == []


def test_un_ecart_se_voit():
    """Le test ci-dessus sait échouer : un client à qui il manque un paramètre est refusé."""

    class RouteurBoiteux:
        def boucle(self, depart, *, azimut_deg):  # ni rayon ni profil
            raise NotImplementedError

        def itineraire(self, points, *, profil=None, obligatoire):
            raise NotImplementedError

    trouves = ecarts(Routeur, RouteurBoiteux)
    assert any("`rayon_m`" in e for e in trouves)
    assert any("`profil`" in e for e in trouves)
    assert any("`obligatoire` en plus" in e for e in trouves)
