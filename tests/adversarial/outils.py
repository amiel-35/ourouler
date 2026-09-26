"""Outils partagés par les tests adversariaux.

Trois familles :

* **vérificateurs d'invariants** (`verifier_json`, `verifier_activite`,
  `verifier_utc`) : ce qui doit être vrai quelle que soit l'implémentation ;
* **tolérance au flou du contrat** (`robuste`) : quand le contrat ne tranche
  pas, on n'invente pas un comportement — on exige seulement qu'aucune
  exception « bug » ne s'échappe et que l'objet rendu reste cohérent ;
* **accès souple aux dataclasses** (`champ`, `fabriquer`) : le contrat donne
  la liste des champs de `EntreeCache` et de `RapportSynchro` mais pas leur
  ordre ni leurs valeurs par défaut ; on les construit par introspection,
  tout en vérifiant que les champs du contrat existent bien.
"""

from __future__ import annotations

import dataclasses
import json
import math
import unicodedata
from datetime import datetime, timedelta
from typing import Any

# Chaîne qui joue le rôle d'une clé d'API. Ce n'est pas une clé : aucune
# valeur réelle n'entre dans ce dépôt (règle absolue 1).
CLE_BIDON = "clef-de-test-qui-ne-doit-jamais-fuiter-0123456789"
ATHLETE_BIDON = "i000000"


class ReseauInterdit(BaseException):
    """Un test a tenté d'ouvrir une connexion. Règle absolue 3 de CLAUDE.md.

    Définie ici plutôt que dans `conftest.py` : quatre `conftest.py` coexistent
    sous `tests/`, et `from conftest import …` dépend de l'ordre de collecte.
    """


# --- invariants -------------------------------------------------------------


def verifier_json(objet: Any, quoi: str = "objet") -> str:
    """`objet` doit être sérialisable JSON sans `default=`. Renvoie le JSON."""
    try:
        return json.dumps(objet, ensure_ascii=False)
    except TypeError as e:  # datetime, Path, bytes, set, dataclasse…
        raise AssertionError(f"{quoi} n'est pas sérialisable JSON tel quel : {e}") from e


def verifier_utc(t: Any, quoi: str) -> datetime:
    assert isinstance(t, datetime), f"{quoi} : datetime attendu, reçu {type(t).__name__} ({t!r})"
    assert t.tzinfo is not None, (
        f"{quoi} : horodatage naïf, le contrat demande un instant conscient du fuseau"
    )
    decalage = t.utcoffset()
    assert decalage == timedelta(0), f"{quoi} : attendu en UTC, décalage {decalage}"
    return t


def _verifier_nombre(valeur: Any, quoi: str, *, positif: bool = True) -> None:
    if valeur is None:
        return
    assert isinstance(valeur, (int, float)) and not isinstance(valeur, bool), (
        f"{quoi} : nombre ou None attendu, reçu {type(valeur).__name__} ({valeur!r})"
    )
    assert not math.isnan(valeur), f"{quoi} : NaN (division par zéro ou moyenne sur zéro point ?)"
    assert math.isfinite(valeur), f"{quoi} : valeur infinie"
    if positif:
        assert valeur >= 0, f"{quoi} : valeur négative ({valeur})"


def verifier_activite(a: Any, *, source_attendue: str | None = None) -> None:
    """Invariants du modèle `Activite`, valables pour tout fichier lu."""
    assert a.source in ("fit", "gpx", "tcx"), f"source inattendue : {a.source!r}"
    if source_attendue:
        assert a.source == source_attendue, f"source {a.source!r}, attendu {source_attendue!r}"
    verifier_utc(a.debut, "Activite.debut")
    assert isinstance(a.duree_s, (int, float)), "Activite.duree_s : nombre attendu"
    assert a.duree_s >= 0, f"Activite.duree_s négatif ({a.duree_s})"
    assert isinstance(a.points, list) and a.points, "Activite.points : liste non vide attendue"
    for i, p in enumerate(a.points):
        verifier_utc(p.t, f"points[{i}].t")
        if p.lat is not None:
            assert -90.0 <= p.lat <= 90.0, f"points[{i}].lat hors bornes : {p.lat}"
        if p.lon is not None:
            assert -180.0 <= p.lon <= 180.0, f"points[{i}].lon hors bornes : {p.lon}"
        assert (p.lat is None) == (p.lon is None), f"points[{i}] : latitude et longitude désolidarisées"
        for nom in ("puissance_w", "cadence_rpm", "fc_bpm", "dist_m", "vitesse_ms", "alt_m", "temp_c"):
            _verifier_nombre(getattr(p, nom), f"points[{i}].{nom}", positif=nom not in ("alt_m", "temp_c"))
    for nom in ("distance_m", "denivele_m", "puissance_moy_w", "puissance_np_w", "duree_mouvement_s"):
        _verifier_nombre(getattr(a, nom), f"Activite.{nom}")
    assert isinstance(a.meta, dict), "Activite.meta : dict attendu"
    verifier_json(a.meta, "Activite.meta")
    if a.fichier is not None:
        assert isinstance(a.fichier, str), "Activite.fichier : str | None (le contrat exclut Path)"


def robuste(appel, *, quoi: str, erreurs_acceptees: tuple[type[BaseException], ...]):
    """Exécute `appel` : soit une erreur utilisateur documentée, soit un résultat.

    Sert aux entrées pour lesquelles le contrat ne dit pas explicitement s'il
    faut refuser ou dégrader. Ce qui n'est jamais acceptable, c'est une
    exception « bug » (ValueError, KeyError, IndexError, AttributeError,
    TypeError, ZeroDivisionError…) qui s'échappe jusqu'à l'appelant : la CLI
    l'afficherait en trace avec le code 1.

    Renvoie `(None, erreur)` ou `(resultat, None)`.
    """
    try:
        return appel(), None
    except erreurs_acceptees as e:
        return None, e
    except BaseException as e:  # noqa: BLE001 — c'est précisément ce qu'on traque
        raise AssertionError(
            f"{quoi} : exception non prévue par le contrat — {type(e).__name__}: {e}. "
            "Une entrée hostile doit donner une erreur utilisateur ou un résultat cohérent."
        ) from e


# --- géographie -------------------------------------------------------------

RAYON_TERRE_KM = 6371.0


def distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Haversine, avec le rayon terrestre de `RAYON_TERRE_KM`."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = phi2 - phi1
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * RAYON_TERRE_KM * math.asin(min(1.0, math.sqrt(a)))


def azimut_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dlambda = math.radians(lon2 - lon1)
    y = math.sin(dlambda) * math.cos(phi2)
    x = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(dlambda)
    return math.degrees(math.atan2(y, x)) % 360.0


# --- dataclasses dont le contrat ne fixe pas l'ordre ------------------------


def sans_accents(texte: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texte) if unicodedata.category(c) != "Mn")


def noms_champs(cls: type) -> set[str]:
    assert dataclasses.is_dataclass(cls), f"{cls.__name__} : dataclasse attendue (contrat)"
    return {f.name for f in dataclasses.fields(cls)}


def exiger_champs(cls: type, attendus: set[str]) -> None:
    manquants = attendus - noms_champs(cls)
    assert not manquants, f"{cls.__name__} : champs du contrat absents : {sorted(manquants)}"


def fabriquer(cls: type, valeurs: dict[str, Any]):
    """Instancie `cls` avec les seules clés de `valeurs` qui sont des champs."""
    connus = noms_champs(cls)
    inconnues = set(valeurs) - connus
    assert not inconnues, f"{cls.__name__} : champs inconnus de l'implémentation : {sorted(inconnues)}"
    return cls(**{k: v for k, v in valeurs.items() if k in connus})


def champ(objet: Any, jeton: str) -> Any:
    """Lit l'attribut dont le nom contient `jeton` (sans accents, insensible à la casse).

    Le contrat nomme les contenus de `RapportSynchro` en français (« vues,
    ajoutées, ignorées, échecs ») sans donner les identifiants exacts.
    """
    cible = sans_accents(jeton).casefold()
    candidats = [n for n in dir(objet) if not n.startswith("_") and cible in sans_accents(n).casefold()]
    assert candidats, (
        f"{type(objet).__name__} : aucun attribut évoquant « {jeton} » (attributs : {dir(objet)})"
    )
    assert len(candidats) == 1, f"{type(objet).__name__} : « {jeton} » ambigu, candidats {candidats}"
    return getattr(objet, candidats[0])


def trouver_cle(objet: Any, jeton: str) -> list[Any]:
    """Toutes les valeurs des clés dont le nom contient `jeton`, en profondeur."""
    cible = sans_accents(jeton).casefold()
    trouvees: list[Any] = []

    def _descendre(noeud: Any) -> None:
        if isinstance(noeud, dict):
            for cle, valeur in noeud.items():
                if isinstance(cle, str) and cible in sans_accents(cle).casefold():
                    trouvees.append(valeur)
                _descendre(valeur)
        elif isinstance(noeud, (list, tuple)):
            for element in noeud:
                _descendre(element)

    _descendre(objet)
    return trouvees
