"""Les entrées hostiles : ce qu'un front mal écrit, un robot ou un doigt qui glisse envoie.

Rien de ceci n'est exotique. Une durée négative sort d'un champ numérique sans
`min`. Une date à dix ans sort d'un sélecteur laissé ouvert. Une adresse de
dix mille caractères sort d'un copier-coller. Un fichier de 200 Mo sort d'un
dossier de photos. Une latitude à 200 degrés sort d'une inversion lat/lon.

Le contrat commun est celui de `verifier_refus_exploitable` : un 4xx, un
`code`, un `message` en français, aucune trace Python. Le contre-exemple qu'on
cherche est toujours le même : la valeur traverse l'API, casse trois couches
plus bas, et remonte en 500 avec le nom d'une variable interne.

Aucun fichier de ce module n'est versionné : les contenus hostiles sont
fabriqués en mémoire, à l'exécution (règle absolue 1).
"""

from __future__ import annotations

import pytest
from outils_api import (
    ApiAbsente,
    client_api,
    config_d_essai,
    noms_de_parametres,
    parametre_nomme,
    route_pour,
    schema_openapi,
    verifier_refus_exploitable,
)

#: Le passage à l'heure d'été 2027 en France : 02:30 n'existe pas ce jour-là.
HEURE_QUI_N_EXISTE_PAS = "2027-03-28T02:30:00"
#: Le retour à l'heure d'hiver 2026 : 02:30 existe deux fois ce jour-là.
HEURE_AMBIGUE = "2026-10-25T02:30:00"
#: Dix ans devant : au-delà de tout modèle météo, et de la durée de vie du projet.
DATE_LOINTAINE = "2036-09-17"


def _route_de_parcours(client):
    schema = schema_openapi(client)
    chemin, methode, operation = route_pour(schema, "sortie", "boucle", "parcours")
    return schema, chemin, methode, operation


def _parametre(schema, operation, *motifs: str) -> str:
    noms = noms_de_parametres(schema, operation)
    nom = parametre_nomme(noms, *motifs)
    if not nom:
        raise ApiAbsente(f"aucun paramètre parmi {motifs} ; déclarés : {sorted(noms)}")
    return nom


# --- durées ------------------------------------------------------------------


@pytest.mark.xfail(strict=True, reason="F1 non livré : pas de route de parcours à maltraiter.")
@pytest.mark.parametrize(
    "valeur,quoi",
    [
        (-30, "durée négative"),
        (0, "durée nulle"),
        (100000, "durée de plus de deux mois"),
        ("deux heures", "durée en toutes lettres"),
    ],
    ids=["negative", "nulle", "enorme", "texte"],
)
def test_une_duree_absurde_est_refusee_proprement(valeur, quoi: str):
    """Protège E16 (« Demander un parcours », champ Durée).

    L'écran affiche une estimation qui bouge à chaque frappe : il enverra donc
    des valeurs intermédiaires, y compris un champ à moitié effacé. Chacune
    doit revenir en refus lisible, pas en 500 — un 500 sur une frappe rend
    l'écran instable au lieu de rendre le champ invalide.
    """
    client = client_api(config=config_d_essai())
    schema, chemin, methode, operation = _route_de_parcours(client)
    duree = _parametre(schema, operation, "duree", "distance")
    verifier_refus_exploitable(client.requete(methode, chemin, params={duree: valeur}), quoi)


# --- dates, fuseaux et heure d'été -------------------------------------------


@pytest.mark.xfail(
    strict=True,
    reason="F1 non livré. Exigence : au-delà de l'horizon des modèles, l'API dit qu'elle ne sait pas.",
)
def test_une_date_a_dix_ans_est_refusee_plutot_que_devinee():
    """Protège E16 (sélecteur « Quand ») et la règle absolue 5.

    « Ne rien affirmer sans mesure. » Aucun modèle météo ne va à dix ans.
    Servir un parcours daté de 2036 avec un vent inventé serait la pire des
    réponses : plausible et fausse. Le refus doit nommer l'horizon réel.
    """
    client = client_api(config=config_d_essai())
    schema, chemin, methode, operation = _route_de_parcours(client)
    jour = _parametre(schema, operation, "jour", "date", "quand")
    corps = verifier_refus_exploitable(
        client.requete(methode, chemin, params={jour: DATE_LOINTAINE}), "date à dix ans"
    )
    message = str(corps.get("message", ""))
    assert any(mot in message.lower() for mot in ("horizon", "jour", "loin", "porte")), (
        f"le refus ne dit pas jusqu'où on sait aller : {message!r}"
    )


@pytest.mark.xfail(strict=True, reason="F1 non livré : pas de route à qui donner une date tordue.")
@pytest.mark.parametrize(
    "valeur,quoi",
    [
        ("2026-02-30", "30 février"),
        ("hier", "date en toutes lettres"),
        ("17/09/2026", "date au format français"),
        ("2026-09-17T25:00:00", "vingt-cinquième heure"),
        ("", "date vide"),
    ],
    ids=["30fevrier", "mot", "format_fr", "heure_25", "vide"],
)
def test_une_date_illisible_est_refusee_proprement(valeur: str, quoi: str):
    """Protège E15 et E16, où la date vient d'un composant tiers.

    Un sélecteur de date React peut très bien envoyer sa valeur au format
    local. Le refus doit dire le format attendu, pas lever un `ValueError` de
    `datetime.fromisoformat` remonté tel quel.
    """
    client = client_api(config=config_d_essai())
    schema, chemin, methode, operation = _route_de_parcours(client)
    jour = _parametre(schema, operation, "jour", "date", "quand")
    verifier_refus_exploitable(client.requete(methode, chemin, params={jour: valeur}), quoi)


@pytest.mark.xfail(
    strict=True,
    reason="F1 non livré. Exigence : l'heure d'été se tranche explicitement, jamais par hasard.",
)
@pytest.mark.parametrize(
    "heure,quoi",
    [
        (HEURE_QUI_N_EXISTE_PAS, "02:30 le jour où l'heure avance : cette heure n'existe pas"),
        (HEURE_AMBIGUE, "02:30 le jour où l'heure recule : cette heure existe deux fois"),
    ],
    ids=["inexistante", "ambigue"],
)
def test_une_heure_de_depart_au_changement_d_heure_ne_plante_pas(heure: str, quoi: str):
    """Protège E14, E16 et E19, où toute heure affichée est une heure locale.

    Le produit affiche « retour vers 11 h 40 » et « Départ à 9 h 40 » : des
    heures locales. Il interroge Open-Meteo, qui raisonne en UTC. Les deux
    jours de bascule annuels sont le seul endroit où la conversion est
    ambiguë ou impossible — et ils tombent un dimanche matin, c'est-à-dire
    exactement quand on roule.

    Deux réponses sont acceptables : un refus lisible, ou un succès qui
    **nomme** l'heure retenue. La seule réponse inacceptable est un 500, ou
    un succès muet qui décale tout d'une heure sans le dire.
    """
    client = client_api(config=config_d_essai())
    schema, chemin, methode, operation = _route_de_parcours(client)
    depart = _parametre(schema, operation, "heure", "depart")
    reponse = client.requete(methode, chemin, params={depart: heure})
    if reponse.status_code >= 400:
        verifier_refus_exploitable(reponse, quoi)
        return
    assert any(
        mot in reponse.text.lower() for mot in ("heure", "fuseau", "utc", "retenu")
    ), f"{quoi} : succès muet, rien ne dit quelle heure a été retenue"


# --- géographie ---------------------------------------------------------------


@pytest.mark.xfail(strict=True, reason="F1 non livré : pas de route qui prenne un point de départ.")
@pytest.mark.parametrize(
    "latitude,longitude,quoi",
    [
        (200, 0, "latitude à 200 degrés"),
        (0, 400, "longitude à 400 degrés"),
        ("nord", "ouest", "coordonnées en toutes lettres"),
        (None, None, "coordonnées nulles"),
    ],
    ids=["lat_200", "lon_400", "texte", "nulles"],
)
def test_une_coordonnee_hors_du_globe_est_refusee_proprement(latitude, longitude, quoi: str):
    """Protège E10 (« D'où partez-vous ? ») et E16 (« Partir d'ailleurs cette fois »).

    L'inversion latitude/longitude est l'erreur la plus fréquente du métier, et
    elle produit souvent un point valide mais absurde. Hors bornes, elle doit
    être refusée par l'API : un point hors du globe descendu jusqu'à Open-Meteo
    revient en `ErreurHorsDomaine`, que l'utilisateur lit comme « hors du
    domaine » — la confusion que E14 · dégradé documente déjà.
    """
    client = client_api(config=config_d_essai())
    schema, chemin, methode, operation = _route_de_parcours(client)
    lat = _parametre(schema, operation, "latitude", "lat")
    lon = _parametre(schema, operation, "longitude", "lon")
    reponse = client.requete(methode, chemin, params={lat: latitude, lon: longitude})
    verifier_refus_exploitable(reponse, quoi)


@pytest.mark.xfail(
    strict=True, reason="F1 non livré : pas de route de géocodage à qui donner une adresse absurde."
)
@pytest.mark.parametrize(
    "adresse,quoi",
    [
        ("A" * 10000, "adresse de dix mille caractères"),
        ("", "adresse vide"),
        ("   ", "adresse en espaces"),
        ("\x00\x01\x02", "adresse en octets de contrôle"),
    ],
    ids=["dix_mille", "vide", "espaces", "octets"],
)
def test_une_adresse_hostile_est_refusee_avant_d_atteindre_le_geocodeur(adresse: str, quoi: str):
    """Protège E10 et E16, et le quota du service de géocodage.

    Une adresse de dix mille caractères ne se géocode pas : elle se refuse. Si
    elle part chez la BAN, elle consomme un appel, peut revenir en 414 et fait
    remonter un message du service tiers — en anglais — jusqu'à l'écran.
    """
    client = client_api(config=config_d_essai())
    schema = schema_openapi(client)
    chemin, methode, operation = route_pour(schema, "geocod", "adresse")
    cle = _parametre(schema, operation, "adresse", "requete", "q")
    verifier_refus_exploitable(client.requete(methode, chemin, params={cle: adresse}), quoi)


# --- fichiers de séance déposés (E17) ----------------------------------------

#: Un ZWO minimal et valide, pour prouver que le refus n'est pas un refus de tout.
ZWO_VALIDE = (
    '<workout_file><name>Essai</name><workout>'
    '<SteadyState Duration="600" Power="0.6"/>'
    "</workout></workout_file>"
)

#: La « bombe à entités » — dix entités imbriquées qui s'expansent en millions
#: de caractères. `xml.etree` la refuse par défaut depuis longtemps, mais un
#: lecteur ZWO qui bricole son propre parseur, ou qui relâche la garde, la
#: déplierait. On la fabrique à l'exécution, on ne la versionne pas.
BOMBE_ENTITES = (
    '<?xml version="1.0"?><!DOCTYPE lol [<!ENTITY a "aaaaaaaaaa">'
    '<!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;">'
    '<!ENTITY c "&b;&b;&b;&b;&b;&b;&b;&b;&b;&b;">'
    '<!ENTITY d "&c;&c;&c;&c;&c;&c;&c;&c;&c;&c;">]>'
    "<workout_file><name>&d;</name></workout_file>"
)


def _route_de_depot(client):
    schema = schema_openapi(client)
    chemin, methode, operation = route_pour(schema, "seance", "depot", "import", "fichier")
    if methode not in {"POST", "PUT"}:
        raise ApiAbsente(f"E17 dépose un fichier : {methode} {chemin} n'accepte pas d'envoi")
    return chemin, methode, operation


@pytest.mark.xfail(
    strict=True, reason="F1 non livré : pas de route de dépôt de séance (E17 « Déposer une séance »)."
)
@pytest.mark.parametrize(
    "nom,contenu,quoi",
    [
        ("vide.zwo", b"", "fichier vide"),
        ("tronque.zwo", ZWO_VALIDE.encode()[:40], "XML tronqué au milieu d'une balise"),
        ("image.zwo", b"\x89PNG\r\n\x1a\n" + b"\x00" * 64, "binaire déguisé en ZWO"),
        ("texte.zwo", b"ceci n'est pas du XML", "texte brut"),
        ("bombe.zwo", BOMBE_ENTITES.encode(), "bombe à entités XML"),
        ("seance.fit", b"\x0e\x10" + b"\x00" * 64, "FIT, reporté par arbitrage"),
        ("seance.gpx", b"<gpx></gpx>", "extension non prévue"),
    ],
    ids=["vide", "tronque", "binaire", "texte", "bombe", "fit", "gpx"],
)
def test_un_fichier_de_seance_hostile_est_refuse_proprement(nom: str, contenu: bytes, quoi: str):
    """Protège E17 (« Importer une séance »).

    E17 promet de montrer « ce qu'il a compris dedans » : c'est le seul moyen
    pour l'utilisateur de voir qu'un fichier a été mal lu avant de partir
    rouler avec. Le corollaire est qu'un fichier illisible doit être nommé
    illisible — pas lu à moitié, pas remonté en trace `ElementTree`.

    Le cas `.fit` est particulier : il est refusé **par arbitrage** (décision 5
    du contrat, « le .FIT attend »), et les maquettes exigent que son absence
    « se dise à l'écran plutôt que de se découvrir au moment du dépôt ». Le
    message doit donc dire que le format viendra, pas qu'il est invalide.
    """
    client = client_api(config=config_d_essai())
    chemin, methode, _ = _route_de_depot(client)
    reponse = client.requete(
        methode, chemin, files={"fichier": (nom, contenu, "application/octet-stream")}
    )
    verifier_refus_exploitable(reponse, quoi)


@pytest.mark.xfail(
    strict=True,
    reason="F1 non livré. Exigence : un fichier énorme se refuse à la taille, avant d'être lu.",
)
def test_un_fichier_de_200_mo_est_refuse_sans_etre_charge_en_memoire():
    """Protège E17, et le serveur qui l'héberge.

    Une séance `.ZWO` fait quelques kilo-octets. Deux cents méga-octets ne sont
    pas une séance : c'est un dossier de photos déposé par erreur, ou un déni
    de service. Le refus doit venir de la taille annoncée, avant toute lecture
    — un serveur qui lit d'abord et juge ensuite tombe au troisième dépôt
    simultané.
    """
    client = client_api(config=config_d_essai())
    chemin, methode, _ = _route_de_depot(client)
    enorme = b"<workout_file>" + b"0" * (200 * 1024 * 1024) + b"</workout_file>"
    reponse = client.requete(methode, chemin, files={"fichier": ("gros.zwo", enorme, "text/xml")})
    assert reponse.status_code in (400, 413, 422), (
        f"statut {reponse.status_code} pour 200 Mo déposés ; attendu un refus de taille (413)"
    )
    verifier_refus_exploitable(reponse, "fichier de 200 Mo")


# --- paramètres contradictoires ----------------------------------------------


@pytest.mark.xfail(
    strict=True,
    reason="F1 non livré. Exigence : deux consignes incompatibles se refusent, elles ne s'arbitrent pas.",
)
def test_des_parametres_contradictoires_sont_refuses_plutot_qu_arbitres_en_silence():
    """Protège E16, où trois réglages cohabitent sur le même écran.

    « Rentrer avec : de travers » et « orientation : peu importe » sont deux
    réponses à la même question ; une durée et une distance imposées
    ensemble en sont deux autres. Un front qui envoie les deux a un bug, et le
    pire service qu'on puisse lui rendre est d'en choisir une au hasard : la
    contradiction devient alors un comportement, et personne ne la retrouve.
    """
    client = client_api(config=config_d_essai())
    schema, chemin, methode, operation = _route_de_parcours(client)
    noms = noms_de_parametres(schema, operation)
    duree = parametre_nomme(noms, "duree")
    distance = parametre_nomme(noms, "distance")
    assert duree and distance, (
        f"E16 demande une durée, la CLI une distance : les deux doivent être déclarées "
        f"pour que la contradiction soit refusable. Déclarés : {sorted(noms)}"
    )
    reponse = client.requete(methode, chemin, params={duree: 2, distance: 200})
    verifier_refus_exploitable(reponse, "durée et distance imposées ensemble")


@pytest.mark.xfail(
    strict=True, reason="F1 non livré : aucune route où envoyer un corps JSON malformé."
)
def test_un_corps_json_malforme_ne_remonte_pas_en_trace():
    """Protège tous les écrans qui écrivent (E9 à E12, E16, E21).

    Un corps tronqué par une connexion mobile coupée est le cas courant, pas
    le cas d'école. Le refus doit être le même que les autres — même forme,
    même `code`, même français — sinon le front a deux gestions d'erreur.
    """
    client = client_api(config=config_d_essai())
    _, chemin, methode, _ = _route_de_parcours(client)
    reponse = client.requete(
        methode,
        chemin,
        content=b'{"duree": 2, "direct',
        headers={"content-type": "application/json"},
    )
    verifier_refus_exploitable(reponse, "corps JSON tronqué")
