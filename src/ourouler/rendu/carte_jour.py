"""La page du jour et la page « rien de prévu » (voir la docstring de `rendu.carte`)."""

from __future__ import annotations

import base64
import html
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime

from ourouler.boucle.meteo_trace import MeteoTrace
from ourouler.noyau.seance import Seance
from ourouler.noyau.texte import nombre_fr
from ourouler.noyau.trace import Trace
from ourouler.rendu.carte_dessin import (
    _FORME_FLECHE_VENT,
    COULEUR_AUTRE_PROPOSITION,
    COULEUR_LIAISON,
    COULEUR_TRACE,
    LEAFLET_CSS,
    LEAFLET_JS,
    TUILES_ATTRIBUTION,
    TUILES_URL,
    _blocs,
    _charge_json,
    _cumuls,
    _liaisons,
    _profil_svg,
    _section_vent,
    _vent_fleches,
)
from ourouler.seance.placement_resultat import Placement

# --- la page du jour -----------------------------------------------------------


@dataclass(frozen=True)
class PropositionCarte:
    """Une proposition contrastée telle que la page du jour la dessine.

    Construit par `services.sortie` à partir d'une `contraste.Retenue` : ce
    module ne sait toujours ni trier ni contraster, seulement dessiner ce
    qu'on lui donne. `distinction` et `chiffres` sont déjà en langage de
    cycliste (`sortie.contraste.phrase`, `rendu.sortie._details_proposition`)
    — recopiés tels quels, jamais reformulés ici. `gpx_texte` est le GPX du
    **parcours placé** (demi-tours compris, comme `_ecrire_gpx`) : ce module
    ne l'écrit pas sur disque, il l'embarque dans la page pour un
    téléchargement `blob:` côté navigateur : le fichier suit le choix du
    cycliste, pas le classement.
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
    motif_equivalence: str | None = None,
    maintenant: datetime | None = None,
) -> str:
    """La page du jour : les propositions contrastées, superposées sur une carte.

    Une seule grande carte porte les tracés de toutes les `propositions`.
    La sélectionnée est **pleine de bout en bout** : ses blocs en couleurs
    vives et ses flèches de vent comme avant, ses liaisons (échauffement,
    récupérations, retour au calme) en couleur franche plutôt qu'en
    pointillé, et sa boucle non parcourue en fond, sous ses blocs : sans ce fond,
    la portion au-delà d'un demi-tour ne serait peinte par personne, et une
    séance sans bloc (un cas courant) n'aurait que des liaisons pâles et
    pointillées.
    Les autres propositions passent en **pointillé gris**
    (`COULEUR_AUTRE_PROPOSITION`) — le pointillé ne veut plus dire « ce
    n'est pas un bloc » mais « ce n'est pas la sélection », et rien d'autre :
    on ne demande jamais à l'œil de suivre plusieurs choses à la
    fois. Sous la carte, une miniature par proposition sert de sélecteur :
    cliquer en allume une, sans jamais en cacher une autre (pas d'onglet).

    `propositions` vient de `sortie.contraste.choisir(...).retenues`, dans
    l'ordre du tri — la première est celle que l'outil recommande, et c'est
    elle qui est active au chargement. Deux propositions sont un cas normal
    (`motif_deux_propositions` porte alors pourquoi), une seule aussi
    (aucune comparaison n'a de sens, la page le montre sans sélecteur inutile
    à comparer).

    `motif_equivalence` est la phrase « elles se valent » : trois tracés différents dont
    aucun ne se détache sur un axe mesuré. Elle s'affiche au même endroit que
    l'autre motif, et les deux peuvent tenir ensemble.
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
        motif_equivalence=motif_equivalence,
    )


def _panneau_proposition(prop: PropositionCarte, blocs: Sequence[dict], avec_vent: bool, profil: str) -> str:
    """Le panneau d'une proposition : sa légende de blocs, ses notes, son profil.

    Affiché seulement pour la proposition active (`hidden` posé par
    `_page_jour` sur les autres) — c'est ce qui rend la météo, la tenue et le
    profil d'altitude propres à chaque direction, sans jamais mélanger deux
    propositions dans un même paragraphe.
    """
    puces = "".join(
        f'<li><i style="background:{b["couleur"]}"></i>bloc {b["n"]} — note {nombre_fr(b["note"], 2)}</li>'
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


#: La page du jour, en morceaux fixes : `_page_jour` n'y insère que ce qui
#: dépend des propositions (titre, sélecteur, panneaux, données, heure).
_PAGE_JOUR_TETE = """<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
"""
_PAGE_JOUR_STYLE = f"""<link rel="stylesheet" href="{LEAFLET_CSS}">
<style>
:root {{ color-scheme: light; }}
body {{ margin: 0; font: 14px/1.45 system-ui, -apple-system, "Segoe UI", sans-serif; color: #1c1c1c;
       background: #fbfbfb; }}
header {{ padding: 12px 16px 8px; }}
h1 {{ font-size: 18px; margin: 0 0 2px; }}
h2 {{ font-size: 13px; font-weight: 400; color: #555; margin: 0; }}
/* Sans borne de largeur, le conteneur prendrait toute la page — bien plus
   large que haut (jusqu'à ~3:1 sur une fenêtre courante). Une boucle de
   club est plutôt ronde : `fitBounds` calerait alors le zoom sur la
   hauteur et laisserait filer la largeur, une vue de ~150 km pour des
   boucles de ~18 km de diamètre. `max-width: min(100%, 78vh)` borne le rapport largeur/hauteur à
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
   page reste lisible à 400 px. */
.carte-selecteur {{ display: flex; flex-wrap: wrap; gap: 14px; margin: 4px 0 10px; }}
.carte-item {{ flex: 1 1 230px; max-width: 360px; min-width: 0; border: 2px solid transparent;
               border-radius: 10px; padding: 8px; background: #fff; cursor: pointer;
               box-shadow: 0 1px 3px #0002; }}
.carte-item:focus-visible {{ outline: 2px solid #1b6ca8; outline-offset: 2px; }}
.carte-item.actif {{ border-color: #1b6ca8; box-shadow: 0 0 0 2px rgba(27,108,168,.35); }}
/* `pointer-events: none` : la mini-carte est décorative (zoom, drag, clic
   Leaflet déjà coupés) et ne doit surtout pas avaler le clic qui sélectionne
   la proposition : sans cette règle, cliquer *sur* la miniature ne ferait
   rien, seul le texte en dessous marcherait. */
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
"""
_PAGE_JOUR_SCRIPT = f"""const carte = L.map('carte');
// Le cadrage se fait **avant** tout ajout de couche (tuiles comprises) :
// un `L.map()` sans vue calcule des coordonnées de tuile `NaN` dès qu'on lui
// ajoute une couche, avant que `fitBounds` n'ait rien fixé — erreur bénigne
// mais réelle (« Invalid LatLng »). Les bornes englobent **toutes** les
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
// pleine de bout en bout (le pointillé ne distingue pas un bloc d'une
// liaison, il ne vaut que pour « pas la sélection »). Ce qui empêche le
// spaghetti : une seule couche riche à la fois.
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
// (sans quoi, pour la sélection, la portion au-delà d'un demi-tour ne
// serait peinte par personne). Son style change
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
// justement la comparaison qu'une carte unique permet — un
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
// ouverte par `file://` que servie. `TextDecoder` restitue l'UTF-8 du base64 (accents des libellés).
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
"""


def _page_jour(
    *,
    titre: str,
    donnees: dict,
    propositions: Sequence[PropositionCarte],
    panneaux: Sequence[str],
    motif_deux_propositions: str | None,
    motif_equivalence: str | None,
    horodatage: str,
) -> str:
    """Le HTML autonome de la page du jour. Les données partent en JSON, comme `_page`."""
    n = len(propositions)
    premiere = propositions[0]
    accord = "s" if n != 1 else ""
    sous_titre = f"{n} proposition{accord} contrastée{accord}" + (
        " — cliquez une miniature pour l'afficher sur la carte" if n > 1 else ""
    )
    items = [_item_selecteur(prop, actif=prop is premiere, seule=n == 1) for prop in propositions]
    panneaux_html = "".join(
        f'<div class="panneau-prop" data-prop="{prop.numero}"{"" if prop is premiere else " hidden"}>'
        f"{panneau}</div>"
        for prop, panneau in zip(propositions, panneaux, strict=True)
    )
    # Deux phrases possibles, au même endroit : « il n'y en a que deux, et
    # voici pourquoi » et « elles se valent, choisissez ». Elles ne s'excluent
    # pas — deux boucles qui vont ailleurs peuvent parfaitement se valoir.
    motif_html = "".join(
        f'<p class="note motif">{html.escape(texte)}</p>'
        for texte in (motif_deux_propositions, motif_equivalence)
        if texte
    )
    charge = _charge_json(donnees)
    return (
        _PAGE_JOUR_TETE
        + f"<title>{html.escape(titre)}</title>\n"
        + _PAGE_JOUR_STYLE
        + f"""<h1>{html.escape(titre)}</h1>
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
"""
        + _PAGE_JOUR_SCRIPT
        + f"""<p class="horodatage">Page générée le {horodatage}.</p>
</body>
</html>
"""
    )


def _item_selecteur(prop: PropositionCarte, *, actif: bool, seule: bool) -> str:
    """La miniature d'une proposition dans le sélecteur de la page du jour."""
    recommandee = ' <span class="badge badge-reco">recommandée</span>' if actif else ""
    return f"""<div class="carte-item{" actif" if actif else ""}" role="button" tabindex="0"
     aria-pressed="{"true" if actif else "false"}" data-prop="{prop.numero}">
<div class="mini-carte" aria-hidden="true"></div>
<p class="distinction"><span class="badge">n° {prop.numero}</span>{recommandee}
{html.escape(prop.distinction or ("la seule candidate" if seule else ""))}</p>
<p class="chiffres">{html.escape(prop.chiffres)}</p>
<a class="gpx-dl" data-prop="{prop.numero}" download="{html.escape(prop.gpx_nom)}" href="#">
Télécharger le GPX</a>
</div>"""


# --- la page « rien de prévu » (contrat de l'hébergé minimal) ---------------


def construire_page_sans_seance(jour: date, *, maintenant: datetime | None = None) -> str:
    """La page du jour quand Intervals.icu ne porte aucune séance vélo ce jour-là.

    Le contrat de l'hébergé minimal (docs/journal/sprints/heberge_minimal_contrat.md, §
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
