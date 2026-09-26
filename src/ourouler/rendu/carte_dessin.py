"""Ce que la carte dessine : constantes, blocs, liaisons, profil, vent, charge JSON.

Partagé par la carte d'une séance (`rendu.carte`) et la page du jour
(`rendu.carte_jour`) ; la raison d'être de chaque couche est dans la docstring
de `rendu.carte`.
"""

from __future__ import annotations

import bisect
import html
import json
from collections.abc import Sequence
from dataclasses import dataclass

from ourouler.boucle.meteo_trace import SEUIL_VENT_SENSIBLE_KMH, fleches_vent
from ourouler.noyau.seance import Seance
from ourouler.noyau.texte import nombre_fr
from ourouler.noyau.trace import PointTrace, Trace, distance_m
from ourouler.seance.placement_resultat import Emplacement, Placement

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
                "etiquette": f"{numero} · {nombre_fr(emplacement.note.note, 1)}",
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
        f"km {nombre_fr(emplacement.debut_parcouru_m / 1000, 1)} → {nombre_fr(fin_parcourue / 1000, 1)} "
        f"({nombre_fr(emplacement.longueur_m / 1000, 1)} km)"
    )
    lignes.append(f"note {nombre_fr(note.note, 2)} km équivalents")
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

#: La règle des flèches est **partie d'ici** : elle vit depuis le 17/09/2026
#: dans `boucle.meteo_trace.fleches_vent`, avec son code et ses raisons, sans
#: une virgule de changée. Elle a bougé parce que le JSON de `boucle.commande`
#: et de `sortie.commande` doit servir les mêmes flèches au front, et que
#: `boucle` ne peut pas importer `sortie`. Ce nom local reste pour ne pas
#: casser les appelants ; les deux chemins dessinent le même vent.
_vent_fleches = fleches_vent


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


