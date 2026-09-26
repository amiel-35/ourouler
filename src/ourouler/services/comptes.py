"""Les comptes de l'hébergé : inviter, lister les invitations, réinitialiser, retirer.

Ce que font `ourouler inviter`, `invitations`, `reinitialiser` et `retirer`, sans
argparse ni affichage. Le service reçoit tout déjà résolu : un dépôt de comptes
ouvert sur la base, l'URL publique du front, les paramètres du relais SMTP (et,
pour les tests, sa fabrique de client), de quoi demander confirmation, de quoi
retrouver les dépôts du serveur hébergé et de quoi effacer. Il ne lit lui-même
ni fichier, ni variable d'environnement, ni chemin de l'utilisateur : c'est
`cli/` qui rassemble tout cela (le cœur ne lit ni configuration ni environnement) et affiche le résultat par
`rendu/comptes.py`.

**Toute la logique d'état d'une invitation — compte déjà actif, invitation en
cours, invitation expirée — vit dans `DepotComptes`** (`api/comptes.py`). Elle
n'est ni recopiée ni redécidée ici : le service rend ce que le dépôt rend.

**Retirer n'efface jamais par un chemin à lui** : il appelle la fonction
d'effacement qu'on lui passe — `vie_privee.effacer_donnees`, la même que
`DELETE /moi` — avec les dépôts du serveur hébergé.

`api/comptes.py` (le dépôt PostgreSQL) et `api/courriel.py` (le client SMTP)
sont rangés, par leur rôle, au stockage et aux connecteurs dans la règle
d'imports (`tests/test_architecture.py`) : un service a le droit de les
importer, pas le reste du paquet `api/`.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from ourouler.api.comptes import DepotComptes, ErreurCompte, InvitationEmise, normaliser_email
from ourouler.api.courriel import (
    FabriqueSMTP,
    ParametresBrevo,
    envoyer_invitation,
    message_invitation,
    message_reinitialisation,
)


def construire_lien(url_publique: str, jeton: str) -> str:
    """`<url_publique>/entrer?jeton=<jeton>` — la seule forme du lien d'invitation."""
    return f"{url_publique.rstrip('/')}/entrer?jeton={jeton}"


def construire_lien_reinitialisation(url_publique: str, jeton: str) -> str:
    """`<url_publique>/reinitialiser?jeton=<jeton>` — le lien de `ourouler reinitialiser`.

    Chemin distinct de `construire_lien` (`/entrer`) : même mécanisme de jeton
    (`api/comptes.py`), mais un écran différent côté front — « choisissez un nouveau mot
    de passe » n'est pas « bienvenue, créez votre compte »."""
    return f"{url_publique.rstrip('/')}/reinitialiser?jeton={jeton}"


@dataclass(frozen=True)
class LienEmis:
    """Ce qu'`inviter` et `reinitialiser` rendent : l'invitation, son lien, et si un courriel est parti."""

    emise: InvitationEmise
    lien: str
    courriel_envoye: bool

    def __repr__(self) -> str:
        """Masque le lien, qui porte le jeton : un `repr` finit dans un journal ou une trace."""
        return f"LienEmis(emise={self.emise!r}, lien=<masqué>, courriel_envoye={self.courriel_envoye})"


@dataclass(frozen=True)
class InvitationListee:
    """Une invitation en cours telle qu'`ourouler invitations` la montre."""

    adresse: str
    lien: str
    expire_le: datetime

    def __repr__(self) -> str:
        return f"InvitationListee(adresse=<masqué>, lien=<masqué>, expire_le={self.expire_le.isoformat()})"


@dataclass(frozen=True)
class DepotsHeberges:
    """Les quatre dépôts de données personnelles du serveur hébergé, et son dossier de cache.

    Le type que rend le résolveur passé à `retirer` (`cli.comptes._depots_de_l_hebergement`).
    """

    profils: Any
    fichiers: Any
    journal: Any
    generations: Any
    dossier_cache: Path


@dataclass(frozen=True)
class Retrait:
    """Ce que `retirer` rend quand le compte est fermé : l'adresse et le bilan de l'effacement."""

    adresse: str
    donnees: dict

    def __repr__(self) -> str:
        """Masque l'adresse, comme `LienEmis` et `InvitationListee` : un `repr` finit dans un journal."""
        return f"Retrait(adresse=<masqué>, donnees={self.donnees!r})"


def inviter(
    adresse: str,
    *,
    depot: DepotComptes,
    url_publique: str,
    sans_courriel: bool,
    parametres_brevo: ParametresBrevo | None,
    invite_par: str,
    fabrique_smtp: FabriqueSMTP | None = None,
) -> LienEmis:
    """Invite `adresse` : émet (ou reprend) l'invitation, et envoie le courriel sauf `sans_courriel`.

    Une invitation refusée (compte déjà actif, adresse invalide) laisse remonter
    l'exception du dépôt telle quelle : `ErreurCompte` et ses sous-classes héritent
    d'`ErreurUtilisateur`, et `cli.main()` les affiche en une ligne, code 2, sans trace.

    `invite_par` : « Prénom Nom » de qui invite, ou une chaîne vide.
    """
    adresse = normaliser_email(adresse)
    emise = depot.inviter(adresse)
    lien = construire_lien(url_publique, emise.jeton)

    envoye = False
    if not sans_courriel:
        if parametres_brevo is None:
            raise ValueError(  # bug d'appel : cli/comptes.py doit charger service.toml avant d'appeler ceci
                "executer_inviter appelé sans parametres_brevo alors que --sans-courriel n'est pas posé"
            )
        message = message_invitation(
            destinataire=adresse,
            lien=lien,
            expire_le=emise.invitation.expire_le,
            parametres=parametres_brevo,
            invite_par=invite_par,
        )
        envoyer_invitation(parametres_brevo, message, fabrique=fabrique_smtp)
        envoye = True
    return LienEmis(emise=emise, lien=lien, courriel_envoye=envoye)


def reinitialiser(
    adresse: str,
    *,
    depot: DepotComptes,
    url_publique: str,
    sans_courriel: bool,
    parametres_brevo: ParametresBrevo | None,
    fabrique_smtp: FabriqueSMTP | None = None,
) -> LienEmis:
    """Émet un lien de nouveau mot de passe pour un compte **déjà actif**.

    Réservé à l'exploitant, en ligne de commande : aucune route HTTP anonyme n'appelle
    `DepotComptes.reinitialiser` — voir la note de module d'`api/comptes.py`. Une adresse
    sans compte actif laisse remonter l'`ErreurCompte` du dépôt telle quelle.
    """
    adresse = normaliser_email(adresse)
    emise = depot.reinitialiser(adresse)
    lien = construire_lien_reinitialisation(url_publique, emise.jeton)

    envoye = False
    if not sans_courriel:
        if parametres_brevo is None:
            raise ValueError(  # bug d'appel : cli/comptes.py doit charger service.toml avant d'appeler ceci
                "executer_reinitialiser appelé sans parametres_brevo alors que --sans-courriel n'est pas posé"
            )
        message = message_reinitialisation(
            destinataire=adresse,
            lien=lien,
            expire_le=emise.invitation.expire_le,
            parametres=parametres_brevo,
        )
        envoyer_invitation(parametres_brevo, message, fabrique=fabrique_smtp)
        envoye = True
    return LienEmis(emise=emise, lien=lien, courriel_envoye=envoye)


def invitations_en_cours(*, depot: DepotComptes, url_publique: str) -> list[InvitationListee]:
    """Les invitations en cours, adresse et lien compris : ce qui rend un lien retrouvable."""
    return [
        InvitationListee(
            adresse=invitation.email,
            lien=construire_lien(url_publique, invitation.jeton),
            expire_le=invitation.expire_le,
        )
        for invitation in depot.invitations_en_cours()
    ]


def retirer(
    adresse: str,
    *,
    depot: DepotComptes,
    confirmer: Callable[[str], bool],
    resoudre_depots_heberges: Callable[[], DepotsHeberges],
    effacer_donnees: Callable[..., dict],
) -> Retrait | None:
    """Ferme le compte d'`adresse` et efface ses données personnelles ; `None` si non confirmé.

    L'ordre des vérifications est voulu : l'adresse d'abord (une adresse sans compte
    lève `ErreurCompte`), puis la confirmation (`confirmer(adresse)` reçoit l'adresse
    normalisée), et **seulement ensuite** `resoudre_depots_heberges`. C'est ce qui laisse
    le résolveur de `cli/comptes.py` refuser proprement (dossier de données introuvable) sans
    avoir fait attendre une confirmation pour rien, et sans masquer un refus d'adresse
    derrière un refus d'environnement qui n'a rien à voir.

    `effacer_donnees` est `vie_privee.effacer_donnees`, le seul chemin d'effacement du
    dépôt, appelé exactement comme `DELETE /moi` l'appelle.
    """
    adresse = normaliser_email(adresse)
    compte = depot.compte_par_email(adresse)
    if compte is None:
        raise ErreurCompte(f"{adresse} n'a pas de compte — rien à retirer")

    if not confirmer(adresse):
        return None

    heberges = resoudre_depots_heberges()
    proprietaire = depot.proprietaire_du_compte(compte.identifiant)
    donnees = effacer_donnees(
        proprietaire,
        profils=heberges.profils,
        fichiers=heberges.fichiers,
        journal=heberges.journal,
        generations=heberges.generations,
        dossier_cache=heberges.dossier_cache,
        comptes=depot,
    )
    return Retrait(adresse=adresse, donnees=donnees)


__all__ = [
    "DepotsHeberges",
    "InvitationListee",
    "LienEmis",
    "Retrait",
    "construire_lien",
    "construire_lien_reinitialisation",
    "invitations_en_cours",
    "inviter",
    "reinitialiser",
    "retirer",
]
