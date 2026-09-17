"""Les corps de requête, et seulement eux.

Pydantic entre dans le projet avec l'API (`doctrine_architecture.md:74` :
« pas de Pydantic **tant qu'il n'y a pas d'API** »), et il n'en sort pas : le
cœur reste en dataclasses. Il sert ici à deux choses, et pas une de plus —
refuser un corps mal formé avant d'appeler quoi que ce soit, et donner au
front un schéma OpenAPI lisible sur `/docs`.

**Aucun modèle de réponse.** Les réponses sont le JSON que la ligne de
commande rend déjà ; le décrire une seconde fois en Pydantic créerait
exactement la divergence que l'adaptateur évite. Le contrat des réponses est
`docs/ux/discovery_donnees.md`, complété par `docs/ux/api_contrat.md`.

**Un départ est un point, jamais une adresse.** Les routes de parcours
reçoivent des coordonnées déjà tranchées ; c'est le front qui choisit dans
la liste que rend la route de géocodage (F0.7 : « là où la CLI choisit et le
dit, l'API ne choisit pas et fait choisir »).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class Modele(BaseModel):
    """Base commune : un champ inconnu est refusé, pas ignoré en silence."""

    model_config = ConfigDict(extra="forbid")


class Point(Modele):
    """Un point de départ déjà choisi, en degrés décimaux."""

    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    nom: str = Field(default="Départ", max_length=200)


class DemandeSortie(Modele):
    """La séance du jour posée sur une boucle — l'équivalent d'`ourouler sortie`."""

    jour: str | None = Field(default=None, description="AAAA-MM-JJ (défaut : aujourd'hui)")
    heure_depart: str | None = Field(
        default=None, description="HH:MM ou AAAA-MM-JJTHH:MM (défaut : le jour de la séance)"
    )
    distance_km: float | None = Field(default=None, gt=0, le=1000)
    direction: str | None = Field(
        default=None, description="N, NE, … NO ou un azimut en degrés (défaut : tout l'horizon)"
    )
    candidates: int | None = Field(default=None, ge=1, le=24)
    vent: str | None = Field(
        default=None,
        description="retour-dos, depart-dos, travers ou peu-importe (défaut : peu-importe)",
    )
    velo: str | None = None
    profil: str | None = None
    depart: Point | None = Field(
        default=None, description="partir d'ailleurs cette fois ; la configuration n'est pas modifiée"
    )
    fichier_seance: str | None = Field(
        default=None,
        description="identifiant d'un .ZWO/.MRC déposé, au lieu de la séance d'Intervals.icu",
    )


class DemandeBoucle(Modele):
    """Une boucle libre, sans séance — l'équivalent d'`ourouler boucle`."""

    distance_km: float = Field(gt=0, le=1000)
    direction: str = Field(description="N, NE, … NO ou un azimut en degrés")
    heure_depart: str | None = None
    candidates: int | None = Field(default=None, ge=1, le=24)
    profil: str | None = None
    velo: str | None = None
    puissance_w: float | None = Field(default=None, gt=0, le=2000)
    depart: Point | None = None


class DemandeSimulation(Modele):
    """Le temps d'un GPX déjà déposé, à puissance constante."""

    gpx: str = Field(description="identifiant d'un GPX du dépôt (généré ou déposé)")
    puissance_w: float = Field(gt=0, le=2000)
    velo: str | None = None
    heure_depart: str | None = None


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
    velo: str | None = None


__all__ = [
    "ApercuZones",
    "DemandeBoucle",
    "DemandeSimulation",
    "DemandeSortie",
    "Point",
]
