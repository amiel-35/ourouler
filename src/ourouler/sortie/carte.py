"""La carte de vérification : le tracé, les blocs là où ils tombent, le profil.

C'est le livrable que le mainteneur a demandé pour **voir** ce que le
placement a décidé : « on voit d'un coup d'œil qu'un bloc traverse un bourg »
(cadrage du sprint 4). La page est un fichier HTML autonome — Leaflet et le
fond OpenStreetMap sont les deux seules ressources externes, tout le reste
(données, styles, script) est dans le fichier.

Ce module ne lit ni fichier, ni configuration, ni réseau, et ne connaît
aucune coordonnée : **la géométrie vient du `Trace` qu'on lui passe**, les
emplacements du `Placement`. Il n'invente aucune règle : les notes et les
motifs sont ceux de `seance.terrain`, recopiés tels quels.

Quatre couches sur la carte :

- le tracé complet en gris (`COULEUR_TRACE`), dessous — ce que la séance ne
  parcourt **jamais** ;
- chaque **bloc** dans une couleur vive, avec son numéro et sa note ; au
  survol, ses motifs ;
- chaque autre étape (échauffement, récupérations, retour au calme) en
  **pointillés clairs** (`COULEUR_LIAISON`), sur sa propre position — Q13,
  lot L5.2. Ces portions-là ne sont pas notées — décision du 13/09, une
  récupération absorbe le point dur et ne se juge pas — mais elles sont
  roulées, et la carte doit le montrer : c'est tout le défaut que Q13
  signalait (« t'as pas oublié l'échauffement ? ») ;
- des **flèches de vent**, une par échantillon météo assez venté (lot du
  16/09/2026) : le sprint 5 a mis le vent dans le placement, il déplace les
  blocs de plusieurs kilomètres, et sans une flèche sur la carte personne ne
  peut vérifier à l'œil que ce déplacement est cohérent avec le vent réel —
  exactement la leçon de Q13, appliquée cette fois au vent plutôt qu'à la
  séance entière. La flèche pointe d'où vient le vent, comme une girouette ;
  sa forme (pleine, creuse ou en pointillés) dit si ce vent est de face, dans
  le dos ou de travers **au cap suivi à cet endroit** — `vent_relatif` de
  `meteo.rapport`, pas une règle réinventée ici. Chiffres à côté : vitesse
  moyenne puis rafale, en km/h. En dessous de `SEUIL_AFFICHAGE_VENT_KMH`,
  rien n'est dessiné — voir la constante pour la raison.

Sous la carte, le **profil d'altitude** en SVG, avec les mêmes couleurs aux
mêmes endroits : une descente sous un bloc s'y voit mieux que sur la carte.

Un demi-tour dessine bien une portion de liaison pour sa récupération : le
couloir qu'elle emprunte (aller et retour) est le même que le bloc qui
précède, mais elle est roulée deux fois là où le bloc ne l'est qu'une —
d'où la pénalité du bloc suivant et le motif « demi-tour » dans son
étiquette, pendant que la récupération, elle, reste sans note.

**La page du jour** (lot L5.4, `construire_page_jour`) réutilise tout ce qui
précède : c'est la même carte, une par proposition contrastée, superposées.
Décision du 16/09/2026 (Q18, contrat du sprint 5 §4.1) — « une carte et 3
itinéraires superposés qui se mettent en grisé ou en surbrillance, c'est la
méthode de Strava et des GPS » — retenue contre trois cartes séparées, parce
que c'est la seule forme qui montre **où** les propositions divergent.
Correction du 16/09/2026 (Q20, contrat de la mise en service) : la
sélectionnée est **pleine de bout en bout** — blocs en couleurs vives,
liaisons en couleur franche, et sa boucle non parcourue en fond, sous ses
blocs, pour que la portion au-delà d'un demi-tour ne reste plus invisible.
Les autres propositions passent en **pointillé gris** — le pointillé ne veut
plus dire « ce n'est pas un bloc » (héritage de L5.2) mais « ce n'est pas la
sélection », et rien d'autre : un seul sens, celui que le mainteneur a
demandé. Les miniatures sous la carte ne sont pas perdues : elles deviennent
le sélecteur, chacune avec sa phrase de distinction (`sortie.contraste`) et
ses chiffres — jamais un onglet, un onglet cache et comparer demande de voir
ensemble.
"""

from __future__ import annotations

import base64
import bisect
import html
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime

from ourouler.boucle.meteo_trace import MeteoTrace
from ourouler.boucle.trace import PointTrace, Trace, distance_m
from ourouler.seance.modele import Seance
from ourouler.seance.placement import Emplacement, Placement
from ourouler.seance.vent import SEUIL_VENT_SENSIBLE_KMH

#: Version épinglée de Leaflet, servie par le CDN autorisé.
LEAFLET_VERSION = "1.9.4"
LEAFLET_CSS = f"https://cdnjs.cloudflare.com/ajax/libs/leaflet/{LEAFLET_VERSION}/leaflet.min.css"
LEAFLET_JS = f"https://cdnjs.cloudflare.com/ajax/libs/leaflet/{LEAFLET_VERSION}/leaflet.min.js"

#: Fond de carte : OpenStreetMap, avec l'attribution que sa licence impose.
#: L'ODbL demande une attribution qui **pointe** vers la page de licence, pas
#: seulement le nom du projet : c'est un lien, et Leaflet le rend tel quel.
TUILES_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
TUILES_ATTRIBUTION = (
    '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
)

#: Couleurs des blocs, dans l'ordre. Vives et distinctes les unes des autres,
#: y compris pour un œil qui confond le rouge et le vert : la teinte n'est pas
#: le seul repère, chaque bloc porte aussi son numéro.
COULEURS_BLOCS = (
    "#d7263d",  # rouge
    "#1b6ca8",  # bleu
    "#f18f01",  # orange
    "#5b2a86",  # violet
    "#0b8457",  # vert
    "#c2185b",  # magenta
    "#00838f",  # cyan foncé
    "#6d4c41",  # brun
)

#: Le tracé, sous les blocs.
COULEUR_TRACE = "#8c8c8c"
#: Les liaisons non notées (échauffement, récupérations, retour au calme).
COULEUR_LIAISON = "#9fb8cd"
#: Le tracé d'une proposition **non sélectionnée**, sur la page du jour
#: (`construire_page_jour`), toujours en pointillé (Q20 b — le pointillé ne
#: veut plus dire que « ce n'est pas la sélection »). Assombri le 16/09/2026
#: (Q20 b) : `#c9c9c9` ne se lisait pas sur les tuiles OpenStreetMap denses
#: (vérifié à l'œil sur la zone de Rennes) — réglé, pas mesuré.
COULEUR_AUTRE_PROPOSITION = "#707070"

#: Nombre maximal de points du profil d'altitude. Au-delà, on sous-échantillonne :
#: un SVG de 3 000 points ne se lit pas mieux qu'un de 800, il pèse seulement
#: quatre fois plus.
POINTS_PROFIL_MAX = 800

#: Vent moyen en dessous duquel aucune flèche n'est dessinée, en km/h.
#:
#: **Remontée dans `seance.vent` au lot L5.3** sous le nom
#: `SEUIL_VENT_SENSIBLE_KMH`, avec sa justification (échelle de Beaufort) :
#: la question de l'orientation au vent se pose exactement quand les flèches
#: se dessinent, et deux constantes égales par hasard auraient fini par
#: diverger. Le nom local reste, c'est le même objet.
SEUIL_AFFICHAGE_VENT_KMH = SEUIL_VENT_SENSIBLE_KMH

#: Dimensions du dessin du profil, en unités du `viewBox`.
PROFIL_LARGEUR = 1000.0
PROFIL_HAUTEUR = 220.0
PROFIL_MARGES = (48.0, 16.0, 28.0, 12.0)  # gauche, droite, bas, haut


@dataclass(frozen=True)
class _Portion:
    """Un morceau de tracé à dessiner : sa géométrie et ce qu'on en dit."""

    points: list[list[float]]
    debut_m: float
    fin_m: float


def construire(
    trace: Trace,
    seance: Seance,
    placement: Placement,
    *,
    titre: str = "",
    sous_titre: str = "",
    notes: Sequence[str] = (),
    meteo: MeteoTrace | None = None,
) -> str:
    """La page HTML complète, prête à être écrite dans un fichier.

    `titre` par défaut : le nom de la séance et son jour. `notes` sont des
    phrases ajoutées sous la légende — la commande y met ce qu'elle sait et
    que la carte ne montre pas (distance, D+, météo, tenue). `meteo` est
    optionnel : à `None` (le défaut), la carte se construit exactement comme
    avant les flèches de vent — aucune régression pour un appelant qui ne
    passe pas cet argument.
    """
    titre = titre or f"{seance.nom} — {seance.jour.isoformat()}"
    cumuls = _cumuls(trace.points)

    blocs = _blocs(trace, seance, placement, cumuls)
    liaisons = _liaisons(trace, placement, cumuls)
    fleches_vent = _vent_fleches(meteo)
    trace_js = [[round(p.lat, 6), round(p.lon, 6)] for p in trace.points]
    depart = trace_js[0] if trace_js else [0.0, 0.0]

    donnees = {
        "trace": trace_js,
        "blocs": [
            {
                "n": b["n"],
                "couleur": b["couleur"],
                "pts": b["pts"],
                "infobulle": b["infobulle"],
                "etiquette": b["etiquette"],
                "milieu": b["milieu"],
            }
            for b in blocs
        ],
        "liaisons": [liaison.points for liaison in liaisons],
        "vent": fleches_vent,
        "depart": depart,
        "couleurs": {"trace": COULEUR_TRACE, "liaison": COULEUR_LIAISON},
        "tuiles": {"url": TUILES_URL, "attribution": TUILES_ATTRIBUTION},
    }

    return _page(
        titre=titre,
        sous_titre=sous_titre,
        notes=notes,
        donnees=donnees,
        blocs=blocs,
        profil=_profil_svg(trace, cumuls, blocs),
        avec_vent=meteo is not None,
    )


# --- ce qu'on dessine ---------------------------------------------------------


def _blocs(
    trace: Trace, seance: Seance, placement: Placement, cumuls: Sequence[float]
) -> list[dict]:
    """Un dictionnaire par bloc : géométrie, couleur, étiquette, infobulle.

    `placement.blocs()`, pas `placement.emplacements` : depuis le lot L5.2
    (Q13), ce dernier porte aussi l'échauffement, les récupérations et le
    retour au calme, qui n'ont pas de note — `emplacement.note.note`
    lèverait sur l'un d'eux. `_liaisons` s'occupe de les dessiner.
    """
    dessins = []
    for numero, emplacement in enumerate(placement.blocs(), start=1):
        couleur = COULEURS_BLOCS[(numero - 1) % len(COULEURS_BLOCS)]
        portion = _portion(trace, cumuls, emplacement.debut_m, emplacement.longueur_m)
        etape = _etape(seance, emplacement)
        dessins.append(
            {
                "n": numero,
                "couleur": couleur,
                "pts": portion.points,
                "milieu": _milieu(portion.points),
                "etiquette": f"{numero} · {_fr(emplacement.note.note, 1)}",
                "infobulle": _infobulle(numero, emplacement, etape),
                # Position sur le tracé, pas le compteur : c'est ce dont le
                # profil d'altitude a besoin pour placer sa bande (`cumuls`
                # est lui aussi indexé sur le tracé). Le compteur, lui, ne
                # sert qu'à l'affichage humain — voir `_infobulle`.
                "debut_m": emplacement.debut_m,
                "fin_m": emplacement.debut_m + emplacement.longueur_m,
                "note": emplacement.note.note,
            }
        )
    return dessins


def _etape(seance: Seance, emplacement: Emplacement):
    etapes = seance.etapes
    if 0 <= emplacement.etape_idx < len(etapes):
        return etapes[emplacement.etape_idx]
    return None


def _infobulle(numero: int, emplacement: Emplacement, etape) -> str:
    """Ce que le survol affiche : la consigne, la position, la note, les motifs.

    Le kilomètre montré est `debut_parcouru_m`, le compteur — jamais
    `debut_m`, une position sur le tracé qui recule après un demi-tour. Deux
    blocs qui reprennent le même couloir (un demi-tour) afficheraient sinon
    « km 11,4 » tous les deux : correct pour qui lit le code, un moteur cassé
    pour qui lit un compteur de vélo. Le demi-tour se dit par ailleurs, en
    toutes lettres, plutôt que par un second nombre appelé « km ».
    """
    note = emplacement.note
    lignes = [f"<b>Bloc {numero}</b>"]
    if etape is not None:
        consigne = etape.libelle_court or etape.type
        duree = f"{int(round(etape.duree_s)) // 60}:{int(round(etape.duree_s)) % 60:02d}"
        puissances = [p for p in (etape.puissance_min_w, etape.puissance_max_w) if p is not None]
        watts = f" — {min(puissances):.0f}-{max(puissances):.0f} W" if puissances else ""
        lignes.append(html.escape(f"{consigne} · {duree}{watts}"))
    fin_parcourue = emplacement.debut_parcouru_m + emplacement.longueur_m
    lignes.append(
        f"km {_fr(emplacement.debut_parcouru_m / 1000, 1)} → {_fr(fin_parcourue / 1000, 1)} "
        f"({_fr(emplacement.longueur_m / 1000, 1)} km)"
    )
    lignes.append(f"note {_fr(note.note, 2)} km équivalents")
    if emplacement.demi_tour:
        lignes.append("demi-tour : le couloir précédent, repris en sens inverse")
    for motif in note.motifs:
        lignes.append("• " + html.escape(motif))
    if not note.motifs:
        lignes.append("• rien à signaler sur ce couloir")
    return "<br>".join(lignes)


def _liaisons(trace: Trace, placement: Placement, cumuls: Sequence[float]) -> list[_Portion]:
    """Les portions non notées : échauffement, récupérations, retour au calme.

    Depuis le lot L5.2 (Q13), chacune est un `Emplacement` à part entière —
    on la dessine donc **directement**, sur son propre `debut_m`/`longueur_m`,
    au lieu de deviner un trou entre deux blocs par soustraction. L'ancienne
    méthode (« ce qui n'est pas un bloc ») peignait tout ce qui suit le
    dernier bloc jusqu'à la fin du tracé, y compris la portion qu'un
    demi-tour ne fait jamais rouler — exactement le défaut que Q13 signale.
    Nourrir cette fonction avec des positions déjà connues, et non avec un
    calcul de gap, est aussi ce qui rend un demi-tour visible d'un bloc à
    l'autre : la récupération qui y mène a sa propre portion, là où l'ancien
    calcul ne lui trouvait aucun trou (deux couloirs qui se chevauchent).

    Elles ne sont pas notées et ne portent donc ni couleur ni motif — elles
    disent seulement par où l'on passe. Ce qui reste en gris (`COULEUR_TRACE`)
    est donc ce que la séance **ne parcourt jamais** : sur un placement qui
    fait demi-tour, toute la portion au-delà reste grise, et c'est
    précisément ce que la carte doit montrer.
    """
    portions = []
    for emplacement in placement.emplacements:
        if emplacement.note is not None:
            continue  # un bloc : `_blocs` s'en charge
        portion = _portion(trace, cumuls, emplacement.debut_m, emplacement.longueur_m)
        if len(portion.points) >= 2:
            portions.append(portion)
    return portions


# --- flèches de vent -----------------------------------------------------------


def _vent_fleches(meteo: MeteoTrace | None) -> list[dict]:
    """Un point de flèche par échantillon météo assez venté.

    `meteo.echantillons` couvre le tracé complet (comme le tracé gris), pas
    seulement le parcours réellement roulé : un échantillon au-delà d'un
    demi-tour, par exemple, peut donc porter une flèche. C'est le même choix
    que pour le tracé gris — situer la météo sur le terrain — et pas une
    inadvertance.

    Écarté si le vent ou sa direction manque (`None` : `vent_face_ms` de
    `seance.vent` traite pareillement ce cas comme « inconnu », jamais
    « nul ») — sans direction connue, aucune rotation n'aurait de sens, et en
    inventer une (par exemple 0°) affirmerait une direction sans preuve
    (règle absolue 5). Écarté aussi sous `SEUIL_AFFICHAGE_VENT_KMH`.
    """
    if meteo is None:
        return []
    fleches = []
    for e in meteo.echantillons:
        if e.vent_kmh is None or e.vent_depuis_deg is None:
            continue
        if e.vent_kmh < SEUIL_AFFICHAGE_VENT_KMH:
            continue
        fleches.append(
            {
                "pt": [round(e.lat, 6), round(e.lon, 6)],
                # Direction d'où vient le vent (convention météo, 0 = nord,
                # sens horaire) : la flèche s'oriente dessus telle quelle,
                # comme une girouette qui pointe vers d'où souffle le vent.
                "depuis_deg": round(e.vent_depuis_deg, 1),
                "vent_kmh": round(e.vent_kmh),
                "rafale_kmh": round(e.rafales_kmh) if e.rafales_kmh is not None else None,
                # « face »/« dos »/« travers », déjà tranché par
                # `meteo.rapport.vent_relatif` au cap local — voir
                # `boucle.meteo_trace.evaluer`. Jamais recalculé ici.
                "relatif": e.vent_relatif,
            }
        )
    return fleches


# --- géométrie ----------------------------------------------------------------


def _cumuls(points: Sequence[PointTrace]) -> list[float]:
    """Distances cumulées le long du tracé, recalculées si le tracé n'en porte pas.

    Même précaution que `seance.placement` et `boucle.meteo_trace` : un tracé
    importé dont les `dist_m` sont restées à zéro donnerait une carte où tous
    les blocs tombent au même endroit.
    """
    if len(points) < 2:
        return [0.0] * len(points)
    valeurs = [float(p.dist_m) for p in points]
    if valeurs[-1] > 0 and all(b >= a for a, b in zip(valeurs[:-1], valeurs[1:], strict=True)):
        return valeurs
    cumul = [0.0]
    for a, b in zip(points[:-1], points[1:], strict=True):
        cumul.append(cumul[-1] + distance_m(a, b))
    return cumul


def _portion(trace: Trace, cumuls: Sequence[float], debut_m: float, longueur_m: float) -> _Portion:
    """Les `[lat, lon]` du tracé entre `debut_m` et `debut_m + longueur_m`.

    Les deux extrémités sont interpolées entre les points encadrants, comme le
    fait `seance.terrain` pour noter le couloir : sans cela, un bloc dessiné
    commencerait jusqu'à cent mètres avant ou après là où il commence
    vraiment. Sur une boucle fermée, un couloir qui dépasse la fin du tracé
    repart du début.
    """
    total = cumuls[-1] if cumuls else 0.0
    if total <= 0 or len(trace.points) < 2 or longueur_m <= 0:
        return _Portion(points=[], debut_m=debut_m, fin_m=debut_m + longueur_m)
    boucle = trace.bornee()
    debut = debut_m % total if boucle else min(max(debut_m, 0.0), total)
    fin = debut + longueur_m
    if fin <= total or not boucle:
        points = _entre(trace.points, cumuls, debut, min(fin, total))
    else:
        points = _entre(trace.points, cumuls, debut, total)
        reste = min(fin - total, total)
        suite = _entre(trace.points, cumuls, 0.0, reste)
        points = points + suite[1:] if points else suite
    return _Portion(points=points, debut_m=debut_m, fin_m=debut_m + longueur_m)


def _entre(
    points: Sequence[PointTrace], cumuls: Sequence[float], debut: float, fin: float
) -> list[list[float]]:
    """La géométrie entre deux distances du tracé, extrémités interpolées."""
    if fin <= debut:
        return []
    sortie = [_interpoler(points, cumuls, debut)]
    i = bisect.bisect_right(list(cumuls), debut)
    while i < len(points) and cumuls[i] < fin:
        sortie.append([round(points[i].lat, 6), round(points[i].lon, 6)])
        i += 1
    sortie.append(_interpoler(points, cumuls, fin))
    return sortie


def _interpoler(points: Sequence[PointTrace], cumuls: Sequence[float], d: float) -> list[float]:
    """Le `[lat, lon]` à la distance `d`, entre les deux points qui l'encadrent."""
    i = min(max(bisect.bisect_right(list(cumuls), d) - 1, 0), len(points) - 1)
    j = min(i + 1, len(points) - 1)
    portee = cumuls[j] - cumuls[i]
    f = (d - cumuls[i]) / portee if portee > 0 else 0.0
    lat = points[i].lat + (points[j].lat - points[i].lat) * f
    lon = points[i].lon + (points[j].lon - points[i].lon) * f
    return [round(lat, 6), round(lon, 6)]


def _milieu(points: Sequence[Sequence[float]]) -> list[float] | None:
    """Le point du milieu d'une portion : là où on pose l'étiquette du bloc."""
    if not points:
        return None
    return list(points[len(points) // 2])


# --- le profil d'altitude -----------------------------------------------------


def _profil_svg(trace: Trace, cumuls: Sequence[float], blocs: Sequence[dict]) -> str:
    """Le profil d'altitude en SVG, blocs surlignés aux couleurs de la carte.

    Sans altitude sur le tracé, le profil n'est pas dessiné : on le dit
    plutôt que de tracer une ligne plate qui ferait croire à un parcours plat
    (règle absolue 5).
    """
    gauche, droite, bas, haut = PROFIL_MARGES
    altitudes = [(d, p.alt_m) for d, p in zip(cumuls, trace.points, strict=True) if p.alt_m is not None]
    total = cumuls[-1] if cumuls else 0.0
    if len(altitudes) < 2 or total <= 0:
        return '<p class="vide">Pas d\'altitude sur ce tracé : aucun profil à dessiner.</p>'

    echantillons = _sous_echantillonner(altitudes, POINTS_PROFIL_MAX)
    alt_min = min(a for _, a in echantillons)
    alt_max = max(a for _, a in echantillons)
    etendue = max(alt_max - alt_min, 1.0)
    largeur = PROFIL_LARGEUR - gauche - droite
    hauteur = PROFIL_HAUTEUR - haut - bas

    def x(d: float) -> float:
        return gauche + largeur * (d / total)

    def y(a: float) -> float:
        return haut + hauteur * (1.0 - (a - alt_min) / etendue)

    morceaux = [
        f'<svg class="profil" viewBox="0 0 {PROFIL_LARGEUR:.0f} {PROFIL_HAUTEUR:.0f}" '
        'preserveAspectRatio="none" role="img" aria-label="profil d\'altitude">'
    ]
    # Les bandes des blocs d'abord : elles passent derrière la courbe.
    for bloc in blocs:
        debut = max(0.0, min(bloc["debut_m"], total))
        fin = max(0.0, min(bloc["fin_m"], total))
        if fin <= debut:
            continue
        morceaux.append(
            f'<rect x="{x(debut):.1f}" y="{haut:.1f}" width="{x(fin) - x(debut):.1f}" '
            f'height="{hauteur:.1f}" fill="{bloc["couleur"]}" opacity="0.18"></rect>'
        )
    morceaux.append(
        f'<polyline fill="none" stroke="{COULEUR_TRACE}" stroke-width="2" '
        f'points="{_points_svg(echantillons, x, y)}"></polyline>'
    )
    for bloc in blocs:
        dans = [(d, a) for d, a in echantillons if bloc["debut_m"] <= d <= bloc["fin_m"]]
        if len(dans) >= 2:
            morceaux.append(
                f'<polyline fill="none" stroke="{bloc["couleur"]}" stroke-width="3.5" '
                f'points="{_points_svg(dans, x, y)}"></polyline>'
            )
        milieu = (max(0.0, min(bloc["debut_m"], total)) + max(0.0, min(bloc["fin_m"], total))) / 2
        morceaux.append(
            f'<text x="{x(milieu):.1f}" y="{haut - 2:.1f}" text-anchor="middle" '
            f'class="num" fill="{bloc["couleur"]}">{bloc["n"]}</text>'
        )
    # Les deux altitudes extrêmes et quelques kilomètres, pour donner l'échelle.
    morceaux.append(
        f'<line x1="{gauche:.1f}" y1="{haut + hauteur:.1f}" x2="{PROFIL_LARGEUR - droite:.1f}" '
        f'y2="{haut + hauteur:.1f}" stroke="#c8c8c8" stroke-width="1"></line>'
    )
    morceaux.append(
        f'<text x="{gauche - 6:.1f}" y="{y(alt_max) + 4:.1f}" text-anchor="end" class="ax">'
        f"{alt_max:.0f} m</text>"
    )
    morceaux.append(
        f'<text x="{gauche - 6:.1f}" y="{y(alt_min) + 4:.1f}" text-anchor="end" class="ax">'
        f"{alt_min:.0f} m</text>"
    )
    for borne in _graduations(total):
        morceaux.append(
            f'<text x="{x(borne):.1f}" y="{haut + hauteur + 18:.1f}" text-anchor="middle" '
            f'class="ax">{borne / 1000:.0f} km</text>'
        )
    morceaux.append("</svg>")
    return "".join(morceaux)


def _points_svg(echantillons: Sequence[tuple[float, float]], x, y) -> str:
    return " ".join(f"{x(d):.1f},{y(a):.1f}" for d, a in echantillons)


def _sous_echantillonner(
    valeurs: Sequence[tuple[float, float]], maximum: int
) -> list[tuple[float, float]]:
    """Au plus `maximum` points, régulièrement espacés, extrémités conservées."""
    if len(valeurs) <= maximum:
        return list(valeurs)
    pas = len(valeurs) / maximum
    gardes = [valeurs[int(i * pas)] for i in range(maximum)]
    if gardes[-1] != valeurs[-1]:
        gardes.append(valeurs[-1])
    return gardes


def _graduations(total_m: float) -> list[float]:
    """Des bornes kilométriques lisibles : 5, 10 ou 20 km selon la longueur."""
    km = total_m / 1000.0
    pas = 5.0 if km <= 40 else (10.0 if km <= 90 else 20.0)
    bornes, borne = [], 0.0
    while borne <= km:
        bornes.append(borne * 1000.0)
        borne += pas
    return bornes


# --- la page ------------------------------------------------------------------


def _charge_json(donnees: dict) -> str:
    """Le JSON des données, sûr à écrire tel quel dans un `<script>`.

    Aujourd'hui rien ne peut y faire entrer `</script>` — tout le texte libre
    (consignes, motifs) passe par `html.escape` avant d'entrer dans la charge.
    Mais la garantie tient alors à ce chemin-là et non à la sérialisation : le
    jour où un champ arrive sans échappement, la page devient injectable. On
    neutralise donc `<` à la source, ce que le JSON accepte sans changer la
    valeur lue par le navigateur.

    `&` et `\u2028`/`\u2029` n'ont pas besoin du même traitement dans un
    `<script>` classique, mais les échapper ne coûte rien et ferme le cas d'une
    page servie un jour en XHTML ou d'un JSON relu par `eval`.
    """
    return (
        json.dumps(donnees, ensure_ascii=False)
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


#: Le triangle réutilisé par les trois flèches (légende et carte) : pointe en
#: haut au repos (0°), donc orienté nord — la rotation JS l'amène ensuite sur
#: `depuis_deg`.
_FORME_FLECHE_VENT = "M10 1 L17 18 L10 14 L3 18 Z"


def _section_vent() -> str:
    """La légende du vent : trois glyphes, un par vent relatif.

    Triangle plein (face), triangle creux (dos), losange creux (travers) —
    trois **formes** distinctes, pas trois teintes d'une même forme : lisible
    sans dépendre de la couleur (règle du lot : pas seulement rouge/vert pour
    un œil daltonien). Des caractères, pas un `<svg>` : la page ne porte
    ainsi toujours qu'un seul vrai `<svg>`, celui du profil d'altitude — les
    flèches de la carte, elles, sont construites par le script, dans le
    texte du `<script>` et non dans le HTML de la page.
    """
    return f"""<h3>Vent</h3>
<ul class="legende legende-vent">
<li><span class="vent-swatch vent-face">▲</span>face (ralentit)</li>
<li><span class="vent-swatch vent-dos">△</span>dos (pousse)</li>
<li><span class="vent-swatch vent-travers">◇</span>travers</li>
</ul>
<p class="note">La flèche pointe d'où vient le vent, comme une girouette. Chiffres à côté :
vitesse moyenne puis rafale, en km/h. Rien en dessous de {SEUIL_AFFICHAGE_VENT_KMH:.0f} km/h
(en deçà, on ne sent quasiment plus l'air).</p>"""


def _page(
    *, titre: str, sous_titre: str, notes, donnees: dict, blocs, profil: str, avec_vent: bool
) -> str:
    """Le HTML autonome. Les données partent en JSON, jamais interpolées en dur."""
    puces = "".join(
        f'<li><i style="background:{bloc["couleur"]}"></i>bloc {bloc["n"]} — note '
        f"{_fr(bloc['note'], 2)}</li>"
        for bloc in blocs
    )
    lignes_notes = "".join(f"<p class=\"note\">{html.escape(str(n))}</p>" for n in notes)
    section_vent = _section_vent() if avec_vent else ""
    charge = _charge_json(donnees)
    return f"""<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(titre)}</title>
<link rel="stylesheet" href="{LEAFLET_CSS}">
<style>
:root {{ color-scheme: light; }}
body {{ margin: 0; font: 14px/1.45 system-ui, -apple-system, "Segoe UI", sans-serif; color: #1c1c1c;
       background: #fbfbfb; }}
header {{ padding: 12px 16px 8px; }}
h1 {{ font-size: 18px; margin: 0 0 2px; }}
h2 {{ font-size: 13px; font-weight: 400; color: #555; margin: 0; }}
#carte {{ height: 62vh; min-height: 340px; }}
section {{ padding: 10px 16px 20px; }}
h3 {{ font-size: 13px; margin: 14px 0 6px; text-transform: uppercase; letter-spacing: .04em;
     color: #555; }}
/* `svg.profil` et non `svg` : la règle nue s'appliquait aussi au calque SVG
   de Leaflet, à qui elle imposait 220 px de haut et un fond blanc — le tracé
   et les blocs disparaissaient de la carte. */
svg.profil {{ width: 100%; height: 220px; background: #fff; border: 1px solid #e3e3e3;
              border-radius: 6px; }}
.ax {{ font: 10px system-ui, sans-serif; fill: #777; }}
.num {{ font: bold 11px system-ui, sans-serif; }}
ul.legende {{ list-style: none; padding: 0; margin: 6px 0; display: flex; flex-wrap: wrap; gap: 4px 18px; }}
ul.legende i {{ display: inline-block; width: 16px; height: 4px; margin-right: 6px;
                vertical-align: middle; border-radius: 2px; }}
p.note {{ margin: 3px 0; color: #333; }}
p.vide {{ color: #777; font-style: italic; }}
.etiq {{ background: #fff; border: 1px solid #999; border-radius: 9px; padding: 0 5px;
         font: bold 11px system-ui, sans-serif; white-space: nowrap; box-shadow: 0 1px 3px #0003; }}
/* Flèches de vent : forme distincte par vent relatif (pas seulement la teinte,
   lisible pour un œil daltonien) — pleine (face), creuse (dos), pointillée
   (travers). `vent-inconnu` est un repli défensif ; `vent_relatif` ne devrait
   jamais être absent ici, un vent sans direction n'ayant pas de flèche. */
.vent-marqueur {{ display: flex; flex-direction: column; align-items: center; }}
.vent-fleche {{ width: 20px; height: 20px; display: block;
                filter: drop-shadow(0 1px 1px rgba(0,0,0,.35)); }}
.vent-face .fleche-forme {{ fill: #c1440e; stroke: #c1440e; stroke-width: 1; }}
.vent-dos .fleche-forme {{ fill: none; stroke: #1b6ca8; stroke-width: 2.6; stroke-linejoin: round; }}
.vent-travers .fleche-forme {{ fill: none; stroke: #6b6b6b; stroke-width: 1.8;
                                stroke-dasharray: 2.2 2.2; }}
.vent-inconnu .fleche-forme {{ fill: none; stroke: #999; stroke-width: 1.2; stroke-dasharray: 1 3; }}
.vent-etiquette {{ margin-top: 1px; font: 700 10px/1 system-ui, sans-serif; background: #fff;
                    border: 1px solid #999; border-radius: 8px; padding: 1px 4px;
                    white-space: nowrap; box-shadow: 0 1px 2px #0003; }}
ul.legende-vent li {{ display: flex; align-items: center; }}
.vent-swatch {{ display: inline-block; width: 1.3em; margin-right: 6px; text-align: center;
                 font-size: 15px; line-height: 1; }}
.vent-swatch.vent-face {{ color: #c1440e; }}
.vent-swatch.vent-dos {{ color: #1b6ca8; }}
.vent-swatch.vent-travers {{ color: #6b6b6b; }}
</style>
</head>
<body>
<header>
<h1>{html.escape(titre)}</h1>
<h2>{html.escape(sous_titre)}</h2>
</header>
<div id="carte"></div>
<section>
<h3>Blocs</h3>
<ul class="legende">{puces}
<li><i style="background:{COULEUR_TRACE}"></i>tracé</li>
<li><i style="background:{COULEUR_LIAISON}"></i>échauffement, récupérations, retour au calme
(non notés)</li>
</ul>
{lignes_notes}
{section_vent}
<h3>Profil d'altitude</h3>
{profil}
</section>
<script src="{LEAFLET_JS}"></script>
<script>
const D = {charge};
const carte = L.map('carte');
L.tileLayer(D.tuiles.url, {{attribution: D.tuiles.attribution, maxZoom: 19}}).addTo(carte);
const groupe = L.featureGroup();
if (D.trace.length > 1) {{
  L.polyline(D.trace, {{color: D.couleurs.trace, weight: 4, opacity: .85}}).addTo(groupe);
}}
for (const l of D.liaisons) {{
  if (l.length > 1) {{
    L.polyline(l, {{color: D.couleurs.liaison, weight: 5, opacity: .9, dashArray: '6 8'}}).addTo(groupe);
  }}
}}
for (const b of D.blocs) {{
  if (b.pts.length > 1) {{
    L.polyline(b.pts, {{color: b.couleur, weight: 7, opacity: .95}})
      .bindTooltip(b.infobulle, {{sticky: true}})
      .addTo(groupe);
  }}
  if (b.milieu) {{
    L.marker(b.milieu, {{
      icon: L.divIcon({{className: '', html: '<span class="etiq">' + b.etiquette + '</span>',
                        iconSize: null}})
    }}).bindTooltip(b.infobulle).addTo(groupe);
  }}
}}
function iconeVent(f) {{
  const cat = f.relatif || 'inconnu';
  const etiquette = String(f.vent_kmh) + (f.rafale_kmh != null ? '/' + f.rafale_kmh : '');
  const svg = '<svg class="vent-fleche" viewBox="0 0 20 20">'
    + '<g transform="rotate(' + f.depuis_deg + ' 10 10)">'
    + '<path class="fleche-forme" d="{_FORME_FLECHE_VENT}"></path></g></svg>';
  return L.divIcon({{
    className: '',
    html: '<div class="vent-marqueur vent-' + cat + '">' + svg
      + '<span class="vent-etiquette">' + etiquette + '</span></div>',
    iconSize: null,
    iconAnchor: [10, 10],
  }});
}}
function infoVent(f) {{
  const mots = {{face: 'vent de face', dos: 'vent dans le dos', travers: 'vent de travers'}};
  let txt = 'Vent ' + f.vent_kmh + ' km/h';
  if (f.rafale_kmh != null) {{ txt += ', rafale ' + f.rafale_kmh + ' km/h'; }}
  if (mots[f.relatif]) {{ txt += ' — ' + mots[f.relatif]; }}
  return txt;
}}
for (const f of D.vent) {{
  L.marker(f.pt, {{icon: iconeVent(f)}}).bindTooltip(infoVent(f), {{sticky: true}}).addTo(groupe);
}}
groupe.addTo(carte);
L.marker(D.depart).addTo(carte).bindPopup('Départ');
const limites = groupe.getBounds();
// Le cadrage se refait au chargement complet : tant que la mise en page n'est
// pas faite, le conteneur peut mesurer zéro, et `fitBounds` calcule alors le
// zoom maximal — la carte s'ouvrait sur cinquante mètres de bitume.
function cadrer() {{
  carte.invalidateSize();
  if (limites.isValid()) {{ carte.fitBounds(limites, {{padding: [20, 20]}}); }}
  else {{ carte.setView(D.depart, 13); }}
}}
cadrer();
window.addEventListener('load', cadrer);
window.addEventListener('resize', function () {{ carte.invalidateSize(); }});
</script>
</body>
</html>
"""


def _fr(valeur: float, decimales: int) -> str:
    return f"{valeur:.{decimales}f}".replace(".", ",")


# --- la page du jour (lot L5.4) -------------------------------------------------


@dataclass(frozen=True)
class PropositionCarte:
    """Une proposition contrastée telle que la page du jour la dessine.

    Construit par `sortie.commande` à partir d'une `contraste.Retenue` : ce
    module ne sait toujours ni trier ni contraster, seulement dessiner ce
    qu'on lui donne. `distinction` et `chiffres` sont déjà en langage de
    cycliste (`sortie.contraste.phrase`, `sortie.commande._details_proposition`)
    — recopiés tels quels, jamais reformulés ici. `gpx_texte` est le GPX du
    **parcours placé** (demi-tours compris, comme `_ecrire_gpx`) : ce module
    ne l'écrit pas sur disque, il l'embarque dans la page pour un
    téléchargement `blob:` côté navigateur (§4.2 du contrat — « le fichier
    suit le choix du cycliste, pas le classement »).
    """

    numero: int
    trace: Trace
    placement: Placement
    meteo: MeteoTrace | None
    distinction: str
    chiffres: str
    sous_titre: str
    notes: Sequence[str]
    gpx_nom: str
    gpx_texte: str


def construire_page_jour(
    seance: Seance,
    propositions: Sequence[PropositionCarte],
    *,
    titre: str = "",
    motif_deux_propositions: str | None = None,
    maintenant: datetime | None = None,
) -> str:
    """La page du jour : les propositions contrastées, superposées sur une carte.

    Une seule grande carte porte les tracés de toutes les `propositions`.
    La sélectionnée est **pleine de bout en bout** : ses blocs en couleurs
    vives et ses flèches de vent comme avant, ses liaisons (échauffement,
    récupérations, retour au calme) en couleur franche plutôt qu'en
    pointillé, et sa boucle non parcourue en fond, sous ses blocs — Q20 a et
    c, la correction du 16/09/2026 : sans ce fond, la portion au-delà d'un
    demi-tour n'était peinte par personne, et une séance sans bloc (le cas
    courant du mainteneur) n'avait que des liaisons pâles et pointillées.
    Les autres propositions passent en **pointillé gris**
    (`COULEUR_AUTRE_PROPOSITION`) — le pointillé ne veut plus dire « ce
    n'est pas un bloc » mais « ce n'est pas la sélection », et rien d'autre
    (Q20 b) : on ne demande jamais à l'œil de suivre plusieurs choses à la
    fois. Sous la carte, une miniature par proposition sert de sélecteur :
    cliquer en allume une, sans jamais en cacher une autre (pas d'onglet).

    `propositions` vient de `sortie.contraste.choisir(...).retenues`, dans
    l'ordre du tri — la première est celle que l'outil recommande, et c'est
    elle qui est active au chargement. Deux propositions sont un cas normal
    (`motif_deux_propositions` porte alors pourquoi), une seule aussi
    (aucune comparaison n'a de sens, la page le montre sans sélecteur inutile
    à comparer).
    """
    if not propositions:
        raise ValueError("construire_page_jour : au moins une proposition est attendue")
    titre = titre or f"{seance.nom} — {seance.jour.isoformat()}"

    donnees_props = []
    panneaux = []
    bornes = []
    for prop in propositions:
        cumuls = _cumuls(prop.trace.points)
        blocs = _blocs(prop.trace, seance, prop.placement, cumuls)
        liaisons = _liaisons(prop.trace, prop.placement, cumuls)
        fleches_vent = _vent_fleches(prop.meteo)
        trace_js = [[round(p.lat, 6), round(p.lon, 6)] for p in prop.trace.points]
        bornes.extend(trace_js)
        donnees_props.append(
            {
                "n": prop.numero,
                "trace": trace_js,
                "depart": trace_js[0] if trace_js else [0.0, 0.0],
                "blocs": [
                    {
                        "n": b["n"],
                        "couleur": b["couleur"],
                        "pts": b["pts"],
                        "infobulle": b["infobulle"],
                        "etiquette": b["etiquette"],
                        "milieu": b["milieu"],
                    }
                    for b in blocs
                ],
                "liaisons": [liaison.points for liaison in liaisons],
                "vent": fleches_vent,
                "gpx_nom": prop.gpx_nom,
                # Base64, pas le texte brut : le GPX porte l'espace de noms
                # `http://www.topografix.com/GPX/1/1`, et une URL en clair
                # dans la page romprait la promesse « seul le CDN autorisé et
                # OSM sont chargés » — même si ce texte-là n'est qu'une charge
                # JSON, jamais une ressource récupérée. `TextDecoder` côté
                # script décode proprement l'UTF-8 (accents des libellés).
                "gpx_b64": base64.b64encode(prop.gpx_texte.encode("utf-8")).decode("ascii"),
            }
        )
        panneaux.append(
            _panneau_proposition(prop, blocs, prop.meteo is not None, _profil_svg(prop.trace, cumuls, blocs))
        )

    donnees = {
        "propositions": donnees_props,
        "couleurs": {
            "trace": COULEUR_TRACE,
            "liaison": COULEUR_LIAISON,
            "autre": COULEUR_AUTRE_PROPOSITION,
        },
        "tuiles": {"url": TUILES_URL, "attribution": TUILES_ATTRIBUTION},
    }
    return _page_jour(
        horodatage=(maintenant or datetime.now()).strftime("%d/%m/%Y à %H:%M"),
        titre=titre,
        donnees=donnees,
        propositions=propositions,
        panneaux=panneaux,
        motif_deux_propositions=motif_deux_propositions,
    )


def _panneau_proposition(prop: PropositionCarte, blocs: Sequence[dict], avec_vent: bool, profil: str) -> str:
    """Le panneau d'une proposition : sa légende de blocs, ses notes, son profil.

    Affiché seulement pour la proposition active (`hidden` posé par
    `_page_jour` sur les autres) — c'est ce qui rend la météo, la tenue et le
    profil d'altitude propres à chaque direction, sans jamais mélanger deux
    propositions dans un même paragraphe.
    """
    puces = "".join(
        f'<li><i style="background:{b["couleur"]}"></i>bloc {b["n"]} — note {_fr(b["note"], 2)}</li>'
        for b in blocs
    )
    lignes_notes = "".join(f'<p class="note">{html.escape(str(n))}</p>' for n in prop.notes)
    section_vent = _section_vent() if avec_vent else ""
    return f"""<p class="note sous-titre">{html.escape(prop.sous_titre)}</p>
<ul class="legende">{puces}
<li><i style="background:{COULEUR_TRACE}"></i>tracé de cette proposition</li>
<li><i style="background:{COULEUR_LIAISON}"></i>échauffement, récupérations, retour au calme
(non notés)</li>
</ul>
{lignes_notes}
{section_vent}
<h3>Profil d'altitude</h3>
{profil}"""


def _page_jour(
    *,
    titre: str,
    donnees: dict,
    propositions: Sequence[PropositionCarte],
    panneaux: Sequence[str],
    motif_deux_propositions: str | None,
    horodatage: str,
) -> str:
    """Le HTML autonome de la page du jour. Les données partent en JSON, comme `_page`."""
    n = len(propositions)
    premiere = propositions[0]
    accord = "s" if n != 1 else ""
    sous_titre = (
        f"{n} proposition{accord} contrastée{accord}"
        + (" — cliquez une miniature pour l'afficher sur la carte" if n > 1 else "")
    )
    items = []
    for prop in propositions:
        actif = prop is premiere
        recommandee = ' <span class="badge badge-reco">recommandée</span>' if actif else ""
        items.append(
            f"""<div class="carte-item{' actif' if actif else ''}" role="button" tabindex="0"
     aria-pressed="{'true' if actif else 'false'}" data-prop="{prop.numero}">
<div class="mini-carte" aria-hidden="true"></div>
<p class="distinction"><span class="badge">n° {prop.numero}</span>{recommandee}
{html.escape(prop.distinction or "la seule candidate")}</p>
<p class="chiffres">{html.escape(prop.chiffres)}</p>
<a class="gpx-dl" data-prop="{prop.numero}" download="{html.escape(prop.gpx_nom)}" href="#">
Télécharger le GPX</a>
</div>"""
        )
    panneaux_html = "".join(
        f'<div class="panneau-prop" data-prop="{prop.numero}"{"" if prop is premiere else " hidden"}>'
        f"{panneau}</div>"
        for prop, panneau in zip(propositions, panneaux, strict=True)
    )
    motif_html = (
        f'<p class="note motif">{html.escape(motif_deux_propositions)}</p>' if motif_deux_propositions else ""
    )
    charge = _charge_json(donnees)
    return f"""<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(titre)}</title>
<link rel="stylesheet" href="{LEAFLET_CSS}">
<style>
:root {{ color-scheme: light; }}
body {{ margin: 0; font: 14px/1.45 system-ui, -apple-system, "Segoe UI", sans-serif; color: #1c1c1c;
       background: #fbfbfb; }}
header {{ padding: 12px 16px 8px; }}
h1 {{ font-size: 18px; margin: 0 0 2px; }}
h2 {{ font-size: 13px; font-weight: 400; color: #555; margin: 0; }}
/* Q20 d : le conteneur, sans borne de largeur, prenait toute la page — bien
   plus large que haut (jusqu'à ~3:1 mesuré sur une fenêtre courante). Une
   boucle de club est plutôt ronde : `fitBounds` cale alors le zoom sur la
   hauteur et laisse filer la largeur, une vue de ~150 km pour des boucles
   de ~18 km de diamètre (vérifié à l'œil, contrat de la mise en service
   §1 d). `max-width: min(100%, 78vh)` borne le rapport largeur/hauteur à
   78/52 = 1,5 quelle que soit la fenêtre — resserré sans dépendre de JS,
   et sans toucher `fitBounds` lui-même, qui reste correct. */
#carte {{ height: 52vh; min-height: 300px; max-width: min(100%, 78vh); margin: 0 auto; }}
section {{ padding: 10px 16px 20px; }}
h3 {{ font-size: 13px; margin: 14px 0 6px; text-transform: uppercase; letter-spacing: .04em;
     color: #555; }}
svg.profil {{ width: 100%; height: 220px; background: #fff; border: 1px solid #e3e3e3;
              border-radius: 6px; }}
.ax {{ font: 10px system-ui, sans-serif; fill: #777; }}
.num {{ font: bold 11px system-ui, sans-serif; }}
ul.legende {{ list-style: none; padding: 0; margin: 6px 0; display: flex; flex-wrap: wrap; gap: 4px 18px; }}
ul.legende i {{ display: inline-block; width: 16px; height: 4px; margin-right: 6px;
                vertical-align: middle; border-radius: 2px; }}
p.note {{ margin: 3px 0; color: #333; }}
p.horodatage {{ color: #777; font-size: 12px; margin: 14px 16px 24px; }}
p.sous-titre {{ font-weight: 600; color: #1c1c1c; }}
p.motif {{ font-style: italic; }}
p.vide {{ color: #777; font-style: italic; }}
.etiq {{ background: #fff; border: 1px solid #999; border-radius: 9px; padding: 0 5px;
         font: bold 11px system-ui, sans-serif; white-space: nowrap; box-shadow: 0 1px 3px #0003; }}
.vent-marqueur {{ display: flex; flex-direction: column; align-items: center; }}
.vent-fleche {{ width: 20px; height: 20px; display: block;
                filter: drop-shadow(0 1px 1px rgba(0,0,0,.35)); }}
.vent-face .fleche-forme {{ fill: #c1440e; stroke: #c1440e; stroke-width: 1; }}
.vent-dos .fleche-forme {{ fill: none; stroke: #1b6ca8; stroke-width: 2.6; stroke-linejoin: round; }}
.vent-travers .fleche-forme {{ fill: none; stroke: #6b6b6b; stroke-width: 1.8;
                                stroke-dasharray: 2.2 2.2; }}
.vent-inconnu .fleche-forme {{ fill: none; stroke: #999; stroke-width: 1.2; stroke-dasharray: 1 3; }}
.vent-etiquette {{ margin-top: 1px; font: 700 10px/1 system-ui, sans-serif; background: #fff;
                    border: 1px solid #999; border-radius: 8px; padding: 1px 4px;
                    white-space: nowrap; box-shadow: 0 1px 2px #0003; }}
ul.legende-vent li {{ display: flex; align-items: center; }}
.vent-swatch {{ display: inline-block; width: 1.3em; margin-right: 6px; text-align: center;
                 font-size: 15px; line-height: 1; }}
.vent-swatch.vent-face {{ color: #c1440e; }}
.vent-swatch.vent-dos {{ color: #1b6ca8; }}
.vent-swatch.vent-travers {{ color: #6b6b6b; }}
/* Le sélecteur : une miniature par proposition, jamais un onglet — cliquer
   en allume une sans en cacher une autre. Empile à partir de ~480 px, la
   page reste lisible à 400 px (point de vigilance du lot). */
.carte-selecteur {{ display: flex; flex-wrap: wrap; gap: 14px; margin: 4px 0 10px; }}
.carte-item {{ flex: 1 1 230px; max-width: 360px; min-width: 0; border: 2px solid transparent;
               border-radius: 10px; padding: 8px; background: #fff; cursor: pointer;
               box-shadow: 0 1px 3px #0002; }}
.carte-item:focus-visible {{ outline: 2px solid #1b6ca8; outline-offset: 2px; }}
.carte-item.actif {{ border-color: #1b6ca8; box-shadow: 0 0 0 2px rgba(27,108,168,.35); }}
/* `pointer-events: none` : la mini-carte est décorative (zoom, drag, clic
   Leaflet déjà coupés) et ne doit surtout pas avaler le clic qui sélectionne
   la proposition — vérifié à la main (lot L5.4) : sans cette règle, cliquer
   *sur* la miniature ne faisait rien, seul le texte en dessous marchait. */
.mini-carte {{ height: 120px; border-radius: 6px; background: #eef1f3; margin-bottom: 6px;
               pointer-events: none; }}
.badge {{ display: inline-block; font: 700 11px system-ui, sans-serif; color: #fff; background: #666;
          border-radius: 9px; padding: 1px 7px; margin-right: 6px; vertical-align: middle; }}
.carte-item.actif .badge {{ background: #1b6ca8; }}
.badge-reco {{ background: #0b8457; }}
.distinction {{ font-weight: 600; margin: 2px 0; }}
.chiffres {{ font-size: 12px; color: #555; margin: 2px 0 8px; }}
.gpx-dl {{ font-size: 12px; }}
@media (max-width: 480px) {{ .carte-item {{ flex-basis: 100%; max-width: none; }} }}
</style>
</head>
<body>
<header>
<h1>{html.escape(titre)}</h1>
<h2>{html.escape(sous_titre)}</h2>
</header>
<div id="carte"></div>
<section>
<h3>Propositions</h3>
<div class="carte-selecteur">{"".join(items)}</div>
{motif_html}
{panneaux_html}
</section>
<script src="{LEAFLET_JS}"></script>
<script>
const D = {charge};
const carte = L.map('carte');
// Le cadrage se fait **avant** tout ajout de couche (tuiles comprises) :
// un `L.map()` sans vue calcule des coordonnées de tuile `NaN` dès qu'on lui
// ajoute une couche, avant que `fitBounds` n'ait rien fixé — erreur bénigne
// mais réelle (« Invalid LatLng »), trouvée à la vérification manuelle du
// lot L5.4 sur les vraies données. Les bornes englobent **toutes** les
// propositions ; `L.latLngBounds` ne demande pas de carte pour exister.
const limites = L.latLngBounds([]);
for (const p of D.propositions) {{ for (const pt of p.trace) {{ limites.extend(pt); }} }}
if (limites.isValid()) {{ carte.fitBounds(limites, {{padding: [20, 20], animate: false}}); }}
else if (D.propositions[0].depart) {{ carte.setView(D.propositions[0].depart, 13); }}
L.tileLayer(D.tuiles.url, {{attribution: D.tuiles.attribution, maxZoom: 19}}).addTo(carte);

function iconeVent(f) {{
  const cat = f.relatif || 'inconnu';
  const etiquette = String(f.vent_kmh) + (f.rafale_kmh != null ? '/' + f.rafale_kmh : '');
  const svg = '<svg class="vent-fleche" viewBox="0 0 20 20">'
    + '<g transform="rotate(' + f.depuis_deg + ' 10 10)">'
    + '<path class="fleche-forme" d="{_FORME_FLECHE_VENT}"></path></g></svg>';
  return L.divIcon({{
    className: '',
    html: '<div class="vent-marqueur vent-' + cat + '">' + svg
      + '<span class="vent-etiquette">' + etiquette + '</span></div>',
    iconSize: null,
    iconAnchor: [10, 10],
  }});
}}
function infoVent(f) {{
  const mots = {{face: 'vent de face', dos: 'vent dans le dos', travers: 'vent de travers'}};
  let txt = 'Vent ' + f.vent_kmh + ' km/h';
  if (f.rafale_kmh != null) {{ txt += ', rafale ' + f.rafale_kmh + ' km/h'; }}
  if (mots[f.relatif]) {{ txt += ' — ' + mots[f.relatif]; }}
  return txt;
}}

// Une couche « riche » (blocs colorés, liaisons pleines, vent) par
// proposition, construite une fois — visible seulement pour la sélection,
// pleine de bout en bout (Q20 b : le pointillé ne sert plus à distinguer
// un bloc d'une liaison, il ne vaut que pour « pas la sélection »). Ce qui
// empêche le spaghetti (contrat §4.1) : une seule couche riche à la fois.
function construireRiche(p) {{
  const g = L.featureGroup();
  for (const l of p.liaisons) {{
    if (l.length > 1) {{
      L.polyline(l, {{color: D.couleurs.liaison, weight: 5, opacity: .9}}).addTo(g);
    }}
  }}
  for (const b of p.blocs) {{
    if (b.pts.length > 1) {{
      L.polyline(b.pts, {{color: b.couleur, weight: 7, opacity: .95}})
        .bindTooltip(b.infobulle, {{sticky: true}}).addTo(g);
    }}
    if (b.milieu) {{
      L.marker(b.milieu, {{
        icon: L.divIcon({{className: '', html: '<span class="etiq">' + b.etiquette + '</span>',
                          iconSize: null}})
      }}).bindTooltip(b.infobulle).addTo(g);
    }}
  }}
  for (const f of p.vent) {{
    L.marker(f.pt, {{icon: iconeVent(f)}}).bindTooltip(infoVent(f), {{sticky: true}}).addTo(g);
  }}
  return g;
}}

// La boucle complète de chaque proposition est **toujours** affichée
// (Q20 a : avant ce correctif, elle manquait pour la sélection — la portion
// au-delà d'un demi-tour n'était peinte par personne). Son style change
// avec la sélection : fond plein sous les blocs pour la sélectionnée
// (`D.couleurs.trace`, la même teinte que « ce que la séance ne parcourt
// jamais » sur la carte simple), pointillé gris pour les autres
// (`D.couleurs.autre`) — `dashArray: null` efface explicitement le
// pointillé au passage actif, `setStyle` ne fait que fusionner les clés
// données, il n'enlève pas celles qu'on omet.
function styleGris(estActif) {{
  return estActif
    ? {{color: D.couleurs.trace, weight: 3, opacity: .6, dashArray: null}}
    : {{color: D.couleurs.autre, weight: 3, opacity: .85, dashArray: '5 7'}};
}}

let actifN = D.propositions[0].n;
const grisesParN = {{}};
const richesParN = {{}};
for (const p of D.propositions) {{
  if (p.trace.length > 1) {{
    grisesParN[p.n] = L.polyline(p.trace, styleGris(p.n === actifN)).addTo(carte);
  }}
  richesParN[p.n] = construireRiche(p);
}}
richesParN[actifN].addTo(carte);  // ajoutée après toutes les grises : au-dessus

function selectionner(n) {{
  if (n === actifN || !richesParN[n]) return;
  if (grisesParN[actifN]) grisesParN[actifN].setStyle(styleGris(false));
  richesParN[actifN].remove();
  actifN = n;
  if (grisesParN[actifN]) grisesParN[actifN].setStyle(styleGris(true));
  richesParN[actifN].addTo(carte);
  document.querySelectorAll('.panneau-prop').forEach(function (el) {{
    el.hidden = el.dataset.prop !== String(n);
  }});
  document.querySelectorAll('.carte-item').forEach(function (el) {{
    const on = el.dataset.prop === String(n);
    el.classList.toggle('actif', on);
    el.setAttribute('aria-pressed', on ? 'true' : 'false');
  }});
}}

L.marker(D.propositions[0].depart).addTo(carte).bindPopup('Départ');
// Le cadrage (plus haut, avant les tuiles) englobe **toutes** les
// propositions, et ne bouge pas quand on change la sélection : c'est
// justement la comparaison qu'une carte unique permet (contrat §4.1) — un
// cadrage qui suivrait la sélection la briserait. Seule la taille se
// revérifie, au chargement complet et au redimensionnement — le conteneur
// peut avoir mesuré zéro avant que la mise en page ne soit faite.
function cadrer() {{
  carte.invalidateSize();
  if (limites.isValid()) {{ carte.fitBounds(limites, {{padding: [20, 20], animate: false}}); }}
}}
window.addEventListener('load', cadrer);
window.addEventListener('resize', function () {{ carte.invalidateSize(); }});

// Les miniatures : une petite carte statique par proposition, non interactive
// (elle ne fait que montrer, cliquer sélectionne — pas de zoom qui la ferait
// dériver de son rôle de vignette). Construites seulement au `load`, jamais
// avant : un conteneur juste inséré dans le DOM peut encore mesurer zéro
// (la mise en page n'est pas faite), et `fitBounds` sur une carte de taille
// nulle calcule des coordonnées `NaN` — même piège que la grande carte
// (`cadrer`), pour la même raison.
function miniCartes() {{
  document.querySelectorAll('.carte-item').forEach(function (el) {{
    const conteneur = el.querySelector('.mini-carte');
    if (!conteneur || conteneur._mini_init) return;
    const n = Number(el.dataset.prop);
    const p = D.propositions.find(function (x) {{ return x.n === n; }});
    if (!p || p.trace.length < 2) return;
    conteneur._mini_init = true;
    const mini = L.map(conteneur, {{
      zoomControl: false, dragging: false, scrollWheelZoom: false, doubleClickZoom: false,
      boxZoom: false, touchZoom: false, keyboard: false, attributionControl: false,
    }});
    // Même précaution que la grande carte : cadrer **avant** d'ajouter la
    // moindre couche, avec des bornes calculées sur les données brutes plutôt
    // que sur une géométrie déjà posée sur une carte qui n'a pas encore de vue.
    const bornesMini = L.latLngBounds(p.trace);
    mini.invalidateSize();
    mini.fitBounds(bornesMini, {{padding: [4, 4], animate: false}});
    L.polyline(p.trace, {{color: D.couleurs.autre, weight: 2.5}}).addTo(mini);
    for (const b of p.blocs) {{
      if (b.pts.length > 1) {{ L.polyline(b.pts, {{color: b.couleur, weight: 3}}).addTo(mini); }}
    }}
  }});
}}
window.addEventListener('load', miniCartes);

// Le GPX de chaque proposition, en téléchargement : un `<a download>` dont
// l'`href` est une URL `blob:`, ce qui marche aussi bien sur une page
// ouverte par `file://` que servie — vérifié à la main (lot L5.4), pas
// supposé. `TextDecoder` restitue l'UTF-8 du base64 (accents des libellés).
function b64VersUtf8(b64) {{
  const bin = atob(b64);
  const octets = Uint8Array.from(bin, function (c) {{ return c.charCodeAt(0); }});
  return new TextDecoder('utf-8').decode(octets);
}}
document.querySelectorAll('.gpx-dl').forEach(function (lien) {{
  const n = Number(lien.dataset.prop);
  const p = D.propositions.find(function (x) {{ return x.n === n; }});
  if (!p) return;
  const url = URL.createObjectURL(new Blob([b64VersUtf8(p.gpx_b64)], {{type: 'application/gpx+xml'}}));
  lien.href = url;
  lien.download = p.gpx_nom;
}});

document.querySelectorAll('.carte-item').forEach(function (el) {{
  const n = Number(el.dataset.prop);
  el.addEventListener('click', function (ev) {{
    if (ev.target.closest('.gpx-dl')) return;  // laisser le lien télécharger
    selectionner(n);
  }});
  el.addEventListener('keydown', function (ev) {{
    if (ev.target.closest('.gpx-dl')) return;
    if (ev.key === 'Enter' || ev.key === ' ') {{ ev.preventDefault(); selectionner(n); }}
  }});
}});
</script>
<p class="horodatage">Page générée le {horodatage}.</p>
</body>
</html>
"""


# --- la page « rien de prévu » (contrat de l'hébergé minimal) ---------------


def construire_page_sans_seance(jour: date, *, maintenant: datetime | None = None) -> str:
    """La page du jour quand Intervals.icu ne porte aucune séance vélo ce jour-là.

    Le contrat de l'hébergé minimal (docs/heberge_minimal_contrat.md, §
    périmètre point 4) interdit deux choses à la fois : planter, et laisser
    filer en silence la page de la veille. Cette page dit donc en clair
    qu'il n'y a rien à rouler **et** de quand elle date (point 5 du même
    contrat) — `maintenant` est injectable pour les tests, `datetime.now()`
    par défaut : lire l'horloge n'est pas lire l'environnement (règle
    absolue 2 de CLAUDE.md, voir `tests/test_invariants.py`), seul un module
    du cœur qui ouvrirait un fichier ou une variable serait fautif ici.

    Volontairement minimale : pas de carte, pas de Leaflet — rien à dessiner
    un jour sans boucle. Le style reprend celui de `_page`/`_page_jour` pour
    que la page reste reconnaissable.
    """
    maintenant = maintenant or datetime.now()
    titre = f"Rien de prévu — {jour.isoformat()}"
    horodatage = maintenant.strftime("%d/%m/%Y à %H:%M")
    return f"""<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(titre)}</title>
<style>
:root {{ color-scheme: light; }}
body {{ margin: 0; font: 14px/1.45 system-ui, -apple-system, "Segoe UI", sans-serif; color: #1c1c1c;
       background: #fbfbfb; }}
header {{ padding: 16px 16px 8px; }}
h1 {{ font-size: 18px; margin: 0 0 2px; }}
h2 {{ font-size: 13px; font-weight: 400; color: #555; margin: 0; }}
section {{ padding: 4px 16px 24px; }}
p.horodatage {{ color: #777; font-size: 12px; margin-top: 18px; }}
</style>
</head>
<body>
<header>
<h1>{html.escape(titre)}</h1>
<h2>Aucune séance vélo planifiée sur Intervals.icu ce jour-là.</h2>
</header>
<section>
<p><code>ourouler boucle</code> propose une sortie libre quand il n'y a rien au calendrier.</p>
<p class="horodatage">Page générée le {horodatage}.</p>
</section>
</body>
</html>
"""


__all__ = [
    "COULEURS_BLOCS",
    "PropositionCarte",
    "construire",
    "construire_page_jour",
    "construire_page_sans_seance",
]
