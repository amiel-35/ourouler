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

from collections.abc import Iterable, Mapping
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

#: **Le catalogue des pannes, publié dans le schéma** (ajouté le 17/09/2026).
#:
#: Un front ne peut pas dessiner un état qu'il ne sait pas reconnaître. Tant
#: que ces codes ne vivaient que dans le code de l'API et dans un tableau de
#: `docs/ux/api_contrat.md`, F2 devait lire l'implémentation ou deviner :
#: `meteo_indisponible` (E14 · dégradé) et `intervals_refuse` (E15 · échec)
#: étaient dessinés dans les maquettes et **nommés nulle part** dans le
#: contrat publié. Ils le sont maintenant, avec les autres, et sans liste
#: d'exceptions (doctrine §10.1).
#:
#: Cette table est la **seule** source : la description de l'application et
#: l'énumération du champ `code` du schéma en sont engendrées, et un invariant
#: vérifie qu'aucun code levé par l'API n'en est absent.
CODES_PANNE: dict[str, str] = {
    "requete_invalide": "option fautive, corps mal formé, champ de profil non modifiable",
    "profil_invalide": "ce que le cycliste vient d'écrire ne fait pas une configuration valide",
    "aucune_boucle": "le moteur a répondu, mais aucune boucle ne convient (E18 · échec)",
    "fichier_illisible": ".ZWO/.MRC vide, tronqué ou mal formé",
    "format_non_lu": "un .FIT de séance — décision 5, la V1 lit .ZWO et .MRC",
    "fichier_trop_gros": "plus d'un mégaoctet déposé",
    "fichier_introuvable": "identifiant inconnu, ou appartenant à quelqu'un d'autre",
    "generation_introuvable": (
        "cette génération n'est plus en mémoire — ses GPX ne sont pas écrits sur "
        "le disque (Q40 g) ; relancer la recherche"
    ),
    "route_inconnue": "aucune route à ce chemin — la liste est dans /openapi.json",
    "methode_refusee": "la route existe, pas avec cette méthode",
    "calcul_en_cours": "un calcul occupe déjà le serveur",
    "brouter_indisponible": "BRouter injoignable ou en erreur",
    "meteo_indisponible": (
        "Open-Meteo injoignable ou en erreur — le parcours reste servi sans "
        "météo, la tenue se tait (E14 · dégradé)"
    ),
    "meteo_hors_domaine": "Open-Meteo ne couvre pas ce point ou cette fenêtre (Q19)",
    "intervals_refuse": (
        "clé Intervals.icu révoquée ou refusée — renvoyer vers l'écran de la "
        "clé, pas vers « réessayer » (E15 · échec)"
    ),
    "intervals_indisponible": "panne côté Intervals.icu",
    "geocodage_indisponible": "BAN ou Nominatim en erreur",
    "service_externe_indisponible": "un service externe non reconnu",
    "configuration_invalide": "le TOML du serveur ne charge pas",
    "erreur_interne": "un bug — le détail reste au journal, jamais dans la réponse",
}


#: **Le catalogue des avertissements, publié lui aussi** (ajouté le 17/09/2026).
#:
#: Un avertissement n'est pas une panne : le parcours est servi, mais une
#: affirmation manque — la pluie, le vent, la tenue. Les maquettes en font un
#: bandeau (E14 · dégradé), donc un **état** de l'écran ; et un état se
#: reconnaît à un code, jamais à une phrase.
#:
#: Tant que `avertissements` était une liste de chaînes, le front n'avait pas
#: le choix : il cherchait « météo » dans la prose du cœur
#: (`front/src/composants/Echec.tsx`, relecture F2 · B3). Le jour où
#: quelqu'un reformulait l'avertissement en « Open-Meteo injoignable », le
#: bandeau disparaissait en silence et il restait un parcours servi sans
#: pluie, sans vent et **sans la phrase qui dit pourquoi**. C'est le trou du
#: contrat que cette table bouche.
#:
#: Le classement lit un fragment du message du cœur — même convention que
#: `PREFIXES_SERVICE`, et même garde-fou : un invariant de
#: `tests/test_invariants.py` vérifie que chaque fragment existe encore dans
#: le module qui l'écrit. Une reformulation casse un test du dépôt **avant**
#: d'effacer un bandeau chez le cycliste.
CODES_AVERTISSEMENT: dict[str, str] = {
    "meteo_indisponible": (
        "Open-Meteo n'a rien rendu — le parcours reste servi, sans pluie ni "
        "vent, et la tenue se tait (E14 · dégradé)"
    ),
    "second_avis_indisponible": (
        "le second modèle météo n'a pas répondu — la confiance vaut "
        "« inconnu » sur toutes les cellules"
    ),
    "adresse_introuvable": "aucun candidat pour cette adresse (E16)",
    "autre": (
        "un avertissement que ce catalogue ne nomme pas encore — à afficher "
        "tel quel, jamais à lire pour en déduire un état"
    ),
}

#: Le fragment de message qui reconnaît chaque avertissement, et les modules
#: qui l'écrivent. L'ordre compte : le premier fragment trouvé gagne, et
#: « second avis » passe avant « météo indisponible » parce que la phrase du
#: second avis parle elle aussi de météo. Les chemins servent à l'invariant,
#: pas au classement.
MOTIFS_AVERTISSEMENT: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    # (fragment cherché, code, modules qui écrivent la phrase)
    ("second avis", "second_avis_indisponible", ("meteo/commande.py",)),
    (
        "météo indisponible",
        "meteo_indisponible",
        ("sortie/commande.py", "boucle/commande.py", "physique/commande.py"),
    ),
    # Écrit par l'API elle-même (`routes.geocodage`), pas par le cœur : zéro
    # candidat n'est pas une panne, mais E16 a besoin d'une phrase.
    ("aucune adresse trouvée", "adresse_introuvable", ("api/routes.py",)),
)


def classer_avertissement(message: str) -> str:
    """Le code d'un avertissement, lu au fragment que son émetteur écrit.

    Rend `"autre"` pour ce que le catalogue ne nomme pas encore : l'écran
    affiche alors la phrase sans en déduire d'état, ce qui est le
    comportement sûr — c'est exactement ce que le front ne pouvait pas faire
    tant qu'un avertissement n'était qu'une chaîne.
    """
    minuscules = message.lower()
    for fragment, code, _modules in MOTIFS_AVERTISSEMENT:
        if fragment in minuscules:
            return code
    return "autre"


def table_des_codes() -> str:
    """`CODES_PANNE` en Markdown, pour la description que publie l'application."""
    lignes = ["| code | quand |", "|---|---|"]
    lignes += [f"| `{code}` | {quand} |" for code, quand in CODES_PANNE.items()]
    return "\n".join(lignes)


def table_des_avertissements() -> str:
    """`CODES_AVERTISSEMENT` en Markdown, publié à côté de celle des pannes."""
    lignes = ["| code | quand |", "|---|---|"]
    lignes += [f"| `{code}` | {quand} |" for code, quand in CODES_AVERTISSEMENT.items()]
    return "\n".join(lignes)


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


def assainir(message: str, secrets: Iterable[str] = (), chemins: Mapping[str, str] | None = None) -> str:
    """Le message, privé des secrets connus et des chemins du serveur.

    **Les chemins** (ajouté le 17/09/2026). L'API donne au cœur des chemins
    qu'elle a fabriqués — le `.ZWO` qu'elle vient de ranger, le GPX qu'elle a
    réservé — et le cœur, qui ne sait pas d'où ils viennent, les cite dans ses
    messages : « /var/folders/…/local/fichiers/137a….zwo : fichier vide ».
    Trois défauts d'un coup pour un écran : ce n'est pas le nom que le
    cycliste a déposé, c'est inutilisable dans un navigateur, et en hébergé
    ça décrit l'arborescence du serveur à quiconque regarde
    (`docs/ux/api_contrat.md`, « un fichier est un identifiant, pas un
    chemin »). Le chemin est donc remplacé par ce nom-là, au moment où le
    message sort.
    """
    propre = str(message)
    for secret in secrets:
        if isinstance(secret, str) and len(secret) >= LONGUEUR_SECRET_MINI:
            propre = propre.replace(secret, MASQUE)
    for chemin, nom in (chemins or {}).items():
        propre = propre.replace(str(chemin), nom)
    return propre


def classer(
    exception: Exception,
    *,
    secrets: Iterable[str] = (),
    chemins: Mapping[str, str] | None = None,
) -> ErreurApi:
    """Traduit une exception du cœur en panne d'API.

    Tout ce qui n'est pas une `ErreurUtilisateur` est un bug (contrat de
    `ourouler/erreurs.py`) : le front reçoit `erreur_interne` et un message
    sans détail, la trace reste dans le journal du serveur.

    `chemins` associe un chemin que l'API a fabriqué au nom que le front
    connaît — voir `assainir`.
    """
    if isinstance(exception, ErreurApi):
        return exception

    message = assainir(str(exception), secrets, chemins)

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
    "CODES_AVERTISSEMENT",
    "CODES_PANNE",
    "DEBUTS_AUCUNE_BOUCLE",
    "INDICE_CLE_REFUSEE",
    "MASQUE",
    "MOTIFS_AVERTISSEMENT",
    "PREFIXES_SERVICE",
    "ErreurApi",
    "assainir",
    "classer",
    "classer_avertissement",
    "secrets_de",
    "table_des_avertissements",
    "table_des_codes",
]
