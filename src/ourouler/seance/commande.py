"""Sous-commande `ourouler seance` : la séance du jour, et la route qu'elle demande.

Ce module lit `calibration.json` (par `physique.commande`, qui sait où il
est) et appelle Intervals.icu ; le reste de `seance/` ne connaît ni fichier,
ni réseau. Le client est injectable pour que les tests ne touchent jamais le
réseau.

**`--fichier-seance`** (F1) remplace Intervals.icu par un `.ZWO`/`.MRC` donné
en ligne de commande, lu par `seance.fichier.lire_fichier_seance` — voir
`_executer_fichier`. C'est le seul autre module qui touche un chemin ici, et
seulement celui que `cli.py` lui passe déjà résolu (règle absolue 2).

**Ce que « longueur de route nécessaire » veut dire.** Pour chaque étape, on
demande au modèle physique la vitesse d'équilibre à la puissance cible, **sur
le plat et sans vent** ; la longueur est cette vitesse multipliée par la
durée de l'étape. C'est une borne de travail, pas une prédiction : le terrain
réel monte, descend et le vent souffle. Le lot L4.3 fera le calcul le long
d'un tracé ; ici, il s'agit de savoir de combien de route droite un bloc a
besoin — « 8 minutes à 250 W, c'est 4,2 km ».

**Le demi-tour.** Un bloc peut reprendre le segment du bloc précédent en sens
inverse, à condition que la récupération qui suit paie l'aller-retour : sa
première moitié dépasse le bout du segment, la seconde revient dessus
(mécanique fixée par le mainteneur le 13/09). La colonne « au-delà » donne
donc, pour chaque bloc suivi d'une récupération, la **longueur de route
nécessaire au-delà de la fin du segment** : moitié de la récupération ×
vitesse de récupération. Sans récupération derrière, la question ne se pose
pas.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from ourouler.config import Config
from ourouler.connecteurs.intervals import ClientIntervals
from ourouler.noyau.erreurs import ErreurIntervalsAbsent, ErreurUtilisateur
from ourouler.noyau.seance import (
    ZONE_FC_BASSE_MAX,
    Etape,
    Seance,
)
from ourouler.physique.modele import Parametres, vitesse_a_plat_ms
from ourouler.seance.intervals import seance_du_jour, seances_periode

#: Comment les types s'écrivent dans le tableau.
LIBELLES_TYPE = {
    "echauffement": "échauffement",
    "bloc": "bloc",
    "recuperation": "récupération",
    "calme": "retour au calme",
}


@dataclass(frozen=True)
class LongueurEtape:
    """Ce qu'une étape demande à la route.

    `longueur_m` est `None` quand aucune vitesse ne peut être calculée —
    étape sans consigne de puissance, ou consigne dont l'unité n'a pas été
    reconnue. `au_dela_m` n'existe que pour un bloc suivi d'une récupération.
    """

    indice: int
    etape: Etape
    vitesse_ms: float | None
    longueur_m: float | None
    recup_s: float | None = None
    au_dela_m: float | None = None

    @property
    def vitesse_kmh(self) -> float | None:
        return None if self.vitesse_ms is None else self.vitesse_ms * 3.6


def longueurs(
    seance: Seance,
    *,
    parametres: Parametres | None = None,
    vitesse_ms: float | None = None,
) -> list[LongueurEtape]:
    """Longueur de route de chaque étape. Exactement un des deux modes.

    - `parametres` : la vitesse de chaque étape vient du modèle, à sa
      puissance cible, sur le plat et sans vent. Une étape sans puissance
      n'a pas de longueur.
    - `vitesse_ms` : une seule vitesse pour toute la séance, faute de
      calibration. Toutes les étapes ont alors une longueur, y compris celles
      sans consigne de puissance.
    """
    if (parametres is None) == (vitesse_ms is None):
        raise ErreurUtilisateur(
            "séance : donner soit des paramètres calibrés, soit une vitesse — pas les deux"
        )

    def vitesse(etape: Etape) -> float | None:
        if vitesse_ms is not None:
            return vitesse_ms
        cible = etape.puissance_cible_w
        if cible is None:
            return None
        return vitesse_a_plat_ms(cible, parametres)

    mesures: list[LongueurEtape] = []
    for indice, etape in enumerate(seance.etapes):
        v = vitesse(etape)
        recup = seance.recuperation_apres(indice) if etape.type == "bloc" else None
        v_recup = vitesse(recup) if recup is not None else None
        mesures.append(
            LongueurEtape(
                indice=indice,
                etape=etape,
                vitesse_ms=v,
                longueur_m=None if v is None else v * etape.duree_s,
                recup_s=None if recup is None else recup.duree_s,
                # La moitié de la récupération sert à dépasser le bout du
                # segment ; l'autre moitié ramène dessus. C'est donc bien la
                # moitié, pas la totalité, qu'il faut trouver en route.
                au_dela_m=(
                    None if (recup is None or v_recup is None) else v_recup * recup.duree_s / 2
                ),
            )
        )
    return mesures


# --- la commande --------------------------------------------------------------


def executer(
    args: argparse.Namespace, config: Config, client: ClientIntervals | None = None
) -> int:
    """Exécute `ourouler seance`. Sans séance ce jour-là : message clair, code 0.

    Trois modes, exclusifs entre eux sauf `--jour` qui reste compatible avec
    `--fichier-seance` (il y fixe alors le jour auquel la séance importée est
    rattachée, aujourd'hui par défaut) :

    - `--jour` seul : un jour chez Intervals.icu (inchangé depuis L4.1) ;
    - `--depuis`/`--jusqua` ensemble : une plage chez Intervals.icu (F0.3,
      voir `_executer_periode`) ;
    - `--fichier-seance` : un `.ZWO`/`.MRC` donné en ligne de commande au lieu
      d'Intervals.icu (F1, comble C1 de `docs/journal/ux/relecture_f0.md` — voir
      `_executer_fichier`).
    """
    jour_brut = getattr(args, "jour", None)
    depuis_brut = getattr(args, "depuis", None)
    jusqua_brut = getattr(args, "jusqua", None)
    fichier_brut = getattr(args, "fichier_seance", None)
    _valider_mode(jour_brut, depuis_brut, jusqua_brut, fichier_brut)

    if fichier_brut:
        return _executer_fichier(args, config, Path(fichier_brut), _jour(jour_brut))

    if client is None:
        if not config.intervals.renseigne:
            raise ErreurIntervalsAbsent(
                "séance : Intervals.icu n'est pas renseigné — compléter [intervals] "
                "athlete_id et api_key dans la configuration"
            )
        client = ClientIntervals(config.intervals.athlete_id, config.intervals.api_key)

    if depuis_brut or jusqua_brut:
        return _executer_periode(args, config, client, _jour(depuis_brut), _jour(jusqua_brut))

    jour = _jour(jour_brut)
    seance = seance_du_jour(
        client,
        jour,
        ftp_w=config.cycliste.ftp_w,
        zones_puissance=config.seance.zones_pct,
        puissance_endurance_pct=config.seance.puissance_endurance_pct,
        seuil_recuperation_pct=config.seance.seuil_recuperation_pct,
    )
    if seance is None:
        if getattr(args, "json", False):
            print(json.dumps({"jour": jour.isoformat(), "seance": None}, ensure_ascii=False))
        else:
            print(f"Aucune séance vélo planifiée le {jour.isoformat()} sur Intervals.icu.")
        return 0

    return _rendre(args, config, seance)


def _executer_fichier(
    args: argparse.Namespace, config: Config, chemin: Path, jour: date
) -> int:
    """Séance lue depuis un `.ZWO`/`.MRC` au lieu d'Intervals.icu (F1, C1).

    Le reste de l'enchaînement — vitesses, longueurs, rendu — est celui de
    `executer` : un fichier remplace seulement la source de la `Seance`.
    `lire_fichier_seance` lève `ErreurLecture` (sous-classe d'`ErreurUtilisateur`)
    pour un fichier absent, vide, mal formé ou d'extension inconnue ; `cli.py`
    l'affiche en une ligne comme toute autre erreur utilisateur.
    """
    from ourouler.seance.fichier import lire_fichier_seance  # import paresseux : lit un fichier

    seance = lire_fichier_seance(
        chemin,
        ftp_w=config.cycliste.ftp_w,
        seuil_recuperation_pct=config.seance.seuil_recuperation_pct,
        jour=jour,
    )
    return _rendre(args, config, seance)


def _rendre(args: argparse.Namespace, config: Config, seance: Seance) -> int:
    """La queue commune à `--jour` et `--fichier-seance` : vitesses, longueurs, rendu."""
    vitesses, source = _vitesses(config)
    mesures = longueurs(seance, **vitesses)
    if getattr(args, "json", False):
        print(json.dumps(rendre_json(seance, mesures, source), ensure_ascii=False, indent=2))
    else:
        print(rendre_texte(seance, mesures, source))
    return 0


def _valider_mode(
    jour: str | None, depuis: str | None, jusqua: str | None, fichier: str | None = None
) -> None:
    if fichier and (depuis or jusqua):
        raise ErreurUtilisateur(
            "séance : --fichier-seance est exclusif de --depuis/--jusqua "
            "— un fichier ne couvre qu'un seul jour"
        )
    if jour and (depuis or jusqua):
        raise ErreurUtilisateur("séance : --jour et --depuis/--jusqua sont exclusifs")
    if bool(depuis) != bool(jusqua):
        raise ErreurUtilisateur("séance : --depuis et --jusqua se donnent ensemble")


def _executer_periode(
    args: argparse.Namespace, config: Config, client: ClientIntervals, depuis: date, jusqua: date
) -> int:
    """Le mode `--depuis`/`--jusqua` : une séance par jour de la plage, un seul appel réseau.

    `seances_periode` porte déjà la garde `jusqua < depuis`. Chaque jour de la
    plage figure dans le rendu, avec `seance: null` s'il n'y en a pas — un
    jour vide s'y distingue donc d'un jour jamais demandé, qui n'apparaît
    simplement pas.
    """
    resultats = seances_periode(
        client,
        depuis,
        jusqua,
        ftp_w=config.cycliste.ftp_w,
        zones_puissance=config.seance.zones_pct,
        puissance_endurance_pct=config.seance.puissance_endurance_pct,
        seuil_recuperation_pct=config.seance.seuil_recuperation_pct,
    )
    vitesses, source = _vitesses(config)
    if getattr(args, "json", False):
        print(
            json.dumps(
                rendre_json_periode(depuis, jusqua, resultats, vitesses, source),
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print(rendre_texte_periode(depuis, jusqua, resultats, vitesses, source))
    return 0


@dataclass(frozen=True)
class SourceVitesse:
    """D'où vient la vitesse affichée. Elle est toujours dite : ce n'est pas pareil."""

    provenance: str  # « calibration » | « configuration » | « défaut »
    velo: str
    parametres: Parametres | None
    vitesse_ms: float | None

    @property
    def calibree(self) -> bool:
        return self.parametres is not None

    @property
    def resume(self) -> str:
        if self.parametres is not None:
            return (
                f"vitesses par le modèle calibré du vélo {self.velo} "
                f"(CdA {_fr(self.parametres.cda_m2, 3)} m², Crr {_fr(self.parametres.crr, 5)}, "
                f"{_fr(self.parametres.masse_totale_kg, 1)} kg), sur le plat et sans vent"
            )
        return (
            f"vitesses à {_fr((self.vitesse_ms or 0.0) * 3.6, 1)} km/h, la vitesse moyenne de la "
            f"configuration — le vélo {self.velo} n'est pas calibré "
            f"(`ourouler calibrer --velo {self.velo}`)"
        )


def _vitesses(config: Config) -> tuple[dict, SourceVitesse]:
    """Le modèle calibré s'il existe, sinon la vitesse moyenne de la configuration.

    `parametres_du_velo` sait aussi fabriquer des paramètres depuis la
    configuration ou des valeurs par défaut ; on ne s'en sert **pas** ici. Un
    CdA jamais mesuré donnerait une longueur de bloc précise au mètre et
    fausse : entre une fausse précision et une vitesse moyenne assumée, le
    mainteneur a demandé la seconde, et qu'on dise laquelle.
    """
    from ourouler.physique.commande import (  # import paresseux : il lit un fichier
        chemin_calibration,
        velo_demande,
    )
    from ourouler.stockage.calibrations import lire_calibration

    velo = velo_demande(config, None)
    calibration = lire_calibration(chemin_calibration(config), velo.nom)
    if calibration is not None:
        source = SourceVitesse("calibration", velo.nom, calibration.parametres, None)
        return ({"parametres": calibration.parametres}, source)
    vitesse_ms = config.boucle.vitesse_moyenne_kmh / 3.6
    return (
        {"vitesse_ms": vitesse_ms},
        SourceVitesse("configuration", velo.nom, None, vitesse_ms),
    )


def _jour(brut: str | None) -> date:
    if not brut:
        return date.today()
    try:
        return date.fromisoformat(str(brut).strip())
    except ValueError as e:
        raise ErreurUtilisateur(f"--jour {brut!r} : date AAAA-MM-JJ attendue") from e


# --- rendus -------------------------------------------------------------------


def rendre_texte(seance: Seance, mesures: list[LongueurEtape], source: SourceVitesse) -> str:
    lignes = [
        f"Séance du {seance.jour.isoformat()} — « {seance.nom} »",
        f"Durée {_duree_longue(seance.duree_s)}, {len(seance.etapes)} étape(s), "
        f"{len(seance.blocs())} bloc(s)",
    ]
    distance = sum(m.longueur_m for m in mesures if m.longueur_m is not None)
    inconnues = sum(1 for m in mesures if m.longueur_m is None)
    lignes.append(
        f"Distance estimée : {_fr(distance / 1000, 1)} km"
        + (f" (hors {inconnues} étape(s) sans puissance)" if inconnues else "")
    )
    lignes.append(source.resume)
    if seance.meta.get("conversion"):
        # Séance venue d'un fichier (`.ZWO`/`.MRC`, F1) : la conversion des
        # pourcentages de FTP en watts doit être visible et dire qu'elle a eu
        # lieu (docs/journal/ux/maquettes_v1.html E17) — c'est ainsi que quelqu'un
        # découvre que sa FTP est mal renseignée.
        lignes.append(seance.meta["conversion"])
    if seance.meta.get("puissance_approximee"):
        lignes.extend(_approximation(seance))
    for message in _avertissements(seance):
        lignes.append(f"⚠ {message}")
    lignes.append("")

    lignes.append(
        f"  {'#':>2}  {'type':<16}{'durée':>7}  {'puissance':<22}{'route':>9}{'au-delà':>10}"
    )
    for mesure in mesures:
        lignes.append(_ligne(mesure))
    lignes.append("")
    lignes.append(
        "« route » : longueur parcourue pendant l'étape, sur le plat et sans vent. "
        "« au-delà » : route nécessaire après la fin du bloc pour faire demi-tour "
        "pendant la récupération (moitié de la récupération, à la vitesse de récupération)."
    )
    if seance.meta.get("seances_ignorees"):
        autres = ", ".join(str(n) for n in seance.meta["seances_ignorees"])
        lignes.append(
            f"Autre(s) séance(s) vélo ce jour-là, ignorée(s) au profit de la plus longue : {autres}."
        )
    return "\n".join(lignes)


def _approximation(seance: Seance) -> list[str]:
    """Dire d'où sortent les watts quand la séance est prescrite en zones de FC.

    Les deux traductions n'ont pas la même nature et ne se disent donc pas de
    la même façon : les zones basses sont calées sur ce que le cycliste fait
    vraiment en endurance (une mesure), les zones hautes sur la table des
    zones de puissance (une correspondance de numéros).
    """
    meta = seance.meta
    ftp = float(meta.get("ftp_w") or 0.0)
    pct = float(meta.get("puissance_endurance_pct") or 0.0)
    lignes = [
        f"⚠ Puissances **approximées** : la séance est prescrite en zones de fréquence "
        f"cardiaque (FTP {_fr(ftp, 0)} W)."
    ]
    if meta.get("etapes_fc_basses"):
        lignes.append(
            f"  Zones basses (jusqu'à Z{ZONE_FC_BASSE_MAX}) : visées à "
            f"{_fr(pct * 100, 0)} % de FTP, soit {_fr(pct * ftp, 0)} W — la puissance "
            "d'endurance mesurée sur vos sorties, pas le milieu de la zone de puissance."
        )
    if meta.get("etapes_fc_hautes"):
        lignes.append(
            "  Zones hautes : traduites par la table des zones de **puissance** de même "
            "numéro. Une FC n'est pas une puissance : la fourchette est indicative."
        )
    return lignes


def _ligne(mesure: LongueurEtape) -> str:
    etape = mesure.etape
    marques = []
    if etape.elastique:
        marques.append("élastique")
    if mesure.au_dela_m is not None:
        marques.append(f"récup {_duree_courte(mesure.recup_s or 0.0)}")
    return (
        f"  {mesure.indice + 1:>2}  {LIBELLES_TYPE[etape.type]:<16}"
        f"{_duree_courte(etape.duree_s):>7}  {_puissance(etape):<22}"
        f"{_km(mesure.longueur_m):>9}{_km(mesure.au_dela_m):>10}"
        + (f"   {', '.join(marques)}" if marques else "")
    )


def _avertissements(seance: Seance) -> list[str]:
    messages = []
    meta = seance.meta
    if meta.get("vide"):
        messages.append("la séance ne contient aucune étape exploitable.")
    if meta.get("etapes_sans_puissance"):
        messages.append(
            f"{meta['etapes_sans_puissance']} étape(s) sans consigne de puissance : "
            "aucune longueur de route ne leur est attribuée."
        )
    if meta.get("seuil_recuperation_replie"):
        messages.append(
            "FTP inconnue : le seuil qui sépare un bloc d'une récupération a été tiré de la "
            f"séance elle-même ({_fr(float(meta.get('seuil_recuperation_w') or 0), 0)} W), "
            "pas du cycliste."
        )
    if meta.get("etapes_libres_reclassees"):
        detail = ", ".join(
            f"#{r['indice'] + 1} → {LIBELLES_TYPE[r['type']]}"
            for r in meta["etapes_libres_reclassees"]
        )
        messages.append(
            f"étape(s) libre(s), sans puissance ni zone : ce ne sont pas des blocs "
            f"et aucun couloir ne sera cherché pour elles ({detail})."
        )
    if meta.get("unites_inconnues"):
        messages.append(f"unité(s) de consigne non reconnue(s) : {', '.join(meta['unites_inconnues'])}.")
    if meta.get("etapes_nulles"):
        messages.append(f"{meta['etapes_nulles']} étape(s) de durée nulle écartée(s).")
    if meta.get("groupes_ignores"):
        messages.append(f"{meta['groupes_ignores']} groupe(s) à zéro répétition écarté(s).")
    if meta.get("etapes_sans_ftp"):
        messages.append(
            f"{meta['etapes_sans_ftp']} consigne(s) en % de FTP ou en zone n'ont pas pu être "
            "converties en watts."
        )
    if meta.get("ecart_duree_doc_s"):
        messages.append(
            f"la source annonce {_duree_longue(float(meta['duree_doc_s']))}, "
            f"soit {_fr(float(meta['ecart_duree_doc_s']) / 60, 1)} min d'écart avec les étapes lues."
        )
    return messages


def rendre_json(seance: Seance, mesures: list[LongueurEtape], source: SourceVitesse) -> dict:
    return {
        "jour": seance.jour.isoformat(),
        "nom": seance.nom,
        "duree_s": round(seance.duree_s),
        "n_blocs": len(seance.blocs()),
        "distance_estimee_m": round(
            sum(m.longueur_m for m in mesures if m.longueur_m is not None), 1
        ),
        "vitesses": {
            "provenance": source.provenance,
            "velo": source.velo,
            "calibree": source.calibree,
            "vitesse_kmh": None
            if source.vitesse_ms is None
            else round(source.vitesse_ms * 3.6, 2),
        },
        "meta": seance.meta,
        "avertissements": _avertissements(seance),
        "etapes": [
            {
                "indice": m.indice,
                "type": m.etape.type,
                "libelle": m.etape.libelle,
                "duree_s": round(m.etape.duree_s),
                "elastique": m.etape.elastique,
                "puissance_min_w": _arrondi(m.etape.puissance_min_w),
                "puissance_max_w": _arrondi(m.etape.puissance_max_w),
                "puissance_cible_w": _arrondi(m.etape.puissance_cible_w),
                "vitesse_kmh": _arrondi(m.vitesse_kmh, 2),
                "longueur_m": _arrondi(m.longueur_m, 1),
                "recuperation_suivante_s": None if m.recup_s is None else round(m.recup_s),
                "route_au_dela_m": _arrondi(m.au_dela_m, 1),
            }
            for m in mesures
        ],
    }


def rendre_json_periode(
    depuis: date,
    jusqua: date,
    resultats: dict[date, Seance | None],
    vitesses: dict,
    source: SourceVitesse,
) -> dict:
    """Une entrée par jour de `depuis` à `jusqua`, séance ou `null` — jamais d'absent.

    L'objet `seance` de chaque jour a exactement la forme que rend
    `rendre_json` pour `seance --jour` : un front qui sait déjà lire l'un sait
    lire l'autre.
    """
    return {
        "depuis": depuis.isoformat(),
        "jusqua": jusqua.isoformat(),
        "jours": [
            {
                "jour": jour.isoformat(),
                "seance": None
                if seance is None
                else rendre_json(seance, longueurs(seance, **vitesses), source),
            }
            for jour, seance in sorted(resultats.items())
        ],
    }


def rendre_texte_periode(
    depuis: date,
    jusqua: date,
    resultats: dict[date, Seance | None],
    vitesses: dict,
    source: SourceVitesse,
) -> str:
    lignes = [f"Séances planifiées du {depuis.isoformat()} au {jusqua.isoformat()}", ""]
    for jour, seance in sorted(resultats.items()):
        if seance is None:
            lignes.append(f"{jour.isoformat()} — aucune séance vélo planifiée.")
            lignes.append("")
            continue
        lignes.append(rendre_texte(seance, longueurs(seance, **vitesses), source))
        lignes.append("")
    return "\n".join(lignes).rstrip("\n")


# --- petits rendus ------------------------------------------------------------


def _puissance(etape: Etape) -> str:
    """« Z4 (FC) 182-210 W », « 250 W », ou le libellé seul si la puissance manque."""
    bas, haut = etape.puissance_min_w, etape.puissance_max_w
    zone = etape.libelle_court
    if bas is None and haut is None:
        return zone or "—"
    if bas is None or haut is None:
        watts = f"{(bas if bas is not None else haut):.0f} W"
    elif bas == haut:
        watts = f"{bas:.0f} W"
    else:
        watts = f"{bas:.0f}-{haut:.0f} W"
    # Le numéro de zone apporte quelque chose que les watts ne disent pas ; un
    # libellé « 240-260 W » ou « 100 % FTP », lui, redirait la même consigne
    # deux fois de suite.
    return f"{zone} {watts}" if zone.startswith("Z") else watts


def _km(metres: float | None) -> str:
    return "—" if metres is None else f"{_fr(metres / 1000, 1)} km"


def _fr(valeur: float, decimales: int) -> str:
    return f"{valeur:.{decimales}f}".replace(".", ",")


def _arrondi(valeur: float | None, decimales: int = 0) -> float | None:
    if valeur is None:
        return None
    return round(valeur, decimales) if decimales else round(valeur)


def _duree_courte(secondes: float) -> str:
    """« 8:00 » — minutes et secondes."""
    total = int(round(secondes))
    return f"{total // 60}:{total % 60:02d}"


def _duree_longue(secondes: float) -> str:
    """« 1 h 03 » ou « 55 min »."""
    minutes = int(round(secondes / 60))
    if minutes < 60:
        return f"{minutes} min"
    return f"{minutes // 60} h {minutes % 60:02d}"


__all__ = [
    "LongueurEtape",
    "SourceVitesse",
    "executer",
    "longueurs",
    "rendre_json",
    "rendre_json_periode",
    "rendre_texte",
    "rendre_texte_periode",
]
