"""Les demandes d'invitation déposées depuis le site public — et leur file d'attente.

Doctrine §10.2 (révisée le 26/09/2026) : le formulaire public de demande
d'invitation est autorisé, mais **une demande n'ouvre jamais de compte
seule** — elle attend un geste explicite du mainteneur dans l'administration
(`api/admin.py`), qui rejoue `services.comptes.inviter()` tel quel.

Deux objets bien distincts, comme pour les comptes (Q46) :

- `DepotDemandes` — la file en base (`migrations/0003_demandes_invitation.sql`) :
  déposer, lister, effacer une demande. Ce dépôt ne sait rien d'un compte ni
  d'une invitation, exactement comme `api/comptes.py` ne sait rien d'un
  `Proprietaire`.
- `LimiteAnonyme` — le débit du formulaire **public**, en mémoire du
  processus, sur le modèle d'`api/quotas.py` (compteur borné, réglable,
  purgé chaque jour). Une IP n'est pas un compte : lui appliquer `Quotas`,
  qui parle de `Proprietaire`, mélangerait deux notions distinctes. D'où une
  petite classe séparée, avec la même forme.

## Pourquoi aucune vérification préalable, ici comme pour les comptes

Ce module **ne consulte jamais la table `comptes`**. Le formulaire public
répond la même chose, dans le même temps, que l'adresse ait déjà un compte,
une invitation en cours, ou rien du tout — la seule façon de ne rien
apprendre à qui dépose une demande est de ne jamais regarder.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

import psycopg

from ourouler.api.comptes import normaliser_email, nouvel_identifiant
from ourouler.noyau.erreurs import ErreurUtilisateur

#: Longueur maximale du message facultatif (« un mot ») — au-delà, ce n'est
#: plus un mot mais un texte, et ce formulaire n'en a pas besoin. Même borne
#: que la contrainte SQL (`demandes_invitation_message_borne`) : la relire ici
#: refuse une demande trop longue *avant* d'aller jusqu'à la base.
LONGUEUR_MAX_MESSAGE = 500


@dataclass(frozen=True)
class DemandeInvitation:
    """Une demande telle qu'elle vit en base : identifiant, adresse, message, date.

    Le `repr` masque l'adresse et le message — même règle que `Compte` et
    consorts (`api/comptes.py`) : un `repr` finit dans un journal.
    """

    id: str
    email: str
    message: str | None
    cree_le: datetime

    def __repr__(self) -> str:
        return (
            f"DemandeInvitation(id={self.id!r}, email=<masqué>, message=<masqué>, "
            f"cree_le={self.cree_le.isoformat()})"
        )


class DepotDemandes:
    """Les demandes d'invitation en attente, dans PostgreSQL — même base que les comptes.

    **Reçoit une connexion, n'en cherche pas** — même règle qu'`api/comptes.DepotComptes`.
    """

    def __init__(self, connexion: psycopg.Connection) -> None:
        self.cx = connexion

    def deposer(self, email: str, message: str | None) -> DemandeInvitation:
        """Enregistre une demande. Ne vérifie et ne lit jamais rien de la table `comptes`.

        `message`, une fois tronqué en amont par l'appelant (le formulaire public
        borne déjà la longueur, voir `api/routes/demandes.py`), est gardé tel quel — texte
        brut, jamais interprété.
        """
        normalise = normaliser_email(email)
        propre = (message or "").strip() or None
        if propre is not None and len(propre) > LONGUEUR_MAX_MESSAGE:
            propre = propre[:LONGUEUR_MAX_MESSAGE]
        identifiant = nouvel_identifiant()
        with self.cx.transaction():
            ligne = self.cx.execute(
                "INSERT INTO demandes_invitation (id, email, message) VALUES (%s, %s, %s) "
                "RETURNING id, email, message, cree_le",
                (identifiant, normalise, propre),
            ).fetchone()
        assert ligne is not None  # un INSERT sans ON CONFLICT rend toujours sa ligne
        return _demande(ligne)

    def en_attente(self) -> list[DemandeInvitation]:
        """La file, des plus anciennes aux plus récentes — ce que l'administration affiche."""
        lignes = self.cx.execute(
            "SELECT id, email, message, cree_le FROM demandes_invitation ORDER BY cree_le"
        ).fetchall()
        return [_demande(ligne) for ligne in lignes]

    def par_id(self, identifiant: str) -> DemandeInvitation | None:
        """Une demande précise, ou `None` — pour l'écran « accepter/refuser cette demande »."""
        ligne = self.cx.execute(
            "SELECT id, email, message, cree_le FROM demandes_invitation WHERE id = %s",
            (identifiant,),
        ).fetchone()
        return _demande(ligne) if ligne is not None else None

    def effacer(self, identifiant: str) -> bool:
        """Efface une demande — vrai si une ligne a été effacée.

        Idempotente, comme `DepotComptes.supprimer_compte_du_proprietaire` : appeler
        « refuser » ou « accepter » deux fois sur la même demande (double clic, deux
        onglets d'administration ouverts) ne doit pas lever d'erreur, la seconde n'a
        simplement plus rien à faire.
        """
        with self.cx.transaction():
            ligne = self.cx.execute(
                "DELETE FROM demandes_invitation WHERE id = %s RETURNING id", (identifiant,)
            ).fetchone()
        return ligne is not None


def _demande(ligne: tuple) -> DemandeInvitation:
    return DemandeInvitation(id=ligne[0], email=ligne[1], message=ligne[2], cree_le=ligne[3])


class ErreurDemandeInvitation(ErreurUtilisateur):
    """Une demande mal formée — adresse invalide, message trop long après coup, etc."""


# --- le débit du formulaire public : anti-abus minimal, sans service externe ------
#
# Deux compteurs, comme `api/quotas.py` distingue générations et consultations
# météo pour deux coûts différents : ici, deux *risques* différents. Un
# compteur par adresse IP borne ce qu'*une* machine peut faire ; un compteur
# global borne ce que le formulaire peut coûter au relais SMTP et au
# mainteneur (une alerte par demande) même si l'abus vient de nombreuses
# adresses IP différentes (un botnet, par exemple).


def _minuit_suivant(maintenant: datetime) -> datetime:
    lendemain = maintenant.date() + timedelta(days=1)
    return datetime(lendemain.year, lendemain.month, lendemain.day, tzinfo=UTC)


@dataclass
class LimiteAnonyme:
    """Un compteur journalier borné, par clé arbitraire (une adresse IP, ou une
    constante pour la limite globale) — le même patron qu'`api.quotas.Quotas`,
    en plus simple : pas de remboursement (une demande déposée ne coûte rien à
    annuler si la suite échoue, il n'y a pas de suite coûteuse), et une clé
    quelconque au lieu d'un `Proprietaire` — une adresse IP n'est le compte de
    personne.

    **En mémoire du processus, comme `Quotas`** : un compteur d'abus n'a pas
    besoin de survivre à un redémarrage. `horloge` est injectable pour les tests.
    """

    plafond: int
    horloge: Callable[[], datetime] = field(default=lambda: datetime.now(UTC))
    _verrou: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)
    _compteurs: dict[tuple[str, date], int] = field(default_factory=dict, repr=False, compare=False)

    def autorise(self, cle: str) -> bool:
        """Décompte un crédit pour `cle` et rend vrai — ou rend faux sans rien décompter.

        Purge, au passage, les compteurs d'un jour révolu — même choix que
        `Quotas.consommer` : la remise à zéro du lendemain est gratuite, et la
        taille du dictionnaire reste bornée par le nombre de clés actives
        aujourd'hui.
        """
        maintenant = self.horloge()
        aujourdhui = maintenant.date()
        cle_du_jour = (cle, aujourdhui)
        with self._verrou:
            for perimee in [c for c in self._compteurs if c[1] != aujourdhui]:
                del self._compteurs[perimee]
            deja = self._compteurs.get(cle_du_jour, 0)
            if deja >= self.plafond:
                return False
            self._compteurs[cle_du_jour] = deja + 1
            return True


#: La clé du compteur global (toutes adresses IP confondues) dans une
#: `LimiteAnonyme` — un mot qu'aucune adresse IP ne peut jamais valoir.
CLE_GLOBALE = "*"

#: Le plafond par défaut, par adresse IP et par jour. Une personne qui
#: dépose deux ou trois demandes en se ravisant sur le message reste sous ce
#: plafond ; au-delà, ce n'est plus une hésitation.
PAR_IP_PAR_JOUR_DEFAUT = 5

#: Le plafond par défaut, toutes adresses IP confondues et par jour — ce que
#: le formulaire peut coûter en alertes courriel au mainteneur même réparti
#: sur de nombreuses adresses IP différentes. Assez large pour ne jamais
#: gêner un usage réel (le service accueille quelques proches, pas des
#: centaines de demandes par jour), assez borné pour qu'un abus distribué ne
#: vide pas la boîte du mainteneur.
GLOBAL_PAR_JOUR_DEFAUT = 100


__all__ = [
    "CLE_GLOBALE",
    "GLOBAL_PAR_JOUR_DEFAUT",
    "LONGUEUR_MAX_MESSAGE",
    "PAR_IP_PAR_JOUR_DEFAUT",
    "DemandeInvitation",
    "DepotDemandes",
    "ErreurDemandeInvitation",
    "LimiteAnonyme",
]
