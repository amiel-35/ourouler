"""Le texte et le JSON de `ourouler routes` : apprendre, stats, poids.

Séparés de `apprentissage/commande.py` : le cas d'usage rend ses
résultats (rapport, statistiques, poids), l'entrée choisit texte ou JSON et
imprime. Aucun de ces rendus ne lit de fichier ni de base.
"""

from __future__ import annotations

from datetime import date

from ourouler.apprentissage.commande import ABSENT, DISTANCE_EXPOSITION_KM
from ourouler.apprentissage.routes import (
    LIBELLE_SANS_HIGHWAY,
    PART_EXPOSITION_MIN,
    RapportApprentissage,
    Statistiques,
)
from ourouler.boucle.couts import POIDS_HIGHWAY_DEFAUT
from ourouler.meteo.couronne import NOMS_DIRECTIONS
from ourouler.noyau.texte import nombre_fr


def texte_apprentissage(rapport: RapportApprentissage, depuis: date, stats: Statistiques) -> str:
    """Ce que `routes apprendre` a rejoué, puis l'état de la base après coup."""
    lignes = [
        f"Apprentissage des routes depuis le {depuis.isoformat()} — "
        f"{rapport.sorties_vues} sortie(s) extérieure(s) en cache",
        f"  apprises ce coup-ci : {rapport.sorties_apprises} "
        f"({nombre_fr(rapport.km, 0)} km rejoués, {rapport.mailles} mailles, "
        f"D+ {nombre_fr(rapport.denivele_m, 0) if rapport.denivele_m is not None else ABSENT} m "
        "tracé rerouté)",
        f"  déjà connues        : {rapport.sorties_deja_connues}",
        f"  échecs              : {rapport.echecs}",
    ]
    lignes.extend(f"    échec — {m}" for m in rapport.messages[:20])
    if len(rapport.messages) > 20:
        lignes.append(f"    … et {len(rapport.messages) - 20} autre(s)")
    lignes.append("")
    lignes.append(
        f"Base : {stats.sorties} sortie(s), {nombre_fr(stats.km_total, 0)} km roulés, "
        f"{stats.mailles} mailles connues."
    )
    return "\n".join(lignes)


def json_apprentissage(rapport: RapportApprentissage, depuis: date) -> dict:
    return {
        "depuis": depuis.isoformat(),
        "sorties_vues": rapport.sorties_vues,
        "sorties_apprises": rapport.sorties_apprises,
        "sorties_deja_connues": rapport.sorties_deja_connues,
        "echecs": rapport.echecs,
        "km": round(rapport.km, 1),
        "mailles": rapport.mailles,
        "denivele_m": round(rapport.denivele_m, 1) if rapport.denivele_m is not None else None,
        "denivele_source": "tracé rerouté" if rapport.denivele_m is not None else None,
        "messages": list(rapport.messages),
    }




def texte_stats(stats: Statistiques, appris: dict[str, float] | None) -> str:
    if stats.km_total <= 0:
        return (
            "Aucune route apprise pour l'instant — lancer `ourouler routes apprendre` "
            "(un appel BRouter par sortie extérieure)."
        )
    lignes = [
        f"Routes roulées — {stats.sorties} sortie(s), {nombre_fr(stats.km_total, 0)} km, "
        f"{stats.mailles} mailles",
        f"Coût moyen du profil BRouter : "
        f"{nombre_fr(stats.cout_km_moyen, 0) if stats.cout_km_moyen is not None else ABSENT}",
        "",
    ]
    titres = ("classe", "km", "part", "part semaine", "poids défaut", "poids appris")
    cellules = [
        [
            _libelle(classe),
            nombre_fr(stats.km_par_highway[classe], 0),
            f"{stats.part(classe) * 100:.0f} %",
            f"{stats.part_semaine(classe) * 100:.0f} %",
            nombre_fr(POIDS_HIGHWAY_DEFAUT.get(classe, 0.0), 1),
            nombre_fr(appris[classe], 2) if appris and classe in appris else ABSENT,
        ]
        for classe in stats.classes()
    ]
    lignes.extend(_tableau(titres, cellules))
    if appris is None:
        lignes.append("")
        lignes.append(
            "Aucun poids appris pour l'instant : `ourouler routes poids --appliquer` "
            "les mesure et les écrit."
        )
    lignes.append("")
    lignes.extend(_secondaire("maxspeed", stats.km_par_maxspeed, stats.km_total))
    lignes.append("")
    lignes.extend(_secondaire("surface", stats.km_par_surface, stats.km_total))
    return "\n".join(lignes)


def _secondaire(nom: str, par_valeur: dict[str, float], km_total: float) -> list[str]:
    """Les cinq valeurs les plus roulées d'un tag secondaire, en une petite table."""
    classees = sorted(par_valeur.items(), key=lambda kv: (-kv[1], kv[0]))[:5]
    titres = (nom, "km", "part")
    cellules = [
        [
            valeur or "(absent)",
            nombre_fr(km, 0),
            f"{(km / km_total * 100 if km_total else 0):.0f} %",
        ]
        for valeur, km in classees
    ]
    return _tableau(titres, cellules)


def json_stats(stats: Statistiques, appris: dict[str, float] | None) -> dict:
    return {
        "sorties": stats.sorties,
        "mailles": stats.mailles,
        "km_total": round(stats.km_total, 1),
        "km_semaine": round(stats.km_semaine, 1),
        "cout_km_moyen": stats.cout_km_moyen,
        "par_highway": [
            {
                "classe": classe,
                "km": round(stats.km_par_highway[classe], 1),
                "part": round(stats.part(classe), 4),
                "part_semaine": round(stats.part_semaine(classe), 4),
                "poids_defaut": POIDS_HIGHWAY_DEFAUT.get(classe, 0.0),
                "poids_appris": (appris or {}).get(classe),
            }
            for classe in stats.classes()
        ],
        "km_par_maxspeed": {k: round(v, 1) for k, v in stats.km_par_maxspeed.items()},
        "km_par_surface": {k: round(v, 1) for k, v in stats.km_par_surface.items()},
    }




def texte_poids(
    stats: Statistiques,
    exposition: Statistiques,
    poids: dict[str, float],
    echecs: list[str],
    ecrit_dans,
) -> str:
    lignes = [
        f"Poids appris — {stats.sorties} sortie(s) roulée(s) ({nombre_fr(stats.km_total, 0)} km) "
        f"contre {exposition.sorties} boucle(s) d'exposition "
        f"({nombre_fr(exposition.km_total, 0)} km, {DISTANCE_EXPOSITION_KM:g} km × "
        f"{len(NOMS_DIRECTIONS)} directions)",
        "Poids = min(4, max(0, log2(part exposition / part sorties))), en km "
        "équivalents par km ; tertiary est la référence, donc 0.",
        f"Sous {PART_EXPOSITION_MIN * 100:.0f} % d'exposition, la classe garde son poids par "
        "défaut : trop peu proposée pour que le rapport veuille dire quelque chose.",
        "",
    ]
    classes = sorted(
        set(stats.km_par_highway) | set(exposition.km_par_highway),
        key=lambda c: -stats.km_par_highway.get(c, 0.0),
    )
    titres = ("classe", "part sorties", "part exposition", "poids défaut", "poids appris")
    cellules = [
        [
            _libelle(classe),
            f"{nombre_fr(stats.part(classe) * 100, 1)} %",
            f"{nombre_fr(exposition.part(classe) * 100, 1)} %",
            nombre_fr(POIDS_HIGHWAY_DEFAUT.get(classe, 0.0), 1),
            nombre_fr(poids[classe], 2) if classe in poids else ABSENT,
        ]
        for classe in classes
    ]
    lignes.extend(_tableau(titres, cellules))
    if echecs:
        lignes.append("")
        lignes.append(f"{len(echecs)} direction(s) sans boucle — l'exposition porte sur le reste :")
        lignes.extend(f"  {m}" for m in echecs)
    lignes.append("")
    if ecrit_dans is not None:
        lignes.append(f"Poids écrits dans {ecrit_dans} — `ourouler boucle` les utilisera.")
    else:
        lignes.append("Rien n'a été écrit : ajouter --appliquer pour enregistrer ces poids.")
    return "\n".join(lignes)


def json_poids(
    stats: Statistiques, exposition: Statistiques, poids: dict[str, float], echecs: list[str]
) -> dict:
    classes = sorted(set(stats.km_par_highway) | set(exposition.km_par_highway))
    return {
        "sorties_apprises": stats.sorties,
        "km_appris": round(stats.km_total, 1),
        "boucles_exposition": exposition.sorties,
        "km_exposition": round(exposition.km_total, 1),
        "directions": list(NOMS_DIRECTIONS),
        "distance_exposition_km": DISTANCE_EXPOSITION_KM,
        "echecs": list(echecs),
        "classes": [
            {
                "classe": classe,
                "part_sorties": round(stats.part(classe), 4),
                "part_exposition": round(exposition.part(classe), 4),
                "poids_defaut": POIDS_HIGHWAY_DEFAUT.get(classe, 0.0),
                "poids_appris": poids.get(classe),
            }
            for classe in classes
        ],
        "poids": {k: round(v, 4) for k, v in poids.items()},
    }




def _tableau(titres: tuple[str, ...], cellules: list[list[str]]) -> list[str]:
    """Un tableau aligné à droite, titres compris. Vide si aucune ligne."""
    if not cellules:
        return [f"  {titres[0]} : aucune donnée"]
    largeurs = [
        max([len(t)] + [len(ligne[i]) for ligne in cellules]) for i, t in enumerate(titres)
    ]
    lignes = ["  " + "  ".join(t.rjust(n) for t, n in zip(titres, largeurs, strict=True))]
    for ligne in cellules:
        lignes.append("  " + "  ".join(c.rjust(n) for c, n in zip(ligne, largeurs, strict=True)))
    return lignes


def _libelle(classe: str) -> str:
    return classe or LIBELLE_SANS_HIGHWAY


