"""Le socle des comptes : ce qu'on prouve par l'effet, pas par la forme.

Leçon de [[Q58]] sur ce dépôt : un test d'isolation y est resté vert pendant
des jours sur une fuite totale, parce qu'il mesurait la mauvaise chose. Les
tests d'ici interrogent donc la **base** — deux connexions réelles, des
transactions réellement concurrentes, un `SELECT` qui va chercher le mot de
passe dans toutes les colonnes de texte — plutôt que de relire le code qui
les accompagne.

Les adresses de test sont **toutes** en `.invalid` — le seul domaine, avec
`.example` et `.test`, que la RFC 2606 réserve et qui n'existera donc jamais.
`exemple.fr`, qu'on trouvait ici le 18/09/2026 au matin, est un domaine
réellement enregistré : écrire une adresse de test dessus, c'est écrire
l'adresse de quelqu'un (règle absolue 1), et c'est aussi ce qui envoie un
courriel au premier lot qui en enverra pour de vrai.
"""

from __future__ import annotations

import re
import threading
import time
from datetime import UTC, datetime, timedelta

import pytest

from ourouler.api.base_de_donnees import (
    DOSSIER_MIGRATIONS,
    appliquer_migrations,
    migrations_disponibles,
    ouvrir,
)
from ourouler.api.comptes import (
    DepotComptes,
    ErreurCompte,
    ErreurCompteExistant,
    ErreurInvitationRefusee,
    hacher_mot_de_passe,
    normaliser_email,
    nouvel_identifiant,
    verifier_mot_de_passe,
)
from ourouler.api.exploitation import VARIABLE_DATABASE_URL, url_base_de_donnees
from ourouler.api.proprietaire import FORME_IDENTIFIANT

#: Un mot de passe qui n'est ni trivial ni un vrai mot de passe de quelqu'un —
#: quatre mots au hasard, dans le goût « diceware », suffisent pour les tests.
MOT_DE_PASSE = "pigeon-vaisselle-quartz-ficelle"

# --- ce qui se vérifie sans base -------------------------------------------
#
# Ces tests-ci tournent partout, y compris sans Docker : l'absence du
# conteneur doit se voir comme des tests sautés, pas comme un fichier entier
# qui disparaît de la suite.


def test_la_forme_d_un_identifiant_est_la_meme_en_python_et_en_base():
    """La contrainte SQL et `FORME_IDENTIFIANT` disent le même mot.

    L'identifiant d'un compte finit en **segment de chemin** (dépôt de
    fichiers). Une base qui accepterait ce que Python refuse — ou l'inverse —
    ferait de la double écriture une fausse sécurité.
    """
    sql = (DOSSIER_MIGRATIONS / "0001_comptes.sql").read_text(encoding="utf-8")
    motifs = set(re.findall(r"~ '(\^[^']+\$)'", sql))
    assert FORME_IDENTIFIANT.pattern in motifs, (
        f"la contrainte SQL n'écrit pas la même forme que FORME_IDENTIFIANT : {motifs}"
    )


def test_un_identifiant_neuf_respecte_la_forme_et_ne_se_repete_pas():
    tirages = {nouvel_identifiant() for _ in range(200)}
    assert len(tirages) == 200
    assert all(FORME_IDENTIFIANT.match(t) for t in tirages)


def test_une_adresse_se_normalise_avant_d_entrer():
    assert normaliser_email("  Cycliste@Exemple.INVALID ") == "cycliste@exemple.invalid"
    for mauvaise in ("", "   ", "sans-arobase", "@exemple.invalid", "cycliste@"):
        with pytest.raises(ErreurCompte):
            normaliser_email(mauvaise)


@pytest.mark.parametrize(
    "hostile",
    [
        "a\n@exemple.invalid",
        "a\r\n@exemple.invalid",
        "a@exemple.invalid\nbcc: ailleurs@exemple.invalid",
        "a\t@exemple.invalid",
        "a b@exemple.invalid",
        "a@exemple .invalid",
        "a\x00@exemple.invalid",
        "a\x7f@exemple.invalid",
        "a\xa0b@exemple.invalid",
    ],
)
def test_une_adresse_qui_porte_un_blanc_ou_un_controle_est_refusee(hostile: str):
    """Le vecteur d'injection d'en-tête, refusé ici et pas plus loin."""
    with pytest.raises(ErreurCompte) as refus:
        normaliser_email(hostile)
    assert "caractère de contrôle ou une espace" in str(refus.value)


def test_le_sous_adressage_par_plus_fait_bien_deux_adresses():
    """Choix assumé et écrit : on ne présume pas la politique du fournisseur."""
    assert normaliser_email("Cycliste+Velo@Exemple.INVALID") == "cycliste+velo@exemple.invalid"
    assert normaliser_email("cycliste+velo@exemple.invalid") != normaliser_email(
        "cycliste@exemple.invalid"
    )


def test_un_mot_de_passe_hache_se_verifie_et_un_autre_est_refuse():
    secret = hacher_mot_de_passe(MOT_DE_PASSE)
    assert verifier_mot_de_passe(MOT_DE_PASSE, secret)
    assert not verifier_mot_de_passe("un-autre-mot-de-passe-tout-a-fait", secret)


def test_deux_hachages_du_meme_mot_de_passe_different_par_le_sel():
    """Un sel par compte : deux comptes au même mot de passe n'ont pas la même ligne."""
    a = hacher_mot_de_passe(MOT_DE_PASSE)
    b = hacher_mot_de_passe(MOT_DE_PASSE)
    assert a != b
    assert verifier_mot_de_passe(MOT_DE_PASSE, a)
    assert verifier_mot_de_passe(MOT_DE_PASSE, b)


def test_le_repr_d_une_invitation_emise_ne_montre_pas_le_jeton():
    """Un `repr` finit dans un journal, une trace, un `print` oublié."""
    from ourouler.api.comptes import Invitation, InvitationEmise

    maintenant = datetime(2026, 9, 18, tzinfo=UTC)
    jeton = "jeton-qui-ne-doit-pas-fuiter"
    emise = InvitationEmise(
        invitation=Invitation(jeton, "compte", maintenant, maintenant, None),
        jeton=jeton,
        deja_en_cours=False,
    )
    assert jeton not in repr(emise)
    assert jeton not in repr(emise.invitation)
    assert "jeton=<masqué>" in repr(emise)


def test_le_repr_d_un_compte_et_d_un_acces_ne_montre_pas_l_adresse():
    """La même règle que pour le jeton, pour la même raison.

    `Acces` est vérifié **par l'effet** et non par la lecture : il n'a pas de
    `__repr__` à lui, et c'est celui de son `Compte` qui le protège — ce test
    est ce qui le dira si un champ s'ajoute.
    """
    from ourouler.api.comptes import Acces, Compte
    from ourouler.api.proprietaire import Proprietaire

    compte = Compte(
        identifiant="a" * 32,
        email="cycliste@exemple.invalid",
        actif=True,
        cree_le=datetime(2026, 9, 18, tzinfo=UTC),
    )
    acces = Acces(compte=compte, proprietaire=Proprietaire("b" * 32))
    for texte in (repr(compte), repr(acces), f"{acces}", str([acces])):
        assert "cycliste@exemple.invalid" not in texte, texte
    assert "a" * 32 in repr(compte), "l'identifiant opaque, lui, doit rester lisible"
    assert "email=<masqué>" in repr(compte)


def test_l_url_de_la_base_ne_se_lit_qu_a_la_porte():
    """Même forme que les autres variables : absente, vide, ou une valeur."""
    assert url_base_de_donnees({}) is None
    assert url_base_de_donnees({VARIABLE_DATABASE_URL: ""}) is None
    assert url_base_de_donnees({VARIABLE_DATABASE_URL: "   "}) is None
    assert url_base_de_donnees({VARIABLE_DATABASE_URL: " postgresql://h/b "}) == "postgresql://h/b"


def test_il_y_a_bien_des_migrations_a_appliquer():
    numeros = [numero for numero, _, _ in migrations_disponibles()]
    assert numeros == sorted(numeros) and numeros, "aucune migration trouvée"


def test_les_migrations_partent_bien_dans_le_paquet():
    """Un `.sql` absent de la roue ferait planter le service au démarrage."""
    import tomllib
    from pathlib import Path

    assert DOSSIER_MIGRATIONS.parents[2].name == "src", DOSSIER_MIGRATIONS
    racine = Path(__file__).resolve().parents[2]
    pyproject = tomllib.loads((racine / "pyproject.toml").read_text(encoding="utf-8"))
    roue = pyproject["tool"]["hatch"]["build"]["targets"]["wheel"]
    assert roue.get("packages") == ["src/ourouler"], roue
    for clause in ("include", "only-include", "exclude"):
        assert clause not in roue, (
            f"[tool.hatch.build.targets.wheel] porte « {clause} » : vérifier que "
            "src/ourouler/api/migrations/*.sql part toujours dans la roue"
        )


# --- les migrations --------------------------------------------------------


def test_les_migrations_rejouees_deux_fois_ne_cassent_rien(url_base: str):
    """La fixture les a déjà appliquées : un second passage ne doit rien faire."""
    with ouvrir(url_base) as cx:
        assert appliquer_migrations(cx) == []
        emise = DepotComptes(cx).inviter("rejoue@exemple.invalid")
        assert appliquer_migrations(cx) == []
        restant = cx.execute(
            "SELECT count(*) FROM comptes WHERE id = %s", (emise.invitation.compte,)
        ).fetchone()[0]
        assert restant == 1


def test_les_migrations_sont_notees_une_seule_fois(url_base: str):
    with ouvrir(url_base) as cx:
        appliquer_migrations(cx)
        appliquer_migrations(cx)
        lignes = cx.execute("SELECT numero, nom FROM migrations ORDER BY numero").fetchall()
    assert len(lignes) == len(migrations_disponibles())
    assert len({numero for numero, _ in lignes}) == len(lignes)


# --- inviter -----------------------------------------------------------------


def attendre_un_fil_bloque(cx, delai_s: float = 20.0) -> None:
    """Attend qu'un **autre** fil soit réellement bloqué sur un verrou, ou échoue.

    On interroge PostgreSQL lui-même (`pg_stat_activity`) plutôt qu'un
    `time.sleep` posé au jugé : un test qui verdit sans avoir mesuré la
    course qu'il prétend tester est le pire des deux échecs possibles
    ([[Q58]]).
    """
    limite = time.monotonic() + delai_s
    while time.monotonic() < limite:
        bloques = cx.execute(
            "SELECT count(*) FROM pg_stat_activity "
            "WHERE datname = current_database() "
            "  AND wait_event_type = 'Lock' "
            "  AND pid <> pg_backend_pid()"
        ).fetchone()[0]
        if bloques:
            return
        time.sleep(0.02)
    raise AssertionError(
        f"aucun fil n'attendait un verrou après {delai_s:.0f} s : la course n'a pas eu "
        "lieu, et ce qui suit ne mesurerait donc pas la sérialisation"
    )


def test_un_compte_naît_inactif_avec_un_proprietaire_distinct(depot: DepotComptes, connexion):
    """[[Q46]] : deux identifiants, pas un. Et un compte invité ne s'utilise pas encore.

    Vérifié en base et non en relisant le code : un compte fraîchement
    invité ne porte aucun moyen de s'authentifier.
    """
    emise = depot.inviter("premier@exemple.invalid")
    compte_id = emise.invitation.compte
    proprietaire = depot.proprietaire_du_compte(compte_id)
    assert proprietaire.identifiant != compte_id
    assert FORME_IDENTIFIANT.match(compte_id)

    actif, methode, secret = connexion.execute(
        "SELECT actif, methode_authentification, secret FROM comptes WHERE id = %s",
        (compte_id,),
    ).fetchone()
    assert actif is False
    assert methode is None and secret is None, "un compte invité ne doit porter aucun secret"


def test_la_casse_et_les_espaces_ne_font_pas_deux_comptes(depot: DepotComptes, connexion):
    """« Cycliste@Exemple.INVALID » et « cycliste@exemple.invalid » : une personne."""
    depot.inviter("  Cycliste@Exemple.INVALID ")
    depot.inviter("cycliste@exemple.invalid")
    depot.inviter("CYCLISTE@EXEMPLE.INVALID")
    total = connexion.execute(
        "SELECT count(*) FROM comptes WHERE lower(email) = %s", ("cycliste@exemple.invalid",)
    ).fetchone()[0]
    assert total == 1


def test_un_compte_actif_ne_peut_pas_etre_reinvite(depot: DepotComptes):
    """Le refus qui reste : réinviter quelqu'un qui a déjà un compte utilisable."""
    emise = depot.inviter("actif@exemple.invalid")
    depot.activer(emise.jeton, MOT_DE_PASSE)

    with pytest.raises(ErreurCompteExistant) as refus:
        depot.inviter("actif@exemple.invalid")
    message = str(refus.value)
    assert "déjà un compte" in message
    assert datetime.now(UTC).strftime("%d/%m/%Y") in message
    assert "Traceback" not in message


def test_reinviter_un_compte_inactif_dont_l_invitation_court_rend_le_meme_jeton(
    depot: DepotComptes, connexion
):
    """Choix du mainteneur : « le cas réel c'est qu'il ne l'a pas vue » — et
    maintenant qu'il est en clair, le jeton peut être relu et renvoyé.
    """
    premiere = depot.inviter("relance@exemple.invalid")
    seconde = depot.inviter("relance@exemple.invalid")

    assert seconde.deja_en_cours
    assert seconde.jeton == premiere.jeton
    assert seconde.invitation.compte == premiere.invitation.compte
    total = connexion.execute(
        "SELECT count(*) FROM invitations WHERE compte = %s", (premiere.invitation.compte,)
    ).fetchone()[0]
    assert total == 1
    # Le lien sert toujours : on n'a rien invalidé en le relisant.
    acces = depot.activer(premiere.jeton, MOT_DE_PASSE)
    assert acces.compte.identifiant == premiere.invitation.compte


def test_une_invitation_expiree_se_remplace(depot: DepotComptes, connexion):
    depart = datetime(2026, 9, 1, 12, tzinfo=UTC)
    ancienne = depot.inviter("perimee@exemple.invalid", duree=timedelta(days=3), maintenant=depart)
    neuve = depot.inviter("perimee@exemple.invalid", maintenant=depart + timedelta(days=10))

    assert not neuve.deja_en_cours
    assert neuve.jeton != ancienne.jeton
    total = connexion.execute(
        "SELECT count(*) FROM invitations WHERE compte = %s", (ancienne.invitation.compte,)
    ).fetchone()[0]
    assert total == 1, "l'expirée a été retirée, pas empilée"
    assert depot.activer(neuve.jeton, MOT_DE_PASSE, maintenant=depart + timedelta(days=11))


def test_deux_invitations_simultanees_sur_une_adresse_neuve_ne_font_qu_un_compte(
    url_base: str,
):
    """La course que le socle précédent ne prouvait pas : cliquer deux fois « inviter ».

    Sous l'ancien schéma, la seconde recevait une erreur. Sous celui-ci, une
    adresse neuve sollicitée deux fois en même temps ne doit fabriquer
    qu'un seul compte et qu'une seule invitation — **et aucune erreur**,
    puisqu'un compte inactif ne bloque jamais une invitation.
    """
    nombre = 4
    adresse = "ruee@exemple.invalid"
    barriere = threading.Barrier(nombre)
    resultats: list[object] = [None] * nombre

    def tenter(rang: int) -> None:
        with ouvrir(url_base) as cx_fil:
            depot = DepotComptes(cx_fil)
            barriere.wait(timeout=20)
            try:
                resultats[rang] = depot.inviter(adresse)
            except BaseException as e:  # noqa: BLE001 - on veut l'exception telle quelle
                resultats[rang] = e

    fils = [threading.Thread(target=tenter, args=(rang,)) for rang in range(nombre)]
    for fil in fils:
        fil.start()
    for fil in fils:
        fil.join(timeout=30)
    assert not any(fil.is_alive() for fil in fils), "un fil ne s'est jamais débloqué"

    incidents = [r for r in resultats if isinstance(r, BaseException)]
    assert not incidents, incidents
    jetons = {r.jeton for r in resultats}
    comptes = {r.invitation.compte for r in resultats}
    assert len(jetons) == 1, "un seul jeton valide pour une adresse neuve sollicitée en rafale"
    assert len(comptes) == 1

    with ouvrir(url_base) as cx:
        total_comptes = cx.execute(
            "SELECT count(*) FROM comptes WHERE lower(email) = %s", (adresse,)
        ).fetchone()[0]
        total_invitations = cx.execute(
            "SELECT count(*) FROM invitations WHERE compte = %s", (comptes.pop(),)
        ).fetchone()[0]
    assert total_comptes == 1
    assert total_invitations == 1


# --- invitations_en_cours (lot L7.2-B) ---------------------------------------


def test_invitations_en_cours_rend_l_adresse_et_le_jeton(depot: DepotComptes):
    emise = depot.inviter("attendue@exemple.invalid")
    en_cours = depot.invitations_en_cours()
    assert len(en_cours) == 1
    assert en_cours[0].jeton == emise.jeton
    assert en_cours[0].email == "attendue@exemple.invalid"
    assert en_cours[0].expire_le == emise.invitation.expire_le


def test_invitations_en_cours_exclut_les_invitations_consommees(depot: DepotComptes):
    emise = depot.inviter("consommee@exemple.invalid")
    depot.activer(emise.jeton, MOT_DE_PASSE)
    assert depot.invitations_en_cours() == []


def test_invitations_en_cours_exclut_les_invitations_expirees(depot: DepotComptes):
    depart = datetime(2026, 9, 1, 12, tzinfo=UTC)
    depot.inviter("expiree@exemple.invalid", duree=timedelta(days=3), maintenant=depart)
    en_cours = depot.invitations_en_cours(maintenant=depart + timedelta(days=10))
    assert en_cours == []
    # Et elle redevient visible si on regarde avant son échéance.
    en_cours_avant = depot.invitations_en_cours(maintenant=depart + timedelta(days=1))
    assert len(en_cours_avant) == 1


def test_invitations_en_cours_triees_par_creation(depot: DepotComptes):
    depart = datetime(2026, 9, 1, 12, tzinfo=UTC)
    depot.inviter("premiere@exemple.invalid", maintenant=depart)
    depot.inviter("seconde@exemple.invalid", maintenant=depart + timedelta(hours=1))
    en_cours = depot.invitations_en_cours(maintenant=depart + timedelta(hours=2))
    assert [i.email for i in en_cours] == ["premiere@exemple.invalid", "seconde@exemple.invalid"]


def test_le_repr_d_une_invitation_avec_adresse_ne_montre_ni_jeton_ni_adresse(depot: DepotComptes):
    depot.inviter("masquee@exemple.invalid")
    en_cours = depot.invitations_en_cours()[0]
    assert "masquee@exemple.invalid" not in repr(en_cours)
    assert en_cours.jeton not in repr(en_cours)
    assert "jeton=<masqué>" in repr(en_cours) and "email=<masqué>" in repr(en_cours)


# --- activer -----------------------------------------------------------------


def test_une_invitation_s_emet_puis_s_active_une_fois(depot: DepotComptes):
    emise = depot.inviter("invite@exemple.invalid")
    assert emise.jeton and not emise.deja_en_cours

    acces = depot.activer(emise.jeton, MOT_DE_PASSE)
    assert acces.compte.identifiant == emise.invitation.compte
    assert acces.compte.actif is True
    assert acces.proprietaire == depot.proprietaire_du_compte(emise.invitation.compte)

    with pytest.raises(ErreurInvitationRefusee) as refus:
        depot.activer(emise.jeton, "un-autre-mot-de-passe-tout-aussi-correct")
    assert "déjà servi" in str(refus.value)
    assert emise.jeton not in str(refus.value), "le refus ne répète jamais le jeton"


def test_un_jeton_expire_est_refuse(depot: DepotComptes):
    depart = datetime(2026, 9, 1, 12, tzinfo=UTC)
    emise = depot.inviter("expire@exemple.invalid", duree=timedelta(days=3), maintenant=depart)
    with pytest.raises(ErreurInvitationRefusee) as refus:
        depot.activer(emise.jeton, MOT_DE_PASSE, maintenant=depart + timedelta(days=4))
    assert "expiré" in str(refus.value)
    assert emise.jeton not in str(refus.value)
    # Et il reste refusé pour de bon : l'expiration n'est pas un retard.
    with pytest.raises(ErreurInvitationRefusee):
        depot.activer(emise.jeton, MOT_DE_PASSE, maintenant=depart + timedelta(days=5))


def test_un_jeton_inconnu_est_refuse_sans_rien_reveler(depot: DepotComptes):
    with pytest.raises(ErreurInvitationRefusee) as refus:
        depot.activer("jeton-completement-invente", MOT_DE_PASSE)
    assert "n'existe pas" in str(refus.value)
    assert "jeton-completement-invente" not in str(refus.value)


def test_deux_activations_concurrentes_du_meme_jeton_une_seule_reussit(url_base: str):
    """`UPDATE … WHERE consomme_le IS NULL … RETURNING`, en une seule instruction.

    Le premier fil active sans valider ; le second se bloque sur la ligne,
    puis constate que la condition n'est plus vraie. Un `SELECT` suivi d'un
    `UPDATE` aurait ouvert l'accès deux fois.
    """
    resultat: dict[str, object] = {}
    with ouvrir(url_base) as cx_a, ouvrir(url_base) as cx_b:
        depot_a, depot_b = DepotComptes(cx_a), DepotComptes(cx_b)
        emise = depot_a.inviter("duel@exemple.invalid")

        def second_fil() -> None:
            try:
                resultat["b"] = depot_b.activer(emise.jeton, "mot-de-passe-du-second-fil")
            except BaseException as e:  # noqa: BLE001
                resultat["b"] = e

        fil = threading.Thread(target=second_fil)
        with cx_a.transaction():
            acces_a = depot_a.activer(emise.jeton, MOT_DE_PASSE)
            fil.start()
            attendre_un_fil_bloque(cx_a)
        fil.join(timeout=20)
        assert not fil.is_alive(), "le second fil ne s'est jamais débloqué"
        consommations = cx_a.execute(
            "SELECT count(*) FROM invitations WHERE compte = %s AND consomme_le IS NOT NULL",
            (emise.invitation.compte,),
        ).fetchone()[0]
        comptes_actifs = cx_a.execute(
            "SELECT count(*) FROM comptes WHERE id = %s AND actif", (emise.invitation.compte,)
        ).fetchone()[0]

    assert acces_a.compte.identifiant == emise.invitation.compte
    assert isinstance(resultat["b"], ErreurInvitationRefusee), resultat["b"]
    assert consommations == 1
    assert comptes_actifs == 1


def test_l_activation_est_atomique_si_la_pose_du_secret_echoue(
    depot: DepotComptes, connexion, monkeypatch
):
    """« Casser le code exprès » : simuler une panne pendant le hachage.

    Si `hacher_mot_de_passe` explose au milieu de la transaction
    d'activation, ni le compte ne doit passer actif, ni l'invitation ne doit
    se trouver consommée — sans ça, un incident de passage laisserait un
    compte actif sans secret, exactement l'état que la contrainte
    `comptes_actif_a_un_secret` interdit en base.
    """
    emise = depot.inviter("atomique@exemple.invalid")

    def hachage_qui_explose(mot_de_passe: str) -> str:
        raise RuntimeError("panne simulée pendant la pose du secret")

    monkeypatch.setattr("ourouler.api.comptes.hacher_mot_de_passe", hachage_qui_explose)

    with pytest.raises(RuntimeError):
        depot.activer(emise.jeton, MOT_DE_PASSE)

    actif = connexion.execute(
        "SELECT actif FROM comptes WHERE id = %s", (emise.invitation.compte,)
    ).fetchone()[0]
    assert actif is False, "le compte ne doit pas passer actif si le secret n'a pas pu être posé"

    consomme_le = connexion.execute(
        "SELECT consomme_le FROM invitations WHERE jeton = %s", (emise.jeton,)
    ).fetchone()[0]
    assert consomme_le is None, "le jeton ne doit pas être consommé si l'activation a échoué"

    # Et le jeton reste utilisable : l'échec n'a rien brûlé qu'il ne fallait.
    monkeypatch.undo()
    acces = depot.activer(emise.jeton, MOT_DE_PASSE)
    assert acces.compte.actif is True


def test_supprimer_un_compte_efface_le_lien_vers_le_proprietaire(depot, connexion):
    """[[Q46]] : c'est **cette** table qu'on efface, et les poids restent.

    Le lot de suppression est un lot ultérieur ; ce qui se vérifie ici est
    seulement que le schéma le permet.
    """
    emise = depot.inviter("efface@exemple.invalid")
    compte_id = emise.invitation.compte
    proprietaire = depot.proprietaire_du_compte(compte_id)

    connexion.execute("DELETE FROM comptes WHERE id = %s", (compte_id,))

    restants = connexion.execute(
        "SELECT count(*) FROM comptes_proprietaires WHERE proprietaire = %s",
        (proprietaire.identifiant,),
    ).fetchone()[0]
    invitations = connexion.execute(
        "SELECT count(*) FROM invitations WHERE compte = %s", (compte_id,)
    ).fetchone()[0]
    assert restants == 0 and invitations == 0


# --- ce que la base n'a pas le droit de contenir, ou d'accepter -------------


def test_le_mot_de_passe_en_clair_n_est_nulle_part_en_base(depot: DepotComptes, connexion):
    """Vérifié **en interrogeant la base**, colonne de texte par colonne de texte.

    Le jeton, lui, est en clair en base par décision du mainteneur — ce
    n'est plus ce qu'on vérifie ici. Ce qui doit rester introuvable, c'est le
    mot de passe : lui reste haché, toujours.
    """
    emise = depot.inviter("secret@exemple.invalid")
    acces = depot.activer(emise.jeton, MOT_DE_PASSE)

    colonnes = connexion.execute(
        "SELECT table_name, column_name FROM information_schema.columns "
        "WHERE table_schema = 'public' AND data_type IN ('text', 'character varying')"
    ).fetchall()
    assert colonnes, "aucune colonne de texte trouvée : le test ne mesure rien"

    portant_le_mot_de_passe = []
    for table, colonne in colonnes:
        requete = f'SELECT count(*) FROM "{table}" WHERE position(%s in "{colonne}") > 0'
        if connexion.execute(requete, (MOT_DE_PASSE,)).fetchone()[0]:
            portant_le_mot_de_passe.append(f"{table}.{colonne}")
    assert not portant_le_mot_de_passe, (
        f"le mot de passe en clair est en base : {portant_le_mot_de_passe}"
    )

    for texte in (repr(acces), repr(acces.compte), repr(emise), str([acces])):
        assert MOT_DE_PASSE not in texte, texte


def test_la_base_refuse_une_adresse_non_normalisee(connexion):
    """La contrainte mord même si le code oubliait d'appeler `normaliser_email`."""
    import psycopg

    with pytest.raises(psycopg.errors.CheckViolation):
        with connexion.transaction():
            connexion.execute(
                "INSERT INTO comptes (id, email) VALUES (%s, %s)",
                (nouvel_identifiant(), "Pas@Normalise.INVALID"),
            )


def test_la_base_refuse_un_identifiant_hors_forme(connexion):
    """Un identifiant qui sert de segment de chemin ne contient pas « ../ »."""
    import psycopg

    for mauvais in ("../evasion", "AvecMajuscules", "", "a" * 65):
        with pytest.raises(psycopg.errors.CheckViolation):
            with connexion.transaction():
                connexion.execute(
                    "INSERT INTO comptes (id, email) VALUES (%s, %s)",
                    (mauvais, f"x{len(mauvais)}@exemple.invalid"),
                )


def test_la_base_refuse_un_compte_actif_sans_secret(connexion):
    """L'invariant du produit, tenu par la base : `comptes_actif_a_un_secret`.

    Même si le code de ce module ne l'écrirait jamais ainsi, une écriture
    directe qui tenterait cet état doit être refusée — c'est ce qui rend la
    garantie vraie même le jour où quelqu'un écrira du SQL à la main.
    """
    import psycopg

    with pytest.raises(psycopg.errors.CheckViolation):
        with connexion.transaction():
            connexion.execute(
                "INSERT INTO comptes (id, email, actif) VALUES (%s, %s, true)",
                (nouvel_identifiant(), "sans.secret@exemple.invalid"),
            )
