"""L'administration : file des demandes, comptes, invitations — jamais exposée sur Internet.

Sprint 12. QP6 (25/09/2026, tranchée (c)) : cette application n'écoute **que**
sur `127.0.0.1`, dans le conteneur — jamais dans `expose`/Traefik. On y entre
par un tunnel SSH puis `docker exec` (ou un port mappé sur la boucle locale de
l'hôte), voir `deploiement/api/README.md`. C'est une **seconde** application
FastAPI, distincte de celle que sert `api/application.py` : `tests/api/…`
prouve qu'aucune de ses routes n'existe dans l'application publique ni dans
son `openapi.json`.

**Authentification par un identifiant dédié** (`[admin]` de `service.toml`,
lu par `api/exploitation.py`), **pas un compte cycliste** — comparaison en
temps constant (`hmac.compare_digest`), comme le mot de passe d'un compte.
Session par cookie **distinct** (`NOM_COOKIE_ADMIN`), jamais confondu avec
`api.session.NOM_COOKIE`.

**CSRF.** Chaque page affichée porte un jeton, posé dans la session en
mémoire à l'ouverture ; chaque formulaire le reporte dans un champ caché, et
chaque route qui agit le revérifie avant d'agir. Sans bibliothèque : un seul
utilisateur, une session à la fois, un jeton aléatoire suffit.

**Cinq écrans, un seul gabarit HTML** (`_page`) : pas de nouvelle dépendance
(pas de Jinja) — le service tourne déjà avec assez de pièces mobiles.

## Les tâches de fond et les quotas du jour : une limite honnête

`api.taches_fond.occupant()` est un état du **processus** ; il n'est visible
que si cette application tourne **dans le même processus Python** que l'API
qu'elle administre — ce que fait `deploiement/api/entrypoint.py` quand
`[admin]` est configuré (voir sa docstring). Lancée seule (`ourouler admin`,
un second processus), les tâches de fond de l'API ne sont pas les siennes :
l'écran le dit plutôt que d'afficher un zéro trompeur. Même chose pour les
quotas, qui vivent dans le `Contexte` de l'API (`api/routes/commun.py`) :
cette application les affiche quand on lui en passe un (`quotas=`), sinon
elle le dit.
"""

from __future__ import annotations

import hmac
import html
import logging
import secrets
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from ourouler.api import base_de_donnees
from ourouler.api.comptes import Compte, DepotComptes
from ourouler.api.courriel import FabriqueSMTP, ParametresBrevo
from ourouler.api.demandes import DepotDemandes
from ourouler.api.exploitation import ParametresAdmin
from ourouler.noyau.erreurs import ErreurUtilisateur
from ourouler.services.demandes import accepter_demande, demandes_en_attente, refuser_demande

#: Le journal des **actions** d'administration — qui a accepté, refusé,
#: supprimé quoi, et quand ; qui s'est connecté, avec succès ou pas.
#: **Jamais une adresse, jamais un secret** : seuls des identifiants opaques
#: (`demande.id`, `compte.identifiant`, déjà des chaînes hexadécimales sans
#: signification) et le nom de l'action. Un incident sur ce journal ne doit
#: rien apprendre de plus qu'« une action a eu lieu ».
journal = logging.getLogger("ourouler.admin")

#: Le port par défaut de l'administration — jamais celui de l'API (8000) :
#: les deux ne doivent jamais pouvoir se confondre dans un réglage Coolify.
PORT_ADMIN_DEFAUT = 8001

#: Le cookie de session de l'administration — jamais `api.session.NOM_COOKIE`.
NOM_COOKIE_ADMIN = "ourouler_admin_session"

#: Une session d'administration dure moins longtemps qu'une session cycliste
#: (`comptes.DUREE_SESSION`, 30 jours) : ce n'est pas un usage quotidien,
#: c'est un geste ponctuel derrière un tunnel SSH.
DUREE_SESSION_ADMIN = timedelta(hours=12)


class ErreurAdmin(ErreurUtilisateur):
    """Un identifiant refusé, un CSRF absent ou faux — jamais montré en détail au navigateur."""


@dataclass
class _SessionAdmin:
    expire_le: datetime
    jeton_csrf: str


@dataclass
class _Sessions:
    """Les sessions d'administration, en mémoire — un seul processus, un seul admin."""

    _verrou: threading.Lock = field(default_factory=threading.Lock)
    _table: dict[str, _SessionAdmin] = field(default_factory=dict)

    def ouvrir(self) -> str:
        jeton = secrets.token_urlsafe(32)
        with self._verrou:
            self._table[jeton] = _SessionAdmin(
                expire_le=datetime.now(UTC) + DUREE_SESSION_ADMIN,
                jeton_csrf=secrets.token_urlsafe(32),
            )
        return jeton

    def valide(self, jeton: str | None) -> _SessionAdmin | None:
        if not jeton:
            return None
        with self._verrou:
            session = self._table.get(jeton)
            if session is None:
                return None
            if session.expire_le <= datetime.now(UTC):
                del self._table[jeton]
                return None
            return session

    def fermer(self, jeton: str | None) -> None:
        if not jeton:
            return
        with self._verrou:
            self._table.pop(jeton, None)

    def exiger(self, jeton: str | None) -> _SessionAdmin:
        session = self.valide(jeton)
        if session is None:
            raise ErreurAdmin("session d'administration absente ou expirée")
        return session

    def verifier_csrf(self, session: _SessionAdmin, jeton_recu: str) -> None:
        if not _constant_time_egal(session.jeton_csrf, jeton_recu or ""):
            raise ErreurAdmin("jeton CSRF absent ou invalide — recharger la page et réessayer")


@dataclass(frozen=True)
class ParametresApplicationAdmin:
    """Tout ce que `creer_application_admin` a besoin de recevoir déjà résolu.

    Un seul objet plutôt que huit paramètres : ce module ne lit lui-même ni
    fichier, ni variable d'environnement (le cœur ne lit ni configuration ni
    environnement) — `cli/admin.py` et `deploiement/api/entrypoint.py`
    rassemblent tout cela.
    """

    url_comptes: str
    identifiant: ParametresAdmin
    url_publique: str
    parametres_brevo: ParametresBrevo | None = None
    invite_par: str = ""
    dossier_config: Path | None = None
    #: `{libellé: Quotas}` du processus de l'API — voir la note de module.
    quotas: dict[str, object] | None = None
    #: Le client SMTP à injecter pour « Accepter » (`envoyer_invitation`,
    #: `api/courriel.py`) — `None` (le défaut) vaut `smtplib.SMTP`, une vraie
    #: connexion. Les tests de ce module y passent toujours un double : pas
    #: de réseau dans les tests, comme partout ailleurs dans ce dépôt.
    fabrique_smtp: FabriqueSMTP | None = None


def _constant_time_egal(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


def _masquer_email(email: str) -> str:
    """`cycliste@exemple.invalid` -> `c***e@exemple.invalid`."""
    utilisateur, _, domaine = email.partition("@")
    if len(utilisateur) <= 2:
        masque = utilisateur[:1] + "***"
    else:
        masque = utilisateur[0] + "***" + utilisateur[-1]
    return f"{masque}@{domaine}" if domaine else masque


# --- le gabarit HTML, sans nouvelle dépendance --------------------------------


def _page(titre: str, corps: str) -> HTMLResponse:
    """Une page HTML minimale — pas de Jinja, pas de front séparé pour cinq écrans."""
    contenu = f"""<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="robots" content="noindex, nofollow">
<title>{html.escape(titre)} — administration ourouler</title>
<style>
body {{ font-family: system-ui, sans-serif; margin: 2rem auto; max-width: 60rem; color: #1a1a1a; }}
h1 {{ font-size: 1.3rem; }}
h2 {{ font-size: 1.05rem; margin-top: 2rem; border-bottom: 1px solid #ccc; }}
table {{ width: 100%; border-collapse: collapse; margin: 0.5rem 0; }}
td, th {{ text-align: left; padding: 0.3rem 0.5rem; border-bottom: 1px solid #eee; }}
form.ligne {{ display: inline; }}
button {{ cursor: pointer; }}
.alerte {{ background: #fdecec; border: 1px solid #e0a0a0; padding: 0.5rem; }}
.vide {{ color: #777; font-style: italic; }}
</style>
</head>
<body>
<h1>{html.escape(titre)}</h1>
{corps}
</body>
</html>"""
    reponse = HTMLResponse(contenu)
    reponse.headers["Cache-Control"] = "no-store"
    # Cette application n'a aucune raison d'être chargée dans un `<iframe>` —
    # se protéger du clic-jacking coûte une ligne, même derrière un tunnel SSH.
    reponse.headers["X-Frame-Options"] = "DENY"
    return reponse


def _connexion_page(erreur: str | None = None) -> HTMLResponse:
    encart = f'<p class="alerte">{html.escape(erreur)}</p>' if erreur else ""
    corps = f"""
{encart}
<form method="post" action="/admin/connexion">
<p><label>Identifiant <input name="identifiant" autocomplete="username" required></label></p>
<p><label>Secret <input type="password" name="secret" autocomplete="current-password" required></label></p>
<p><button type="submit">Se connecter</button></p>
</form>"""
    return _page("Connexion", corps)


def _section_demandes(demandes, csrf: str) -> str:
    if not demandes:
        return '<p class="vide">Aucune demande en attente.</p>'
    lignes = "".join(
        f"<tr><td>{html.escape(d.email)}</td><td>{html.escape(d.message or '')}</td>"
        f"<td>{d.cree_le.astimezone(UTC).strftime('%d/%m/%Y %H:%M')} UTC</td>"
        f"<td>{_bouton('Accepter', f'/admin/demandes/{d.id}/accepter', csrf)} "
        f"{_bouton('Refuser', f'/admin/demandes/{d.id}/refuser', csrf)}</td></tr>"
        for d in demandes
    )
    return f"<table><tr><th>Adresse</th><th>Message</th><th>Déposée le</th><th></th></tr>{lignes}</table>"


def _section_invitations(invitations) -> str:
    if not invitations:
        return '<p class="vide">Aucune invitation en cours.</p>'
    lignes = "".join(
        f"<tr><td>{html.escape(_masquer_email(i.email))}</td>"
        f"<td>{i.expire_le.astimezone(UTC).strftime('%d/%m/%Y')}</td></tr>"
        for i in invitations
    )
    return f"<table><tr><th>Adresse</th><th>Expire le</th></tr>{lignes}</table>"


def _section_comptes(comptes, csrf: str) -> str:
    if not comptes:
        return '<p class="vide">Aucun compte actif.</p>'
    lignes = "".join(
        f"<tr><td>{html.escape(c.email)}</td>"
        f"<td>{c.cree_le.astimezone(UTC).strftime('%d/%m/%Y')}</td>"
        f"<td>{_bouton('Supprimer', f'/admin/comptes/{c.identifiant}/supprimer', csrf)}</td></tr>"
        for c in comptes
    )
    return f"<table><tr><th>Adresse</th><th>Créé le</th><th></th></tr>{lignes}</table>"


def _bouton(libelle: str, action: str, csrf: str) -> str:
    return (
        f'<form class="ligne" method="post" action="{html.escape(action)}">'
        f'<input type="hidden" name="csrf" value="{html.escape(csrf)}">'
        f'<button type="submit">{html.escape(libelle)}</button></form>'
    )


def _section_taches() -> str:
    from ourouler.api import taches_fond

    occupant = taches_fond.occupant()
    if occupant:
        return f"<p>Une tâche est en cours : <b>{html.escape(occupant)}</b>.</p>"
    return '<p class="vide">Aucune tâche de fond en cours.</p>'


def _section_quotas(quotas: dict[str, object] | None) -> str:
    if not quotas:
        return (
            '<p class="vide">Non disponible dans ce mode : les quotas vivent dans le '
            "processus de l'API — lancer l'administration intégrée à l'entrypoint pour "
            "les voir ici (voir deploiement/api/README.md).</p>"
        )
    lignes = "".join(
        f"<tr><td>{html.escape(libelle)}</td><td>{q.plafond}</td></tr>"  # type: ignore[attr-defined]
        for libelle, q in quotas.items()
    )
    return f"<table><tr><th>Poste</th><th>Plafond</th></tr>{lignes}</table>"


def _section_debit_global(quotas_fournis: bool) -> str:
    """Le plafond global du formulaire public, s'il est atteint aujourd'hui.

    **Visible seulement quand `quotas_fournis` est vrai** (l'administration
    tourne dans le même processus que l'API, voir `deploiement/api/entrypoint.py`)
    — sinon le compteur relu ici serait celui d'un processus qui n'a jamais vu
    le trafic public, et afficherait toujours « non atteint », à tort.
    """
    if not quotas_fournis:
        return ""
    from ourouler.api.routes import demandes as module_demandes

    if not module_demandes.debit_global_epuise():
        return ""
    return (
        '<p class="alerte">Le plafond global du formulaire public de demande d\'invitation '
        "est atteint aujourd'hui : les nouvelles demandes ne sont plus enregistrées, "
        "silencieusement, jusqu'à minuit UTC.</p>"
    )


def _corps_tableau_de_bord(
    session: _SessionAdmin, demandes, invitations, comptes, quotas, *, alerte: str | None = None
) -> str:
    csrf = session.jeton_csrf
    encart_alerte = f'<p class="alerte">{html.escape(alerte)}</p>' if alerte else ""
    return (
        f"{encart_alerte}"
        f"{_section_debit_global(quotas is not None)}"
        f"<h2>Demandes en attente</h2>{_section_demandes(demandes, csrf)}"
        f"<h2>Invitations en cours</h2>{_section_invitations(invitations)}"
        f"<h2>Comptes actifs</h2>{_section_comptes(comptes, csrf)}"
        f"<h2>Tâches de fond</h2>{_section_taches()}"
        f"<h2>Quotas du jour</h2>{_section_quotas(quotas)}"
        '<form method="post" action="/admin/deconnexion"><button type="submit">Se déconnecter</button></form>'
    )


def _page_confirmation_suppression(compte: Compte, csrf: str) -> HTMLResponse:
    action = f"/admin/comptes/{compte.identifiant}/supprimer"
    corps = f"""
<p class="alerte">Confirmez la suppression définitive du compte <b>{html.escape(compte.email)}</b>
— ses données personnelles seront effacées (même geste que « ourouler retirer »),
ce qui ne se défait pas.</p>
<form method="post" action="{html.escape(action)}">
<input type="hidden" name="csrf" value="{html.escape(csrf)}">
<input type="hidden" name="confirmation" value="oui">
<button type="submit">Confirmer la suppression</button>
</form>
<p><a href="/admin/">Annuler</a></p>"""
    return _page("Confirmer la suppression", corps)


def _effacer_donnees_admin(proprietaire, **kwargs):
    from ourouler.api import vie_privee

    return vie_privee.effacer_donnees(proprietaire, **kwargs)


def _depots_heberges(dossier_config: Path | None):
    """Reconstruit les dépôts du serveur hébergé — même construction que
    `cli.comptes._depots_de_l_hebergement`, dupliquée ici plutôt qu'importée :
    `api/` ne dépend jamais de `cli/` (les dépendances vont de `cli/` vers
    `api/`, jamais l'inverse — `ARCHITECTURE.md` §5).

    **À lancer dans le même conteneur, avec le même volume de données que
    l'API** — même mise en garde que pour `ourouler retirer`
    (`deploiement/api/README.md`) : refuse si le dossier de données attendu
    n'existe pas.
    """
    from ourouler.api import exploitation
    from ourouler.api.application import NOM_DOSSIER_DONNEES
    from ourouler.api.depots import DepotFichiers, DepotGenerations, DepotProfils, JournalServices, SocleTOML
    from ourouler.config import dossier_cache_depuis
    from ourouler.services.comptes import DepotsHeberges

    chemin = dossier_config if dossier_config is not None else exploitation.chemin_config()
    variables = exploitation.variables()
    socle = SocleTOML(chemin, variables=variables, proprietaire=None)
    dossier_cache = dossier_cache_depuis(exploitation.lire_toml(chemin))
    dossier_donnees = dossier_cache / NOM_DOSSIER_DONNEES
    if not dossier_donnees.is_dir():
        raise ErreurUtilisateur(
            f"administration : dossier de données introuvable ({dossier_donnees}) — cette "
            "application doit tourner dans le même conteneur que l'API, avec le même "
            "volume (voir deploiement/api/README.md)"
        )
    return DepotsHeberges(
        profils=DepotProfils(socle, dossier_donnees),
        fichiers=DepotFichiers(dossier_donnees),
        journal=JournalServices(dossier_donnees),
        generations=DepotGenerations(),
        dossier_cache=dossier_cache,
    )


def _supprimer_compte_reellement(depot: DepotComptes, compte: Compte, dossier_config: Path | None) -> None:
    """Le même chemin que `ourouler retirer` (`services.comptes.retirer`), RGPD compris."""
    from ourouler.services.comptes import retirer

    retirer(
        compte.email,
        depot=depot,
        confirmer=lambda _adresse: True,  # la double confirmation a déjà eu lieu dans l'écran
        resoudre_depots_heberges=lambda: _depots_heberges(dossier_config),
        effacer_donnees=_effacer_donnees_admin,
    )


# --- l'application ------------------------------------------------------------


def _montrer_authentification(
    app: FastAPI, sessions: _Sessions, parametres: ParametresApplicationAdmin
) -> None:
    """Les trois routes de session : connexion, déconnexion, et le refus commun."""

    @app.exception_handler(ErreurAdmin)
    async def _erreur_admin(requete: Request, erreur: ErreurAdmin) -> HTMLResponse:
        del requete
        reponse = _connexion_page(str(erreur))
        reponse.status_code = 403
        return reponse

    @app.get("/admin/connexion")
    def page_connexion(requete: Request):
        if sessions.valide(requete.cookies.get(NOM_COOKIE_ADMIN)) is not None:
            return RedirectResponse("/admin/", status_code=303)
        return _connexion_page()

    @app.post("/admin/connexion")
    def connexion(requete: Request, identifiant: str = Form(...), secret: str = Form(...)):
        del requete
        attendu = parametres.identifiant
        ok = _constant_time_egal(identifiant, attendu.identifiant) and _constant_time_egal(
            secret, attendu.secret
        )
        if not ok:
            journal.warning("connexion admin refusée")
            reponse = _connexion_page("identifiant ou secret refusés")
            reponse.status_code = 401
            return reponse
        journal.info("connexion admin réussie")
        jeton = sessions.ouvrir()
        reponse = RedirectResponse("/admin/", status_code=303)
        reponse.set_cookie(
            NOM_COOKIE_ADMIN,
            jeton,
            httponly=True,
            # **`secure=False`, volontairement.** Cette application n'est
            # jamais servie qu'en clair, sur la boucle locale
            # (`127.0.0.1`, jamais un nom de domaine ni TLS) — voir la
            # docstring de module et QP6. Un cookie `Secure` sur une origine
            # `http://` n'est tout simplement pas posé par certains
            # navigateurs (Safari, en particulier) : ça produirait une
            # boucle de connexion silencieuse plutôt qu'un risque réel, le
            # trafic ne quittant déjà jamais la machine (`docker exec`) ou
            # un tunnel SSH déjà chiffré (`deploiement/api/README.md`).
            secure=False,
            samesite="strict",
            path="/admin",
        )
        reponse.headers["Cache-Control"] = "no-store"
        return reponse

    @app.post("/admin/deconnexion")
    def deconnexion(requete: Request):
        sessions.fermer(requete.cookies.get(NOM_COOKIE_ADMIN))
        reponse = RedirectResponse("/admin/connexion", status_code=303)
        reponse.delete_cookie(NOM_COOKIE_ADMIN, path="/admin")
        return reponse


def creer_application_admin(parametres: ParametresApplicationAdmin) -> FastAPI:
    """L'application d'administration. **Ne monte aucune route sur `/api/v1`** —
    c'est une application à part, jamais fusionnée avec celle que sert
    `api/application.py`. Voir `ParametresApplicationAdmin` pour ce qu'elle reçoit.
    """
    app = FastAPI(title="administration ourouler", docs_url=None, redoc_url=None, openapi_url=None)
    sessions = _Sessions()
    _montrer_authentification(app, sessions, parametres)

    def _tableau_de_bord(session: _SessionAdmin, *, alerte: str | None = None) -> HTMLResponse:
        """Relit la file, les invitations et les comptes, et rend la page — avec un
        encart d'alerte facultatif (une action refusée, mais lisible, plutôt qu'un 500)."""
        with base_de_donnees.ouvrir(parametres.url_comptes) as cx:
            demandes = demandes_en_attente(depot=DepotDemandes(cx))
            invitations = DepotComptes(cx).invitations_en_cours()
            comptes = DepotComptes(cx).comptes_actifs()
        corps = _corps_tableau_de_bord(
            session, demandes, invitations, comptes, parametres.quotas, alerte=alerte
        )
        return _page("Administration ourouler", corps)

    @app.get("/admin/")
    def tableau_de_bord(requete: Request):
        session = sessions.exiger(requete.cookies.get(NOM_COOKIE_ADMIN))
        return _tableau_de_bord(session)

    @app.post("/admin/demandes/{identifiant}/accepter")
    def accepter(identifiant: str, requete: Request, csrf: str = Form(...)):
        session = sessions.exiger(requete.cookies.get(NOM_COOKIE_ADMIN))
        sessions.verifier_csrf(session, csrf)
        try:
            with base_de_donnees.ouvrir(parametres.url_comptes) as cx:
                accepter_demande(
                    identifiant,
                    depot_demandes=DepotDemandes(cx),
                    depot_comptes=DepotComptes(cx),
                    url_publique=parametres.url_publique,
                    parametres_brevo=parametres.parametres_brevo,
                    invite_par=parametres.invite_par,
                    fabrique_smtp=parametres.fabrique_smtp,
                )
        except ErreurUtilisateur as e:
            # **Un refus normal, pas un bug.** Une adresse déjà titulaire d'un compte
            # (`ErreurCompteExistant`, quelqu'un a demandé alors qu'il a déjà accès) ou un
            # relais SMTP en panne (`ErreurCourriel`) sont des refus **attendus** de
            # `services.comptes.inviter`/`envoyer_invitation`, pas des bugs de
            # l'administration — ils méritent un encart lisible, pas un 500.
            journal.warning("demande %s : acceptation refusée (%s)", identifiant, type(e).__name__)
            return _tableau_de_bord(session, alerte=str(e))
        journal.info("demande %s acceptée", identifiant)
        return RedirectResponse("/admin/", status_code=303)

    @app.post("/admin/demandes/{identifiant}/refuser")
    def refuser(identifiant: str, requete: Request, csrf: str = Form(...)):
        session = sessions.exiger(requete.cookies.get(NOM_COOKIE_ADMIN))
        sessions.verifier_csrf(session, csrf)
        with base_de_donnees.ouvrir(parametres.url_comptes) as cx:
            refuser_demande(identifiant, depot=DepotDemandes(cx))
        journal.info("demande %s refusée", identifiant)
        return RedirectResponse("/admin/", status_code=303)

    @app.post("/admin/comptes/{identifiant}/supprimer")
    def supprimer_compte(
        identifiant: str,
        requete: Request,
        csrf: str = Form(...),
        confirmation: str = Form(""),
    ):
        session = sessions.exiger(requete.cookies.get(NOM_COOKIE_ADMIN))
        sessions.verifier_csrf(session, csrf)
        try:
            with base_de_donnees.ouvrir(parametres.url_comptes) as cx:
                depot = DepotComptes(cx)
                compte = next((c for c in depot.comptes_actifs() if c.identifiant == identifiant), None)
                if compte is None:
                    return RedirectResponse("/admin/", status_code=303)
                if confirmation != "oui":
                    return _page_confirmation_suppression(compte, session.jeton_csrf)
                _supprimer_compte_reellement(depot, compte, parametres.dossier_config)
        except ErreurUtilisateur as e:
            journal.warning("compte %s : suppression refusée (%s)", identifiant, type(e).__name__)
            return _tableau_de_bord(session, alerte=str(e))
        journal.info("compte %s supprimé", identifiant)
        return RedirectResponse("/admin/", status_code=303)

    return app


__all__ = [
    "DUREE_SESSION_ADMIN",
    "NOM_COOKIE_ADMIN",
    "PORT_ADMIN_DEFAUT",
    "ErreurAdmin",
    "ParametresApplicationAdmin",
    "creer_application_admin",
]
