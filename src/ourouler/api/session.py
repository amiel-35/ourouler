"""Qui est derrière la requête — sans jamais dire **comment** on l'a su.

Doctrine §10.2 : « Isolation des données : par utilisateur, vérifiée côté
serveur à chaque requête, jamais seulement côté front. **Aucune requête sans
clause de propriétaire.** »

`api/proprietaire.py` dit *à qui* appartient une ligne ; ce module-ci dit
*comment la requête en cours se rattache à quelqu'un*. Jusqu'au 18/09/2026
les deux étaient confondus : `resoudre()` rendait le propriétaire local, donc
une requête anonyme obtenait les données du mainteneur. La couture est ici.

**Aucune méthode d'authentification n'est choisie dans ce fichier**, et c'est
délibéré (lot L7.A du sprint 7) : ni mot de passe, ni jeton d'un fournisseur
particulier, ni courriel, ni lien à usage unique. Ce choix demande la clé
Brevo et la politique de modération, qui sont des arbitrages du mainteneur.
Ce qui s'écrit maintenant est la **forme** : une interface que le service
configure et que les tests injectent. Le jour où la méthode sera tranchée,
elle s'écrira comme une troisième classe de ce module et rien d'autre ne
bougera.

## Deux produits, pas deux réglages

Un service qui sert **une** personne chez elle et un service qui en sert
**plusieurs** ne sont pas le même produit, et le code le nomme :

- `SessionPersonnelle` — `ourouler api` sur la machine du cycliste. Il n'y a
  qu'un utilisateur, la machine est la frontière de sécurité, et le
  propriétaire est toujours le même. C'est l'usage d'origine du projet et il
  ne meurt pas.
- `SessionHebergee` — un service exposé, plusieurs cyclistes. Tant qu'aucune
  méthode d'authentification n'est branchée, il n'ouvre **aucune** session :
  toute route de données répond 401. C'est le bon comportement, pas une
  régression — servir le profil du mainteneur à un inconnu serait pire qu'un
  refus.

Ce qui devait disparaître, et qui disparaît : que le mode personnel soit le
**défaut implicite** d'un service exposé. Le mode se déclare
(`OUROULER_MODE`, lu par `api/exploitation.py` et par lui seul) ; en son
absence, le service refuse au lieu de deviner.

**Ce module ne connaît pas FastAPI.** La requête est reçue en `object` : la
ligne de commande doit pouvoir importer ce fichier sans l'extra `api`, et un
fournisseur n'a pas besoin du cadre web pour dire qui il sert.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ourouler.api.proprietaire import PROPRIETAIRE_LOCAL, Proprietaire

#: Le service sert **un** cycliste, sur sa machine. `ourouler api`.
MODE_PERSONNEL = "personnel"

#: Le service sert **plusieurs** cyclistes. Il faut donc savoir lequel parle,
#: et tant que personne ne sait le dire, il ne sert personne.
MODE_HEBERGE = "heberge"

#: Les deux modes, pour les messages d'erreur et la validation.
MODES = (MODE_PERSONNEL, MODE_HEBERGE)


class FournisseurSession(Protocol):
    """Ce que l'API demande à une session, et rien de plus.

    Une seule question — « qui parle ? » — et deux réponses possibles : un
    `Proprietaire`, ou `None` quand aucune session n'est ouverte. `None` n'est
    pas une panne : c'est l'absence de session, que la route traduit en 401.

    Un fournisseur ne lève pas d'exception pour dire « personne » ; il rend
    `None`. Ce qu'il lève, le cas échéant, est une vraie panne (un annuaire
    injoignable), et elle remonte comme les autres.
    """

    #: Lequel des deux produits ce fournisseur sert. Sert à le **dire** —
    #: dans un message d'erreur, dans une sonde — jamais à en dériver un
    #: droit : le droit vient de `ouvrir`.
    mode: str

    def ouvrir(self, requete: object) -> Proprietaire | None:
        """Le propriétaire de cette requête, ou `None` si aucune session n'est ouverte."""
        ...


@dataclass(frozen=True)
class SessionPersonnelle:
    """Un seul cycliste, chez lui : toujours le même propriétaire.

    **Explicitement configuré, jamais deviné.** C'est ce que `ourouler api`
    installe, parce que la ligne de commande tourne sur la machine de son
    utilisateur : il n'y a personne d'autre à distinguer, et exiger une
    connexion pour lire son propre fichier de configuration serait une
    cérémonie sans objet.

    La requête est ignorée, et c'est le point : rien de ce que le client
    envoie ne peut désigner quelqu'un d'autre.
    """

    proprietaire: Proprietaire = PROPRIETAIRE_LOCAL

    #: Sans annotation : une *constante de classe*, pas un champ de la
    #: dataclasse — on ne construit pas une `SessionPersonnelle` d'un autre
    #: mode.
    mode = MODE_PERSONNEL

    def ouvrir(self, requete: object) -> Proprietaire:
        del requete
        return self.proprietaire


@dataclass(frozen=True)
class SessionHebergee:
    """Plusieurs cyclistes, et aucune méthode d'authentification branchée.

    **N'ouvre jamais de session**, donc toute route de données répond 401.
    Ce n'est pas un bouchon en attendant mieux : c'est la seule réponse juste
    tant que le service ne sait pas reconnaître qui parle. Un défaut qui
    servirait « le » profil du serveur ferait de chaque déploiement une fuite
    en un mot.

    Le jour où la méthode sera tranchée (clé Brevo, politique de modération —
    hors périmètre du sprint 7), elle prendra la place de cette classe dans
    `exploitation.fournisseur_session`, et rien d'autre ne changera.
    """

    mode = MODE_HEBERGE

    def ouvrir(self, requete: object) -> None:
        del requete
        return None


#: La phrase rendue au cycliste quand aucune session n'est ouverte. Elle dit
#: ce qui s'est passé **et** ce qu'on peut faire (L7.D) : « 401 » tout seul
#: n'a jamais renseigné personne.
MESSAGE_SANS_SESSION = (
    "aucune session ouverte — cette route sert des données personnelles, et ce "
    "serveur ne sait pas encore à qui elles appartiennent. La méthode de "
    "connexion n'est pas branchée sur ce déploiement ; pour servir un seul "
    "cycliste sur sa propre machine, lancer « ourouler api »."
)

#: Le code que le front teste, et qui est publié dans `erreurs.CODES_PANNE`.
CODE_SANS_SESSION = "session_absente"


__all__ = [
    "CODE_SANS_SESSION",
    "MESSAGE_SANS_SESSION",
    "MODES",
    "MODE_HEBERGE",
    "MODE_PERSONNEL",
    "FournisseurSession",
    "SessionHebergee",
    "SessionPersonnelle",
]
