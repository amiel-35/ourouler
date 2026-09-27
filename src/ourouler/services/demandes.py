"""Les demandes d'invitation : déposer depuis le site public, modérer depuis l'administration.

Symétrique de `services/comptes.py` : ce module reçoit tout déjà résolu
(le dépôt des demandes, éventuellement les paramètres du relais SMTP) et ne
lit lui-même ni fichier, ni variable d'environnement (le cœur ne lit ni
configuration ni environnement) — c'est `api/routes/demandes.py` et
`api/admin.py` qui rassemblent tout cela.

**`deposer_demande` ne consulte jamais la table des comptes.** C'est la
condition de la doctrine du formulaire public : la même réponse, dans le
même temps, que l'adresse ait déjà un compte ou non. Le seul moyen de ne
rien apprendre à qui dépose une demande est de ne jamais regarder.

**`accepter_demande` rejoue `services.comptes.inviter()` tel quel** — même
chemin que `ourouler inviter`, mêmes règles (une invitation en cours reprend
son jeton existant, unicité portée par la base). La demande n'est effacée
qu'**après** que l'invitation a été émise avec succès : un incident entre les
deux (relais SMTP en panne, par exemple) laisse la demande dans la file
plutôt que de la faire disparaître sans qu'une invitation soit vraiment
partie.
"""

from __future__ import annotations

from dataclasses import dataclass

from ourouler.api.comptes import DepotComptes
from ourouler.api.courriel import FabriqueSMTP, ParametresBrevo, envoyer_invitation, message_alerte_demande
from ourouler.api.demandes import DemandeInvitation, DepotDemandes, ErreurDemandeInvitation
from ourouler.services.comptes import LienEmis, inviter


@dataclass(frozen=True)
class DemandeDeposee:
    """Ce que `deposer_demande` rend : la demande, et si l'alerte au mainteneur est partie.

    `alerte_envoyee` ne dit **jamais** au demandeur si son adresse a un compte — seulement
    si l'alerte a pu partir, ce qui ne dépend que de la présence du relais SMTP.
    """

    demande: DemandeInvitation
    alerte_envoyee: bool

    def __repr__(self) -> str:
        return f"DemandeDeposee(demande={self.demande!r}, alerte_envoyee={self.alerte_envoyee})"


def deposer_demande(
    adresse: str,
    message: str | None,
    *,
    depot: DepotDemandes,
    destinataire_alerte: str | None,
    parametres_brevo: ParametresBrevo | None,
    fabrique_smtp: FabriqueSMTP | None = None,
) -> DemandeDeposee:
    """Enregistre la demande, puis tente l'alerte au mainteneur — sans jamais faire échouer
    l'enregistrement si l'alerte ne part pas.

    `destinataire_alerte` et `parametres_brevo` peuvent être `None` chacun de son côté
    (destinataire non configuré, relais absent ou incomplet) : dans les deux cas, la
    demande est quand même enregistrée, et `alerte_envoyee` vaut `False` — c'est à
    l'appelant (`api/routes/demandes.py`) de journaliser cette absence, jamais de la
    montrer au demandeur.
    """
    demande = depot.deposer(adresse, message)
    if destinataire_alerte is None or parametres_brevo is None:
        return DemandeDeposee(demande=demande, alerte_envoyee=False)
    courriel = message_alerte_demande(
        destinataire=destinataire_alerte,
        adresse_demandeur=demande.email,
        message_demandeur=demande.message,
        parametres=parametres_brevo,
    )
    envoyer_invitation(parametres_brevo, courriel, fabrique=fabrique_smtp)
    return DemandeDeposee(demande=demande, alerte_envoyee=True)


def demandes_en_attente(*, depot: DepotDemandes) -> list[DemandeInvitation]:
    """La file, telle que l'administration l'affiche.

    Purge d'abord les demandes de plus de 30 jours (`DepotDemandes.en_attente`,
    RGPD — minimisation) : elles n'apparaissent donc jamais dans la liste rendue.
    """
    return depot.en_attente()


def purger_demandes_perimees(*, depot: DepotDemandes) -> int:
    """Efface les demandes non traitées depuis plus de 30 jours — rend leur nombre.

    Appelée au démarrage (`ourouler admin`, ou l'administration intégrée à
    l'entrypoint) en plus de la purge automatique à l'ouverture de la file
    (`demandes_en_attente`) — une file jamais consultée entre deux
    démarrages ne doit pas non plus garder des adresses indéfiniment.
    """
    return depot.purger_perimees()


def refuser_demande(identifiant: str, *, depot: DepotDemandes) -> bool:
    """Efface la demande sans rien envoyer — vrai si elle existait encore.

    Idempotente (voir `DepotDemandes.effacer`) : refuser une demande déjà
    refusée ou déjà acceptée par un autre onglet d'administration ne lève
    rien, elle n'a simplement plus rien à faire.
    """
    return depot.effacer(identifiant)


def accepter_demande(
    identifiant: str,
    *,
    depot_demandes: DepotDemandes,
    depot_comptes: DepotComptes,
    url_publique: str,
    parametres_brevo: ParametresBrevo | None,
    invite_par: str = "",
    fabrique_smtp: FabriqueSMTP | None = None,
) -> LienEmis:
    """Accepte la demande : émet l'invitation (même chemin que `ourouler inviter`), puis
    efface la demande de la file.

    Lève `ErreurDemandeInvitation` si la demande n'existe plus (déjà traitée
    par un autre onglet, par exemple) — avant d'appeler `inviter`, pour ne
    jamais émettre une invitation sans qu'une demande l'ait justifiée.
    """
    demande = depot_demandes.par_id(identifiant)
    if demande is None:
        raise ErreurDemandeInvitation(f"demande {identifiant!r} introuvable — déjà traitée ?")
    lien = inviter(
        demande.email,
        depot=depot_comptes,
        url_publique=url_publique,
        sans_courriel=parametres_brevo is None,
        parametres_brevo=parametres_brevo,
        invite_par=invite_par,
        fabrique_smtp=fabrique_smtp,
    )
    depot_demandes.effacer(identifiant)
    return lien


__all__ = [
    "DemandeDeposee",
    "accepter_demande",
    "demandes_en_attente",
    "deposer_demande",
    "purger_demandes_perimees",
    "refuser_demande",
]
