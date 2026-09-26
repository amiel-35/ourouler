"""Ce que `ourouler boucle` montre de ses candidates : le tableau texte et le JSON.

Couche 4 de `docs/ouverture_plan.md` §2 (lot 6). `boucle/commande.py`
cherche, mesure, classe et écrit le GPX ; il passe ici des objets déjà
construits — `Evaluation`, `Demande`, `ModeleTemps`, la `Config` et le bloc
« compteur » — et imprime ce qui en revient. Ce module ne lit ni fichier, ni
configuration, ni environnement, et n'écrit rien : la phrase et la forme du
JSON (le contrat du front) sont tout ce qu'il décide.

`sortie` reprend d'ici le chronométrage porte à porte (`porte_a_porte`,
`ligne_temps_ecoule`, `texte_entre`) et la phrase de l'élargissement
(`lignes_elargissement`), pour dire les mêmes choses avec les mêmes mots.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from ourouler.boucle.commande import TAGS_PROVENANCE_RAPPROCHEMENT, Demande, Evaluation, ModeleTemps
from ourouler.boucle.meteo_trace import MeteoTrace
from ourouler.meteo import portee
from ourouler.meteo.rapport import date_en_francais
from ourouler.noyau.trace import Trace
from ourouler.physique.modele import PorteAPorte
from ourouler.rendu.boucle_json import (
    _duree_pauses_s,
    _meteo_rendue,
    _modele_meteo_json,  # noqa: F401 — réexporté (tests)
    porte_a_porte,
    rendre_json,  # noqa: F401 — réexporté
)

if TYPE_CHECKING:
    # Le rendu lit les champs d'une `Config` déjà chargée ; il n'importe pas,
    # à l'exécution, l'entrée qui la charge (même règle que `rendu/profil.py`).
    from ourouler.config import Config

#: Marque de la ligne retenue dans le tableau texte.
MARQUE_RETENUE = "→"

#: Mention accolée au titre de la colonne « temps » quand il vient du modèle.
MENTION_MODELE = "(modèle)"

#: La même, quand CdA et Crr n'ont pas été mesurés sur ce vélo mais viennent de
#: la table de `physique.litterature`. Deux mots de plus, et ils comptent : le
#: temps est calculé, pas supposé constant, mais il repose sur des valeurs de
#: catégorie (règle absolue 5, même geste que le « supposé » du facteur
#: compteur).
MENTION_MODELE_LITTERATURE = "(modèle, littérature)"

#: Part de kilomètres non classés au-delà de laquelle le tableau le dit. En
#: dessous, c'est le bruit habituel des tronçons de raccordement ; au-delà,
#: « 0,0 km de trafic » ne veut plus dire « tracé calme ».
PART_NON_CLASSE_SIGNALEE = 0.05

#: Les deux libellés de la colonne des antennes. Ils ne disent pas la même
#: chose : une candidate générée est **élaguée**, le tableau compte donc les
#: mètres qu'on lui a retirés et le tracé proposé n'en a plus ; un GPX importé
#: n'est pas touché, le tableau compte les mètres qui y sont **encore**.
#: Afficher le même mot pour les deux ferait croire à un élagage qui n'a pas
#: eu lieu (règle absolue 5).
TITRE_ANTENNES_RETIREES = "antennes retirées"
TITRE_ANTENNES_DETECTEES = "antennes détectées"

#: Ce qu'on affiche à la place d'une mesure absente (jamais un zéro : un
#: GPX importé ne dit rien des routes empruntées, ce n'est pas « 0 km de
#: trafic »).
ABSENT = "—"


def avertissement_meteo(panne: str | None, meteo_absente: portee.MeteoAbsente | None) -> str | None:
    """La ligne de la sortie d'erreur quand la météo manque, ou `None` si elle a répondu.

    La boucle reste servie sans ses colonnes météo : une panne d'Open-Meteo se
    nomme, une date hors de l'horizon dit ce qu'on ne sait pas (Q40 a).
    """
    if panne is not None:
        return (
            f"ourouler : météo indisponible ({panne}) — tableau affiché sans les "
            "colonnes météo, la boucle reste valable"
        )
    if meteo_absente is not None:
        return (
            f"ourouler : {meteo_absente.message} — tableau affiché sans les colonnes météo, "
            "la boucle reste valable"
        )
    return None


# --- rendu texte ---------------------------------------------------------------

#: Colonnes du tableau, dans l'ordre des contrats §6 (sprint 2) et §2
#: (sprint 3). Le second membre nomme la mesure dont la colonne dépend :
#: sans cette mesure, la colonne **disparaît** au lieu d'afficher une colonne
#: de tirets. `None` = toujours affichée.
COLONNES = (
    ("n°", None),
    ("distance", None),
    ("D+", None),
    ("temps", None),  # le titre porte sa provenance, voir `_titres`
    ("trafic", None),
    ("non revêtu", None),
    ("coût profil", "cout"),
    ("virages G", None),
    ("sens", None),
    ("connu %", "connu"),
    (TITRE_ANTENNES_RETIREES, None),  # remplacé par `_titres` pour un GPX importé
    ("feux", "feux"),
    ("pluie", "meteo"),
    ("vent face", "meteo"),
    ("ressenti min", "meteo"),
)


def rendre_texte(
    evaluations: list[Evaluation],
    demande: Demande,
    config: Config,
    chemin: Path | None,
    modele: ModeleTemps | None = None,
    *,
    poids: dict[str, float] | None = None,
    compteur_info: dict | None = None,
) -> str:
    """Le tableau des candidates, la ligne retenue marquée d'une flèche."""
    presentes = _mesures_presentes(evaluations)
    lignes = _entete(
        demande,
        config,
        "meteo" in presentes,
        poids=poids,
        evaluations=evaluations,
        modele=modele,
        compteur_info=compteur_info,
    )

    titres = _titres(presentes, elaguees=demande.gpx is None, config=config, modele=modele)
    cellules = [_cellules(e, config, presentes, compteur_info) for e in evaluations]
    largeurs = [
        max([len(titre)] + [len(ligne[i]) for ligne in cellules]) for i, titre in enumerate(titres)
    ]
    marge = " " * (len(MARQUE_RETENUE) + 1)
    lignes.append(marge + "  ".join(t.rjust(n) for t, n in zip(titres, largeurs, strict=True)))
    for evaluation, ligne in zip(evaluations, cellules, strict=True):
        retenue = evaluation is evaluations[0] and demande.gpx is None
        marque = f"{MARQUE_RETENUE} " if retenue else marge
        lignes.append(marque + "  ".join(c.rjust(n) for c, n in zip(ligne, largeurs, strict=True)))

    if compteur_info is not None:
        lignes.append(ligne_temps_ecoule(compteur_info))
    if any(e.trace.meta.get("couts_partiels") for e in evaluations):
        lignes.append(
            f"{ABSENT} : tracé sans tags de route (GPX importé) — trafic et revêtement inconnus."
        )
    ligne_rapprochement = _ligne_rapprochement_tags(evaluations)
    if ligne_rapprochement is not None:
        lignes.append(ligne_rapprochement)
    non_classes = _non_classes_signales(evaluations)
    if non_classes:
        lignes.append(
            f"{_fr(non_classes, 1)} km sur des routes non classées (ni trafic ni calme) : "
            "« trafic » et « calme » ne couvrent pas tout le tracé."
        )
    ignores = sum(int(e.trace.meta.get("segments_ignores") or 0) for e in evaluations)
    if ignores:
        lignes.append(
            f"{ignores} tronçon(s) à la longueur inexploitable écartés du kilométrage : "
            "trafic et revêtement sont sous-estimés d'autant."
        )
    lignes += lignes_elargissement(evaluations, demande.distance_km)
    if chemin is not None:
        lignes.append(
            f"{MARQUE_RETENUE} retenue : n° {evaluations[0].numero}"
            f"{_porte_a_porte_retenue(evaluations[0], config, compteur_info)}, "
            f"écrite dans {chemin}"
        )
    return "\n".join(lignes)


def _porte_a_porte_retenue(
    evaluation: Evaluation, config: Config, compteur_info: dict | None
) -> str:
    """« , entre 4 h 23 et 4 h 38 porte à porte » — ou rien sans fourchette."""
    mouvement_s = _temps_mouvement_s(evaluation, config)
    if mouvement_s is None or compteur_info is None:
        return ""
    return f", {texte_entre(porte_a_porte(mouvement_s, compteur_info))} porte à porte"


def lignes_elargissement(evaluations, distance_km: float | None) -> list[str]:
    """« On n'a pas trouvé de boucle dans les contraintes, on a élargi de X %. »

    Les mots sont ceux du mainteneur (Q41 d). Rien ne s'affiche quand toutes
    les boucles tiennent dans la tolérance — c'est le cas normal, et une
    ligne qui signale ce qui ne compte pas apprend à ne plus lire la ligne
    (même raison que `SEUIL_ECART_DUREE` dans `sortie/commande.py`).

    Partagée avec `sortie`, qui rend le même fait dans un autre tableau : le
    cycliste n'a pas à apprendre deux formulations pour une seule notion.
    """
    elargies = [e for e in evaluations if e.elargissement]
    if not elargies or distance_km is None:
        return []
    tolerance = next((e.tolerance_distance for e in elargies if e.tolerance_distance), None)
    if tolerance is None:
        return []
    palier_max = max(e.elargissement or 0.0 for e in elargies)
    numeros = ", ".join(f"n° {e.numero}" for e in elargies)
    lignes = [
        f"Aucune boucle à ±{tolerance:.0%} de {_fr(distance_km, 0)} km : la tolérance a été "
        f"élargie de {palier_max:.0%}, soit ±{tolerance + palier_max:.0%} ({numeros})."
    ]
    for e in elargies:
        lignes.append(
            f"    n° {e.numero} : {_fr(e.trace.distance_m / 1000, 1)} km, "
            f"{e.ecart_relatif:+.0%} de la distance demandée."
        )
    return lignes


def _titres(
    presentes: set[str],
    *,
    elaguees: bool,
    config: Config,
    modele: ModeleTemps | None = None,
) -> list[str]:
    """Les titres des colonnes affichées — antennes et temps disent d'où ils viennent.

    Antennes : « retirées » sur une candidate générée (elle est élaguée),
    « détectées » sur un GPX importé (il ne l'est pas). Temps : `(modèle)`
    quand la calibration du vélo existe, `(modèle, littérature)` quand le
    modèle tourne sur des valeurs de catégorie jamais mesurées sur ce vélo,
    `(27 km/h)` — la vitesse moyenne de la configuration — quand il n'y a pas
    de modèle du tout. Sans ces mentions, deux exécutions du même ordre
    donnaient deux chiffres différents sans rien dire.
    """
    mention = mention_temps(modele, config)
    titres = [
        f"temps {mention}" if titre == "temps" else titre
        for titre, mesure in COLONNES
        if mesure is None or mesure in presentes
    ]
    if not elaguees:
        titres[titres.index(TITRE_ANTENNES_RETIREES)] = TITRE_ANTENNES_DETECTEES
    return titres


def mention_temps(modele: ModeleTemps | None, config: Config) -> str:
    """D'où sort le temps affiché, en trois mots — la source unique de la mention.

    Le titre de la colonne et la vitesse de l'entête la partagent : les voir
    diverger (« (modèle) » au-dessus d'un chiffre de littérature) serait
    exactement le « mensonge par mise en page » que la décision 8 du cycle UX
    interdit.
    """
    if modele is None:
        return f"({config.boucle.vitesse_moyenne_kmh:g} km/h)"
    return MENTION_MODELE if modele.calibre else MENTION_MODELE_LITTERATURE


def _vitesse_passage(
    config: Config,
    evaluations: list[Evaluation] | None,
    modele: ModeleTemps | None = None,
) -> str:
    """« 27 km/h » ou « 29,4 km/h (modèle) » — la vitesse qui a daté la météo.

    Les candidates n'ont pas toutes la même : une boucle vallonnée se parcourt
    moins vite qu'un plat-pays à la même puissance. L'entête affiche donc la
    moyenne des candidates dès qu'elles diffèrent d'un dixième.
    """
    connues = [
        e.vitesse_meteo_kmh for e in (evaluations or []) if e.vitesse_meteo_kmh is not None
    ]
    if not connues:
        return f"{config.boucle.vitesse_moyenne_kmh:g} km/h"
    moyenne = sum(connues) / len(connues)
    if abs(moyenne - config.boucle.vitesse_moyenne_kmh) < 0.05:
        return f"{config.boucle.vitesse_moyenne_kmh:g} km/h"
    etendue = ""
    if max(connues) - min(connues) >= 0.1:
        etendue = f" de {min(connues):.1f} à {max(connues):.1f}".replace(".", ",")
    mention = MENTION_MODELE if modele is None or modele.calibre else MENTION_MODELE_LITTERATURE
    return f"{moyenne:.1f} km/h {mention}{etendue}".replace(".", ",", 1)


def _ligne_rapprochement_tags(evaluations: list[Evaluation]) -> str | None:
    """« Tags de route rapprochés... » — d'où viennent les tags d'un GPX greffé.

    Règle absolue 5 : un tag **mesuré** par le moteur (une candidate générée)
    et un tag **deviné** par rapprochement (un GPX importé, `boucle.
    tags_importes`) ne sont pas la même chose, et l'écran doit le dire —
    avec le seuil retenu et la part de kilomètres qui n'a rien trouvé.
    `None` sans tracé greffé : rien à ajouter.
    """
    greffees = [
        e for e in evaluations if e.trace.meta.get("tags_provenance") == TAGS_PROVENANCE_RAPPROCHEMENT
    ]
    if not greffees:
        return None
    seuil = next((e.trace.meta.get("tags_seuil_m") for e in greffees), None)
    km_sans_tag = sum(float(e.trace.meta.get("tags_km_sans_tag") or 0.0) for e in greffees)
    return (
        f"Tags de route rapprochés du tracé rerouté par BRouter (seuil {seuil:g} m) : "
        f"{_fr(km_sans_tag, 1)} km n'ont trouvé aucun tronçon assez proche, comptés en "
        "routes non classées."
    )


def _non_classes_signales(evaluations: list[Evaluation]) -> float:
    """Le plus gros kilométrage non classé à signaler, ou 0 s'il n'y a rien à dire.

    Un tracé dont la moitié passe par des chemins sans `highway` connu
    (`path`, `footway`, une valeur OSM nouvelle) affichait « 0,0 km de
    trafic » exactement comme un tracé parfaitement calme : `km_trafic` et
    `km_calme` peuvent valoir bien moins que la distance, et rien ne le disait
    (point 15 de la relecture du sprint 2).
    """
    a_signaler = [
        e.couts.km_non_classe
        for e in evaluations
        if not e.trace.meta.get("couts_partiels")
        and e.trace.distance_m > 0
        and e.couts.km_non_classe / (e.trace.distance_m / 1000.0) > PART_NON_CLASSE_SIGNALEE
    ]
    return max(a_signaler, default=0.0)


def _mesures_presentes(evaluations: list[Evaluation]) -> set[str]:
    """Les mesures dont au moins une candidate dispose — donc les colonnes à montrer."""
    presentes = set()
    if any(e.meteo is not None for e in evaluations):
        presentes.add("meteo")
    if any(e.couts.cout_km_moyen is not None for e in evaluations):
        presentes.add("cout")
    if any(e.part_connue is not None for e in evaluations):
        presentes.add("connu")
    if any(e.marqueurs is not None and e.marqueurs.connue for e in evaluations):
        presentes.add("feux")
    return presentes


def _ligne_modele_meteo(evaluations: list[Evaluation], config: Config) -> str:
    """Nomme le modèle météo qui a **répondu**, et le dit haut quand c'est un repli.

    Cette ligne annonçait le modèle *configuré* et son second avis. Depuis que
    le repli de Q19 s'applique aussi à `boucle`, ce serait un mensonge une
    fois sur deux : le tableau montrerait la pluie d'`icon_seamless` sous un
    en-tête qui nomme AROME. Même phrase et même raison que
    `rendu.sortie._ligne_modele_meteo` — règle absolue 5 : quand un seul
    des deux modèles a pu répondre, c'est encore une divergence à dire.
    """
    meteo = _meteo_rendue(evaluations)
    if meteo is None or not meteo.modele_utilise:
        return f"Météo {config.meteo.modele}, second avis {config.meteo.second_avis or 'aucun'}"
    if meteo.repli and meteo.bascule_dist_m is not None:
        # Repli **partiel** : le principal a répondu pour le début du
        # parcours, sa portée horaire s'arrête avant la fin (une nuit de
        # sommeil, par exemple) — les deux moitiés ne portent pas la même
        # qualité de prévision, et rien ne doit les confondre (règle
        # absolue 5).
        return (
            f"Météo {meteo.modele_utilise} jusqu'au kilomètre "
            f"{meteo.bascule_dist_m / 1000.0:g} — au-delà, {config.meteo.second_avis} "
            "(modèle de repli, hors de portée du principal)."
        )
    if meteo.repli:
        return (
            f"Météo : {config.meteo.modele} ne couvre pas cette fenêtre — bascule sur "
            f"{meteo.modele_utilise} (second avis, configuré en repli)."
        )
    return (
        f"Météo {meteo.modele_utilise}, second avis {config.meteo.second_avis or 'aucun'}"
    )


def _lignes_litterature(modele: ModeleTemps) -> list[str]:
    """La catégorie servie et sa dérive mesurée, ou rien. Délégué, jamais recalculé ici."""
    from ourouler.physique import litterature

    choix = litterature.pour_usage(modele.usage) if modele.provenance == "littérature" else None
    if choix is None:
        return []
    return [
        f"Catégorie {choix.resume}",
        f"Pour un temps mesuré sur vous : `ourouler calibrer --velo {modele.velo}`.",
    ]


def _entete(
    demande: Demande,
    config: Config,
    avec_meteo: bool,
    *,
    poids: dict[str, float] | None = None,
    evaluations: list[Evaluation] | None = None,
    modele: ModeleTemps | None = None,
    compteur_info: dict | None = None,
) -> list[str]:
    lignes = []
    if demande.gpx is not None:
        lignes.append(f"Tracé importé : {demande.gpx}")
    else:
        # Sans `--direction` (Q47), la recherche balaie tout l'horizon : il
        # n'y a alors pas un azimut à afficher, mais huit.
        direction = (
            f"{demande.direction} ({demande.azimut_deg:.0f}°)"
            if demande.azimut_deg is not None
            else "toutes directions"
        )
        lignes.append(
            f"Boucle depuis {config.depart.nom} — {demande.distance_km:g} km vers "
            f"{direction}, profil {demande.profil}"
        )
    lignes.append(
        f"Départ {date_en_francais(demande.depart)} — "
        f"{_vitesse_passage(config, evaluations, modele)} "
        f"(heures de passage météo), sens préféré {config.boucle.sens}"
    )
    if modele is not None and modele.calibre:
        lignes.append(
            f"Temps estimé par le modèle calibré du {modele.velo} à {modele.puissance_w:.0f} W "
            "— temps en mouvement, arrêts non modélisés"
        )
        if modele.alerte:
            lignes.append(f"⚠ Calibration du {modele.velo} : {modele.alerte}.")
    elif modele is not None:
        # Le modèle tourne, mais sur des CdA et Crr de catégorie : il le dit
        # ici comme le facteur compteur dit « supposé » (règle absolue 5).
        lignes.append(
            f"Temps estimé par le modèle du {modele.velo} à {modele.puissance_w:.0f} W, "
            f"sur des valeurs de {modele.provenance} — temps en mouvement, arrêts non modélisés"
        )
        lignes.extend(_lignes_litterature(modele))
    else:
        lignes.append(
            f"Temps estimé à {config.boucle.vitesse_moyenne_kmh:g} km/h : aucun modèle "
            "physique pour ce vélo (usage hors des catégories connues)"
        )
    if avec_meteo:
        lignes.append(_ligne_modele_meteo(evaluations or [], config))
    ligne_pauses = _ligne_pauses(demande, evaluations or [], config, compteur_info)
    if ligne_pauses is not None:
        lignes.append(ligne_pauses)
    lignes.append("Tri : score (km équivalents) + pluie cumulée × 2 ; plus bas = mieux.")
    if poids:
        # D'où viennent les poids : sans cette ligne, deux exécutions
        # séparées par un `routes poids --appliquer` donneraient des scores
        # différents sans que rien ne l'explique.
        cites = _classes_citees(poids, evaluations or [])
        lignes.append(
            "Poids des routes : appris sur vos sorties"
            + (f" ({cites})." if cites else ".")
        )
    else:
        lignes.append(
            "Poids des routes : valeurs par défaut — `ourouler routes poids --appliquer` "
            "les apprend sur vos sorties."
        )
    lignes.append(
        "« connu % » : part des km déjà roulés — informatif, jamais dans le score."
    )
    return lignes


def _classes_citees(
    poids: dict[str, float], evaluations: list[Evaluation], nombre: int = 4
) -> str:
    """Le poids des classes les plus **présentes dans les candidates affichées**.

    Citer les plus pénalisées donnait une ligne vraie mais inutile
    (« primary_link 4,0, pedestrian 3,3 ») : ces classes ne font pas
    cinquante mètres du tracé. Ce que le lecteur veut savoir, c'est ce que
    coûtent les routes qu'il a sous les yeux.
    """
    km_par_classe: dict[str, float] = {}
    for evaluation in evaluations:
        for classe, km in evaluation.couts.km_par_highway.items():
            if classe:
                km_par_classe[classe] = km_par_classe.get(classe, 0.0) + km
    classes = sorted(km_par_classe.items(), key=lambda kv: (-kv[1], kv[0]))[:nombre]
    return ", ".join(f"{classe} {_fr(poids.get(classe, 0.0), 1)}" for classe, _ in classes)


def _cellules(
    evaluation: Evaluation, config: Config, presentes: set[str], compteur_info: dict | None = None
) -> list[str]:
    couts, meteo = evaluation.couts, evaluation.meteo
    partiels = bool(evaluation.trace.meta.get("couts_partiels"))
    cellules = [
        str(evaluation.numero),
        f"{_fr(evaluation.trace.distance_m / 1000, 1)} km",
        _denivele(evaluation.trace),
        _temps(evaluation, config, compteur_info),
        ABSENT if partiels else f"{_fr(couts.km_trafic, 1)} km",
        ABSENT if partiels else f"{_fr(couts.km_non_revetu, 1)} km",
    ]
    if "cout" in presentes:
        cellules.append(
            _fr(couts.cout_km_moyen, 0) if couts.cout_km_moyen is not None else ABSENT
        )
    cellules += [
        f"{couts.virages_gauche} ({couts.virages_gauche_trafic})",
        couts.sens,
    ]
    if "connu" in presentes:
        cellules.append(
            f"{evaluation.part_connue * 100:.0f} %" if evaluation.part_connue is not None else ABSENT
        )
    cellules.append(f"{couts.antennes_m:.0f} m")
    if "feux" in presentes:
        marqueurs = evaluation.marqueurs
        cellules.append(
            str(marqueurs.par_nature.get("traffic_signals", 0))
            if marqueurs is not None and marqueurs.connue
            else ABSENT
        )
    if "meteo" in presentes:
        cellules += [
            f"{_fr(meteo.pluie_cumulee_mm, 1)} mm" if meteo else ABSENT,
            _vent_face(meteo),
            f"{_fr(meteo.ressenti_min_c, 1)} °C" if meteo and meteo.ressenti_min_c is not None else ABSENT,
        ]
    return cellules


def _denivele(trace: Trace) -> str:
    """« 362 m (moteur) » ou « 362 m (gpx relu) » — le D+ dit d'où il vient.

    Le « filtered ascend » du moteur et le D+ recalculé à la relecture d'un
    GPX divergent de 10 à 32 % sur les tracés mesurés, dans les deux sens :
    afficher le chiffre sans sa provenance rendait l'écart incompréhensible
    (point 5 de la relecture du sprint 2).
    """
    if trace.denivele_m is None:
        return ABSENT
    source = trace.meta.get("denivele_source")
    return f"{trace.denivele_m:.0f} m" + (f" ({source})" if source else "")


def _vent_face(meteo: MeteoTrace | None) -> str:
    """« 38 % (12/12) » — le pourcentage et le nombre d'échantillons qui le portent.

    Les parts de vent se calculent sur les seuls échantillons au vent connu,
    ce qui est le bon choix : un échantillon sans donnée ne doit pas compter
    pour du travers. Mais « vent face 100 % » ne disait pas s'il reposait sur
    douze échantillons ou sur un seul, les onze autres étant hors de
    l'horizon de prévision (point 18 de la relecture du sprint 2).
    """
    if meteo is None:
        return ABSENT
    return f"{meteo.part_vent_face * 100:.0f} % ({meteo.n_vent_connu}/{len(meteo.echantillons)})"


def _temps_mouvement_s(evaluation: Evaluation, config: Config) -> float | None:
    """Le temps en mouvement, en secondes — celui du modèle s'il y en a un, sinon
    celui de la vitesse moyenne de la configuration. `None` si ni l'un ni
    l'autre n'est disponible (vitesse moyenne nulle ou non configurée)."""
    if evaluation.temps_s is not None:
        return evaluation.temps_s
    vitesse = config.boucle.vitesse_moyenne_kmh
    if vitesse <= 0:
        return None
    return evaluation.trace.distance_m / 1000 / vitesse * 3600


def _temps_ecoule_s(
    evaluation: Evaluation, config: Config, compteur_info: dict | None
) -> float | None:
    """Le temps écoulé porte à porte **médian**, en secondes — sans les pauses déclarées.

    La médiane de la fourchette du vélo (`porte_a_porte`) quand un vélo en
    donne une ; à défaut, le temps en mouvement tel quel. `None` si même
    celui-ci manque. Les pauses s'ajoutent par-dessus, ailleurs
    (`_duree_pauses_s` + ce résultat) : la fourchette ne les connaît pas, et
    ne doit pas les connaître — les compter ici *et* les ajouter ensuite les
    compterait deux fois.
    """
    mouvement_s = _temps_mouvement_s(evaluation, config)
    if mouvement_s is None:
        return None
    if compteur_info is None:
        return mouvement_s
    return porte_a_porte(mouvement_s, compteur_info).mediane_s


def _heure_arrivee(
    evaluation: Evaluation, demande: Demande, config: Config, compteur_info: dict | None
) -> datetime | None:
    """`depart + temps écoulé porte à porte + pauses déclarées` — l'heure de la pendule.

    `None` si aucun temps de base n'est calculable (pas de vitesse moyenne
    configurée et pas de modèle physique) : pas d'heure à annoncer plutôt
    qu'une heure fausse.
    """
    ecoule_s = _temps_ecoule_s(evaluation, config, compteur_info)
    if ecoule_s is None:
        return None
    return demande.depart + timedelta(seconds=ecoule_s + _duree_pauses_s(demande.pauses))


def _ligne_pauses(
    demande: Demande,
    evaluations: list[Evaluation],
    config: Config,
    compteur_info: dict | None,
) -> str | None:
    """« Pauses : 2 déclarée(s), 1:15 au total — arrivée estimée … (n° 1). »

    `None` sans pause déclarée : pas de ligne pour ne rien dire. L'arrivée
    est celle de la candidate retenue (`evaluations[0]`, la même que celle
    qu'annonce déjà `_ecrire_meilleure`) — chaque candidate a son propre
    temps de base, une seule ligne d'en-tête ne peut pas toutes les dire.
    """
    if not demande.pauses:
        return None
    retenue = evaluations[0]
    total_texte = _duree_texte(_duree_pauses_s(demande.pauses))
    n = len(demande.pauses)
    arrivee = _heure_arrivee(retenue, demande, config, compteur_info)
    if arrivee is None:
        return (
            f"Pauses : {n} déclarée(s), {total_texte} au total — s'ajoutent par-dessus le "
            "temps écoulé porte à porte, jamais confondues avec lui (arrivée non estimable "
            "sans temps de base)."
        )
    return (
        f"Pauses : {n} déclarée(s), {total_texte} au total — s'ajoutent par-dessus le temps "
        f"écoulé porte à porte, jamais confondues avec lui. Arrivée estimée : "
        f"{date_en_francais(arrivee)} (n° {retenue.numero})."
    )


def _temps(evaluation: Evaluation, config: Config, compteur_info: dict | None = None) -> str:
    """« 2:14 » seul, ou « 2:20-2:24 / 2:14 » — porte à porte en fourchette /
    mouvement — dès qu'un vélo donne une fourchette (voir `ligne_temps_ecoule`).

    **L'écoulé vient en premier** (18/09/2026). Le mainteneur l'a tranché
    pour l'écran, et la CLI ne dit pas l'inverse : « je demande 5 h, je veux
    5 h, pas 4 h et un truc plus loin qui me dit en fait c'est 5 h ». Le
    premier chiffre est donc celui qui répond à la durée demandée ; le
    second dit ce que ça donnerait sans un seul arrêt.
    """
    mouvement_s = _temps_mouvement_s(evaluation, config)
    if mouvement_s is None:
        return ABSENT
    if compteur_info is None:
        return _duree_texte(mouvement_s)
    pp = porte_a_porte(mouvement_s, compteur_info)
    return f"{_duree_texte(pp.bas_s)}-{_duree_texte(pp.haut_s)} / {_duree_texte(mouvement_s)}"


def texte_entre(pp: PorteAPorte) -> str:
    """« entre 4 h 23 et 4 h 38 » — la fourchette du porte à porte, en toutes lettres.

    Publique : `sortie.commande` dit la sienne avec les mêmes mots.
    """
    return f"entre {_heures_minutes(pp.bas_s)} et {_heures_minutes(pp.haut_s)}"


def _heures_minutes(secondes: float) -> str:
    minutes = round(secondes / 60)
    return f"{minutes // 60} h {minutes % 60:02d}"


def provenance_fourchette(compteur_info: dict) -> str:
    """D'où vient la fourchette du vélo, en une incise : mesurée sur ses sorties ou convention.

    Règle absolue 5 : la convention ne se présente jamais comme une mesure.
    """
    brut = compteur_info["porte_a_porte"]
    if brut["provenance"] == "mesure":
        return f"mesurée sur {brut['n']} sorties du {compteur_info['velo']} roulées seul"
    return "convention, mesurée sur un seul cycliste — pas encore sur vos sorties"


def ligne_temps_ecoule(compteur_info: dict) -> str:
    """La légende sous le tableau : ce que veut dire « 2:20-2:31 / 2:14 » en colonne « temps ».

    Choix d'affichage (18/09/2026) : une cellule combinée plutôt qu'une
    colonne de plus — le tableau en a déjà treize, une quatorzième pour un
    seul chiffre de plus n'aurait pas tenu en largeur de terminal. La CLI et
    le JSON disent la même chose : `temps_estime_s`/`temps_ecoule_s`.

    **Publique et non préfixée** : `sortie.commande` l'appelle telle quelle
    plutôt que de réécrire la même phrase pour son propre tableau — même
    raison que `lignes_elargissement` juste au-dessus.

    Ce temps écoulé ne connaît pas les pauses déclarées (`--pause`) : elles
    couvrent un arrêt volontaire (repas, nuit), la fourchette couvre déjà les
    feux et les micro-arrêts. Une pause déclarée s'ajoute **par-dessus** ce
    chiffre, voir `_ligne_pauses` — les compter ici reviendrait à les compter
    deux fois.

    Depuis L9.1 (25/09/2026) le porte à porte est le temps sans arrêt de ce
    tracé-ci multiplié par la fourchette du vélo : la moyenne compteur ne le
    chronomètre plus, elle ne sert qu'à choisir la distance.
    """
    brut = compteur_info["porte_a_porte"]
    return (
        "Temps affiché : porte à porte, arrêts compris / sans un seul arrêt — le porte "
        f"à porte est le temps sans arrêt × {_fr(brut['bas'], 2)} à × {_fr(brut['haut'], 2)} "
        f"({provenance_fourchette(compteur_info)}) : la moitié des sorties tombe dans "
        "cette fourchette."
    )


def _duree_texte(secondes: float) -> str:
    minutes = round(secondes / 60)
    return f"{minutes // 60}:{minutes % 60:02d}"


def _fr(valeur: float, decimales: int) -> str:
    """Un nombre à la française : virgule décimale, pas de séparateur de milliers."""
    return f"{valeur:.{decimales}f}".replace(".", ",")
