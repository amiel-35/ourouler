"""`workout_doc` **fabriqués**, à la forme observée chez Intervals.icu.

Aucune de ces séances n'existe : elles reproduisent la *structure* du format
(groupes `{reps, text, duration, steps}`, sous-étapes `{duration, power|hr}`,
marqueurs `warmup`/`cooldown`/`intensity`), avec des durées et des puissances
inventées. Aucun identifiant, aucun nom et aucune valeur ne vient d'un compte
réel.

Trois variantes de la même forme — échauffement, 4 × [bloc + récup], retour au
calme — pour couvrir les trois façons de dire la consigne :

- `groupes_hr_zone()` en `hr_zone` (puissance approximée) ;
- `groupes_pourcent_ftp()` en `%ftp` ;
- `groupes_watts()` en `watts`.
"""

from __future__ import annotations

#: Une FTP inventée, ronde, pour que les attentes des tests se calculent de tête.
FTP_TEST = 200.0


def _doc(steps: list[dict], **extra) -> dict:
    duree = sum(s.get("duration", 0) for s in steps)
    return {"steps": steps, "locales": [], "options": {}, "distance": 0, "duration": duree, **extra}


def _groupe(reps: int, texte: str, steps: list[dict]) -> dict:
    return {
        "reps": reps,
        "text": texte,
        "steps": steps,
        "distance": 0,
        "duration": reps * sum(s.get("duration", 0) for s in steps),
    }


def groupes_hr_zone() -> dict:
    """Échauffement, 4 × [8 min Z4 + 4 min Z1], retour au calme — en zones de FC."""
    return _doc(
        [
            _groupe(
                1,
                "Main Set 1x",
                [
                    {
                        "hr": {"units": "hr_zone", "value": 2},
                        "warmup": True,
                        "duration": 600,
                        "intensity": "warmup",
                    }
                ],
            ),
            _groupe(
                4,
                "Main Set 4x",
                [
                    {"hr": {"units": "hr_zone", "value": 4}, "duration": 480},
                    {
                        "hr": {"units": "hr_zone", "value": 1},
                        "duration": 240,
                        "intensity": "recovery",
                    },
                ],
            ),
            _groupe(
                1,
                "Main Set 1x",
                [
                    {
                        "hr": {"units": "hr_zone", "value": 1},
                        "cooldown": True,
                        "duration": 300,
                        "intensity": "cooldown",
                    }
                ],
            ),
        ]
    )


def groupes_pourcent_ftp() -> dict:
    """Même forme, consignes en `%ftp`, avec une rampe d'échauffement."""
    return _doc(
        [
            _groupe(
                1,
                "Echauffement",
                [
                    {
                        "power": {"units": "%ftp", "start": 55, "end": 70},
                        "ramp": True,
                        "warmup": True,
                        "duration": 900,
                        "intensity": "warmup",
                    }
                ],
            ),
            _groupe(
                4,
                "Corps 4x",
                [
                    {"power": {"units": "%ftp", "value": 100}, "duration": 480},
                    {
                        "power": {"units": "%ftp", "value": 50},
                        "duration": 240,
                        "intensity": "recovery",
                    },
                ],
            ),
            _groupe(
                1,
                "Retour au calme",
                [
                    {
                        "power": {"units": "%ftp", "start": 60, "end": 40},
                        "ramp": True,
                        "cooldown": True,
                        "duration": 300,
                    }
                ],
            ),
        ]
    )


def groupes_watts() -> dict:
    """Même forme, consignes en watts absolus."""
    return _doc(
        [
            _groupe(
                1,
                "Echauffement",
                [{"power": {"units": "watts", "value": 130}, "warmup": True, "duration": 600}],
            ),
            _groupe(
                4,
                "Corps 4x",
                [
                    {"power": {"units": "watts", "start": 240, "end": 260}, "duration": 480},
                    {
                        "power": {"units": "watts", "value": 110},
                        "duration": 240,
                        "intensity": "recovery",
                    },
                ],
            ),
            _groupe(
                1,
                "Retour au calme",
                [
                    {
                        "power": {"units": "watts", "value": 110},
                        "duration": 300,
                        "intensity": "cooldown",
                    }
                ],
            ),
        ]
    )


def sortie_libre() -> dict:
    """Une sortie d'endurance : un seul groupe, marqué `warmup` de bout en bout.

    C'est la forme réelle d'une « sortie EF » sur le compte du mainteneur : le
    planificateur marque toute la séance en échauffement.
    """
    return _doc(
        [
            _groupe(
                1,
                "Main Set 1x",
                [
                    {
                        "hr": {"units": "hr_zone", "value": 2},
                        "warmup": True,
                        "duration": 7200,
                        "intensity": "warmup",
                    }
                ],
            )
        ]
    )


def plat_et_groupes() -> dict:
    """Étapes à plat **et** groupes dans le même document, plus deux étapes libres.

    Forme observée sur une séance d'extérieur : les portions libres servent à
    rejoindre la zone d'intervalles.
    """
    return _doc(
        [
            {"duration": 1200, "freeride": True},
            _groupe(
                4,
                "4x",
                [
                    {"power": {"units": "%ftp", "value": 145}, "duration": 40},
                    {
                        "power": {"units": "%ftp", "value": 52},
                        "duration": 90,
                        "intensity": "recovery",
                    },
                ],
            ),
            {"power": {"units": "%ftp", "value": 80}, "duration": 300},
            {"duration": 600, "freeride": True},
        ],
        description="Seance fabriquee pour les tests.",
    )


def evenement(doc: dict, *, nom: str, sport: str = "Ride", identifiant: int = 1) -> dict:
    """Un événement de calendrier minimal autour d'un `workout_doc`."""
    return {
        "id": identifiant,
        "name": nom,
        "type": sport,
        "category": "WORKOUT",
        "start_date_local": "2026-09-08T00:00:00",
        "workout_doc": doc,
    }


def coach_sans_marqueur() -> dict:
    """Séance de coach : aucun marqueur, le type est écrit dans `text`.

    Forme des séances iDOSport remontées dans Intervals : ni `warmup`, ni
    `cooldown`, ni `intensity` — seulement « RPE cible 2, Échauffement » et
    « RPE cible 2, Récupération » dans le champ libre.
    """
    calme = {
        "text": "RPE cible 2,  Récupération",
        "power": {"end": 70, "start": 50, "units": "%ftp"},
        "duration": 1200,
    }
    return _doc(
        [
            {
                "text": "RPE cible 2,  Échauffement",
                "power": {"end": 70, "start": 50, "units": "%ftp"},
                "duration": 1800,
            },
            _groupe(
                2,
                "2x",
                [
                    {"power": {"end": 85, "start": 80, "units": "%ftp"}, "duration": 1200},
                    {
                        "text": "RPE cible 2,  Récupération",
                        "power": {"end": 70, "start": 50, "units": "%ftp"},
                        "duration": 300,
                    },
                ],
            ),
            calme,
        ]
    )


def coach_muet() -> dict:
    """Séance de coach sans marqueur **ni** texte : seule la puissance parle.

    Forme de « 4x8 SV1 outdoor » : des efforts à 98-145 % de FTP séparés de
    récupérations à 50 %, et rien d'autre pour les distinguer.
    """
    return _doc(
        [
            {"power": {"units": "%ftp", "value": 50}, "duration": 1200},
            _groupe(
                4,
                "4x",
                [
                    {"power": {"units": "%ftp", "value": 98}, "duration": 480},
                    {"power": {"units": "%ftp", "value": 50}, "duration": 165},
                ],
            ),
            {"power": {"units": "%ftp", "value": 50}, "duration": 900},
        ]
    )
