"""Le JSON de `ourouler boucle` et les mesures qu'il partage avec le tableau texte.

Sorti de `rendu/boucle.py`, qui importe `porte_a_porte` :
la fourchette porte à porte, la durée des pauses et le modèle météo
réellement utilisé servent aux deux rendus, et vivent ici pour que
`rendu/boucle.py` les importe sans cycle. Aucun fichier, aucune configuration,
aucune horloge ; la forme est figée par `tests/caracterisation`.
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from ourouler.boucle.commande import Demande, Evaluation, ModeleTemps
from ourouler.boucle.geometrie import geometrie_json
from ourouler.boucle.horaire import duree_pauses_s
from ourouler.boucle.marqueurs import Marqueurs
from ourouler.boucle.meteo_trace import MeteoTrace, fleches_vent
from ourouler.meteo import portee
from ourouler.physique.modele import FourchettePorteAPorte, PorteAPorte, temps_ecoule

if TYPE_CHECKING:
    # Même règle que `rendu/boucle.py` : la `Config` est lue, jamais importée
    # à l'exécution.
    from ourouler.config import Config


def _meteo_rendue(evaluations: list[Evaluation]) -> MeteoTrace | None:
    """La première météo réellement obtenue — celle qui sait quel modèle a répondu."""
    return next((e.meteo for e in evaluations if e.meteo is not None), None)


def _modele_meteo_json(evaluations: list[Evaluation]) -> dict | None:
    """L'équivalent JSON de `_ligne_modele_meteo` — `bascule_km` en plus, absent de `sortie`.

    `bascule_km` : `None` sans repli, ou avec un repli total dès le départ
    (`repli` seul le dit déjà) ; sinon le premier kilomètre où le repli a
    pris le relais du modèle principal (repli partiel).
    """
    meteo = _meteo_rendue(evaluations)
    if meteo is None or not meteo.modele_utilise:
        return None
    return {
        "utilise": meteo.modele_utilise,
        "repli": meteo.repli,
        "bascule_km": (round(meteo.bascule_dist_m / 1000.0, 3) if meteo.bascule_dist_m is not None else None),
    }


def _litterature_json(modele: ModeleTemps) -> dict | None:
    """L'équivalent JSON de `_lignes_litterature` — délégué à `rendu.physique`."""
    from ourouler.rendu.physique import litterature_json

    return litterature_json(modele.provenance, modele.usage)


def porte_a_porte(mouvement_s: float, compteur_info: dict) -> PorteAPorte:
    """`temps_ecoule(mouvement_s, fourchette du vélo)` — la fourchette lue dans le bloc compteur.

    **Publique** : `sortie.commande` chronomètre ses propositions de la même
    façon, sans réécrire la lecture du bloc.
    """
    brut = compteur_info["porte_a_porte"]
    fourchette = FourchettePorteAPorte(
        bas=brut["bas"],
        mediane=brut["mediane"],
        haut=brut["haut"],
        provenance=brut["provenance"],
        n=brut.get("n", 0),
    )
    return temps_ecoule(mouvement_s, fourchette)


# --- rendu JSON ----------------------------------------------------------------


def rendre_json(
    evaluations: list[Evaluation],
    demande: Demande,
    config: Config,
    chemin: Path | None,
    modele: ModeleTemps | None = None,
    *,
    poids: dict[str, float] | None = None,
    meteo_absente: portee.MeteoAbsente | None = None,
    compteur_info: dict | None = None,
) -> dict:
    """Toutes les mesures, plus le chemin du GPX écrit."""
    return {
        "depart": {
            "nom": config.depart.nom,
            "latitude": config.depart.latitude,
            "longitude": config.depart.longitude,
            "heure": demande.depart.isoformat(),
        },
        "demande": {
            "distance_km": demande.distance_km,
            "direction": demande.direction or None,
            "azimut_deg": demande.azimut_deg,
            "profil": demande.profil,
            "candidates": demande.nb_candidates,
            "gpx_importe": str(demande.gpx) if demande.gpx is not None else None,
        },
        # Les pauses **telles que déclarées** (`--pause`, répétable) : jamais
        # celles réellement appliquées par candidate (une pause au-delà d'une
        # candidate plus courte que la cible n'y a simplement aucun effet,
        # voir `boucle.horaire`) — ce que l'utilisateur a demandé, pas une
        # réinterprétation par tracé.
        "pauses": [{"km": round(p.dist_m / 1000.0, 3), "duree_s": round(p.duree_s)} for p in demande.pauses],
        # La troisième valeur de l'écran de FTP (`ecran_ftp.info_compteur`),
        # publiée ici pour que `temps_ecoule_s` de chaque candidate se
        # vérifie de tête : `null` sans vélo dans la configuration — pas de
        # modèle physique, pas de facteur, rien à réconcilier.
        "compteur": compteur_info,
        "vitesse_moyenne_kmh": config.boucle.vitesse_moyenne_kmh,
        "sens_prefere": config.boucle.sens,
        "modele": config.meteo.modele,
        "second_avis": config.meteo.second_avis,
        # Ce qui a **répondu**, à côté de ce qui est configuré. Même forme que
        # `sortie` (`{utilise, repli}`), pour qu'un écran lise le repli de
        # modèle de la même façon sur les deux routes de parcours. `null` quand
        # aucune candidate n'a de météo.
        "modele_meteo": _modele_meteo_json(evaluations),
        # L'état « pas de météo », dit une fois. `null` quand la
        # météo a répondu. Voir `meteo.portee`.
        "meteo_absente": None if meteo_absente is None else meteo_absente.json(),
        "gpx": str(chemin) if chemin is not None else None,
        "poids_routes": dict(poids) if poids else None,
        "modele_physique": None
        if modele is None
        else {
            "velo": modele.velo,
            "puissance_w": modele.puissance_w,
            "provenance": modele.provenance,
            "cda_m2": modele.parametres.cda_m2,
            "crr": modele.parametres.crr,
            "masse_totale_kg": modele.parametres.masse_totale_kg,
            # Le même fait qu'en texte, en un booléen et un bloc : un client
            # qui ne lit que `provenance` afficherait un temps de littérature
            # comme un temps mesuré (on ne présente jamais une estimation comme une mesure).
            "mesure": modele.calibre,
            "litterature": _litterature_json(modele),
            "alerte": modele.alerte or None,
        },
        "candidates": [_candidate_json(e, demande, config, chemin, compteur_info) for e in evaluations],
    }


def _candidate_json(
    evaluation: Evaluation,
    demande: Demande,
    config: Config,
    chemin: Path | None,
    compteur_info: dict | None = None,
) -> dict:
    couts, meteo = evaluation.couts, evaluation.meteo
    trace = evaluation.trace
    distance_km = trace.distance_m / 1000.0
    # Identique à l'ancien calcul de `temps_estime_s` (INCHANGÉ) : pas de
    # garde-fou sur `vitesse_moyenne_kmh` ici, `config` la valide déjà
    # strictement positive au chargement. `_temps_mouvement_s`, elle, protège
    # le rendu texte d'une configuration construite à la main (tests).
    mouvement_s = (
        evaluation.temps_s
        if evaluation.temps_s is not None
        else distance_km / config.boucle.vitesse_moyenne_kmh * 3600
    )
    temps_ecoule_s = temps_ecoule_bas_s = temps_ecoule_haut_s = temps_ecoule_source = None
    ecoule_base_s = mouvement_s  # non arrondi : sert à `heure_arrivee`, voir plus bas
    if compteur_info is not None:
        pp = porte_a_porte(mouvement_s, compteur_info)
        temps_ecoule_s = round(pp.mediane_s)
        temps_ecoule_bas_s, temps_ecoule_haut_s = round(pp.bas_s), round(pp.haut_s)
        temps_ecoule_source = pp.provenance
        ecoule_base_s = pp.mediane_s
    # L'heure de la pendule : temps écoulé porte à porte (ou, à défaut, le
    # temps en mouvement) **plus** les pauses déclarées — jamais confondues
    # avec le facteur compteur, qui couvre déjà feux et micro-arrêts (voir
    # `_ligne_pauses`). `ecoule_base_s` **non arrondi** : arrondir à la
    # seconde avant d'ajouter les pauses (`temps_ecoule_s`, arrondi pour
    # l'affichage de cette seule valeur) décalait l'heure affichée d'une
    # minute entière une fois sur deux, une fois formatée à la minute près.
    pauses_s = duree_pauses_s(demande.pauses)
    heure_arrivee = demande.depart + timedelta(seconds=ecoule_base_s + pauses_s)
    return {
        "numero": evaluation.numero,
        "retenue": evaluation.numero == 1 and chemin is not None,
        "nom": trace.nom,
        "distance_km": round(distance_km, 3),
        "denivele_m": trace.denivele_m,
        "denivele_source": trace.meta.get("denivele_source"),
        "temps_estime_s": round(mouvement_s),
        "temps_source": "modele" if evaluation.temps_s is not None else "vitesse_moyenne",
        # Le porte à porte, arrêts compris (`physique.modele.temps_ecoule`) —
        # jamais à la place de `temps_estime_s`, à côté. Une fourchette :
        # `temps_ecoule_s` en est la médiane (gardé pour compatibilité),
        # `_bas_s`/`_haut_s` les bornes (centiles 25 et 75), et la source dit
        # « mesure » (sorties du vélo) ou « defaut » (convention). `null` avec
        # `compteur` : sans vélo, pas de fourchette.
        "temps_ecoule_s": temps_ecoule_s,
        "temps_ecoule_bas_s": temps_ecoule_bas_s,
        "temps_ecoule_haut_s": temps_ecoule_haut_s,
        "temps_ecoule_source": temps_ecoule_source,
        # L'heure d'arrivée annoncée, pauses comprises — voir le commentaire
        # au-dessus du calcul de `heure_arrivee`.
        "heure_arrivee": heure_arrivee.isoformat(),
        "vitesse_meteo_kmh": (
            None if evaluation.vitesse_meteo_kmh is None else round(evaluation.vitesse_meteo_kmh, 2)
        ),
        "azimut_deg": evaluation.azimut_deg,
        "rayon_m": evaluation.rayon_m,
        "ecart_relatif": evaluation.ecart_relatif,
        # L'écart cesse d'être tu : trois champs, pas un commentaire. Un
        # client qui n'affiche que `distance_km` continue de marcher, un
        # client qui veut expliquer a de quoi le faire.
        "hors_tolerance": bool(evaluation.elargissement),
        "elargissement": evaluation.elargissement,
        "tolerance_distance": evaluation.tolerance_distance,
        "total_tri": round(evaluation.total, 3),
        "couts_partiels": bool(trace.meta.get("couts_partiels")),
        "segments_ignores": int(trace.meta.get("segments_ignores") or 0),
        # « retirees » : le tracé proposé n'a plus ces mètres. « detectees » :
        # un GPX importé n'est pas élagué, ils y sont encore.
        "antennes_source": "retirees" if trace.meta.get("antennes") is not None else "detectees",
        "antennes": trace.meta.get("antennes"),
        "distance_source": trace.meta.get("distance_source"),
        # Informatifs, hors score : le coût que le moteur s'attribue à
        # lui-même, et la part de kilomètres déjà roulés.
        "cout_km_moyen": couts.cout_km_moyen,
        "part_connue": evaluation.part_connue,
        "marqueurs": _marqueurs_json(evaluation.marqueurs),
        "km_par_highway": {k: round(v, 3) for k, v in couts.km_par_highway.items()},
        "couts": {
            "km_trafic": round(couts.km_trafic, 3),
            "km_calme": round(couts.km_calme, 3),
            "km_non_classe": round(couts.km_non_classe, 3),
            "km_non_revetu": round(couts.km_non_revetu, 3),
            "antennes_m": round(couts.antennes_m, 1),
            "virages_gauche": couts.virages_gauche,
            "virages_gauche_trafic": couts.virages_gauche_trafic,
            "virages_droite": couts.virages_droite,
            "sens": couts.sens,
            "score": round(couts.score, 3),
        },
        "meteo": _meteo_json(meteo),
        "meta": trace.meta,
        # La géométrie, pour que le front n'ait pas à relire le GPX écrit sur
        # disque. Voir
        # `boucle.geometrie` pour la forme et la simplification appliquée.
        "trace": geometrie_json(trace),
    }


def _marqueurs_json(marqueurs: Marqueurs | None) -> dict | None:
    """Feux, stops et densité de marqueurs — même vocabulaire que `sortie.contraste`.

    `connue` faux (ou `marqueurs` absent) : le tracé ne porte pas de
    `segments`, `feux`/`stops` valent alors `None`, jamais 0 — un GPX qui n'a
    pas pu être rapproché ne dit pas « aucun feu », il dit « je ne sais pas ».
    """
    if marqueurs is None or not marqueurs.connue:
        return {"connue": False, "feux": None, "stops": None, "nombre": None, "par_km": None}
    return {
        "connue": True,
        "feux": marqueurs.par_nature.get("traffic_signals", 0),
        "stops": marqueurs.par_nature.get("stop", 0),
        "nombre": marqueurs.nombre,
        "par_km": round(marqueurs.par_km, 3) if marqueurs.par_km is not None else None,
    }


def _meteo_json(meteo: MeteoTrace | None) -> dict | None:
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
        # Les flèches à dessiner le long du tracé, position comprise, déjà
        # filtrées au seuil où le vent se sent (`meteo_trace.fleches_vent`).
        # C'est **la règle du cœur, pas une liste brute** : un écran qui
        # recevrait tous les échantillons devrait réappliquer le seuil de
        # 8 km/h lui-même, donc le réinventer, donc pouvoir en diverger.
        # Les `echantillons` ci-dessous restent tels quels, sans position :
        # ils servent à autre chose, et les doubler serait du poids pour rien.
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
                # Le modèle qui a renseigné **cet** échantillon précisément —
                # `null` si ni le principal ni le repli ne le couvrent. Voir
                # `_modele_meteo_json` pour le premier kilomètre où ça change.
                "modele": e.modele,
            }
            for e in meteo.echantillons
        ],
    }
