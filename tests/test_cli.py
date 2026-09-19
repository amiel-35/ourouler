"""Tests de la CLI (L1.1)."""

import json
from pathlib import Path

import pytest

from ourouler.cli import construire_parseur, main

CONFIG = '[depart]\nnom="Test"\nlatitude=0.0\nlongitude=0.0\n[cycliste]\nmasse_kg=80\nftp_w=250\n'


def test_sans_commande_affiche_aide(capsys):
    assert main([]) == 0
    assert "meteo" in capsys.readouterr().out


def test_config_affiche(tmp_path: Path, capsys):
    f = tmp_path / "c.toml"
    f.write_text(CONFIG, encoding="utf-8")
    assert main(["--config", str(f), "config"]) == 0
    out = capsys.readouterr().out
    assert "Test" in out and "non renseigné" in out


def test_config_absente_code_2(tmp_path: Path, capsys):
    assert main(["--config", str(tmp_path / "x.toml"), "config"]) == 2
    assert "introuvable" in capsys.readouterr().err


# --- --json avant ou après la sous-commande ---------------------------------
#
# Tests qui auraient attrapé A3 : `--json` n'était déclaré qu'en option
# globale, et `ourouler meteo --json` — la forme écrite au contrat de sprint
# §4 — répondait « unrecognized arguments: --json ».


@pytest.mark.parametrize(
    "commande",
    ["config", "inventaire", "meteo", "boucle"],
    ids=lambda c: c,
)
@pytest.mark.parametrize("place", ["avant", "apres"], ids=lambda p: f"--json {p}")
def test_json_accepte_avant_et_apres_la_sous_commande(commande: str, place: str):
    """Le parseur doit accepter les deux formes, avec le même `dest`."""
    parseur = construire_parseur()
    argv = ["--json", commande] if place == "avant" else [commande, "--json"]
    args = parseur.parse_args(argv)
    assert args.json is True, f"{' '.join(argv)} : --json non pris en compte"
    assert args.commande == commande


@pytest.mark.parametrize("commande", ["config", "inventaire", "meteo", "boucle"])
def test_sans_json_la_sortie_reste_en_texte(commande: str):
    """Le sous-parseur ne doit pas non plus forcer `--json` à vrai."""
    assert construire_parseur().parse_args([commande]).json is False


def test_json_apres_la_sous_commande_avec_d_autres_options():
    args = construire_parseur().parse_args(["meteo", "--horizon", "3", "--json"])
    assert args.json is True and args.horizon == 3


def test_json_global_n_est_pas_ecrase_par_le_defaut_du_sous_parseur():
    """Le piège d'argparse : sans `default=SUPPRESS`, le sous-parseur remet False."""
    args = construire_parseur().parse_args(["--json", "meteo", "--horizon", "3"])
    assert args.json is True


def test_json_rend_bien_du_json_sur_la_sous_commande_config(tmp_path: Path, capsys):
    """De bout en bout : la forme `config --json` doit produire du JSON analysable."""
    f = tmp_path / "c.toml"
    f.write_text(CONFIG, encoding="utf-8")
    assert main(["--config", str(f), "config", "--json"]) == 0
    charge = json.loads(capsys.readouterr().out)
    assert charge["depart"]["nom"] == "Test"
    assert charge["intervals"]["api_key"] == "", "aucune clé renseignée ici"


def test_une_option_vraiment_inconnue_reste_refusee(capsys):
    """On n'a pas ouvert la porte à n'importe quelle option après la sous-commande."""
    with pytest.raises(SystemExit):
        construire_parseur().parse_args(["meteo", "--jsonn"])
    assert "unrecognized arguments" in capsys.readouterr().err


# --- état des connecteurs dans `ourouler config` (L2.1) ----------------------

MOT_DE_PASSE_CLI = "secret-de-test-cli"
CONFIG_BROUTER = (
    CONFIG
    + '[brouter]\nurl="https://brouter.exemple.test"\nutilisateur="u"\n'
    + f'mot_de_passe="{MOT_DE_PASSE_CLI}"\nprofil="gravel"\n'
)


def _config(tmp_path: Path, contenu: str) -> Path:
    f = tmp_path / "c.toml"
    f.write_text(contenu, encoding="utf-8")
    return f


def test_config_affiche_brouter_renseigne_avec_son_url(tmp_path: Path, capsys):
    assert main(["--config", str(_config(tmp_path, CONFIG_BROUTER)), "config"]) == 0
    out = capsys.readouterr().out
    assert "BRouter  : renseigné" in out
    assert "https://brouter.exemple.test" in out, "l'URL n'est pas un secret"
    assert "gravel" in out


def test_config_affiche_brouter_non_renseigne(tmp_path: Path, capsys):
    assert main(["--config", str(_config(tmp_path, CONFIG)), "config"]) == 0
    assert "BRouter  : non renseigné" in capsys.readouterr().out


def test_le_mot_de_passe_brouter_n_est_jamais_affiche(tmp_path: Path, capsys):
    assert main(["--config", str(_config(tmp_path, CONFIG_BROUTER)), "config"]) == 0
    assert MOT_DE_PASSE_CLI not in capsys.readouterr().out


# --- `ourouler config` sans FTP renseignée (T5, entonnoir d'accueil) --------

CONFIG_SANS_FTP = '[depart]\nnom="Test"\nlatitude=0.0\nlongitude=0.0\n[cycliste]\nmasse_kg=80\n'


def test_config_sans_ftp_n_affiche_pas_de_watts_pour_le_cycliste(tmp_path: Path, capsys):
    """Point 1 : `format(None, '.0f')` levait `TypeError` — repli textuel."""
    assert main(["--config", str(_config(tmp_path, CONFIG_SANS_FTP)), "config"]) == 0
    assert "FTP non renseignée" in capsys.readouterr().out


def test_config_sans_ftp_n_affiche_pas_de_watts_pour_les_zones(tmp_path: Path, capsys):
    """Point 2 : la ligne « Zones » calculait `pct * ftp_w`, même défaut."""
    assert main(["--config", str(_config(tmp_path, CONFIG_SANS_FTP)), "config"]) == 0
    out = capsys.readouterr().out
    assert "Zones" in out
    assert "pas de watts (FTP non renseignée)" in out


def test_le_mot_de_passe_brouter_est_masque_en_json(tmp_path: Path, capsys):
    """`dataclasses.asdict` ignore le `repr` masquant : il faut masquer ici aussi."""
    assert main(["--config", str(_config(tmp_path, CONFIG_BROUTER)), "config", "--json"]) == 0
    sortie = capsys.readouterr().out
    assert MOT_DE_PASSE_CLI not in sortie
    assert json.loads(sortie)["brouter"]["mot_de_passe"] == "***"
    assert json.loads(sortie)["brouter"]["url"] == "https://brouter.exemple.test"


# --- ourouler comparer (L3.3, point 3 de la relecture) ------------------------


def test_comparer_est_enregistree_avec_ses_options():
    args = construire_parseur().parse_args(
        ["comparer", "--velos", "RCR", "BMC", "--pente-max", "0.02", "--json"]
    )
    assert args.commande == "comparer"
    assert args.velos == ["RCR", "BMC"]
    assert args.pente_max == 0.02
    assert args.json is True


def test_comparer_exige_deux_velos():
    with pytest.raises(SystemExit):
        construire_parseur().parse_args(["comparer", "--velos", "RCR"])


def test_comparer_sans_velos_est_refusee():
    with pytest.raises(SystemExit):
        construire_parseur().parse_args(["comparer"])


# --- ourouler seance (L4.1) ---------------------------------------------------


def test_seance_est_enregistree_avec_ses_options():
    args = construire_parseur().parse_args(["seance", "--jour", "2026-09-08", "--json"])
    assert args.commande == "seance"
    assert args.jour == "2026-09-08"
    assert args.json is True


def test_seance_sans_option():
    args = construire_parseur().parse_args(["seance"])
    assert args.commande == "seance"
    assert args.jour is None
    assert args.json is False


def test_seance_accepte_json_avant_la_sous_commande():
    assert construire_parseur().parse_args(["--json", "seance"]).json is True


def test_seance_refuse_une_option_inconnue():
    with pytest.raises(SystemExit):
        construire_parseur().parse_args(["seance", "--velo", "RCR"])


# --- la troisième valeur de l'écran de FTP (F1, comble C2 de la relecture) ---
#
# `moyenne_compteur_kmh` (physique.modele) existait déjà, sans appelant : ces
# tests couvrent le branchement dans `ourouler config`, pas le calcul
# lui-même (couvert par tests/test_physique_modele.py).

CONFIG_VELO = (
    CONFIG + '[[velos]]\nnom="Route"\nusage="route"\nmasse_kg=9.0\ncda_m2=0.30\ncrr=0.005\n'
)
CONFIG_VELO_MESURE = CONFIG_VELO + "facteur_compteur=0.85\n"


def test_config_sans_section_velos_prend_quand_meme_le_velo_route_par_defaut(tmp_path, capsys):
    """`depuis_dict` pose déjà un vélo « Route » par défaut sans `[[velos]]` :
    la ligne apparaît donc dès la config la plus nue, avec un CdA/Crr par
    défaut — pas de crash, et le facteur reste marqué supposé."""
    assert main(["--config", str(_config(tmp_path, CONFIG)), "config"]) == 0
    out = capsys.readouterr().out
    assert "Vitesse" in out
    assert "SUPPOSÉ" in out


def test_info_vitesse_compteur_rend_none_sans_le_moindre_velo():
    """Garde défensive : `_info_vitesse_compteur` ne doit jamais planter si
    `Config.velos` est vide, même si `depuis_dict` ne produit jamais ce cas
    en pratique (elle pose toujours un vélo « Route » par défaut)."""
    import dataclasses

    from ourouler.cli import _info_vitesse_compteur
    from ourouler.config import depuis_dict

    config = depuis_dict(
        {
            "depart": {"nom": "Test", "latitude": 0.0, "longitude": 0.0},
            "cycliste": {"masse_kg": 80, "ftp_w": 250},
        }
    )
    assert _info_vitesse_compteur(dataclasses.replace(config, velos=())) is None


def test_config_avec_velo_affiche_la_vitesse_a_plat_et_la_moyenne_compteur(tmp_path, capsys):
    assert main(["--config", str(_config(tmp_path, CONFIG_VELO)), "config"]) == 0
    out = capsys.readouterr().out
    assert "Vitesse" in out
    assert "à plat" in out
    assert "moyenne compteur" in out


def test_config_sans_facteur_regle_dit_suppose(tmp_path, capsys):
    """Défaut du facteur (F0.6) : dérivé, pas mesuré — l'écran doit le dire."""
    assert main(["--config", str(_config(tmp_path, CONFIG_VELO)), "config"]) == 0
    out = capsys.readouterr().out
    assert "SUPPOSÉ" in out


def test_config_avec_facteur_regle_dit_mesure_et_pas_suppose(tmp_path, capsys):
    """Un utilisateur qui a réglé son facteur ne reçoit pas le même avertissement."""
    assert main(["--config", str(_config(tmp_path, CONFIG_VELO_MESURE)), "config"]) == 0
    out = capsys.readouterr().out
    assert "mesuré" in out
    assert "SUPPOSÉ" not in out


def test_config_json_distingue_facteur_mesure_de_suppose(tmp_path, capsys):
    assert main(["--config", str(_config(tmp_path, CONFIG_VELO)), "config", "--json"]) == 0
    suppose = json.loads(capsys.readouterr().out)["seance"]["vitesse_compteur"]
    assert suppose["facteur_mesure"] is False

    assert main(["--config", str(_config(tmp_path, CONFIG_VELO_MESURE)), "config", "--json"]) == 0
    mesure = json.loads(capsys.readouterr().out)["seance"]["vitesse_compteur"]
    assert mesure["facteur_mesure"] is True
    assert mesure["facteur_compteur"] == pytest.approx(0.85)


def test_config_json_vitesse_compteur_plus_basse_que_vitesse_a_plat(tmp_path, capsys):
    """C'est tout l'intérêt de l'afficher : elle est plus basse dès que le
    facteur l'est (docstring de `moyenne_compteur_kmh`)."""
    assert main(["--config", str(_config(tmp_path, CONFIG_VELO_MESURE)), "config", "--json"]) == 0
    info = json.loads(capsys.readouterr().out)["seance"]["vitesse_compteur"]
    assert info["moyenne_compteur_kmh"] < info["vitesse_a_plat_kmh"]


def test_config_json_vitesse_compteur_present_avec_le_velo_par_defaut(tmp_path, capsys):
    assert main(["--config", str(_config(tmp_path, CONFIG)), "config", "--json"]) == 0
    info = json.loads(capsys.readouterr().out)["seance"]["vitesse_compteur"]
    assert info is not None
    assert info["facteur_mesure"] is False


# --- inviter / invitations : ce qui se vérifie sans base (lot L7.2-B) --------
#
# Le câblage complet (vraie base PostgreSQL, envoi via un double SMTP) vit
# dans tests/comptes/test_cli_inviter.py, qui a besoin de Docker. Ici, les
# deux refus qui doivent se voir **avant** toute tentative de connexion à la
# base : `_url_publique()` est appelée avant `ouvrir(url_db)` dans
# `_commande_inviter`, donc une URL de base bidon (jamais composée) suffit à
# atteindre le second refus sans jamais toucher au réseau.


def test_inviter_sans_database_url_echoue_avec_un_message_lisible(tmp_path, capsys, monkeypatch):
    from ourouler.api.exploitation import VARIABLE_DATABASE_URL

    monkeypatch.delenv(VARIABLE_DATABASE_URL, raising=False)
    code = main(
        ["--config", str(_config(tmp_path, CONFIG)), "inviter", "x@exemple.invalid", "--sans-courriel"]
    )
    assert code == 2
    erreur = capsys.readouterr().err
    assert VARIABLE_DATABASE_URL in erreur
    assert "Traceback" not in erreur


def test_inviter_sans_url_publique_echoue_avec_un_message_lisible(tmp_path, capsys, monkeypatch):
    from ourouler.api.exploitation import VARIABLE_DATABASE_URL
    from ourouler.cli import VARIABLE_URL_PUBLIQUE

    # Une valeur bidon suffit : le refus sur l'URL publique tombe avant toute
    # tentative de connexion (voir la note ci-dessus).
    monkeypatch.setenv(VARIABLE_DATABASE_URL, "postgresql://jamais-compose/invalid")
    monkeypatch.delenv(VARIABLE_URL_PUBLIQUE, raising=False)
    code = main(
        ["--config", str(_config(tmp_path, CONFIG)), "inviter", "x@exemple.invalid", "--sans-courriel"]
    )
    assert code == 2
    erreur = capsys.readouterr().err
    assert VARIABLE_URL_PUBLIQUE in erreur
    assert "Traceback" not in erreur


def test_invitations_sans_database_url_echoue_avec_un_message_lisible(tmp_path, capsys, monkeypatch):
    from ourouler.api.exploitation import VARIABLE_DATABASE_URL

    monkeypatch.delenv(VARIABLE_DATABASE_URL, raising=False)
    code = main(["--config", str(_config(tmp_path, CONFIG)), "invitations"])
    assert code == 2
    erreur = capsys.readouterr().err
    assert VARIABLE_DATABASE_URL in erreur
    assert "Traceback" not in erreur


# --- _charger_service / _url_publique : les deux lecteurs propres à ce lot --
#
# Seul `cli.py` a le droit de lire `service.toml` ou la variable qui porte
# l'URL publique (règle absolue 2) — ces deux fonctions sont donc testées ici,
# directement, avec un fichier à nous. Jamais le vrai `service.toml` du
# mainteneur : ni ouvert, ni approché.


def test_charger_service_suit_la_variable_d_environnement(tmp_path, monkeypatch):
    """`OUROULER_SERVICE` déplace le fichier, pour un conteneur sans « chez soi ».

    Le 19/09/2026, envoyer le premier courriel réel depuis le conteneur a
    demandé un `docker cp` du fichier suivi d'un `rm` : le défaut
    `~/.config/ourouler/service.toml` ne veut rien dire là où il n'y a pas
    d'utilisateur. `deploiement/api/entrypoint.py` écrit désormais le fichier
    depuis l'environnement et pose cette variable pour dire où il l'a mis.
    """
    from ourouler.cli import VARIABLE_SERVICE, _charger_service

    ailleurs = tmp_path / "ailleurs" / "service.toml"
    ailleurs.parent.mkdir()
    ailleurs.write_text('[brevo]\nserveur = "relais.exemple.invalid"\n', encoding="utf-8")
    monkeypatch.setenv(VARIABLE_SERVICE, str(ailleurs))

    assert _charger_service()["brevo"]["serveur"] == "relais.exemple.invalid"


def test_charger_service_refuse_un_fichier_absent(tmp_path):
    from ourouler.cli import _charger_service
    from ourouler.erreurs import ErreurUtilisateur

    with pytest.raises(ErreurUtilisateur) as refus:
        _charger_service(tmp_path / "absent.toml")
    assert "introuvable" in str(refus.value)
    assert "service.example.toml" in str(refus.value)


def test_charger_service_refuse_un_toml_invalide(tmp_path):
    from ourouler.cli import _charger_service
    from ourouler.erreurs import ErreurUtilisateur

    fichier = tmp_path / "service.toml"
    fichier.write_text("ceci n'est pas du TOML valide [[[", encoding="utf-8")
    with pytest.raises(ErreurUtilisateur) as refus:
        _charger_service(fichier)
    assert "TOML invalide" in str(refus.value)


def test_charger_service_lit_un_fichier_de_test(tmp_path):
    """« Écris le code qui le lit, teste-le avec un fichier de test à toi » — jamais le
    vrai service.toml du mainteneur."""
    from ourouler.cli import _charger_service

    fichier = tmp_path / "service.toml"
    fichier.write_text(
        '[brevo]\nserveur="smtp-relay.exemple.invalid"\nport=587\n'
        'utilisateur="compte@exemple.invalid"\nmot_de_passe="xsmtpsib-test"\n'
        'expediteur="ourouler@exemple.invalid"\nnom_expediteur="où rouler"\n',
        encoding="utf-8",
    )
    brut = _charger_service(fichier)
    assert brut["brevo"]["serveur"] == "smtp-relay.exemple.invalid"


def test_url_publique_refuse_une_variable_absente_ou_vide():
    from ourouler.cli import _url_publique
    from ourouler.erreurs import ErreurUtilisateur

    with pytest.raises(ErreurUtilisateur):
        _url_publique({})
    with pytest.raises(ErreurUtilisateur):
        _url_publique({"OUROULER_URL_PUBLIQUE": "   "})


def test_url_publique_rend_la_valeur_depouillee():
    from ourouler.cli import _url_publique

    assert _url_publique({"OUROULER_URL_PUBLIQUE": "  https://ourouler.exemple.invalid  "}) == (
        "https://ourouler.exemple.invalid"
    )
