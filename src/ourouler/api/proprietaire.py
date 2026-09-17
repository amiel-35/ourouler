"""À qui appartient ce que la requête demande.

Doctrine §10.2 : « Isolation des données : par utilisateur, vérifiée côté
serveur à chaque requête, jamais seulement côté front. **Aucune requête sans
clause de propriétaire.** »

Les comptes sont le lot F3, pas celui-ci. Ce qui s'écrit **maintenant** est
la *forme* : toute lecture et toute écriture de données passe par un dépôt
dont chaque méthode reçoit un `Proprietaire` en **premier argument
positionnel** — l'équivalent du `WHERE proprietaire = …` qu'aucune requête
n'aura le droit d'omettre le jour où la base sera un PostgreSQL. Un invariant
de `tests/test_invariants.py` le vérifie sur l'arbre syntaxique : un dépôt
qui prendrait un raccourci casse la suite.

Aujourd'hui l'identité est **unique et fixe** (`PROPRIETAIRE_LOCAL`) : un seul
cycliste, celui dont le fichier de configuration est chargé. Demain
`resoudre` lira la session ouverte par le lien à usage unique ou la passkey
(décision 1 du cycle UX) et rendra un identifiant opaque par utilisateur.
Rien d'autre ne bougera : ni les routes, ni les dépôts, ni le cœur.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: Ce qu'un identifiant de propriétaire a le droit d'être. Fermé exprès : il
#: sert de **segment de chemin** dans le dépôt de fichiers, et un identifiant
#: libre y ferait entrer `..` ou un séparateur. Le jour où l'identité viendra
#: d'un fournisseur tiers, elle sera un identifiant opaque qui respecte déjà
#: cette forme (hexadécimal ou base32), pas une adresse e-mail.
FORME_IDENTIFIANT = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")

#: L'unique propriétaire tant qu'il n'y a pas de comptes (lot F3).
IDENTIFIANT_LOCAL = "local"


class ErreurProprietaire(ValueError):
    """Identifiant de propriétaire absent ou mal formé. Jamais une erreur du cycliste."""


@dataclass(frozen=True)
class Proprietaire:
    """À qui appartiennent le profil, les séances déposées et les parcours générés."""

    identifiant: str

    def __post_init__(self) -> None:
        if not isinstance(self.identifiant, str) or not FORME_IDENTIFIANT.match(self.identifiant):
            raise ErreurProprietaire(
                f"identifiant de propriétaire invalide : {self.identifiant!r} — attendu "
                "1 à 64 caractères parmi a-z, 0-9, « _ » et « - »"
            )

    def __str__(self) -> str:  # pragma: no cover - confort de journalisation
        return self.identifiant


#: L'instance unique d'aujourd'hui.
PROPRIETAIRE_LOCAL = Proprietaire(IDENTIFIANT_LOCAL)


def resoudre() -> Proprietaire:
    """Le propriétaire de la requête en cours.

    **Un seul, fixe, aujourd'hui.** C'est ici, et nulle part ailleurs, que F3
    branchera la session : les routes ne connaissent que cette fonction, et
    les dépôts ne connaissent que son résultat.

    Volontairement sans argument : rien dans la requête HTTP ne doit pouvoir
    désigner un autre propriétaire tant que rien n'authentifie personne. Un
    en-tête qui ferait ce travail serait une porte ouverte, pas une
    préfiguration.
    """
    return PROPRIETAIRE_LOCAL


__all__ = [
    "FORME_IDENTIFIANT",
    "IDENTIFIANT_LOCAL",
    "PROPRIETAIRE_LOCAL",
    "ErreurProprietaire",
    "Proprietaire",
    "resoudre",
]
