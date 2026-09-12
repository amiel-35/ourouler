#!/usr/bin/env python3
"""Génère les fichiers d'activité de test dans `tests/fixtures/activites/`.

Aucune trace réelle : tout est synthétique, autour du point fictif
(0.0, 0.0) — en pleine mer, dans le golfe de Guinée, à plus de 500 km de
toute côte et de toute ville. Aucune donnée personnelle, aucune clé.

Usage : `uv run python tests/fixtures/generer_activites.py`
Le script est idempotent : il réécrit les mêmes octets à chaque exécution.

Pourquoi un encodeur FIT écrit à la main ? `fitdecode` sait lire un FIT,
pas en écrire un, et aucune dépendance du projet ne le fait. On encode donc
ici le strict minimum du format : en-tête 14 octets, messages de définition
et de données pour `file_id`, `record` et `session`, puis le CRC final.
C'est ~120 lignes et ça reste lisible ; l'alternative (ajouter une
dépendance d'écriture FIT pour les seuls tests) coûtait plus cher.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

# --- point de départ fictif ---------------------------------------------------

LAT_FICTIVE = 0.0
LON_FICTIVE = 0.0
DEBUT = datetime(2024, 3, 30, 9, 0, 0, tzinfo=UTC)

DOSSIER_DEFAUT = Path(__file__).resolve().parent / "activites"


# --- trajectoire synthétique --------------------------------------------------


@dataclass
class Echantillon:
    t: datetime
    lat: float | None
    lon: float | None
    alt_m: float | None
    dist_m: float
    vitesse_ms: float
    puissance_w: int | None
    cadence_rpm: int | None
    fc_bpm: int | None
    temp_c: int | None


def trajectoire(
    n: int = 340,
    *,
    pas_s: int = 2,
    debut: datetime = DEBUT,
    avec_gps: bool = True,
    avec_altitude: bool = True,
    avec_puissance: bool = True,
) -> list[Echantillon]:
    """Boucle circulaire de rayon ~1 km autour du point fictif, à ~28 km/h."""
    rayon_deg = 0.009  # ~1 km
    vitesse = 7.8  # m/s
    echantillons: list[Echantillon] = []
    for i in range(n):
        angle = 2 * math.pi * i / n
        dist = vitesse * i * pas_s
        # Puissance : plateau à 200 W avec une bosse et une descente franches.
        puissance = 200 + 60 * math.sin(4 * math.pi * i / n) + (40 if 200 <= i < 260 else 0)
        echantillons.append(
            Echantillon(
                t=debut + timedelta(seconds=i * pas_s),
                lat=LAT_FICTIVE + rayon_deg * math.sin(angle) if avec_gps else None,
                lon=LON_FICTIVE + rayon_deg * math.cos(angle) if avec_gps else None,
                alt_m=round(20 + 30 * math.sin(2 * math.pi * i / n), 1) if avec_altitude else None,
                dist_m=round(dist, 2),
                vitesse_ms=vitesse,
                puissance_w=int(puissance) if avec_puissance else None,
                cadence_rpm=85 if avec_puissance else None,
                fc_bpm=130 + int(10 * math.sin(6 * math.pi * i / n)),
                temp_c=14,
            )
        )
    return echantillons


# --- encodeur FIT minimal -----------------------------------------------------

EPOQUE_FIT = datetime(1989, 12, 31, tzinfo=UTC)

# (code du type de base FIT, taille en octets, valeur « invalide »)
TYPES_FIT = {
    "enum": (0x00, 1, 0xFF),
    "uint8": (0x02, 1, 0xFF),
    "sint8": (0x01, 1, 0x7F),
    "uint16": (0x84, 2, 0xFFFF),
    "sint16": (0x83, 2, 0x7FFF),
    "uint32": (0x86, 4, 0xFFFFFFFF),
    "sint32": (0x85, 4, 0x7FFFFFFF),
    "uint32z": (0x8C, 4, 0),
}

TABLE_CRC = (
    0x0000, 0xCC01, 0xD801, 0x1400, 0xF001, 0x3C00, 0x2800, 0xE401,
    0xA001, 0x6C00, 0x7800, 0xB401, 0x5000, 0x9C01, 0x8801, 0x4400,
)  # fmt: skip


def crc_fit(octets: bytes, crc: int = 0) -> int:
    """CRC-16 du format FIT (deux quartets par octet, table officielle)."""
    for octet in octets:
        for _ in range(2):
            tmp = TABLE_CRC[crc & 0xF]
            crc = (crc >> 4) & 0x0FFF
            crc = crc ^ tmp ^ TABLE_CRC[octet & 0xF]
            octet >>= 4
    return crc


def _horodatage_fit(t: datetime) -> int:
    return int((t - EPOQUE_FIT).total_seconds())


def _semicercles(degres: float) -> int:
    return int(round(degres * (2**31 / 180.0)))


def _valeur(valeur: float | None, type_nom: str) -> bytes:
    code, taille, invalide = TYPES_FIT[type_nom]
    brut = invalide if valeur is None else int(valeur)
    return brut.to_bytes(taille, "little", signed=type_nom.startswith("sint"))


def message_definition(local: int, global_num: int, champs: list[tuple[int, str]]) -> bytes:
    d = bytearray()
    d.append(0x40 | local)  # en-tête : message de définition
    d.append(0)  # réservé
    d.append(0)  # architecture : petit-boutiste
    d += global_num.to_bytes(2, "little")
    d.append(len(champs))
    for numero, type_nom in champs:
        code, taille, _ = TYPES_FIT[type_nom]
        d += bytes((numero, taille, code))
    return bytes(d)


def message_donnees(local: int, champs: list[tuple[int, str]], valeurs: list[float | None]) -> bytes:
    d = bytearray()
    d.append(local)  # en-tête : message de données
    for (_, type_nom), valeur in zip(champs, valeurs, strict=True):
        d += _valeur(valeur, type_nom)
    return bytes(d)


def fichier_fit(corps: bytes) -> bytes:
    """Assemble en-tête (14 octets, CRC inclus) + corps + CRC final."""
    entete = bytearray()
    entete.append(14)
    entete.append(0x20)  # version du protocole 2.0
    entete += (2143).to_bytes(2, "little")  # version du profil
    entete += len(corps).to_bytes(4, "little")
    entete += b".FIT"
    entete += crc_fit(bytes(entete)).to_bytes(2, "little")
    fichier = bytes(entete) + corps
    return fichier + crc_fit(fichier).to_bytes(2, "little")


CHAMPS_FILE_ID = [(0, "enum"), (1, "uint16"), (2, "uint16"), (4, "uint32")]
CHAMPS_SESSION = [
    (253, "uint32"),  # timestamp
    (2, "uint32"),  # start_time
    (5, "enum"),  # sport (2 = cycling)
    (6, "enum"),  # sub_sport (6 = indoor_cycling, 0 = generic)
    (7, "uint32"),  # total_elapsed_time (ms)
    (8, "uint32"),  # total_timer_time (ms)
    (9, "uint32"),  # total_distance (cm)
    (20, "uint16"),  # avg_power
]


def _champs_record(*, gps: bool, altitude: bool, puissance: bool) -> list[tuple[int, str]]:
    champs: list[tuple[int, str]] = [(253, "uint32")]
    if gps:
        champs += [(0, "sint32"), (1, "sint32")]
    if altitude:
        champs.append((2, "uint16"))
    champs += [(3, "uint8"), (4, "uint8"), (5, "uint32"), (6, "uint16")]
    if puissance:
        champs.append((7, "uint16"))
    champs.append((13, "sint8"))
    return champs


def encoder_fit(echantillons: list[Echantillon], *, sport: int = 2, sous_sport: int = 0) -> bytes:
    """Un FIT à une seule session — le cas courant."""
    return encoder_fit_multisession([echantillons], sport=sport, sous_sport=sous_sport)


def encoder_fit_multisession(
    troncons: list[list[Echantillon]], *, sport: int = 2, sous_sport: int = 0
) -> bytes:
    """Un FIT portant **une trame `session` par tronçon**.

    C'est ce qu'écrit un appareil quand la sortie est coupée en deux (pause
    longue, changement d'activité) ou pour un fichier multisport. Les
    `record` sont écrits d'affilée, avec leur distance cumulée depuis le tout
    début ; chaque `session` porte la distance et la durée **de son
    tronçon**, si bien que le total est la somme des sessions — et pas la
    valeur de la dernière.
    """
    assert troncons and all(troncons), "chaque tronçon doit porter au moins un échantillon"
    tous = [e for troncon in troncons for e in troncon]
    gps = tous[0].lat is not None
    altitude = tous[0].alt_m is not None
    puissance = tous[0].puissance_w is not None
    champs_record = _champs_record(gps=gps, altitude=altitude, puissance=puissance)

    corps = bytearray()
    corps += message_definition(0, 0, CHAMPS_FILE_ID)
    corps += message_donnees(
        0,
        CHAMPS_FILE_ID,
        [4, 255, 0, _horodatage_fit(tous[0].t)],  # type=activity, fabricant=development
    )
    corps += message_definition(1, 20, champs_record)
    for e in tous:
        valeurs: list[float | None] = [_horodatage_fit(e.t)]
        if gps:
            valeurs += [_semicercles(e.lat), _semicercles(e.lon)]
        if altitude:
            valeurs.append(round((e.alt_m + 500) * 5))  # échelle 5, décalage 500
        valeurs += [e.fc_bpm, e.cadence_rpm, round(e.dist_m * 100), round(e.vitesse_ms * 1000)]
        if puissance:
            valeurs.append(e.puissance_w)
        valeurs.append(e.temp_c)
        corps += message_donnees(1, champs_record, valeurs)

    corps += message_definition(2, 18, CHAMPS_SESSION)
    for troncon in troncons:
        corps += _donnees_session(troncon, sport=sport, sous_sport=sous_sport)
    return fichier_fit(bytes(corps))


def _donnees_session(
    echantillons: list[Echantillon], *, sport: int, sous_sport: int
) -> bytes:
    """La trame `session` d'un tronçon : sa durée et sa distance, pas celles du fichier."""
    premier, dernier = echantillons[0], echantillons[-1]
    ecoule = (dernier.t - premier.t).total_seconds()
    distance = dernier.dist_m - premier.dist_m
    puissances = [e.puissance_w for e in echantillons if e.puissance_w is not None]
    return message_donnees(
        2,
        CHAMPS_SESSION,
        [
            _horodatage_fit(dernier.t),
            _horodatage_fit(premier.t),
            sport,
            sous_sport,
            round(ecoule * 1000),
            max(round(ecoule * 1000) - 30_000, 0),  # temps de mouvement : 30 s d'arrêt
            round(distance * 100),
            round(sum(puissances) / len(puissances)) if puissances else None,
        ],
    )


# --- GPX ----------------------------------------------------------------------

ENTETE_GPX = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<gpx version="1.1" creator="ourouler-generateur-de-fixtures" '
    'xmlns="http://www.topografix.com/GPX/1/1" '
    'xmlns:gpxtpx="http://www.garmin.com/xmlschemas/TrackPointExtension/v1" '
    'xmlns:gpxpx="http://www.garmin.com/xmlschemas/PowerExtension/v1">\n'
)


def encoder_gpx(echantillons: list[Echantillon], *, type_trace: str = "cycling") -> str:
    lignes = [ENTETE_GPX, "  <trk>\n", "    <name>Boucle synthetique</name>\n"]
    lignes.append(f"    <type>{type_trace}</type>\n")
    lignes.append("    <trkseg>\n")
    for e in echantillons:
        lat = 0.0 if e.lat is None else e.lat
        lon = 0.0 if e.lon is None else e.lon
        lignes.append(f'      <trkpt lat="{lat:.6f}" lon="{lon:.6f}">\n')
        if e.alt_m is not None:
            lignes.append(f"        <ele>{e.alt_m:.1f}</ele>\n")
        lignes.append(f"        <time>{e.t.strftime('%Y-%m-%dT%H:%M:%SZ')}</time>\n")
        lignes.append("        <extensions>\n")
        if e.puissance_w is not None:
            lignes.append(f"          <gpxpx:PowerInWatts>{e.puissance_w}</gpxpx:PowerInWatts>\n")
        lignes.append("          <gpxtpx:TrackPointExtension>\n")
        if e.fc_bpm is not None:
            lignes.append(f"            <gpxtpx:hr>{e.fc_bpm}</gpxtpx:hr>\n")
        if e.cadence_rpm is not None:
            lignes.append(f"            <gpxtpx:cad>{e.cadence_rpm}</gpxtpx:cad>\n")
        if e.temp_c is not None:
            lignes.append(f"            <gpxtpx:atemp>{e.temp_c}</gpxtpx:atemp>\n")
        lignes.append("          </gpxtpx:TrackPointExtension>\n")
        lignes.append("        </extensions>\n")
        lignes.append("      </trkpt>\n")
    lignes += ["    </trkseg>\n", "  </trk>\n", "</gpx>\n"]
    return "".join(lignes)


# --- TCX ----------------------------------------------------------------------

ENTETE_TCX = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<TrainingCenterDatabase xmlns="http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2" '
    'xmlns:ns3="http://www.garmin.com/xmlschemas/ActivityExtension/v2">\n'
)


def encoder_tcx(echantillons: list[Echantillon], *, sport: str = "Biking") -> str:
    premier, dernier = echantillons[0], echantillons[-1]
    ecoule = (dernier.t - premier.t).total_seconds()
    puissances = [e.puissance_w for e in echantillons if e.puissance_w is not None]
    lignes = [
        ENTETE_TCX,
        "  <Activities>\n",
        f'    <Activity Sport="{sport}">\n',
        f"      <Id>{premier.t.strftime('%Y-%m-%dT%H:%M:%SZ')}</Id>\n",
        f'      <Lap StartTime="{premier.t.strftime("%Y-%m-%dT%H:%M:%SZ")}">\n',
        f"        <TotalTimeSeconds>{ecoule:.1f}</TotalTimeSeconds>\n",
        f"        <DistanceMeters>{dernier.dist_m:.1f}</DistanceMeters>\n",
        "        <Intensity>Active</Intensity>\n",
        "        <TriggerMethod>Manual</TriggerMethod>\n",
        "        <Track>\n",
    ]
    for e in echantillons:
        lignes.append("          <Trackpoint>\n")
        lignes.append(f"            <Time>{e.t.strftime('%Y-%m-%dT%H:%M:%SZ')}</Time>\n")
        if e.lat is not None and e.lon is not None:
            lignes.append("            <Position>\n")
            lignes.append(f"              <LatitudeDegrees>{e.lat:.6f}</LatitudeDegrees>\n")
            lignes.append(f"              <LongitudeDegrees>{e.lon:.6f}</LongitudeDegrees>\n")
            lignes.append("            </Position>\n")
        if e.alt_m is not None:
            lignes.append(f"            <AltitudeMeters>{e.alt_m:.1f}</AltitudeMeters>\n")
        lignes.append(f"            <DistanceMeters>{e.dist_m:.1f}</DistanceMeters>\n")
        if e.fc_bpm is not None:
            lignes.append(f"            <HeartRateBpm><Value>{e.fc_bpm}</Value></HeartRateBpm>\n")
        if e.cadence_rpm is not None:
            lignes.append(f"            <Cadence>{e.cadence_rpm}</Cadence>\n")
        lignes.append("            <Extensions>\n")
        lignes.append("              <ns3:TPX>\n")
        lignes.append(f"                <ns3:Speed>{e.vitesse_ms:.3f}</ns3:Speed>\n")
        if e.puissance_w is not None:
            lignes.append(f"                <ns3:Watts>{e.puissance_w}</ns3:Watts>\n")
        lignes.append("              </ns3:TPX>\n")
        lignes.append("            </Extensions>\n")
        lignes.append("          </Trackpoint>\n")
    lignes.append("        </Track>\n")
    lignes.append("        <Extensions>\n")
    lignes.append("          <ns3:LX>\n")
    if puissances:
        moyenne = round(sum(puissances) / len(puissances))
        lignes.append(f"            <ns3:AvgWatts>{moyenne}</ns3:AvgWatts>\n")
    lignes.append("          </ns3:LX>\n")
    lignes.append("        </Extensions>\n")
    lignes.append("      </Lap>\n")
    lignes.append("      <Creator xsi:type=\"Device_t\" "
                  'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">\n')
    lignes.append("        <Name>Appareil de test</Name>\n")
    lignes.append("      </Creator>\n")
    lignes.append("    </Activity>\n")
    lignes.append("  </Activities>\n")
    lignes.append("</TrainingCenterDatabase>\n")
    return "".join(lignes)


# --- génération ---------------------------------------------------------------


def generer(dossier: Path = DOSSIER_DEFAUT) -> dict[str, Path]:
    """Écrit toutes les fixtures et renvoie {nom de fichier: chemin}."""
    dossier.mkdir(parents=True, exist_ok=True)
    complete = trajectoire()
    sans_gps = trajectoire(n=300, avec_gps=False, avec_altitude=False)
    sans_puissance = trajectoire(n=300, avec_puissance=False)
    courte = trajectoire(n=120, debut=datetime(2024, 4, 2, 8, 0, tzinfo=UTC))

    fichiers: dict[str, bytes] = {
        # --- cas nominaux, un par format ---
        "boucle.fit": encoder_fit(complete),
        "boucle.gpx": encoder_gpx(complete).encode("utf-8"),
        "boucle.tcx": encoder_tcx(complete).encode("utf-8"),
        # --- variantes valides ---
        # sous-sport 6 = indoor_cycling : la seule chose qui, dans un FIT,
        # distingue un home-trainer d'une sortie.
        "home_trainer.fit": encoder_fit(sans_gps, sport=2, sous_sport=6),
        "sans_puissance.gpx": encoder_gpx(sans_puissance).encode("utf-8"),
        "sans_altitude.gpx": encoder_gpx(
            trajectoire(n=200, avec_altitude=False)
        ).encode("utf-8"),
        "COURTE.GPX": encoder_gpx(courte).encode("utf-8"),  # extension en majuscules
        # --- cas dégradés ---
        "vide.fit": b"",
        "vide.gpx": b"",
        "vide.tcx": b"",
        "tronque.fit": encoder_fit(complete)[:60],
        "tronque.gpx": encoder_gpx(complete).encode("utf-8")[:400],
        "tronque.tcx": encoder_tcx(complete).encode("utf-8")[:400],
        "inconnu.dat": b"ni FIT ni GPX ni TCX\n",
    }
    # Horodatages non monotones : on permute deux points au milieu de la trace.
    desordre = trajectoire(n=200)
    desordre[100], desordre[120] = desordre[120], desordre[100]
    fichiers["non_monotone.gpx"] = encoder_gpx(desordre).encode("utf-8")

    ecrits: dict[str, Path] = {}
    for nom, contenu in fichiers.items():
        chemin = dossier / nom
        chemin.write_bytes(contenu)
        ecrits[nom] = chemin
    return ecrits


# Sous-ensemble de fixtures valides, importable par un dossier de cache.
VALIDES = ("boucle.fit", "boucle.gpx", "boucle.tcx", "home_trainer.fit",
           "sans_puissance.gpx", "sans_altitude.gpx", "COURTE.GPX")  # fmt: skip


if __name__ == "__main__":  # pragma: no cover
    for nom, chemin in generer().items():
        print(f"{nom:24} {chemin.stat().st_size:>8} octets")
