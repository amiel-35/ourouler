"""`POST /demandes-invitation` : le formulaire public — sans compte, sans session.

Sprint 12. Doctrine §10.2 (révisée le 26/09/2026) : le formulaire public de
demande d'invitation est autorisé, mais il ne crée jamais de compte ni
d'invitation — voir `services/demandes.py` et `api/admin.py` (la modération).

**Cette route précède toute session**, exactement comme `/entrer` et
`/connexion` (`api/routes/sessions.py`) : elle n'a pas de clause de
propriétaire à respecter puisqu'elle n'en a pas encore. Même exemption dans
`tests/api/test_api_isolation_proprietaire.py` (`ROUTES_AVANT_SESSION`).

**La réponse est identique dans tous les cas** — adresse déjà titulaire d'un
compte, invitation déjà en cours, adresse inconnue, honeypot rempli, débit
dépassé : `{"donnees": {}}`, 200, toujours. C'est la seule façon de ne rien
apprendre à qui dépose une demande. En conséquence, cette route ne peut
jamais faire remonter `comptes_indisponibles` par un mécanisme visible —
quand ce déploiement n'a pas de base de comptes configurée, elle rend la
même réponse sans avoir rien enregistré, plutôt qu'un refus qui décrirait
l'infrastructure du serveur.
"""

from __future__ import annotations

import logging

from fastapi import Request

from ourouler.api import base_de_donnees, exploitation
from ourouler.api.demandes import CLE_GLOBALE, DepotDemandes, LimiteAnonyme
from ourouler.api.modeles import DemandeInvitationPublique
from ourouler.api.routes.commun import Ctx, nouveau_routeur
from ourouler.api.session import SessionParCookie
from ourouler.services.demandes import deposer_demande

routeur = nouveau_routeur()

journal = logging.getLogger("ourouler.demandes")

#: Les deux compteurs de débit, en mémoire du processus — voir
#: `api.demandes.LimiteAnonyme`. Des objets de **module**, comme
#: `api/taches_fond.VERROU` : un seul processus sert ce formulaire (même
#: doctrine que `api/quotas.py`), et un test qui veut un compteur vierge
#: réimporte le module ou avance l'horloge plutôt que de les reconstruire.
#:
#: Le plafond se lit une fois, à l'import du module (`[demandes]` de
#: `service.toml`, `api/exploitation.py`) : c'est le même choix que
#: `Quotas`, dont le plafond est fixé à la construction du `Contexte` par
#: `application()`, pas relu à chaque requête.
_LIMITE_PAR_IP = LimiteAnonyme(plafond=exploitation.demandes_par_ip_par_jour())
_LIMITE_GLOBALE = LimiteAnonyme(plafond=exploitation.demandes_global_par_jour())


def debit_global_epuise() -> bool:
    """Vrai si le plafond global du formulaire public est atteint aujourd'hui.

    Lue par l'administration (`api/admin.py`) pour l'afficher sur le tableau
    de bord — seulement visible quand l'administration tourne dans le même
    processus que l'API (voir la note sur les quotas et tâches de fond,
    `api/admin.py`), puisque ce compteur, comme les autres, vit en mémoire
    d'un seul processus.
    """
    return _LIMITE_GLOBALE.epuise(CLE_GLOBALE)


#: La réponse rendue dans tous les cas — succès, honeypot rempli, débit
#: dépassé, base absente. Une constante plutôt qu'une valeur recalculée à
#: chaque branche : c'est ce qui rend visible, à la lecture, qu'aucune
#: branche ne dit jamais autre chose.
_REPONSE = {"donnees": {}}


def _adresse_ip(requete: Request) -> str:
    """L'adresse IP du client, pour le débit — jamais enregistrée en base (voir
    `api/demandes.py`, note de module).
    """
    client = requete.client
    return client.host if client is not None else "inconnue"


@routeur.post("/demandes-invitation")
def demander_invitation(ctx: Ctx, corps: DemandeInvitationPublique, requete: Request) -> dict:
    """Dépose une demande d'invitation. Toujours 200, toujours la même réponse.

    Quatre raisons de **ne rien enregistrer**, silencieusement, dans l'ordre où
    elles sont vérifiées (la moins chère d'abord) :

    1. le honeypot est rempli (`corps.piege`) — un humain ne le remplit jamais ;
    2. le débit par adresse IP est dépassé ;
    3. le débit global est dépassé ;
    4. ce déploiement n'a pas de base de comptes configurée — il n'y a nulle
       part où ranger la demande.

    Dans les quatre cas comme dans le succès, la réponse est `_REPONSE` : rien ne
    distingue, de l'extérieur, un formulaire rempli par un robot d'un formulaire
    accepté.
    """
    if corps.piege.strip():
        journal.info("demande d'invitation ignorée : champ honeypot rempli")
        return _REPONSE

    ip = _adresse_ip(requete)
    if not _LIMITE_PAR_IP.autorise(ip):
        journal.info("demande d'invitation ignorée : débit par adresse IP dépassé")
        return _REPONSE
    if not _LIMITE_GLOBALE.autorise(CLE_GLOBALE):
        journal.warning("demande d'invitation ignorée : débit global du formulaire dépassé")
        return _REPONSE

    session = ctx.session
    if not isinstance(session, SessionParCookie):
        journal.info("demande d'invitation ignorée : aucune base de comptes configurée")
        return _REPONSE

    try:
        with base_de_donnees.ouvrir(session.url) as cx:
            depot = DepotDemandes(cx)
            deposer_demande(
                corps.adresse,
                corps.message,
                depot=depot,
                destinataire_alerte=exploitation.adresse_alerte_demandes(),
                parametres_brevo=exploitation.parametres_brevo_service(),
            )
    except Exception as e:  # noqa: BLE001 — toute panne (adresse mal formée, alerte en échec,
        # base injoignable) reste **interne** : la réponse ne doit jamais varier
        # selon ce qui a raté, sans quoi elle redeviendrait un oracle.
        #
        # **Jamais `journal.exception` ici** : elle imprimerait la trace, et
        # `ErreurCompte` (`normaliser_email`) porte l'adresse **saisie** dans
        # son message (`repr(brut)`) — l'écrire au journal ferait fuiter
        # l'adresse d'un formulaire public dans les logs du serveur, la
        # fuite même que ce module existe pour refuser. Seul le nom du type
        # d'exception est journalisé, jamais son message ni sa trace.
        journal.warning("demande d'invitation non enregistrée (%s)", type(e).__name__)
    return _REPONSE
