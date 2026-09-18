"""Le socle des comptes : ce qu'on prouve par l'effet, pas par la forme.

Leçon de [[Q58]] sur ce dépôt : un test d'isolation y est resté vert pendant
des jours sur une fuite totale, parce qu'il mesurait la mauvaise chose. Les
tests d'ici interrogent donc la **base** — deux connexions réelles, des
transactions réellement concurrentes, un `SELECT` qui va chercher le jeton
dans toutes les colonnes de texte — plutôt que de relire le code qui les
accompagne.

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
    condenser,
    normaliser_email,
    nouvel_identifiant,
)
from ourouler.api.exploitation import VARIABLE_DATABASE_URL, url_base_de_donnees
from ourouler.api.proprietaire import FORME_IDENTIFIANT

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
    """Le vecteur d'injection d'en-tête, refusé ici et pas plus loin.

    `btrim` côté base ne coupe que l'espace ASCII : « a\\n@… » passait la
    contrainte `comptes_email_normalise` sans broncher, et le lot qui
    branchera l'envoi de courriel aurait mis cette chaîne dans un en-tête.
    Le refus est mesuré sur ce qui compte : saut de ligne, retour chariot,
    tabulation, octet nul, espace insécable, et l'espace simple interne.
    """
    with pytest.raises(ErreurCompte) as refus:
        normaliser_email(hostile)
    assert "caractère de contrôle ou une espace" in str(refus.value)


def test_le_sous_adressage_par_plus_fait_bien_deux_adresses():
    """Choix assumé et écrit : on ne présume pas la politique du fournisseur.

    Si ce test tombe un jour, c'est que quelqu'un a décidé de replier
    « cycliste+velo@… » sur « cycliste@… ». Ce n'est pas interdit — c'est une
    décision de produit, et elle doit se voir passer ici.
    """
    assert normaliser_email("Cycliste+Velo@Exemple.INVALID") == "cycliste+velo@exemple.invalid"
    assert normaliser_email("cycliste+velo@exemple.invalid") != normaliser_email(
        "cycliste@exemple.invalid"
    )


def test_le_repr_d_une_invitation_emise_ne_montre_pas_le_jeton():
    """Un `repr` finit dans un journal, une trace, un `print` oublié."""
    from ourouler.api.comptes import Invitation, InvitationEmise

    maintenant = datetime(2026, 9, 18, tzinfo=UTC)
    emise = InvitationEmise(
        invitation=Invitation("a" * 64, "compte", maintenant, maintenant, None),
        jeton="jeton-qui-ne-doit-pas-fuiter",
        deja_en_cours=False,
    )
    assert "jeton-qui-ne-doit-pas-fuiter" not in repr(emise)
    assert "jeton=<présent>" in repr(emise)


def test_le_repr_d_un_compte_et_d_un_acces_ne_montre_pas_l_adresse():
    """La même règle que pour le jeton, pour la même raison.

    Une relecture a vu l'adresse s'imprimer en clair dans la sortie d'un échec
    de pytest : le `repr` par défaut d'une dataclass montre tous ses champs.
    `Acces` est vérifié **par l'effet** et non par la lecture : il n'a pas de
    `__repr__` à lui, et c'est celui de son `Compte` qui le protège — ce test
    est ce qui le dira si un champ s'ajoute.
    """
    from ourouler.api.comptes import Acces, Compte
    from ourouler.api.proprietaire import Proprietaire

    compte = Compte(
        identifiant="a" * 32,
        email="cycliste@exemple.invalid",
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
    """Un `.sql` absent de la roue ferait planter le service au démarrage.

    Hatchling embarque tout ce qui vit sous `packages`, donc les `.sql` — et
    c'est vérifié à la main sur la roue construite le 18/09/2026. Ce qui
    casserait cette propriété sans bruit, c'est une clause `include` ou
    `only-include` ajoutée plus tard pour « ne prendre que le Python » : la
    suite resterait verte en développement (installation éditable) et le
    déploiement échouerait à la première migration.
    """
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
    """La fixture les a déjà appliquées : un second passage ne doit rien faire.

    Et un troisième non plus, après écriture — c'est le cas qui compte, parce
    que le service applique ses migrations à chaque démarrage, sur une base
    qui contient déjà des comptes.
    """
    with ouvrir(url_base) as cx:
        assert appliquer_migrations(cx) == []
        compte = DepotComptes(cx).creer_compte("rejoue@exemple.invalid")
        assert appliquer_migrations(cx) == []
        restant = cx.execute(
            "SELECT count(*) FROM comptes WHERE id = %s", (compte.identifiant,)
        ).fetchone()[0]
        assert restant == 1


def test_les_migrations_sont_notees_une_seule_fois(url_base: str):
    with ouvrir(url_base) as cx:
        appliquer_migrations(cx)
        appliquer_migrations(cx)
        lignes = cx.execute("SELECT numero, nom FROM migrations ORDER BY numero").fetchall()
    assert len(lignes) == len(migrations_disponibles())
    assert len({numero for numero, _ in lignes}) == len(lignes)


# --- les comptes -----------------------------------------------------------


def attendre_un_fil_bloque(cx, delai_s: float = 20.0) -> None:
    """Attend qu'un **autre** fil soit réellement bloqué sur un verrou, ou échoue.

    Remplace un `time.sleep(0.5)` posé « le temps que le second atteigne
    l'INSERT » (relecture du 18/09/2026). La différence n'est pas le confort :
    sur une machine chargée, le second fil peut n'avoir jamais atteint son
    `INSERT` quand le dormeur se réveille — le premier valide alors avant que
    la course ait lieu, et **le test reste vert sans avoir mesuré la
    sérialisation**. Un test qui verdit en ne testant rien est le pire des
    deux échecs possibles ([[Q58]]).

    On interroge donc PostgreSQL lui-même : `pg_stat_activity` dit quel
    processus attend un verrou. Tant qu'aucun n'attend, la course n'a pas
    commencé et il n'y a rien à valider. Si personne n'attend au bout du
    délai, le test **échoue** au lieu de continuer.
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


def test_un_compte_naît_avec_un_propriétaire_distinct(depot: DepotComptes):
    """[[Q46]] : deux identifiants, pas un.

    Les confondre serait tentant et invisible — jusqu'au jour de la
    suppression d'un compte, où il n'y aurait plus rien à délier.
    """
    compte = depot.creer_compte("premier@exemple.invalid")
    proprietaire = depot.proprietaire_du_compte(compte.identifiant)
    assert proprietaire.identifiant != compte.identifiant
    assert FORME_IDENTIFIANT.match(compte.identifiant)
    assert compte.email == "premier@exemple.invalid"
    assert compte.identifiant not in compte.email


def test_inviter_deux_fois_la_meme_adresse_dit_non(depot: DepotComptes):
    """« Pas d'interface ne veut pas dire pas de contrôle. »"""
    depot.creer_compte("deux.fois@exemple.invalid")
    with pytest.raises(ErreurCompteExistant) as refus:
        depot.creer_compte("deux.fois@exemple.invalid")
    message = str(refus.value)
    assert "déjà un compte" in message
    assert datetime.now(UTC).strftime("%d/%m/%Y") in message, "le refus doit dire depuis quand"
    assert "Traceback" not in message


def test_la_casse_et_les_espaces_ne_font_pas_deux_comptes(depot: DepotComptes, connexion):
    """« Cycliste@Exemple.INVALID » et « cycliste@exemple.invalid » : une personne."""
    depot.creer_compte("  Cycliste@Exemple.INVALID ")
    with pytest.raises(ErreurCompteExistant):
        depot.creer_compte("cycliste@exemple.invalid")
    with pytest.raises(ErreurCompteExistant):
        depot.creer_compte("CYCLISTE@EXEMPLE.INVALID")
    total = connexion.execute(
        "SELECT count(*) FROM comptes WHERE lower(email) = %s", ("cycliste@exemple.invalid",)
    ).fetchone()[0]
    assert total == 1


def test_deux_creations_concurrentes_ne_font_qu_un_compte(url_base: str):
    """Le cas que seul un `SELECT` puis `INSERT` laisserait passer.

    Le premier fil écrit **sans valider** et tient sa transaction ouverte ; le
    second se bloque sur l'index unique, puis reçoit le refus lisible dès que
    le premier valide. C'est la sérialisation par la base qu'on mesure, pas la
    chance d'un ordonnancement.
    """
    adresse = "course@exemple.invalid"
    resultat: dict[str, object] = {}
    with ouvrir(url_base) as cx_a, ouvrir(url_base) as cx_b:
        depot_a, depot_b = DepotComptes(cx_a), DepotComptes(cx_b)

        def second_fil() -> None:
            try:
                resultat["b"] = depot_b.creer_compte(adresse)
            except BaseException as e:  # noqa: BLE001 - on veut l'exception telle quelle
                resultat["b"] = e

        fil = threading.Thread(target=second_fil)
        with cx_a.transaction():
            depot_a.creer_compte(adresse)
            fil.start()
            # Mesuré, pas supposé : on attend que le second fil soit
            # effectivement bloqué sur le verrou avant de valider.
            attendre_un_fil_bloque(cx_a)
        fil.join(timeout=20)
        assert not fil.is_alive(), "le second fil ne s'est jamais débloqué"
        total = cx_a.execute(
            "SELECT count(*) FROM comptes WHERE lower(email) = %s", (adresse,)
        ).fetchone()[0]

    assert isinstance(resultat["b"], ErreurCompteExistant), resultat["b"]
    assert total == 1


def test_six_creations_simultanees_n_en_laissent_passer_qu_une(url_base: str):
    """La même chose en vrac : six fils, une barrière, un seul gagnant."""
    adresse = "melee@exemple.invalid"
    nombre = 6
    barriere = threading.Barrier(nombre)
    resultats: list[object] = [None] * nombre

    def tenter(rang: int) -> None:
        with ouvrir(url_base) as cx:
            depot = DepotComptes(cx)
            barriere.wait(timeout=20)
            try:
                resultats[rang] = depot.creer_compte(adresse)
            except BaseException as e:  # noqa: BLE001
                resultats[rang] = e

    fils = [threading.Thread(target=tenter, args=(rang,)) for rang in range(nombre)]
    for fil in fils:
        fil.start()
    for fil in fils:
        fil.join(timeout=30)

    gagnants = [r for r in resultats if not isinstance(r, BaseException)]
    refus = [r for r in resultats if isinstance(r, ErreurCompteExistant)]
    assert len(gagnants) == 1, resultats
    assert len(refus) == nombre - 1, resultats
    with ouvrir(url_base) as cx:
        total = cx.execute(
            "SELECT count(*) FROM comptes WHERE lower(email) = %s", (adresse,)
        ).fetchone()[0]
    assert total == 1


# --- les invitations -------------------------------------------------------


def test_inviter_un_compte_inexistant_dit_lequel_sans_trace_de_pilote(depot: DepotComptes):
    """Une erreur d'utilisateur, pas une exception de pilote.

    `creer_compte` traduisait déjà sa violation d'unicité ; `creer_invitation`
    laissait remonter une `ForeignKeyViolation` brute de psycopg (relecture du
    18/09/2026). `ourouler inviter` aurait affiché une trace de pilote à qui
    avait seulement tapé un identifiant de travers.
    """
    with pytest.raises(ErreurCompte) as refus:
        depot.creer_invitation("ffffffffffffffffffffffffffffffff")
    message = str(refus.value)
    assert "aucun compte" in message and "ffffffffffffffffffffffffffffffff" in message
    assert "psycopg" not in message and "DETAIL" not in message
    # Et le dépôt reste utilisable : la transaction a bien été annulée.
    compte = depot.creer_compte("apres.le.refus@exemple.invalid")
    assert depot.creer_invitation(compte.identifiant).jeton


def test_deux_invitations_simultanees_ne_font_qu_un_lien(url_base: str):
    """La troisième course du lot, celle qu'il ne prouvait pas.

    Les deux autres — deux créations de compte, deux consommations — étaient
    mesurées ; celle-ci ne l'était pas, alors que c'est exactement le geste que
    le mainteneur répétera : cliquer deux fois sur « inviter ». L'index partiel
    `invitations_en_cours_unique` et le `ON CONFLICT … DO NOTHING` doivent
    donner **un seul jeton** et dire aux autres qu'une invitation est déjà en
    cours — jamais deux liens valides pour le même compte.
    """
    nombre = 4
    with ouvrir(url_base) as cx:
        compte = DepotComptes(cx).creer_compte("ruee@exemple.invalid")
    barriere = threading.Barrier(nombre)
    resultats: list[object] = [None] * nombre

    def tenter(rang: int) -> None:
        with ouvrir(url_base) as cx_fil:
            depot = DepotComptes(cx_fil)
            barriere.wait(timeout=20)
            try:
                resultats[rang] = depot.creer_invitation(compte.identifiant)
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
    avec_jeton = [r for r in resultats if r.jeton is not None]
    sans_jeton = [r for r in resultats if r.jeton is None]
    assert len(avec_jeton) == 1, resultats
    assert all(r.deja_en_cours for r in sans_jeton), resultats
    assert {r.invitation.condense for r in resultats} == {
        avec_jeton[0].invitation.condense
    }, "les perdants doivent décrire l'invitation du gagnant, pas une autre"

    with ouvrir(url_base) as cx:
        total = cx.execute(
            "SELECT count(*) FROM invitations WHERE compte = %s", (compte.identifiant,)
        ).fetchone()[0]
        assert total == 1, "deux liens valides pour un compte"
        # Et le seul jeton rendu ouvre bien l'accès : la course n'a pas
        # fabriqué un gagnant qui ne sert à rien.
        acces = DepotComptes(cx).consommer(avec_jeton[0].jeton)
        assert acces.compte.identifiant == compte.identifiant


def test_une_invitation_s_emet_puis_se_consomme_une_fois(depot: DepotComptes):
    compte = depot.creer_compte("invite@exemple.invalid")
    emise = depot.creer_invitation(compte.identifiant)
    assert emise.jeton and not emise.deja_en_cours

    acces = depot.consommer(emise.jeton)
    assert acces.compte.identifiant == compte.identifiant
    assert acces.proprietaire == depot.proprietaire_du_compte(compte.identifiant)

    with pytest.raises(ErreurInvitationRefusee) as refus:
        depot.consommer(emise.jeton)
    assert "déjà servi" in str(refus.value)
    assert emise.jeton not in str(refus.value), "le refus ne répète jamais le jeton"


def test_un_jeton_expire_est_refuse(depot: DepotComptes):
    compte = depot.creer_compte("expire@exemple.invalid")
    depart = datetime(2026, 9, 1, 12, tzinfo=UTC)
    emise = depot.creer_invitation(
        compte.identifiant, duree=timedelta(days=7), maintenant=depart
    )
    with pytest.raises(ErreurInvitationRefusee) as refus:
        depot.consommer(emise.jeton, maintenant=depart + timedelta(days=8))
    assert "expiré" in str(refus.value)
    assert emise.jeton not in str(refus.value)
    # Et il reste refusé pour de bon : l'expiration n'est pas un retard.
    with pytest.raises(ErreurInvitationRefusee):
        depot.consommer(emise.jeton, maintenant=depart + timedelta(days=9))


def test_un_jeton_inconnu_est_refuse_sans_rien_reveler(depot: DepotComptes):
    with pytest.raises(ErreurInvitationRefusee) as refus:
        depot.consommer("jeton-completement-invente")
    assert "n'existe pas" in str(refus.value)
    assert "jeton-completement-invente" not in str(refus.value)


def test_une_invitation_deja_en_cours_ne_produit_pas_un_second_jeton(
    depot: DepotComptes, connexion
):
    """Choix du mainteneur : « le cas réel c'est qu'il ne l'a pas vue. »"""
    compte = depot.creer_compte("relance@exemple.invalid")
    premiere = depot.creer_invitation(compte.identifiant)
    seconde = depot.creer_invitation(compte.identifiant)

    assert seconde.deja_en_cours
    assert seconde.jeton is None, "un second jeton ferait deux liens valides"
    assert seconde.invitation.condense == premiere.invitation.condense
    total = connexion.execute(
        "SELECT count(*) FROM invitations WHERE compte = %s", (compte.identifiant,)
    ).fetchone()[0]
    assert total == 1
    # Le premier lien marche toujours : on n'a rien invalidé en chemin.
    assert depot.consommer(premiere.jeton).compte.identifiant == compte.identifiant


def test_une_invitation_expiree_se_remplace(depot: DepotComptes, connexion):
    compte = depot.creer_compte("perimee@exemple.invalid")
    depart = datetime(2026, 9, 1, 12, tzinfo=UTC)
    ancienne = depot.creer_invitation(
        compte.identifiant, duree=timedelta(days=7), maintenant=depart
    )
    neuve = depot.creer_invitation(compte.identifiant, maintenant=depart + timedelta(days=30))

    assert not neuve.deja_en_cours and neuve.jeton
    assert neuve.invitation.condense != ancienne.invitation.condense
    total = connexion.execute(
        "SELECT count(*) FROM invitations WHERE compte = %s", (compte.identifiant,)
    ).fetchone()[0]
    assert total == 1, "l'expirée a été retirée, pas empilée"
    assert depot.consommer(neuve.jeton, maintenant=depart + timedelta(days=31))


def test_deux_consommations_concurrentes_n_en_laissent_passer_qu_une(url_base: str):
    """`UPDATE … WHERE consomme_le IS NULL … RETURNING`, en une seule instruction.

    Le premier fil consomme sans valider ; le second se bloque sur la ligne,
    puis constate que la condition n'est plus vraie. Un `SELECT` suivi d'un
    `UPDATE` aurait ouvert l'accès deux fois.
    """
    resultat: dict[str, object] = {}
    with ouvrir(url_base) as cx_a, ouvrir(url_base) as cx_b:
        depot_a, depot_b = DepotComptes(cx_a), DepotComptes(cx_b)
        compte = depot_a.creer_compte("duel@exemple.invalid")
        jeton = depot_a.creer_invitation(compte.identifiant).jeton

        def second_fil() -> None:
            try:
                resultat["b"] = depot_b.consommer(jeton)
            except BaseException as e:  # noqa: BLE001
                resultat["b"] = e

        fil = threading.Thread(target=second_fil)
        with cx_a.transaction():
            acces_a = depot_a.consommer(jeton)
            fil.start()
            attendre_un_fil_bloque(cx_a)
        fil.join(timeout=20)
        assert not fil.is_alive(), "le second fil ne s'est jamais débloqué"
        consommations = cx_a.execute(
            "SELECT count(*) FROM invitations WHERE compte = %s AND consomme_le IS NOT NULL",
            (compte.identifiant,),
        ).fetchone()[0]

    assert acces_a.compte.identifiant == compte.identifiant
    assert isinstance(resultat["b"], ErreurInvitationRefusee), resultat["b"]
    assert consommations == 1


# --- ce que la base n'a pas le droit de contenir ---------------------------


def test_le_jeton_en_clair_n_est_nulle_part_en_base(depot: DepotComptes, connexion):
    """Vérifié **en interrogeant la base**, colonne de texte par colonne de texte.

    Relire le code aurait prouvé que le code d'aujourd'hui est correct ; ceci
    prouve que la base d'aujourd'hui l'est, ce qui reste vrai après une
    migration qu'on aurait écrite sans y penser. Le condensé, lui, doit bien
    s'y trouver — sinon le test chercherait au mauvais endroit et passerait
    pour de mauvaises raisons ([[Q58]]).
    """
    compte = depot.creer_compte("secret@exemple.invalid")
    emise = depot.creer_invitation(compte.identifiant)
    jeton = emise.jeton

    colonnes = connexion.execute(
        "SELECT table_name, column_name FROM information_schema.columns "
        "WHERE table_schema = 'public' AND data_type IN ('text', 'character varying')"
    ).fetchall()
    assert colonnes, "aucune colonne de texte trouvée : le test ne mesure rien"

    portant_le_jeton = []
    portant_le_condense = []
    for table, colonne in colonnes:
        requete = f'SELECT count(*) FROM "{table}" WHERE position(%s in "{colonne}") > 0'
        if connexion.execute(requete, (jeton,)).fetchone()[0]:
            portant_le_jeton.append(f"{table}.{colonne}")
        if connexion.execute(requete, (condenser(jeton),)).fetchone()[0]:
            portant_le_condense.append(f"{table}.{colonne}")

    assert not portant_le_jeton, f"le jeton en clair est en base : {portant_le_jeton}"
    assert portant_le_condense == ["invitations.condense"], portant_le_condense


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


def test_supprimer_un_compte_efface_le_lien_vers_le_proprietaire(depot, connexion):
    """[[Q46]] : c'est **cette** table qu'on efface, et les poids restent.

    Le lot de suppression est le sprint 9 ou 10 ; ce qui se vérifie ici est
    seulement que le schéma le permet — la cascade existe, et un compte
    supprimé ne laisse pas une correspondance orpheline qui rattacherait
    encore quelqu'un à ses données.
    """
    compte = depot.creer_compte("efface@exemple.invalid")
    proprietaire = depot.proprietaire_du_compte(compte.identifiant)
    depot.creer_invitation(compte.identifiant)

    connexion.execute("DELETE FROM comptes WHERE id = %s", (compte.identifiant,))

    restants = connexion.execute(
        "SELECT count(*) FROM comptes_proprietaires WHERE proprietaire = %s",
        (proprietaire.identifiant,),
    ).fetchone()[0]
    invitations = connexion.execute(
        "SELECT count(*) FROM invitations WHERE compte = %s", (compte.identifiant,)
    ).fetchone()[0]
    assert restants == 0 and invitations == 0
