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

**Ce module dit à qui appartient une ligne ; il ne dit pas qui parle.** Le
rattachement d'une requête à quelqu'un est le travail d'`api/session.py`,
séparé le 18/09/2026 (lot L7.A). Ce fichier portait jusque-là un `resoudre()`
qui rendait `PROPRIETAIRE_LOCAL` quoi qu'il arrive : une requête anonyme
obtenait les données du mainteneur. Il a été **retiré** plutôt que déprécié —
une fonction nommée « résoudre le propriétaire » qui rend toujours le même
est précisément ce qu'on rappelle sans y penser.

L'identité d'aujourd'hui reste unique et fixe en mode personnel
(`PROPRIETAIRE_LOCAL`, un cycliste sur sa machine) ; en mode hébergé, elle
vient du fournisseur de session, et son absence vaut 401. Aucune méthode
d'authentification n'est encore choisie : voir `api/session.py`.
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

#: Le propriétaire servi en **mode personnel** : un cycliste, sa machine.
#: En mode hébergé il ne désigne personne — la session tranche (`session.py`).
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


#: Le propriétaire que `SessionPersonnelle` rend, toujours le même.
PROPRIETAIRE_LOCAL = Proprietaire(IDENTIFIANT_LOCAL)


__all__ = [
    "FORME_IDENTIFIANT",
    "IDENTIFIANT_LOCAL",
    "PROPRIETAIRE_LOCAL",
    "ErreurProprietaire",
    "Proprietaire",
]
