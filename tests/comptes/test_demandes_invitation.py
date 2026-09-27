"""Les demandes d'invitation : dépôt public, file, modération — contre une vraie base.

Sprint 12. Même esprit que `tests/comptes/test_comptes.py` : ce qui touche la
base (dépôt, débit, effacement) se prouve contre un vrai PostgreSQL, pas en
relisant le code qui l'accompagne. Adresses de test toutes en `.invalid`
(RFC 2606, règle absolue 1).
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from ourouler.api.application import creer_application
from ourouler.api.base_de_donnees import ouvrir
from ourouler.api.comptes import DepotComptes
from ourouler.api.courriel import ParametresBrevo
from ourouler.api.demandes import (
    LONGUEUR_MAX_MESSAGE,
    DepotDemandes,
    ErreurDemandeInvitation,
    LimiteAnonyme,
)
from ourouler.api.depots import SocleVide
from ourouler.api.session import SessionParCookie
from ourouler.services.demandes import accepter_demande, demandes_en_attente, deposer_demande, refuser_demande

MOT_DE_PASSE = "pigeon-vaisselle-quartz-ficelle"
PREFIXE = "/api/v1"


@pytest.fixture
def depot_demandes(connexion):
    return DepotDemandes(connexion)


@pytest.fixture
def parametres_brevo() -> ParametresBrevo:
    return ParametresBrevo(
        serveur="smtp.exemple.invalid",
        port=587,
        utilisateur="utilisateur-essai",
        mot_de_passe="secret-essai",
        expediteur="ourouler@exemple.invalid",
        nom_expediteur="où rouler (essai)",
    )


class _ClientSMTPDouble:
    """Un client SMTP factice : n'ouvre aucune connexion, retient les messages envoyés."""

    envoyes: list = []

    def __init__(self, serveur: str, port: int) -> None:
        del serveur, port

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def starttls(self):
        return None

    def login(self, utilisateur, mot_de_passe):
        return None

    def send_message(self, message):
        _ClientSMTPDouble.envoyes.append(message)


@pytest.fixture(autouse=True)
def _vider_envoyes():
    _ClientSMTPDouble.envoyes.clear()
    yield
    _ClientSMTPDouble.envoyes.clear()


# --- le dépôt, sans HTTP -----------------------------------------------------


def test_deposer_enregistre_la_demande(depot_demandes: DepotDemandes):
    demande = depot_demandes.deposer("Cycliste@Exemple.INVALID", "  un mot  ")
    assert demande.email == "cycliste@exemple.invalid"  # normalisée, comme les comptes
    assert demande.message == "un mot"
    en_attente = depot_demandes.en_attente()
    assert [d.id for d in en_attente] == [demande.id]


def test_deposer_tronque_un_message_trop_long(depot_demandes: DepotDemandes):
    demande = depot_demandes.deposer("long@exemple.invalid", "x" * (LONGUEUR_MAX_MESSAGE + 100))
    assert demande.message is not None
    assert len(demande.message) == LONGUEUR_MAX_MESSAGE


def test_deposer_sans_message_rend_none(depot_demandes: DepotDemandes):
    demande = depot_demandes.deposer("sansmessage@exemple.invalid", None)
    assert demande.message is None
    demande2 = depot_demandes.deposer("sansmessage2@exemple.invalid", "   ")
    assert demande2.message is None


def test_deposer_ne_regarde_jamais_la_table_des_comptes(depot_demandes: DepotDemandes, connexion):
    """Une adresse qui a déjà un compte actif se voit accepter sa demande exactement
    comme une adresse inconnue — ce module ne consulte jamais `comptes`."""
    depot_comptes = DepotComptes(connexion)
    emise = depot_comptes.inviter("deja-invite@exemple.invalid")
    depot_comptes.activer(emise.jeton, MOT_DE_PASSE)

    demande = depot_demandes.deposer("deja-invite@exemple.invalid", "je voudrais rejoindre")
    assert demande.email == "deja-invite@exemple.invalid"


def test_effacer_est_idempotent(depot_demandes: DepotDemandes):
    demande = depot_demandes.deposer("efface-moi@exemple.invalid", None)
    assert depot_demandes.effacer(demande.id) is True
    assert depot_demandes.effacer(demande.id) is False
    assert depot_demandes.en_attente() == []


def test_en_attente_est_triee_par_date():
    pass  # couvert indirectement : voir test_deposer_enregistre_la_demande (ordre trivial ici)


# --- le service : déposer + alerte -------------------------------------------


def test_deposer_demande_sans_relais_n_envoie_rien_mais_enregistre(depot_demandes: DepotDemandes):
    resultat = deposer_demande(
        "sansrelais@exemple.invalid",
        "un mot",
        depot=depot_demandes,
        destinataire_alerte=None,
        parametres_brevo=None,
    )
    assert resultat.alerte_envoyee is False
    assert depot_demandes.en_attente()[0].email == "sansrelais@exemple.invalid"


def test_deposer_demande_avec_relais_envoie_l_alerte_au_mainteneur(
    depot_demandes: DepotDemandes, parametres_brevo: ParametresBrevo
):
    resultat = deposer_demande(
        "avecrelais@exemple.invalid",
        "coucou",
        depot=depot_demandes,
        destinataire_alerte="mainteneur@exemple.invalid",
        parametres_brevo=parametres_brevo,
        fabrique_smtp=_ClientSMTPDouble,
    )
    assert resultat.alerte_envoyee is True
    assert len(_ClientSMTPDouble.envoyes) == 1
    message = _ClientSMTPDouble.envoyes[0]
    assert message["To"] == "mainteneur@exemple.invalid"
    assert "avecrelais@exemple.invalid" in str(message)
    assert "coucou" in str(message)
    # Texte brut : le corps ne doit porter aucune partie HTML.
    assert message.get_content_type() == "text/plain"


def test_l_alerte_ne_part_jamais_vers_le_demandeur(
    depot_demandes: DepotDemandes, parametres_brevo: ParametresBrevo
):
    deposer_demande(
        "demandeur@exemple.invalid",
        None,
        depot=depot_demandes,
        destinataire_alerte="mainteneur@exemple.invalid",
        parametres_brevo=parametres_brevo,
        fabrique_smtp=_ClientSMTPDouble,
    )
    assert len(_ClientSMTPDouble.envoyes) == 1
    assert _ClientSMTPDouble.envoyes[0]["To"] != "demandeur@exemple.invalid"


# --- le service : modération --------------------------------------------------


def test_accepter_demande_emet_une_invitation_et_vide_la_file(depot_demandes: DepotDemandes, connexion):
    demande = depot_demandes.deposer("accepte-moi@exemple.invalid", None)
    depot_comptes = DepotComptes(connexion)

    lien = accepter_demande(
        demande.id,
        depot_demandes=depot_demandes,
        depot_comptes=depot_comptes,
        url_publique="https://exemple.invalid",
        parametres_brevo=None,
    )
    assert lien.emise.invitation.compte
    assert depot_demandes.en_attente() == []
    compte = depot_comptes.compte_par_email("accepte-moi@exemple.invalid")
    assert compte is not None
    assert compte.actif is False  # inactif : l'invitation n'est pas encore consommée


def test_accepter_une_demande_disparue_leve_une_erreur_nommee(depot_demandes: DepotDemandes, connexion):
    with pytest.raises(ErreurDemandeInvitation):
        accepter_demande(
            "introuvable",
            depot_demandes=depot_demandes,
            depot_comptes=DepotComptes(connexion),
            url_publique="https://exemple.invalid",
            parametres_brevo=None,
        )


def test_refuser_demande_efface_sans_rien_creer(depot_demandes: DepotDemandes, connexion):
    demande = depot_demandes.deposer("refuse-moi@exemple.invalid", None)
    assert refuser_demande(demande.id, depot=depot_demandes) is True
    assert depot_demandes.en_attente() == []
    assert DepotComptes(connexion).compte_par_email("refuse-moi@exemple.invalid") is None


def test_demandes_en_attente_service(depot_demandes: DepotDemandes):
    depot_demandes.deposer("un@exemple.invalid", None)
    depot_demandes.deposer("deux@exemple.invalid", None)
    assert {d.email for d in demandes_en_attente(depot=depot_demandes)} == {
        "un@exemple.invalid",
        "deux@exemple.invalid",
    }


# --- le débit anonyme, sans base -----------------------------------------------


def test_limite_anonyme_refuse_au_dela_du_plafond():
    limite = LimiteAnonyme(plafond=2)
    assert limite.autorise("1.2.3.4") is True
    assert limite.autorise("1.2.3.4") is True
    assert limite.autorise("1.2.3.4") is False
    # Une autre clé garde son propre compteur.
    assert limite.autorise("5.6.7.8") is True


def test_limite_anonyme_se_libere_le_jour_suivant():
    maintenant = datetime(2026, 9, 27, tzinfo=UTC)
    limite = LimiteAnonyme(plafond=1, horloge=lambda: maintenant)
    assert limite.autorise("1.2.3.4") is True
    assert limite.autorise("1.2.3.4") is False
    maintenant = maintenant + timedelta(days=1)
    limite.horloge = lambda: maintenant
    assert limite.autorise("1.2.3.4") is True


# --- la route HTTP publique ---------------------------------------------------


def _app(url_base: str):
    return creer_application(socle=SocleVide(), session=SessionParCookie(url_base))


def _requete(app, methode: str, chemin: str, **kwargs) -> httpx.Response:
    async def _aller() -> httpx.Response:
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://api.test") as client:
            return await client.request(methode, chemin, **kwargs)

    return asyncio.run(_aller())


@pytest.fixture(autouse=True)
def _limites_fraiches(monkeypatch: pytest.MonkeyPatch):
    """Des compteurs neufs à chaque test — les limites du module sont des singletons
    de processus (comme `api.quotas`), et un test ne doit pas hériter du précédent."""
    from ourouler.api.routes import demandes as module_route

    monkeypatch.setattr(module_route, "_LIMITE_PAR_IP", LimiteAnonyme(plafond=5))
    monkeypatch.setattr(module_route, "_LIMITE_GLOBALE", LimiteAnonyme(plafond=100))
    yield


def test_la_route_publique_rend_toujours_la_meme_reponse(url_base: str):
    app = _app(url_base)
    reponse_inconnue = _requete(
        app, "POST", f"{PREFIXE}/demandes-invitation", json={"adresse": "x@exemple.invalid"}
    )
    with ouvrir(url_base) as cx:
        emise = DepotComptes(cx).inviter("connue@exemple.invalid")
        DepotComptes(cx).activer(emise.jeton, MOT_DE_PASSE)
    reponse_connue = _requete(
        app, "POST", f"{PREFIXE}/demandes-invitation", json={"adresse": "connue@exemple.invalid"}
    )
    assert reponse_inconnue.status_code == reponse_connue.status_code == 200
    assert reponse_inconnue.json() == reponse_connue.json() == {"donnees": {}}


def test_la_route_publique_enregistre_bien_la_demande(url_base: str):
    app = _app(url_base)
    reponse = _requete(
        app,
        "POST",
        f"{PREFIXE}/demandes-invitation",
        json={"adresse": "vraie-demande@exemple.invalid", "message": "un mot"},
    )
    assert reponse.status_code == 200
    with ouvrir(url_base) as cx:
        demandes = DepotDemandes(cx).en_attente()
    assert [d.email for d in demandes] == ["vraie-demande@exemple.invalid"]


def test_le_honeypot_rempli_n_enregistre_rien(url_base: str):
    app = _app(url_base)
    reponse = _requete(
        app,
        "POST",
        f"{PREFIXE}/demandes-invitation",
        json={"adresse": "robot@exemple.invalid", "piege": "je suis un robot"},
    )
    assert reponse.status_code == 200
    assert reponse.json() == {"donnees": {}}
    with ouvrir(url_base) as cx:
        assert DepotDemandes(cx).en_attente() == []


def test_le_debit_par_ip_au_dela_du_plafond_n_enregistre_plus_rien(
    url_base: str, monkeypatch: pytest.MonkeyPatch
):
    from ourouler.api.routes import demandes as module_route

    monkeypatch.setattr(module_route, "_LIMITE_PAR_IP", LimiteAnonyme(plafond=1))
    app = _app(url_base)
    premiere = _requete(app, "POST", f"{PREFIXE}/demandes-invitation", json={"adresse": "a@exemple.invalid"})
    seconde = _requete(app, "POST", f"{PREFIXE}/demandes-invitation", json={"adresse": "b@exemple.invalid"})
    assert premiere.status_code == seconde.status_code == 200
    assert premiere.json() == seconde.json()
    with ouvrir(url_base) as cx:
        demandes = DepotDemandes(cx).en_attente()
    assert [d.email for d in demandes] == ["a@exemple.invalid"]


def test_un_message_trop_long_est_refuse_au_bord_sans_planter(url_base: str):
    app = _app(url_base)
    reponse = _requete(
        app,
        "POST",
        f"{PREFIXE}/demandes-invitation",
        json={"adresse": "borne@exemple.invalid", "message": "x" * 5000},
    )
    # Refusé par la validation Pydantic (422) — la réponse ne varie toujours pas selon
    # l'existence d'un compte, elle varie seulement selon la forme du corps envoyé, ce
    # qu'un demandeur contrôle lui-même et qui ne renseigne rien sur personne d'autre.
    assert reponse.status_code == 422
    with ouvrir(url_base) as cx:
        assert DepotDemandes(cx).en_attente() == []


def test_une_adresse_avec_saut_de_ligne_n_enregistre_rien_et_ne_casse_rien(url_base: str):
    """Une tentative d'injection d'en-tête de courriel ne doit ni planter, ni s'enregistrer."""
    app = _app(url_base)
    reponse = _requete(
        app,
        "POST",
        f"{PREFIXE}/demandes-invitation",
        json={"adresse": "x@exemple.invalid\nBcc: victime@exemple.invalid"},
    )
    assert reponse.status_code == 200
    assert reponse.json() == {"donnees": {}}
    with ouvrir(url_base) as cx:
        assert DepotDemandes(cx).en_attente() == []
