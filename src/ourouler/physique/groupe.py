"""La détection des sorties en groupe : rouler durablement plus vite que la puissance ne le justifie.

Sorti de physique/calibration.py, qui réexporte ces noms. Physique pure
comme lui ; mêmes calculs, dans le même ordre, avant et après le déplacement.
"""

from __future__ import annotations

from ourouler.noyau.activite import Activite
from ourouler.noyau.meteo import HeureArchive
from ourouler.physique.echantillonnage import echantillonner
from ourouler.physique.modele import Parametres, vitesse_regime

#: Une sortie est dite « en groupe » si le résidu de vitesse dépasse ce seuil
#: sur plus de `PART_DISTANCE_GROUPE` de la distance retenue (contrat §3).
SEUIL_RESIDU_GROUPE = 0.08
PART_DISTANCE_GROUPE = 0.50


# --- détection des sorties en groupe -----------------------------------------


def detecter_groupe(
    activite: Activite,
    p: Parametres,
    vent: list[HeureArchive],
    *,
    ftp_w: float = 250.0,
    vitesse_min_kmh: float = 8.0,
) -> tuple[bool, float]:
    """(en groupe ?, part de la distance anormalement rapide).

    Pour chaque tronçon retenu, on demande au modèle la vitesse que la
    puissance mesurée justifie, compte tenu de la pente et du vent. Rouler
    durablement plus vite que ça, c'est rouler dans une roue : le peloton
    fait gagner 20 à 30 % de traînée, et un tel gain attribué au vélo
    fausserait son CdA pour toutes les autres sorties.

    Le seuil est celui du contrat : résidu > +8 % sur plus de la moitié de la
    distance **retenue** (les tronçons écartés — arrêts, accélérations — ne
    disent rien d'un équilibre).
    """
    echantillons = [
        e
        for e in echantillonner(activite, vent, ftp_w=ftp_w, vitesse_min_kmh=vitesse_min_kmh)
        if e.retenu
    ]
    distance = sum(e.longueur_m for e in echantillons)
    if distance <= 0:
        return (False, 0.0)
    rapide = 0.0
    for e in echantillons:
        # La part de la puissance qui a servi à accélérer n'a pas servi à
        # tenir une vitesse : la retirer avant de demander au modèle quelle
        # vitesse d'équilibre la puissance justifie, sinon tout tronçon de
        # relance passerait pour un tronçon d'aspiration.
        equilibre = e.puissance_w - e.puissance_cinetique_w(p.masse_totale_kg, p.rendement)
        attendue = vitesse_regime(equilibre, e.pente, e.vent_face_ms, p)
        if attendue > 0 and (e.v_ms - attendue) / attendue > SEUIL_RESIDU_GROUPE:
            rapide += e.longueur_m
    part = rapide / distance
    return (part > PART_DISTANCE_GROUPE, part)
