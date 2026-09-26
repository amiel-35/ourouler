"""Fabriques d'entrées hostiles pour la séance, le terrain, le placement et la tenue.

Trois familles :

* **documents Intervals** (`groupe`, `etape_doc`, `doc`) : le format réel
  observé le 13/09 — `doc["steps"]` est une liste de groupes `{reps, steps}`
  et chaque sous-étape porte `duration` plus `power` ou `hr`. Les fabriques
  permettent d'imbriquer, de mettre `reps` à zéro, d'omettre la puissance.
* **géométries contrôlées** (`droite`, `trace_taguee`) : un tracé dont on
  connaît la pente tronçon par tronçon, les tags OSM et les `node_tags`, pour
  que « une descente de 1,2 km » ou « trois feux dans le bloc » soient des
  faits de la fixture et non des hasards.
* **objets du contrat** (`etape`, `seance`, `meteo_fictive`) construits par
  introspection : le contrat donne les champs, pas leur ordre.

Aucune coordonnée réelle : tout part de `fabriques.LAT0/LON0`, en pleine mer.
Aucun réseau : rien ici n'ouvre de socket.
"""

from __future__ import annotations

import dataclasses
import importlib
import math
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from typing import Any

import fabriques
import pytest
from outils import fabriquer

from ourouler.noyau.trace import PointTrace, Segment, Trace

#: Jour de référence des séances fabriquées. Une date quelconque : aucune
#: sortie réelle du mainteneur n'est rejouée ici.
JOUR = date(2026, 6, 10)
DEPART = datetime(2026, 6, 10, 9, 0, tzinfo=UTC)

#: FTP de test. Ce n'est pas celui du mainteneur (règle absolue 1).
FTP_TEST_W = 200.0

#: Les modules de séance vivent sous `seance/`, certains sous `sortie/` : on
#: cherche dans les deux plutôt que de faire sauter toute la suite
#: sur un désaccord de nom qui ne change aucun comportement.
PAQUETS = ("ourouler.seance", "ourouler.sortie")


def module(nom: str, *, motif: str) -> Any:
    """`ourouler.seance.<nom>`, ou `ourouler.sortie.<nom>`, ou skip.

    Le saut n'est toléré que si le **paquet lui-même** est absent — c'est le
    seul cas prévu, celui d'un lot pas encore écrit. Tout autre `ImportError`
    remonte : un symbole renommé dans `boucle.couts` et importé par
    `seance/terrain.py` transformerait sinon une suite adversariale entière en
    « skipped » vert, ce qui se lit comme « rien à signaler ».
    """
    for paquet in PAQUETS:
        try:
            return importlib.import_module(f"{paquet}.{nom}")
        except ModuleNotFoundError as e:
            if e.name is not None and not (
                e.name == paquet or e.name == f"{paquet}.{nom}"
            ):
                raise  # le paquet est là, c'est un de ses imports qui manque
            continue
    # Tous les lots du contrat existent désormais : un module introuvable est
    # une régression (renommage, suppression), plus jamais un lot à venir.
    # Un saut rendait ici des suites entières silencieusement vertes.
    pytest.fail(motif)


# --- documents Intervals ----------------------------------------------------


def etape_doc(
    duree: Any = 300.0,
    *,
    watts: Any = None,
    ftp_pct: Any = None,
    rampe: tuple[Any, Any] | None = None,
    zone_fc: Any = None,
    units: str | None = None,
    warmup: bool = False,
    cooldown: bool = False,
    intensity: str | None = None,
    text: str = "",
    **extra: Any,
) -> dict:
    """Une sous-étape au format observé. Tout est optionnel : c'est le sujet du test."""
    etape: dict[str, Any] = {"duration": duree, "text": text}
    if watts is not None:
        etape["power"] = {"units": units or "watts", "value": watts}
    elif ftp_pct is not None:
        etape["power"] = {"units": units or "%ftp", "value": ftp_pct}
    elif rampe is not None:
        etape["power"] = {"units": units or "%ftp", "start": rampe[0], "end": rampe[1]}
    elif units is not None:
        etape["power"] = {"units": units, "value": 1.0}
    if zone_fc is not None:
        etape["hr"] = {"units": "hr_zone", "value": zone_fc}
    if warmup:
        etape["warmup"] = True
    if cooldown:
        etape["cooldown"] = True
    if intensity is not None:
        etape["intensity"] = intensity
    etape.update(extra)
    return etape


def groupe(sous_etapes: Sequence[Any], *, reps: Any = 1, text: str = "", **extra: Any) -> dict:
    g: dict[str, Any] = {"reps": reps, "text": text, "steps": list(sous_etapes)}
    g.update(extra)
    return g


def doc(groupes: Sequence[Any], **extra: Any) -> dict:
    d: dict[str, Any] = {"steps": list(groupes)}
    d.update(extra)
    return d


def doc_4x8() -> dict:
    """« Vélo HIT — 4x8min Z4 » : la séance de référence, en miniature."""
    return doc(
        [
            groupe([etape_doc(900.0, ftp_pct=0.60, warmup=True, intensity="warmup")]),
            groupe(
                [
                    etape_doc(480.0, ftp_pct=1.05, text="bloc"),
                    etape_doc(240.0, ftp_pct=0.50, intensity="recovery", text="recup"),
                ],
                reps=4,
            ),
            groupe([etape_doc(600.0, ftp_pct=0.55, cooldown=True, intensity="cooldown")]),
        ]
    )


#: Zones de puissance en pourcentage de FTP, forme attendue par le contrat
#: (« ex. Z4 = 105-120 % »). Valeurs de test, pas celles d'un athlète réel.
ZONES_PUISSANCE = {
    1: (0.0, 0.55),
    2: (0.56, 0.75),
    3: (0.76, 0.90),
    4: (0.91, 1.05),
    5: (1.06, 1.20),
    6: (1.21, 1.50),
    7: (1.51, 3.00),
}


def appeler_depuis_workout(mod: Any, document: Any, **surcharges: Any) -> Any:
    """`depuis_workout_doc` avec les arguments par défaut des tests."""
    arguments: dict[str, Any] = {
        "nom": "seance de test",
        "jour": JOUR,
        "ftp_w": FTP_TEST_W,
        "zones_puissance": ZONES_PUISSANCE,
    }
    arguments.update(surcharges)
    return mod.depuis_workout_doc(document, **arguments)


# --- séances construites à la main ------------------------------------------


def etape(
    mod: Any,
    type_: str,
    duree_s: float,
    *,
    pmin: float | None = None,
    pmax: float | None = None,
    libelle: str = "",
    elastique: bool = False,
) -> Any:
    return fabriquer(
        mod.Etape,
        {
            "type": type_,
            "duree_s": duree_s,
            "puissance_min_w": pmin,
            "puissance_max_w": pmax,
            "libelle": libelle,
            "elastique": elastique,
        },
    )


def seance(mod: Any, etapes: Sequence[Any], *, nom: str = "seance de test", meta: dict | None = None) -> Any:
    return fabriquer(
        mod.Seance,
        {
            "nom": nom,
            "jour": JOUR,
            "etapes": list(etapes),
            "duree_s": sum(float(e.duree_s) for e in etapes),
            "meta": dict(meta or {}),
        },
    )


def seance_deux_blocs(
    mod: Any,
    *,
    echauffement_s: float = 1200.0,
    bloc_s: float = 600.0,
    recup_s: float = 240.0,
    calme_s: float = 600.0,
    puissance_bloc_w: float = 210.0,
    puissance_z2_w: float = 140.0,
) -> Any:
    """Échauffement Z2 élastique, deux blocs séparés d'une récup, calme élastique."""
    return seance(
        mod,
        [
            etape(
                mod, "echauffement", echauffement_s,
                pmin=puissance_z2_w, pmax=puissance_z2_w, elastique=True,
            ),
            etape(mod, "bloc", bloc_s, pmin=puissance_bloc_w, pmax=puissance_bloc_w, libelle="bloc 1"),
            etape(mod, "recuperation", recup_s, pmin=puissance_z2_w, pmax=puissance_z2_w, libelle="recup"),
            etape(mod, "bloc", bloc_s, pmin=puissance_bloc_w, pmax=puissance_bloc_w, libelle="bloc 2"),
            etape(mod, "calme", calme_s, pmin=puissance_z2_w, pmax=puissance_z2_w, elastique=True),
        ],
    )


def durees_par_type(seance_: Any, type_: str) -> list[float]:
    return [float(e.duree_s) for e in seance_.etapes if e.type == type_]


# --- géométries contrôlées ---------------------------------------------------

PAS_M = 100.0


def droite(
    n_troncons: int,
    *,
    pas_m: float = PAS_M,
    cap_deg: float = 90.0,
    pentes: Sequence[float] | float = 0.0,
    alt0: float | None = 50.0,
    depart: tuple[float, float] = (fabriques.LAT0, fabriques.LON0),
) -> list[tuple[float, float, float | None]]:
    """`n_troncons + 1` points alignés, d'altitude dictée par les pentes.

    `pentes` vaut un nombre (pente constante) ou une valeur par tronçon.
    `alt0=None` fabrique un tracé sans altitude du tout.
    """
    if not isinstance(pentes, Sequence):
        pentes = [float(pentes)] * n_troncons
    assert len(pentes) == n_troncons, "une pente par tronçon attendue"
    lat, lon = depart
    alt = alt0
    coords: list[tuple[float, float, float | None]] = [(lat, lon, alt)]
    for pente in pentes:
        lat, lon = fabriques.deplacer(lat, lon, cap_deg, pas_m)
        if alt is not None:
            alt = alt + pente * pas_m
        coords.append((lat, lon, alt))
    return coords


def virage(
    n_avant: int,
    n_apres: int,
    *,
    angle_deg: float,
    pas_m: float = PAS_M,
    cap_deg: float = 90.0,
    alt: float | None = 50.0,
) -> list[tuple[float, float, float | None]]:
    """Deux droites plates se rejoignant sur un virage unique de `angle_deg`."""
    avant = droite(n_avant, pas_m=pas_m, cap_deg=cap_deg, alt0=alt)
    lat, lon, _ = avant[-1]
    apres = droite(n_apres, pas_m=pas_m, cap_deg=cap_deg + angle_deg, alt0=alt, depart=(lat, lon))
    return avant + apres[1:]


CHAMPS_SEGMENT = {f.name for f in dataclasses.fields(Segment)}


def segments_disponibles_avec_node_tags() -> bool:
    """`Segment.node_tags` est un prérequis du lot L4.2, absent avant lui."""
    return "node_tags" in CHAMPS_SEGMENT


def trace_taguee(
    coords: Sequence[tuple[float, float, float | None]],
    *,
    tags: dict[str, str] | Sequence[dict[str, str]] | None = None,
    node_tags: dict[int, dict[str, str]] | None = None,
    nom: str = "trace de test",
    sans_segments: bool = False,
) -> Trace:
    """Une `Trace` dont chaque tronçon porte ses tags OSM et ses `node_tags`.

    `tags` : un jeu unique répété, ou un jeu par tronçon.
    `node_tags` : `{indice de tronçon: tags du nœud}`. Ignoré (avec un skip
    explicite du test appelant) tant que `Segment.node_tags` n'existe pas.
    """
    points = fabriques.points_trace(coords)
    n = max(len(points) - 1, 0)
    if isinstance(tags, dict) or tags is None:
        jeux = [dict(tags or {"highway": "tertiary"}) for _ in range(n)]
    else:
        assert len(tags) == n, "un jeu de tags par tronçon attendu"
        jeux = [dict(t) for t in tags]
    segments: list[Segment] = []
    if not sans_segments:
        for i, jeu in enumerate(jeux):
            valeurs: dict[str, Any] = {
                "debut_idx": i,
                "fin_idx": i + 1,
                "longueur_m": points[i + 1].dist_m - points[i].dist_m,
                "tags": jeu,
            }
            if node_tags and "node_tags" in CHAMPS_SEGMENT:
                valeurs["node_tags"] = dict(node_tags.get(i, {}))
            segments.append(Segment(**valeurs))
    altitudes = [p.alt_m for p in points if p.alt_m is not None]
    denivele = None
    if len(altitudes) == len(points) and altitudes:
        denivele = sum(max(0.0, b - a) for a, b in zip(altitudes, altitudes[1:], strict=False))
    return Trace(
        nom=nom,
        points=points,
        segments=segments,
        distance_m=points[-1].dist_m if points else 0.0,
        denivele_m=denivele,
        temps_moteur_s=None,
        meta={},
    )


def boucle_plate(
    *,
    rayon_m: float = 4000.0,
    n: int = 240,
    tags: dict[str, str] | None = None,
    node_tags: dict[int, dict[str, str]] | None = None,
    nom: str = "boucle de test",
) -> Trace:
    """Une boucle fermée, plate, sans obstacle sauf ce qu'on y met."""
    coords = fabriques.cercle(n, rayon_m=rayon_m, sens="horaire")
    return trace_taguee(coords, tags=tags, node_tags=node_tags, nom=nom)


def troncon_de(trace: Trace, debut_m: float, fin_m: float) -> list[int]:
    """Indices des tronçons dont le départ tombe dans `[debut_m, fin_m)`."""
    return [
        i
        for i in range(max(len(trace.points) - 1, 0))
        if debut_m <= trace.points[i].dist_m < fin_m
    ]


def salir(
    trace: Trace,
    zones_m: Sequence[tuple[float, float]],
    *,
    village: bool = True,
    feux: bool = True,
) -> Trace:
    """Copie du tracé avec villages et feux **uniquement** dans `zones_m`.

    La géométrie ne bouge pas d'un mètre : seules les étiquettes changent.
    Deux tracés ainsi appariés ne diffèrent donc pas par la physique, et toute
    différence de note vient bien de l'évaluation du terrain.
    """
    tags: list[dict[str, str]] = [dict(s.tags) for s in trace.segments]
    noeuds: dict[int, dict[str, str]] = {
        i: dict(getattr(s, "node_tags", {}) or {}) for i, s in enumerate(trace.segments)
    }
    for debut, fin in zones_m:
        for i in troncon_de(trace, debut, fin):
            if i >= len(tags):
                continue
            if village:
                tags[i] = {"highway": "residential", "maxspeed": "50"}
            if feux and i % 3 == 0:
                noeuds[i] = {"highway": "traffic_signals"}
    coords = [(p.lat, p.lon, p.alt_m) for p in trace.points]
    return trace_taguee(coords, tags=tags, node_tags=noeuds, nom=trace.nom + " (sali)")


# --- météo fabriquée ---------------------------------------------------------


def echantillon(
    mod_meteo: Any,
    dist_m: float,
    *,
    minute: float = 0.0,
    ressenti: float | None = 12.0,
    pluie: float | None = 0.0,
    vent: float | None = 10.0,
    vent_relatif: str | None = "de face",
) -> Any:
    return fabriquer(
        mod_meteo.Echantillon,
        {
            "dist_m": dist_m,
            "t": DEPART + timedelta(minutes=minute),
            "lat": fabriques.LAT0,
            "lon": fabriques.LON0,
            "cap_deg": 90.0,
            "pluie_mm": pluie,
            "vent_kmh": vent,
            "vent_relatif": vent_relatif,
            "ressenti_c": ressenti,
            "vent_depuis_deg": 270.0,
        },
    )


def meteo_fictive(mod_meteo: Any, echantillons: Sequence[Any], *, confiance: str = "bonne") -> Any:
    pluies = [e.pluie_mm for e in echantillons if e.pluie_mm is not None]
    ressentis = [e.ressenti_c for e in echantillons if e.ressenti_c is not None]
    return fabriquer(
        mod_meteo.MeteoTrace,
        {
            "echantillons": list(echantillons),
            "pluie_cumulee_mm": sum(pluies),
            "minutes_pluie": 60.0 * len([p for p in pluies if p >= 0.2]),
            "part_vent_face": 1.0 if echantillons else 0.0,
            "part_vent_dos": 0.0,
            "ressenti_min_c": min(ressentis) if ressentis else None,
            "confiance": confiance,
            "n_vent_connu": len([e for e in echantillons if e.vent_kmh is not None]),
        },
    )


def meteo_uniforme(
    mod_meteo: Any,
    *,
    ressenti: float | None = 12.0,
    pluie: float | None = 0.0,
    vent: float | None = 10.0,
    n: int = 6,
) -> Any:
    return meteo_fictive(
        mod_meteo,
        [
            echantillon(mod_meteo, i * 5000.0, minute=i * 12.0, ressenti=ressenti, pluie=pluie, vent=vent)
            for i in range(n)
        ],
    )


# --- vérificateurs partagés --------------------------------------------------


def nombre_fini(valeur: Any, quoi: str, *, positif: bool = False) -> float:
    assert isinstance(valeur, (int, float)) and not isinstance(valeur, bool), (
        f"{quoi} : nombre attendu, reçu {type(valeur).__name__} ({valeur!r})"
    )
    assert math.isfinite(float(valeur)), f"{quoi} : {valeur!r} n'est pas fini"
    if positif:
        assert float(valeur) >= 0.0, f"{quoi} : valeur négative ({valeur})"
    return float(valeur)


def liste_de_chaines(valeur: Any, quoi: str) -> list[str]:
    assert isinstance(valeur, list), f"{quoi} : liste attendue, reçu {type(valeur).__name__}"
    for i, element in enumerate(valeur):
        assert isinstance(element, str), f"{quoi}[{i}] : chaîne attendue, reçu {element!r}"
        assert element.strip(), f"{quoi}[{i}] : motif vide, illisible pour le mainteneur"
    return valeur


def verifier_note(note: Any, *, quoi: str) -> None:
    """Invariants de `NoteBloc`, quel que soit le barème."""
    nombre_fini(note.note, f"{quoi}.note", positif=True)
    liste_de_chaines(note.motifs, f"{quoi}.motifs")
    for nom in ("pente_moyenne", "pente_max"):
        pente = nombre_fini(getattr(note, nom), f"{quoi}.{nom}")
        assert abs(pente) <= 1.0, f"{quoi}.{nom} = {pente} : une pente se donne en fraction, pas en %"
    carrefours = note.carrefours
    assert isinstance(carrefours, int) and not isinstance(carrefours, bool), (
        f"{quoi}.carrefours : entier attendu, reçu {carrefours!r}"
    )
    assert carrefours >= 0, f"{quoi}.carrefours négatif ({carrefours})"
    for nom in ("km_batis", "descente_m", "montee_m"):
        nombre_fini(getattr(note, nom), f"{quoi}.{nom}", positif=True)


def verifier_etape(etape_: Any, types: Sequence[str], *, quoi: str) -> None:
    assert etape_.type in types, f"{quoi}.type = {etape_.type!r}, hors de TYPES {tuple(types)}"
    duree = nombre_fini(etape_.duree_s, f"{quoi}.duree_s", positif=True)
    assert duree < 24 * 3600.0, f"{quoi}.duree_s = {duree} s : plus d'une journée de vélo"
    for nom in ("puissance_min_w", "puissance_max_w", "puissance_cible_w"):
        valeur = getattr(etape_, nom)
        if valeur is not None:
            puissance = nombre_fini(valeur, f"{quoi}.{nom}", positif=True)
            assert puissance <= 5.0 * FTP_TEST_W, (
                f"{quoi}.{nom} = {puissance} W pour un FTP de {FTP_TEST_W} W : "
                "pourcentage lu comme des watts ?"
            )
    mini, maxi = etape_.puissance_min_w, etape_.puissance_max_w
    if mini is not None and maxi is not None:
        assert mini <= maxi, f"{quoi} : fourchette à l'envers ({mini} > {maxi})"
        cible = etape_.puissance_cible_w
        assert cible is not None and mini <= cible <= maxi, (
            f"{quoi}.puissance_cible_w = {cible!r} hors de [{mini}, {maxi}]"
        )
    assert isinstance(etape_.libelle, str), f"{quoi}.libelle : chaîne attendue"


def verifier_seance(seance_: Any, types: Sequence[str], *, quoi: str = "Seance") -> None:
    assert isinstance(seance_.etapes, list), f"{quoi}.etapes : liste attendue"
    for i, e in enumerate(seance_.etapes):
        verifier_etape(e, types, quoi=f"{quoi}.etapes[{i}]")
    total = sum(float(e.duree_s) for e in seance_.etapes)
    duree = nombre_fini(seance_.duree_s, f"{quoi}.duree_s", positif=True)
    assert abs(duree - total) < 1e-6, (
        f"{quoi}.duree_s = {duree} s alors que les étapes en totalisent {total} s"
    )
    assert isinstance(seance_.meta, dict), f"{quoi}.meta : dict attendu"
    assert isinstance(seance_.jour, date), f"{quoi}.jour : date attendue, reçu {seance_.jour!r}"
    # Décision du 13/09 : seules les Z2 d'ouverture et de fermeture sont
    # élastiques. Une récupération élastique trahirait la prescription.
    elastiques = [i for i, e in enumerate(seance_.etapes) if e.elastique]
    for i in elastiques:
        e = seance_.etapes[i]
        assert e.type in ("echauffement", "calme"), (
            f"{quoi}.etapes[{i}] de type {e.type!r} marquée élastique : "
            "seules les Z2 d'ouverture et de fermeture le sont (plan, sprint 4)"
        )
        assert i in (0, len(seance_.etapes) - 1), (
            f"{quoi}.etapes[{i}] élastique au milieu de la séance : "
            "seules la première et la dernière étape peuvent l'être"
        )
    for i, (indice, bloc) in enumerate(seance_.blocs()):
        assert 0 <= indice < len(seance_.etapes), f"{quoi}.blocs()[{i}] : indice {indice} hors bornes"
        assert seance_.etapes[indice] is bloc, f"{quoi}.blocs()[{i}] : l'indice ne désigne pas l'étape"
        assert bloc.type == "bloc", f"{quoi}.blocs()[{i}] : étape de type {bloc.type!r}"


def instantane_seance(seance_: Any) -> list[tuple[Any, ...]]:
    """Instantané comparable : `placer` ne doit toucher à aucune étape."""
    return [
        (e.type, float(e.duree_s), e.puissance_min_w, e.puissance_max_w, e.libelle, e.elastique)
        for e in seance_.etapes
    ]


def instantane_trace(trace: Trace) -> list[tuple[float, float, float | None, float]]:
    return [(p.lat, p.lon, p.alt_m, p.dist_m) for p in trace.points]


def points_de(trace: Trace) -> list[PointTrace]:
    return list(trace.points)
