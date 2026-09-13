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

Trois couches sur la carte :

- le tracé complet en gris, dessous ;
- chaque **bloc** dans une couleur vive, avec son numéro et sa note ; au
  survol, ses motifs ;
- ce qui sépare deux blocs (échauffement, récupérations, retour au calme) en
  **pointillés clairs**. Ces portions-là ne sont pas notées — décision du
  13/09, une récupération absorbe le point dur et ne se juge pas.

Sous la carte, le **profil d'altitude** en SVG, avec les mêmes couleurs aux
mêmes endroits : une descente sous un bloc s'y voit mieux que sur la carte.

Un demi-tour ne dessine pas de portion de liaison : le bloc suivant reprend
le même couloir en sens inverse, il n'y a rien à tracer entre les deux. Le
fait est écrit dans l'étiquette du bloc.
"""

from __future__ import annotations

import bisect
import html
import json
from collections.abc import Sequence
from dataclasses import dataclass

from ourouler.boucle.trace import PointTrace, Trace, distance_m
from ourouler.seance.modele import Seance
from ourouler.seance.placement import Emplacement, Placement

#: Version épinglée de Leaflet, servie par le CDN autorisé.
LEAFLET_VERSION = "1.9.4"
LEAFLET_CSS = f"https://cdnjs.cloudflare.com/ajax/libs/leaflet/{LEAFLET_VERSION}/leaflet.min.css"
LEAFLET_JS = f"https://cdnjs.cloudflare.com/ajax/libs/leaflet/{LEAFLET_VERSION}/leaflet.min.js"

#: Fond de carte : OpenStreetMap, avec l'attribution que sa licence impose.
TUILES_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
TUILES_ATTRIBUTION = "© OpenStreetMap"

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

#: Nombre maximal de points du profil d'altitude. Au-delà, on sous-échantillonne :
#: un SVG de 3 000 points ne se lit pas mieux qu'un de 800, il pèse seulement
#: quatre fois plus.
POINTS_PROFIL_MAX = 800

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
) -> str:
    """La page HTML complète, prête à être écrite dans un fichier.

    `titre` par défaut : le nom de la séance et son jour. `notes` sont des
    phrases ajoutées sous la légende — la commande y met ce qu'elle sait et
    que la carte ne montre pas (distance, D+, météo, tenue).
    """
    titre = titre or f"{seance.nom} — {seance.jour.isoformat()}"
    cumuls = _cumuls(trace.points)
    total = cumuls[-1] if cumuls else 0.0

    blocs = _blocs(trace, seance, placement, cumuls)
    liaisons = _liaisons(trace, placement, cumuls, total)
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
    )


# --- ce qu'on dessine ---------------------------------------------------------


def _blocs(
    trace: Trace, seance: Seance, placement: Placement, cumuls: Sequence[float]
) -> list[dict]:
    """Un dictionnaire par bloc : géométrie, couleur, étiquette, infobulle."""
    dessins = []
    for numero, emplacement in enumerate(placement.emplacements, start=1):
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
    """Ce que le survol affiche : la consigne, la position, la note, les motifs."""
    note = emplacement.note
    lignes = [f"<b>Bloc {numero}</b>"]
    if etape is not None:
        consigne = etape.libelle_court or etape.type
        duree = f"{int(round(etape.duree_s)) // 60}:{int(round(etape.duree_s)) % 60:02d}"
        puissances = [p for p in (etape.puissance_min_w, etape.puissance_max_w) if p is not None]
        watts = f" — {min(puissances):.0f}-{max(puissances):.0f} W" if puissances else ""
        lignes.append(html.escape(f"{consigne} · {duree}{watts}"))
    lignes.append(
        f"km {_fr(emplacement.debut_m / 1000, 1)} → "
        f"{_fr((emplacement.debut_m + emplacement.longueur_m) / 1000, 1)} "
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


def _liaisons(
    trace: Trace, placement: Placement, cumuls: Sequence[float], total: float
) -> list[_Portion]:
    """Les portions entre les blocs : échauffement, récupérations, retour au calme.

    Elles ne sont pas notées et ne portent donc ni couleur ni motif — elles
    disent seulement par où l'on passe pour aller d'un bloc au suivant.

    Le sens de marche n'est pas toujours celui du tracé : après un demi-tour,
    `seance.placement` continue à l'envers, et les blocs suivants ont des
    kilomètres **décroissants**. On prend donc, entre deux couloirs, l'écart
    qui les sépare dans un sens comme dans l'autre ; deux couloirs qui se
    chevauchent (le demi-tour lui-même) ne donnent aucune liaison. La
    dernière liaison suit le sens des deux derniers blocs : vers la fin du
    tracé si l'on avance, vers le départ si l'on revient à l'envers.

    Ce qui reste en gris est donc ce que la séance **ne parcourt pas** : sur
    un placement qui se termine en sens inverse, la moitié de la boucle reste
    grise, et c'est précisément ce que la carte doit montrer.
    """
    if not placement.emplacements:
        return [_portion(trace, cumuls, 0.0, total)] if total > 0 else []
    bornes = [(e.debut_m, e.debut_m + e.longueur_m) for e in placement.emplacements]
    coupures = [(0.0, bornes[0][0])]
    for (debut_a, fin_a), (debut_b, fin_b) in zip(bornes[:-1], bornes[1:], strict=True):
        if debut_b >= fin_a:  # on continue dans le sens du tracé
            coupures.append((fin_a, debut_b))
        elif fin_b <= debut_a:  # on revient en arrière
            coupures.append((fin_b, debut_a))
    if len(bornes) >= 2 and bornes[-1][1] <= bornes[-2][0]:
        coupures.append((0.0, bornes[-1][0]))  # retour au calme à l'envers, vers le départ
    else:
        coupures.append((bornes[-1][1], total))
    portions = []
    for debut, fin in coupures:
        if fin - debut <= 0:
            continue
        portion = _portion(trace, cumuls, debut, fin - debut)
        if len(portion.points) >= 2:
            portions.append(portion)
    return portions


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


def _page(*, titre: str, sous_titre: str, notes, donnees: dict, blocs, profil: str) -> str:
    """Le HTML autonome. Les données partent en JSON, jamais interpolées en dur."""
    puces = "".join(
        f'<li><i style="background:{bloc["couleur"]}"></i>bloc {bloc["n"]} — note '
        f"{_fr(bloc['note'], 2)}</li>"
        for bloc in blocs
    )
    lignes_notes = "".join(f"<p class=\"note\">{html.escape(str(n))}</p>" for n in notes)
    charge = json.dumps(donnees, ensure_ascii=False)
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


__all__ = ["COULEURS_BLOCS", "construire"]
