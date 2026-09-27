"""Les comptes, les invitations, et le lien vers le propriétaire pseudonyme.

Doctrine §10.2 : **l'entrée se fait sur invitation, définitivement, y compris
pour la version publique.** Il n'y a pas de création de compte à la demande,
donc pas de formulaire d'inscription, pas de demande d'accès, pas de liste
d'attente. Le seul chemin vers un compte est un lien envoyé par l'exploitant
du service — et son propre compte passe par ce chemin-là, sans trappe
d'amorçage.

## Des choix simples, assumés

- **Le jeton d'invitation est en clair.** L'exploitant doit pouvoir le
  relire et le renvoyer par le canal qu'il veut — un condensé l'en
  empêcherait. Le risque est borné par la durée, **trois jours**
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

## Le cycle de vie

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
séparé « relancer » (décision Q59, `docs/journal/questions/questions_mainteneur.md`).

## Les sessions

`activer` ouvre l'accès ; encore fallait-il un moyen de **rester** connecté,
et d'y **revenir**. La table `sessions` (`migrations/0002_sessions.sql`) porte
un jeton opaque de plus, avec la même logique que celui de l'invitation : pas
de cookie signé, pas de clé de serveur à gérer, un jeton aléatoire en base qui
se révoque en effaçant sa ligne (`fermer_session`). Trois méthodes, la même
frontière que le reste du module — elles précèdent ou entourent l'existence
d'une session, elles ne servent pas de données à un propriétaire :

- `ouvrir_session(compte)` — après `activer` ou `authentifier`, jamais avant ;
- `proprietaire_de_la_session(jeton)` — `None` si le jeton est inconnu ou la
  session expirée, jamais une exception : c'est `api/session.py` qui traduit
  cette absence en 401 ;
- `fermer_session(jeton)` — idempotente, pour que se déconnecter marche même
  deux fois.

`authentifier(email, mot_de_passe)` est le pendant de `activer` pour revenir
sans jeton d'invitation : **une adresse sans compte actif et un mot de passe
faux rendent la même chose, dans le même temps** — sans quoi la route qui
l'appelle deviendrait un oracle pour qui cherche des adresses valides
(`_SECRET_BOUCHE_TROU` égalise le temps de calcul, pas seulement le message).

## Pourquoi ce dépôt n'est pas dans `api/depots.py`

`api/depots.py` s'ouvre sur une phrase qu'un invariant fait respecter :
« chaque méthode publique de ce module prend un `Proprietaire` en premier
argument positionnel ». C'est la clause de propriétaire de la doctrine §10.2,
et elle est juste — pour des données qui **appartiennent** à quelqu'un.

Les opérations d'ici sont d'une autre nature : inviter et activer un compte
**précèdent** l'existence d'un propriétaire. Leur demander une clause de
propriétaire serait circulaire, exactement comme pour les fonctions
`_migrer` dispensées par l'invariant SQL. Le choix retenu est donc : **un
module séparé, une frontière nommée**. C'est la ligne de la décision Q46
(`docs/journal/questions/questions_mainteneur.md`) — le compte
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
from ourouler.noyau.erreurs import ErreurUtilisateur

#: Combien de temps une invitation reste valable. **Trois jours** : c'est la
#: contrepartie du jeton en clair, voir la note de module. L'argument `duree` de `inviter` peut la changer ;
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
#: attaque GPU ou ASIC chère. Ce projet n'est pas une banque : ces valeurs, pas
#: les plus hautes recommandées pour un service bancaire, restent largement
#: au-dessus de ce qu'un mot de passe de
#: cycliste entre amis mérite.
SCRYPT_N = 2**14
SCRYPT_R = 8
SCRYPT_P = 1
SCRYPT_TAILLE_CLE = 32

#: Taille du sel, propre à chaque compte, tiré à chaque hachage.
SEL_OCTETS = 16

#: Combien de temps une session reste valable après sa création. Pas de
#: renouvellement glissant (voir la note de `0002_sessions.sql`) : l'échéance
#: est posée une fois, à l'ouverture, et l'usage ne la repousse pas. Trente
#: jours : ourouler sert un
#: cycliste et quelques proches sur leur propre navigateur, pas un guichet
#: public, et il n'y a pas encore de récupération de secret pour rattraper
#: une session perdue trop tôt.
DUREE_SESSION = timedelta(days=30)

#: Longueur, en octets d'entropie, du jeton de session — même choix que
#: `OCTETS_JETON` pour l'invitation, et pour la même raison.
OCTETS_JETON_SESSION = 32


class ErreurCompte(ErreurUtilisateur):
    """Ce que l'exploitant doit lire quand une invitation ou une activation échoue."""


class ErreurCompteExistant(ErreurCompte):
    """L'adresse est déjà titulaire d'un compte **actif**.

    « Pas d'interface ne veut pas dire pas de contrôle » : inviter un compte
    déjà actif répond « il a déjà un compte », jamais un doublon. Un compte
    **inactif** ne lève pas cette erreur : `inviter` lui rend son invitation
    en cours, ou lui en pose une neuve si la sienne a expiré.

    **La limite, écrite avant qu'elle morde.** Aujourd'hui, la seule façon
    d'atteindre cette erreur est que **l'exploitant** invite quelqu'un
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


class ErreurMotDePasseActuelRefuse(ErreurCompte):
    """L'ancien mot de passe fourni ne correspond pas à celui du compte.

    Levée par `changer_mot_de_passe` — le changement « je connais déjà mon mot de passe,
    j'en choisis un autre », sous session ouverte, distinct de la réinitialisation par
    jeton (`changer_mot_de_passe_par_jeton`) qui, elle, ne prouve rien de l'ancien secret."""


@dataclass(frozen=True)
class Compte:
    """L'identité et l'accès : un identifiant opaque, une adresse, l'état, une date.

    Le `repr` **masque l'adresse** : un `repr` finit dans un journal, dans un
    `print` de mise au point, dans la sortie d'un échec de test, et l'adresse
    y apparaîtrait en clair. L'identifiant, lui, reste
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
class ChoixConservation:
    """Le choix de garder ou d'effacer ses fichiers d'origine, et depuis quand.

    Fiche « choix de garder ou d'effacer ses fichiers d'origine » —
    `migrations/0003_conservation_fichiers.sql`. `garder` vaut `True` par
    défaut (Q67 révisée le 27/09/2026) : un compte qui n'a jamais touché ce
    réglage garde ses fichiers, comme avant que ce choix existe.
    """

    garder: bool
    #: `None` si personne n'a jamais posé ce choix explicitement — voir
    #: `migrations/0003_conservation_fichiers.sql`.
    depuis: datetime | None


@dataclass(frozen=True)
class Invitation:
    """Une invitation telle qu'elle vit en base, jeton compris.

    Le jeton est en clair en base — voir la note de module — mais un `repr`
    finit dans un journal aussi facilement qu'une ligne SQL : il reste masqué
    ici comme partout ailleurs dans ce module.
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
class InvitationAvecAdresse:
    """Une invitation en cours, avec l'adresse qu'elle vise — ce qu'`ourouler invitations` affiche.

    Distincte d'`Invitation` : celle-ci ne porte pas l'adresse (elle vit dans `comptes`,
    pas `invitations`), et cette jointure n'a de sens que pour cet affichage précis — la
    faire à chaque lecture d'`Invitation` serait une donnée que personne d'autre ne demande.

    Jeton et adresse restent masqués dans le `repr`, comme partout ailleurs dans ce
    module : c'est ce qu'`ourouler invitations` montre à l'écran, pas ce qui doit finir
    dans un journal ou une trace.
    """

    jeton: str
    email: str
    cree_le: datetime
    expire_le: datetime

    def __repr__(self) -> str:
        return (
            f"InvitationAvecAdresse(jeton=<masqué>, email=<masqué>, "
            f"cree_le={self.cree_le.isoformat()}, expire_le={self.expire_le.isoformat()})"
        )


@dataclass(frozen=True)
class Acces:
    """Ce qu'une activation ouvre : un compte, et son propriétaire.

    Les deux voyagent ensemble et restent distincts : c'est toute la décision
    Q46, et les fondre en un seul objet serait la défaire au premier
    appel.

    Le `repr` reste celui de la dataclass : il n'a pas de champ sensible à
    lui, et l'adresse qu'il montrerait est celle de son `Compte`, dont le
    `repr` la masque déjà.
    """

    compte: Compte
    proprietaire: Proprietaire


@dataclass(frozen=True)
class InvitationOuverte:
    """L'état d'un jeton d'invitation encore valable — sans le consommer.

    Rendu par `DepotComptes.invitation_ouverte`, pour l'écran qui affiche
    « vous avez été invité·e » avant de poser un mot de passe. Un jeton
    inconnu, périmé ou déjà consommé ne produit **pas** cet objet : les trois
    rendent `None`, indistinguablement — voir la méthode.
    """

    email: str
    expire_le: datetime


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


#: Un hachage bouche-trou : ni un mot de passe réel, ni celui de personne —
#: calculé une seule fois, au chargement du module, pour que `authentifier`
#: ait **quelque chose** à comparer quand l'adresse n'a pas de compte actif.
#: Sans lui, une adresse inconnue répondrait aussitôt (aucun hachage à
#: calculer) et une adresse connue répondrait après le coût de scrypt : le
#: temps de réponse dirait alors, à lui seul, si l'adresse a un compte.
#: Comparer contre ce bouche-trou fait tourner le même calcul dans les deux
#: cas.
_SECRET_BOUCHE_TROU = hacher_mot_de_passe(secrets.token_urlsafe(16))


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

        **Une seule commande, qui lit l'état** (décision Q59) :

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
                "DELETE FROM invitations WHERE compte = %s AND consomme_le IS NULL AND expire_le <= %s",
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
                f"impossible de poser une invitation pour le compte {identifiant_compte!r} — réessayer"
            )
        invitation = _invitation(en_cours)
        return InvitationEmise(invitation, jeton=invitation.jeton, deja_en_cours=True)

    # -- activer --------------------------------------------------------------

    def activer(self, jeton: str, mot_de_passe: str, *, maintenant: datetime | None = None) -> Acces:
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

        **Le compte visé doit être inactif** :
        `AND compte IN (SELECT id FROM comptes WHERE NOT actif)` — sans ce filtre, un
        jeton de *réinitialisation* (`reinitialiser`, qui vise un compte déjà actif)
        présenté ici se consommait quand même : le mot de passe changeait, mais
        `actif` restait déjà vrai et rien ne le contredisait, si bien que la ligne
        d'`invitations` brûlait pour un effet qu'`activer` ne documente pas (elle ne
        ferme pas les sessions, contrairement à `changer_mot_de_passe_par_jeton`).
        Un jeton d'invitation ne vaut donc que pour le compte inactif qui l'a reçu ;
        le même jeton présenté après coup à `changer_mot_de_passe_par_jeton` échoue
        symétriquement, pour la raison inverse.
        """
        maintenant = _instant(maintenant)
        with self.cx.transaction():
            ligne = self.cx.execute(
                "UPDATE invitations SET consomme_le = %(quand)s "
                "WHERE jeton = %(jeton)s "
                "  AND consomme_le IS NULL "
                "  AND expire_le > %(quand)s "
                "  AND compte IN (SELECT id FROM comptes WHERE NOT actif) "
                "RETURNING compte",
                {"quand": maintenant, "jeton": jeton},
            ).fetchone()
            if ligne is None:
                raise self._invitation_refusee(jeton, attendu_actif=False, maintenant=maintenant)
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
            compte=Compte(identifiant=compte[0], email=compte[1], actif=compte[2], cree_le=compte[3]),
            proprietaire=proprietaire,
        )

    # -- réinitialiser : un nouveau mot de passe pour un compte déjà actif ----
    #
    # Le trou que `inviter` laisse volontairement ouvert : un
    # compte **actif** qui a perdu son mot de passe n'a aucun moyen d'en
    # poser un autre. Plutôt qu'un second système de jetons, `reinitialiser`
    # pose une invitation sur la **même** table `invitations`, avec la même
    # garantie d'unicité en cours (`invitations_en_cours_unique`) et le même
    # mécanisme de consommation atomique — voir `_emettre_ou_reprendre`,
    # partagé avec `inviter`. Ce qui distingue les deux flux n'est donc pas
    # le jeton, mais ce que sa consommation fait au compte : `activer` pose
    # `actif = true` et remplit `comptes_proprietaires` (un compte neuf) ;
    # `changer_mot_de_passe_par_jeton` ne touche ni l'un ni l'autre (déjà en
    # place) et referme toutes les sessions ouvertes du compte à la place.
    #
    # **Aucune route HTTP anonyme n'appelle `reinitialiser`** : un « mot de passe oublié » en libre-service
    # ouvrirait un relais de spam (poster une adresse au hasard fait partir
    # un courriel) et un oracle d'énumération (la réponse dirait si l'adresse
    # a un compte, comme `ErreurCompteExistant` le documente déjà pour
    # `inviter`). Seul l'exploitant, en ligne de commande
    # (`ourouler reinitialiser`), émet ce lien — voir `cli/` et
    # `deploiement/api/README.md`.

    def reinitialiser(
        self,
        email: str,
        *,
        duree: timedelta = DUREE_INVITATION,
        maintenant: datetime | None = None,
    ) -> InvitationEmise:
        """Émet un lien de réinitialisation — ou relance celui déjà en cours — pour un compte actif.

        Le pendant exact d'`inviter`, avec la condition inversée : `inviter` refuse un
        compte déjà actif (`ErreurCompteExistant`), `reinitialiser` l'exige. Une adresse
        sans compte, ou dont le compte est encore inactif (invité mais jamais activé),
        est refusée : c'est `inviter` qu'il faut alors, pas `reinitialiser` — les deux
        commandes ne se chevauchent pas.
        """
        normalise = normaliser_email(email)
        maintenant = _instant(maintenant)
        identifiant_compte = self._compte_actif_a_reinitialiser(normalise)
        return self._emettre_ou_reprendre(identifiant_compte, duree=duree, maintenant=maintenant)

    def _compte_actif_a_reinitialiser(self, email_normalise: str) -> str:
        """L'identifiant du compte actif à réinitialiser, ou un refus qui dit pourquoi."""
        ligne = self.cx.execute(
            "SELECT id, actif FROM comptes WHERE lower(email) = %s", (email_normalise,)
        ).fetchone()
        if ligne is None:
            raise ErreurCompte(f"{email_normalise} n'a pas de compte — rien à réinitialiser")
        identifiant, actif = ligne
        if not actif:
            raise ErreurCompte(
                f"{email_normalise} n'a pas encore de compte actif — « ourouler inviter », "
                "pas « ourouler reinitialiser », pour une invitation en cours"
            )
        return identifiant

    def changer_mot_de_passe_par_jeton(
        self, jeton: str, nouveau_mot_de_passe: str, *, maintenant: datetime | None = None
    ) -> Acces:
        """Pose un nouveau mot de passe depuis un jeton de réinitialisation, et déconnecte tout le monde.

        Le pendant d'`activer`, pour un compte **déjà actif** : consomme l'invitation par
        le même `UPDATE … WHERE … RETURNING` (même garantie d'usage unique et de course
        gagnée par une seule des deux tentatives concurrentes), hache et pose le nouveau
        secret — mais, à la différence d'`activer`, ne touche ni `actif` (déjà vrai) ni
        `comptes_proprietaires` (déjà rempli depuis l'activation d'origine : reposer une
        ligne recréerait la correspondance compte-propriétaire sur un identifiant neuf, ce qui
        casserait le rattachement aux données existantes).

        **Toutes les sessions ouvertes du compte sont fermées ici, à la consommation du
        jeton — pas avant.** Un lien émis mais pas encore utilisé ne doit déconnecter
        personne (l'exploitant qui vient d'émettre un lien reste connecté) ; c'est la
        perte du mot de passe, actée par la pose du nouveau, qui rend caduque toute
        confiance dans les sessions déjà ouvertes — quelqu'un qui aurait volé l'ancien
        mot de passe et laissé une session active ne doit pas la garder après coup. Les
        quatre gestes (consommer, hacher, poser le secret, fermer les sessions) sont dans
        la **même transaction** qu'`activer` : un incident au milieu laisse tout en
        arrière, jeton compris.

        **Le compte visé doit être actif** :
        `AND compte IN (SELECT id FROM comptes WHERE actif)` — sans ce filtre, un
        jeton *d'invitation* (qui vise un compte encore inactif) présenté ici posait
        quand même un secret et ouvrait une session, sans jamais activer le compte ni
        remplir `comptes_proprietaires` : un compte inactif avec une session valide,
        un état que la doctrine du module interdit ailleurs.
        """
        maintenant = _instant(maintenant)
        with self.cx.transaction():
            ligne = self.cx.execute(
                "UPDATE invitations SET consomme_le = %(quand)s "
                "WHERE jeton = %(jeton)s "
                "  AND consomme_le IS NULL "
                "  AND expire_le > %(quand)s "
                "  AND compte IN (SELECT id FROM comptes WHERE actif) "
                "RETURNING compte",
                {"quand": maintenant, "jeton": jeton},
            ).fetchone()
            if ligne is None:
                raise self._invitation_refusee(jeton, attendu_actif=True, maintenant=maintenant)
            identifiant_compte = ligne[0]
            secret = hacher_mot_de_passe(nouveau_mot_de_passe)
            compte = self.cx.execute(
                "UPDATE comptes SET methode_authentification = %s, secret = %s "
                "WHERE id = %s "
                "RETURNING id, email, actif, cree_le",
                (METHODE_MOT_DE_PASSE, secret, identifiant_compte),
            ).fetchone()
            self.cx.execute("DELETE FROM sessions WHERE compte = %s", (identifiant_compte,))
            proprietaire = self.proprietaire_du_compte(identifiant_compte)
        if compte is None:  # pragma: no cover - la clé étrangère l'interdit
            raise ErreurCompte("invitation de réinitialisation rattachée à un compte disparu")
        return Acces(
            compte=Compte(identifiant=compte[0], email=compte[1], actif=compte[2], cree_le=compte[3]),
            proprietaire=proprietaire,
        )

    def changer_mot_de_passe(
        self, identifiant_compte: str, ancien_mot_de_passe: str, nouveau_mot_de_passe: str
    ) -> None:
        """Change le mot de passe sous session ouverte — vérifie l'ancien, pose le nouveau.

        À la différence de `changer_mot_de_passe_par_jeton`, l'appelant est déjà
        authentifié (une session ouverte l'a amené ici) et vient de prouver, en
        fournissant l'ancien mot de passe, qu'il n'a rien perdu : les autres sessions
        ouvertes de ce compte ne sont **pas** fermées — rien ne les rend caduques.

        Lève `ErreurMotDePasseActuelRefuse` si `ancien_mot_de_passe` ne correspond pas
        (compte inconnu ou inactif compris, pour ne pas distinguer les deux cas).
        """
        ligne = self.cx.execute(
            "SELECT secret FROM comptes WHERE id = %s AND actif", (identifiant_compte,)
        ).fetchone()
        if ligne is None or not verifier_mot_de_passe(ancien_mot_de_passe, ligne[0]):
            raise ErreurMotDePasseActuelRefuse("mot de passe actuel refusé")
        nouveau_secret = hacher_mot_de_passe(nouveau_mot_de_passe)
        with self.cx.transaction():
            self.cx.execute(
                "UPDATE comptes SET secret = %s WHERE id = %s",
                (nouveau_secret, identifiant_compte),
            )

    # -- retrouver un compte, pour `ourouler retirer` et le changement de mot de passe --

    def compte_par_email(self, email: str) -> Compte | None:
        """Le compte pour cette adresse, actif ou non — ou `None` si l'adresse n'a pas de compte.

        Sert `ourouler retirer` : trouver le compte visé avant d'en chercher
        le propriétaire (`proprietaire_du_compte`) et d'effacer ses données.
        """
        normalise = normaliser_email(email)
        ligne = self.cx.execute(
            "SELECT id, email, actif, cree_le FROM comptes WHERE lower(email) = %s", (normalise,)
        ).fetchone()
        if ligne is None:
            return None
        return Compte(identifiant=ligne[0], email=ligne[1], actif=ligne[2], cree_le=ligne[3])

    def comptes_actifs(self) -> list[Compte]:
        """Les comptes **actifs**, triés par date de création — pour l'administration.

        N'expose jamais un compte inactif (invité mais pas encore activé) :
        ceux-là n'ont pas encore de secret et n'ont rien à « supprimer » — ils
        disparaissent tout seuls quand leur invitation expire et qu'une
        nouvelle invitation les remplace.
        """
        lignes = self.cx.execute(
            "SELECT id, email, actif, cree_le FROM comptes WHERE actif ORDER BY cree_le"
        ).fetchall()
        return [
            Compte(identifiant=ligne[0], email=ligne[1], actif=ligne[2], cree_le=ligne[3]) for ligne in lignes
        ]

    def compte_du_proprietaire(self, proprietaire: Proprietaire) -> Compte | None:
        """Le compte lié à ce propriétaire — ou `None` (déploiement sans compte, ou orphelin).

        Le sens inverse de `proprietaire_du_compte`, utile à `GET /moi` et
        `POST /moi/mot-de-passe` : ces deux routes partent d'un `Proprietaire` (résolu par
        la session) et ont besoin du compte pour, respectivement, en montrer l'adresse et
        en changer le secret.
        """
        ligne = self.cx.execute(
            "SELECT c.id, c.email, c.actif, c.cree_le FROM comptes c "
            "JOIN comptes_proprietaires cp ON cp.compte = c.id "
            "WHERE cp.proprietaire = %s",
            (str(proprietaire),),
        ).fetchone()
        if ligne is None:
            return None
        return Compte(identifiant=ligne[0], email=ligne[1], actif=ligne[2], cree_le=ligne[3])

    def choix_conservation_du_proprietaire(self, proprietaire: Proprietaire) -> ChoixConservation | None:
        """Le choix de ce compte — ou `None` s'il n'a pas (encore) de compte lié.

        Pour l'écran Réglages → Mon compte et pour `GET /moi/export`. `None`
        se traite comme « garder » (le défaut) par l'appelant qui n'a besoin
        que d'un booléen — `api/routes/commun._conserver_brut`.
        """
        ligne = self.cx.execute(
            "SELECT c.conserver_fichiers_bruts, c.conserver_fichiers_bruts_le FROM comptes c "
            "JOIN comptes_proprietaires cp ON cp.compte = c.id WHERE cp.proprietaire = %s",
            (str(proprietaire),),
        ).fetchone()
        if ligne is None:
            return None
        return ChoixConservation(garder=ligne[0], depuis=ligne[1])

    def definir_conservation_du_proprietaire(
        self, proprietaire: Proprietaire, *, garder: bool
    ) -> ChoixConservation:
        """Pose le choix de ce compte, horodaté à maintenant. Lève `ErreurCompte` sans compte lié.

        Toujours horodaté au moment de l'appel, même si le choix ne change
        pas : redemander « ne pas garder » alors que c'est déjà le cas est
        sans effet ailleurs (`api/vie_privee.py` n'efface rien de plus), mais
        la date dit quand la personne a confirmé pour la dernière fois — utile
        si elle doute d'avoir cliqué.
        """
        with self.cx.transaction():
            ligne = self.cx.execute(
                "UPDATE comptes SET conserver_fichiers_bruts = %s, conserver_fichiers_bruts_le = now() "
                "WHERE id = (SELECT compte FROM comptes_proprietaires WHERE proprietaire = %s) "
                "RETURNING conserver_fichiers_bruts, conserver_fichiers_bruts_le",
                (garder, str(proprietaire)),
            ).fetchone()
        if ligne is None:
            raise ErreurCompte(f"aucun compte lié au propriétaire {proprietaire!r}")
        return ChoixConservation(garder=ligne[0], depuis=ligne[1])

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
                "la correspondance compte → propriétaire manque, ce qui ne devrait pas arriver"
            )
        return Proprietaire(ligne[0])

    def supprimer_compte_du_proprietaire(self, proprietaire: Proprietaire) -> bool:
        """Efface le compte lié à ce propriétaire — vrai si un compte a été effacé.

        C'est l'autre face de la décision Q46, côté effacement RGPD
        (`api/vie_privee.py`) : « c'est **elle** qu'on
        efface à la suppression d'un compte » (doctrine §10.2). Un seul
        `DELETE`, sur une sous-requête qui retrouve le compte via
        `comptes_proprietaires` (colonne `proprietaire`) : la cascade du
        schéma fait le reste — `invitations.compte`, `sessions.compte` et
        `comptes_proprietaires.compte` référencent `comptes (id)` en
        `ON DELETE CASCADE` (`migrations/0001_comptes.sql`,
        `migrations/0002_sessions.sql`), donc effacer la ligne `comptes`
        emporte d'un coup l'invitation, les sessions ouvertes et la
        correspondance elle-même. Aucune requête séparée n'est nécessaire.

        **Idempotente** : un propriétaire sans compte lié (jamais invité, ou
        déjà supprimé) ne lève rien et rend simplement `False` — le même
        parti pris que `DepotProfils.supprimer_profil` et consorts
        (`api/depots.py`), pour que `vie_privee.effacer_donnees` reste
        appelable plusieurs fois sur le même propriétaire sans jamais échouer.
        """
        with self.cx.transaction():
            ligne = self.cx.execute(
                "DELETE FROM comptes WHERE id = ("
                "  SELECT compte FROM comptes_proprietaires WHERE proprietaire = %s"
                ") RETURNING id",
                (str(proprietaire),),
            ).fetchone()
        return ligne is not None

    def invitations_en_cours(self, *, maintenant: datetime | None = None) -> list[InvitationAvecAdresse]:
        """Les invitations non consommées et non expirées, adresse et jeton compris.

        C'est ce qui rend le jeton **retrouvable** sans fouiller un historique de
        terminal ou de messagerie : c'est ce que sert `ourouler invitations`.
        Triée par `cree_le` : les plus anciennes, donc les plus urgentes à
        relancer ou à relire, en tête.
        """
        maintenant = _instant(maintenant)
        lignes = self.cx.execute(
            "SELECT invitations.jeton, comptes.email, invitations.cree_le, invitations.expire_le "
            "FROM invitations "
            "JOIN comptes ON comptes.id = invitations.compte "
            "WHERE invitations.consomme_le IS NULL AND invitations.expire_le > %s "
            "ORDER BY invitations.cree_le",
            (maintenant,),
        ).fetchall()
        return [
            InvitationAvecAdresse(jeton=jeton, email=email, cree_le=cree_le, expire_le=expire_le)
            for jeton, email, cree_le, expire_le in lignes
        ]

    # -- l'état d'un jeton, sans le consommer ------------------------------------

    def invitation_ouverte(
        self, jeton: str, *, maintenant: datetime | None = None
    ) -> InvitationOuverte | None:
        """L'adresse et l'échéance d'un jeton encore valable — ou `None`.

        **Indistinguable par construction** : un jeton inconnu,
        un jeton expiré et un jeton déjà consommé rendent tous les trois
        `None`, par la même requête — une seule ligne ne remonte que si les
        trois conditions (`jeton = …`, `consomme_le IS NULL`,
        `expire_le > maintenant`) sont réunies à la fois. Il n'y a donc rien à
        choisir entre trois messages : il n'y a que deux réponses possibles,
        et c'est voulu — un inconnu qui essaie des jetons au hasard ne doit
        pas apprendre lequel de ces trois états il a rencontré.
        """
        maintenant = _instant(maintenant)
        ligne = self.cx.execute(
            "SELECT c.email, i.expire_le FROM invitations i JOIN comptes c ON c.id = i.compte "
            "WHERE i.jeton = %s AND i.consomme_le IS NULL AND i.expire_le > %s",
            (jeton, maintenant),
        ).fetchone()
        if ligne is None:
            return None
        return InvitationOuverte(email=ligne[0], expire_le=ligne[1])

    # -- authentifier, pour revenir sans jeton d'invitation ----------------------

    def authentifier(self, email: str, mot_de_passe: str) -> Compte | None:
        """Le compte si l'adresse a un compte actif et que le mot de passe convient.

        **Une adresse sans compte actif et un mot de passe faux rendent la
        même chose, dans le même temps** : une différence de comportement entre « cette adresse n'a pas de
        compte » et « ce mot de passe est faux » est un oracle offert à qui
        cherche des adresses valides. Le hachage tourne même quand l'adresse
        n'existe pas ou que le compte n'est pas actif, comparé au bouche-trou
        (`_SECRET_BOUCHE_TROU`) : c'est ce qui égalise le temps de réponse,
        pas seulement le message rendu à l'appelant.
        """
        normalise = normaliser_email(email)
        ligne = self.cx.execute(
            "SELECT id, email, actif, cree_le, secret FROM comptes WHERE lower(email) = %s",
            (normalise,),
        ).fetchone()
        if ligne is None or not ligne[2]:
            verifier_mot_de_passe(mot_de_passe, _SECRET_BOUCHE_TROU)
            return None
        identifiant, email_bd, actif, cree_le, secret = ligne
        if not verifier_mot_de_passe(mot_de_passe, secret):
            return None
        return Compte(identifiant=identifiant, email=email_bd, actif=actif, cree_le=cree_le)

    # -- sessions : ouvrir, retrouver, fermer ------------------------------------

    def ouvrir_session(
        self,
        compte: str,
        *,
        duree: timedelta = DUREE_SESSION,
        maintenant: datetime | None = None,
    ) -> str:
        """Une session neuve pour ce compte, et rend son jeton en clair.

        Appelée après une activation (`POST /entrer`) ou une authentification
        réussie (`POST /connexion`) — jamais avant : ce dépôt ne revérifie pas
        ici que le compte est actif, c'est à l'appelant de n'appeler ceci
        qu'après `activer` ou `authentifier`.
        """
        maintenant = _instant(maintenant)
        jeton = secrets.token_urlsafe(OCTETS_JETON_SESSION)
        with self.cx.transaction():
            self.cx.execute(
                "INSERT INTO sessions (jeton, compte, cree_le, expire_le) VALUES (%s, %s, %s, %s)",
                (jeton, compte, maintenant, maintenant + duree),
            )
        return jeton

    def proprietaire_de_la_session(
        self, jeton: str, *, maintenant: datetime | None = None
    ) -> Proprietaire | None:
        """Le propriétaire derrière ce jeton — ou `None` si la session est absente ou expirée.

        `None` n'est pas une panne (voir `api/session.py`) : un jeton
        inconnu, une session expirée et une session fermée par
        `fermer_session` rendent tous les trois `None`, et l'appelant
        (`SessionParCookie`) le traduit en 401.
        """
        maintenant = _instant(maintenant)
        ligne = self.cx.execute(
            "SELECT compte FROM sessions WHERE jeton = %s AND expire_le > %s",
            (jeton, maintenant),
        ).fetchone()
        if ligne is None:
            return None
        return self.proprietaire_du_compte(ligne[0])

    def fermer_session(self, jeton: str) -> None:
        """Révoque cette session — silencieusement si elle n'existait déjà plus.

        Idempotente à dessein : `POST /sortir` doit rendre le cookie
        inutilisable que la session ait déjà expiré, ait déjà été fermée
        ailleurs, ou soit toujours vivante. « Ça n'existait déjà plus » n'est
        pas un échec pour qui veut simplement ne plus être connecté.
        """
        with self.cx.transaction():
            self.cx.execute("DELETE FROM sessions WHERE jeton = %s", (jeton,))

    def _invitation_refusee(
        self,
        jeton: str,
        *,
        attendu_actif: bool | None = None,
        maintenant: datetime | None = None,
    ) -> ErreurInvitationRefusee:
        """Dire *pourquoi* le jeton est refusé, sans jamais répéter le jeton.

        `attendu_actif` distingue un jeton d'invitation (`False` : vise un compte
        encore inactif) d'un jeton de réinitialisation (`True` : vise un compte déjà
        actif). Sans cette distinction, un jeton
        présenté au mauvais flux (invitation à la réinitialisation, ou l'inverse)
        retombait sur le message « a expiré », qui n'était pas la vraie raison du
        refus : le jeton n'a ni expiré ni servi, il ne vaut simplement pas pour ce
        flux-là.
        """
        ligne = self.cx.execute(
            "SELECT i.expire_le, i.consomme_le, c.actif FROM invitations i "
            "JOIN comptes c ON c.id = i.compte WHERE i.jeton = %s",
            (jeton,),
        ).fetchone()
        if ligne is None:
            return ErreurInvitationRefusee(
                "ce lien d'invitation n'existe pas — vérifier qu'il a été copié en entier"
            )
        expire_le, consomme_le, actif = ligne
        if consomme_le is not None:
            return ErreurInvitationRefusee(
                "ce lien d'invitation a déjà servi le "
                f"{consomme_le.astimezone(UTC).strftime('%d/%m/%Y')} — un lien ne sert qu'une fois"
            )
        if attendu_actif is not None and actif != attendu_actif:
            if attendu_actif:
                return ErreurInvitationRefusee(
                    "ce lien est un lien d'invitation, pas un lien de réinitialisation — "
                    "le compte visé n'est pas encore actif"
                )
            return ErreurInvitationRefusee(
                "ce lien est un lien de réinitialisation, pas un lien d'invitation — "
                "le compte visé est déjà actif"
            )
        maintenant = _instant(maintenant)
        if expire_le <= maintenant:
            return ErreurInvitationRefusee(
                "ce lien d'invitation a expiré le "
                f"{expire_le.astimezone(UTC).strftime('%d/%m/%Y')} — il en faut un nouveau"
            )
        raise ErreurCompte(  # pragma: no cover - la ligne aurait dû matcher la mise à jour
            "jeton refusé sans raison identifiable — incohérence entre la mise à jour "
            "qui a échoué et ce diagnostic, à corriger (le jeton n'apparaît pas ici, "
            "voir la règle du module)"
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
    "DUREE_SESSION",
    "METHODE_MOT_DE_PASSE",
    "OCTETS_JETON",
    "OCTETS_JETON_SESSION",
    "Acces",
    "ChoixConservation",
    "Compte",
    "DepotComptes",
    "ErreurCompte",
    "ErreurCompteExistant",
    "ErreurInvitationRefusee",
    "ErreurMotDePasseActuelRefuse",
    "Invitation",
    "InvitationAvecAdresse",
    "InvitationEmise",
    "InvitationOuverte",
    "hacher_mot_de_passe",
    "normaliser_email",
    "nouvel_identifiant",
    "verifier_mot_de_passe",
]
