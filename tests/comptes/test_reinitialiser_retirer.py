"""`DepotComptes.reinitialiser` et consorts : le trou que `inviter` laisse ouvert (lot L9.6).

Un compte **actif** qui a perdu son mot de passe n'a, avant ce lot, aucun moyen d'en
poser un autre — `inviter` refuse explicitement les comptes actifs. Ces tests prouvent,
contre une vraie base PostgreSQL jetable (`tests/comptes/conftest.py`), que le mécanisme
de réinitialisation réutilise bien celui de l'invitation (même table, même garantie
d'usage unique) plutôt que d'en inventer un second, et que la consommation du jeton ferme
bien toutes les sessions déjà ouvertes — pas avant.

Adresses de test en `.invalid` uniquement (RFC 2606, règle absolue 1).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from ourouler.api.comptes import (
    DepotComptes,
    ErreurCompte,
    ErreurInvitationRefusee,
    ErreurMotDePasseActuelRefuse,
    verifier_mot_de_passe,
)

MOT_DE_PASSE = "grenat-poulie-silex-marmotte"
NOUVEAU_MOT_DE_PASSE = "corbeau-lentille-etain-marmotte"


def _compte_actif(depot: DepotComptes, adresse: str) -> str:
    """Invite puis active `adresse` — rend l'identifiant du compte."""
    emise = depot.inviter(adresse)
    acces = depot.activer(emise.jeton, MOT_DE_PASSE)
    return acces.compte.identifiant


# --- reinitialiser : émettre le lien ----------------------------------------


def test_reinitialiser_refuse_une_adresse_sans_compte(depot: DepotComptes):
    with pytest.raises(ErreurCompte) as refus:
        depot.reinitialiser("inconnue@exemple.invalid")
    assert "n'a pas de compte" in str(refus.value)


def test_reinitialiser_refuse_un_compte_invite_mais_pas_encore_actif(depot: DepotComptes):
    depot.inviter("jamais-active@exemple.invalid")
    with pytest.raises(ErreurCompte) as refus:
        depot.reinitialiser("jamais-active@exemple.invalid")
    assert "pas encore de compte actif" in str(refus.value)


def test_reinitialiser_emet_un_lien_pour_un_compte_actif(depot: DepotComptes, connexion):
    identifiant = _compte_actif(depot, "actif@exemple.invalid")
    emise = depot.reinitialiser("actif@exemple.invalid")
    assert emise.jeton and not emise.deja_en_cours
    assert emise.invitation.compte == identifiant

    # C'est bien la même table, pas un second mécanisme.
    ligne = connexion.execute(
        "SELECT compte FROM invitations WHERE jeton = %s", (emise.jeton,)
    ).fetchone()
    assert ligne == (identifiant,)


def test_reinitialiser_deux_fois_de_suite_reprend_le_meme_jeton(depot: DepotComptes):
    _compte_actif(depot, "relance@exemple.invalid")
    premiere = depot.reinitialiser("relance@exemple.invalid")
    seconde = depot.reinitialiser("relance@exemple.invalid")
    assert seconde.deja_en_cours
    assert seconde.jeton == premiere.jeton


def test_reinitialiser_une_invitation_expiree_se_remplace(depot: DepotComptes):
    depart = datetime(2026, 9, 1, 12, tzinfo=UTC)
    _compte_actif(depot, "expire@exemple.invalid")
    ancienne = depot.reinitialiser("expire@exemple.invalid", duree=timedelta(days=1), maintenant=depart)
    neuve = depot.reinitialiser("expire@exemple.invalid", maintenant=depart + timedelta(days=10))
    assert not neuve.deja_en_cours
    assert neuve.jeton != ancienne.jeton


# --- changer_mot_de_passe_par_jeton : consommer le lien ---------------------


def test_reinitialisation_pose_le_nouveau_secret_sans_toucher_actif_ni_proprietaire(
    depot: DepotComptes, connexion
):
    identifiant = _compte_actif(depot, "consomme@exemple.invalid")
    proprietaire_avant = depot.proprietaire_du_compte(identifiant)
    emise = depot.reinitialiser("consomme@exemple.invalid")

    acces = depot.changer_mot_de_passe_par_jeton(emise.jeton, NOUVEAU_MOT_DE_PASSE)

    assert acces.compte.identifiant == identifiant
    assert acces.compte.actif is True
    assert acces.proprietaire == proprietaire_avant

    secret = connexion.execute(
        "SELECT secret FROM comptes WHERE id = %s", (identifiant,)
    ).fetchone()[0]
    assert verifier_mot_de_passe(NOUVEAU_MOT_DE_PASSE, secret)
    assert not verifier_mot_de_passe(MOT_DE_PASSE, secret), "l'ancien mot de passe ne doit plus valoir"

    # comptes_proprietaires n'a pas gagné de seconde ligne pour ce compte.
    total = connexion.execute(
        "SELECT count(*) FROM comptes_proprietaires WHERE compte = %s", (identifiant,)
    ).fetchone()[0]
    assert total == 1


def test_reinitialisation_ferme_les_sessions_ouvertes_a_la_consommation_pas_avant(
    depot: DepotComptes, connexion
):
    """Le cœur du contrat : un lien émis ne déconnecte personne tant qu'il n'est pas ouvert."""
    identifiant = _compte_actif(depot, "sessions@exemple.invalid")
    jeton_session_a = depot.ouvrir_session(identifiant)
    jeton_session_b = depot.ouvrir_session(identifiant)

    emise = depot.reinitialiser("sessions@exemple.invalid")

    # Le lien est émis, mais pas encore ouvert : les deux sessions valent encore.
    assert depot.proprietaire_de_la_session(jeton_session_a) is not None
    assert depot.proprietaire_de_la_session(jeton_session_b) is not None

    depot.changer_mot_de_passe_par_jeton(emise.jeton, NOUVEAU_MOT_DE_PASSE)

    # La consommation du jeton a fermé les deux sessions déjà ouvertes.
    assert depot.proprietaire_de_la_session(jeton_session_a) is None
    assert depot.proprietaire_de_la_session(jeton_session_b) is None
    restantes = connexion.execute(
        "SELECT count(*) FROM sessions WHERE compte = %s", (identifiant,)
    ).fetchone()[0]
    assert restantes == 0


def test_deux_consommations_du_meme_jeton_de_reinitialisation_la_seconde_est_refusee(
    depot: DepotComptes,
):
    _compte_actif(depot, "rejoue@exemple.invalid")
    emise = depot.reinitialiser("rejoue@exemple.invalid")

    depot.changer_mot_de_passe_par_jeton(emise.jeton, NOUVEAU_MOT_DE_PASSE)
    with pytest.raises(ErreurInvitationRefusee) as refus:
        depot.changer_mot_de_passe_par_jeton(emise.jeton, "un-troisieme-mot-de-passe-tout-aussi-correct")
    assert "déjà servi" in str(refus.value)
    assert emise.jeton not in str(refus.value)


def test_un_jeton_de_reinitialisation_expire_est_refuse(depot: DepotComptes):
    depart = datetime(2026, 9, 1, 12, tzinfo=UTC)
    _compte_actif(depot, "perime@exemple.invalid")
    emise = depot.reinitialiser("perime@exemple.invalid", duree=timedelta(days=3), maintenant=depart)
    with pytest.raises(ErreurInvitationRefusee) as refus:
        depot.changer_mot_de_passe_par_jeton(
            emise.jeton, NOUVEAU_MOT_DE_PASSE, maintenant=depart + timedelta(days=4)
        )
    assert "expiré" in str(refus.value)


# --- changer_mot_de_passe : sous session ouverte, l'ancien vérifié ----------


def test_changer_mot_de_passe_verifie_l_ancien_et_ne_ferme_pas_les_autres_sessions(
    depot: DepotComptes, connexion
):
    identifiant = _compte_actif(depot, "session-ouverte@exemple.invalid")
    jeton_session = depot.ouvrir_session(identifiant)

    depot.changer_mot_de_passe(identifiant, MOT_DE_PASSE, NOUVEAU_MOT_DE_PASSE)

    secret = connexion.execute(
        "SELECT secret FROM comptes WHERE id = %s", (identifiant,)
    ).fetchone()[0]
    assert verifier_mot_de_passe(NOUVEAU_MOT_DE_PASSE, secret)
    # La session qui a servi à prouver l'ancien mot de passe reste ouverte :
    # rien ne la rend caduque, à la différence de la réinitialisation par jeton.
    assert depot.proprietaire_de_la_session(jeton_session) is not None


def test_changer_mot_de_passe_refuse_si_l_ancien_est_faux(depot: DepotComptes, connexion):
    identifiant = _compte_actif(depot, "mauvais-ancien@exemple.invalid")
    with pytest.raises(ErreurMotDePasseActuelRefuse):
        depot.changer_mot_de_passe(identifiant, "un-mot-de-passe-invente", NOUVEAU_MOT_DE_PASSE)
    secret = connexion.execute(
        "SELECT secret FROM comptes WHERE id = %s", (identifiant,)
    ).fetchone()[0]
    assert verifier_mot_de_passe(MOT_DE_PASSE, secret), "l'ancien mot de passe doit rester valable"


# --- retrouver un compte -----------------------------------------------------


def test_compte_par_email_et_compte_du_proprietaire(depot: DepotComptes):
    identifiant = _compte_actif(depot, "retrouve@exemple.invalid")
    proprietaire = depot.proprietaire_du_compte(identifiant)

    compte = depot.compte_par_email("Retrouve@Exemple.INVALID")
    assert compte is not None
    assert compte.identifiant == identifiant

    retrouve = depot.compte_du_proprietaire(proprietaire)
    assert retrouve is not None
    assert retrouve.identifiant == identifiant


def test_compte_par_email_rend_none_si_l_adresse_n_a_pas_de_compte(depot: DepotComptes):
    assert depot.compte_par_email("personne@exemple.invalid") is None


# --- fermer_sessions_du_compte, appelable seule -----------------------------


def test_fermer_sessions_du_compte_les_ferme_toutes_et_rend_le_compte(depot: DepotComptes):
    identifiant = _compte_actif(depot, "toutes-fermees@exemple.invalid")
    a = depot.ouvrir_session(identifiant)
    b = depot.ouvrir_session(identifiant)

    assert depot.fermer_sessions_du_compte(identifiant) == 2
    assert depot.proprietaire_de_la_session(a) is None
    assert depot.proprietaire_de_la_session(b) is None
    # Idempotente : rien à fermer une seconde fois.
    assert depot.fermer_sessions_du_compte(identifiant) == 0
