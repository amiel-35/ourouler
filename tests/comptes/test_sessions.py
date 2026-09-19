"""Les sessions : entrer, revenir, sortir (lot L7.2-C) — prouvé par l'effet.

Même discipline que `test_comptes.py` (et la même leçon de [[Q58]] derrière) :
on interroge la **base** et le **dépôt**, jamais la lecture du code qui les
accompagne. Les propriétés du brief sont couvertes une par une :

- deux `entrer` concurrents sur le même jeton n'ouvrent qu'une session
  (via l'atomicité déjà prouvée de `activer` — `test_comptes.py` — complétée
  ici par la preuve qu'une seule session existe derrière) ;
- un cookie d'une session expirée ou détruite rend `None` ;
- le jeton de session n'est pas devinable (même entropie que le jeton
  d'invitation, même forme vérifiée en base) ;
- un secret faux et un compte inexistant sont indistinguables, message et
  durée ;
- après activation, la session rend le `Proprietaire` du compte et pas celui
  d'un autre ;
- fermer une session la rend inutilisable, y compris quand elle n'existait
  déjà plus.

Les adresses de test sont toutes en `.invalid` (RFC 2606) — voir la note de
`test_comptes.py` sur `exemple.fr`.
"""

from __future__ import annotations

import re
import threading
import time
from datetime import UTC, datetime, timedelta

import pytest

from ourouler.api import comptes
from ourouler.api.base_de_donnees import DOSSIER_MIGRATIONS, ouvrir
from ourouler.api.comptes import DepotComptes
from ourouler.api.proprietaire import FORME_IDENTIFIANT

#: Un mot de passe qui n'est ni trivial ni un vrai mot de passe de quelqu'un.
MOT_DE_PASSE = "chameau-lanterne-oxyde-bicyclette"


def _activer(depot: DepotComptes, email: str):
    """Invite puis active un compte d'un coup — le geste répété par ce fichier."""
    emise = depot.inviter(email)
    return depot.activer(emise.jeton, MOT_DE_PASSE)


# --- la forme du jeton, sans base ---------------------------------------------


def test_la_forme_du_jeton_de_session_est_la_meme_en_python_et_en_base():
    """Même contrôle que pour l'identifiant de compte, appliqué au jeton de session."""
    sql = (DOSSIER_MIGRATIONS / "0002_sessions.sql").read_text(encoding="utf-8")
    motifs = set(re.findall(r"~ '(\^[^']+\$)'", sql))
    assert r"^[A-Za-z0-9_-]{20,255}$" in motifs, (
        f"la contrainte SQL du jeton de session ne se lit pas dans {motifs}"
    )


# --- ouvrir_session : forme et entropie ----------------------------------------


def test_un_jeton_de_session_respecte_la_forme_et_ne_se_repete_pas(depot: DepotComptes):
    """32 octets d'entropie (`OCTETS_JETON_SESSION`), comme pour l'invitation.

    On ouvre 200 sessions pour le même compte plutôt que d'appeler
    `secrets.token_urlsafe` directement : c'est le jeton que **le dépôt**
    rend qui doit être testé, pas la fonction de la bibliothèque standard
    qu'il appelle.
    """
    acces = _activer(depot, "cent-sessions@exemple.invalid")
    forme = re.compile(r"^[A-Za-z0-9_-]{20,255}$")
    jetons = {depot.ouvrir_session(acces.compte.identifiant) for _ in range(200)}
    assert len(jetons) == 200, "deux jetons de session identiques : l'entropie ne suffit pas"
    assert all(forme.match(j) for j in jetons)


def test_ouvrir_session_pose_bien_une_ligne_avec_la_bonne_echeance(
    depot: DepotComptes, connexion
):
    acces = _activer(depot, "echeance@exemple.invalid")
    depart = datetime(2026, 9, 19, 8, 0, tzinfo=UTC)
    jeton = depot.ouvrir_session(
        acces.compte.identifiant, duree=timedelta(days=30), maintenant=depart
    )
    compte, cree_le, expire_le = connexion.execute(
        "SELECT compte, cree_le, expire_le FROM sessions WHERE jeton = %s", (jeton,)
    ).fetchone()
    assert compte == acces.compte.identifiant
    assert cree_le == depart
    assert expire_le == depart + timedelta(days=30)


# --- proprietaire_de_la_session : le bon, jamais un autre ----------------------


def test_apres_activation_la_session_rend_le_proprietaire_du_compte(depot: DepotComptes):
    acces = _activer(depot, "propre-session@exemple.invalid")
    jeton = depot.ouvrir_session(acces.compte.identifiant)
    assert depot.proprietaire_de_la_session(jeton) == acces.proprietaire


def test_deux_comptes_ont_chacun_leur_session_et_jamais_celle_de_l_autre(depot: DepotComptes):
    """La fuite que [[Q58]] a mordu ailleurs : ici, sur la session elle-même."""
    acces_a = _activer(depot, "cycliste-a@exemple.invalid")
    acces_b = _activer(depot, "cycliste-b@exemple.invalid")
    jeton_a = depot.ouvrir_session(acces_a.compte.identifiant)
    jeton_b = depot.ouvrir_session(acces_b.compte.identifiant)

    assert depot.proprietaire_de_la_session(jeton_a) == acces_a.proprietaire
    assert depot.proprietaire_de_la_session(jeton_b) == acces_b.proprietaire
    assert acces_a.proprietaire != acces_b.proprietaire, "le semis ne distingue rien"
    assert depot.proprietaire_de_la_session(jeton_a) != acces_b.proprietaire
    assert depot.proprietaire_de_la_session(jeton_b) != acces_a.proprietaire


def test_un_jeton_de_session_invente_ne_resout_personne(depot: DepotComptes):
    assert depot.proprietaire_de_la_session("jeton-completement-invente") is None


def test_une_session_expiree_rend_none(depot: DepotComptes):
    acces = _activer(depot, "expire-vite@exemple.invalid")
    depart = datetime(2026, 9, 1, 12, tzinfo=UTC)
    jeton = depot.ouvrir_session(
        acces.compte.identifiant, duree=timedelta(hours=1), maintenant=depart
    )
    # Juste avant l'échéance : la session est encore vivante.
    assert depot.proprietaire_de_la_session(
        jeton, maintenant=depart + timedelta(minutes=59)
    ) == acces.proprietaire
    # Juste après : elle ne l'est plus.
    assert (
        depot.proprietaire_de_la_session(jeton, maintenant=depart + timedelta(hours=2)) is None
    )


def test_une_session_fermee_rend_none(depot: DepotComptes):
    acces = _activer(depot, "ferme-vite@exemple.invalid")
    jeton = depot.ouvrir_session(acces.compte.identifiant)
    assert depot.proprietaire_de_la_session(jeton) == acces.proprietaire

    depot.fermer_session(jeton)

    assert depot.proprietaire_de_la_session(jeton) is None


def test_fermer_une_session_deja_fermee_ou_inconnue_ne_leve_rien(depot: DepotComptes):
    """Idempotence explicite : « sortir » ne doit jamais échouer sur un cookie mort."""
    acces = _activer(depot, "deux-fois@exemple.invalid")
    jeton = depot.ouvrir_session(acces.compte.identifiant)

    depot.fermer_session(jeton)
    depot.fermer_session(jeton)  # une deuxième fois : toujours aucune exception
    depot.fermer_session("jeton-qui-n-a-jamais-existe")


# --- authentifier : indistinguable, message et durée ---------------------------


def test_authentifier_rend_le_compte_quand_tout_correspond(depot: DepotComptes):
    acces = _activer(depot, "revient@exemple.invalid")
    compte = depot.authentifier("revient@exemple.invalid", MOT_DE_PASSE)
    assert compte is not None
    assert compte.identifiant == acces.compte.identifiant


def test_authentifier_refuse_une_adresse_inconnue_un_mauvais_mot_de_passe_et_un_compte_inactif(
    depot: DepotComptes,
):
    _activer(depot, "existe@exemple.invalid")
    depot.inviter("jamais-active@exemple.invalid")  # un compte inactif, sans secret

    assert depot.authentifier("personne@exemple.invalid", MOT_DE_PASSE) is None
    assert depot.authentifier("existe@exemple.invalid", "un-autre-mot-de-passe-plausible") is None
    assert depot.authentifier("jamais-active@exemple.invalid", MOT_DE_PASSE) is None


def test_authentifier_calcule_un_hachage_meme_quand_l_adresse_est_inconnue(
    depot: DepotComptes, monkeypatch
):
    """La preuve **déterministe** de l'égalisation du temps — pas une mesure d'horloge.

    Le temps de réponse ne peut différer que si le calcul diffère : ce test
    espionne `verifier_mot_de_passe` et vérifie qu'il tourne, contre le
    bouche-trou, même quand l'adresse n'existe pas. C'est la cause ; le test
    de chronomètre plus bas en est la conséquence, mesurée en best-effort.
    """
    appels: list[str] = []
    original = comptes.verifier_mot_de_passe

    def espion(mot_de_passe: str, secret: str) -> bool:
        appels.append(secret)
        return original(mot_de_passe, secret)

    monkeypatch.setattr(comptes, "verifier_mot_de_passe", espion)

    assert depot.authentifier("inconnue-espionnee@exemple.invalid", "peu importe") is None
    assert appels == [comptes._SECRET_BOUCHE_TROU], (
        "authentifier() sur une adresse inconnue n'a pas calculé de hachage : le temps de "
        "réponse trahirait alors, à lui seul, qu'aucun compte n'existe pour cette adresse"
    )


def test_authentifier_met_a_peu_pres_le_meme_temps_pour_une_adresse_inconnue_et_un_mauvais_mot_de_passe(
    depot: DepotComptes,
):
    """Chronomètre best-effort : indicatif, pas la preuve (voir le test déterministe ci-dessus).

    On garde le **minimum** de plusieurs tirages de chaque côté — le bruit
    du système ralentit une mesure, il ne l'accélère jamais artificiellement
    — et on tolère un facteur généreux (x8) entre les deux : l'objectif est
    de détecter un court-circuit qui **sauterait** le hachage bouche-trou
    (rapport de plusieurs ordres de grandeur), pas de garantir une égalité au
    milliseconde près sur une machine partagée.
    """
    _activer(depot, "chrono@exemple.invalid")

    def _chrono(appel) -> float:
        depart = time.perf_counter()
        appel()
        return time.perf_counter() - depart

    t_inconnue = min(
        _chrono(lambda: depot.authentifier("personne-du-tout@exemple.invalid", "x"))
        for _ in range(5)
    )
    t_mauvais = min(
        _chrono(lambda: depot.authentifier("chrono@exemple.invalid", "mauvais-mot-de-passe"))
        for _ in range(5)
    )
    plus_lent, plus_rapide = max(t_inconnue, t_mauvais), max(min(t_inconnue, t_mauvais), 1e-6)
    rapport = plus_lent / plus_rapide
    assert rapport < 8, (
        f"adresse inconnue en {t_inconnue * 1000:.2f} ms, mauvais mot de passe en "
        f"{t_mauvais * 1000:.2f} ms (rapport {rapport:.1f}×) — trop d'écart pour que le "
        "bouche-trou tourne bien des deux côtés"
    )


def test_authentifier_ne_rend_rien_pour_un_compte_actif_mais_sans_secret_coherent(
    depot: DepotComptes, connexion
):
    """Contre-épreuve directe en base : un secret corrompu ne doit jamais matcher."""
    acces = _activer(depot, "corrompu@exemple.invalid")
    with connexion.transaction():
        connexion.execute(
            "UPDATE comptes SET secret = %s WHERE id = %s",
            ("0" * 32 + "$" + "0" * 64, acces.compte.identifiant),
        )
    assert depot.authentifier("corrompu@exemple.invalid", MOT_DE_PASSE) is None


# --- invitation_ouverte : indistinguable, les trois cas -------------------------


def test_invitation_ouverte_rend_l_adresse_et_l_echeance_sans_rien_consommer(
    depot: DepotComptes,
):
    emise = depot.inviter("regarder-sans-consommer@exemple.invalid")
    etat = depot.invitation_ouverte(emise.jeton)
    assert etat is not None
    assert etat.email == "regarder-sans-consommer@exemple.invalid"
    assert etat.expire_le == emise.invitation.expire_le
    # Rien n'a été consommé : le jeton active toujours un compte après coup.
    acces = depot.activer(emise.jeton, MOT_DE_PASSE)
    assert acces.compte.actif is True


def test_invitation_ouverte_rend_none_pour_un_jeton_inconnu_expire_ou_consomme(
    depot: DepotComptes,
):
    """Les trois façons d'échouer, une seule réponse — `None` dans les trois cas."""
    depart = datetime(2026, 9, 1, tzinfo=UTC)
    expiree = depot.inviter(
        "expiree@exemple.invalid", duree=timedelta(days=3), maintenant=depart
    )
    consommee = depot.inviter("consommee@exemple.invalid")
    depot.activer(consommee.jeton, MOT_DE_PASSE)

    assert depot.invitation_ouverte("jeton-completement-invente") is None
    assert (
        depot.invitation_ouverte(expiree.jeton, maintenant=depart + timedelta(days=10)) is None
    )
    assert depot.invitation_ouverte(consommee.jeton) is None


# --- une seule session pour un jeton d'invitation disputé -----------------------


def test_deux_entrer_concurrents_sur_le_meme_jeton_n_ouvrent_qu_une_seule_session(
    url_base: str,
):
    """`activer` sérialise déjà l'invitation (`test_comptes.py`) ; ici, la session.

    Deux fils tentent d'activer **et** d'ouvrir une session pour le même
    jeton, en même temps. Un seul doit réussir l'activation (l'invitation ne
    se consomme qu'une fois) ; c'est donc lui, et lui seul, qui ouvre une
    session — la base ne doit en contenir qu'une pour ce compte.
    """
    nombre = 4
    barriere = threading.Barrier(nombre)
    resultats: list[object] = [None] * nombre

    with ouvrir(url_base) as cx_principale:
        emise = DepotComptes(cx_principale).inviter("course-entrer@exemple.invalid")

    def tenter(rang: int) -> None:
        with ouvrir(url_base) as cx_fil:
            depot_fil = DepotComptes(cx_fil)
            barriere.wait(timeout=20)
            try:
                acces = depot_fil.activer(emise.jeton, MOT_DE_PASSE)
                resultats[rang] = depot_fil.ouvrir_session(acces.compte.identifiant)
            except BaseException as e:  # noqa: BLE001 - on veut l'exception telle quelle
                resultats[rang] = e

    fils = [threading.Thread(target=tenter, args=(rang,)) for rang in range(nombre)]
    for fil in fils:
        fil.start()
    for fil in fils:
        fil.join(timeout=30)
    assert not any(fil.is_alive() for fil in fils), "un fil ne s'est jamais débloqué"

    reussites = [r for r in resultats if isinstance(r, str)]
    echecs = [r for r in resultats if isinstance(r, BaseException)]
    assert len(reussites) == 1, f"plus d'une activation a réussi : {resultats}"
    assert len(echecs) == nombre - 1

    with ouvrir(url_base) as cx:
        total_sessions = cx.execute(
            "SELECT count(*) FROM sessions WHERE compte = %s", (emise.invitation.compte,)
        ).fetchone()[0]
    assert total_sessions == 1, "plus d'une session ouverte pour un seul jeton disputé"


# --- ce que la base n'a pas le droit d'accepter ---------------------------------


def test_la_base_refuse_un_jeton_de_session_hors_forme(depot: DepotComptes, connexion):
    import psycopg

    acces = _activer(depot, "forme-refusee@exemple.invalid")
    with pytest.raises(psycopg.errors.CheckViolation):
        with connexion.transaction():
            connexion.execute(
                "INSERT INTO sessions (jeton, compte, cree_le, expire_le) "
                "VALUES (%s, %s, now(), now() + interval '1 day')",
                ("trop-court", acces.compte.identifiant),
            )


def test_la_base_refuse_une_session_qui_expire_avant_sa_creation(
    depot: DepotComptes, connexion
):
    import psycopg

    acces = _activer(depot, "echeance-absurde@exemple.invalid")
    with pytest.raises(psycopg.errors.CheckViolation):
        with connexion.transaction():
            connexion.execute(
                "INSERT INTO sessions (jeton, compte, cree_le, expire_le) "
                "VALUES (%s, %s, now(), now() - interval '1 day')",
                ("j" * 32, acces.compte.identifiant),
            )


def test_supprimer_un_compte_efface_ses_sessions(depot: DepotComptes, connexion):
    acces = _activer(depot, "compte-efface@exemple.invalid")
    jeton = depot.ouvrir_session(acces.compte.identifiant)

    connexion.execute("DELETE FROM comptes WHERE id = %s", (acces.compte.identifiant,))

    restantes = connexion.execute(
        "SELECT count(*) FROM sessions WHERE jeton = %s", (jeton,)
    ).fetchone()[0]
    assert restantes == 0


def test_le_forme_d_identifiant_est_toujours_celle_du_module_proprietaire():
    """Sentinelle : si `FORME_IDENTIFIANT` change de forme, ce fichier doit être relu."""
    assert FORME_IDENTIFIANT.pattern == r"^[a-z0-9][a-z0-9_-]{0,63}$"
