"""Le courriel d'invitation : composition et envoi par SMTP standard, STARTTLS.

Doctrine §10.2 : **SMTP de la bibliothèque standard (`smtplib`), pas de
bibliothèque de fournisseur.** Brevo distribue une
clé dédiée à son relais SMTP — voir `service.example.toml`, section `[brevo]`
— et le protocole est assez standard pour qu'on change de prestataire en
éditant trois valeurs, sans réécrire ce module.

**Ce module ne lit ni fichier ni variable d'exécution** (le cœur ne lit ni
configuration ni environnement) : il
reçoit ses paramètres déjà résolus — `ParametresBrevo` — construits par
`cli.py` à partir du fichier de secrets du service. `tests/test_invariants.py`
vérifie que ce module n'a pas cette permission ; lui en écrire une reviendrait
à rouvrir la porte que la doctrine tient fermée.

Le client SMTP est **injectable** (`fabrique`) : les tests y passent un
double, jamais `smtplib.SMTP` pour de vrai. Ce module ne se connecte donc
lui-même à rien pendant les tests (pas de réseau dans les tests), et **aucun
test de ce dépôt n'envoie de courriel réel** : seul le service configuré, à
la demande de son exploitant, en envoie.
"""

from __future__ import annotations

import smtplib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from email.message import EmailMessage
from typing import Protocol

from ourouler.noyau.erreurs import ErreurUtilisateur


class ErreurCourriel(ErreurUtilisateur):
    """La section `[brevo]` du fichier de service manque ou est incomplète, ou l'envoi a échoué.

    Sous-classe d'`ErreurUtilisateur` : la CLI l'affiche en une ligne, code 2, sans trace.
    """


#: Les six champs attendus dans la section `[brevo]` — voir `service.example.toml`.
#: Nommés ici pour que le message d'erreur cite exactement ce qui manque, plutôt
#: qu'un `KeyError` sur le premier champ absent.
CHAMPS_REQUIS_BREVO = ("serveur", "port", "utilisateur", "mot_de_passe", "expediteur", "nom_expediteur")


@dataclass(frozen=True, repr=False)
class ParametresBrevo:
    """Les six champs de la section `[brevo]`, une fois validés. Le `repr` masque le mot de passe.

    Le « mot de passe » est la clé SMTP dédiée de Brevo (préfixe `xsmtpsib-`, distincte de
    la clé de son API REST) — elle n'est jamais utilisée telle quelle ici, elle est
    seulement transmise au client SMTP.
    """

    serveur: str
    port: int
    utilisateur: str
    mot_de_passe: str
    expediteur: str
    nom_expediteur: str

    def __repr__(self) -> str:
        secret = "***" if self.mot_de_passe else ""
        return (
            f"ParametresBrevo(serveur={self.serveur!r}, port={self.port!r}, "
            f"utilisateur={self.utilisateur!r}, mot_de_passe={secret!r}, "
            f"expediteur={self.expediteur!r}, nom_expediteur={self.nom_expediteur!r})"
        )


def parametres_brevo_depuis_dict(brut: dict) -> ParametresBrevo:
    """La section `[brevo]` d'un dictionnaire déjà lu, validée champ par champ.

    Lève `ErreurCourriel`, avec les champs manquants ou vides **nommés**, plutôt qu'un
    `KeyError` sur le premier accès. Ce n'est pas ici que le fichier s'ouvre — c'est
    `cli.py` qui le lit et qui appelle cette fonction avec le dictionnaire obtenu (règle
    absolue 2) : cette fonction-ci est pure, elle ne touche qu'à ce qu'on lui donne.
    """
    section = brut.get("brevo") if isinstance(brut, dict) else None
    if not isinstance(section, dict):
        raise ErreurCourriel(
            "section [brevo] manquante — copier service.example.toml vers "
            "~/.config/ourouler/service.toml (0600) et la renseigner"
        )
    manquants = [champ for champ in CHAMPS_REQUIS_BREVO if not str(section.get(champ, "")).strip()]
    if manquants:
        raise ErreurCourriel(
            "service.toml [brevo] incomplète — champ(s) manquant(s) ou vide(s) : "
            + ", ".join(manquants)
        )
    try:
        port = int(section["port"])
    except (TypeError, ValueError) as e:
        raise ErreurCourriel(
            f"service.toml [brevo] port : entier attendu, reçu {section['port']!r}"
        ) from e
    return ParametresBrevo(
        serveur=str(section["serveur"]),
        port=port,
        utilisateur=str(section["utilisateur"]),
        mot_de_passe=str(section["mot_de_passe"]),
        expediteur=str(section["expediteur"]),
        nom_expediteur=str(section["nom_expediteur"]),
    )


def message_invitation(
    *,
    destinataire: str,
    lien: str,
    expire_le: datetime,
    parametres: ParametresBrevo,
    invite_par: str = "",
) -> EmailMessage:
    """Compose le courriel d'invitation. Texte simple, français, court — pas de HTML, pas
    de pixel de suivi.

    Construit avec `email.message.EmailMessage`, **jamais par concaténation de chaînes** :
    c'est elle qui refuse un en-tête qui porterait un retour à la ligne, donc une adresse
    hostile qui aurait échappé à `comptes.normaliser_email` en amont ne peut pas glisser un
    en-tête de plus dans le message — elle fait échouer la composition à la place.
    """
    message = EmailMessage()
    message["Subject"] = "Invitation à où rouler"
    message["From"] = f"{parametres.nom_expediteur} <{parametres.expediteur}>"
    try:
        message["To"] = destinataire
    except ValueError as e:
        raise ErreurCourriel(f"adresse destinataire refusée par la composition du message : {e}") from e

    qui_invite = f"{invite_par} vous invite" if invite_par else "Vous êtes invité·e"
    echeance = expire_le.astimezone(UTC).strftime("%d/%m/%Y")
    message.set_content(
        "Bonjour,\n\n"
        f"{qui_invite} à rejoindre où rouler, un service de météo par direction et de "
        "tracé de parcours pour cyclistes.\n\n"
        f"Pour créer votre compte, ouvrez ce lien avant le {echeance} :\n"
        f"{lien}\n\n"
        "— où rouler\n"
    )
    return message


def message_reinitialisation(
    *,
    destinataire: str,
    lien: str,
    expire_le: datetime,
    parametres: ParametresBrevo,
) -> EmailMessage:
    """Compose le courriel de réinitialisation (`ourouler reinitialiser`).

    Même forme que `message_invitation` — texte simple, français, court, composé avec
    `EmailMessage` et non par concaténation (même garde-fou contre un en-tête hostile) —
    mais un texte différent : ce compte existe déjà, ce lien pose un nouveau mot de
    passe, il ne crée rien.
    """
    message = EmailMessage()
    message["Subject"] = "Nouveau mot de passe pour où rouler"
    message["From"] = f"{parametres.nom_expediteur} <{parametres.expediteur}>"
    try:
        message["To"] = destinataire
    except ValueError as e:
        raise ErreurCourriel(f"adresse destinataire refusée par la composition du message : {e}") from e

    echeance = expire_le.astimezone(UTC).strftime("%d/%m/%Y")
    message.set_content(
        "Bonjour,\n\n"
        "Une réinitialisation de mot de passe a été demandée pour votre compte où rouler.\n\n"
        f"Pour choisir un nouveau mot de passe, ouvrez ce lien avant le {echeance} :\n"
        f"{lien}\n\n"
        "Si vous n'êtes pas à l'origine de cette demande, ignorez ce message : votre mot "
        "de passe actuel reste valable tant que vous n'ouvrez pas ce lien.\n\n"
        "— où rouler\n"
    )
    return message


class ClientSMTP(Protocol):
    """Ce qu'un client SMTP doit savoir faire, pour être injecté ici ou doublé en test.

    `smtplib.SMTP` s'y conforme déjà (utilisé comme gestionnaire de contexte). Un double de
    test n'a besoin d'implémenter que ces cinq méthodes.
    """

    def __enter__(self) -> ClientSMTP: ...

    def __exit__(self, *exc: object) -> bool | None: ...

    def starttls(self) -> object: ...

    def login(self, utilisateur: str, mot_de_passe: str) -> object: ...

    def send_message(self, message: EmailMessage) -> object: ...


#: Une fabrique de client SMTP : `(serveur, port) -> ClientSMTP`. `smtplib.SMTP` en est une
#: par construction (son constructeur prend hôte et port). Injectable pour ne jamais
#: dépendre du réseau en test (pas de réseau dans les tests).
FabriqueSMTP = Callable[[str, int], ClientSMTP]


def envoyer_invitation(
    parametres: ParametresBrevo,
    message: EmailMessage,
    *,
    fabrique: FabriqueSMTP | None = None,
) -> None:
    """Remet `message` au relais SMTP décrit par `parametres`, en STARTTLS.

    `fabrique` par défaut vaut `smtplib.SMTP` — une vraie connexion — mais seulement si rien
    n'est injecté : les tests de ce dépôt lui passent toujours un double (pas de réseau dans
    les tests, aucun courriel réel envoyé d'ici).
    """
    fabrique_effective = fabrique or smtplib.SMTP
    try:
        with fabrique_effective(parametres.serveur, parametres.port) as client:
            client.starttls()
            client.login(parametres.utilisateur, parametres.mot_de_passe)
            client.send_message(message)
    except (smtplib.SMTPException, OSError) as e:
        raise ErreurCourriel(f"l'envoi du courriel d'invitation a échoué : {e}") from e


__all__ = [
    "CHAMPS_REQUIS_BREVO",
    "ClientSMTP",
    "ErreurCourriel",
    "FabriqueSMTP",
    "ParametresBrevo",
    "envoyer_invitation",
    "message_invitation",
    "message_reinitialisation",
    "parametres_brevo_depuis_dict",
]
