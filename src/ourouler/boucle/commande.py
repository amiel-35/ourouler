"""Sous-commande `ourouler boucle` : candidates → coûts → météo → tableau → GPX.

Ce module est appelé par `cli.py` et ne lit rien de l'environnement : il
reçoit `args` et `config`, et les deux clients (BRouter, Open-Meteo) sont
injectables pour que les tests ne touchent jamais le réseau.

L'enchaînement est celui du contrat de sprint §6 :

1. `boucle.candidates.generer` demande au moteur plusieurs boucles autour de
   la direction voulue (lot L2.3) ;
2. `boucle.couts.evaluer` mesure trafic, revêtement, virages et sens (L2.4) ;
3. `boucle.meteo_trace.evaluer` regarde la pluie et le vent **à l'heure de
   passage** sur chaque tronçon (L2.5) ;
4. le tableau est trié par `score + pluie_cumulee_mm × 2` — les kilomètres
   équivalents du score et les millimètres de pluie ne sont pas la même
   grandeur, ce poids est un arbitrage assumé, pas une mesure ;
5. la meilleure est écrite en GPX.

Avec `--gpx`, les étapes 1 et 5 sautent : on évalue le fichier importé seul.

La météo est le seul maillon qu'on accepte de perdre : si Open-Meteo ne
répond pas, le tableau s'affiche sans ses colonnes et un avertissement part
sur la sortie d'erreur. Perdre la boucle parce qu'il manque la pluie serait
absurde ; l'inverse (afficher une pluie inventée) est interdit par la règle
absolue 5.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from ourouler.boucle.candidates import generer
from ourouler.boucle.couts import Couts
from ourouler.boucle.couts import evaluer as evaluer_couts
from ourouler.boucle.gpx import ecrire_gpx, lire_gpx_trace
from ourouler.boucle.meteo_trace import MeteoTrace
from ourouler.boucle.meteo_trace import evaluer as evaluer_meteo
from ourouler.boucle.trace import Trace
from ourouler.config import Config
from ourouler.connecteurs.brouter import ClientBrouter
from ourouler.erreurs import ErreurConfig, ErreurConnecteur, ErreurUtilisateur
from ourouler.meteo.commande import heure_depart
from ourouler.meteo.couronne import NOMS_DIRECTIONS, NOMS_DIRECTIONS_16, azimut_de
from ourouler.meteo.openmeteo import ClientOpenMeteo
from ourouler.meteo.rapport import date_en_francais

#: Poids de la pluie dans le tri du tableau : un millimètre cumulé coûte
#: autant que deux kilomètres équivalents de score (contrat §6).
POIDS_PLUIE_TRI = 2.0

#: Marque de la ligne retenue dans le tableau texte.
MARQUE_RETENUE = "→"

#: Part de kilomètres non classés au-delà de laquelle le tableau le dit. En
#: dessous, c'est le bruit habituel des tronçons de raccordement ; au-delà,
#: « 0,0 km de trafic » ne veut plus dire « tracé calme ».
PART_NON_CLASSE_SIGNALEE = 0.05

#: Ce qu'on affiche à la place d'une mesure absente (jamais un zéro : un
#: GPX importé ne dit rien des routes empruntées, ce n'est pas « 0 km de
#: trafic »).
ABSENT = "—"


@dataclass(frozen=True)
class Demande:
    """Ce que l'utilisateur a demandé, une fois validé — avant tout appel réseau."""

    gpx: Path | None
    distance_km: float | None
    direction: str  # libellé normalisé, sert au nom du fichier de sortie
    azimut_deg: float | None
    nb_candidates: int
    profil: str
    depart: datetime
    sortie: Path | None
    ecraser: bool = False


@dataclass
class Evaluation:
    """Une candidate mesurée : son tracé, ses coûts, sa météo, son total de tri."""

    numero: int
    trace: Trace
    couts: Couts
    meteo: MeteoTrace | None
    ecart_relatif: float | None
    azimut_deg: float | None
    rayon_m: float | None
    total: float


def executer(
    args: argparse.Namespace,
    config: Config,
    client_brouter: ClientBrouter | None = None,
    client_meteo: ClientOpenMeteo | None = None,
) -> int:
    """Exécute `ourouler boucle`. Renvoie le code de sortie (0 = succès)."""
    demande = lire_options(args, config)

    if demande.gpx is not None:
        traces = [(lire_gpx_trace(demande.gpx), None, None)]
    else:
        client_brouter = client_brouter if client_brouter is not None else ClientBrouter(config.brouter)
        trouvees = generer(
            client_brouter,
            config.depart,
            distance_km=demande.distance_km,
            azimut_deg=demande.azimut_deg,
            nb=demande.nb_candidates,
            tolerance=config.boucle.tolerance_distance,
            profil=demande.profil,
        )
        if not trouvees:
            raise ErreurConnecteur(
                f"boucle : aucune boucle bornée trouvée autour de {demande.direction} "
                f"pour {demande.distance_km:g} km (profil {demande.profil}) — "
                "essayer une autre direction, une autre distance ou un autre profil"
            )
        traces = [(c.trace, c.ecart_relatif, c) for c in trouvees]

    client_meteo = client_meteo if client_meteo is not None else ClientOpenMeteo()
    meteos, panne = _meteos(
        [t for t, _, _ in traces], client_meteo, config, depart=demande.depart
    )

    evaluations = _classer(traces, meteos, sens_prefere=config.boucle.sens)
    chemin = _ecrire_meilleure(evaluations[0].trace, demande) if demande.gpx is None else None

    if panne is not None:
        print(
            f"ourouler : météo indisponible ({panne}) — tableau affiché sans les "
            "colonnes météo, la boucle reste valable",
            file=sys.stderr,
        )
    if getattr(args, "json", False):
        print(json.dumps(rendre_json(evaluations, demande, config, chemin), ensure_ascii=False, indent=2))
    else:
        print(rendre_texte(evaluations, demande, config, chemin))
    return 0


# --- options ------------------------------------------------------------------


def lire_options(args: argparse.Namespace, config: Config) -> Demande:
    """Valide les options **avant** toute connexion. Lève `ErreurUtilisateur` sinon.

    L'ordre compte : une distance négative ou une direction illisible doivent
    coûter un message immédiat, pas un aller-retour sur le serveur du
    mainteneur (contrat §6).
    """
    gpx = getattr(args, "gpx", None)
    chemin_gpx = Path(gpx) if gpx else None
    if chemin_gpx is not None and not chemin_gpx.is_file():
        raise ErreurUtilisateur(f"--gpx {gpx} : fichier introuvable")

    distance_km = getattr(args, "distance", None)
    direction = getattr(args, "direction", None)
    azimut = None
    libelle = ""

    if chemin_gpx is None:
        if distance_km is None:
            raise ErreurUtilisateur(
                "boucle : --distance KM est obligatoire (ou --gpx pour évaluer un fichier existant)"
            )
        if direction is None:
            raise ErreurUtilisateur(
                "boucle : --direction N|NE|…|NO ou un azimut en degrés est obligatoire "
                "(ou --gpx pour évaluer un fichier existant)"
            )
        if not math.isfinite(distance_km) or distance_km <= 0:
            raise ErreurUtilisateur(
                f"--distance {distance_km} : une distance en kilomètres strictement positive est attendue"
            )
        libelle, azimut = direction_en_azimut(direction)
    elif direction is not None:
        libelle, azimut = direction_en_azimut(direction)

    nb = getattr(args, "candidates", None)
    nb = config.boucle.candidates if nb is None else nb
    if nb < 1:
        raise ErreurUtilisateur(f"--candidates {nb} : au moins une candidate est attendue")

    profil = getattr(args, "profil", None) or config.brouter.profil
    if chemin_gpx is None and not config.brouter.renseigne:
        raise ErreurUtilisateur(
            "boucle : [brouter] url n'est pas renseigné dans la configuration — "
            "y mettre l'adresse du serveur BRouter, ou passer --gpx pour évaluer un fichier"
        )

    sortie = getattr(args, "sortie", None)
    demande = Demande(
        gpx=chemin_gpx,
        distance_km=float(distance_km) if distance_km is not None else None,
        direction=libelle,
        azimut_deg=azimut,
        nb_candidates=int(nb),
        profil=profil,
        depart=heure_depart(getattr(args, "depart", None)),
        sortie=Path(sortie) if sortie else None,
        ecraser=bool(getattr(args, "ecraser", False)),
    )
    if demande.gpx is None:
        _verifier_sortie(demande)
    return demande


def _verifier_sortie(demande: Demande) -> None:
    """Refuse d'avance un GPX qu'on ne pourra pas écrire (contrat §6, avant-réseau).

    Un dossier inexistant ou non inscriptible se voyait au moment de
    l'écriture, c'est-à-dire après avoir consommé jusqu'à 12 appels BRouter et
    10 appels Open-Meteo, et sortait en trace plutôt qu'en message.

    Un `--sortie` qui existe déjà n'est **pas** écrasé sans `--ecraser` : avec
    un nom choisi, la deuxième exécution est le cas normal, et remplacer sans
    un mot le fichier qu'on vient de relire serait une perte. Le nom par
    défaut, lui, porte l'horodatage à la minute : il est écrasé sans question
    (décision du superviseur, point 19 de la relecture).
    """
    chemin = demande.sortie if demande.sortie is not None else Path(nom_par_defaut(demande))
    dossier = chemin.parent if str(chemin.parent) else Path(".")
    if not dossier.is_dir():
        raise ErreurUtilisateur(
            f"--sortie {chemin} : le dossier {dossier} n'existe pas"
        )
    _verifier_inscriptible(dossier, chemin)
    if demande.sortie is not None and chemin.exists() and not demande.ecraser:
        raise ErreurUtilisateur(
            f"{chemin} existe déjà — ajouter --ecraser pour le remplacer, "
            "ou choisir un autre nom"
        )


def _verifier_inscriptible(dossier: Path, chemin: Path) -> None:
    """Écrit et efface un fichier témoin : la seule façon de savoir vraiment.

    Un droit d'écriture se mesure, il ne se déduit pas des bits de mode (ACL,
    montage en lecture seule, quota). Le témoin porte un nom unique et est
    effacé aussitôt, y compris si la création a échoué à mi-chemin.
    """
    temoin = dossier / f".ourouler-{uuid.uuid4().hex}.tmp"
    try:
        temoin.touch()
    except OSError as e:
        raise ErreurUtilisateur(
            f"--sortie {chemin} : écriture impossible dans {dossier} ({e})"
        ) from e
    finally:
        try:
            temoin.unlink(missing_ok=True)
        except OSError:  # pragma: no cover - le témoin existe et vient d'être créé
            pass


def direction_en_azimut(texte: str) -> tuple[str, float]:
    """(libellé, azimut) pour « NE », « 45 », « 45° » ou « 45,5 ».

    Les noms à 8 et à 16 secteurs sont acceptés — `azimut_de` les connaît
    déjà, on ne réécrit pas la table. « W » est toléré comme alias de « O »
    (NW → NO) : les cartes et les applications anglophones en sont pleines,
    et refuser une direction pour une lettre serait pénible.
    """
    brut = (texte or "").strip()
    if not brut:
        raise ErreurUtilisateur("--direction : valeur vide, attendu N|NE|…|NO ou un azimut en degrés")

    nombre = brut.rstrip("°").strip().replace(",", ".")
    try:
        azimut = float(nombre)
    except ValueError:
        pass
    else:
        if not math.isfinite(azimut):
            raise ErreurUtilisateur(f"--direction {texte!r} : azimut illisible")
        azimut %= 360.0
        return (f"{azimut:03.0f}", azimut)

    nom = brut.upper().replace("W", "O")
    for directions in (8, 16):
        try:
            return (nom, azimut_de(nom, directions))
        except ErreurConfig:
            continue
    raise ErreurUtilisateur(
        f"--direction {texte!r} : attendu un de {', '.join(NOMS_DIRECTIONS)} "
        f"(ou {', '.join(NOMS_DIRECTIONS_16)}), ou un azimut en degrés"
    )


# --- mesures ------------------------------------------------------------------


def _meteos(
    traces: list[Trace], client: ClientOpenMeteo, config: Config, *, depart: datetime
) -> tuple[list[MeteoTrace | None], str | None]:
    """La météo de chaque tracé, et le motif de panne s'il y en a une.

    Dès qu'un appel échoue, on cesse d'insister : si Open-Meteo est
    injoignable pour la première candidate, il l'est pour les quatre autres,
    et attendre cinq timeouts ne rend service à personne.
    """
    resultats: list[MeteoTrace | None] = []
    panne: str | None = None
    for trace in traces:
        if panne is not None:
            resultats.append(None)
            continue
        try:
            resultats.append(
                evaluer_meteo(
                    trace,
                    client,
                    depart=depart,
                    vitesse_kmh=config.boucle.vitesse_moyenne_kmh,
                    modele=config.meteo.modele,
                    second_avis=config.meteo.second_avis,
                )
            )
        except ErreurConnecteur as e:
            panne = str(e)
            resultats.append(None)
    return (resultats, panne)


def _classer(
    traces: list[tuple[Trace, float | None, object]],
    meteos: list[MeteoTrace | None],
    *,
    sens_prefere: str,
) -> list[Evaluation]:
    """Les candidates mesurées et triées par `score + pluie × 2`, numérotées à partir de 1."""
    evaluations = []
    for (trace, ecart, candidate), meteo in zip(traces, meteos, strict=True):
        couts = evaluer_couts(trace, sens_prefere=sens_prefere)
        pluie = meteo.pluie_cumulee_mm if meteo is not None else 0.0
        evaluations.append(
            Evaluation(
                numero=0,
                trace=trace,
                couts=couts,
                meteo=meteo,
                ecart_relatif=ecart,
                azimut_deg=getattr(candidate, "azimut_deg", None),
                rayon_m=getattr(candidate, "rayon_m", None),
                total=couts.score + pluie * POIDS_PLUIE_TRI,
            )
        )
    evaluations.sort(key=lambda e: e.total)
    for numero, evaluation in enumerate(evaluations, start=1):
        evaluation.numero = numero
    return evaluations


def _ecrire_meilleure(trace: Trace, demande: Demande) -> Path:
    """Écrit la boucle retenue en GPX et rend son chemin."""
    chemin = demande.sortie if demande.sortie is not None else Path(nom_par_defaut(demande))
    try:
        chemin.write_text(ecrire_gpx(trace, trace.nom), encoding="utf-8")
    except OSError as e:
        # Disque plein, droits retirés entre-temps, chemin devenu un dossier :
        # un message, pas une trace — les appels externes sont déjà consommés.
        raise ErreurUtilisateur(f"écriture impossible dans {chemin} ({e})") from e
    return chemin


def nom_par_defaut(demande: Demande) -> str:
    """`boucle_<direction>_<distance>km_<AAAAMMJJ-HHMM>.gpx` (contrat §6)."""
    distance = f"{demande.distance_km:g}" if demande.distance_km is not None else "0"
    return f"boucle_{demande.direction}_{distance}km_{demande.depart:%Y%m%d-%H%M}.gpx"


# --- rendu texte ---------------------------------------------------------------

#: Colonnes du tableau, dans l'ordre du contrat §6. Le drapeau dit si la
#: colonne vient de la météo : sans météo, elle disparaît au lieu d'afficher
#: une colonne de tirets.
COLONNES = (
    ("n°", False),
    ("distance", False),
    ("D+", False),
    ("temps", False),
    ("trafic", False),
    ("non revêtu", False),
    ("antennes m", False),
    ("virages G", False),
    ("sens", False),
    ("pluie", True),
    ("vent face", True),
    ("ressenti min", True),
)


def rendre_texte(
    evaluations: list[Evaluation], demande: Demande, config: Config, chemin: Path | None
) -> str:
    """Le tableau des candidates, la ligne retenue marquée d'une flèche."""
    avec_meteo = any(e.meteo is not None for e in evaluations)
    lignes = _entete(demande, config, avec_meteo)

    titres = [titre for titre, meteo in COLONNES if avec_meteo or not meteo]
    cellules = [_cellules(e, config, avec_meteo) for e in evaluations]
    largeurs = [
        max([len(titre)] + [len(ligne[i]) for ligne in cellules]) for i, titre in enumerate(titres)
    ]
    marge = " " * (len(MARQUE_RETENUE) + 1)
    lignes.append(marge + "  ".join(t.rjust(n) for t, n in zip(titres, largeurs, strict=True)))
    for evaluation, ligne in zip(evaluations, cellules, strict=True):
        retenue = evaluation is evaluations[0] and demande.gpx is None
        marque = f"{MARQUE_RETENUE} " if retenue else marge
        lignes.append(marque + "  ".join(c.rjust(n) for c, n in zip(ligne, largeurs, strict=True)))

    if any(e.trace.meta.get("couts_partiels") for e in evaluations):
        lignes.append(
            f"{ABSENT} : tracé sans tags de route (GPX importé) — trafic et revêtement inconnus."
        )
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
    if chemin is not None:
        lignes.append(f"{MARQUE_RETENUE} retenue : n° {evaluations[0].numero}, écrite dans {chemin}")
    return "\n".join(lignes)


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


def _entete(demande: Demande, config: Config, avec_meteo: bool) -> list[str]:
    lignes = []
    if demande.gpx is not None:
        lignes.append(f"Tracé importé : {demande.gpx}")
    else:
        lignes.append(
            f"Boucle depuis {config.depart.nom} — {demande.distance_km:g} km vers "
            f"{demande.direction} ({demande.azimut_deg:.0f}°), profil {demande.profil}"
        )
    lignes.append(
        f"Départ {date_en_francais(demande.depart)} — {config.boucle.vitesse_moyenne_kmh:g} km/h, "
        f"sens préféré {config.boucle.sens}"
    )
    if avec_meteo:
        lignes.append(f"Météo {config.meteo.modele}, second avis {config.meteo.second_avis or 'aucun'}")
    lignes.append("Tri : score (km équivalents) + pluie cumulée × 2 ; plus bas = mieux.")
    return lignes


def _cellules(evaluation: Evaluation, config: Config, avec_meteo: bool) -> list[str]:
    couts, meteo = evaluation.couts, evaluation.meteo
    partiels = bool(evaluation.trace.meta.get("couts_partiels"))
    cellules = [
        str(evaluation.numero),
        f"{_fr(evaluation.trace.distance_m / 1000, 1)} km",
        _denivele(evaluation.trace),
        _duree(evaluation.trace.distance_m / 1000, config.boucle.vitesse_moyenne_kmh),
        ABSENT if partiels else f"{_fr(couts.km_trafic, 1)} km",
        ABSENT if partiels else f"{_fr(couts.km_non_revetu, 1)} km",
        f"{couts.antennes_m:.0f}",
        f"{couts.virages_gauche} ({couts.virages_gauche_trafic})",
        couts.sens,
    ]
    if avec_meteo:
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


def _duree(distance_km: float, vitesse_kmh: float) -> str:
    """« 2:14 » — le temps estimé à la vitesse moyenne de la configuration."""
    if vitesse_kmh <= 0:
        return ABSENT
    minutes = round(distance_km / vitesse_kmh * 60)
    return f"{minutes // 60}:{minutes % 60:02d}"


def _fr(valeur: float, decimales: int) -> str:
    """Un nombre à la française : virgule décimale, pas de séparateur de milliers."""
    return f"{valeur:.{decimales}f}".replace(".", ",")


# --- rendu JSON ----------------------------------------------------------------


def rendre_json(
    evaluations: list[Evaluation], demande: Demande, config: Config, chemin: Path | None
) -> dict:
    """Toutes les mesures, plus le chemin du GPX écrit (contrat §6)."""
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
        "vitesse_moyenne_kmh": config.boucle.vitesse_moyenne_kmh,
        "sens_prefere": config.boucle.sens,
        "modele": config.meteo.modele,
        "second_avis": config.meteo.second_avis,
        "gpx": str(chemin) if chemin is not None else None,
        "candidates": [_candidate_json(e, config, chemin) for e in evaluations],
    }


def _candidate_json(evaluation: Evaluation, config: Config, chemin: Path | None) -> dict:
    couts, meteo = evaluation.couts, evaluation.meteo
    trace = evaluation.trace
    distance_km = trace.distance_m / 1000.0
    return {
        "numero": evaluation.numero,
        "retenue": evaluation.numero == 1 and chemin is not None,
        "nom": trace.nom,
        "distance_km": round(distance_km, 3),
        "denivele_m": trace.denivele_m,
        "denivele_source": trace.meta.get("denivele_source"),
        "temps_estime_s": round(distance_km / config.boucle.vitesse_moyenne_kmh * 3600),
        "azimut_deg": evaluation.azimut_deg,
        "rayon_m": evaluation.rayon_m,
        "ecart_relatif": evaluation.ecart_relatif,
        "total_tri": round(evaluation.total, 3),
        "couts_partiels": bool(trace.meta.get("couts_partiels")),
        "segments_ignores": int(trace.meta.get("segments_ignores") or 0),
        "antennes": trace.meta.get("antennes"),
        "distance_source": trace.meta.get("distance_source"),
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
        "echantillons": [
            {
                "dist_m": round(e.dist_m, 1),
                "t": e.t.isoformat(),
                "cap_deg": round(e.cap_deg, 1),
                "pluie_mm": e.pluie_mm,
                "vent_kmh": e.vent_kmh,
                "vent_relatif": e.vent_relatif,
                "ressenti_c": e.ressenti_c,
            }
            for e in meteo.echantillons
        ],
    }
