"""Générateur des fichiers d'activité hostiles des tests adversariaux.

Aucune donnée réelle : toutes les trajectoires tournent autour du point
fictif (0.0, 0.0) — en mer, au large du golfe de Guinée — ou d'un point
manifestement inventé au milieu du Pacifique (0.0, 179.9). Aucun nom, aucune
clé, aucun identifiant appartenant au mainteneur.

Les fichiers ne sont **pas** versionnés en binaire : `.gitignore` ignore tout
`*.fit`/`*.gpx`/`*.tcx` et ne réintègre nommément que les quelques fixtures de
`tests/fixtures/activites/`, jamais ce dossier-ci. C'est donc ce
script qui est versionné, et les tests le déroulent dans un `tmp_path` de
session (voir `tests/adversarial/conftest.py`). Avantage secondaire : pas de
fixture binaire qui se périme en silence.

Utilisable aussi à la main, pour inspecter les fichiers :

    uv run python tests/adversarial/fixtures/generer_hostiles.py /tmp/hostiles

Catalogue (clé -> nom de fichier) : voir `CATALOGUE` en fin de module.

Encodage FIT
------------
Le FIT est écrit ici à la main (fitdecode ne sait que lire) :

* en-tête 14 octets : taille, version de protocole, version de profil,
  `data_size` (uint32 LE), `".FIT"`, CRC des 12 premiers octets ;
* messages de définition (`0x40 | type local`) puis de données ;
* CRC final (2 octets LE) sur tout ce qui précède.

Un test garde-fou (`test_adv_lecture.py::test_le_fit_nominal_est_bien_un_fit`)
vérifie que `fitdecode` relit le FIT nominal : si l'encodeur de ce script est
faux, c'est ce test-là qui tombe, pas ceux du lecteur L1.2.
"""

from __future__ import annotations

import datetime as dt
import struct
import sys
from pathlib import Path

# --- CRC FIT ----------------------------------------------------------------

_TABLE_CRC = (
    0x0000,
    0xCC01,
    0xD801,
    0x1400,
    0xF001,
    0x3C00,
    0x2800,
    0xE401,
    0xA001,
    0x6C00,
    0x7800,
    0xB401,
    0x5000,
    0x9C01,
    0x8801,
    0x4400,
)


def crc_fit(donnees: bytes, crc: int = 0) -> int:
    for octet in donnees:
        tmp = _TABLE_CRC[crc & 0x0F]
        crc = (crc >> 4) & 0x0FFF
        crc = crc ^ tmp ^ _TABLE_CRC[octet & 0x0F]
        tmp = _TABLE_CRC[crc & 0x0F]
        crc = (crc >> 4) & 0x0FFF
        crc = crc ^ tmp ^ _TABLE_CRC[(octet >> 4) & 0x0F]
    return crc & 0xFFFF


# --- types de base FIT ------------------------------------------------------

EPOQUE_FIT = dt.datetime(1989, 12, 31, tzinfo=dt.UTC)

ENUM, UINT8, UINT16, UINT32, SINT8, SINT32, CHAINE = 0x00, 0x02, 0x84, 0x86, 0x01, 0x85, 0x07
_TAILLES = {ENUM: 1, UINT8: 1, SINT8: 1, UINT16: 2, UINT32: 4, SINT32: 4}
_FORMATS = {ENUM: "B", UINT8: "B", SINT8: "b", UINT16: "<H", UINT32: "<I", SINT32: "<i"}


def horodatage_fit(t: dt.datetime) -> int:
    return int((t - EPOQUE_FIT).total_seconds())


def semicercles(degres: float) -> int:
    return int(degres * (2**31) / 180.0)


class _Champ:
    def __init__(self, numero: int, type_base: int, taille: int | None = None):
        self.numero = numero
        self.type_base = type_base
        self.taille = taille if taille is not None else _TAILLES[type_base]

    def encoder(self, valeur) -> bytes:
        if self.type_base == CHAINE:
            brut = (valeur or "").encode("utf-8")[: self.taille - 1]
            return brut + b"\x00" * (self.taille - len(brut))
        if valeur is None:  # « invalide » FIT : tous les bits à 1
            return b"\xff" * self.taille
        return struct.pack(_FORMATS[self.type_base], valeur)


def _definition(type_local: int, message_global: int, champs: list[_Champ]) -> bytes:
    corps = struct.pack("<BBHB", 0, 0, message_global, len(champs))
    for c in champs:
        corps += struct.pack("<BBB", c.numero, c.taille, c.type_base)
    return bytes([0x40 | type_local]) + corps


def _donnees(type_local: int, champs: list[_Champ], valeurs: list) -> bytes:
    sortie = bytes([type_local])
    for champ, valeur in zip(champs, valeurs, strict=True):
        sortie += champ.encoder(valeur)
    return sortie


def _assembler(corps: bytes, *, data_size: int | None = None) -> bytes:
    """En-tête 14 octets + corps + CRC. `data_size` menteur si on le force."""
    taille = data_size if data_size is not None else len(corps)
    entete = struct.pack("<BBHI4s", 14, 0x20, 2140, taille, b".FIT")
    entete += struct.pack("<H", crc_fit(entete))
    return entete + corps + struct.pack("<H", crc_fit(entete + corps))


# --- messages ---------------------------------------------------------------

CHAMPS_FILE_ID = [_Champ(0, ENUM), _Champ(1, UINT16), _Champ(4, UINT32)]
CHAMPS_DEVICE = [_Champ(2, UINT16), _Champ(27, CHAINE, 24)]
CHAMPS_SESSION = [
    _Champ(253, UINT32),
    _Champ(2, UINT32),
    _Champ(5, ENUM),
    _Champ(7, UINT32),
    _Champ(8, UINT32),
    _Champ(9, UINT32),
    _Champ(20, UINT16),
    _Champ(22, UINT16),
]

# `record` : on choisit les champs variante par variante.
REC_T = _Champ(253, UINT32)
REC_LAT = _Champ(0, SINT32)
REC_LON = _Champ(1, SINT32)
REC_ALT = _Champ(2, UINT16)
REC_DIST = _Champ(5, UINT32)
REC_VIT = _Champ(6, UINT16)
REC_PUI = _Champ(7, UINT16)
REC_FC = _Champ(3, UINT8)
REC_CAD = _Champ(4, UINT8)
REC_TEMP = _Champ(13, SINT8)

DEBUT = dt.datetime(2026, 4, 12, 9, 0, tzinfo=dt.UTC)
NB_POINTS = 60  # une heure à un point par minute


def _points(nb: int = NB_POINTS, *, decalages: dict[int, int] | None = None):
    """Trajectoire synthétique autour de (0.0, 0.0). `decalages` triche sur le temps."""
    decalages = decalages or {}
    for i in range(nb):
        t = DEBUT + dt.timedelta(seconds=60 * i + decalages.get(i, 0))
        yield {
            "t": t,
            "lat": 0.0 + 0.0009 * i,
            "lon": 0.0 + 0.0004 * i,
            "alt": 20.0 + 10.0 * (i % 5),
            "dist": 400.0 * i,
            "vit": 6.7,
            "pui": 180 + (i % 7) * 10,
            "fc": 130 + (i % 9),
            "cad": 85,
            "temp": 14,
        }


def fit(
    *,
    gps: bool = True,
    puissance: bool = True,
    nb_points: int = NB_POINTS,
    decalages: dict[int, int] | None = None,
    session: bool = True,
    appareil: str | None = "Fictif 1000",
) -> bytes:
    champs = [REC_T]
    if gps:
        champs += [REC_LAT, REC_LON]
    champs += [REC_ALT, REC_DIST, REC_VIT]
    if puissance:
        champs.append(REC_PUI)
    champs += [REC_FC, REC_CAD, REC_TEMP]

    corps = _definition(0, 0, CHAMPS_FILE_ID)
    corps += _donnees(0, CHAMPS_FILE_ID, [4, 1, horodatage_fit(DEBUT)])
    if appareil is not None:
        corps += _definition(1, 23, CHAMPS_DEVICE)
        corps += _donnees(1, CHAMPS_DEVICE, [4242, appareil])

    corps += _definition(2, 20, champs)
    pts = list(_points(nb_points, decalages=decalages))
    for p in pts:
        valeurs = [horodatage_fit(p["t"])]
        if gps:
            valeurs += [semicercles(p["lat"]), semicercles(p["lon"])]
        valeurs += [int((p["alt"] + 500) * 5), int(p["dist"] * 100), int(p["vit"] * 1000)]
        if puissance:
            valeurs.append(p["pui"])
        valeurs += [p["fc"], p["cad"], p["temp"]]
        corps += _donnees(2, champs, valeurs)

    if session and pts:
        ecoule = int((pts[-1]["t"] - pts[0]["t"]).total_seconds())
        corps += _definition(3, 18, CHAMPS_SESSION)
        corps += _donnees(
            3,
            CHAMPS_SESSION,
            [
                horodatage_fit(pts[-1]["t"]),
                horodatage_fit(pts[0]["t"]),
                2,
                abs(ecoule) * 1000,
                abs(ecoule) * 1000,
                int(pts[-1]["dist"] * 100),
                200 if puissance else None,
                120,
            ],
        )
    return _assembler(corps)


# --- GPX / TCX --------------------------------------------------------------


def gpx(
    *,
    gps: bool = True,
    puissance: bool = True,
    temps: bool = True,
    nb_points: int = 30,
    decalages: dict[int, int] | None = None,
    horodatages: list[str] | None = None,
) -> bytes:
    lignes = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<gpx version="1.1" creator="generer_hostiles.py"'
        ' xmlns="http://www.topografix.com/GPX/1/1"'
        ' xmlns:gpxtpx="http://www.garmin.com/xmlschemas/TrackPointExtension/v1"'
        ' xmlns:pwr="http://www.garmin.com/xmlschemas/PowerExtension/v1">',
        "<trk><name>Trace fictive</name><trkseg>",
    ]
    for i, p in enumerate(_points(nb_points, decalages=decalages)):
        if gps:
            lignes.append(f'<trkpt lat="{p["lat"]:.6f}" lon="{p["lon"]:.6f}">')
        else:
            lignes.append("<trkpt>")
        lignes.append(f"<ele>{p['alt']:.1f}</ele>")
        if horodatages is not None:
            lignes.append(f"<time>{horodatages[i]}</time>")
        elif temps:
            lignes.append(f"<time>{p['t'].strftime('%Y-%m-%dT%H:%M:%SZ')}</time>")
        ext = [
            f"<gpxtpx:hr>{p['fc']}</gpxtpx:hr>",
            f"<gpxtpx:cad>{p['cad']}</gpxtpx:cad>",
            f"<gpxtpx:atemp>{p['temp']}</gpxtpx:atemp>",
        ]
        if puissance:
            ext.insert(0, f"<pwr:PowerInWatts>{p['pui']}</pwr:PowerInWatts>")
        lignes.append(
            "<extensions><gpxtpx:TrackPointExtension>"
            + "".join(ext)
            + "</gpxtpx:TrackPointExtension></extensions>"
        )
        lignes.append("</trkpt>")
    lignes += ["</trkseg></trk>", "</gpx>"]
    return "\n".join(lignes).encode("utf-8")


_TCX_NS = (
    ' xmlns="http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2"'
    ' xmlns:ns3="http://www.garmin.com/xmlschemas/ActivityExtension/v2"'
)


def tcx(
    *,
    gps: bool = True,
    puissance: bool = True,
    temps: bool = True,
    nb_points: int = 30,
    decalages: dict[int, int] | None = None,
    horodatages: list[str] | None = None,
    sport: str = "Biking",
    espaces_de_noms: bool = True,
    appareil: str | None = "Fictif 1000",
) -> bytes:
    pts = list(_points(nb_points, decalages=decalages))
    lignes = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f"<TrainingCenterDatabase{_TCX_NS if espaces_de_noms else ''}>",
        f'<Activities><Activity Sport="{sport}">',
        f"<Id>{pts[0]['t'].strftime('%Y-%m-%dT%H:%M:%SZ')}</Id>",
        f'<Lap StartTime="{pts[0]["t"].strftime("%Y-%m-%dT%H:%M:%SZ")}">',
        f"<TotalTimeSeconds>{(nb_points - 1) * 60}</TotalTimeSeconds>",
        f"<DistanceMeters>{pts[-1]['dist']:.1f}</DistanceMeters>",
        "<Track>",
    ]
    for i, p in enumerate(pts):
        lignes.append("<Trackpoint>")
        if horodatages is not None:
            lignes.append(f"<Time>{horodatages[i]}</Time>")
        elif temps:
            lignes.append(f"<Time>{p['t'].strftime('%Y-%m-%dT%H:%M:%SZ')}</Time>")
        if gps:
            lignes.append(
                f"<Position><LatitudeDegrees>{p['lat']:.6f}</LatitudeDegrees>"
                f"<LongitudeDegrees>{p['lon']:.6f}</LongitudeDegrees></Position>"
            )
        lignes.append(f"<AltitudeMeters>{p['alt']:.1f}</AltitudeMeters>")
        lignes.append(f"<DistanceMeters>{p['dist']:.1f}</DistanceMeters>")
        lignes.append(f"<HeartRateBpm><Value>{p['fc']}</Value></HeartRateBpm>")
        lignes.append(f"<Cadence>{p['cad']}</Cadence>")
        prefixe = "ns3:" if espaces_de_noms else ""
        ext = [f"<{prefixe}Speed>{p['vit']}</{prefixe}Speed>"]
        if puissance:
            ext.append(f"<{prefixe}Watts>{p['pui']}</{prefixe}Watts>")
        lignes.append(f"<Extensions><{prefixe}TPX>" + "".join(ext) + f"</{prefixe}TPX></Extensions>")
        lignes.append("</Trackpoint>")
    lignes += ["</Track></Lap>"]
    if appareil is not None:
        lignes.append(f"<Creator><Name>{appareil}</Name></Creator>")
    lignes += ["</Activity></Activities>", "</TrainingCenterDatabase>"]
    return "\n".join(lignes).encode("utf-8")


# --- catalogue --------------------------------------------------------------

# Dernier dimanche d'octobre 2026 : à 01:00 UTC il est 03:00 CEST, à 01:00 UTC
# + 1 h il est 02:00 CET. Deux points à une heure d'intervalle qui portent la
# même heure locale, et deux écritures locales différentes du même instant.
HORODATAGES_HEURE_ETE = [
    "2026-10-25T02:59:00+02:00",  # = 00:59 UTC, CEST
    "2026-10-25T02:01:00+01:00",  # = 01:01 UTC, CET — heure locale « en arrière »
    "2026-10-25T01:30:00Z",
    "2026-10-25T03:00:00+01:00",  # = 02:00 UTC
]

HORODATAGES_PRINTEMPS = [
    "2026-03-29T01:59:00+01:00",  # = 00:59 UTC, CET
    "2026-03-29T03:01:00+02:00",  # = 01:01 UTC, CEST — heure locale qui saute
    "2026-03-29T01:30:00Z",
    "2026-03-29T04:00:00+02:00",  # = 02:00 UTC
]


def contenus() -> dict[str, bytes]:
    """Tout le catalogue, en mémoire. Clé = nom de fichier."""
    nominal_fit = fit()
    c: dict[str, bytes] = {
        # --- FIT ---
        "nominal.fit": nominal_fit,
        "nominal_maj.FIT": nominal_fit,  # même contenu, extension en majuscules
        "vide.fit": b"",
        "tronque.fit": nominal_fit[:40],
        "entete_seul.fit": _assembler(b"", data_size=0),
        "entete_menteur.fit": _assembler(b"", data_size=4096),
        "crc_faux.fit": nominal_fit[:-1] + bytes([nominal_fit[-1] ^ 0xFF]),
        "corps_aleatoire.fit": _assembler(bytes(range(256)) * 4),
        "fit_sans_gps.fit": fit(gps=False),
        "fit_sans_puissance.fit": fit(puissance=False),
        "fit_non_monotone.fit": fit(decalages={10: -3600, 11: -3600, 12: -3600}),
        "fit_un_point.fit": fit(nb_points=1),
        "fit_sans_session.fit": fit(session=False),
        # --- GPX ---
        "nominal.gpx": gpx(),
        "nominal_maj.GPX": gpx(),
        "nominal_mixte.Gpx": gpx(),
        "vide.gpx": b"",
        "espaces_seuls.gpx": b"   \n\t\n  ",
        "xml_invalide.gpx": gpx()[: int(len(gpx()) * 0.6)] + b'<trkpt lat="0.0"',
        "pas_du_gpx.gpx": b'<?xml version="1.0"?>\n<html><body>bonjour</body></html>\n',
        "gpx_sans_gps.gpx": gpx(gps=False),
        "gpx_sans_puissance.gpx": gpx(puissance=False),
        "gpx_sans_temps.gpx": gpx(temps=False),
        "gpx_sans_point.gpx": (
            b'<?xml version="1.0" encoding="UTF-8"?>\n'
            b'<gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1">'
            b"<trk><trkseg></trkseg></trk></gpx>\n"
        ),
        "gpx_non_monotone.gpx": gpx(decalages={5: -1800, 6: -1800}),
        "gpx_heure_ete.gpx": gpx(nb_points=4, horodatages=HORODATAGES_HEURE_ETE),
        "gpx_heure_ete_printemps.gpx": gpx(nb_points=4, horodatages=HORODATAGES_PRINTEMPS),
        "gpx_temps_naif.gpx": gpx(
            nb_points=3,
            horodatages=["2026-10-25T00:30:00", "2026-10-25T00:31:00", "2026-10-25T00:32:00"],
        ),
        "gpx_temps_absurde.gpx": gpx(nb_points=3, horodatages=["hier matin", "2026-13-45T99:99:99Z", ""]),
        # --- TCX ---
        "nominal.tcx": tcx(),
        "nominal_maj.TCX": tcx(),
        "vide.tcx": b"",
        "xml_invalide.tcx": tcx()[:-30],
        "tcx_sans_espaces_de_noms.tcx": tcx(espaces_de_noms=False),
        "tcx_sans_gps.tcx": tcx(gps=False),
        "tcx_sans_puissance.tcx": tcx(puissance=False),
        "tcx_non_monotone.tcx": tcx(decalages={4: -7200}),
        "tcx_virtuel.tcx": tcx(sport="Other", appareil="ZWIFT\u00a0Runtime\u200b v1.2  "),
        "tcx_heure_ete.tcx": tcx(nb_points=4, horodatages=HORODATAGES_HEURE_ETE),
        "tcx_sans_trackpoint.tcx": (
            b'<?xml version="1.0" encoding="UTF-8"?>\n'
            b'<TrainingCenterDatabase xmlns="http://www.garmin.com/xmlschemas/'
            b'TrainingCenterDatabase/v2"><Activities/></TrainingCenterDatabase>\n'
        ),
        # --- extensions ---
        "activite.inconnu": b"peu importe le contenu\n",
        "activite_sans_extension": b"peu importe le contenu\n",
        "activite.fit.gz": b"\x1f\x8b\x08\x00" + b"\x00" * 20,
        "activite.gpx.bak": gpx(nb_points=3),
    }
    return c


#: Ce que chaque fichier est censé démontrer — sert de documentation et de
#: garde-fou : `test_adv_lecture.py` vérifie que le catalogue et cette table
#: couvrent les mêmes noms.
CATALOGUE = {
    "nominal.fit": "FIT complet valide (GPS, puissance, session, appareil)",
    "nominal_maj.FIT": "même FIT, extension en majuscules",
    "vide.fit": "0 octet",
    "tronque.fit": "en-tête « .FIT » + 26 octets de corps, ni fin de message ni CRC",
    "entete_seul.fit": "en-tête valide, data_size=0, aucun message",
    "entete_menteur.fit": "en-tête valide annonçant 4 ko de données absentes",
    "crc_faux.fit": "FIT nominal dont le dernier octet de CRC est inversé",
    "corps_aleatoire.fit": "en-tête cohérent, corps d'octets arbitraires",
    "fit_sans_gps.fit": "records sans position_lat/long",
    "fit_sans_puissance.fit": "records sans power",
    "fit_non_monotone.fit": "trois records qui reculent d'une heure",
    "fit_un_point.fit": "un seul record (durée nulle)",
    "fit_sans_session.fit": "records sans message session",
    "nominal.gpx": "GPX 1.1 valide avec extensions puissance/FC/cadence",
    "nominal_maj.GPX": "même GPX, extension en majuscules",
    "nominal_mixte.Gpx": "même GPX, extension en casse mélangée",
    "vide.gpx": "0 octet",
    "espaces_seuls.gpx": "uniquement des blancs",
    "xml_invalide.gpx": "XML tronqué puis balise ouverte jamais fermée",
    "pas_du_gpx.gpx": "XML valide mais racine <html>",
    "gpx_sans_gps.gpx": "trkpt sans attributs lat/lon — GPX invalide, gpxpy le refuse",
    "gpx_sans_puissance.gpx": "aucune extension de puissance",
    "gpx_sans_temps.gpx": "aucun <time>",
    "gpx_sans_point.gpx": "trkseg vide",
    "gpx_non_monotone.gpx": "deux points qui reculent de 30 min",
    "gpx_heure_ete.gpx": "fenêtre du dernier dimanche d'octobre 2026, offsets +02:00 puis +01:00",
    "gpx_heure_ete_printemps.gpx": "fenêtre du dernier dimanche de mars 2026, +01:00 puis +02:00",
    "gpx_temps_naif.gpx": "<time> sans fuseau ni Z",
    "gpx_temps_absurde.gpx": "<time> non analysables (texte, mois 13, vide)",
    "nominal.tcx": "TCX valide avec Watts, Cadence, Position",
    "nominal_maj.TCX": "même TCX, extension en majuscules",
    "vide.tcx": "0 octet",
    "xml_invalide.tcx": "TCX tronqué en fin de fichier",
    "tcx_sans_espaces_de_noms.tcx": "structure TCX valide mais sans aucun namespace déclaré",
    "tcx_sans_gps.tcx": "Trackpoint sans Position",
    "tcx_sans_puissance.tcx": "Trackpoint sans ns3:Watts",
    "tcx_non_monotone.tcx": "un Trackpoint qui recule de deux heures",
    "tcx_virtuel.tcx": "Sport=Other, Creator ZWIFT avec espace insécable, espace de largeur nulle et blancs",
    "tcx_heure_ete.tcx": "fenêtre du changement d'heure d'octobre 2026",
    "tcx_sans_trackpoint.tcx": "<Activities/> vide",
    "activite.inconnu": "extension inconnue",
    "activite_sans_extension": "aucune extension",
    "activite.fit.gz": "double extension, contenu gzip",
    "activite.gpx.bak": "GPX valide mais extension finale .bak",
}


def ecrire_tous(dossier: Path) -> dict[str, Path]:
    """Matérialise le catalogue dans `dossier` et renvoie {nom: chemin}."""
    dossier.mkdir(parents=True, exist_ok=True)
    chemins = {}
    for nom, contenu in contenus().items():
        chemin = dossier / nom
        chemin.write_bytes(contenu)
        chemins[nom] = chemin
    return chemins


if __name__ == "__main__":  # pragma: no cover
    cible = Path(sys.argv[1] if len(sys.argv) > 1 else "hostiles")
    for nom, chemin in sorted(ecrire_tous(cible).items()):
        print(f"{chemin.stat().st_size:>8} o  {nom:32} {CATALOGUE.get(nom, '')}")
