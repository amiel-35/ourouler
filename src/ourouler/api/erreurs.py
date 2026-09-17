"""La forme des pannes, pour un front qui ne peut rien faire d'une trace Python.

Quatre des vingt écrans des maquettes sont des écrans d'échec
(`docs/ux/maquettes_v1.html`). Ils ne peuvent exister que si chaque panne
prévisible a **un code stable** — que le front teste — et **une phrase en
français** — qu'il affiche telle quelle. C'est le contrat de ce module.

Forme unique, quelle que soit la route :

```json
{"erreur": {"code": "brouter_indisponible",
            "message": "BRouter : HTTP 502 sur …",
            "service": "brouter",
            "details": {}}}
```

Trois principes.

**Le code prime sur le message.** Le message vient du cœur, il est écrit pour
un humain et il peut être reformulé sans préavis ; le code, lui, est une
valeur du contrat et ne change pas sans changer la version de l'API.

**« Aucune boucle trouvée » est une panne, « aucune séance ce jour-là » n'en
est pas.** La première est un 422 avec un code ; la seconde est une réponse
normale, 200, avec `seance: null` — la ligne de commande fait déjà cette
distinction (code de sortie 2 contre 0), l'API la garde.

**Un secret ne sort jamais**, même dans un message d'erreur : `assainir`
remplace toute occurrence littérale d'une clé connue avant de rendre la
réponse. Le cœur promet déjà de n'en mettre aucune ; ceci est la ceinture
en plus des bretelles, et elle est testée.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from ourouler.erreurs import (
    ErreurConfig,
    ErreurConnecteur,
    ErreurHorsDomaine,
    ErreurLecture,
    ErreurUtilisateur,
)

#: Ce qui remplace un secret trouvé dans un message.
MASQUE = "***"

#: Longueur minimale d'un secret cherché dans un message : au-dessous, le
#: masquage ferait plus de dégâts que de bien (une clé vide vaut "", et
#: remplacer "" dans une chaîne la détruit).
LONGUEUR_SECRET_MINI = 6


@dataclass(frozen=True)
class ErreurApi(Exception):
    """Une panne déjà traduite : code stable, message français, statut HTTP."""

    code: str
    message: str
    statut: int = 500
    service: str | None = None
    details: dict = field(default_factory=dict)

    def __str__(self) -> str:  # pragma: no cover - confort
        return f"{self.code} : {self.message}"

    def charge(self) -> dict:
        """Le corps JSON rendu au front."""
        return {
            "erreur": {
                "code": self.code,
                "message": self.message,
                "service": self.service,
                "details": self.details,
            }
        }


#: Les services externes, reconnus au préfixe que leurs connecteurs mettent en
#: tête de chaque message. C'est une **convention du cœur**, pas un hasard :
#: `connecteurs/brouter.py`, `meteo/openmeteo.py`, `connecteurs/intervals.py`
#: et `connecteurs/geocodage.py` écrivent tous « <Service> : … ». Un test
#: vérifie que ces préfixes existent encore dans le code des connecteurs.
PREFIXES_SERVICE: tuple[tuple[str, str, str], ...] = (
    # (préfixe du message, nom du service, code d'erreur)
    ("BRouter", "brouter", "brouter_indisponible"),
    ("Open-Meteo", "openmeteo", "meteo_indisponible"),
    ("Intervals.icu", "intervals", "intervals_indisponible"),
    ("BAN", "ban", "geocodage_indisponible"),
    ("Nominatim", "nominatim", "geocodage_indisponible"),
)

#: Ce qu'écrit `connecteurs/intervals._indice` quand la clé est refusée. Une
#: clé révoquée n'est pas une panne du service : le front doit renvoyer le
#: cycliste vers l'écran de la clé, pas lui dire de réessayer plus tard.
INDICE_CLE_REFUSEE = "clé d'API refusée"

#: Le début du message de `sortie/commande._motif_aucune` et de son équivalent
#: dans `boucle`. Ce n'est pas une panne technique : le moteur a répondu, et
#: aucune de ses boucles ne convient. Le front a un écran dessiné pour ça.
#: Les trois messages concernés, tous vérifiés par un test contre le code
#: qui les lève : `sortie/commande._motif_aucune` (aucune boucle ne porte la
#: séance), `sortie/commande._candidates` et `boucle/commande.executer`
#: (le moteur n'a rendu aucune boucle dans la tolérance de distance).
DEBUTS_AUCUNE_BOUCLE = (
    "sortie : la séance",
    "sortie : aucune boucle",
    "boucle : aucune boucle",
)


def assainir(message: str, secrets: Iterable[str] = ()) -> str:
    """Le message, privé de toute occurrence littérale d'un secret connu."""
    propre = str(message)
    for secret in secrets:
        if isinstance(secret, str) and len(secret) >= LONGUEUR_SECRET_MINI:
            propre = propre.replace(secret, MASQUE)
    return propre


def classer(exception: Exception, *, secrets: Iterable[str] = ()) -> ErreurApi:
    """Traduit une exception du cœur en panne d'API.

    Tout ce qui n'est pas une `ErreurUtilisateur` est un bug (contrat de
    `ourouler/erreurs.py`) : le front reçoit `erreur_interne` et un message
    sans détail, la trace reste dans le journal du serveur.
    """
    if isinstance(exception, ErreurApi):
        return exception

    message = assainir(str(exception), secrets)

    # **Avant tout classement par service** : « aucune boucle bornée trouvée »
    # est une `ErreurConnecteur` dans `boucle/commande.py` alors que BRouter a
    # parfaitement répondu — il n'a simplement rien rendu qui tienne dans la
    # tolérance. La classer comme une panne enverrait le front sur l'écran
    # « service indisponible » au lieu de l'écran dessiné pour ce cas-là.
    if isinstance(exception, ErreurUtilisateur) and any(
        message.startswith(debut) for debut in DEBUTS_AUCUNE_BOUCLE
    ):
        return ErreurApi(code="aucune_boucle", message=message, statut=422)

    if isinstance(exception, ErreurHorsDomaine):
        return ErreurApi(
            code="meteo_hors_domaine",
            message=message,
            statut=502,
            service="openmeteo",
        )
    if isinstance(exception, ErreurConnecteur):
        return _connecteur(message)
    if isinstance(exception, ErreurLecture):
        return ErreurApi(code="fichier_illisible", message=message, statut=422)
    if isinstance(exception, ErreurConfig):
        # Une configuration invalide n'est pas une faute du cycliste quand
        # elle vient du fichier du serveur (500) ; elle en est une quand elle
        # vient de ce qu'il vient d'écrire dans son profil — cette
        # distinction-là se fait à l'appel, en levant `profil_invalide`.
        return ErreurApi(code="configuration_invalide", message=message, statut=500)
    if isinstance(exception, ErreurUtilisateur):
        return ErreurApi(code="requete_invalide", message=message, statut=400)

    return ErreurApi(
        code="erreur_interne",
        message="erreur interne du serveur — le détail est dans le journal, pas dans cette réponse",
        statut=500,
    )


def _connecteur(message: str) -> ErreurApi:
    """Le service fautif, lu au préfixe du message, et le code qui va avec."""
    for prefixe, service, code in PREFIXES_SERVICE:
        if not message.startswith(prefixe):
            continue
        if service == "intervals" and INDICE_CLE_REFUSEE in message:
            return ErreurApi(
                code="intervals_refuse",
                message=message,
                statut=502,
                service=service,
            )
        return ErreurApi(code=code, message=message, statut=502, service=service)
    return ErreurApi(code="service_externe_indisponible", message=message, statut=502)


def secrets_de(config) -> tuple[str, ...]:
    """Les chaînes que la réponse ne doit jamais contenir, pour cette configuration.

    Typage volontairement lâche (`config` est une `ourouler.config.Config`) :
    ce module est importé par la traduction d'erreurs, pas par le cœur, et
    n'a pas besoin d'en dépendre.
    """
    valeurs = (
        getattr(getattr(config, "intervals", None), "api_key", "") or "",
        getattr(getattr(config, "brouter", None), "mot_de_passe", "") or "",
    )
    return tuple(v for v in valeurs if v)


__all__ = [
    "DEBUTS_AUCUNE_BOUCLE",
    "INDICE_CLE_REFUSEE",
    "MASQUE",
    "PREFIXES_SERVICE",
    "ErreurApi",
    "assainir",
    "classer",
    "secrets_de",
]
