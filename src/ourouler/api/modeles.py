"""Les corps de requête, et seulement eux.

Pydantic entre dans le projet avec l'API (`doctrine_architecture.md:74` :
« pas de Pydantic **tant qu'il n'y a pas d'API** »), et il n'en sort pas : le
cœur reste en dataclasses. Il sert ici à deux choses, et pas une de plus —
refuser un corps mal formé avant d'appeler quoi que ce soit, et donner au
front un schéma OpenAPI lisible sur `/docs`.

**Aucun modèle de réponse de succès.** Les réponses heureuses sont le JSON que
la ligne de commande rend déjà ; le décrire une seconde fois en Pydantic
créerait exactement la divergence que l'adaptateur évite. Le contrat de ces
réponses est `docs/ux/discovery_donnees.md`, complété par
`docs/ux/api_contrat.md`.

**Les pannes, elles, ont un modèle** (`ReponseErreur`, ajouté le 17/09/2026),
et ce n'est pas la même chose : leur forme n'appartient pas au cœur, elle
appartient à l'API — c'est elle qui traduit une exception en code stable. La
décrire ici ne duplique rien ; ne pas la décrire laissait quatre écrans
d'échec dessinés sans aucun nom publié à quoi les brancher.

**Un départ est un point, jamais une adresse.** Les routes de parcours
reçoivent des coordonnées déjà tranchées ; c'est le front qui choisit dans
la liste que rend la route de géocodage (F0.7 : « là où la CLI choisit et le
dit, l'API ne choisit pas et fait choisir »).
"""

from __future__ import annotations

import re
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

from ourouler.api.erreurs import CODES_PANNE

#: Ce qu'une chaîne doit contenir pour vouloir dire quelque chose : au moins
#: une lettre ou un chiffre.
#:
#: **Pourquoi ce n'est pas `min_length=1`** (17/09/2026). Trois entrées
#: distinctes passaient cette borne sans être des valeurs : la chaîne vide, la
#: chaîne d'espaces, la chaîne d'octets de contrôle. Chacune traversait
#: l'API et se faisait interpréter plus bas — un `jour=""` devenait
#: « aujourd'hui », parce qu'une chaîne vide est fausse en Python et que le
#: cœur lit ses options avec un défaut ; une adresse d'espaces partait chez la
#: BAN, y consommait un appel et revenait en 502 avec une phrase en anglais.
#: Un champ à moitié effacé dans un formulaire produit exactement ça, et
#: E16 prévient qu'il en enverra (« l'écran affiche une estimation qui bouge à
#: chaque frappe »).
CARACTERE_UTILE = re.compile(r"\w")


def _texte_utile(valeur: str) -> str:
    """La chaîne, sans ses blancs de bord — ou un refus si elle ne dit rien."""
    coupe = valeur.strip()
    if not CARACTERE_UTILE.search(coupe):
        raise ValueError(
            "valeur vide de sens : au moins une lettre ou un chiffre est attendu "
            "(une chaîne vide, d'espaces ou d'octets de contrôle n'est pas une valeur)"
        )
    return coupe


#: Une chaîne qui veut dire quelque chose. À préférer partout à `str` dans un
#: corps de requête : ce qui n'a pas de sens se refuse au bord, pas trois
#: couches plus bas ni chez un service d'en face.
TexteUtile = Annotated[str, AfterValidator(_texte_utile)]


class Modele(BaseModel):
    """Base commune : un champ inconnu est refusé, pas ignoré en silence."""

    model_config = ConfigDict(extra="forbid")


class Panne(Modele):
    """Une panne traduite : un code stable, une phrase française, le service fautif.

    **Le code prime sur le message.** Le message vient du cœur et peut être
    reformulé ; le code est une valeur du contrat, et l'énumération ci-dessous
    est celle que le front branche sur ses écrans. Elle est engendrée de
    `erreurs.CODES_PANNE`, qui en est la seule source.
    """

    code: str = Field(
        description="l'état d'échec, stable — voir la description de l'API pour le sens de chacun",
        json_schema_extra={"enum": sorted(CODES_PANNE)},
    )
    message: str = Field(description="la phrase française que l'écran affiche telle quelle")
    service: str | None = Field(
        default=None, description="le service externe fautif, quand il y en a un"
    )
    details: dict = Field(
        default_factory=dict, description="ce que l'écran peut exploiter en plus du message"
    )


class ReponseErreur(Modele):
    """La forme **unique** d'une réponse en panne, quelle que soit la route.

    Une réponse porte `donnees` ou `erreur`, jamais les deux : c'est ce qui
    permet à un front de n'avoir qu'une gestion d'erreur.
    """

    erreur: Panne


class Point(Modele):
    """Un point de départ déjà choisi, en degrés décimaux."""

    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    nom: str = Field(default="Départ", max_length=200)


class DemandeSortie(Modele):
    """La séance du jour posée sur une boucle — l'équivalent d'`ourouler sortie`."""

    jour: TexteUtile | None = Field(default=None, description="AAAA-MM-JJ (défaut : aujourd'hui)")
    heure_depart: TexteUtile | None = Field(
        default=None, description="HH:MM ou AAAA-MM-JJTHH:MM (défaut : le jour de la séance)"
    )
    distance_km: float | None = Field(default=None, gt=0, le=1000)
    direction: TexteUtile | None = Field(
        default=None, description="N, NE, … NO ou un azimut en degrés (défaut : tout l'horizon)"
    )
    candidates: int | None = Field(default=None, ge=1, le=24)
    vent: TexteUtile | None = Field(
        default=None,
        description="retour-dos, depart-dos, travers ou peu-importe (défaut : peu-importe)",
    )
    velo: TexteUtile | None = None
    profil: TexteUtile | None = None
    depart: Point | None = Field(
        default=None, description="partir d'ailleurs cette fois ; la configuration n'est pas modifiée"
    )
    fichier_seance: TexteUtile | None = Field(
        default=None,
        description="identifiant d'un .ZWO/.MRC déposé, au lieu de la séance d'Intervals.icu",
    )


class DemandeBoucle(Modele):
    """Une boucle libre, sans séance — l'équivalent d'`ourouler boucle`.

    Q47 : `direction` était obligatoire alors que `sortie` balaie déjà tout
    l'horizon quand rien n'est demandé — une contrainte héritée, pas un choix
    de conception. Elle est désormais facultative, comme côté `sortie`.
    """

    distance_km: float = Field(gt=0, le=1000)
    direction: TexteUtile | None = Field(
        default=None, description="N, NE, … NO ou un azimut en degrés (défaut : tout l'horizon)"
    )
    heure_depart: TexteUtile | None = None
    candidates: int | None = Field(default=None, ge=1, le=24)
    profil: TexteUtile | None = None
    velo: TexteUtile | None = None
    puissance_w: float | None = Field(default=None, gt=0, le=2000)
    depart: Point | None = None


class DemandeSimulation(Modele):
    """Le temps d'un GPX déjà déposé, à puissance constante."""

    gpx: TexteUtile = Field(description="identifiant d'un GPX du dépôt (généré ou déposé)")
    puissance_w: float = Field(gt=0, le=2000)
    velo: TexteUtile | None = None
    heure_depart: TexteUtile | None = None


class ApercuZones(Modele):
    """Les trois valeurs liées de l'écran de FTP, recalculées **sans rien stocker**.

    Exactement un des trois champs : éditer la puissance ou la vitesse à plat
    déplace la position, et c'est la position qui sera stockée si le cycliste
    valide (décision 7). La moyenne compteur n'est pas éditable (décision 8) —
    elle n'a donc pas de champ ici, et c'est voulu.
    """

    position_zone: float | None = Field(default=None, ge=-2, le=3)
    puissance_w: float | None = Field(default=None, gt=0, le=2000)
    vitesse_a_plat_kmh: float | None = Field(default=None, gt=0, le=100)
    velo: TexteUtile | None = None


class DemandeEntree(Modele):
    """Le jeton d'une invitation et le secret choisi — active le compte, ouvre la session.

    `jeton` et `secret` restent des `TexteUtile` ordinaires : ce module ne
    connaît pas la forme du jeton (elle vit en base et dans `comptes.py`), et
    aucune politique de mot de passe n'a été tranchée — inventer une longueur
    minimale ici serait décider une règle produit à la place du mainteneur.
    """

    jeton: TexteUtile = Field(description="le jeton reçu par le lien d'invitation")
    secret: TexteUtile = Field(description="le mot de passe choisi pour ce compte")


class DemandeConnexion(Modele):
    """L'adresse et le secret d'un compte déjà actif — pour revenir sans jeton."""

    email: TexteUtile = Field(description="l'adresse du compte")
    secret: TexteUtile = Field(description="le mot de passe du compte")


__all__ = [
    "ApercuZones",
    "DemandeBoucle",
    "DemandeConnexion",
    "DemandeEntree",
    "DemandeSimulation",
    "DemandeSortie",
    "Panne",
    "Point",
    "TexteUtile",
    "ReponseErreur",
]
