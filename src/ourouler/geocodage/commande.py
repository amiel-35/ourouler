"""Sous-commande `ourouler geocoder ADRESSE` : rend les candidats, sans trancher.

Le cas d'usage (`executer`) reçoit une `DemandeGeocodage` déjà lue par
l'entrée (`commandes/geocoder.py`) et rend les candidats ; il ne connaît ni
argparse ni la sortie standard. Les clients sont injectables pour que les
tests ne touchent jamais le réseau. Aucun réglage du cycliste n'est lu : le
contexte est accepté pour que tous les services s'appellent de la même façon,
et ignoré.
"""

from __future__ import annotations

from dataclasses import dataclass

from ourouler.connecteurs.geocodage import (
    LIMITE_DEFAUT,
    Candidat,
    ClientBAN,
    ClientNominatim,
    ambiguite,
    chercher_adresse,
)
from ourouler.services.contexte import Contexte


@dataclass(frozen=True)
class DemandeGeocodage:
    """L'adresse à chercher et le nombre maximal de candidats."""

    adresse: str
    limite: int = LIMITE_DEFAUT


@dataclass(frozen=True)
class ResultatGeocodage:
    """Les candidats, dans l'ordre des services, et l'adresse qui les a donnés."""

    adresse: str
    candidats: list[Candidat]


def executer(
    demande: DemandeGeocodage,
    contexte: Contexte | None = None,
    ban: ClientBAN | None = None,
    nominatim: ClientNominatim | None = None,
) -> ResultatGeocodage:
    """Cherche l'adresse. Ne tranche jamais : c'est le rendu qui dit l'ambiguïté."""
    del contexte  # rien à lire du cycliste ici
    candidats = chercher_adresse(demande.adresse, ban=ban, nominatim=nominatim, limite=demande.limite)
    return ResultatGeocodage(adresse=demande.adresse, candidats=candidats)


def rendre_json(adresse: str, candidats: list[Candidat]) -> dict:
    trouble = ambiguite(candidats)
    return {
        "adresse": adresse,
        "candidats": [
            {
                "label": c.label,
                "latitude": c.latitude,
                "longitude": c.longitude,
                "score": c.score,
                "source": c.source,
                "commune": c.commune,
                "code_postal": c.code_postal,
            }
            for c in candidats
        ],
        # Ce que le front doit savoir pour décider s'il fait confirmer sur la
        # carte ou s'il redemande la commune. **Ce n'est pas un arbitrage** :
        # les candidats sont rendus quand même, l'API ne tranche jamais.
        "ambigu": trouble is not None,
        "motif_ambiguite": None if trouble is None else trouble.motif,
    }


def rendre_texte(adresse: str, candidats: list[Candidat]) -> str:
    """La liste des candidats. **Cette commande ne refuse jamais** : elle est là pour montrer.

    C'est `--adresse-depart` qui refuse une adresse ambiguë (décision Q34) ; `ourouler
    geocoder` est précisément l'outil qu'on lance ensuite pour voir ce qui
    s'oppose. Elle le dit en une ligne, elle ne le sanctionne pas.
    """
    if not candidats:
        return f"aucune adresse trouvée pour « {adresse} »"
    lignes = [f"{len(candidats)} candidat(s) pour « {adresse} » :"]
    for i, c in enumerate(candidats, start=1):
        ou = c.commune or "commune inconnue"
        if c.code_postal:
            ou += f" {c.code_postal}"
        lignes.append(
            f"  {i}. {c.label} — {ou} — {c.latitude:.5f}, {c.longitude:.5f} (score {c.score:.4f}, {c.source})"
        )
    trouble = ambiguite(candidats)
    if trouble is not None:
        lignes.append(
            f"adresse ambiguë — {trouble.phrase} ; "
            "--adresse-depart la refuserait, réécrire avec la commune et le code postal"
        )
    return "\n".join(lignes)
