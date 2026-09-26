"""Rendu de `ourouler comparer` : le texte et le JSON d'une `Comparaison`.

Sorti de `rendu/physique.py`. Aucun accès disque ni réseau,
aucune lecture de configuration ; texte et JSON figés par
`tests/caracterisation/cli_comparer.json`.
"""

from __future__ import annotations

from datetime import date

from ourouler.physique.echantillonnage import LONGUEUR_ECHANTILLON_M
from ourouler.services.comparer import SERIES_MIN_BANDE, SERIES_MIN_REGRESSION, Bande, Comparaison

# --- ourouler comparer ---------------------------------------------------------


def rendre_texte_comparaison(resultat: Comparaison, depuis: date) -> str:
    premier, second = resultat.velos
    bas, haut = resultat.zone_w
    lignes = [
        f"Comparaison {premier} / {second} — vitesse à puissance égale, mesurée",
        f"Depuis le {depuis.isoformat()} : "
        + ", ".join(
            f"{nom} {resultat.par_velo[nom].sorties} sortie(s)" for nom in resultat.velos
        ),
        f"Séries de tronçons de {LONGUEUR_ECHANTILLON_M:.0f} m : "
        f"|pente| ≤ {resultat.pente_max * 100:.1f} %, {_libelle_cap(resultat.cap_max_deg)}, "
        f"≥ {resultat.longueur_min_m:.0f} m, sans arrêt ni relance,",
        f"puissance dans la zone {resultat.zone_ftp[0] * 100:.0f}-{resultat.zone_ftp[1] * 100:.0f} % "
        f"de la FTP, soit {bas:.0f}-{haut:.0f} W. Vent inconnu ; la mesure n'utilise aucun modèle.",
        "",
        f"  {'vélo':<8}{'séries':>8}{'km':>8}{'P moy':>9}{'V médiane':>12}",
    ]
    for nom in resultat.velos:
        v = resultat.par_velo[nom]
        lignes.append(
            f"  {nom:<8}{v.n_series:>8}{v.km:>8.0f}"
            f"{_watts(v.puissance_moyenne_w):>9}{_kmh(v.vitesse_mediane_kmh):>12}"
        )
    lignes += [
        "",
        "  Vitesse médiane par bande de puissance (bandes égales dans la zone) :",
        f"  {'bande':<12}{premier:>19}{second:>19}",
    ]
    for bande in resultat.bandes:
        lignes.append(
            f"  {bande.libelle:<12}"
            f"{_vitesse_et_n(bande, premier):>19}{_vitesse_et_n(bande, second):>19}"
        )
    milieu = resultat.puissance_milieu_w
    lignes += [
        "",
        f"  Régression vitesse = a + b·puissance (pondérée par la longueur), lue à {milieu:.0f} W "
        "(milieu de la zone) :",
    ]
    for nom in resultat.velos:
        lignes.append(f"  {_ligne_regression(resultat, nom)}")
    lignes += ["", *_synthese(resultat)]
    lignes.append(
        "Mailles de ~30 m touchées par ces séries : "
        + ", ".join(f"{nom} {resultat.mailles.get(nom, 0)}" for nom in resultat.velos)
        + f" — {resultat.mailles_communes} en commun (information : les mailles communes ne "
        "filtrent rien ici)."
    )
    lignes.append(
        "La mesure ne doit rien à un modèle : ce sont des moyennes de vitesse et de puissance "
        "mesurées. Le vent, la fraîcheur et le sens de passage diffèrent d'une série à l'autre "
        "— ils se compensent en partie, ils ne s'annulent pas."
    )
    return "\n".join(lignes)


def _libelle_cap(cap_max_deg: float | None) -> str:
    """Sans option, aucun cap n'est filtré : le dire plutôt que de taire le filtre absent."""
    if cap_max_deg is None or cap_max_deg >= 180:
        return "aucun filtre de cap (--cap-max pour en poser un)"
    return f"écart de cap ≤ {cap_max_deg:.0f}°"


def _ligne_regression(resultat: Comparaison, nom: str) -> str:
    velo = resultat.par_velo[nom]
    if velo.regression is None:
        return (
            f"{nom} : pas de régression — {velo.n_series} série(s), il en faut au moins "
            f"{SERIES_MIN_REGRESSION}."
        )
    r = velo.regression
    return (
        f"{nom} : {r.vitesse_kmh(resultat.puissance_milieu_w):.1f} km/h "
        f"(pente {r.pente_kmh_par_w * 10:.2f} km/h par 10 W, {r.n_series} séries, "
        f"{r.longueur_m / 1000:.0f} km)"
    )


def _synthese(resultat: Comparaison) -> list[str]:
    """Les lignes qui répondent à la question posée, ou disent pourquoi elles ne peuvent pas.

    L'ordre est volontaire : la **mesure** d'abord, en km/h, puis les
    conversions en watts, chacune avec sa formule et son statut.
    """
    premier, second = resultat.velos
    ecart = resultat.ecart_kmh
    if ecart is None:
        return [
            f"Écart non mesurable : il manque une régression "
            f"({premier} {resultat.par_velo[premier].n_series} série(s), "
            f"{second} {resultat.par_velo[second].n_series})."
        ]
    milieu = resultat.puissance_milieu_w
    vitesse = resultat.vitesse_lue(premier)
    lignes = [
        f"Mesure : {second} roule {ecart:+.1f} km/h à puissance égale "
        f"({milieu:.0f} W, milieu de la zone)."
    ]
    v3 = resultat.ecart_w_v3
    if v3 is not None:
        lent, rapide = (premier, second) if v3 >= 0 else (second, premier)
        lignes.append(
            f"Conversion, ordre de grandeur (loi en v³) : ΔP ≈ 3·P·Δv/v = "
            f"3 × {milieu:.0f} × {ecart:+.2f} / {vitesse:.1f} ≈ {abs(v3):.0f} W — "
            f"{lent} doit fournir ≈ {abs(v3):.0f} W de plus pour tenir l'allure de {rapide}."
        )
    modele = resultat.ecart_w_modele
    if modele is not None:
        p = resultat.parametres_reference
        lignes.append(
            f"Conversion par la calibration de {premier} (CdA {p.cda_m2:.3f} m², "
            f"Crr {p.crr:.5f}, {p.masse_totale_kg:.0f} kg) : "
            f"P({resultat.vitesse_lue(second):.1f} km/h) − P({vitesse:.1f} km/h) "
            f"≈ {abs(modele):.0f} W à plat et sans vent."
        )
    lignes.append(
        "Les km/h sont la mesure ; les watts en sont une conversion, pas une mesure."
    )
    return lignes


def _vitesse_et_n(bande: Bande, nom: str) -> str:
    """La médiane de la bande, ou seulement son effectif quand il est dérisoire."""
    vitesse, n = bande.vitesses.get(nom), bande.n.get(nom, 0)
    if vitesse is None or n < SERIES_MIN_BANDE:
        return f"— (n={n})"
    return f"{vitesse:.1f} km/h (n={n})"


def _watts(valeur: float | None) -> str:
    return "—" if valeur is None else f"{valeur:.0f} W"


def _kmh(valeur: float | None) -> str:
    return "—" if valeur is None else f"{valeur:.1f} km/h"


def rendre_json_comparaison(resultat: Comparaison, depuis: date) -> dict:
    premier, second = resultat.velos
    return {
        "velos": list(resultat.velos),
        "depuis": depuis.isoformat(),
        "zone_ftp": list(resultat.zone_ftp),
        "zone_w": [round(v, 1) for v in resultat.zone_w],
        "pente_max": resultat.pente_max,
        "cap_max_deg": resultat.cap_max_deg,
        "longueur_min_m": resultat.longueur_min_m,
        "longueur_troncon_m": LONGUEUR_ECHANTILLON_M,
        "puissance_lue_w": round(resultat.puissance_milieu_w, 1),
        "velo": {
            nom: {
                "sorties": v.sorties,
                "series": v.n_series,
                "km": round(v.km, 1),
                "puissance_moyenne_w": _arrondi(v.puissance_moyenne_w),
                "vitesse_mediane_kmh": _arrondi(v.vitesse_mediane_kmh),
                "regression": (
                    None
                    if v.regression is None
                    else {
                        "ordonnee_kmh": round(v.regression.ordonnee_kmh, 3),
                        "pente_kmh_par_w": round(v.regression.pente_kmh_par_w, 5),
                        "vitesse_lue_kmh": round(
                            v.regression.vitesse_kmh(resultat.puissance_milieu_w), 2
                        ),
                        "series": v.regression.n_series,
                        "km": round(v.regression.longueur_m / 1000, 1),
                    }
                ),
            }
            for nom, v in resultat.par_velo.items()
        },
        "bandes": [
            {
                "p_min_w": round(b.p_min_w, 1),
                "p_max_w": round(b.p_max_w, 1),
                "vitesse_mediane_kmh": {
                    nom: _arrondi(valeur) for nom, valeur in b.vitesses.items()
                },
                "n": dict(b.n),
            }
            for b in resultat.bandes
        ],
        "mailles": resultat.mailles,
        "mailles_communes": resultat.mailles_communes,
        "synthese": {
            "puissance_w": round(resultat.puissance_milieu_w, 1),
            "vitesse_kmh": {
                nom: _arrondi(resultat.vitesse_lue(nom), 2) for nom in (premier, second)
            },
            "ecart_kmh": _arrondi(resultat.ecart_kmh, 2),
            "ecart_w_v3": _arrondi(resultat.ecart_w_v3, 0),
            "ecart_w_modele": _arrondi(resultat.ecart_w_modele, 0),
            "formules": {
                "mesure": "ecart_kmh = vitesse(second) − vitesse(premier) au milieu de la zone",
                "ecart_w_v3": f"3 × puissance_w × ecart_kmh / vitesse({premier})",
                "ecart_w_modele": (
                    f"puissance_requise(vitesse(second)) − puissance_requise(vitesse({premier}))"
                    f" avec la calibration de {premier}, à plat et sans vent"
                ),
            },
        },
        # La mesure (les km/h) ne doit rien à un modèle ; seule la conversion en
        # watts en emprunte un, et elle est rendue à part.
        "modele_physique": False,
    }


def _arrondi(valeur: float | None, decimales: int = 1) -> float | None:
    return None if valeur is None else round(valeur, decimales)
