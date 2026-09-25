"""Lecture et écriture de `calibration.json`.

Le format est figé (`tests/compatibilite/LISEZMOI.md`) : ce module le lit et
l'écrit à l'octet près comme `physique.commande` le faisait avant le lot 7.
Il reçoit un chemin et rend une `physique.parametres_velo.Calibration` ; il
ne sait pas **où** le fichier se trouve — c'est `physique.commande.
chemin_calibration` qui le résout depuis la configuration.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from ourouler.noyau.erreurs import ErreurUtilisateur
from ourouler.physique import calibration as calib
from ourouler.physique.modele import FourchettePorteAPorte, Parametres
from ourouler.physique.parametres_velo import Calibration

#: Nom du fichier où la calibration est écrite, dans le dossier de cache.
NOM_CALIBRATION = "calibration.json"

#: Version du format de `calibration.json`. Un fichier plus récent est ignoré
#: plutôt que relu de travers.
VERSION_CALIBRATION = 1


def lire_calibration(chemin: Path, velo: str) -> Calibration | None:
    """La calibration d'un vélo, ou `None` si le fichier manque, est illisible ou muet.

    Jamais d'exception : une calibration absente n'empêche pas de rouler, elle
    change seulement la mention affichée à côté du temps estimé.
    """
    try:
        charge = json.loads(chemin.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(charge, dict) or charge.get("version") != VERSION_CALIBRATION:
        return None
    velos = charge.get("velos")
    if not isinstance(velos, dict):
        return None
    brut = velos.get(velo) or _sans_casse(velos, velo)
    if not isinstance(brut, dict):
        return None
    try:
        parametres = Parametres(
            masse_totale_kg=float(brut["masse_totale_kg"]),
            cda_m2=float(brut["cda_m2"]),
            crr=float(brut["crr"]),
            rendement=float(brut.get("rendement", Parametres.rendement)),
            rho=float(brut.get("rho", Parametres.rho)),
        )
    except (KeyError, TypeError, ValueError):
        return None
    mae = brut.get("mae")
    biais = brut.get("biais")
    return Calibration(
        velo=velo,
        parametres=parametres,
        date=str(brut.get("date") or ""),
        n_sorties=int(brut.get("n_sorties") or 0),
        mae=float(mae) if isinstance(mae, (int, float)) else None,
        porte_a_porte=_lire_porte_a_porte(brut.get("porte_a_porte")),
        crr_source=str(brut.get("crr_source") or ""),
        pneu=str(brut["pneu"]) if brut.get("pneu") else None,
        biais=float(biais) if isinstance(biais, (int, float)) else None,
        n_validation=int(brut.get("n_validation") or 0),
    )


def _lire_porte_a_porte(brut: object) -> FourchettePorteAPorte | None:
    """La fourchette écrite par `ourouler calibrer`, ou `None` si absente ou illisible.

    Jamais d'exception, comme `lire_calibration` : une fourchette abîmée
    retombe sur la convention, elle n'empêche pas de rouler.
    """
    if not isinstance(brut, dict):
        return None
    try:
        return FourchettePorteAPorte(
            bas=float(brut["bas"]),
            mediane=float(brut["mediane"]),
            haut=float(brut["haut"]),
            provenance="mesure",
            n=int(brut.get("n") or 0),
        )
    except (KeyError, TypeError, ValueError, ErreurUtilisateur):
        return None


def _sans_casse(velos: dict, nom: str) -> dict | None:
    for cle, valeur in velos.items():
        if str(cle).casefold() == nom.casefold():
            return valeur
    return None


def ecrire_calibration(chemin: Path, velo: str, contenu: dict) -> None:
    """Écrit (ou remplace) l'entrée d'un vélo **sans toucher aux autres.

    Calibrer le BMC ne doit pas effacer le RCR : le fichier est relu, l'entrée
    du vélo remplacée, et le tout réécrit.
    """
    charge: dict = {"version": VERSION_CALIBRATION, "velos": {}}
    try:
        ancien = json.loads(chemin.read_text(encoding="utf-8"))
        if isinstance(ancien, dict) and isinstance(ancien.get("velos"), dict):
            charge["velos"] = dict(ancien["velos"])
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        pass
    charge["velos"][velo] = contenu
    try:
        chemin.parent.mkdir(parents=True, exist_ok=True)
        # Écrit à côté puis renommé : depuis L9.4, une calibration s'écrit
        # dans une tâche de fond pendant que d'autres requêtes relisent le
        # fichier — elles doivent voir l'ancien ou le nouveau, jamais un
        # fichier à moitié écrit.
        provisoire = chemin.with_name(chemin.name + ".provisoire")
        provisoire.write_text(
            json.dumps(charge, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        provisoire.replace(chemin)
    except OSError as e:
        raise ErreurUtilisateur(f"calibration : écriture impossible dans {chemin} ({e})") from e


def contenu_calibration(
    rapport: calib.RapportCalibration, crr_source: str = "ajuste", pneu: str | None = None
) -> dict:
    """L'entrée d'un vélo dans `calibration.json`, telle que `ourouler calibrer` l'écrit."""
    a = rapport.ajustement
    return {
        "cda_m2": round(a.cda_m2, 5),
        "crr": round(a.crr, 6),
        # D'où vient le Crr (L9.1) : « pneu » ou « configuration » (fixé, seul
        # le CdA a été cherché) ou « ajuste » (cherché avec le CdA).
        "crr_source": crr_source,
        "pneu": pneu if crr_source == "pneu" else None,
        "masse_totale_kg": round(a.masse_totale_kg, 2),
        "rendement": a.parametres().rendement,
        "rho": round(a.rho_moyen, 4),
        "date": datetime.now().date().isoformat(),
        "n_sorties": rapport.n_apprentissage,
        "n_echantillons": a.n_echantillons,
        "cda_incertitude": _arrondi(a.incertitudes.cda, 5),
        "crr_incertitude": _arrondi(a.incertitudes.crr, 6),
        "rmse_w": round(a.rmse_w, 2),
        "resistance": {
            f"{vitesse:g}": {"force_n": round(force, 2), "puissance_w": round(puissance, 1)}
            for vitesse, force, puissance in a.resistances
        },
        "mae": _arrondi(rapport.validation.mae, 4),
        "mediane": _arrondi(rapport.validation.mediane, 4),
        "biais": _arrondi(rapport.validation.biais, 4),
        "n_validation": rapport.validation.n,
        "n_solo": rapport.n_solo,
        "part_groupe_max": rapport.part_groupe_max,
        "bornes_atteintes": list(a.bornes_atteintes),
        "porte_a_porte": porte_a_porte_json(rapport.porte_a_porte),
    }


def porte_a_porte_json(mesure: calib.MesurePorteAPorte) -> dict | None:
    """La fourchette telle que `calibration.json` la garde, ou `None` si trop peu de sorties.

    `None` n'est pas une panne : `fourchette_du_velo` retombera sur la
    convention, et le dira.
    """
    centiles = mesure.centiles
    if centiles is None:
        return None
    bas, mediane, haut = centiles
    mouvement = mesure.centiles_mouvement
    return {
        "bas": round(bas, 4),
        "mediane": round(mediane, 4),
        "haut": round(haut, 4),
        "centiles": list(calib.CENTILES_PORTE_A_PORTE),
        "n": mesure.n,
        "n_total": len(mesure.sorties),
        # Mesurée sur les seules sorties de validation, jamais vues par
        # l'ajustement du CdA (contre-lecture du 25/09).
        "sorties": "validation",
        "seuil_groupe": mesure.seuil_groupe,
        # Ce que les centiles mesurent : temps écoulé réel (du premier au
        # dernier point, arrêts compris) / temps simulé en mouvement.
        "base": "temps_ecoule",
        # Les mêmes centiles sur le temps **en mouvement** — l'erreur du
        # modèle seul, arrêts exclus. Gardés pour comparer à la note du 23/09,
        # qui les avait lus sous ce nom.
        "ratio_mouvement": None if mouvement is None else [round(x, 4) for x in mouvement],
    }


def _arrondi(valeur: float | None, decimales: int) -> float | None:
    return None if valeur is None else round(valeur, decimales)
