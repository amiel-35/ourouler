"""`ourouler inviter` et `ourouler invitations` : l'orchestration, sans jamais lire de fichier.

Lot L7.2-B. Ce module reçoit tout ce dont il a besoin déjà résolu — un dépôt
de comptes ouvert sur la base, l'URL publique du service, et, si un courriel
doit partir, les paramètres Brevo déjà validés. C'est `cli.py` qui les
rassemble : lui seul a le droit de lire le fichier de secrets du service, la
variable qui porte l'URL publique, et celle qui porte l'URL de la base (règle
absolue 2). Ce module n'en sait rien et ne pourrait pas fonctionner sans
qu'on les lui apporte.

**Toute la logique d'état d'une invitation — compte déjà actif, invitation en
cours, invitation expirée — vit dans `DepotComptes.inviter`** (lot L7.2-A).
Elle n'est ni recopiée ni redécidée ici : ce module affiche ce que le dépôt
rend, il ne le devine pas.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC

from ourouler.api.comptes import DepotComptes, InvitationEmise, normaliser_email
from ourouler.api.courriel import FabriqueSMTP, ParametresBrevo, envoyer_invitation, message_invitation
from ourouler.config import Config


def construire_lien(url_publique: str, jeton: str) -> str:
    """`<url_publique>/entrer?jeton=<jeton>` — la seule forme du lien d'invitation."""
    return f"{url_publique.rstrip('/')}/entrer?jeton={jeton}"


def _nom_complet(config: Config) -> str:
    """« Prénom Nom » du cycliste qui invite (celui qui a lancé la commande), ou une chaîne vide.

    Une configuration écrite avant Q36 ne porte ni l'un ni l'autre : l'e-mail dit alors
    « vous êtes invité·e », sans inventer de nom (règle absolue 1).
    """
    return " ".join(morceau for morceau in (config.cycliste.prenom, config.cycliste.nom) if morceau)


def executer_inviter(
    args: argparse.Namespace,
    config: Config,
    *,
    depot: DepotComptes,
    url_publique: str,
    parametres_brevo: ParametresBrevo | None,
    fabrique_smtp: FabriqueSMTP | None = None,
) -> int:
    """Exécute `ourouler inviter ADRESSE`. Renvoie le code de sortie (0 = succès).

    Une invitation refusée (compte déjà actif, adresse invalide) laisse remonter
    l'exception du dépôt telle quelle : `ErreurCompte` et ses sous-classes héritent
    d'`ErreurUtilisateur`, et `cli.main()` les affiche en une ligne, code 2, sans trace —
    ce module n'a rien à en faire de plus.

    **Le lien s'affiche toujours**, que le courriel parte ou non — décision explicite du
    mainteneur (voir le brief du lot) : il veut pouvoir le relire et le renvoyer par un
    autre canal.
    """
    sans_courriel = getattr(args, "sans_courriel", False)
    adresse = normaliser_email(args.adresse)

    emise = depot.inviter(adresse)
    lien = construire_lien(url_publique, emise.jeton)

    envoye = False
    if not sans_courriel:
        if parametres_brevo is None:
            raise ValueError(  # bug d'appel : cli.py doit charger service.toml avant d'appeler ceci
                "executer_inviter appelé sans parametres_brevo alors que --sans-courriel n'est pas posé"
            )
        message = message_invitation(
            destinataire=adresse,
            lien=lien,
            expire_le=emise.invitation.expire_le,
            parametres=parametres_brevo,
            invite_par=_nom_complet(config),
        )
        envoyer_invitation(parametres_brevo, message, fabrique=fabrique_smtp)
        envoye = True

    _afficher_invitation(args, emise, lien, envoye=envoye)
    return 0


def _afficher_invitation(
    args: argparse.Namespace, emise: InvitationEmise, lien: str, *, envoye: bool
) -> None:
    echeance = emise.invitation.expire_le.astimezone(UTC).strftime("%d/%m/%Y")
    if getattr(args, "json", False):
        print(
            json.dumps(
                {
                    "lien": lien,
                    "expire_le": emise.invitation.expire_le.isoformat(),
                    "deja_en_cours": emise.deja_en_cours,
                    "courriel_envoye": envoye,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return
    if emise.deja_en_cours:
        print("ourouler : invitation déjà en cours — le même jeton est repris, rien n'est émis à neuf")
    else:
        print("ourouler : invitation créée")
    print(f"lien           : {lien}")
    print(f"valable jusqu'au {echeance}")
    print("courriel envoyé" if envoye else "courriel non envoyé (--sans-courriel)")


def executer_invitations(
    args: argparse.Namespace,
    config: Config,
    *,
    depot: DepotComptes,
    url_publique: str,
) -> int:
    """Exécute `ourouler invitations` : les invitations en cours, adresse et lien compris.

    Ce qui rend le lien **retrouvable** sans fouiller un historique de terminal ou de
    messagerie — demande nommée du mainteneur. Rien de plus : pas de filtre, pas de
    pagination.
    """
    del config  # non utilisé ici, gardé pour la même signature que les autres sous-commandes
    invitations = depot.invitations_en_cours()

    if getattr(args, "json", False):
        print(
            json.dumps(
                [
                    {
                        "adresse": invitation.email,
                        "lien": construire_lien(url_publique, invitation.jeton),
                        "expire_le": invitation.expire_le.isoformat(),
                    }
                    for invitation in invitations
                ],
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    if not invitations:
        print("ourouler : aucune invitation en cours")
        return 0
    for invitation in invitations:
        echeance = invitation.expire_le.astimezone(UTC).strftime("%d/%m/%Y")
        lien = construire_lien(url_publique, invitation.jeton)
        print(f"{invitation.email} — {lien} — valable jusqu'au {echeance}")
    return 0


__all__ = [
    "construire_lien",
    "executer_inviter",
    "executer_invitations",
]
