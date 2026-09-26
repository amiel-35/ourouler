"""Rendu des commandes du modèle physique : `calibrer`, `simuler`, `analyser`, `comparer`.

Couche 4 de `docs/ouverture_plan.md` §2, sortie de `physique/commande.py` et
de `physique/comparer.py` au lot 8. Chaque fonction reçoit des objets déjà
calculés — le rapport de calibration, la simulation, la météo le long du
tracé, la comparaison — et rend une chaîne ou un dictionnaire : aucun accès
disque ni réseau, aucune lecture de configuration. Ce que la commande
connaissait par la `Config` ou le client d'archive (date de début de
l'historique, appels à l'archive, fichier écrit) lui est passé en valeurs.

Le texte et le JSON sont ceux d'avant le lot 8, à l'octet près : les
références `tests/caracterisation/cli_calibrer.json` et `cli_comparer.json`
les figent.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime
from pathlib import Path

from ourouler.boucle.geometrie import geometrie_json
from ourouler.boucle.horaire import Pause
from ourouler.boucle.meteo_trace import MeteoTrace, fleches_vent
from ourouler.noyau.profil import Velo
from ourouler.physique import litterature
from ourouler.physique.calibration import (
    LONGUEUR_ECHANTILLON_M,
    SORTIES_MIN_FOURCHETTE,
    MesurePorteAPorte,
    RapportCalibration,
)
from ourouler.physique.modele import FourchettePorteAPorte, Parametres, PorteAPorte, Simulation
from ourouler.services.comparer import SERIES_MIN_BANDE, SERIES_MIN_REGRESSION, Bande, Comparaison
from ourouler.stockage.calibrations import porte_a_porte_json

#: Mention affichée à côté d'un temps, selon d'où il vient. La seconde vaut
#: pour un modèle qui tourne sur des valeurs de `physique.litterature` : le
#: temps est calculé, mais sur des CdA et Crr jamais mesurés sur ce vélo
#: (règle absolue 5). Mêmes mots que `boucle.commande`.
MENTION_MODELE = "(modèle)"
MENTION_MODELE_LITTERATURE = "(modèle, littérature)"


# --- ourouler calibrer --------------------------------------------------------


def rendre_texte_calibration(
    rapport: RapportCalibration,
    velo: Velo,
    *,
    depuis: date,
    fichier: Path,
    archives_appels: int,
    archives_cache: int,
    motifs: dict[str, int],
    n_calibrables: int,
    crr_source: str = "ajuste",
) -> str:
    a = rapport.ajustement
    v = rapport.validation
    lignes = [
        f"Calibration {velo.nom} — {n_calibrables} sortie(s) calibrable(s) "
        f"depuis le {depuis.isoformat()}"
    ]
    if motifs:
        detail = ", ".join(f"{nombre} {motif}" for motif, nombre in sorted(motifs.items()))
        lignes.append(f"Sorties du vélo écartées : {detail}")
    lignes.append(
        f"Archives météo : {archives_appels} appel(s), {archives_cache} déjà en cache"
    )
    lignes.append("")
    lignes.append(
        f"Apprentissage : {rapport.n_apprentissage} sortie(s), "
        f"{rapport.echantillons_retenus} échantillon(s) retenu(s) sur {rapport.echantillons}"
    )
    if rapport.motifs:
        detail = ", ".join(f"{motif} {nombre}" for motif, nombre in rapport.motifs.items())
        lignes.append(f"  échantillons écartés : {detail}")
    if rapport.echantillons_sans_vent:
        lignes.append(
            f"  {rapport.echantillons_sans_vent} échantillon(s) retenu(s) sans vent archivé "
            "(comptés à vent nul)"
        )
    # Ce que les données mesurent vraiment vient en premier ; CdA et Crr, qui
    # peuvent se compenser l'un l'autre, sont relégués à une ligne de détail
    # (décision du 13/09 — on ne cherche plus à les séparer).
    lignes.append("  résistance totale sur le plat sans vent, vélo + cycliste :")
    for vitesse, force, puissance in a.resistances:
        lignes.append(
            f"    à {vitesse:g} km/h : {_fr(force, 1)} N  —  {_fr(puissance, 0)} W au pédalier"
        )
    lignes.append(
        f"  résidu de puissance : RMSE {_fr(a.rmse_w, 1)} W, MAE {_fr(a.mae_w, 1)} W"
    )
    if a.crr_fixe:
        # L9.1 : le Crr est reçu (pneu ou configuration), seul le CdA est
        # cherché — il se cite donc, lui, sans la réserve « mal séparé ».
        lignes.append(
            f"  CdA {_fr(a.cda_m2, 3)} m²{_incertitude(a.incertitudes.cda, 3)} (cherché), "
            f"Crr {_fr(a.crr, 4)} fixé ({_crr_texte(crr_source, velo)}), "
            f"masse {_fr(a.masse_totale_kg, 1)} kg, ρ moyen {_fr(a.rho_moyen, 3)}"
        )
    else:
        lignes.append(
            f"  détail (mal séparé, à ne pas citer seul) : CdA {_fr(a.cda_m2, 3)} m²"
            f"{_incertitude(a.incertitudes.cda, 3)}, Crr {_fr(a.crr, 5)}"
            f"{_incertitude(a.incertitudes.crr, 5)}, masse {_fr(a.masse_totale_kg, 1)} kg, "
            f"ρ moyen {_fr(a.rho_moyen, 3)}"
        )
    lignes.append(
        f"  première passe (avec les sorties en groupe) : CdA {_fr(rapport.passe1.cda_m2, 3)}, "
        f"Crr {_fr(rapport.passe1.crr, 5)}"
    )
    if a.crr_fixe:
        lignes.append(
            f"  CdA cherché sur le temps de {rapport.n_solo} sortie(s) d'apprentissage à moins "
            f"de {rapport.part_groupe_max:.0%} de signal de groupe"
        )
    if rapport.repli_solo:
        lignes.append(f"  ⚠ {rapport.repli_solo}")
    for borne in a.bornes_atteintes:
        lignes.append(f"  ⚠ borne atteinte : {borne} — la vraie valeur est probablement au-delà")
    for avertissement in a.avertissements:
        lignes.append(f"  ⚠ {avertissement}")
    if rapport.groupes:
        lignes.append(f"  {len(rapport.groupes)} sortie(s) écartée(s) au résidu (« groupe ») :")
        for nom, part in rapport.groupes:
            lignes.append(f"    {part:.0%} de la distance trop rapide — {nom}")

    lignes.append("")
    lignes.append(f"Validation : {v.n} sortie(s) les plus récentes, jamais vues par l'ajustement")
    if v.n:
        lignes.append(
            f"  erreur de temps en mouvement : MAE {_pourcent(v.mae)}  "
            f"médiane {_pourcent(v.mediane)}  biais {_pourcent(v.biais, signe=True)}"
        )
        lignes.append(f"  {'jour':<12}{'km':>7}{'réel':>9}{'simulé':>9}{'écart':>9}  nom")
        for sortie in sorted(v.sorties, key=lambda s: abs(s.erreur_relative), reverse=True):
            lignes.append(
                f"  {sortie.jour or '?':<12}{sortie.distance_m / 1000:>7.1f}"
                f"{_duree(sortie.temps_reel_s):>9}{_duree(sortie.temps_simule_s):>9}"
                f"{sortie.erreur_relative * 100:>+8.1f}%  {sortie.nom[:40]}"
            )
    if rapport.groupes_en_validation:
        lignes.append(
            f"  dont {len(rapport.groupes_en_validation)} sortie(s) que le même critère "
            "désigne comme « groupe » — elles restent comptées dans l'erreur :"
        )
        for nom, part in rapport.groupes_en_validation:
            lignes.append(f"    {part:.0%} de la distance trop rapide — {nom}")
    lignes.append("")
    lignes.extend(_lignes_porte_a_porte(rapport.porte_a_porte))
    lignes.append("")
    lignes.append(
        "Le temps simulé est un temps **en mouvement** : ni les arrêts, ni les "
        "redémarrages n'y sont modélisés — la fourchette du porte à porte les ajoute."
    )
    lignes.append(f"Écrit dans {fichier}")
    return "\n".join(lignes)


def _crr_texte(crr_source: str, velo: Velo) -> str:
    """« pneu course_quatre_saisons », « configuration »… — d'où vient un Crr fixé."""
    if crr_source == "pneu":
        pneu = litterature.pour_pneu(velo.pneu)
        return f"pneu {pneu.libelle}, littérature" if pneu is not None else "pneu"
    if crr_source == "usage":
        return f"usage {velo.usage}, littérature — aucun pneu déclaré"
    return crr_source


def _lignes_porte_a_porte(mesure: MesurePorteAPorte) -> list[str]:
    """Le paragraphe « porte à porte » du rapport : la fourchette, ou pourquoi il n'y en a pas."""
    seuil = f"{mesure.seuil_groupe:.0%}"
    centiles = mesure.centiles
    if centiles is None:
        return [
            f"Porte à porte : {mesure.n} sortie(s) de validation roulée(s) seul (moins de "
            f"{seuil} de signal de groupe), il en faut {SORTIES_MIN_FOURCHETTE} — la "
            "fourchette par défaut (convention) reste en vigueur."
        ]
    bas, mediane, haut = centiles
    lignes = [
        f"Porte à porte : temps simulé × {_fr(bas, 3)} à × {_fr(haut, 3)} "
        f"(médiane × {_fr(mediane, 3)}), centiles 25-75 du temps écoulé réel sur le "
        f"temps simulé, {mesure.n} sortie(s) de validation sur {len(mesure.sorties)} à "
        f"moins de {seuil} de signal de groupe"
    ]
    mouvement = mesure.centiles_mouvement
    if mouvement is not None:
        lignes.append(
            f"  sur le seul temps en mouvement : × {_fr(mouvement[0], 3)} à × "
            f"{_fr(mouvement[2], 3)} (médiane × {_fr(mouvement[1], 3)}) — l'erreur du modèle, "
            "arrêts exclus"
        )
    return lignes


def rendre_json_calibration(
    rapport: RapportCalibration,
    velo: Velo,
    *,
    depuis: date,
    fichier: Path,
    archives_appels: int,
    archives_cache: int,
    motifs: dict[str, int],
    n_calibrables: int,
    crr_source: str = "ajuste",
) -> dict:
    a = rapport.ajustement
    v = rapport.validation
    return {
        "velo": velo.nom,
        "depuis": depuis.isoformat(),
        "sorties_calibrables": n_calibrables,
        "sorties_ecartees": motifs,
        "archives": {"appels": archives_appels, "cache": archives_cache},
        "apprentissage": {
            "n_sorties": rapport.n_apprentissage,
            "echantillons": rapport.echantillons,
            "echantillons_retenus": rapport.echantillons_retenus,
            "echantillons_sans_vent": rapport.echantillons_sans_vent,
            "motifs": rapport.motifs,
            "groupes": [{"nom": nom, "part": round(part, 3)} for nom, part in rapport.groupes],
        },
        "ajustement": {
            "cda_m2": a.cda_m2,
            "crr": a.crr,
            "crr_fixe": a.crr_fixe,
            "n_solo": rapport.n_solo,
            "part_groupe_max": rapport.part_groupe_max,
            "repli_solo": rapport.repli_solo or None,
            "crr_source": crr_source,
            "pneu": velo.pneu if crr_source == "pneu" else None,
            "cda_incertitude": a.incertitudes.cda,
            "crr_incertitude": a.incertitudes.crr,
            "masse_totale_kg": a.masse_totale_kg,
            "rho_moyen": a.rho_moyen,
            "n_echantillons": a.n_echantillons,
            "rmse_w": a.rmse_w,
            "mae_w": a.mae_w,
            "resistance": [
                {
                    "v_kmh": vitesse,
                    "force_n": round(force, 2),
                    "puissance_w": round(puissance, 1),
                }
                for vitesse, force, puissance in a.resistances
            ],
            "bornes_atteintes": list(a.bornes_atteintes),
            "avertissements": list(a.avertissements),
        },
        "passe1": {"cda_m2": rapport.passe1.cda_m2, "crr": rapport.passe1.crr},
        "validation": {
            "n": v.n,
            "mae": v.mae,
            "mediane": v.mediane,
            "biais": v.biais,
            "groupes": [
                {"nom": nom, "part": round(part, 3)} for nom, part in rapport.groupes_en_validation
            ],
            "sorties": [
                {
                    "jour": s.jour or None,
                    "nom": s.nom,
                    "distance_km": round(s.distance_m / 1000, 2),
                    "temps_reel_s": round(s.temps_reel_s),
                    "temps_simule_s": round(s.temps_simule_s),
                    "erreur_relative": round(s.erreur_relative, 4),
                }
                for s in v.sorties
            ],
        },
        "porte_a_porte": porte_a_porte_json(rapport.porte_a_porte),
        "fichier": str(fichier),
    }


# --- ourouler analyser et simuler ---------------------------------------------


def rendre_texte_analyse(
    simulation: Simulation,
    trace,
    velo: Velo,
    parametres: Parametres,
    provenance: str,
    puissance_w: float,
    *,
    meteo: MeteoTrace | None,
    ecoule: PorteAPorte,
    depart: datetime,
    arrivee_mediane: datetime,
    alerte: str | None,
    meteo_absente,
    panne: str | None,
) -> str:
    lignes = [
        f"Analyse de « {trace.nom} » — {_fr(trace.distance_m / 1000, 1)} km"
        + (f", D+ {trace.denivele_m:.0f} m" if trace.denivele_m is not None else ""),
        f"Vélo {velo.nom} — CdA {_fr(parametres.cda_m2, 3)} m², Crr {_fr(parametres.crr, 5)}, "
        f"{_fr(parametres.masse_totale_kg, 1)} kg ({provenance}), ρ {_fr(parametres.rho, 3)}",
        f"Puissance tenue : {puissance_w:.0f} W",
        "",
    ]
    mention = MENTION_MODELE_LITTERATURE if provenance == "littérature" else MENTION_MODELE
    lignes.append(
        f"Temps en mouvement : {_duree(simulation.temps_s)} "
        f"({_fr(simulation.vitesse_moy_kmh, 1)} km/h de moyenne) {mention}"
    )
    source = (
        "mesurée sur vos sorties" if ecoule.provenance == "mesure" else "convention par défaut"
    )
    lignes.append(
        f"Porte à porte : {_duree(ecoule.bas_s)} à {_duree(ecoule.haut_s)} "
        f"({source}) — arrivée vers {arrivee_mediane.strftime('%d/%m %H:%M')}"
    )
    if panne is not None:
        lignes.append(f"Météo indisponible ({panne}) : durée rendue sans météo.")
    elif meteo_absente is not None:
        lignes.append(f"{meteo_absente.message} : durée rendue sans météo.")
    elif meteo is not None:
        lignes.append(
            f"Vent : face sur {meteo.part_vent_face:.0%} des échantillons "
            f"({meteo.n_vent_connu}/{len(meteo.echantillons)} connus), "
            f"pluie cumulée {_fr(meteo.pluie_cumulee_mm, 1)} mm"
            + (" (sur la partie prévue)" if _debut_au_dela(meteo) is not None else "")
        )
        if meteo.repli and meteo.bascule_dist_m is not None:
            lignes.append(
                f"  au-delà du km {meteo.bascule_dist_m / 1000:.0f}, la prévision vient du "
                "second modèle (portée horaire du principal dépassée)"
            )
        debut_au_dela = _debut_au_dela(meteo)
        if debut_au_dela is not None:
            lignes.append(
                f"  à partir du km {debut_au_dela / 1000:.0f} : au-delà de la prévision, "
                "pas de météo"
            )
        lignes.append(
            "  (heures de passage estimées porte à porte, arrêts compris)"
        )
    if alerte:
        lignes.append(alerte)
    return "\n".join(lignes)


def rendre_json_analyse(
    simulation: Simulation,
    trace,
    velo: Velo,
    parametres: Parametres,
    provenance: str,
    puissance_w: float,
    *,
    meteo: MeteoTrace | None,
    ecoule: PorteAPorte,
    depart: datetime,
    arrivee_bas: datetime,
    arrivee_mediane: datetime,
    arrivee_haut: datetime,
    alerte: str | None,
    meteo_absente,
    fourchette: FourchettePorteAPorte,
    panne: str | None,
    avertissements_trace: list[str],
    vitesse_a_vent_nul_kmh: float,
) -> dict:
    return {
        "nom": trace.nom,
        "distance_km": round(trace.distance_m / 1000.0, 3),
        "denivele_m": trace.denivele_m,
        "velo": velo.nom,
        "parametres": {
            "cda_m2": parametres.cda_m2,
            "crr": parametres.crr,
            "masse_totale_kg": parametres.masse_totale_kg,
            "rendement": parametres.rendement,
            "rho": parametres.rho,
            "provenance": provenance,
            "alerte": alerte,
            "litterature": litterature_json(provenance, velo.usage),
        },
        "puissance_w": puissance_w,
        "depart": depart.isoformat(),
        "temps_estime_s": round(simulation.temps_s),
        "vitesse_moy_kmh": round(simulation.vitesse_moy_kmh, 2),
        "pas_plafonnes": simulation.pas_plafonnes,
        "pas_bloques": simulation.pas_bloques,
        # Le porte à porte en fourchette (L9.1) — jamais un seul chiffre, la
        # provenance dit si elle vient des sorties de ce vélo ou d'une
        # convention (règle absolue 5). Même trio de champs que les
        # candidates de `boucle` (`temps_ecoule_s`/`_bas_s`/`_haut_s`).
        "temps_ecoule_s": round(ecoule.mediane_s),
        "temps_ecoule_bas_s": round(ecoule.bas_s),
        "temps_ecoule_haut_s": round(ecoule.haut_s),
        "temps_ecoule_source": ecoule.provenance,
        "heure_arrivee": arrivee_mediane.isoformat(),
        "heure_arrivee_bas": arrivee_bas.isoformat(),
        "heure_arrivee_haut": arrivee_haut.isoformat(),
        # La fourchette elle-même, pour le dépliant « d'où viennent ces
        # chiffres » : sa médiane date aussi les échantillons météo.
        "porte_a_porte": {
            "bas": fourchette.bas,
            "mediane": fourchette.mediane,
            "haut": fourchette.haut,
            "provenance": fourchette.provenance,
            "n": fourchette.n,
        },
        # La vitesse qui a daté les échantillons météo, divisée par la
        # médiane ci-dessus : à vent nul (le vent attendu dépend de l'heure,
        # qui dépend du vent — second ordre, voir `_vitesse_a_vent_nul`).
        "vitesse_a_vent_nul_kmh": round(vitesse_a_vent_nul_kmh, 3),
        "meteo_absente": None if meteo_absente is None else meteo_absente.json(),
        # La panne Open-Meteo, dite à part : l'API rembourse la consultation
        # quand aucune météo n'a été rendue.
        "meteo_panne": panne,
        "avertissements_trace": avertissements_trace,
        "meteo": _meteo_json_analyse(meteo),
        # Même forme que `boucle._candidate_json["trace"]` (F0.1) : `points`
        # pour la carte, `profil` pour la courbe d'altitude — le front
        # réutilise `Carte`/`ProfilAltitude` sans rien réécrire.
        "trace": geometrie_json(trace),
    }


def _meteo_json_analyse(meteo: MeteoTrace | None) -> dict | None:
    """Même forme que `boucle.commande._meteo_json` (candidate d'une boucle) : un front qui
    sait déjà lire `candidate.meteo` (flèches de vent, échantillons) lit celui-ci sans
    code neuf. Dupliquée plutôt qu'importée depuis `boucle.commande` : c'est de la mise en
    forme de données déjà calculées par `MeteoTrace`/`fleches_vent`, pas une deuxième
    implémentation du calcul météo — la même règle que `boucle.commande._meteo_json`
    documente pour elle-même.
    """
    if meteo is None:
        return None
    return {
        "pluie_cumulee_mm": round(meteo.pluie_cumulee_mm, 3),
        "minutes_pluie": round(meteo.minutes_pluie, 1),
        "part_vent_face": round(meteo.part_vent_face, 3),
        "part_vent_dos": round(meteo.part_vent_dos, 3),
        "n_vent_connu": meteo.n_vent_connu,
        "n_echantillons": len(meteo.echantillons),
        "ressenti_min_c": meteo.ressenti_min_c,
        "confiance": meteo.confiance,
        "modele_utilise": meteo.modele_utilise,
        "repli": meteo.repli,
        "bascule_dist_m": (
            None if meteo.bascule_dist_m is None else round(meteo.bascule_dist_m, 1)
        ),
        # Le premier kilomètre (en mètres) passé **au-delà de la prévision** —
        # `None` si tout le parcours est couvert.
        "au_dela_prevision_dist_m": _debut_au_dela(meteo),
        "fleches_vent": fleches_vent(meteo),
        "echantillons": [
            {
                "dist_m": round(e.dist_m, 1),
                "t": e.t.isoformat(),
                "cap_deg": round(e.cap_deg, 1),
                "pluie_mm": e.pluie_mm,
                "vent_kmh": e.vent_kmh,
                "vent_relatif": e.vent_relatif,
                "ressenti_c": e.ressenti_c,
                "modele": e.modele,
                "au_dela_prevision": e.au_dela_prevision,
            }
            for e in meteo.echantillons
        ],
    }


def _debut_au_dela(meteo: MeteoTrace) -> float | None:
    """La distance du premier échantillon au-delà de la prévision, ou `None`."""
    for e in meteo.echantillons:
        if e.au_dela_prevision:
            return round(e.dist_m, 1)
    return None


def rendre_texte_simulation(
    simulation: Simulation,
    trace,
    velo: Velo,
    parametres: Parametres,
    provenance: str,
    puissance_w: float,
    *,
    meteo,
    pauses: Sequence[Pause] = (),
    arrivee: datetime | None = None,
    alerte: str | None = None,
) -> str:
    lignes = [
        f"Simulation de « {trace.nom} » — {_fr(simulation.distance_m / 1000, 1)} km"
        + (f", D+ {trace.denivele_m:.0f} m" if trace.denivele_m is not None else ""),
        f"Vélo {velo.nom} — CdA {_fr(parametres.cda_m2, 3)} m², Crr {_fr(parametres.crr, 5)}, "
        f"{_fr(parametres.masse_totale_kg, 1)} kg ({provenance}), ρ {_fr(parametres.rho, 3)}",
        f"Puissance tenue : {puissance_w:.0f} W",
    ]
    if meteo is not None:
        lignes.append(
            f"Vent prévu : face sur {meteo.part_vent_face:.0%} des échantillons "
            f"({meteo.n_vent_connu}/{len(meteo.echantillons)} connus)"
        )
    lignes.append("")
    mention = MENTION_MODELE_LITTERATURE if provenance == "littérature" else MENTION_MODELE
    lignes.append(
        f"Temps en mouvement : {_duree(simulation.temps_s)} "
        f"({_fr(simulation.vitesse_moy_kmh, 1)} km/h de moyenne) {mention}"
    )
    if simulation.pas_plafonnes:
        lignes.append(
            f"  {simulation.pas_plafonnes} pas de 100 m plafonnés à 60 km/h en descente"
        )
    if simulation.pas_bloques:
        lignes.append(
            f"  {simulation.pas_bloques} pas où la vitesse calculée est sous 0,5 m/s "
            "(temps plancher, pas une mesure)"
        )
    lignes.append(
        "Les arrêts ne sont pas modélisés : feux, stops et ravitaillements s'ajoutent à ce temps."
    )
    if pauses:
        total = sum(p.duree_s for p in pauses)
        lignes.append(
            f"Pauses déclarées : {len(pauses)}, {_duree(total)} au total — s'ajoutent "
            "par-dessus le temps en mouvement, pas confondues avec les arrêts ci-dessus."
        )
        if arrivee is not None:
            from ourouler.meteo.rapport import date_en_francais

            lignes.append(f"Arrivée estimée : {date_en_francais(arrivee)}.")
    if alerte:
        lignes.append(f"⚠ Calibration du {velo.nom} : {alerte} (`ourouler calibrer --velo {velo.nom}`).")
    if provenance != "calibration":
        lignes.append(
            f"CdA et Crr viennent de la {provenance} et n'ont pas été mesurés : "
            f"lancer `ourouler calibrer --velo {velo.nom}`."
        )
        lignes.extend(lignes_litterature(provenance, velo.usage))
    return "\n".join(lignes)


def lignes_litterature(provenance: str, usage: str) -> list[str]:
    """Ce que vaut le jeu générique servi, en clair. Vide si rien de générique.

    Règle absolue 5 : un temps calculé sur des valeurs jamais mesurées le dit,
    et dit **de combien il dérive** là où la dérive a pu être mesurée. Le
    chiffre vient de `physique.litterature`, qui le tient de la campagne du
    17/09/2026 sur les 34 sorties de validation du mainteneur — un cycliste,
    deux vélos.
    """
    if provenance != "littérature":
        return []
    choix = litterature.pour_usage(usage)
    if choix is None:  # pragma: no cover - la provenance vient justement de la table
        return []
    return [f"Catégorie {choix.resume}"]


def litterature_json(provenance: str, usage: str) -> dict | None:
    """Le bloc « littérature » du JSON, ou `None` si le modèle n'en vient pas.

    Même contenu que `lignes_litterature`, pour un appelant qui met en forme
    lui-même : le front doit pouvoir écrire sa propre phrase sans réapprendre
    d'où sortent les chiffres.
    """
    if provenance != "littérature":
        return None
    choix = litterature.pour_usage(usage)
    if choix is None:  # pragma: no cover - la provenance vient justement de la table
        return None
    return {
        "usage": choix.usage,
        "jeu": choix.jeu.nom,
        "source": choix.jeu.source,
        "mesure_sur": choix.mesure_sur,
        "derive_min_2h": choix.derive_min_2h,
        "f27_jeu_n": choix.f27_jeu_n,
        "f27_reference_n": choix.f27_reference_n,
        "mesuree": False,
    }


def rendre_json_simulation(
    simulation: Simulation,
    trace,
    velo: Velo,
    parametres: Parametres,
    provenance: str,
    puissance_w: float,
    *,
    meteo,
    pauses: Sequence[Pause] = (),
    arrivee: datetime | None = None,
    alerte: str | None = None,
) -> dict:
    return {
        "trace": trace.nom,
        "distance_m": round(simulation.distance_m, 1),
        "denivele_m": trace.denivele_m,
        "velo": velo.nom,
        "parametres": {
            "cda_m2": parametres.cda_m2,
            "crr": parametres.crr,
            "masse_totale_kg": parametres.masse_totale_kg,
            "rendement": parametres.rendement,
            "rho": parametres.rho,
            "provenance": provenance,
            "alerte": alerte,
            "litterature": litterature_json(provenance, velo.usage),
        },
        "puissance_w": puissance_w,
        "temps_mouvement_s": round(simulation.temps_s),
        "vitesse_moy_kmh": round(simulation.vitesse_moy_kmh, 2),
        "pas_plafonnes": simulation.pas_plafonnes,
        "pas_bloques": simulation.pas_bloques,
        "vent": None
        if meteo is None
        else {
            "part_vent_face": round(meteo.part_vent_face, 3),
            "n_vent_connu": meteo.n_vent_connu,
            "n_echantillons": len(meteo.echantillons),
        },
        "arrets_modelises": False,
        # Les pauses telles que déclarées (`--pause`), et l'heure d'arrivée
        # qui en tient compte — `null` sans `--heure-depart` (rien à dater).
        "pauses": [
            {"km": round(p.dist_m / 1000.0, 3), "duree_s": round(p.duree_s)} for p in pauses
        ],
        "heure_arrivee": arrivee.isoformat() if arrivee is not None else None,
    }


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


# --- petits rendus ------------------------------------------------------------


def _fr(valeur: float, decimales: int) -> str:
    """Un nombre à la française : virgule décimale."""
    return f"{valeur:.{decimales}f}".replace(".", ",")


def _incertitude(valeur: float | None, decimales: int) -> str:
    return "" if valeur is None else f" ± {_fr(valeur, decimales)}"


def _pourcent(valeur: float | None, *, signe: bool = False) -> str:
    if valeur is None:
        return "—"
    texte = f"{valeur * 100:{'+' if signe else ''}.1f}"
    return texte.replace(".", ",") + " %"


def _duree(secondes: float) -> str:
    """« 2:14 » — heures et minutes."""
    minutes = round(secondes / 60)
    return f"{minutes // 60}:{minutes % 60:02d}"
