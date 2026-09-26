"""Le JSON de `ourouler sortie` : le contrat que lit le front.

Sorti de `rendu/sortie.py`, qui réexporte `rendre_json`. Mêmes règles que
lui : aucun fichier, aucune configuration, aucune horloge ; la forme est
figée par `tests/caracterisation` et `tests/api/test_contrat_openapi.py`.
"""

from __future__ import annotations

from ourouler.boucle.geometrie import geometrie_json
from ourouler.boucle.meteo_trace import fleches_vent, vent_par_position
from ourouler.rendu.boucle import porte_a_porte
from ourouler.seance.placement import Emplacement
from ourouler.sortie import contraste, orientation, vent_demande
from ourouler.sortie.commande import (
    NOTE_BLOC_BIEN_PLACE,
    Proposition,
    _Contexte,
)


def _modele_meteo_json(propositions: list[Proposition]) -> dict | None:
    """L'équivalent JSON de `_ligne_modele_meteo` : même donnée, forme structurée."""
    meteo = next((p.meteo for p in propositions if p.meteo is not None), None)
    if meteo is None or not meteo.modele_utilise:
        return None
    return {"utilise": meteo.modele_utilise, "repli": meteo.repli}


# --- rendu JSON ----------------------------------------------------------------


def rendre_json(propositions: list[Proposition], contexte: _Contexte) -> dict:
    seance, demande = contexte.seance, contexte.demande
    # La troisième valeur de l'écran de FTP (18/09/2026), même bloc que
    # `boucle.rendre_json`, lu par la commande — voir `_candidate_json` pour
    # son usage dans `temps_ecoule_s`.
    compteur_info = contexte.compteur_info
    return {
        "jour": seance.jour.isoformat(),
        "seance": {
            "nom": seance.nom,
            "duree_s": round(seance.duree_s),
            "n_etapes": len(seance.etapes),
            "n_blocs": len(seance.blocs()),
            "meta": seance.meta,
        },
        "demande": {
            "distance_km": contexte.distance_km,
            "distance_source": contexte.distance_source,
            "direction": demande.direction or None,
            "azimut_deg": demande.azimut_deg,
            "candidates": demande.nb_candidates,
            "profil": demande.profil,
            "depart": demande.depart.isoformat(),
            # Le **lieu** d'où part cette sortie, en regard de l'heure
            # ci-dessus. Il vaut celui de la configuration, sauf si l'appelant
            # en a fourni un autre (`--adresse-depart`, demain une requête
            # d'API) : sans cette clé, deux réponses JSON identiques
            # décriraient deux parcours partant de deux endroits différents.
            "lieu_depart": {
                "nom": contexte.config.depart.nom,
                "latitude": contexte.config.depart.latitude,
                "longitude": contexte.config.depart.longitude,
            },
            "velo": demande.velo,
        },
        # `null` si la configuration ne porte aucun vélo — en pratique cela
        # n'arrive pas pour `sortie` (`_parametres` lève avant), sauf appel
        # direct de `rendre_json` en test avec une `Config` construite à la
        # main.
        "compteur": compteur_info,
        "modele_physique": contexte.provenance_modele,
        # Q19 : le modèle météo qui a effectivement répondu, et si c'est un
        # repli sur le second avis (le principal ne couvrait pas la
        # fenêtre) — `None` quand aucune candidate n'a de météo (panne).
        "modele_meteo": _modele_meteo_json(propositions),
        # Q40 (a) : l'état « pas de météo », dit une fois et en toutes lettres,
        # au lieu d'un 502 « service en panne » pour une demande simplement
        # hors de portée. `null` quand la météo a répondu. La phrase dit quel
        # est le dernier jour couvert, jamais pourquoi celui-ci ne l'est pas —
        # Open-Meteo rend le même bloc vide dans les deux cas, et le cœur ne
        # tranche pas (règle absolue 5).
        "meteo_absente": (
            None if contexte.meteo_absente is None else contexte.meteo_absente.json()
        ),
        "seuil_bloc_bien_place": NOTE_BLOC_BIEN_PLACE,
        # Écart relatif de note en dessous duquel la pluie départage plutôt que
        # le vent (préférence du cycliste, `config.seance.tolerance_egalite`) :
        # publié pour que le rang des candidates dans `candidates` s'explique
        # sans relire la configuration.
        "tolerance_egalite": contexte.config.seance.tolerance_egalite,
        "gpx": str(contexte.gpx) if contexte.gpx is not None else None,
        "carte": str(contexte.carte) if contexte.carte is not None else None,
        # Lot F2.4 : `etape` dit **où** la candidate est tombée, et `trace` la
        # dessine quand elle existe. Un azimut et une distance ne se dessinent
        # pas : c'est ce qui manquait pour que « 8 candidate(s) écartée(s) »
        # soit autre chose qu'une ligne de texte.
        "ecartees": [
            {
                "azimut_deg": e.azimut_deg,
                "distance_km": round(e.distance_km, 3),
                "motif": e.motif,
                "etape": e.etape,
                "trace": None if e.trace is None else geometrie_json(e.trace),
            }
            for e in contexte.ecartees
        ],
        "tenue": None
        if contexte.tenue is None
        else {
            "categorie_temp": contexte.tenue.categorie_temp,
            "categorie_humidite": contexte.tenue.categorie_humidite,
            "base": contexte.tenue.base,
            "a_emporter": contexte.tenue.a_emporter,
            "a_enlever": contexte.tenue.a_enlever,
            "motifs": contexte.tenue.motifs,
        },
        # Les clés du lot L5.3. `propositions` est le sous-ensemble contrasté
        # de `candidates` : mêmes objets, repérés par `numero`, avec la phrase
        # qui les distingue. `candidates` reste la liste complète et
        # inchangée — un script qui la lisait continue de marcher.
        "propositions": _propositions_json(contexte),
        "question_vent": _question_vent_json(contexte),
        "motif_deux_propositions": (
            contexte.selection.motif_deux_propositions if contexte.selection else None
        ),
        # Le pendant de la clé précédente (Q45) : quand aucune proposition ne
        # se détache, on le dit au lieu de fabriquer une différence. Les deux
        # peuvent être remplies en même temps — deux boucles qui vont ailleurs
        # et qui se valent.
        "motif_equivalence": (
            contexte.selection.motif_equivalence if contexte.selection else None
        ),
        # Lot F2.4 : ce que le contraste a décidé de **chaque** candidate, et
        # par quelle paire. Le produit montrait ce qu'il retenait, jamais ce
        # qu'il jetait ni pourquoi — et c'est au contraste que les candidates
        # du mainteneur disparaissaient.
        "arbitrage": _arbitrage_json(contexte),
        "candidates": [_candidate_json(p, compteur_info) for p in propositions],
    }


def _arbitrage_json(contexte: _Contexte) -> dict | None:
    """Le sort de toutes les candidates au contraste, la matrice, et ce qu'elle mesure.

    `paires` porte **toutes** les paires, pas seulement celles des retenues :
    c'est la matrice complète qui montre qu'une seule case au-dessus du seuil
    interdit tout groupe contenant ses deux boucles. Sans elle, un lecteur
    verrait des verdicts sans pouvoir refaire le raisonnement.

    Aucun pourcentage n'est laissé à calculer en aval : `motif` et `phrase`
    sont écrits par `sortie.contraste`, dans les termes qui décident vraiment.
    """
    selection = contexte.selection
    if selection is None:
        return None
    return {
        "seuil_recouvrement": selection.seuil_recouvrement,
        "candidates": [
            {
                "numero": v.numero,
                "sort": v.sort,
                "recouvrement_max": (
                    None if v.recouvrement_max is None else round(v.recouvrement_max, 4)
                ),
                "contre_numero": v.contre_numero,
                "motif": v.motif,
            }
            for v in selection.verdicts
        ],
        "paires": [
            {
                "a": i + 1,
                "b": j + 1,
                "recouvrement": round(part, 4),
                "au_dessus_du_seuil": part > selection.seuil_recouvrement,
            }
            for (i, j), part in sorted(selection.recouvrements_candidates.items())
        ],
        "essais": (
            None
            if selection.essais is None
            else {
                "taille": selection.essais.taille,
                "essayes": selection.essais.essayes,
                "valides": selection.essais.valides,
                "refuses_par_une_paire": selection.essais.refuses_par_une_paire,
            }
        ),
        "phrase": selection.phrase_arbitrage,
    }


def _propositions_json(contexte: _Contexte) -> list[dict]:
    """Les deux ou trois propositions contrastées, dans l'ordre du tri.

    `distinction` porte la phrase en langage de cycliste, `axe_distinctif`
    l'axe qui la motive. `recouvrement_max_avec` dit, pour chaque autre
    proposition, la part de routes communes — c'est le critère qui garantit
    que deux propositions ne se ressemblent pas sur la carte.
    """
    selection = contexte.selection
    if selection is None:
        return []
    par_paire = selection.recouvrements
    sortie = []
    for i, retenue in enumerate(selection.retenues):
        profil = retenue.profil
        sortie.append(
            {
                "numero": retenue.proposition.numero,
                "retenue": i == 0,
                "distinction": retenue.distinction,
                # L'axe de base, sans son orientation : un consommateur lit « vent »,
                # pas « vent:travers » — l'orientation est déjà sous
                # `orientation_vent`.
                "axe_distinctif": (
                    contraste.axe_de_base(retenue.axe_distinctif)
                    if retenue.axe_distinctif
                    else None
                ),
                "duree_s": round(profil.duree_s),
                # Signé : positif = on rentre plus tard (normal), négatif = la
                # séance est amputée (pas normal). L'axe de contraste, lui,
                # compare la valeur absolue — voir `contraste.PAS_DUREE_S`.
                "depassement_seance_s": (
                    None if profil.depassement_s is None else round(profil.depassement_s)
                ),
                "demi_tours": profil.demi_tours,
                "pluie_mm": (None if profil.pluie_mm is None else round(profil.pluie_mm, 3)),
                # `None` et jamais `0.0` : un tracé sans tag de nœud ne prouve
                # pas qu'il n'y a pas de feu (règle absolue 5), et l'ignorance
                # n'est jamais un malus (contrat du sprint 3).
                "densite_marqueurs_km": (
                    None
                    if profil.densite_marqueurs_km is None
                    else round(profil.densite_marqueurs_km, 3)
                ),
                # **Les entiers, et pas seulement la densité** (ajouté le
                # 17/09/2026). `contraste.Profil` les porte depuis le sprint 3
                # — « affiché tel quel : 28 feux, 20 stops » — mais seule la
                # densité sortait en JSON, si bien que le front les retrouvait
                # en multipliant par la distance : exactement le geste que le
                # commentaire de `contraste.py` nomme comme le piège à éviter.
                # La densité est arrondie à trois décimales, donc ce produit
                # s'efface au-delà de 100 km (relecture F2 · C1). Les rendre
                # supprime la seule arithmétique du front.
                "feux": profil.feux,
                "stops": profil.stops,
                "part_trafic": (
                    None if profil.part_trafic is None else round(profil.part_trafic, 4)
                ),
                "orientation_vent": profil.orientation,
                "note_terrain": round(profil.note_terrain, 4),
                "recouvrement_max_avec": {
                    str(selection.retenues[j].proposition.numero): round(part, 4)
                    for (a, b), part in par_paire.items()
                    for j in ((b,) if a == i else (a,) if b == i else ())
                },
            }
        )
    return sortie


def _question_vent_json(contexte: _Contexte) -> dict | None:
    """Ce que le vent au départ permettait de demander, et ce qui a été demandé."""
    question = contexte.question_vent
    if question is None:
        return None
    return {
        "posee": question.posee,
        "motif": question.motif or None,
        "vent_kmh": question.vent_kmh,
        "vent_depuis_deg": question.vent_depuis_deg,
        "seuil_kmh": vent_demande.SEUIL_VENT_SENSIBLE_KMH,
        "horizon_jours": vent_demande.HORIZON_ORIENTATION_J,
        "reponse": contexte.demande.vent,
        # Pluriel depuis Q44 : « de travers » en ouvre deux, opposés. Le
        # singulier `azimut_recherche_deg` disparaît plutôt que de coexister —
        # un consommateur qui l'aurait lu aurait cru à un seul azimut exploré.
        "azimuts_recherche_deg": list(question.azimuts_pour(contexte.demande.vent)),
        "choix": list(orientation.CHOIX),
        "azimuts_par_choix": {
            choix: list(question.azimuts_pour(choix)) for choix in orientation.CHOIX
        },
    }


def _emplacement_json(e: Emplacement) -> dict:
    """Un emplacement en JSON — `note` et le reste de `NoteBloc` à `None` sans bloc.

    Q13, lot L5.2 : un `0.0` à la place de `None` se lirait, par un script
    comme par un humain, comme un couloir parfait — c'est précisément le
    défaut que le contrat §2.2 a) interdit.

    `debut_parcouru_m` est le compteur kilométrique (ne recule jamais) ;
    `debut_m` reste la position sur le tracé (recule après un demi-tour). Un
    script qui veut afficher un kilomètre lit le premier, pas le second.
    """
    base = {
        "etape_idx": e.etape_idx,
        "debut_m": round(e.debut_m, 1),
        "debut_parcouru_m": round(e.debut_parcouru_m, 1),
        "longueur_m": round(e.longueur_m, 1),
        "demi_tour": e.demi_tour,
    }
    if e.note is None:
        return base | {
            "note": None,
            "motifs": None,
            "pente_moyenne": None,
            "pente_max": None,
            "carrefours": None,
            "km_batis": None,
            "descente_m": None,
            "montee_m": None,
        }
    return base | {
        "note": round(e.note.note, 4),
        "motifs": e.note.motifs,
        "pente_moyenne": round(e.note.pente_moyenne, 5),
        "pente_max": round(e.note.pente_max, 5),
        "carrefours": e.note.carrefours,
        "km_batis": round(e.note.km_batis, 3),
        "descente_m": round(e.note.descente_m, 1),
        "montee_m": round(e.note.montee_m, 1),
    }


def _candidate_json(proposition: Proposition, compteur_info: dict | None = None) -> dict:
    trace, placement, meteo = proposition.trace, proposition.placement, proposition.meteo
    temps_ecoule_s = temps_ecoule_bas_s = temps_ecoule_haut_s = temps_ecoule_source = None
    if compteur_info is not None:
        pp = porte_a_porte(placement.duree_totale_s, compteur_info)
        temps_ecoule_s = round(pp.mediane_s)
        temps_ecoule_bas_s, temps_ecoule_haut_s = round(pp.bas_s), round(pp.haut_s)
        temps_ecoule_source = pp.provenance
    return {
        "numero": proposition.numero,
        "retenue": proposition.numero == 1,
        "nom": trace.nom,
        "distance_km": round(trace.distance_m / 1000.0, 3),
        "denivele_m": trace.denivele_m,
        "azimut_deg": proposition.azimut_deg,
        "ecart_relatif": proposition.ecart_relatif,
        # L'écart à la distance demandée cesse d'être tu (Q41 d).
        "hors_tolerance": bool(proposition.elargissement),
        "elargissement": proposition.elargissement,
        "tolerance_distance": proposition.tolerance_distance,
        "part_connue": proposition.part_connue,
        "vitesse_kmh": round(proposition.vitesse_kmh, 2),
        # Le porte à porte, arrêts compris. **Au niveau de la candidate, et
        # non dans `placement`** (déplacé le 18/09/2026) : le voisinage de
        # `duree_totale_s`, son analogue en mouvement, était tentant, mais le
        # temps écoulé est une propriété du *parcours*, pas du placement de
        # la séance dessus — et `boucle` le publie déjà à ce niveau-là. Un
        # même chiffre à deux adresses selon la route obligeait le front à
        # connaître deux chemins pour un seul composant, et le second était
        # tombé silencieusement : aucune erreur, juste un chiffre manquant.
        # Depuis L9.1, une fourchette (`physique.modele.temps_ecoule`) :
        # `temps_ecoule_s` en est la médiane, `_bas_s`/`_haut_s` les bornes,
        # la source « mesure » ou « defaut ». `null` avec `compteur` : sans
        # vélo, pas de fourchette.
        "temps_ecoule_s": temps_ecoule_s,
        "temps_ecoule_bas_s": temps_ecoule_bas_s,
        "temps_ecoule_haut_s": temps_ecoule_haut_s,
        "temps_ecoule_source": temps_ecoule_source,
        "placement": {
            "note_totale": round(placement.note_totale, 4),
            "note_terrain": round(placement.note_terrain, 4),
            "penalite_seance": round(placement.penalite_seance, 4),
            "decalage_z2_s": round(placement.decalage_z2_s),
            "duree_totale_s": round(placement.duree_totale_s),
            "distance_totale_m": round(placement.distance_totale_m, 1),
            # Le D+ du **parcours placé**, recalculé par `denivele_filtre`, à côté
            # du `denivele_m` de la boucle annoncé par le moteur : deux méthodes
            # qui divergent, et la règle absolue 5 demande qu'on le voie.
            "denivele_parcours_m": (
                None
                if proposition.denivele_parcours_m is None
                else round(proposition.denivele_parcours_m, 1)
            ),
            "blocs_bien_places": proposition.blocs_bien_places,
            "demi_tours": proposition.demi_tours,
            "avertissements": placement.avertissements,
            # Ce qui se dit sans être un défaut — le retour au calme qui
            # s'allonge dans sa fenêtre (Q14). Séparé des avertissements
            # parce qu'un script qui compte les défauts ne doit pas le compter.
            "informations": placement.informations,
            # Toutes les étapes de la séance, pas seulement les blocs (Q13, lot
            # L5.2) : `_emplacement_json` met `None`, jamais `0.0`, pour tout ce
            # qu'une récupération n'a pas — un script qui lirait un `0.0` le
            # prendrait pour un couloir parfait.
            "emplacements": [_emplacement_json(e) for e in placement.emplacements],
        },
        "couts": {
            "km_trafic": round(proposition.couts.km_trafic, 3),
            "km_calme": round(proposition.couts.km_calme, 3),
            # Sérialisé le 17/09/2026, comme il l'était déjà côté boucle
            # libre. `km_trafic` et `km_calme` **ne font pas la distance** :
            # le reste est sur des voies que le moteur ne sait pas classer, et
            # sans ce chiffre un tracé à moitié sur des chemins s'annonce
            # « 0,0 km de trafic » comme un tracé parfaitement calme (voir le
            # commentaire du champ dans `boucle.couts.Couts`).
            "km_non_classe": round(proposition.couts.km_non_classe, 3),
            "km_non_revetu": round(proposition.couts.km_non_revetu, 3),
            "score": round(proposition.couts.score, 3),
            "sens": proposition.couts.sens,
        },
        "meteo": None
        if meteo is None
        else {
            "pluie_cumulee_mm": round(meteo.pluie_cumulee_mm, 3),
            "minutes_pluie": round(meteo.minutes_pluie, 1),
            "part_vent_face": round(meteo.part_vent_face, 3),
            "ressenti_min_c": meteo.ressenti_min_c,
            "confiance": meteo.confiance,
            "n_echantillons": len(meteo.echantillons),
            # Les mêmes flèches que la page HTML du sprint 5 dessine, filtrées
            # au même seuil parce que c'est le même code — voir
            # `boucle.meteo_trace.fleches_vent`.
            "fleches_vent": fleches_vent(meteo),
            # Le tracé entier, pour le colorer (lot d'affordance, 20/09/2026) :
            # aucun filtre de sensibilité, voir `boucle.meteo_trace.vent_par_position`.
            "vent_par_position": vent_par_position(meteo),
            "modele_utilise": meteo.modele_utilise,
            "repli": meteo.repli,
        },
        # Lot F0.1 : la géométrie n'existait dans aucun JSON, seulement dans
        # le GPX et le HTML Leaflet (`docs/journal/ux/discovery_donnees.md` §2). Les
        # `debut_m`/`longueur_m` des `emplacements` ci-dessus se raccordent à
        # `trace.profil` par recherche dichotomique sur `dist_m` — voir la
        # docstring de `boucle.geometrie`.
        "trace": geometrie_json(trace),
    }
