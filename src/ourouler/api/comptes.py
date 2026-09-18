"""Les comptes, les invitations, et le lien vers le propriétaire pseudonyme.

Doctrine §10.2, et décision produit du mainteneur du 18/09/2026 :
**l'entrée se fait sur invitation, définitivement, y compris pour la version
publique.** Il n'y a pas de création de compte à la demande, donc pas de
formulaire d'inscription, pas de demande d'accès, pas de liste d'attente. Le
seul chemin vers un compte est un lien envoyé par le mainteneur — et son
propre compte passe par ce chemin-là, sans trappe d'amorçage.

## Pourquoi ce dépôt n'est pas dans `api/depots.py`

`api/depots.py` s'ouvre sur une phrase qu'un invariant fait respecter :
« chaque méthode publique de ce module prend un `Proprietaire` en premier
argument positionnel ». C'est la clause de propriétaire de la doctrine §10.2,
et elle est juste — pour des données qui **appartiennent** à quelqu'un.

Les opérations d'ici sont d'une autre nature : créer un compte et consommer
une invitation **précèdent** l'existence d'un propriétaire. Leur demander une
clause de propriétaire serait circulaire, exactement comme pour les fonctions
`_migrer` dispensées par l'invariant SQL. Deux mauvaises réponses étaient
possibles, et ce fichier existe pour n'en prendre aucune :

- les poser dans `api/depots.py` en espérant que la liste `CLASSES_DEPOT` de
  `tests/test_invariants.py` ne les nomme pas — c'est-à-dire échapper à
  l'invariant par le silence, ce qui est pire que de le modifier ;
- leur faire prendre un `Proprietaire` de complaisance pour satisfaire la
  forme, ce qui viderait la règle de son sens partout ailleurs.

Le choix retenu est donc : **un module séparé, une frontière nommée**. `api/`
contient désormais deux familles de dépôts, et la ligne entre elles est celle
de [[Q46]] — le compte porte l'identité et l'accès, le `Proprietaire` est la
clé pseudonyme sous laquelle vivent les données. Deux invariants ajoutés le
18/09/2026 gardent cette frontière plutôt que de la contourner : l'un exige
que toute classe `Depot*` de `api/depots.py` soit nommée dans `CLASSES_DEPOT`
(on ne peut plus y ajouter un dépôt en douce), l'autre exempte nommément les
seules tables d'identité de la clause SQL de propriétaire — et vérifie que
`comptes_proprietaires`, elle, n'en est **pas** exemptée.

## Ce que le code ne fait pas, et pourquoi

**Aucune unicité n'est vérifiée avant d'écrire.** Un `SELECT` suivi d'un
`INSERT` est un *check-then-act* : deux requêtes concurrentes le doublent, et
le doublon apparaît le jour où deux personnes cliquent en même temps, c'est-à-
dire jamais en test et toujours en production. Ici on insère, et on traduit la
violation de contrainte en phrase lisible. De même, une invitation se consomme
par un unique `UPDATE … WHERE … AND consomme_le IS NULL … RETURNING`, jamais
par un `SELECT` puis un `UPDATE`.

**Le jeton en clair ne sort pas d'ici sans qu'on le veuille.** Il est rendu
une fois, à la création, par `InvitationEmise` — dont le `__repr__` le masque
pour qu'un journal, un `print` de mise au point ou une trace d'exception ne le
recopie pas. Seul son condensé va en base.
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import psycopg
from psycopg import errors as erreurs_psycopg

from ourouler.api.proprietaire import Proprietaire
from ourouler.erreurs import ErreurUtilisateur

#: Combien de temps une invitation reste valable. Sept jours : assez pour
#: qu'un mail vu le week-end suivant serve encore, assez peu pour qu'un lien
#: oublié dans une boîte ne soit pas une porte ouverte pour toujours. La durée
#: est un argument de `creer_invitation` — cette constante n'est que le défaut.
DUREE_INVITATION = timedelta(days=7)

#: Longueur, en octets d'entropie, du jeton rendu à l'appelant. 32 octets
#: rendent 43 caractères en base64 url-safe : hors de portée d'une recherche
#: exhaustive, et ça tient dans une URL sans la rendre absurde.
OCTETS_JETON = 32


class ErreurCompte(ErreurUtilisateur):
    """Ce que le mainteneur doit lire quand une invitation ne peut pas aboutir."""


class ErreurCompteExistant(ErreurCompte):
    """L'adresse est déjà titulaire d'un compte.

    « Pas d'interface ne veut pas dire pas de contrôle » : inviter deux fois
    la même personne répond « il a déjà un compte », jamais un doublon.
    """


class ErreurInvitationRefusee(ErreurCompte):
    """Le jeton est inconnu, expiré, ou déjà consommé. Le message dit lequel, jamais le jeton."""


@dataclass(frozen=True)
class Compte:
    """L'identité et l'accès : un identifiant opaque, une adresse, une date."""

    identifiant: str
    email: str
    cree_le: datetime


@dataclass(frozen=True)
class Invitation:
    """Une invitation telle qu'elle vit en base — c'est-à-dire sans son jeton."""

    condense: str
    compte: str
    cree_le: datetime
    expire_le: datetime
    consomme_le: datetime | None


@dataclass(frozen=True)
class InvitationEmise:
    """Ce que `creer_invitation` rend : l'invitation, et le jeton s'il est neuf.

    `jeton` vaut `None` quand une invitation était **déjà en cours** : son
    condensé seul est en base, et un condensé ne se remonte pas. L'appelant
    apprend donc qu'il y a déjà un lien valide et jusqu'à quand, mais il ne
    peut pas le renvoyer — c'est le prix, assumé, de ne jamais stocker un
    jeton en clair. Voir la note dans `creer_invitation`.
    """

    invitation: Invitation
    jeton: str | None
    deja_en_cours: bool

    def __repr__(self) -> str:
        """Masque le jeton : un `repr` finit dans un journal ou une trace."""
        etat = "présent" if self.jeton else "absent"
        return (
            f"InvitationEmise(compte={self.invitation.compte!r}, "
            f"expire_le={self.invitation.expire_le.isoformat()}, "
            f"jeton=<{etat}>, deja_en_cours={self.deja_en_cours})"
        )


@dataclass(frozen=True)
class Acces:
    """Ce qu'une invitation consommée ouvre : un compte, et son propriétaire.

    Les deux voyagent ensemble et restent distincts : c'est toute la décision
    de [[Q46]], et les fondre en un seul objet serait la défaire au premier
    appel.
    """

    compte: Compte
    proprietaire: Proprietaire


def normaliser_email(brut: str) -> str:
    """La forme canonique d'une adresse : espaces coupés, minuscules.

    **Avant l'insertion, et non à la lecture.** Sans ça, « Amiel@X.com » et
    « amiel@x.com » sont deux lignes que plus aucune contrainte ne rapproche.
    La base répète l'exigence (`comptes_email_normalise`) pour qu'un appelant
    distrait se fasse refuser au lieu d'être cru.
    """
    normalise = brut.strip().lower()
    if not normalise or "@" not in normalise[1:-1]:
        raise ErreurCompte(f"adresse e-mail invalide : {brut!r}")
    return normalise


def nouvel_identifiant() -> str:
    """Un identifiant opaque à nous, qui respecte `FORME_IDENTIFIANT`.

    Hexadécimal sur 32 caractères : ni l'adresse (qui change), ni un entier
    séquentiel (qui dit combien il y a d'utilisateurs et laisse essayer le
    suivant). Il finit en segment de chemin, d'où la forme fermée.
    """
    return secrets.token_hex(16)


def condenser(jeton: str) -> str:
    """Le SHA-256 hexadécimal d'un jeton. La seule forme qui a le droit d'être écrite."""
    return hashlib.sha256(jeton.encode("utf-8")).hexdigest()


class DepotComptes:
    """Les comptes et leurs invitations, dans PostgreSQL.

    **Reçoit une connexion, n'en cherche pas.** Doctrine §10.2 et règle
    absolue 2 : l'URL se lit dans `api/exploitation.py`, et seulement là. La
    connexion est attendue en autocommit (voir `base_de_donnees.ouvrir`) :
    chaque opération déclare sa transaction, et un appelant qui a besoin d'une
    portée plus large ouvre la sienne autour.
    """

    def __init__(self, connexion: psycopg.Connection) -> None:
        self.cx = connexion

    # -- les comptes ---------------------------------------------------------

    def creer_compte(self, email: str) -> Compte:
        """Crée un compte pour cette adresse, et son propriétaire pseudonyme.

        Les deux lignes — le compte et sa correspondance — sont écrites dans
        la même transaction : un compte sans propriétaire serait un compte à
        qui l'on ne peut rien rattacher, et il n'existe donc à aucun instant.

        Lève `ErreurCompteExistant` si l'adresse est déjà titulaire. Ce refus
        vient de l'index unique de la base, pas d'une lecture préalable :
        c'est ce qui le rend vrai quand deux invitations partent en même
        temps.
        """
        normalise = normaliser_email(email)
        identifiant = nouvel_identifiant()
        proprietaire = nouvel_identifiant()
        try:
            with self.cx.transaction():
                ligne = self.cx.execute(
                    "INSERT INTO comptes (id, email) VALUES (%s, %s) RETURNING id, email, cree_le",
                    (identifiant, normalise),
                ).fetchone()
                self.cx.execute(
                    "INSERT INTO comptes_proprietaires (compte, proprietaire) VALUES (%s, %s)",
                    (identifiant, proprietaire),
                )
        except erreurs_psycopg.UniqueViolation as e:
            if (e.diag.constraint_name or "") != "comptes_email_unique":
                # Collision sur un identifiant que nous tirons au hasard sur
                # 128 bits : ce n'est pas une erreur d'utilisateur, c'est un
                # incident, et il doit se voir comme tel.
                raise
            raise self._deja_titulaire(normalise) from e
        return Compte(identifiant=ligne[0], email=ligne[1], cree_le=ligne[2])

    def proprietaire_du_compte(self, identifiant_compte: str) -> Proprietaire:
        """La clé pseudonyme sous laquelle vivent les données de ce compte.

        Lève `ErreurCompte` si la correspondance n'existe pas : c'est alors un
        compte orphelin, donc un bug de ce module, et le dire vaut mieux que
        rendre `None` à quelqu'un qui n'en fera rien de bon.
        """
        ligne = self.cx.execute(
            "SELECT proprietaire FROM comptes_proprietaires WHERE compte = %s",
            (identifiant_compte,),
        ).fetchone()
        if ligne is None:
            raise ErreurCompte(
                f"aucun propriétaire rattaché au compte {identifiant_compte!r} — "
                "la correspondance de [[Q46]] manque, ce qui ne devrait pas arriver"
            )
        return Proprietaire(ligne[0])

    # -- les invitations -----------------------------------------------------

    def creer_invitation(
        self,
        identifiant_compte: str,
        *,
        duree: timedelta = DUREE_INVITATION,
        maintenant: datetime | None = None,
    ) -> InvitationEmise:
        """Un lien d'invitation pour ce compte — ou celui qui est déjà en cours.

        **Choix du mainteneur** : quand une invitation valide n'a pas encore
        été consommée, on n'en fabrique pas une seconde. « Le cas réel c'est
        qu'il ne l'a pas vue. » Le résultat porte alors `deja_en_cours=True`
        et `jeton=None`, et c'est à l'appelant de dire ce qu'il en fait.

        **Ce que cela laisse ouvert, et qui demande un arbitrage** : comme le
        jeton n'est pas stocké en clair, on ne peut pas *renvoyer le même
        lien*. L'appelant peut dire « une invitation est déjà en cours,
        envoyée le X, valable jusqu'au Y », pas la relancer telle quelle. Si
        le besoin est vraiment de renvoyer le mail, il faudra un geste
        explicite qui **remplace** l'invitation en cours (et invalide donc
        l'ancien lien) : ce n'est pas la même promesse, et ce n'est pas au
        code de la choisir.

        Une invitation **expirée** ne bloque pas : elle est retirée et
        remplacée dans la même transaction.
        """
        maintenant = _instant(maintenant)
        jeton = secrets.token_urlsafe(OCTETS_JETON)
        with self.cx.transaction():
            # La place est occupée par l'index partiel `invitations_en_cours_unique`
            # tant que la ligne n'est pas consommée, expirée ou non. On libère
            # ce qui a expiré, puis on tente ; si quelqu'un d'autre a gagné la
            # course entre les deux, `DO NOTHING` nous le dit sans rien casser.
            self.cx.execute(
                "DELETE FROM invitations "
                "WHERE compte = %s AND consomme_le IS NULL AND expire_le <= %s",
                (identifiant_compte, maintenant),
            )
            ligne = self.cx.execute(
                "INSERT INTO invitations (condense, compte, cree_le, expire_le) "
                "VALUES (%s, %s, %s, %s) "
                "ON CONFLICT (compte) WHERE consomme_le IS NULL DO NOTHING "
                "RETURNING condense, compte, cree_le, expire_le, consomme_le",
                (condenser(jeton), identifiant_compte, maintenant, maintenant + duree),
            ).fetchone()
            if ligne is not None:
                return InvitationEmise(_invitation(ligne), jeton=jeton, deja_en_cours=False)
            en_cours = self.cx.execute(
                "SELECT condense, compte, cree_le, expire_le, consomme_le FROM invitations "
                "WHERE compte = %s AND consomme_le IS NULL",
                (identifiant_compte,),
            ).fetchone()
        if en_cours is None:  # pragma: no cover - la ligne a disparu entre-temps
            raise ErreurCompte(
                "impossible de poser une invitation pour le compte "
                f"{identifiant_compte!r} — réessayer"
            )
        return InvitationEmise(_invitation(en_cours), jeton=None, deja_en_cours=True)

    def consommer(self, jeton: str, *, maintenant: datetime | None = None) -> Acces:
        """Consomme un jeton, une seule fois, et rend le compte et son propriétaire.

        **Une seule instruction décide**, et c'est ce qui rend la double
        consommation impossible : `UPDATE … WHERE condense = … AND consomme_le
        IS NULL AND expire_le > … RETURNING`. Deux requêtes concurrentes se
        sérialisent sur la ligne ; la seconde ne voit plus `consomme_le IS
        NULL` et ne met rien à jour. Un `SELECT` puis un `UPDATE` les aurait
        laissées passer toutes les deux.

        Le jeton n'apparaît dans aucun message d'erreur : ce qui est refusé
        est nommé (inconnu, expiré, déjà utilisé), pas montré.
        """
        maintenant = _instant(maintenant)
        condense = condenser(jeton)
        with self.cx.transaction():
            ligne = self.cx.execute(
                "UPDATE invitations SET consomme_le = %(quand)s "
                "WHERE condense = %(condense)s "
                "  AND consomme_le IS NULL "
                "  AND expire_le > %(quand)s "
                "RETURNING compte",
                {"quand": maintenant, "condense": condense},
            ).fetchone()
            if ligne is None:
                raise self._invitation_refusee(condense)
            compte = self.cx.execute(
                "SELECT id, email, cree_le FROM comptes WHERE id = %s", (ligne[0],)
            ).fetchone()
            proprietaire = self.proprietaire_du_compte(ligne[0])
        if compte is None:  # pragma: no cover - la clé étrangère l'interdit
            raise ErreurCompte("invitation rattachée à un compte disparu")
        return Acces(
            compte=Compte(identifiant=compte[0], email=compte[1], cree_le=compte[2]),
            proprietaire=proprietaire,
        )

    # -- les messages --------------------------------------------------------

    def _deja_titulaire(self, email_normalise: str) -> ErreurCompteExistant:
        """« Non, il a déjà un compte » — et depuis quand.

        Cette lecture arrive **après** le refus de la base : elle sert à
        écrire la phrase, pas à décider. C'est la différence entre expliquer
        un refus et le prononcer.
        """
        ligne = self.cx.execute(
            "SELECT cree_le FROM comptes WHERE lower(email) = %s", (email_normalise,)
        ).fetchone()
        if ligne is None:  # pragma: no cover - le gagnant a annulé entre-temps
            return ErreurCompteExistant(
                f"{email_normalise} : un compte vient d'être créé pour cette adresse"
            )
        return ErreurCompteExistant(
            f"{email_normalise} a déjà un compte, ouvert le "
            f"{ligne[0].astimezone(UTC).strftime('%d/%m/%Y')} — rien n'a été créé"
        )

    def _invitation_refusee(self, condense: str) -> ErreurInvitationRefusee:
        """Dire *pourquoi* le jeton est refusé, sans jamais répéter le jeton."""
        ligne = self.cx.execute(
            "SELECT expire_le, consomme_le FROM invitations WHERE condense = %s", (condense,)
        ).fetchone()
        if ligne is None:
            return ErreurInvitationRefusee(
                "ce lien d'invitation n'existe pas — vérifier qu'il a été copié en entier"
            )
        expire_le, consomme_le = ligne
        if consomme_le is not None:
            return ErreurInvitationRefusee(
                "ce lien d'invitation a déjà servi le "
                f"{consomme_le.astimezone(UTC).strftime('%d/%m/%Y')} — un lien ne sert qu'une fois"
            )
        return ErreurInvitationRefusee(
            "ce lien d'invitation a expiré le "
            f"{expire_le.astimezone(UTC).strftime('%d/%m/%Y')} — il en faut un nouveau"
        )


def _instant(maintenant: datetime | None) -> datetime:
    """L'heure courante en UTC, ou celle qu'on nous donne.

    Injectable exprès : une invitation expirée se teste en avançant l'horloge
    d'un argument, pas en attendant sept jours ni en trafiquant la base.
    """
    if maintenant is None:
        return datetime.now(UTC)
    if maintenant.tzinfo is None:
        raise ErreurCompte("un instant sans fuseau ne désigne rien — passer un datetime en UTC")
    return maintenant


def _invitation(ligne: tuple) -> Invitation:
    return Invitation(
        condense=ligne[0],
        compte=ligne[1],
        cree_le=ligne[2],
        expire_le=ligne[3],
        consomme_le=ligne[4],
    )


__all__ = [
    "DUREE_INVITATION",
    "OCTETS_JETON",
    "Acces",
    "Compte",
    "DepotComptes",
    "ErreurCompte",
    "ErreurCompteExistant",
    "ErreurInvitationRefusee",
    "Invitation",
    "InvitationEmise",
    "condenser",
    "normaliser_email",
    "nouvel_identifiant",
]