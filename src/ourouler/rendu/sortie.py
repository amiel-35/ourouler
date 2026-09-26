"""Ce que `ourouler sortie` montre : le tableau texte, le JSON et la page du jour.

La couche de rendu (`ARCHITECTURE.md`). `services/sortie.py` lit la
séance, cherche les boucles, place, mesure, trie et écrit les fichiers ; il
passe ici des objets déjà construits — les `Proposition`, le `_Contexte` (qui
porte la `Config` et le bloc « compteur » déjà lus), la `Selection`
contrastée, les GPX en mémoire — et imprime ou écrit ce qui en revient.

Ce module ne lit ni fichier, ni configuration, ni environnement, n'écrit
rien et ne lit pas l'horloge : la page reçoit son `maintenant`. Il décide
des phrases, de la forme du JSON (le contrat du front) et de la page HTML,
que `rendu/carte.py` dessine.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from ourouler.boucle.meteo_trace import SEUIL_VENT_SENSIBLE_KMH
from ourouler.meteo import portee
from ourouler.meteo.couronne import nom_de_azimut
from ourouler.meteo.rapport import date_en_francais
from ourouler.noyau.seance import Seance
from ourouler.noyau.texte import azimut_texte, duree_h_min, minutes_signees, nombre_fr
from ourouler.rendu.boucle import ligne_temps_ecoule, lignes_elargissement
from ourouler.rendu.boucle_json import porte_a_porte
from ourouler.rendu.carte import PropositionCarte, construire_page_jour, construire_page_sans_seance
from ourouler.seance.tenue import Tenue
from ourouler.seance.tenue import conseiller as conseiller_tenue
from ourouler.services.sortie import (
    NOTE_BLOC_BIEN_PLACE,
    Demande,
    GpxPropose,
    Proposition,
    _Contexte,
)
from ourouler.sortie import contraste, orientation, vent_demande

if TYPE_CHECKING:
    # Le rendu lit les champs d'une `Config` déjà chargée ; il n'importe pas,
    # à l'exécution, l'entrée qui la charge (même règle que `rendu/profil.py`).
    from ourouler.config import Config


#: Marque de la ligne retenue dans le tableau texte (même signe que `boucle`).
MARQUE_RETENUE = "→"

#: Ce qu'on affiche à la place d'une mesure absente — jamais un zéro.
ABSENT = "—"


# --- ce que la commande imprime ou écrit hors du tableau ---------------------


def json_sans_seance(jour: date, carte: Path | None) -> dict:
    """La réponse JSON d'un jour sans séance : ce n'est pas une erreur, c'est une réponse."""
    return {
        "jour": jour.isoformat(),
        "seance": None,
        "candidates": [],
        "carte": str(carte) if carte else None,
    }


def texte_sans_seance(jour: date, carte: Path | None) -> str:
    """Le message d'un jour sans séance, et la page écrite s'il y en a une."""
    message = (
        f"Aucune séance vélo planifiée le {jour.isoformat()} sur Intervals.icu — "
        "rien à placer. `ourouler boucle` propose une sortie libre."
    )
    if carte is not None:
        message += f"\nPage écrite : {carte}"
    return message


def avertissement_meteo(panne: str | None, meteo_absente: portee.MeteoAbsente | None) -> str | None:
    """La ligne de la sortie d'erreur quand la météo manque, ou `None` si elle a répondu.

    Perdre la séance parce qu'il manque la pluie serait absurde : le tableau
    reste servi sans ses colonnes météo ni la tenue, et le placement reste
    valable. Une panne d'Open-Meteo se nomme ; une date hors de l'horizon dit
    ce qu'on ne sait pas.
    """
    if panne is not None:
        return (
            f"ourouler : météo indisponible ({panne}) — tableau sans les colonnes météo et "
            "sans tenue conseillée ; le placement, lui, reste valable"
        )
    if meteo_absente is not None:
        return (
            f"ourouler : {meteo_absente.message} — tableau sans les colonnes météo et sans "
            "tenue conseillée ; le placement, lui, reste valable"
        )
    return None


def page_sans_seance(jour: date, *, maintenant: datetime) -> str:
    """La page du jour quand rien n'est planifié, datée de `maintenant` (voir `rendu.carte`)."""
    return construire_page_sans_seance(jour, maintenant=maintenant)


def page_jour(
    seance: Seance,
    demande: Demande,
    config: Config,
    selection: contraste.Selection,
    gpx_propositions: list[GpxPropose],
    *,
    maintenant: datetime,
) -> str:
    """La page du jour : les propositions contrastées, superposées.

    Une `carte.PropositionCarte` par proposition retenue par
    `contraste.choisir` — jamais recalculée ici, seulement mise en forme
    pour l'affichage. Chacune porte sa **propre** tenue : la météo diffère
    d'une direction à l'autre, et un cycliste qui choisit la deuxième
    proposition doit lire son conseil à elle, pas celui de la première. Le
    GPX embarqué dans la page est celui du **parcours placé**, demi-tours
    compris — même règle que le fichier que la commande écrit sur disque,
    mais celui-ci n'est jamais écrit : il part en base64 dans la page, pour
    un téléchargement `blob:` côté navigateur : le fichier suit le choix du
    cycliste, pas le classement.
    """
    par_numero = {g.numero: g for g in gpx_propositions}
    cartes_props = []
    for retenue in selection.retenues:
        p = retenue.proposition
        tenue_p = conseiller_tenue(p.meteo, config.tenue) if p.meteo is not None else None
        gpx = par_numero[p.numero]
        cartes_props.append(
            PropositionCarte(
                numero=p.numero,
                trace=p.trace,
                placement=p.placement,
                meteo=p.meteo,
                # Vide plutôt que faux : `construire_page_jour` sait qu'une
                # proposition sans phrase parle par son tracé, et n'écrit
                # « la seule candidate » que quand elle l'est vraiment.
                distinction=retenue.distinction,
                chiffres=_details_proposition(retenue),
                sous_titre=_sous_titre(p, demande, config),
                notes=_notes_carte(p, seance, tenue_p),
                gpx_nom=gpx.nom_fichier,
                gpx_texte=gpx.texte,
            )
        )
    return construire_page_jour(
        seance,
        cartes_props,
        titre=f"{seance.nom} — {date_en_francais(demande.depart)}",
        motif_deux_propositions=selection.motif_deux_propositions,
        motif_equivalence=selection.motif_equivalence,
        maintenant=maintenant,
    )


def vent_depart_json(question: vent_demande.QuestionVent, jour: date, depart_heure: datetime) -> dict:
    """Le vent au départ et ce que chaque préférence en ferait, en JSON.

    `azimuts_par_choix` porte **des listes**, y compris pour les préférences
    qui n'ouvrent qu'un azimut : un consommateur qui lit une liste ne peut pas
    rater le second azimut du travers, là où un champ scalaire l'aurait
    silencieusement tronqué.

    Les noms de direction (`"SO"`) sont calculés **ici** et non côté écran : le
    front n'a le droit d'afficher que ce que l'API lui donne.
    """
    return {
        "jour": jour.isoformat(),
        "depart": depart_heure.isoformat(),
        "posee": question.posee,
        "motif": question.motif or None,
        "vent_kmh": question.vent_kmh,
        "vent_depuis_deg": question.vent_depuis_deg,
        "vent_depuis_nom": (
            nom_de_azimut(question.vent_depuis_deg) if question.vent_depuis_deg is not None else None
        ),
        "seuil_kmh": SEUIL_VENT_SENSIBLE_KMH,
        "horizon_jours": vent_demande.HORIZON_ORIENTATION_J,
        "choix": list(orientation.CHOIX),
        "azimuts_par_choix": {
            choix: [{"azimut_deg": a, "nom": nom_de_azimut(a)} for a in question.azimuts_pour(choix)]
            for choix in orientation.CHOIX
        },
    }


def _sous_titre(proposition: Proposition, demande: Demande, config: Config) -> str:
    trace = proposition.trace
    morceaux = [
        f"départ {config.depart.nom}",
        f"{nombre_fr(trace.distance_m / 1000, 1)} km",
        f"D+ {trace.denivele_m:.0f} m" if trace.denivele_m is not None else f"D+ {ABSENT}",
        f"note de placement {nombre_fr(proposition.placement.note_totale, 2)}",
        f"{proposition.blocs_bien_places}/{len(proposition.placement.blocs())} blocs bien placés",
    ]
    if demande.direction:
        morceaux.insert(1, f"vers {demande.direction}")
    return " · ".join(morceaux)


def _notes_carte(proposition: Proposition, seance: Seance, tenue: Tenue | None) -> list[str]:
    notes = [
        f"Séance : {_duree_longue(seance.duree_s)}, {len(seance.blocs())} bloc(s) ; "
        f"placement {_duree_longue(proposition.placement.duree_totale_s)} pour "
        f"{nombre_fr(proposition.placement.distance_totale_m / 1000, 1)} km, décalage de la Z2 "
        f"d'ouverture {minutes_signees(proposition.placement.decalage_z2_s)}.",
    ]
    meteo = proposition.meteo
    if meteo is not None:
        notes.append(
            f"Météo le long du tracé : {nombre_fr(meteo.pluie_cumulee_mm, 1)} mm cumulés, "
            f"vent de face sur {meteo.part_vent_face * 100:.0f} % des échantillons."
        )
    else:
        notes.append("Météo indisponible pour ce jour : ni pluie, ni vent, ni tenue.")
    if tenue is not None:
        notes.append("Tenue : " + _tenue_courte(tenue))
    notes.extend(proposition.placement.informations)
    for avertissement in proposition.placement.avertissements:
        notes.append("⚠ " + avertissement)
    return notes


# --- rendu texte ---------------------------------------------------------------

#: Écart, en mètres, au-delà duquel le parcours réellement roulé mérite sa
#: propre colonne. Sans demi-tour il vaut la boucle au mètre près ; avec, il
#: peut valoir le double (72,7 km mesurés sur une boucle de 38,5). Cent mètres
#: parce qu'en dessous l'écart n'est que l'arrondi du placement.
ECART_PARCOURS_M = 100.0

#: Écart, en mètres de dénivelé, au-delà duquel les deux D+ méritent d'être
#: montrés côte à côte. Dix mètres : en dessous, les deux méthodes disent la
#: même chose et une ligne de plus ne ferait que du bruit.
ECART_DENIVELE_M = 10.0

#: Colonnes du tableau. Le second membre nomme la mesure dont la colonne
#: dépend : sans cette mesure, la colonne **disparaît** au lieu d'afficher une
#: colonne de tirets. `None` = toujours affichée.
#:
#: « boucle » et « D+ boucle » décrivent le tracé proposé par le moteur ;
#: « parcours » et « temps » décrivent ce que la séance fait réellement rouler.
#: La ligne mélangeait les deux — 38,5 km en 2 h 44, soit 14 km/h — parce que
#: la distance venait de la boucle et la durée du placement.
COLONNES = (
    ("n°", None),
    ("boucle", None),
    ("D+ boucle", None),
    ("parcours", "parcours"),
    ("temps", None),
    ("trafic", None),
    ("connu %", "connu"),
    ("pluie", "meteo"),
    ("vent face", "meteo"),
    ("note placement", None),
    ("blocs bien placés", None),
    ("demi-tours", "demi_tours"),
)


def rendre_texte(propositions: list[Proposition], contexte: _Contexte) -> str:
    """L'en-tête, le tableau des candidates, la séance placée, la tenue, les fichiers."""
    presentes = _mesures_presentes(propositions)
    lignes = _entete(propositions, contexte, presentes)
    # La troisième valeur de l'écran de FTP, lue par la commande
    # (elle relit la calibration du vélo) et portée par le contexte.
    compteur_info = contexte.compteur_info

    titres = [t for t, mesure in COLONNES if mesure is None or mesure in presentes]
    cellules = [_cellules(p, presentes, compteur_info) for p in propositions]
    largeurs = [max([len(titre)] + [len(ligne[i]) for ligne in cellules]) for i, titre in enumerate(titres)]
    marge = " " * (len(MARQUE_RETENUE) + 1)
    lignes.append(marge + "  ".join(t.rjust(n) for t, n in zip(titres, largeurs, strict=True)))
    for proposition, ligne in zip(propositions, cellules, strict=True):
        marque = f"{MARQUE_RETENUE} " if proposition is propositions[0] else marge
        lignes.append(marque + "  ".join(c.rjust(n) for c, n in zip(ligne, largeurs, strict=True)))

    if compteur_info is not None:
        lignes.append(ligne_temps_ecoule(compteur_info))
    lignes += _notes_sous_tableau(propositions[0], presentes)
    # L'élargissement de la tolérance de distance se dit ici, sous le tableau,
    # et non dans la colonne « durée » : ce sont deux grandeurs différentes.
    # Voir `SEUIL_ECART_DUREE` plus bas pour la cohabitation des deux.
    lignes += lignes_elargissement(propositions, contexte.distance_km)
    lignes.append("")
    lignes += _propositions_contrastees(contexte)
    lignes += _seance_placee(propositions[0], contexte)
    lignes.append("")
    lignes += _tenue_lignes(contexte)
    if contexte.gpx is not None:
        lignes.append(f"{MARQUE_RETENUE} GPX   : {contexte.gpx}")
    if contexte.carte is not None:
        lignes.append(f"{MARQUE_RETENUE} Carte : {contexte.carte}")
    return "\n".join(lignes)


def _lignes_vent(contexte: _Contexte) -> list[str]:
    """La question d'orientation au vent, ou la raison pour laquelle on ne la pose pas.

    Elle est imprimée dans l'en-tête parce qu'elle a été posée **avant** la
    recherche : ce que le lecteur voit en dessous est déjà la réponse à ce
    qu'il a (ou n'a pas) demandé.
    """
    question, demande = contexte.question_vent, contexte.demande
    if question is None:
        return []
    if not question.posee:
        return [f"Orientation au vent : pas d'avis — {question.motif}."]
    vent = f"Vent au départ {question.vent_kmh:.0f} km/h de {azimut_texte(question.vent_depuis_deg)}"
    if demande.vent != orientation.PEU_IMPORTE:
        azimuts = question.azimuts_pour(demande.vent)
        ou = f" — recherche dirigée vers {_azimuts(azimuts)}" if azimuts else ""
        return [f"{vent}. Demandé : {_LIBELLES_VENT[demande.vent]}{ou}."]
    return [
        f"{vent}. Question : `--vent retour-dos` pour rentrer avec, `--vent depart-dos` "
        "pour partir avec, `--vent travers` — ou rien, et les propositions ci-dessous "
        "répondent à votre place."
    ]


#: Comment on nomme chaque réponse à la question du vent, à l'affichage.
_LIBELLES_VENT = {
    orientation.PEU_IMPORTE: "peu importe",
    orientation.ORIENTATION_RETOUR_DOS: "rentrer avec le vent dans le dos",
    orientation.ORIENTATION_DEPART_DOS: "partir avec le vent dans le dos",
    orientation.ORIENTATION_TRAVERS: "vent de travers",
}


def _propositions_contrastees(contexte: _Contexte) -> list[str]:
    """Les deux ou trois propositions retenues, chacune avec sa phrase.

    La phrase, en langage de cycliste et
    jamais en langage de note, est ce qui permet d'arbitrer **en regardant**
    plutôt qu'en réglant.
    """
    selection = contexte.selection
    if selection is None or not selection.retenues:
        return []
    seule = len(selection.retenues) == 1
    lignes = [
        f"{len(selection.retenues)} proposition(s) qui vont à des endroits différents "
        "(et non les trois premières du tri) :"
    ]
    for retenue in selection.retenues:
        numero = retenue.proposition.numero
        # Une retenue peut n'avoir aucune phrase : son tracé la
        # distingue, pas un axe mesuré. « La seule candidate » ne vaut alors
        # que si elle est vraiment seule — l'écrire sous l'une de trois
        # propositions serait faux.
        phrase = retenue.distinction or ("la seule candidate" if seule else "")
        lignes.append(f"    n° {numero} — {phrase}" if phrase else f"    n° {numero}")
        lignes.append(f"           {_details_proposition(retenue)}")
    if selection.recouvrements:
        parts = ", ".join(
            f"n° {selection.retenues[i].proposition.numero}/"
            f"n° {selection.retenues[j].proposition.numero} {part:.0%}"
            for (i, j), part in sorted(selection.recouvrements.items())
        )
        lignes.append(
            f"    Routes communes : {parts} "
            f"(au-delà de {contraste.SEUIL_RECOUVREMENT:.0%}, deux boucles se ressemblent "
            "sur la carte quoi que disent leurs notes)."
        )
    if selection.motif_deux_propositions:
        lignes.append(f"    {selection.motif_deux_propositions}")
    if selection.motif_equivalence:
        lignes.append(f"    {selection.motif_equivalence}")
    lignes.append("")
    return lignes


#: Écart de durée en deçà duquel on n'affiche rien : 5 % de la séance.
#: Une minute en plus ou en moins n'est pas un écart important ; on ne dit
#: rien en deçà de 5 % de différence de durée (décision Q21 a,
#: `docs/journal/questions/questions_mainteneur.md`). Deux seuils, deux rôles :
#: celui-ci décide si l'écart mérite d'être dit, `elasticite_calme_min` s'il
#: mérite une alerte.
#:
#: **Et un troisième, à ne surtout pas confondre avec lui** :
#: `boucle.candidates.elargissement_max` borne l'écart de **distance** entre
#: la boucle servie et la boucle demandée. Les deux mesurent des grandeurs
#: différentes sur des objets différents, et ne se recouvrent pas :
#:
#: - `SEUIL_ECART_DUREE` parle de la **durée d'une séance** — la séance
#:   prescrite dure 2 h, le parcours placé en dure 2 h 04, faut-il le dire ?
#:   Il ne refuse jamais rien : il décide si un écart déjà accepté s'affiche.
#: - `elargissement_max` parle de la **distance d'une boucle** — 150 km
#:   demandés, 176 rendus, sert-on cette boucle ? Il refuse, et quand il
#:   accepte, il impose de dire de combien la tolérance a été élargie.
#:
#: Conséquence pratique : une boucle peut être servie en disant « tolérance
#: élargie de 10 % » (fait de distance) et ne rien afficher sur la durée
#: parce que la séance tombe à 2 % près (fait de durée). Ce n'est pas une
#: incohérence, c'est la raison d'avoir deux seuils : un affichage d'écart de
#: durée trop bavard serait alarmant à tort.
SEUIL_ECART_DUREE = 0.05


def _ecart_seance(profil) -> str:
    """« (+18 min) » ou « (⚠ séance amputée de 12 min) », ou rien si elle tombe juste.

    Le signe compte et se dit : rentrer plus tard est normal — c'est le rôle
    du retour au calme —, rouler moins que la séance ne l'est pas. Les deux
    écarts sont du même côté de la valeur absolue dans l'axe de contraste, ils
    ne doivent pas l'être à l'affichage.

    **Le ⚠ suit le verdict du placement (`profil.seance_amputee`), pas un
    seuil recalculé ici.** Un seuil fixe de 60 secondes afficherait
    « ⚠ séance amputée » pour un écart de 0,8 % sur une séance de 2 h — alors
    que le seuil qui compte est déjà fixé, `elasticite_calme_min` (config
    `[seance]`, −5 % par défaut), et que `seance.placement` l'applique déjà pour décider si le
    retour au calme est raccourci. Un écart sous ce seuil reste visible en
    minutes, neutre, sans ⚠ — symétrique du dépassement positif.

    **Et sous le seuil, on n'affiche rien du tout** : même « (−5 min) » sans
    le ⚠ serait de trop, un écart qu'on juge négligeable n'a pas à
    s'afficher. Une ligne qui signale
    ce qui ne compte pas apprend à ne plus lire la ligne.
    """
    depassement = getattr(profil, "depassement_s", None)
    duree = getattr(profil, "duree_s", None)
    if depassement is None or abs(depassement) < 60:
        return ""
    if duree:
        prescrite = duree - depassement
        if prescrite > 0 and abs(depassement) / prescrite < SEUIL_ECART_DUREE:
            return ""
    if depassement > 0:
        return f" (+{depassement / 60:.0f} min)"
    if getattr(profil, "seance_amputee", False):
        return f" (⚠ séance amputée de {-depassement / 60:.0f} min)"
    return f" ({depassement / 60:.0f} min)"


def _details_proposition(retenue) -> str:
    """Les mesures qui portent la phrase, dans les unités du cycliste."""
    profil = retenue.profil
    morceaux = [duree_h_min(profil.duree_s) + _ecart_seance(profil)]
    if profil.feux is not None:
        # Nombres absolus, et séparés : « 1,7 feux/stops/passages au km » se
        # lirait « 170 sur 100 km » sur un composite dont les deux tiers sont
        # des passages piétons, qu'on traverse sans lever le pied. On ne
        # montre que ce qui pose le pied.
        arrets = [f"{profil.feux} feu{'x' if profil.feux > 1 else ''}"]
        if profil.stops:
            arrets.append(f"{profil.stops} stop{'s' if profil.stops > 1 else ''}")
        morceaux.append(", ".join(arrets))
    else:
        morceaux.append("marqueurs inconnus")
    morceaux.append("aucun demi-tour" if profil.demi_tours == 0 else f"{profil.demi_tours} demi-tour(s)")
    if profil.part_trafic is not None:
        # Le % de `primary` seul, pas le composite primary + secondary +
        # trunk qui multiplierait par quatre ce qui doit inquiéter
        # (« secondary », une départementale ordinaire, en porterait les deux
        # tiers ; décision Q21 c).
        morceaux.append(f"{profil.part_trafic * 100:.0f} % de nationales")
    if profil.pluie_mm is not None:
        morceaux.append(f"{nombre_fr(profil.pluie_mm, 1)} mm de pluie")
    if profil.orientation is not None:
        morceaux.append(f"vent : {_LIBELLES_ORIENTATION[profil.orientation]}")
    part = getattr(retenue.proposition, "part_connue", None)
    if part is not None:
        morceaux.append(f"{part * 100:.0f} % de routes connues")
    return ", ".join(morceaux)


#: Comment on nomme une orientation au vent dans la ligne de détail. La part
#: connue y figure aussi, mais **seulement pour décrire** une proposition déjà
#: retenue : elle n'entre jamais dans un score — pénaliser l'inconnu
#: condamnerait d'avance toute direction jamais explorée.
_LIBELLES_ORIENTATION = {
    orientation.ORIENTATION_RETOUR_DOS: "dans le dos au retour",
    orientation.ORIENTATION_DEPART_DOS: "dans le dos au départ",
    orientation.ORIENTATION_TRAVERS: "de travers",
    orientation.ORIENTATION_FACE: "de face aux deux bouts",
}


def _notes_sous_tableau(proposition: Proposition, presentes: set[str]) -> list[str]:
    """Ce que les colonnes ne peuvent pas dire : les deux parcours, et les deux D+.

    Même règle que pour la météo : deux modèles qui divergent s'affichent
    comme un désaccord, jamais moyennés. Ici ce n'est pas deux modèles mais deux
    mesures — le « filtered ascend » que BRouter annonce pour la boucle, et le
    D+ que `denivele_filtre` recalcule sur le parcours placé, hystérésis de 2 m
    comprise. Elles ont différé de −33 % sur un cas mesuré, alors qu'un
    aller-retour devrait plutôt *augmenter* le D+. La provenance est écrite
    dans chaque artefact (`(moteur)`, `(parcours placé)`), mais sans cette
    note il faudrait ouvrir le GPX pour voir le désaccord.
    """
    lignes: list[str] = []
    if "parcours" in presentes:
        lignes.append(
            f"Boucle {nombre_fr(proposition.trace.distance_m / 1000, 1)} km, parcours réellement "
            f"roulé {nombre_fr(proposition.distance_parcours_m / 1000, 1)} km "
            f"({proposition.demi_tours} demi-tour(s)) : le GPX porte le parcours, la carte "
            "montre la boucle. La colonne « temps » va avec le parcours."
        )
    moteur, parcours = proposition.trace.denivele_m, proposition.denivele_parcours_m
    if moteur is not None and parcours is not None and abs(moteur - parcours) > ECART_DENIVELE_M:
        lignes.append(
            f"D+ : {moteur:.0f} m annoncés par le moteur pour la boucle, {parcours:.0f} m "
            "recalculés sur le parcours placé — deux méthodes, pas deux parcours "
            "(le recalcul efface les vallonnements de moins de 2 m)."
        )
    return lignes


def _ligne_modele_meteo(propositions: list[Proposition], config: Config) -> list[str]:
    """Nomme le modèle météo utilisé, et le dit haut quand c'est un repli.

    Sans cette ligne, un repli sur le second avis passerait en silence — ce
    que la règle « deux modèles météo qui divergent s'affichent comme un
    désaccord » interdit, et ici un seul des deux a pu répondre.
    """
    meteo = next((p.meteo for p in propositions if p.meteo is not None), None)
    if meteo is None or not meteo.modele_utilise:
        return []
    if meteo.repli:
        return [
            f"Météo : {config.meteo.modele} ne couvre pas cette fenêtre — bascule sur "
            f"{meteo.modele_utilise} (second avis, configuré en repli)."
        ]
    return [f"Météo : modèle {meteo.modele_utilise}."]


def _entete(propositions: list[Proposition], contexte: _Contexte, presentes: set[str]) -> list[str]:
    seance, demande, config = contexte.seance, contexte.demande, contexte.config
    # Trois cas et non deux : une réponse à la question
    # d'orientation au vent dirige la recherche elle aussi. Dire « dans toutes
    # les directions » alors qu'on a cherché au sud-ouest serait faux.
    azimuts_vent = (
        contexte.question_vent.azimuts_pour(demande.vent) if contexte.question_vent is not None else ()
    )
    if demande.azimut_deg is not None:
        direction = f"vers {demande.direction} ({demande.azimut_deg:.0f}°)"
    elif azimuts_vent:
        # Au pluriel quand le travers en a ouvert deux : « vers 315° » sur une
        # recherche qui a exploré 315° et 135° ferait chercher sur la carte une
        # cohérence qui n'existe pas.
        direction = (
            f"vers {_azimuts(azimuts_vent)}, "
            f"{'directions imposées' if len(azimuts_vent) > 1 else 'direction imposée'} par "
            f"--vent {demande.vent}"
        )
    else:
        direction = "dans toutes les directions (aucune --direction demandée)"
    lignes = [
        f"Sortie du {seance.jour.isoformat()} — « {seance.nom} »",
        f"Séance : {_duree_longue(seance.duree_s)}, {len(seance.etapes)} étape(s), "
        f"{len(seance.blocs())} bloc(s)",
        f"Boucle depuis {config.depart.nom} — {contexte.distance_km:g} km {direction}, "
        f"profil {demande.profil}",
        f"Départ {date_en_francais(demande.depart)} — vitesse de la séance sur le tracé "
        f"{nombre_fr(propositions[0].vitesse_kmh, 1)} km/h (heures de passage météo)",
        f"Distance : {contexte.distance_source}",
        f"Modèle physique : {contexte.provenance_modele}",
    ]
    # Pas un test sur « défaut » seul : les vélos non calibrés reçoivent les
    # valeurs de `physique.litterature`, dont la provenance ne dit pas
    # « défaut » — et l'avertissement disparaîtrait justement dans le cas où
    # il sert le plus (on ne présente jamais une estimation comme une mesure).
    # Ce qui compte, c'est « mesuré sur ce vélo ou non ».
    if not contexte.provenance_modele.startswith("calibration"):
        lignes.append(
            "⚠ aucun vélo calibré : les vitesses, donc la position des blocs, reposent sur un "
            f"CdA et un Crr qui viennent de la {contexte.provenance_modele.split(' (')[0]} "
            "et n'ont pas été mesurés sur vous (`ourouler calibrer`)."
        )
    lignes += _ligne_modele_meteo(propositions, config)
    lignes += _lignes_vent(contexte)
    if seance.meta.get("puissance_approximee"):
        lignes.append("⚠ puissances approximées : la séance est prescrite en zones de fréquence cardiaque.")
    if seance.meta.get("seances_ignorees"):
        # S1 : `ourouler seance` le disait, `ourouler sortie` non — et c'est
        # justement la commande qui construit une boucle entière pour la séance
        # choisie. Le choix (la plus longue) ne doit pas rester dans `meta`.
        autres = ", ".join(str(n) for n in seance.meta["seances_ignorees"])
        lignes.append(
            f"Autre(s) séance(s) vélo ce jour-là, ignorée(s) au profit de la plus longue : {autres}."
        )
    if contexte.ecartees:
        # Deux motifs cohabitent ici : la séance qui ne tient
        # pas sur le tracé, et la boucle trop loin de la distance demandée.
        # Chaque ligne porte le sien ; l'en-tête ne préjuge plus duquel il
        # s'agit, sous peine d'annoncer « la séance n'y tenait pas » pour une
        # direction que le placement n'a jamais vue.
        lignes.append(f"{len(contexte.ecartees)} candidate(s) écartée(s) —")
        for ecartee in contexte.ecartees:
            lignes.append(
                f"    {azimut_texte(ecartee.azimut_deg)} "
                f"{nombre_fr(ecartee.distance_km, 1)} km : {ecartee.motif}"
            )
    lignes.append(
        "Tri : note de placement (km équivalents) d'abord, pluie cumulée ensuite ; "
        "plus bas = mieux. La note additionne le terrain sous les blocs (vent de face "
        "compris), le coût — faible et sans seuil — de chaque minute "
        "de retour au calme en trop, et la pénalité, elle très lourde, d'une séance "
        "amputée : rentrer plus tard est normal, ne pas rouler la séance ne l'est pas. "
        f"À note égale à {config.seance.tolerance_egalite * 100:.0f} % près, c'est la "
        "pluie cumulée qui décide (`tolerance_egalite`, config [seance])."
    )
    lignes.append(
        f"« blocs bien placés » : note du couloir sous {nombre_fr(NOTE_BLOC_BIEN_PLACE, 1)} km "
        "équivalent, soit moins qu'un feu rouge."
    )
    if "meteo" not in presentes:
        lignes.append("Météo indisponible : colonnes pluie et vent absentes, aucune tenue conseillée.")
    return lignes


def _mesures_presentes(propositions: list[Proposition]) -> set[str]:
    presentes = set()
    if any(p.meteo is not None for p in propositions):
        presentes.add("meteo")
    if any(p.part_connue is not None for p in propositions):
        presentes.add("connu")
    if any(p.demi_tours for p in propositions):
        presentes.add("demi_tours")
    if any(abs(p.distance_parcours_m - p.trace.distance_m) > ECART_PARCOURS_M for p in propositions):
        presentes.add("parcours")
    return presentes


def _cellules(proposition: Proposition, presentes: set[str], compteur_info: dict | None = None) -> list[str]:
    trace, couts, meteo = proposition.trace, proposition.couts, proposition.meteo
    partiels = bool(trace.meta.get("couts_partiels"))
    cellules = [
        str(proposition.numero),
        f"{nombre_fr(trace.distance_m / 1000, 1)} km",
        f"{trace.denivele_m:.0f} m" if trace.denivele_m is not None else ABSENT,
    ]
    if "parcours" in presentes:
        cellules.append(f"{nombre_fr(proposition.distance_parcours_m / 1000, 1)} km")
    cellules += [
        _temps_texte(proposition, compteur_info),
        ABSENT if partiels else f"{nombre_fr(couts.km_trafic, 1)} km",
    ]
    if "connu" in presentes:
        cellules.append(
            f"{proposition.part_connue * 100:.0f} %" if proposition.part_connue is not None else ABSENT
        )
    if "meteo" in presentes:
        cellules += [
            f"{nombre_fr(meteo.pluie_cumulee_mm, 1)} mm" if meteo is not None else ABSENT,
            f"{meteo.part_vent_face * 100:.0f} %" if meteo is not None else ABSENT,
        ]
    cellules += [
        nombre_fr(proposition.placement.note_totale, 2),
        f"{proposition.blocs_bien_places}/{len(proposition.placement.blocs())}",
    ]
    if "demi_tours" in presentes:
        cellules.append(str(proposition.demi_tours) if proposition.demi_tours else ABSENT)
    return cellules


#: Libellé humain d'un type d'étape non-bloc, pour l'affichage texte.
_LIBELLES_ETAPE = {
    "echauffement": "échauffement",
    "recuperation": "récupération",
    "calme": "retour au calme",
}


def _seance_placee(proposition: Proposition, contexte: _Contexte) -> list[str]:
    """La séance posée sur la candidate retenue, étape par étape, motifs en clair.

    Toutes les étapes de la séance apparaissent, pas seulement les blocs
    (décision Q13, `docs/journal/questions/questions_mainteneur.md`) : `seance.placement` mémorise la position
    de chacune. Seuls les blocs portent une note — aucun terrain n'est évalué
    sous une récupération — donc la colonne reste vide pour le reste plutôt
    que de porter un tiret ambigu. Le décalage de la Z2 d'ouverture et la durée
    totale disent, eux, ce qui arrive aux extrémités.

    Le kilomètre affiché est `debut_parcouru_m`, le compteur — jamais
    `debut_m`, qui repère une position sur le tracé et peut reculer après un
    demi-tour. Un lecteur qui roule veut lire un compteur qui monte, pas la
    géométrie du tracé ; le demi-tour se dit par ailleurs, en toutes lettres.
    """
    placement = proposition.placement
    seance = contexte.seance
    note = nombre_fr(placement.note_totale, 2)
    if placement.penalite_seance > 0:
        note += (
            # « extrémités » et non « séance non tenue » : cette pénalité
            # additionne deux choses de natures différentes — une
            # séance amputée, qui est un défaut, et le dépassement du retour au
            # calme, qui n'en est pas un. Le détail se lit deux lignes plus bas.
            f" = terrain {nombre_fr(placement.note_terrain, 2)} + extrémités "
            f"{nombre_fr(placement.penalite_seance, 2)}"
        )
    lignes = [
        f"Séance placée sur la candidate n° {proposition.numero} (note {note}) :",
        f"    Z2 d'ouverture allongée de {minutes_signees(placement.decalage_z2_s)} — c'est elle qui "
        "fait coulisser les blocs le long du tracé.",
    ]
    numero_bloc = 0
    for emplacement in placement.emplacements:
        etape = seance.etapes[emplacement.etape_idx]
        fin = emplacement.debut_parcouru_m + emplacement.longueur_m
        km = (
            f"km {nombre_fr(emplacement.debut_parcouru_m / 1000, 1)} → {nombre_fr(fin / 1000, 1)} "
            f"({nombre_fr(emplacement.longueur_m / 1000, 1)} km, {duree_h_min(etape.duree_s)}, "
            f"{_puissance(etape)})"
        )
        demi_tour = " — demi-tour" if emplacement.demi_tour else ""
        if emplacement.note is not None:
            numero_bloc += 1
            lignes.append(
                f"    bloc {numero_bloc} — {km} : note {nombre_fr(emplacement.note.note, 2)}{demi_tour}"
            )
            if emplacement.note.note >= NOTE_BLOC_BIEN_PLACE:
                for motif in emplacement.note.motifs or ["aucun motif détaillé"]:
                    lignes.append(f"        • {motif}")
        else:
            libelle = _LIBELLES_ETAPE.get(etape.type, etape.type)
            lignes.append(f"    {libelle} — {km}{demi_tour}")
    lignes.append(
        f"    Retour au calme : {_duree_longue(placement.duree_totale_s)} et "
        f"{nombre_fr(placement.distance_totale_m / 1000, 1)} km au total — il absorbe ce qui reste."
    )
    for information in placement.informations:
        lignes.append(f"    {information}")
    for avertissement in placement.avertissements:
        lignes.append(f"    ⚠ {avertissement}")
    return lignes


def _tenue_lignes(contexte: _Contexte) -> list[str]:
    tenue = contexte.tenue
    if tenue is None:
        return ["Tenue : pas de météo pour ce jour, aucun conseil de tenue.", ""]
    lignes = [
        f"Tenue conseillée — {tenue.categorie_temp}, {tenue.categorie_humidite} :",
        f"    au départ : {_liste(tenue.base)}",
    ]
    if tenue.a_emporter:
        lignes.append(f"    à emporter : {_liste(tenue.a_emporter)}")
    if tenue.a_enlever:
        lignes.append(f"    à prévoir d'enlever : {_liste(tenue.a_enlever)}")
    for motif in tenue.motifs:
        lignes.append(f"    • {motif}")
    lignes.append("")
    return lignes


def _tenue_courte(tenue: Tenue) -> str:
    morceaux = [f"{tenue.categorie_temp}, {tenue.categorie_humidite} — {_liste(tenue.base)}"]
    if tenue.a_emporter:
        morceaux.append("emporter " + _liste(tenue.a_emporter))
    if tenue.a_enlever:
        morceaux.append("prévoir d'enlever " + _liste(tenue.a_enlever))
    return " ; ".join(morceaux)


# --- petits rendus -------------------------------------------------------------


def _puissance(etape) -> str:
    bas, haut = etape.puissance_min_w, etape.puissance_max_w
    if bas is None and haut is None:
        return etape.libelle_court or "sans consigne"
    if bas is None or haut is None:
        return f"{(bas if bas is not None else haut):.0f} W"
    return f"{bas:.0f} W" if bas == haut else f"{bas:.0f}-{haut:.0f} W"


def _azimuts(azimuts_deg: Sequence[float]) -> str:
    """Un azimut, ou deux joints par « et » — le travers en ouvre deux.

    Écrire « 315° » quand la recherche a exploré 315° **et** 135° serait faux
    au même titre que « dans toutes les directions » quand une seule a été
    explorée : le lecteur doit pouvoir retrouver sur la carte ce qu'on lui dit
    d'avoir cherché.
    """
    if not azimuts_deg:
        return "direction inconnue"
    return " et ".join(azimut_texte(a) for a in azimuts_deg)


def _liste(elements) -> str:
    return ", ".join(elements) if elements else "rien de particulier"


def _temps_texte(proposition: Proposition, compteur_info: dict | None) -> str:
    """« 2:14 » seul, ou « 2:20-2:31 / 2:14 » — porte à porte en fourchette / sans arrêt.

    Même ordre, même choix d'affichage et même légende (`ligne_temps_ecoule`)
    que `boucle` : le porte à porte d'abord, parce que c'est lui qui répond à
    la durée demandée, et une cellule combinée plutôt qu'une colonne de plus.
    Le temps sans arrêt est celui du **parcours réellement roulé**
    (`duree_totale_s`, demi-tours compris), pas celui de la boucle : c'est
    déjà la règle de la colonne « temps » elle-même (voir
    `_notes_sous_tableau`).
    """
    placement = proposition.placement
    if compteur_info is None:
        return duree_h_min(placement.duree_totale_s)
    pp = porte_a_porte(placement.duree_totale_s, compteur_info)
    return f"{duree_h_min(pp.bas_s)}-{duree_h_min(pp.haut_s)} / {duree_h_min(placement.duree_totale_s)}"


def _duree_longue(secondes: float) -> str:
    minutes = int(round(secondes / 60))
    return f"{minutes} min" if minutes < 60 else f"{minutes // 60} h {minutes % 60:02d}"
