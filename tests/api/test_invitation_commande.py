"""`ourouler inviter` / `ourouler invitations` : l'orchestration, contre un dépôt en double.

Ce module (`api/invitation_commande.py`) ne parle jamais à PostgreSQL directement — il
reçoit un dépôt déjà ouvert. On le teste donc ici contre un **double** de `DepotComptes`,
sans base réelle : ce qui se joue à cette base-là — la course entre deux invitations
concurrentes, l'atomicité de l'activation — est déjà couvert par `tests/comptes/`
(`DepotComptes.inviter`, `.activer`, `.invitations_en_cours`) ; le câblage complet, avec une
vraie base, est couvert par `tests/comptes/test_cli_inviter.py`. Ici, on prouve seulement ce
que ce module ajoute : l'affichage, `--sans-courriel`, et l'appel — ou non — au client SMTP.

Ce dossier coupe le réseau (`conftest.py`) : un double SMTP qui laisserait passer un vrai
`smtplib.SMTP` ferait échouer bruyamment, pas silencieusement.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime, timedelta

import pytest

from ourouler.api.comptes import ErreurCompteExistant, Invitation, InvitationEmise
from ourouler.api.courriel import ParametresBrevo
from ourouler.cli import executer_invitations, executer_inviter
from ourouler.config import Config, Cycliste, Depart
from ourouler.services.comptes import construire_lien

PARAMETRES_BREVO = ParametresBrevo(
    serveur="smtp-relay.exemple.invalid",
    port=587,
    utilisateur="compte@exemple.invalid",
    mot_de_passe="xsmtpsib-test",
    expediteur="ourouler@exemple.invalid",
    nom_expediteur="où rouler",
)

MAINTENANT = datetime(2026, 9, 19, 8, 0, tzinfo=UTC)


def config_avec_nom(prenom: str = "Amiel", nom: str = "Lavon") -> Config:
    return Config(
        depart=Depart(nom="Départ", latitude=48.0, longitude=2.0),
        cycliste=Cycliste(masse_kg=75.0, ftp_w=250.0, prenom=prenom, nom=nom),
    )


def namespace(adresse: str = "cycliste@exemple.invalid", *, sans_courriel=False, json_=False):
    return argparse.Namespace(adresse=adresse, sans_courriel=sans_courriel, json=json_)


def emise(*, jeton="jeton-de-test", deja_en_cours=False, expire_dans=timedelta(days=3)):
    invitation = Invitation(
        jeton=jeton,
        compte="compte-de-test",
        cree_le=MAINTENANT,
        expire_le=MAINTENANT + expire_dans,
        consomme_le=None,
    )
    return InvitationEmise(invitation=invitation, jeton=jeton, deja_en_cours=deja_en_cours)


class DepotDouble:
    """Un double de `DepotComptes` : pas de base, juste ce que ce module lui demande."""

    def __init__(self, *, rendu: InvitationEmise | Exception, invitations=()):
        self.rendu = rendu
        self._invitations = list(invitations)
        self.adresses_invitees: list[str] = []

    def inviter(self, adresse: str) -> InvitationEmise:
        self.adresses_invitees.append(adresse)
        if isinstance(self.rendu, Exception):
            raise self.rendu
        return self.rendu

    def invitations_en_cours(self):
        return list(self._invitations)


class FabriqueSMTPDouble:
    """Un double de fabrique SMTP qui enregistre ce qu'il reçoit — jamais de réseau."""

    def __init__(self):
        self.appels: list[object] = []

    def __call__(self, serveur: str, port: int):
        self.appels.append((serveur, port))
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def starttls(self):
        pass

    def login(self, utilisateur, mot_de_passe):
        pass

    def send_message(self, message):
        self.appels.append(("send_message", message))


def fabrique_qui_explose(serveur: str, port: int):
    raise AssertionError(
        f"le client SMTP n'aurait pas dû être fabriqué (serveur={serveur!r}, port={port!r})"
    )


# --- ourouler inviter ----------------------------------------------------------


def test_le_lien_s_affiche_meme_quand_le_courriel_part(capsys):
    """Décision explicite du mainteneur : le lien est toujours affiché, envoi ou pas."""
    depot = DepotDouble(rendu=emise())
    fabrique = FabriqueSMTPDouble()

    code = executer_inviter(
        namespace(),
        config_avec_nom(),
        depot=depot,
        url_publique="https://ourouler.exemple.invalid",
        parametres_brevo=PARAMETRES_BREVO,
        fabrique_smtp=fabrique,
    )

    assert code == 0
    sortie = capsys.readouterr().out
    assert "https://ourouler.exemple.invalid/entrer?jeton=jeton-de-test" in sortie
    assert "courriel envoyé" in sortie
    # Et le courriel est bien parti, via le double.
    assert ("send_message", None) not in fabrique.appels  # sanity : pas de faux positif idiot
    assert any(appel == (PARAMETRES_BREVO.serveur, PARAMETRES_BREVO.port) for appel in fabrique.appels)


def test_sans_courriel_n_appelle_pas_le_client_smtp(capsys):
    depot = DepotDouble(rendu=emise())

    code = executer_inviter(
        namespace(sans_courriel=True),
        config_avec_nom(),
        depot=depot,
        url_publique="https://ourouler.exemple.invalid",
        parametres_brevo=None,
        fabrique_smtp=fabrique_qui_explose,
    )

    assert code == 0
    sortie = capsys.readouterr().out
    assert "https://ourouler.exemple.invalid/entrer?jeton=jeton-de-test" in sortie
    assert "courriel non envoyé" in sortie


def test_une_invitation_reprise_affiche_le_meme_jeton_et_le_dit(capsys):
    depot = DepotDouble(rendu=emise(jeton="jeton-deja-emis", deja_en_cours=True))

    executer_inviter(
        namespace(sans_courriel=True),
        config_avec_nom(),
        depot=depot,
        url_publique="https://ourouler.exemple.invalid",
        parametres_brevo=None,
    )

    sortie = capsys.readouterr().out
    assert "jeton=jeton-deja-emis" in sortie
    assert "déjà en cours" in sortie


def test_un_compte_actif_fait_echouer_la_commande_avec_le_bon_message():
    """La logique d'état vit dans `DepotComptes.inviter` (lot L7.2-A) ; ce module la laisse
    remonter telle quelle, il ne la redécide pas."""
    refus = ErreurCompteExistant("cycliste@exemple.invalid a déjà un compte, ouvert le 01/01/2026")
    depot = DepotDouble(rendu=refus)

    with pytest.raises(ErreurCompteExistant) as leve:
        executer_inviter(
            namespace(sans_courriel=True),
            config_avec_nom(),
            depot=depot,
            url_publique="https://ourouler.exemple.invalid",
            parametres_brevo=None,
        )
    assert "déjà un compte" in str(leve.value)
    assert "Traceback" not in str(leve.value)


def test_la_sortie_json_porte_le_lien_l_echeance_et_l_etat(capsys):
    depot = DepotDouble(rendu=emise(jeton="jeton-json", deja_en_cours=False))

    executer_inviter(
        namespace(sans_courriel=True, json_=True),
        config_avec_nom(),
        depot=depot,
        url_publique="https://ourouler.exemple.invalid/",  # barre finale : doit être absorbée
        parametres_brevo=None,
    )

    sortie = json.loads(capsys.readouterr().out)
    assert sortie["lien"] == "https://ourouler.exemple.invalid/entrer?jeton=jeton-json"
    assert sortie["deja_en_cours"] is False
    assert sortie["courriel_envoye"] is False


def test_qui_invite_vient_du_prenom_et_nom_du_cycliste_qui_lance_la_commande():
    depot = DepotDouble(rendu=emise())
    fabrique = FabriqueSMTPDouble()

    executer_inviter(
        namespace(),
        config_avec_nom(prenom="Amiel", nom="Lavon"),
        depot=depot,
        url_publique="https://ourouler.exemple.invalid",
        parametres_brevo=PARAMETRES_BREVO,
        fabrique_smtp=fabrique,
    )

    messages = [
        appel[1] for appel in fabrique.appels if isinstance(appel, tuple) and appel[0] == "send_message"
    ]
    assert len(messages) == 1
    assert "Amiel Lavon vous invite" in messages[0].get_content()


def test_le_jeton_n_apparait_dans_aucun_journal(caplog):
    depot = DepotDouble(rendu=emise(jeton="jeton-tres-distinctif-a1b2c3"))
    with caplog.at_level("DEBUG"):
        executer_inviter(
            namespace(sans_courriel=True),
            config_avec_nom(),
            depot=depot,
            url_publique="https://ourouler.exemple.invalid",
            parametres_brevo=None,
        )
    assert all("jeton-tres-distinctif-a1b2c3" not in e.getMessage() for e in caplog.records)


def test_construire_lien_absorbe_la_barre_finale_de_l_url_publique():
    assert (
        construire_lien("https://ourouler.exemple.invalid/", "abc")
        == "https://ourouler.exemple.invalid/entrer?jeton=abc"
    )
    assert (
        construire_lien("https://ourouler.exemple.invalid", "abc")
        == "https://ourouler.exemple.invalid/entrer?jeton=abc"
    )


# --- ourouler invitations -------------------------------------------------------


def test_invitations_liste_adresse_lien_et_echeance(capsys):
    from ourouler.api.comptes import InvitationAvecAdresse

    invitations = [
        InvitationAvecAdresse(
            jeton="jeton-a",
            email="a@exemple.invalid",
            cree_le=MAINTENANT,
            expire_le=MAINTENANT + timedelta(days=3),
        ),
        InvitationAvecAdresse(
            jeton="jeton-b",
            email="b@exemple.invalid",
            cree_le=MAINTENANT,
            expire_le=MAINTENANT + timedelta(days=1),
        ),
    ]
    depot = DepotDouble(rendu=emise(), invitations=invitations)

    code = executer_invitations(
        namespace(), config_avec_nom(), depot=depot, url_publique="https://ourouler.exemple.invalid"
    )

    assert code == 0
    sortie = capsys.readouterr().out
    assert "a@exemple.invalid — https://ourouler.exemple.invalid/entrer?jeton=jeton-a" in sortie
    assert "b@exemple.invalid — https://ourouler.exemple.invalid/entrer?jeton=jeton-b" in sortie


def test_invitations_json():
    from ourouler.api.comptes import InvitationAvecAdresse

    invitations = [
        InvitationAvecAdresse(
            jeton="jeton-a",
            email="a@exemple.invalid",
            cree_le=MAINTENANT,
            expire_le=MAINTENANT + timedelta(days=3),
        ),
    ]
    depot = DepotDouble(rendu=emise(), invitations=invitations)

    import io
    from contextlib import redirect_stdout

    tampon = io.StringIO()
    with redirect_stdout(tampon):
        executer_invitations(
            namespace(json_=True),
            config_avec_nom(),
            depot=depot,
            url_publique="https://ourouler.exemple.invalid",
        )
    sortie = json.loads(tampon.getvalue())
    assert sortie == [
        {
            "adresse": "a@exemple.invalid",
            "lien": "https://ourouler.exemple.invalid/entrer?jeton=jeton-a",
            "expire_le": (MAINTENANT + timedelta(days=3)).isoformat(),
        }
    ]


def test_invitations_vide_le_dit_sans_planter(capsys):
    depot = DepotDouble(rendu=emise(), invitations=[])
    code = executer_invitations(
        namespace(), config_avec_nom(), depot=depot, url_publique="https://ourouler.exemple.invalid"
    )
    assert code == 0
    assert "aucune invitation" in capsys.readouterr().out
