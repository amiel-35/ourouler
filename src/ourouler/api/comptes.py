"""Les comptes, les invitations, et le lien vers le propriétaire pseudonyme.

Doctrine §10.2, et décision produit du mainteneur du 18/09/2026 : **l'entrée
se fait sur invitation, définitivement, y compris pour la version publique.**
Il n'y a pas de création de compte à la demande, donc pas de formulaire
d'inscription, pas de demande d'accès, pas de liste d'attente. Le seul chemin
vers un compte est un lien envoyé par le mainteneur — et son propre compte
passe par ce chemin-là, sans trappe d'amorçage.

## Révision du même jour : « c'est pas une banque »

Une première version de ce module condensait le jeton d'invitation (SHA-256)
et le faisait vivre sept jours. Le mainteneur a demandé un retour en arrière
avant que rien n'en dépende : « je trouve que tu compliques les choses, on va
revenir au basique. » Ce qui change, et pourquoi c'est assumé plutôt que subi :

- **Le jeton d'invitation est en clair.** Le mainteneur veut pouvoir le
  relire et le renvoyer par le canal qu'il veut — un condensé l'en empêchait.
  Le risque est borné par la durée, ramenée de sept à **trois jours**
  (`DUREE_INVITATION`), et par ce qu'un lien ouvre : un compte vide, rien de
  plus. Il ne doit en revanche **jamais partir dans un journal** : c'est ce
  que masquent les `__repr__` d'`Invitation` et d'`InvitationEmise`.
- **Le mot de passe, lui, reste haché, toujours.** Ce n'est pas le même
  objet que le jeton : les gens réutilisent leurs mots de passe, et une fuite
  de cette base ne doit pas donner accès à autre chose qu'ourouler. Scrypt
  (`hashlib`, bibliothèque standard), un sel par compte, une comparaison en
  temps constant — voir `hacher_mot_de_passe` et `verifier_mot_de_passe`.
- **Le secret est rangé derrière une petite indirection** (`methode_authentification`,
  `secret`) parce que le mot de passe ne restera pas le seul moyen — une
  passkey, plus tard. Cette abstraction-là s'arrête à deux colonnes : il n'y
  a pas de passkey aujourd'hui, et ce module n'en écrit pas l'ombre.

## Le cycle de vie, décidé par le mainteneur

1. **`inviter(email)`** crée un compte **inactif** — aucun moyen de s'y
   authentifier n'est posé — et une invitation qui le vise. Le jeton est
   rendu en clair.
2. La personne ouvre le lien : rien n'est consommé ici, ce module n'expose
   même pas de méthode pour ça — regarder l'état d'un jeton sans le
   consommer est un besoin du lot suivant (la route), pas de celui-ci.
3. **`activer(jeton, mot_de_passe)`** pose le secret, active le compte et
   consomme l'invitation — **les trois dans une seule transaction** : un
   compte actif sans secret, ou un secret posé sur une invitation déjà
   consommée, sont des états qui ne doivent jamais exister.
4. Le reste de l'inscription (nom, départ, vélo, FTP) se fait sous session
   normale, plus jamais avec le jeton. Un profil incomplet est un état
   normal ; ça n'est pas l'affaire de ce module.

**Réinviter une adresse** passe par le même `inviter` : un compte déjà actif
est refusé (« il a déjà un compte ») ; un compte inactif dont l'invitation
court encore **rend le jeton existant**, ce que le jeton en clair rend enfin
possible ; une invitation périmée est remplacée par une neuve. Il n'y a donc
qu'une seule commande, qui lit l'état et agit en conséquence — pas de geste
séparé « relancer » ([[Q59]], close le 18/09/2026).

## Pourquoi ce dépôt n'est pas dans `api/depots.py`

`api/depots.py` s'ouvre sur une phrase qu'un invariant fait respecter :
« chaque méthode publique de ce module prend un `Proprietaire` en premier
argument positionnel ». C'est la clause de propriétaire de la doctrine §10.2,
et elle est juste — pour des données qui **appartiennent** à quelqu'un.

Les opérations d'ici sont d'une autre nature : inviter et activer un compte
**précèdent** l'existence d'un propriétaire. Leur demander une clause de
propriétaire serait circulaire, exactement comme pour les fonctions
`_migrer` dispensées par l'invariant SQL. Le choix retenu est donc : **un
module séparé, une frontière nommée**. C'est la ligne de [[Q46]] — le compte
porte l'identité et l'accès, le `Proprietaire` est la clé pseudonyme sous
laquelle vivent les données.

## Ce que le code ne fait pas, et pourquoi

**Aucune unicité n'est vérifiée avant d'écrire.** Un `SELECT` suivi d'un
`INSERT` est un *check-then-act* : deux requêtes concurrentes le doublent, et
le doublon apparaît le jour où deux personnes cliquent en même temps, c'est-à-
dire jamais en test et toujours en production. Ici on insère avec
`ON CONFLICT … DO NOTHING`, jamais un `SELECT` puis un `INSERT`. De même, une
invitation se consomme par un unique `UPDATE … WHERE … AND consomme_le IS
NULL … RETURNING`.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import psycopg

from ourouler.api.proprietaire import Proprietaire
from ourouler.erreurs import ErreurUtilisateur

#: Combien de temps une invitation reste valable. **Trois jours** (et non
#: sept) : c'est la contrepartie du jeton en clair — décision du mainteneur,
#: voir la note de module. L'argument `duree` de `inviter` peut la changer ;
#: cette constante n'en est que le défaut.
DUREE_INVITATION = timedelta(days=3)

#: Longueur, en octets d'entropie, du jeton rendu à l'appelant. 32 octets
#: rendent 43 caractères en base64 url-safe : hors de portée d'une recherche
#: exhaustive, et ça tient dans une URL sans la rendre absurde.
OCTETS_JETON = 32

#: La seule méthode d'authentification qui existe aujourd'hui. Nommée en
#: constante plutôt qu'écrite en dur, pour qu'une passkey future se pose à
#: côté sans qu'on cherche la chaîne dans tout le module.
METHODE_MOT_DE_PASSE = "mot_de_passe"

#: Paramètres de `hashlib.scrypt`, rangés en constantes nommées plutôt qu'en
#: dur dans l'appel. Ce sont les valeurs de l'exemple de la documentation de
#: la bibliothèque standard — un coût mémoire dominant (`n`), qui rend une
#: attaque GPU ou ASIC chère. Ce projet n'est « pas une banque » (le
#: mainteneur) : ces valeurs, pas les plus hautes recommandées pour un
#: service bancaire, restent largement au-dessus de ce qu'un mot de passe de
#: cycliste entre amis mérite.
SCRYPT_N = 2**14
SCRYPT_R = 8
SCRYPT_P = 1
SCRYPT_TAILLE_CLE = 32

#: Taille du sel, propre à chaque compte, tiré à chaque hachage.
SEL_OCTETS = 16


class ErreurCompte(ErreurUtilisateur):
    """Ce que le mainteneur doit lire quand une invitation ou une activation échoue."""


class ErreurCompteExistant(ErreurCompte):
    """L'adresse est déjà titulaire d'un compte **actif**.

    « Pas d'interface ne veut pas dire pas de contrôle » : inviter un compte
    déjà actif répond « il a déjà un compte », jamais un doublon. Un compte
    **inactif** ne lève pas cette erreur : `inviter` lui rend son invitation
    en cours, ou lui en pose une neuve si la sienne a expiré.

    **La limite, écrite avant qu'elle morde.** Aujourd'hui, la seule façon
    d'atteindre cette erreur est que **le mainteneur** invite quelqu'un
    depuis sa propre ligne de commande. Le jour où ce chemin devient une
    **réponse HTTP** ouverte à d'autres que lui, cette erreur devient un
    oracle — « est-ce que cette adresse a un compte chez vous ? », posée par
    n'importe qui. Ce jour-là, la réponse doit devenir indistinguable du
    succès côté appelant, et le détail rester dans le journal du serveur. Ce
    n'est pas un changement à faire maintenant — c'en est un à ne pas
    découvrir après coup.
    """


class ErreurInvitationRefusee(ErreurCompte):
    """Le jeton est inconnu, expiré, ou déjà consommé. Le message dit lequel, jamais le jeton."""


@dataclass(frozen=True)
class Compte:
    """L'identité et l'accès : un identifiant opaque, une adresse, l'état, une date.

    Le `repr` **masque l'adresse** : un `repr` finit dans un journal, dans un
    `print` de mise au point, dans la sortie d'un échec de test — et une
    relecture l'y a vu apparaître en clair. L'identifiant, lui, reste
    visible : il est opaque, il ne désigne personne hors de la base.
    """

    identifiant: str
    email: str
    actif: bool
    cree_le: datetime

    def __repr__(self) -> str:
        """Masque l'adresse : un `repr` finit dans un journal ou une trace."""
        return (
            f"Compte(identifiant={self.identifiant!r}, email=<masqué>, "
            f"actif={self.actif}, cree_le={self.cree_le.isoformat()})"
        )


@dataclass(frozen=True)
class Invitation:
    """Une invitation telle qu'elle vit en base, jeton compris.

    Le jeton est en clair en base — décision du mainteneur, voir la note de
    module — mais un `repr` finit dans un journal aussi facilement qu'une
    ligne SQL : il reste masqué ici comme partout ailleurs dans ce module.
    """

    jeton: str
    compte: str
    cree_le: datetime
    expire_le: datetime
    consomme_le: datetime | None

    def __repr__(self) -> str:
        """Masque le jeton : un `repr` finit dans un journal ou une trace."""
        consomme = self.consomme_le.isoformat() if self.consomme_le else None
        return (
            f"Invitation(jeton=<masqué>, compte={self.compte!r}, "
            f"cree_le={self.cree_le.isoformat()}, expire_le={self.expire_le.isoformat()}, "
            f"consomme_le={consomme})"
        )


@dataclass(frozen=True)
class InvitationEmise:
    """Ce que `inviter` rend : l'invitation, son jeton en clair, et si elle est neuve.

    `deja_en_cours` dit si le jeton vient d'être créé (`False`) ou s'il
    s'agit d'une invitation déjà en cours qu'on relance (`True`) — dans les
    deux cas `jeton` porte de quoi ouvrir le lien, ce que le condensé de la
    version précédente interdisait.
    """

    invitation: Invitation
    jeton: str
    deja_en_cours: bool

    def __repr__(self) -> str:
        """Masque le jeton : un `repr` finit dans un journal ou une trace."""
        return (
            f"InvitationEmise(compte={self.invitation.compte!r}, "
            f"expire_le={self.invitation.expire_le.isoformat()}, "
            f"jeton=<masqué>, deja_en_cours={self.deja_en_cours})"
        )


@dataclass(frozen=True)
class Acces:
    """Ce qu'une activation ouvre : un compte, et son propriétaire.

    Les deux voyagent ensemble et restent distincts : c'est toute la décision
    de [[Q46]], et les fondre en un seul objet serait la défaire au premier
    appel.

    Le `repr` reste celui de la dataclass : il n'a pas de champ sensible à
    lui, et l'adresse qu'il montrerait est celle de son `Compte`, dont le
    `repr` la masque déjà.
    """

    compte: Compte
    proprietaire: Proprietaire


def normaliser_email(brut: str) -> str:
    """La forme canonique d'une adresse : espaces de bord coupés, minuscules.

    **Avant l'insertion, et non à la lecture.** Sans ça, « Cycliste@Exemple.INVALID »
    et « cycliste@exemple.invalid » sont deux lignes que plus aucune contrainte
    ne rapproche. La base répète l'exigence (`comptes_email_normalise`) pour
    qu'un appelant distrait se fasse refuser au lieu d'être cru.

    ## Pourquoi les caractères de contrôle et les espaces internes sont refusés

    « a\\n@exemple.invalid » passe `btrim` (qui ne coupe que l'espace ASCII)
    et donc la contrainte `CHECK (email = lower(btrim(email)))`. Or cette
    chaîne finira dans un envoi de courriel : **une adresse porteuse d'un
    saut de ligne est un vecteur d'injection d'en-tête**. C'est ici que ça se
    règle, une fois. Le refus couvre tout caractère de contrôle et tout blanc
    interne, pas seulement `\\n` : `\\r`, la tabulation et l'espace simple
    séparent ou poursuivent une ligne d'en-tête aussi bien l'un que l'autre.

    ## Ce que cette fonction n'est pas

    **Ce n'est pas un validateur d'adresse.** Elle vérifie une forme minimale
    — un arobase qui n'est ni au début ni à la fin — et rien de plus : une
    adresse n'est réellement valide que si un courriel y arrive, ce que seul
    l'envoi dira.

    ## Le `+` : deux comptes, et c'est délibéré

    « cycliste+velo@exemple.invalid » et « cycliste@exemple.invalid » font
    **deux comptes distincts**. Le sous-adressage par `+` est une convention
    de *certains* fournisseurs, pas une règle du courriel : replier l'une sur
    l'autre présumerait la politique du fournisseur du destinataire, et le
    jour où l'on se trompe, on donne à quelqu'un le compte de quelqu'un
    d'autre.
    """
    normalise = brut.strip().lower()
    interdit = next((c for c in normalise if c.isspace() or c < " " or c == "\x7f"), None)
    if interdit is not None:
        raise ErreurCompte(
            f"adresse e-mail invalide : {brut!r} contient {interdit!r}, "
            "un caractère de contrôle ou une espace — une adresse n'en porte pas"
        )
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


def hacher_mot_de_passe(mot_de_passe: str) -> str:
    """Hache `mot_de_passe` avec scrypt et un sel propre à cet appel.

    Rend `"<sel hexadécimal>$<empreinte hexadécimale>"` : une seule chaîne,
    pour que la colonne `secret` garde la même forme quelle que soit la
    méthode d'authentification — une passkey y rangerait sa propre
    représentation le jour venu, sous un autre nom de méthode.
    """
    sel = secrets.token_bytes(SEL_OCTETS)
    empreinte = hashlib.scrypt(
        mot_de_passe.encode("utf-8"),
        salt=sel,
        n=SCRYPT_N,
        r=SCRYPT_R,
        p=SCRYPT_P,
        dklen=SCRYPT_TAILLE_CLE,
    )
    return f"{sel.hex()}${empreinte.hex()}"


def verifier_mot_de_passe(mot_de_passe: str, secret: str) -> bool:
    """Vrai si `mot_de_passe` correspond au `secret` rendu par `hacher_mot_de_passe`.

    Comparaison en **temps constant** (`hmac.compare_digest`) : comparer deux
    empreintes octet par octet, en s'arrêtant à la première différence,
    laisserait deviner l'empreinte par le temps de réponse.
    """
    sel_hex, _, empreinte_hex = secret.partition("$")
    calcul = hashlib.scrypt(
        mot_de_passe.encode("utf-8"),
        salt=bytes.fromhex(sel_hex),
        n=SCRYPT_N,
        r=SCRYPT_R,
        p=SCRYPT_P,
        dklen=SCRYPT_TAILLE_CLE,
    )
    return hmac.compare_digest(calcul, bytes.fromhex(empreinte_hex))


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

    # -- inviter, et réinviter sans y penser ---------------------------------

    def inviter(
        self,
        email: str,
        *,
        duree: timedelta = DUREE_INVITATION,
        maintenant: datetime | None = None,
    ) -> InvitationEmise:
        """Invite une adresse — ou relance l'invitation en cours, ou refuse.

        **Une seule commande, qui lit l'état** ([[Q59]], close le 18/09/2026) :

        - l'adresse n'a pas encore de compte → un compte **inactif** est
          créé, une invitation neuve l'accompagne ;
        - elle en a un et il est **actif** → `ErreurCompteExistant`, « il a
          déjà un compte » ;
        - elle en a un **inactif**, avec une invitation qui court encore →
          **le même jeton** est rendu (`deja_en_cours=True`) ;
        - elle en a un inactif dont l'invitation a **expiré** → une neuve la
          remplace.

        Rien de tout ça ne se décide par un `SELECT` préalable qui déciderait
        seul : c'est `INSERT … ON CONFLICT … DO NOTHING` qui tranche la
        création du compte, et le même motif pour l'invitation — voir les
        méthodes privées qui suivent.
        """
        normalise = normaliser_email(email)
        maintenant = _instant(maintenant)
        identifiant_compte = self._compte_a_inviter(normalise)
        return self._emettre_ou_reprendre(identifiant_compte, duree=duree, maintenant=maintenant)

    def _compte_a_inviter(self, email_normalise: str) -> str:
        """L'identifiant du compte à inviter — le crée s'il n'existe pas encore.

        `INSERT … ON CONFLICT ((lower(email))) DO NOTHING`, jamais un
        `SELECT` puis un `INSERT` : deux invitations posées en même temps sur
        une adresse neuve ne doivent fabriquer qu'un seul compte, pas gagner
        une course sur `ErreurCompteExistant`. Quand la ligne existe déjà
        (le `RETURNING` ne rend rien), on la relit pour savoir si elle est
        active — auquel cas on refuse — ou pas — auquel cas c'est son
        identifiant qu'on rend.
        """
        identifiant = nouvel_identifiant()
        with self.cx.transaction():
            ligne = self.cx.execute(
                "INSERT INTO comptes (id, email) VALUES (%s, %s) "
                "ON CONFLICT ((lower(email))) DO NOTHING "
                "RETURNING id",
                (identifiant, email_normalise),
            ).fetchone()
            if ligne is not None:
                self.cx.execute(
                    "INSERT INTO comptes_proprietaires (compte, proprietaire) VALUES (%s, %s)",
                    (ligne[0], nouvel_identifiant()),
                )
                return ligne[0]
            existant = self.cx.execute(
                "SELECT id, actif, cree_le FROM comptes WHERE lower(email) = %s",
                (email_normalise,),
            ).fetchone()
        if existant is None:  # pragma: no cover - la ligne a disparu entre-temps
            raise ErreurCompte(f"impossible d'inviter {email_normalise} — réessayer")
        identifiant_existant, actif, cree_le = existant
        if actif:
            raise ErreurCompteExistant(
                f"{email_normalise} a déjà un compte, ouvert le "
                f"{cree_le.astimezone(UTC).strftime('%d/%m/%Y')} — rien n'a été envoyé"
            )
        return identifiant_existant

    def _emettre_ou_reprendre(
        self, identifiant_compte: str, *, duree: timedelta, maintenant: datetime
    ) -> InvitationEmise:
        """Pose une invitation neuve, ou rend celle déjà en cours pour ce compte.

        Même motif que pour le compte : `DELETE` de ce qui a expiré puis
        `INSERT … ON CONFLICT (compte) WHERE consomme_le IS NULL DO NOTHING`,
        jamais un `SELECT` puis un `INSERT`. Ce qui change par rapport à la
        version condensée du jeton : comme le jeton **est** en base en clair,
        on peut désormais le relire et le rendre tel quel à l'appelant qui
        relance une invitation déjà en cours.
        """
        jeton = secrets.token_urlsafe(OCTETS_JETON)
        with self.cx.transaction():
            self.cx.execute(
                "DELETE FROM invitations "
                "WHERE compte = %s AND consomme_le IS NULL AND expire_le <= %s",
                (identifiant_compte, maintenant),
            )
            ligne = self.cx.execute(
                "INSERT INTO invitations (jeton, compte, cree_le, expire_le) "
                "VALUES (%s, %s, %s, %s) "
                "ON CONFLICT (compte) WHERE consomme_le IS NULL DO NOTHING "
                "RETURNING jeton, compte, cree_le, expire_le, consomme_le",
                (jeton, identifiant_compte, maintenant, maintenant + duree),
            ).fetchone()
            if ligne is not None:
                return InvitationEmise(_invitation(ligne), jeton=jeton, deja_en_cours=False)
            en_cours = self.cx.execute(
                "SELECT jeton, compte, cree_le, expire_le, consomme_le FROM invitations "
                "WHERE compte = %s AND consomme_le IS NULL",
                (identifiant_compte,),
            ).fetchone()
        if en_cours is None:  # pragma: no cover - la ligne a disparu entre-temps
            raise ErreurCompte(
                f"impossible de poser une invitation pour le compte "
                f"{identifiant_compte!r} — réessayer"
            )
        invitation = _invitation(en_cours)
        return InvitationEmise(invitation, jeton=invitation.jeton, deja_en_cours=True)

    # -- activer --------------------------------------------------------------

    def activer(
        self, jeton: str, mot_de_passe: str, *, maintenant: datetime | None = None
    ) -> Acces:
        """Pose le mot de passe, active le compte, consomme l'invitation — atomique.

        **Une seule transaction pour les trois.** L'invitation se consomme
        par un `UPDATE … WHERE jeton = … AND consomme_le IS NULL AND
        expire_le > … RETURNING` : deux activations concurrentes du même
        jeton se sérialisent sur la ligne, la seconde ne voit plus
        `consomme_le IS NULL` et échoue proprement. Le mot de passe est
        haché **à l'intérieur** de cette même transaction, après la
        consommation de l'invitation et avant l'activation du compte : si le
        hachage échoue, la transaction entière annule — l'invitation
        redevient utilisable, le compte reste inactif. Un compte actif sans
        secret ne peut donc exister à aucun instant, pas même le temps d'un
        incident.

        Le jeton n'apparaît dans aucun message d'erreur : ce qui est refusé
        est nommé (inconnu, expiré, déjà utilisé), pas montré.
        """
        maintenant = _instant(maintenant)
        with self.cx.transaction():
            ligne = self.cx.execute(
                "UPDATE invitations SET consomme_le = %(quand)s "
                "WHERE jeton = %(jeton)s "
                "  AND consomme_le IS NULL "
                "  AND expire_le > %(quand)s "
                "RETURNING compte",
                {"quand": maintenant, "jeton": jeton},
            ).fetchone()
            if ligne is None:
                raise self._invitation_refusee(jeton)
            identifiant_compte = ligne[0]
            secret = hacher_mot_de_passe(mot_de_passe)
            compte = self.cx.execute(
                "UPDATE comptes SET actif = true, methode_authentification = %s, secret = %s "
                "WHERE id = %s "
                "RETURNING id, email, actif, cree_le",
                (METHODE_MOT_DE_PASSE, secret, identifiant_compte),
            ).fetchone()
            proprietaire = self.proprietaire_du_compte(identifiant_compte)
        if compte is None:  # pragma: no cover - la clé étrangère l'interdit
            raise ErreurCompte("invitation rattachée à un compte disparu")
        return Acces(
            compte=Compte(
                identifiant=compte[0], email=compte[1], actif=compte[2], cree_le=compte[3]
            ),
            proprietaire=proprietaire,
        )

    # -- ce qui est commun aux deux --------------------------------------------

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

    def _invitation_refusee(self, jeton: str) -> ErreurInvitationRefusee:
        """Dire *pourquoi* le jeton est refusé, sans jamais répéter le jeton."""
        ligne = self.cx.execute(
            "SELECT expire_le, consomme_le FROM invitations WHERE jeton = %s", (jeton,)
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
    d'un argument, pas en attendant trois jours ni en trafiquant la base.
    """
    if maintenant is None:
        return datetime.now(UTC)
    if maintenant.tzinfo is None:
        raise ErreurCompte("un instant sans fuseau ne désigne rien — passer un datetime en UTC")
    return maintenant


def _invitation(ligne: tuple) -> Invitation:
    return Invitation(
        jeton=ligne[0],
        compte=ligne[1],
        cree_le=ligne[2],
        expire_le=ligne[3],
        consomme_le=ligne[4],
    )


__all__ = [
    "DUREE_INVITATION",
    "METHODE_MOT_DE_PASSE",
    "OCTETS_JETON",
    "Acces",
    "Compte",
    "DepotComptes",
    "ErreurCompte",
    "ErreurCompteExistant",
    "ErreurInvitationRefusee",
    "Invitation",
    "InvitationEmise",
    "hacher_mot_de_passe",
    "normaliser_email",
    "nouvel_identifiant",
    "verifier_mot_de_passe",
]
