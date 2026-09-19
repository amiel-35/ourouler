"""Le courriel d'invitation (lot L7.2-B) : composition et envoi contre un double SMTP.

Ce dossier coupe déjà tout accès réseau (`conftest.py`, règle absolue 3) : si l'un de ces
tests se mettait à ouvrir une vraie connexion — un oubli d'injection de `fabrique`, par
exemple — il échouerait bruyamment au lieu d'envoyer un courriel pour de vrai. C'est la
garantie de la règle absolue 4 du lot : rien d'ici n'envoie de courriel réel.

Adresses de test en `.invalid` uniquement (RFC 2606) — jamais un domaine réellement
enregistré, règle absolue 1 de CLAUDE.md.
"""

from __future__ import annotations

import smtplib
from datetime import UTC, datetime

import pytest

from ourouler.api.courriel import (
    ErreurCourriel,
    ParametresBrevo,
    envoyer_invitation,
    message_invitation,
    parametres_brevo_depuis_dict,
)

PARAMETRES = ParametresBrevo(
    serveur="smtp-relay.exemple.invalid",
    port=587,
    utilisateur="compte-smtp@exemple.invalid",
    mot_de_passe="xsmtpsib-jeton-de-test-jamais-reel",
    expediteur="ourouler@exemple.invalid",
    nom_expediteur="où rouler",
)

EXPIRE_LE = datetime(2026, 9, 22, 12, tzinfo=UTC)


class ClientSMTPDouble:
    """Le double injecté à la place de `smtplib.SMTP` — jamais de réseau (règle absolue 3)."""

    instances: list[ClientSMTPDouble] = []

    def __init__(self, serveur: str, port: int) -> None:
        self.serveur = serveur
        self.port = port
        self.starttls_appele = False
        self.identifiants: tuple[str, str] | None = None
        self.messages: list[object] = []
        ClientSMTPDouble.instances.append(self)

    def __enter__(self) -> ClientSMTPDouble:
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def starttls(self) -> None:
        self.starttls_appele = True

    def login(self, utilisateur: str, mot_de_passe: str) -> None:
        self.identifiants = (utilisateur, mot_de_passe)

    def send_message(self, message: object) -> None:
        self.messages.append(message)


class ClientSMTPQuiRefuse:
    """Simule un relais qui refuse l'authentification — panne réelle, mesurée en forme."""

    def __init__(self, serveur: str, port: int) -> None:
        pass

    def __enter__(self) -> ClientSMTPQuiRefuse:
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def starttls(self) -> None:
        pass

    def login(self, utilisateur: str, mot_de_passe: str) -> None:
        raise smtplib.SMTPAuthenticationError(535, b"authentification refusee")

    def send_message(self, message: object) -> None:  # pragma: no cover - jamais atteint
        raise AssertionError("send_message appelé alors que login a échoué")


@pytest.fixture(autouse=True)
def _vider_les_instances():
    ClientSMTPDouble.instances.clear()
    yield
    ClientSMTPDouble.instances.clear()


# --- ParametresBrevo ---------------------------------------------------------


def test_le_repr_de_parametres_brevo_masque_le_mot_de_passe():
    assert PARAMETRES.mot_de_passe not in repr(PARAMETRES)
    assert "mot_de_passe='***'" in repr(PARAMETRES)


def test_parametres_brevo_depuis_dict_accepte_une_section_complete():
    brut = {
        "brevo": {
            "serveur": "smtp-relay.exemple.invalid",
            "port": 587,
            "utilisateur": "compte@exemple.invalid",
            "mot_de_passe": "xsmtpsib-test",
            "expediteur": "ourouler@exemple.invalid",
            "nom_expediteur": "où rouler",
        }
    }
    parametres = parametres_brevo_depuis_dict(brut)
    assert parametres.port == 587
    assert parametres.serveur == "smtp-relay.exemple.invalid"


def test_parametres_brevo_depuis_dict_refuse_une_section_absente():
    with pytest.raises(ErreurCourriel) as refus:
        parametres_brevo_depuis_dict({})
    assert "[brevo] manquante" in str(refus.value)
    assert "Traceback" not in str(refus.value)


@pytest.mark.parametrize("champ_absent", ["serveur", "port", "utilisateur", "mot_de_passe", "expediteur"])
def test_parametres_brevo_depuis_dict_nomme_le_champ_manquant(champ_absent: str):
    """Un champ vide ou manquant donne un message lisible, jamais un `KeyError`."""
    section = {
        "serveur": "smtp-relay.exemple.invalid",
        "port": 587,
        "utilisateur": "compte@exemple.invalid",
        "mot_de_passe": "xsmtpsib-test",
        "expediteur": "ourouler@exemple.invalid",
        "nom_expediteur": "où rouler",
    }
    section[champ_absent] = ""
    with pytest.raises(ErreurCourriel) as refus:
        parametres_brevo_depuis_dict({"brevo": section})
    assert champ_absent in str(refus.value)
    assert "KeyError" not in str(refus.value)
    assert "Traceback" not in str(refus.value)


def test_parametres_brevo_depuis_dict_refuse_un_port_non_numerique():
    section = {
        "serveur": "smtp-relay.exemple.invalid",
        "port": "pas-un-port",
        "utilisateur": "compte@exemple.invalid",
        "mot_de_passe": "xsmtpsib-test",
        "expediteur": "ourouler@exemple.invalid",
        "nom_expediteur": "où rouler",
    }
    with pytest.raises(ErreurCourriel):
        parametres_brevo_depuis_dict({"brevo": section})


# --- message_invitation -------------------------------------------------------


def test_le_message_porte_le_lien_l_echeance_et_qui_invite():
    message = message_invitation(
        destinataire="cycliste@exemple.invalid",
        lien="https://ourouler.exemple.invalid/entrer?jeton=abc123",
        expire_le=EXPIRE_LE,
        parametres=PARAMETRES,
        invite_par="Amiel Lavon",
    )
    corps = message.get_content()
    assert "https://ourouler.exemple.invalid/entrer?jeton=abc123" in corps
    assert "22/09/2026" in corps
    assert "Amiel Lavon vous invite" in corps
    assert message["To"] == "cycliste@exemple.invalid"
    assert "où rouler" in message["From"]
    # Texte simple : pas de HTML, pas de pixel de suivi.
    assert not message.is_multipart()
    assert message.get_content_type() == "text/plain"


def test_le_message_sans_nom_d_invitant_reste_lisible():
    message = message_invitation(
        destinataire="cycliste@exemple.invalid",
        lien="https://ourouler.exemple.invalid/entrer?jeton=abc123",
        expire_le=EXPIRE_LE,
        parametres=PARAMETRES,
    )
    assert "vous êtes invité" in message.get_content().lower()


def test_une_adresse_qui_porte_un_saut_de_ligne_ne_produit_pas_d_en_tete_supplementaire():
    """Le garde-fou de `comptes.normaliser_email` refuse déjà ce cas en amont ; ce test
    prouve que le chemin d'envoi ne le contourne pas si, un jour, quelque chose l'appelle
    directement avec une adresse non passée par ce garde-fou.
    """
    hostile = "victime@exemple.invalid\nBcc: attaquant@exemple.invalid"
    with pytest.raises(ErreurCourriel):
        message_invitation(
            destinataire=hostile,
            lien="https://ourouler.exemple.invalid/entrer?jeton=abc123",
            expire_le=EXPIRE_LE,
            parametres=PARAMETRES,
        )


# --- envoyer_invitation --------------------------------------------------------


def test_envoyer_invitation_utilise_starttls_et_les_identifiants_fournis():
    message = message_invitation(
        destinataire="cycliste@exemple.invalid",
        lien="https://ourouler.exemple.invalid/entrer?jeton=abc123",
        expire_le=EXPIRE_LE,
        parametres=PARAMETRES,
    )
    envoyer_invitation(PARAMETRES, message, fabrique=ClientSMTPDouble)

    assert len(ClientSMTPDouble.instances) == 1
    client = ClientSMTPDouble.instances[0]
    assert (client.serveur, client.port) == (PARAMETRES.serveur, PARAMETRES.port)
    assert client.starttls_appele is True
    assert client.identifiants == (PARAMETRES.utilisateur, PARAMETRES.mot_de_passe)
    assert client.messages == [message]


def test_un_relais_qui_refuse_l_authentification_donne_un_message_lisible():
    message = message_invitation(
        destinataire="cycliste@exemple.invalid",
        lien="https://ourouler.exemple.invalid/entrer?jeton=abc123",
        expire_le=EXPIRE_LE,
        parametres=PARAMETRES,
    )
    with pytest.raises(ErreurCourriel) as refus:
        envoyer_invitation(PARAMETRES, message, fabrique=ClientSMTPQuiRefuse)
    assert "Traceback" not in str(refus.value)


def test_le_jeton_n_apparait_dans_aucun_journal(caplog):
    """Le jeton sort sur la sortie standard et dans le corps du courriel, nulle part ailleurs."""
    jeton = "jeton-de-test-tres-distinctif-9f8e7d"
    lien = f"https://ourouler.exemple.invalid/entrer?jeton={jeton}"
    with caplog.at_level("DEBUG"):
        message = message_invitation(
            destinataire="cycliste@exemple.invalid",
            lien=lien,
            expire_le=EXPIRE_LE,
            parametres=PARAMETRES,
        )
        envoyer_invitation(PARAMETRES, message, fabrique=ClientSMTPDouble)
    assert all(jeton not in enregistrement.getMessage() for enregistrement in caplog.records)
    # Et il est bien resté dans le corps du courriel, sinon ce test ne prouverait rien.
    assert jeton in message.get_content()
