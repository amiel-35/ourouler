"""La carte de vérification : le tracé, les blocs là où ils tombent, le profil.

Elle sert à **voir** ce que le placement a décidé : on voit d'un coup d'œil
qu'un bloc traverse un bourg. La page est un fichier HTML autonome — Leaflet et le
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
  **pointillés clairs** (`COULEUR_LIAISON`), sur sa propre position. Ces
  portions-là ne sont pas notées — une récupération absorbe le point dur et
  ne se juge pas — mais elles sont roulées, et la carte doit le montrer : une
  carte qui n'afficherait que les blocs ferait croire l'échauffement oublié
  (décision Q13, `docs/journal/questions/questions_mainteneur.md`) ;
- des **flèches de vent**, une par échantillon météo assez venté : le vent
  entre dans le placement, il déplace les blocs de plusieurs kilomètres, et
  sans une flèche sur la carte personne ne peut vérifier à l'œil que ce
  déplacement est cohérent avec le vent réel. La flèche pointe d'où vient le vent, comme une girouette ;
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

**La page du jour** (`construire_page_jour`) réutilise tout ce qui
précède : c'est la même carte, une par proposition contrastée, superposées —
une carte et trois itinéraires qui passent en grisé ou en surbrillance,
comme sur Strava et les GPS (décisions Q18 et Q20), plutôt que trois cartes
séparées, parce que c'est la seule forme qui montre **où** les propositions
divergent. La sélectionnée est **pleine de bout en bout** — blocs en
couleurs vives, liaisons en couleur franche, et sa boucle non parcourue en
fond, sous ses blocs, pour que la portion au-delà d'un demi-tour reste
visible. Les autres propositions passent en **pointillé gris** — le
pointillé ne veut pas dire « ce n'est pas un bloc » mais « ce n'est pas la
sélection », et rien d'autre : un seul sens. Les miniatures sous la carte ne
sont pas perdues : elles deviennent le sélecteur, chacune avec sa phrase de
distinction (`sortie.contraste`) et
ses chiffres — jamais un onglet, un onglet cache et comparer demande de voir
ensemble.
"""

from __future__ import annotations

import html
from collections.abc import Sequence

from ourouler.boucle.meteo_trace import MeteoTrace
from ourouler.noyau.seance import Seance
from ourouler.noyau.texte import nombre_fr
from ourouler.noyau.trace import Trace
from ourouler.rendu.carte_dessin import (
    _FORME_FLECHE_VENT,
    COULEUR_AUTRE_PROPOSITION,
    COULEUR_LIAISON,
    COULEUR_TRACE,
    COULEURS_BLOCS,
    LEAFLET_CSS,
    LEAFLET_JS,
    LEAFLET_VERSION,
    POINTS_PROFIL_MAX,
    PROFIL_HAUTEUR,
    PROFIL_LARGEUR,
    PROFIL_MARGES,
    SEUIL_AFFICHAGE_VENT_KMH,
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
from ourouler.rendu.carte_jour import (
    PropositionCarte,
    construire_page_jour,
    construire_page_sans_seance,
)
from ourouler.seance.placement_resultat import Placement


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


#: La carte d'une séance, en morceaux fixes : `_page` n'y insère que ce qui
#: dépend de la séance (titre, légende, notes, profil, données).
_PAGE_TETE = """<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
"""
_PAGE_STYLE = f"""<link rel="stylesheet" href="{LEAFLET_CSS}">
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
"""
_PAGE_SCRIPT = f"""const carte = L.map('carte');
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


def _page(*, titre: str, sous_titre: str, notes, donnees: dict, blocs, profil: str, avec_vent: bool) -> str:
    """Le HTML autonome. Les données partent en JSON, jamais interpolées en dur."""
    puces = "".join(
        f'<li><i style="background:{bloc["couleur"]}"></i>bloc {bloc["n"]} — note '
        f"{nombre_fr(bloc['note'], 2)}</li>"
        for bloc in blocs
    )
    lignes_notes = "".join(f'<p class="note">{html.escape(str(n))}</p>' for n in notes)
    section_vent = _section_vent() if avec_vent else ""
    charge = _charge_json(donnees)
    return (
        _PAGE_TETE
        + f"<title>{html.escape(titre)}</title>\n"
        + _PAGE_STYLE
        + f"""<h1>{html.escape(titre)}</h1>
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
"""
        + _PAGE_SCRIPT
    )


__all__ = [
    "COULEURS_BLOCS",
    "COULEUR_AUTRE_PROPOSITION",
    "COULEUR_LIAISON",
    "COULEUR_TRACE",
    "LEAFLET_CSS",
    "LEAFLET_JS",
    "LEAFLET_VERSION",
    "POINTS_PROFIL_MAX",
    "PROFIL_HAUTEUR",
    "PROFIL_LARGEUR",
    "PROFIL_MARGES",
    "PropositionCarte",
    "SEUIL_AFFICHAGE_VENT_KMH",
    "TUILES_ATTRIBUTION",
    "TUILES_URL",
    "construire",
    "construire_page_jour",
    "construire_page_sans_seance",
]
