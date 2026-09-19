"""Qui est derrière la requête — sans jamais dire **comment** on l'a su.

Doctrine §10.2 : « Isolation des données : par utilisateur, vérifiée côté
serveur à chaque requête, jamais seulement côté front. **Aucune requête sans
clause de propriétaire.** »

`api/proprietaire.py` dit *à qui* appartient une ligne ; ce module-ci dit
*comment la requête en cours se rattache à quelqu'un*. Jusqu'au 18/09/2026
les deux étaient confondus : `resoudre()` rendait le propriétaire local, donc
une requête anonyme obtenait les données du mainteneur. La couture est ici.

**La méthode d'authentification a été tranchée le 19/09/2026** (lot L7.2-C) :
un compte, un mot de passe, une session par jeton opaque en base
(`api/comptes.py`, `migrations/0002_sessions.sql`). Ce fichier s'écrit alors
exactement comme la note ci-dessous l'annonçait — **une troisième classe, et
rien d'autre ne bouge** : `SessionParCookie` s'ajoute à côté de
`SessionPersonnelle` et `SessionHebergee`, qui restent inchangées.

## Deux produits, pas deux réglages

Un service qui sert **une** personne chez elle et un service qui en sert
**plusieurs** ne sont pas le même produit, et le code le nomme :

- `SessionPersonnelle` — `ourouler api` sur la machine du cycliste. Il n'y a
  qu'un utilisateur, la machine est la frontière de sécurité, et le
  propriétaire est toujours le même. C'est l'usage d'origine du projet et il
  ne meurt pas.
- `SessionHebergee` — un service exposé, mais sans base de comptes
  configurée (`OUROULER_DATABASE_URL` absente). Il n'ouvre **aucune**
  session : toute route de données répond 401. C'est le bon comportement, pas
  une régression — servir le profil du mainteneur à un inconnu serait pire
  qu'un refus.
- `SessionParCookie` — un service exposé, avec une base de comptes
  configurée. Un cookie porte un jeton opaque, retrouvé en base
  (`DepotComptes.proprietaire_de_la_session`) ; absent, inconnu ou expiré, il
  vaut `None` comme les deux autres cas où personne ne parle.

Ce qui a disparu avec le lot L7.A et ne revient pas : que le mode personnel
soit le **défaut implicite** d'un service exposé. Le mode se déclare
(`OUROULER_MODE`, lu par `api/exploitation.py` et par lui seul) ; en son
absence, le service refuse au lieu de deviner.

**Ce module ne connaît pas FastAPI**, mais la requête que `SessionParCookie`
reçoit en porte un (`starlette.requests.Request`, injecté par les routes) :
on y lit `requete.cookies`, un attribut que Starlette expose indépendamment
du reste du cadre. La ligne de commande continue d'importer ce fichier sans
l'extra `api` — `SessionPersonnelle` et `SessionHebergee` n'en ont toujours
pas besoin, et `SessionParCookie` ne construit sa connexion qu'à l'appel de
`ouvrir`, jamais à l'import du module.
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


#: Le nom du cookie qui porte le jeton de session. `HttpOnly` (un script du
#: front ne le lit jamais), `Secure` (jamais envoyé en clair), `SameSite=Lax`
#: (un lien externe peut encore ouvrir une page authentifiée ; un site tiers
#: ne peut pas déclencher, depuis chez lui, une requête qui s'en sert) — les
#: trois posés par `api/routes.py` au moment d'écrire le cookie, pas ici : ce
#: module ne connaît pas la forme d'une réponse HTTP.
NOM_COOKIE = "ourouler_session"


@dataclass(frozen=True)
class SessionParCookie:
    """Plusieurs cyclistes, une session par jeton opaque en base (lot L7.2-C).

    **La méthode d'authentification que la note de module annonçait.** Le
    cookie porte un jeton ; ce module le lit (`requete.cookies`, l'attribut
    que Starlette expose) et demande au dépôt des comptes à qui il
    appartient. `DepotComptes.proprietaire_de_la_session` rend `None` pour un
    jeton absent, inconnu ou expiré — les trois cas où « personne » est la
    seule réponse honnête, et `proprietaire()` (`api/routes.py`) les traduit
    tous en 401 de la même façon.

    **Une connexion par appel, pas de réserve tenue ouverte.** Chaque
    `ouvrir()` se connecte à la base, pose sa question, referme. C'est le
    choix le plus simple pour un service qui n'a encore qu'une poignée de
    cyclistes ([[CLAUDE.md]] : « 50 lignes évidentes valent mieux que 20
    lignes malignes ») ; un bassin de connexions est un problème à résoudre
    quand le trafic le demandera, pas avant.
    """

    #: L'URL du PostgreSQL des comptes — lue une fois par `api/exploitation.py`
    #: (règle absolue 2) et portée ici telle quelle. Ce module ne la relit
    #: jamais dans l'environnement.
    url: str

    #: Sans annotation, comme pour les deux autres classes : une constante de
    #: classe, pas un champ de la dataclass.
    mode = MODE_HEBERGE

    def ouvrir(self, requete: object) -> Proprietaire | None:
        jeton = getattr(requete, "cookies", {}).get(NOM_COOKIE)
        if not jeton:
            return None
        # Importés ici, et non en tête de module : `comptes.py` importe
        # `psycopg`, et rien n'oblige la ligne de commande à le tirer pour
        # construire une `SessionPersonnelle` ou une `SessionHebergee`.
        from ourouler.api import base_de_donnees
        from ourouler.api.comptes import DepotComptes

        with base_de_donnees.ouvrir(self.url) as connexion:
            return DepotComptes(connexion).proprietaire_de_la_session(jeton)


#: La phrase rendue au cycliste quand aucune session n'est ouverte. Elle dit
#: ce qui s'est passé **et** ce qu'on peut faire (L7.D) : « 401 » tout seul
#: n'a jamais renseigné personne.
#:
#: **Reformulée le 19/09/2026 (lot L7.2-C).** Elle disait « la méthode de
#: connexion n'est pas branchée sur ce déploiement », vrai tant que
#: `SessionHebergee` était la seule issue d'un service exposé. Ce n'est plus
#: toujours vrai : un cookie absent, inconnu ou expiré vaut aussi `None` chez
#: `SessionParCookie`, sur un déploiement où la connexion, elle, est bien
#: branchée. La phrase ne présume donc plus de la raison et donne les deux
#: gestes possibles.
MESSAGE_SANS_SESSION = (
    "aucune session ouverte — cette route sert des données personnelles, et ce "
    "serveur ne sait pas encore à qui elles appartiennent. Se connecter "
    "(POST /api/v1/connexion) ou activer son invitation (POST /api/v1/entrer) ; "
    "pour servir un seul cycliste sur sa propre machine, lancer « ourouler api »."
)

#: Le code que le front teste, et qui est publié dans `erreurs.CODES_PANNE`.
CODE_SANS_SESSION = "session_absente"


__all__ = [
    "CODE_SANS_SESSION",
    "MESSAGE_SANS_SESSION",
    "MODES",
    "MODE_HEBERGE",
    "MODE_PERSONNEL",
    "NOM_COOKIE",
    "FournisseurSession",
    "SessionHebergee",
    "SessionParCookie",
    "SessionPersonnelle",
]
