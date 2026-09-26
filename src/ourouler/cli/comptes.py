"""Les commandes de l'exploitant : `inviter`, `invitations`, `reinitialiser`, `retirer`."""

from __future__ import annotations

import argparse
import os
import sys
import tomllib
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ourouler.cli.options import parent_json
from ourouler.config import Config
from ourouler.noyau.erreurs import ErreurUtilisateur

if TYPE_CHECKING:
    # Imports réservés à l'analyse statique (annotations des adaptateurs de comptes) :
    # `services/comptes.py` tire le pilote PostgreSQL, un extra ; ce module doit
    # rester importable sans lui (règle du paquet : une sous-commande absente ou
    # cassée ne doit pas empêcher les autres de tourner).
    from ourouler.api.comptes import DepotComptes
    from ourouler.api.courriel import FabriqueSMTP, ParametresBrevo
    from ourouler.services.comptes import DepotsHeberges


# --- inviter -------------------------------------------------------------------
#
# Cette commande fait tourner le socle des comptes (`api/comptes.py`) depuis
# la ligne de commande de l'exploitant — c'est lui, et lui seul, qui invite.
# Elle a besoin de trois choses que seul `cli/` a le droit de lire (le cœur ne
# lit ni configuration ni environnement) : l'URL de la base PostgreSQL de
# l'hébergé, l'URL publique devant laquelle le lien
# s'ouvre, et — sauf `--sans-courriel` — les secrets du relais SMTP. Le reste
# (inviter, composer et envoyer le courriel) est délégué à `services/comptes.py`,
# et l'affichage à `rendu/comptes.py`, qui ne lisent rien eux-mêmes :
# `tests/test_invariants.py` le vérifie. Les fonctions `executer_*` ci-dessous
# sont les adaptateurs : options argparse et configuration en entrée, texte ou
# JSON sur la sortie standard.

#: Où vivent les secrets du *service* (Brevo…), distincts du profil cycliste
#: de `config.toml` — voir `service.example.toml`. Même statut que
#: `CHEMIN_CONFIG_DEFAUT` : un défaut, réglable par test.
CHEMIN_SERVICE_DEFAUT = Path("~/.config/ourouler/service.toml")

#: La variable qui déplace ce fichier, pour un déploiement où « chez soi »
#: n'existe pas. Le conteneur n'a pas de `~` qui veuille dire quelque chose :
#: `deploiement/api/entrypoint.py` y écrit le fichier depuis
#: `OUROULER_SERVICE_TOML_B64` et pose cette variable-ci pour dire où.
VARIABLE_SERVICE = "OUROULER_SERVICE"

#: L'URL publique du front hébergé, devant laquelle `/entrer?jeton=...`
#: s'ouvre — une donnée de déploiement, au même titre que celles que
#: `api/exploitation.py` lit pour le processus de l'API (`OUROULER_DATABASE_URL`,
#: `OUROULER_MODE`…). Celle-ci n'appartient pas au processus serveur : c'est le
#: l'exploitant, depuis sa propre ligne de commande, qui la pose dans son
#: environnement le temps d'inviter quelqu'un.
VARIABLE_URL_PUBLIQUE = "OUROULER_URL_PUBLIQUE"


def ajouter_inviter(sous: argparse._SubParsersAction) -> None:
    p = sous.add_parser(
        "inviter",
        help="invite une adresse à rejoindre où rouler (compte hébergé + courriel)",
        parents=[parent_json()],
    )
    p.add_argument("adresse", help="adresse e-mail à inviter")
    p.add_argument(
        "--sans-courriel",
        dest="sans_courriel",
        action="store_true",
        help="n'envoie pas le courriel d'invitation, affiche seulement le lien",
    )
    p.set_defaults(fonction=_commande_inviter, requiert_profil=False)


def _commande_inviter(args: argparse.Namespace, config: Config) -> int:
    from ourouler.api.comptes import DepotComptes
    from ourouler.api.courriel import parametres_brevo_depuis_dict

    url_db = _url_des_comptes("inviter")
    url_pub = _url_publique()

    parametres_brevo = None
    if not getattr(args, "sans_courriel", False):
        parametres_brevo = parametres_brevo_depuis_dict(_charger_service())

    with _base_des_comptes("inviter", url_db) as connexion:
        depot = DepotComptes(connexion)
        return executer_inviter(
            args, config, depot=depot, url_publique=url_pub, parametres_brevo=parametres_brevo
        )


def ajouter_invitations(sous: argparse._SubParsersAction) -> None:
    p = sous.add_parser(
        "invitations",
        help="liste les invitations en cours : adresse, lien, échéance",
        parents=[parent_json()],
    )
    p.set_defaults(fonction=_commande_invitations, requiert_profil=False)


def _commande_invitations(args: argparse.Namespace, config: Config) -> int:
    from ourouler.api.comptes import DepotComptes

    url_db = _url_des_comptes("invitations")
    url_pub = _url_publique()

    with _base_des_comptes("invitations", url_db) as connexion:
        depot = DepotComptes(connexion)
        return executer_invitations(args, config, depot=depot, url_publique=url_pub)


def _nom_complet(config: Config) -> str:
    """« Prénom Nom » du cycliste qui invite (celui qui a lancé la commande), ou une chaîne vide.

    Une configuration qui ne porte ni l'un ni l'autre donne un e-mail qui dit
    « vous êtes invité·e », sans inventer de nom (aucune donnée personnelle
    dans le dépôt).
    """
    return " ".join(morceau for morceau in (config.cycliste.prenom, config.cycliste.nom) if morceau)


def executer_inviter(
    args: argparse.Namespace,
    config: Config,
    *,
    depot: DepotComptes,
    url_publique: str,
    parametres_brevo: ParametresBrevo | None,
    fabrique_smtp: FabriqueSMTP | None = None,
) -> int:
    """`ourouler inviter ADRESSE` : le service `inviter`, puis son affichage. Code 0.

    Un refus du dépôt (compte déjà actif, adresse invalide) remonte tel quel :
    `main()` l'affiche en une ligne, code 2, sans trace.
    """
    from ourouler.rendu.comptes import json_lien_emis, texte_lien_emis
    from ourouler.services.comptes import inviter

    resultat = inviter(
        args.adresse,
        depot=depot,
        url_publique=url_publique,
        sans_courriel=getattr(args, "sans_courriel", False),
        parametres_brevo=parametres_brevo,
        invite_par=_nom_complet(config),
        fabrique_smtp=fabrique_smtp,
    )
    print(json_lien_emis(resultat) if getattr(args, "json", False) else texte_lien_emis(resultat))
    return 0


def executer_invitations(
    args: argparse.Namespace,
    config: Config,
    *,
    depot: DepotComptes,
    url_publique: str,
) -> int:
    """`ourouler invitations` : les invitations en cours, adresse et lien compris. Code 0."""
    from ourouler.rendu.comptes import json_invitations, texte_invitations
    from ourouler.services.comptes import invitations_en_cours

    del config  # non utilisé ici, gardé pour la même signature que les autres sous-commandes
    invitations = invitations_en_cours(depot=depot, url_publique=url_publique)
    print(json_invitations(invitations) if getattr(args, "json", False) else texte_invitations(invitations))
    return 0


# --- reinitialiser -------------------------------------------------------------
#
# Le trou que `inviter` laisse volontairement ouvert : un compte **actif** qui a
# perdu son mot de passe. Même patron que `inviter` — mêmes secrets `service.toml`,
# même base de comptes, `--sans-courriel` pour n'afficher que le lien — voir
# `api/comptes.py` (note de module de `reinitialiser`) pour le détail du mécanisme
# réutilisé (même table `invitations`, même jeton à usage unique).
#
# **Aucune route HTTP n'appelle ceci.** Réservée à la ligne de commande de
# l'exploitant — un « mot de passe oublié » en libre-service ouvrirait un relais de
# spam (poster une adresse au hasard fait partir un courriel) et un oracle
# d'énumération d'adresses (la réponse dirait si l'adresse a un compte). Voir
# `deploiement/api/README.md`.


def ajouter_reinitialiser(sous: argparse._SubParsersAction) -> None:
    p = sous.add_parser(
        "reinitialiser",
        help="émet un lien de nouveau mot de passe pour un compte déjà actif (hébergé)",
        parents=[parent_json()],
    )
    p.add_argument("adresse", help="adresse e-mail du compte déjà actif")
    p.add_argument(
        "--sans-courriel",
        dest="sans_courriel",
        action="store_true",
        help="n'envoie pas le courriel de réinitialisation, affiche seulement le lien",
    )
    p.set_defaults(fonction=_commande_reinitialiser, requiert_profil=False)


def _commande_reinitialiser(args: argparse.Namespace, config: Config) -> int:
    from ourouler.api.comptes import DepotComptes
    from ourouler.api.courriel import parametres_brevo_depuis_dict

    url_db = _url_des_comptes("reinitialiser")
    url_pub = _url_publique()

    parametres_brevo = None
    if not getattr(args, "sans_courriel", False):
        parametres_brevo = parametres_brevo_depuis_dict(_charger_service())

    with _base_des_comptes("reinitialiser", url_db) as connexion:
        depot = DepotComptes(connexion)
        return executer_reinitialiser(
            args, config, depot=depot, url_publique=url_pub, parametres_brevo=parametres_brevo
        )


def executer_reinitialiser(
    args: argparse.Namespace,
    config: Config,
    *,
    depot: DepotComptes,
    url_publique: str,
    parametres_brevo: ParametresBrevo | None,
    fabrique_smtp: FabriqueSMTP | None = None,
) -> int:
    """`ourouler reinitialiser ADRESSE` : le service `reinitialiser`, puis son affichage. Code 0."""
    from ourouler.rendu.comptes import json_lien_emis, texte_lien_emis
    from ourouler.services.comptes import reinitialiser

    del config  # non utilisé : pas de « X vous invite » sur un lien de réinitialisation
    resultat = reinitialiser(
        args.adresse,
        depot=depot,
        url_publique=url_publique,
        sans_courriel=getattr(args, "sans_courriel", False),
        parametres_brevo=parametres_brevo,
        fabrique_smtp=fabrique_smtp,
    )
    print(json_lien_emis(resultat) if getattr(args, "json", False) else texte_lien_emis(resultat))
    return 0


# --- retirer -------------------------------------------------------------------
#
# Ferme un compte, ses sessions, son invitation, et efface ses données
# personnelles — le même chemin que `DELETE /moi` (`api/routes/`), jamais une
# réimplémentation : `services/comptes.retirer` appelle `vie_privee.effacer_donnees`
# telle quelle. Cette commande a donc besoin de plus que la base des comptes :
# les mêmes dépôts (profil, fichiers, journal, générations) et le même dossier de
# cache que le serveur hébergé réellement lancé — `_depots_de_l_hebergement`
# ci-dessous les reconstruit à l'identique de `api.application.application()`.
#
# **À lancer dans le conteneur du serveur, pas depuis un poste personnel** :
# `OUROULER_CONFIG` et le dossier de cache que
# `_depots_de_l_hebergement` lit sont ceux de la machine **qui exécute la
# commande**. Lancée depuis un poste personnel avec seulement
# `OUROULER_DATABASE_URL` pointé sur la base distante, `retirer` fermerait bien le
# compte dans Postgres (distant, donc correct) mais chercherait profil, fichiers et
# cache d'activités dans un dossier **local**, presque toujours vide ou absent —
# laissant le vrai dépôt du propriétaire, sur le serveur, intact et désormais
# orphelin (`comptes_proprietaires` ne le retrouve plus), tout en annonçant un
# succès. `_depots_de_l_hebergement` refuse donc si le dossier de données
# attendu n'existe pas, plutôt que de continuer en silence sur une base vide — mais
# ce n'est qu'un filet : la commande doit être lancée `docker exec` (ou équivalent)
# dans le conteneur `deploiement/api/Dockerfile`, avec les mêmes variables que lui,
# voir `deploiement/api/README.md`. `inviter`, `invitations` et `reinitialiser`
# n'ont pas ce problème : elles ne touchent que la base de comptes (distante), pas
# de fichier local.


def ajouter_retirer(sous: argparse._SubParsersAction) -> None:
    # `VARIABLE_CONFIG` importée plutôt que son nom recopié en dur dans l'aide
    # ci-dessous : `tests/test_invariants.py` interdit qu'un module autre
    # qu'`api/exploitation.py` écrive le nom d'une variable `OUROULER_*` de
    # l'API dans du code exécuté (un pas de plus que « ne pas la lire ») —
    # même dans un simple texte d'aide.
    from ourouler.api.exploitation import VARIABLE_CONFIG

    p = sous.add_parser(
        "retirer",
        help="ferme un compte hébergé et efface ses données personnelles (RGPD) — "
        "à lancer DANS le conteneur du serveur, pas depuis le poste du mainteneur "
        "(voir deploiement/api/README.md)",
        description=(
            "Ferme un compte hébergé et efface ses données personnelles (RGPD), par le "
            "même chemin que DELETE /moi. À lancer DANS le conteneur du serveur, pas "
            "depuis le poste du mainteneur (voir deploiement/api/README.md). "
            "IMPORTANT : --config (l'option globale de `ourouler`) n'a aucun effet ici "
            f"— cette commande lit le profil du serveur hébergé via {VARIABLE_CONFIG} "
            "(la variable, pas l'option), exactement comme le fait le serveur lui-même ; "
            "--config ne sert qu'à charger une configuration valide pour le reste de la "
            "CLI, elle n'est jamais utilisée pour retrouver les données à effacer."
        ),
        parents=[parent_json()],
    )
    p.add_argument("adresse", help="adresse e-mail du compte à retirer")
    p.add_argument(
        "--oui",
        action="store_true",
        help="ne demande pas confirmation avant de supprimer définitivement",
    )
    p.set_defaults(fonction=_commande_retirer, requiert_profil=False)


def _commande_retirer(args: argparse.Namespace, config: Config) -> int:
    from ourouler.api.comptes import DepotComptes

    url_db = _url_des_comptes("retirer")

    with _base_des_comptes("retirer", url_db) as connexion:
        depot = DepotComptes(connexion)
        # `_depots_de_l_hebergement` passée telle quelle, jamais appelée ici : elle ne
        # doit s'exécuter (et donc pouvoir refuser sur un dossier de données absent)
        # qu'une fois l'adresse et la confirmation validées — voir `services/comptes.retirer`.
        return executer_retirer(args, config, depot=depot, resoudre_depots_heberges=_depots_de_l_hebergement)


#: Les réponses qui valent « oui » à la confirmation de `retirer` — en minuscules, sans
#: espace de bord (la comparaison est faite après `.strip().lower()`).
REPONSES_OUI = ("o", "oui", "y", "yes")


def executer_retirer(
    args: argparse.Namespace,
    config: Config,
    *,
    depot: DepotComptes,
    resoudre_depots_heberges: Callable[[], DepotsHeberges],
    demander_confirmation: Callable[[str], str] | None = None,
) -> int:
    """`ourouler retirer ADRESSE`. Renvoie le code de sortie (0 = succès, 1 = annulé).

    `demander_confirmation` est injectable (défaut : `None`, résolu en `input` **au
    moment de demander**, jamais comme valeur par défaut du paramètre) : une valeur
    par défaut `= input` capturerait l'objet `input` à l'import du module, qu'un
    `monkeypatch.setattr("builtins.input", ...)` ne pourrait plus atteindre — un test
    se retrouverait à attendre une frappe sur stdin.

    Une adresse sans compte lève `ErreurCompte` — `main()` l'affiche en une ligne,
    code 2, sans trace, comme les refus d'`inviter`.
    """
    from ourouler.api import vie_privee
    from ourouler.rendu.comptes import RETRAIT_ANNULE, json_retrait, question_retrait, texte_retrait
    from ourouler.services.comptes import retirer

    del config  # non utilisé : cette commande ne construit aucune configuration cycliste

    def confirmer(adresse: str) -> bool:
        if getattr(args, "oui", False):
            return True
        demander = demander_confirmation if demander_confirmation is not None else input
        return demander(question_retrait(adresse)).strip().lower() in REPONSES_OUI

    retrait = retirer(
        args.adresse,
        depot=depot,
        confirmer=confirmer,
        resoudre_depots_heberges=resoudre_depots_heberges,
        effacer_donnees=vie_privee.effacer_donnees,
    )
    if retrait is None:
        print(RETRAIT_ANNULE, file=sys.stderr)
        return 1
    print(json_retrait(retrait) if getattr(args, "json", False) else texte_retrait(retrait))
    return 0


def _depots_de_l_hebergement() -> DepotsHeberges:
    """Reconstruit les dépôts du serveur hébergé, à l'identique d'`api.application.application()`.

    « retirer » doit effacer les mêmes fichiers que sert le serveur réellement lancé —
    pas une approximation : même lecture du TOML partagé et des variables
    d'environnement (`api/exploitation.py`, seule autre porte du paquet à avoir le droit
    de les lire), même calcul du dossier de cache (`dossier_cache_depuis`), même
    sous-dossier `api/` pour les données (`NOM_DOSSIER_DONNEES`). Dupliqué ici plutôt
    qu'obtenu en appelant `application()` : cette fabrique construit une application
    FastAPI entière (routes, middlewares, front statique…) qu'une commande de ligne de
    commande n'a aucune raison de monter pour effacer des fichiers.

    `proprietaire=None` sur le socle, comme le fait `application()` en mode hébergé : ce
    TOML est la base commune, le profil de personne en particulier.

    **Refuse si le dossier de données attendu n'existe pas** — au lieu de rendre des
    dépôts qui pointent sur un dossier vide ou absent, ce qui laisserait `retirer`
    annoncer un succès sans avoir rien effacé sur le vrai serveur quand la commande
    tourne depuis un poste personnel plutôt que dans le conteneur. Ce n'est qu'un
    filet : un dossier qui existe par coïncidence au même chemin sur un poste
    personnel passerait ce test sans être le bon — la
    commande doit être lancée dans l'environnement du serveur, voir
    `deploiement/api/README.md`.
    """
    from ourouler.api import exploitation
    from ourouler.api.application import NOM_DOSSIER_DONNEES
    from ourouler.api.depots import (
        DepotFichiers,
        DepotGenerations,
        DepotProfils,
        JournalServices,
        SocleTOML,
    )
    from ourouler.config import dossier_cache_depuis
    from ourouler.services.comptes import DepotsHeberges

    chemin = exploitation.chemin_config()
    variables = exploitation.variables()
    socle = SocleTOML(chemin, variables=variables, proprietaire=None)
    dossier_cache = dossier_cache_depuis(exploitation.lire_toml(chemin))
    dossier_donnees = dossier_cache / NOM_DOSSIER_DONNEES
    if not dossier_donnees.is_dir():
        raise ErreurUtilisateur(
            f"retirer : dossier de données introuvable ({dossier_donnees}) — cette "
            "commande doit tourner DANS le conteneur du serveur hébergé (mêmes "
            f"{exploitation.VARIABLE_CONFIG} et volume que lui), pas depuis un autre "
            "poste : lancée ailleurs, elle fermerait le compte dans la base de comptes "
            "distante sans toucher au vrai profil, aux vrais fichiers ni au vrai cache "
            "du propriétaire, qui resteraient orphelins sur le serveur. "
            "Voir deploiement/api/README.md."
        )
    return DepotsHeberges(
        profils=DepotProfils(socle, dossier_donnees),
        fichiers=DepotFichiers(dossier_donnees),
        journal=JournalServices(dossier_donnees),
        generations=DepotGenerations(),
        dossier_cache=dossier_cache,
    )


def _url_des_comptes(commande: str) -> str:
    """L'URL de la base des comptes, ou un refus qui nomme la variable.

    Séparée de `_base_des_comptes` pour que l'ordre des refus reste celui du
    besoin : sans base, rien ne se fait — c'est ce qui se dit en premier,
    avant l'URL publique, qui ne sert qu'à fabriquer un lien.
    """
    from ourouler.api.exploitation import VARIABLE_DATABASE_URL, url_base_de_donnees

    url = url_base_de_donnees()
    if url is None:
        raise ErreurUtilisateur(
            f"{commande} : {VARIABLE_DATABASE_URL} n'est pas défini — impossible de joindre "
            "la base des comptes de l'hébergé"
        )
    return url


@contextmanager
def _base_des_comptes(commande: str, url_db: str) -> Iterator[Any]:
    """Une connexion à la base des comptes, **déjà migrée**, ou un refus lisible.

    Trois choses que les tests n'attrapent pas, et qu'un vrai lancement
    trouve en trois secondes :

    1. **Les migrations s'appliquent ici.** Les tests partent d'une base que
       leur `conftest` a migrée ; la vraie vie part d'une base vide, et la
       commande mourrait sur `relation "comptes" does not exist`. Les
       migrations sont idempotentes (`appliquer_migrations` rend la liste de
       ce qu'elle a fait, vide quand il n'y avait rien à faire) : les poser
       ici coûte quelques millisecondes et supprime une étape à retenir.
    2. **La trace du pilote ne remonte pas à l'utilisateur.** Une base
       injoignable, un mot de passe faux ou un serveur arrêté donneraient
       sinon une pile `psycopg`, pas une phrase.
    3. Et le nom de la commande figure dans les messages, comme dans le
       refus de la variable d'environnement.

    Ce qui est appliqué est **dit** : une migration qui passe en silence est
    une migration dont on découvre l'existence le jour où elle a mal tourné.
    """
    from ourouler.api.base_de_donnees import appliquer_migrations, ouvrir
    from ourouler.api.exploitation import VARIABLE_DATABASE_URL

    try:
        connexion = ouvrir(url_db)
    except Exception as e:  # psycopg lève une famille entière, toutes traitées pareil
        raise ErreurUtilisateur(
            f"{commande} : base des comptes injoignable ({_premiere_ligne(e)}) — vérifier "
            f"{VARIABLE_DATABASE_URL}, et que le serveur PostgreSQL est démarré"
        ) from e
    try:
        with connexion:
            posees = appliquer_migrations(connexion)
            if posees:
                print(f"base des comptes : {len(posees)} migration(s) appliquée(s)", file=sys.stderr)
            yield connexion
    except ErreurUtilisateur:
        raise
    except Exception as e:  # idem : une phrase plutôt qu'une pile
        raise ErreurUtilisateur(f"{commande} : {_premiere_ligne(e)}") from e


def _premiere_ligne(e: Exception) -> str:
    """Le message d'une exception de pilote, sans sa pile ni son curseur SQL."""
    return str(e).strip().splitlines()[0] if str(e).strip() else type(e).__name__


def _url_publique(environ: Mapping[str, str] | None = None) -> str:
    """L'URL publique du front hébergé, ou `ErreurUtilisateur` si elle n'est pas posée.

    Même forme que les lecteurs de variable d'`api/exploitation.py` : une variable,
    dépouillée, ou un refus qui nomme la variable plutôt qu'un lien vide silencieusement
    construit (`https:///entrer?jeton=...` ne mènerait nulle part).
    """
    environ = os.environ if environ is None else environ
    brut = (environ.get(VARIABLE_URL_PUBLIQUE) or "").strip()
    if not brut:
        raise ErreurUtilisateur(
            f"inviter : {VARIABLE_URL_PUBLIQUE} n'est pas défini — c'est l'URL publique du "
            "front hébergé, devant laquelle /entrer?jeton=... s'ouvre"
        )
    return brut


def _charger_service(chemin: Path | None = None) -> dict:
    """Le contenu de `service.toml`, lu ici et nulle part ailleurs (le cœur ne lit ni configuration ni
    environnement).

    `chemin` est injectable pour les tests — jamais un vrai `service.toml` n'est lu ou
    montré par les tests : ils lui passent un fichier à eux, en `.invalid`, jamais
    celui d'un vrai serveur.
    """
    chemin = (chemin or Path(os.environ.get(VARIABLE_SERVICE) or CHEMIN_SERVICE_DEFAUT)).expanduser()
    if not chemin.is_file():
        raise ErreurUtilisateur(
            f"inviter : fichier de service introuvable : {chemin} — copier "
            "service.example.toml et le renseigner"
        )
    try:
        with chemin.open("rb") as f:
            return tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        raise ErreurUtilisateur(f"{chemin} : TOML invalide ({e})") from e
