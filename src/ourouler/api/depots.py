"""Où vivent les données, et à qui elles appartiennent.

**Chaque méthode publique de ce module prend un `Proprietaire` en premier
argument positionnel.** Ce n'est pas une convention d'écriture, c'est la
clause de propriétaire de la doctrine §10.2 (« aucune requête sans clause de
propriétaire ») posée pendant qu'elle est gratuite. Un invariant de
`tests/test_invariants.py` le vérifie sur l'arbre syntaxique : le jour où ces
dépôts parleront à PostgreSQL, la signature qui force le `WHERE` sera déjà là.

Deux dépôts, deux natures de données :

- `DepotProfils` — le profil : le **socle** servi par le serveur, plus ce que
  **ce propriétaire-là** a modifié depuis l'interface. Le TOML du serveur
  n'est jamais réécrit (voir `enregistrer`).
- `DepotFichiers` — les fichiers produits (carte) et déposés (`.ZWO`,
  `.MRC`), rangés sous un préfixe par propriétaire et servis par un
  identifiant opaque, jamais par un chemin.
- `DepotGenerations` — les GPX des propositions d'une génération, **en
  mémoire et bornés**, servis à la demande quand le cycliste choisit.

Aucun des deux ne lit l'environnement : ils reçoivent les chemins que
`exploitation.py` a résolus, comme le cœur reçoit sa `Config`.
"""

from __future__ import annotations

import json
import re
import uuid
from collections import OrderedDict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path

from ourouler.api.erreurs import ErreurProfilAbsent
from ourouler.api.exploitation import construire, ecrire_toml, lire_toml
from ourouler.api.proprietaire import PROPRIETAIRE_LOCAL, Proprietaire
from ourouler.config import CACHE_DEFAUT, PREFIXE_ENV, Config, dossier_cache_depuis
from ourouler.noyau.erreurs import ErreurConfig, ErreurUtilisateur
from ourouler.noyau.profil import DEPART_PAR_DEFAUT

#: Le tiers 3 du découpage du profil (décision Q35,
#: `docs/journal/questions/questions_mainteneur.md`) — **perso pur** : jamais
#: hérité, jamais deviné. Ni le TOML du serveur, ni les variables
#: d'environnement de la machine ne peuvent fournir
#: une de ces sections à un propriétaire qui ne l'a pas lui-même écrite.
#: `SocleTOML.config` s'en sert, c'est le seul endroit où un socle hébergé se
#: construit : le contrôle vit à un seul endroit.
SECTIONS_PERSO_PUR = ("depart", "cycliste", "velos", "intervals")

#: Les suffixes `OUROULER_<suffixe>` (`config.py:_survoler_environnement`,
#: `PREFIXE_ENV`) qui portent les sections ci-dessus. `brouter` n'y figure
#: pas : c'est un secret **serveur**, pas un profil de cycliste —
#: ses variables restent légitimes en mode hébergé.
VARIABLES_PERSO_PUR = (
    "DEPART_NOM",
    "DEPART_LATITUDE",
    "DEPART_LONGITUDE",
    "INTERVALS_API_KEY",
    "INTERVALS_ATHLETE_ID",
)

#: Le strict minimum pour qu'une `Config` se construise en mode hébergé tant
#: que le tiers 3 n'est pas complet — voir `SocleTOML.config_ou_comblee`.
#: **Jamais écrit sur disque, jamais présenté comme la valeur de quelqu'un** :
#: seuls `depart.latitude`/`.longitude` et `cycliste.masse_kg` y figurent,
#: parce que ce sont les trois seuls champs de tout `Config` sans aucun
#: défaut ailleurs (`config.py:depuis_dict`) — `cycliste.ftp_w` est déjà
#: facultative, `velos` retombe déjà sur un vélo générique. Les valeurs
#: choisies ne désignent personne : `depart` est le repli du produit
#: (`DEPART_PAR_DEFAUT`, « Paris », `noyau.profil`) — **jamais (0, 0)**, qui
#: n'est le domicile de personne mais n'est pas non plus un lieu où router
#: une boucle (BRouter n'y a pas de carte ; fiche
#: `docs/backlog/2026-09-28-bug-depart-fictif-golfe-de-guinee.md`) — et
#: 70 kg est un poids générique, au même titre que le filet de dernier
#: recours de l'entonnoir d'estimation de FTP — un modèle générique, dit
#: comme tel, pas une donnée devinée sur quelqu'un.
COMBLEMENT_EMBARQUEMENT: dict = {
    "depart": {
        "nom": DEPART_PAR_DEFAUT.nom,
        "latitude": DEPART_PAR_DEFAUT.latitude,
        "longitude": DEPART_PAR_DEFAUT.longitude,
    },
    "cycliste": {"masse_kg": 70.0},
}


def _depart_incomplet(surcharge: dict) -> bool:
    """Vrai si `surcharge["depart"]` (ce que **ce** propriétaire a lui-même
    écrit, jamais le socle — voir `SocleTOML.config_ou_comblee`) ne porte pas
    de quoi construire un départ : absente, ou sans `latitude` ni
    `longitude`. C'est exactement ce que `config._depart_depuis` teste pour
    la même raison côté commandes de comptes — même règle, deux appelants.

    **Dit aussi comment `config_ou_comblee` doit traiter ce `depart`-là** :
    incomplet, il se remplace **en bloc** par `DEPART_PAR_DEFAUT`
    (`_surcharge_sans_depart_incomplet`) plutôt que de se compléter champ par
    champ — un `{"nom": "Chez moi"}` sans coordonnées ne doit pas ressortir
    avec les degrés de Paris dessous, ni un `{"latitude": 3.0}` seul avec
    « Paris » écrit sur un point qui n'est pas le sien.
    """
    depart = surcharge.get("depart")
    if not isinstance(depart, dict):
        return True
    return not {"latitude", "longitude"} <= depart.keys()


def _surcharge_sans_depart_incomplet(surcharge: dict) -> dict:
    """`surcharge`, sans sa clé `depart` quand `_depart_incomplet` la juge incomplète.

    Sert à `config_ou_comblee` : fusionner `COMBLEMENT_EMBARQUEMENT` avec la
    `surcharge` telle quelle compléterait un `depart` partiel champ par champ
    (`fusionner` fusionne les dicts imbriqués), et produirait un point
    hybride — un nom réel sur les coordonnées du repli, ou l'inverse. Retirer
    la clé fait gagner le `depart` du comblement **en entier** à la place.
    """
    if not _depart_incomplet(surcharge):
        return surcharge
    return {cle: valeur for cle, valeur in surcharge.items() if cle != "depart"}


#: Ce qu'un propriétaire a le droit de modifier dans son profil — section
#: par section, et **champ par champ** à l'intérieur d'une section du tiers
#: 2. Liste blanche et non liste noire : un champ inconnu est refusé, pas
#: ignoré — le front doit apprendre son erreur, pas la découvrir en
#: constatant que rien n'a changé.
#:
#: Le découpage suit, littéralement, les trois tiers de la décision Q35 :
#:
#: - **serveur, jamais servi à un cycliste** — absent d'ici, et c'est
#:   volontaire : `cache` (exploitation, pas profil), `brouter` (le serveur
#:   BRouter de l'exploitant, un secret d'infrastructure), `meteo` (modèle,
#:   second avis, horizons — un réglage de méthode) et `calibration`. Ce
#:   dernier trompe par son nom : la section `[calibration]` ne porte que des
#:   réglages de méthode (`mots_groupe`, `part_validation`,
#:   `vitesse_min_kmh`) — le **résultat** d'une calibration, personnel, vit
#:   dans `calibration.json`, pas ici.
#: - **perso, défaut serveur, champ par champ** — `boucle` (seul `sens` :
#:   « horaire » ou « antihoraire » dépend d'où on roule ; `candidates` et
#:   `tolerance_distance` coûtent des appels externes et restent un réglage
#:   de service) et `seance` (seul `position_zone`, décision 7 : on ne
#:   stocke jamais une valeur en watts à côté d'une table qui bouge).
#:   `tenue` appartient à ce tiers **dans le modèle de données**, mais
#:   son interface d'édition attend explicitement la V2 (« même ça attend
#:   la V2 ») : ses seuils ne sont donc **pas encore** dans cette liste
#:   blanche, volontairement.
#: - **perso pur, jamais hérité, jamais deviné** — `depart`, `cycliste`,
#:   `intervals` ci-dessous ; `velos` et `evitements`, des listes qui se
#:   remplacent en entier (`LISTES_MODIFIABLES`) ; `historique_depuis`, un
#:   champ scalaire à la racine du TOML, pas dans une section
#:   (`CHAMPS_RACINE_MODIFIABLES`).
CHAMPS_MODIFIABLES: dict[str, tuple[str, ...]] = {
    "depart": ("nom", "latitude", "longitude"),
    # « prenom » et « nom » : identité du compte, obligatoire pour tout
    # profil créé par l'assistant — mais un profil plus ancien qui ne les
    # porte pas se charge et se modifie normalement
    # (`Cycliste.prenom`, `config.py`). Aucun calcul ne s'en sert aujourd'hui.
    "cycliste": ("masse_kg", "ftp_w", "prenom", "nom"),
    # La position dans la zone, et elle seule : la décision 7 interdit de
    # stocker une valeur en watts à côté d'une table qui bouge.
    "seance": ("position_zone",),
    "intervals": ("athlete_id", "api_key"),
    # Le sens de la boucle, et lui seul : `candidates`/`tolerance_distance`
    # restent un réglage de service.
    "boucle": ("sens",),
}

#: Les tables qui se remplacent en entier plutôt que champ par champ. Un vélo
#: se supprime, se renomme et se réordonne, une zone à éviter aussi :
#: fusionner une liste par index donnerait des résultats que personne ne
#: peut prévoir. `evitements` est personnel, avec un défaut vide.
LISTES_MODIFIABLES = ("velos", "evitements")

#: Les champs scalaires à la racine du TOML — pas dans une section — qu'un
#: propriétaire a le droit d'écrire. Un seul aujourd'hui : `historique_depuis`
#: (perso pur, avec un défaut pour que personne ne parte d'une page blanche :
#: `config.HISTORIQUE_DEPUIS_DEFAUT` ne s'applique qu'à qui n'a rien réglé).
CHAMPS_RACINE_MODIFIABLES = ("historique_depuis",)


def schema_des_modifications() -> dict:
    """Ce que `PATCH /profil` accepte, en schéma publiable.

    **Engendré de `CHAMPS_MODIFIABLES`, qui reste la seule source.** Le corps
    de cette route n'a pas de modèle Pydantic — le décrire une seconde fois
    dupliquerait `Config` et la liste blanche ci-dessus, et les trois
    divergeraient. Mais ne rien publier laisserait la principale route
    d'écriture du produit sans contrat : le front devrait lire `depots.py` pour
    savoir qu'on enregistre `seance.position_zone` et **jamais** des watts
    (décision 7 du cycle UX), ce qui est exactement ce que le schéma est censé
    éviter.

    Les champs sont publiés sans type : la liste blanche n'en porte pas, et
    en inventer un ici serait une deuxième vérité. Ce que le schéma dit, et
    c'est ce dont le front a besoin, c'est **quels champs existent**.
    """
    sections = {
        section: {
            "type": "object",
            "additionalProperties": False,
            "properties": {champ: {} for champ in champs},
        }
        for section, champs in CHAMPS_MODIFIABLES.items()
    }
    sections |= {nom: {"type": "array", "items": {"type": "object"}} for nom in LISTES_MODIFIABLES}
    sections |= {nom: {} for nom in CHAMPS_RACINE_MODIFIABLES}
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": sections,
        "description": "les sections à modifier ; tout champ absent de cette liste est refusé "
        "et nommé, jamais ignoré en silence",
    }


#: Le nom du fichier de profil d'un propriétaire, dans son dossier.
NOM_PROFIL = "profil.json"

#: Le nom du journal des services d'un propriétaire, à côté de son profil.
#: Voir `JournalServices` : il ne porte que des dates, jamais un secret.
NOM_JOURNAL = "services.json"

#: Les extensions de fichier que le dépôt accepte de garder, et leur type de
#: contenu. Fermé : un dépôt de fichiers qui accepte tout est un hébergeur.
EXTENSIONS = {
    ".gpx": "application/gpx+xml",
    ".html": "text/html; charset=utf-8",
    ".zwo": "application/xml",
    ".mrc": "text/plain; charset=utf-8",
}

#: Forme d'un identifiant de fichier : un UUID sans tirets. Vérifiée avant
#: toute construction de chemin — c'est ce qui rend la traversée impossible.
FORME_IDENTIFIANT = re.compile(r"^[0-9a-f]{32}$")

#: Comment on donne un profil à une application qui n'en a pas. Les deux
#: chemins, dans l'ordre où ils servent : l'un pour qui voulait un **service**
#: et s'est trompé de fabrique, l'autre pour qui voulait bien cette fabrique-ci
#: et doit maintenant la remplir.
PHRASE_COMPLETER_PROFIL = (
    "compléter le profil par « PATCH /api/v1/profil », ou lancer le serveur par la "
    "fabrique de service — « ourouler api », c'est-à-dire "
    "« ourouler.api.application:application », qui lit le fichier de configuration"
)

#: Ce que répond une application construite sans rien quand on lui demande des
#: données. Elle ne dit pas ce qui manque à un fichier : elle dit **qu'elle
#: n'a pas de profil**, et comment lui en donner un.
MESSAGE_SANS_PROFIL = (
    "cette application a été construite sans profil : elle publie son contrat "
    "(/docs, /openapi.json) mais n'a ni point de départ, ni vélo, ni clé, et ne peut "
    "donc rien calculer. Elle n'en invente pas — "
    f"{PHRASE_COMPLETER_PROFIL}"
)


class SocleTOML:
    """Le socle lu dans un fichier TOML, relu à chaque requête.

    **Il appartient à quelqu'un.** Un fichier de configuration porte un point
    de départ, une clé Intervals et un identifiant d'athlète : ce n'est pas
    un réglage de serveur, c'est le profil d'une personne. `proprietaire` dit
    de qui, et `DepotProfils` refuse de le servir à un autre — voir
    `DepotProfils.config`.

    `variables` est **reçu**, jamais lu ici : seul `exploitation.py` sait où
    il tourne (le cœur ne lit ni configuration ni environnement), et l'invariant adversarial refuse jusqu'au
    nom `environ` dans le cœur. Vide par défaut, pour qu'une application
    construite dans un test n'absorbe pas les variables de la machine.

    **`proprietaire=None` veut dire « hébergé, ce socle n'est le profil de
    personne » (`application.py`).** Dans ce cas, `config` retire du TOML
    serveur — et rend inertes les variables d'environnement pour — les
    sections perso pur (`SECTIONS_PERSO_PUR`) avant de fusionner la
    surcharge de l'appelant : sans ce retrait, un propriétaire qui n'a pas
    encore écrit son propre `[depart]`/`[cycliste]`/`[[velos]]`/`[intervals]`
    hériterait silencieusement de celui du serveur, ou d'une variable
    `OUROULER_DEPART_*`/`OUROULER_INTERVALS_*` posée pour le déploiement —
    une fuite, que `verifier_proprietaire` (`DepotProfils`) ne refuserait pas puisque ce socle n'appartient
    justement à personne. La surcharge de l'appelant, elle, n'est jamais
    touchée : c'est elle, et seulement elle, qui peut porter ces sections en
    mode hébergé.
    """

    modifiable = True

    def __init__(
        self,
        chemin: Path,
        *,
        variables: Mapping[str, str] | None = None,
        proprietaire: Proprietaire | None = PROPRIETAIRE_LOCAL,
    ) -> None:
        self.chemin = chemin
        self.proprietaire = proprietaire
        self._variables = dict(variables or {})

    def config(self, surcharge: dict) -> Config:
        brut = lire_toml(self.chemin)
        variables = self._variables
        if self.proprietaire is None:
            # `SECTIONS_PERSO_PUR` couvre les sections (des dicts) ;
            # `CHAMPS_RACINE_MODIFIABLES` couvre `historique_depuis`, un
            # champ scalaire à la racine du TOML — perso pur lui aussi
            # mais absent de `SECTIONS_PERSO_PUR` parce que ce n'est
            # pas une section. Sans lui, un propriétaire qui n'écrit rien
            # recevrait la date d'historique du serveur.
            a_taire = {*SECTIONS_PERSO_PUR, *CHAMPS_RACINE_MODIFIABLES}
            brut = {cle: valeur for cle, valeur in brut.items() if cle not in a_taire}
            variables_a_taire = {f"{PREFIXE_ENV}{suffixe}" for suffixe in VARIABLES_PERSO_PUR}
            variables = {cle: valeur for cle, valeur in variables.items() if cle not in variables_a_taire}
        return construire(fusionner(brut, surcharge), environ=variables)

    def config_ou_comblee(self, surcharge: dict) -> Config:
        """Comme `config`, mais ne refuse jamais faute de tiers 3 en mode hébergé.

        **Le problème.** Le découpage en tiers dit deux choses qui se tiennent mal ensemble à
        l'exécution : « le tiers 3 ne s'hérite jamais » (tenu par `config`
        ci-dessus) et « c'est le but de l'assistant d'embarquement de
        remplir ce qui est vide ». Le second suppose qu'on puisse **lire et
        écrire un profil encore vide** — et le front (`Assistant.tsx`) écrit
        le sien en plusieurs `PATCH /profil` successifs et partiels
        (`{cycliste: {prenom, nom}}` d'abord, `{depart}` plus tard…), pendant
        que `App.tsx` interroge `/systeme`, `/profil` et `/profil/zones`
        **sans condition** dès le premier écran, avant la moindre écriture.
        Avec `config` seule, la toute première requête d'un compte fraîchement
        activé — ou d'un compte qui vient d'être effacé puis réinvité, voir
        `tests/comptes/test_vie_privee_comptes_adversarial.py::test_reinviter_la_meme_adresse_repart_de_zero`
        — lève « section [depart] manquante », et l'assistant qui est censé
        la remplir ne peut jamais s'afficher.

        **La réponse retenue ici** : en mode hébergé, quand `config` échoue
        faute de tiers 3, on la retente en comblant *seulement* ce qui n'a
        **aucun défaut ailleurs** — `depart.latitude`/`.longitude` et
        `cycliste.masse_kg`, les trois champs sans quoi `Config` ne se
        construit pas du tout (`COMBLEMENT_EMBARQUEMENT`). Ce comblement
        n'est **jamais écrit** (seule `surcharge` l'est, dans `enregistrer`)
        et n'est **jamais** celui d'une personne réelle : c'est une valeur
        neutre, la même pour tout le monde, à l'opposé de la fuite fermée
        plus haut qui servait le départ ou le poids *réels* de quelqu'un.
        `assistant_recommande` (`api/routes/`) dit déjà au front que ce
        qu'il reçoit est provisoire — c'est le signal existant, pas un
        nouveau.

        **Ce que ça ne change pas** : un propriétaire qui a écrit une valeur
        fausse (une FTP hors bornes, une latitude à 200°) continue d'être
        refusé — le comblement ne porte que sur ce qui **manque**, jamais sur
        ce qui est **présent et invalide** ; `fusionner` fait gagner la
        surcharge de l'appelant sur le comblement, champ par champ.

        **Sauf `depart`, qui se comble en bloc et non champ par champ**
        (`_surcharge_sans_depart_incomplet`) : un `depart` incomplet
        (`_depart_incomplet`) n'entre pas dans la fusion, pour que le repli
        fournisse `nom`, `latitude` et `longitude` ensemble plutôt qu'un
        mélange — sans quoi `{"depart": {"nom": "Chez moi"}}` ressortirait
        avec les coordonnées de Paris sous ce nom-là, et
        `{"depart": {"latitude": 3.0}}` avec « Paris » écrit sur un point qui
        n'est pas le sien.

        **`config.depart.par_defaut` dit si *ce* comblement a servi pour le
        départ** — fiche `docs/backlog/2026-09-28-bug-depart-fictif-golfe-de-guinee.md` :
        avant d'appeler `COMBLEMENT_EMBARQUEMENT` (qui peut être sollicité
        pour `cycliste` seul), on regarde `surcharge["depart"]`, la seule
        source du départ d'un socle hébergé (`SocleTOML.config` en retire
        déjà celui du socle) — jamais la `Config` reconstruite, qui ne
        distingue plus une coordonnée réelle qui vaudrait par hasard celle du
        repli. Absente, ou sans `latitude` ni `longitude` : ce propriétaire
        n'a pas encore écrit son départ, le comblement l'a fourni, et l'API
        (`api/routes/generations.py`) comme le front (bandeau « Départ par
        défaut ») ont besoin de le savoir.
        """
        try:
            return self.config(surcharge)
        except ErreurConfig:
            if self.proprietaire is not None:
                raise
            depart_incomplet = _depart_incomplet(surcharge)
            config = self.config(
                fusionner(COMBLEMENT_EMBARQUEMENT, _surcharge_sans_depart_incomplet(surcharge))
            )
            if depart_incomplet:
                config = replace(config, depart=replace(config.depart, par_defaut=True))
            return config

    def dossier_cache(self) -> Path:
        """Le dossier de cache du **serveur**, sans construire de `Config`.

        `[cache]` est un réglage serveur, qui ne dépend d'aucune
        section perso pur : l'obtenir ne doit donc pas exiger qu'un
        propriétaire ait déjà écrit son départ ou son cycliste — ce qu'un
        socle hébergé sans surcharge ne garantit pas depuis `config`
        ci-dessus. Sert `DepotProfils.dossier_cache` (export et suppression
        RGPD, `api/vie_privee.py`).
        """
        return dossier_cache_depuis(lire_toml(self.chemin))


class SocleVide:
    """Aucun profil de départ : tout vient de la surcharge du propriétaire.

    C'est le socle d'une application construite sans rien — `creer_application()`.
    Elle publie son contrat (`/openapi.json`, `/docs`) et sert ses routes,
    mais tant que personne n'a écrit de profil, les routes de données
    refusent. C'est volontaire : inventer un point de départ par défaut
    mettrait une coordonnée dans le code (aucune donnée personnelle dans le
    dépôt), et aller le chercher sur le disque ferait lire l'environnement à
    la fabrique (le cœur ne lit ni configuration ni environnement).

    **Ce qu'elles répondent compte.** Un refus `configuration_invalide` avec,
    pour toute explication, « section [depart] manquante » décrirait un
    fichier TOML que l'appelant n'a jamais eu l'intention d'écrire, et
    laisserait croire à une configuration cassée là où il n'y en a aucune :
    l'application démarrerait et annoncerait « configuration invalide » sur
    tout.
    """

    modifiable = True
    proprietaire: Proprietaire | None = None

    def config(self, surcharge: dict) -> Config:
        if not surcharge:
            raise ErreurProfilAbsent(MESSAGE_SANS_PROFIL)
        try:
            return construire(dict(surcharge), environ={})
        except ErreurConfig as e:
            # Un profil a été commencé mais ne tient pas encore : là, l'erreur
            # de validation est la bonne information — elle nomme ce qui
            # manque à ce que l'appelant a lui-même écrit. On la garde, en
            # disant seulement d'où elle vient, parce qu'aucun fichier n'est
            # en cause ici non plus.
            raise ErreurProfilAbsent(
                f"le profil de cette application est incomplet : {e} — {PHRASE_COMPLETER_PROFIL}"
            ) from e

    def config_ou_comblee(self, surcharge: dict) -> Config:
        """Identique à `config` : pas de socle serveur, donc rien à combler.

        Le comblement de `SocleTOML.config_ou_comblee` répond à un socle
        **partagé** qui ne fournit pas le tiers 3 ; `SocleVide` n'a
        jamais rien fourni du tout, et `ErreurProfilAbsent` — avec son
        message qui dit déjà comment compléter le profil — reste la réponse
        la plus honnête ici.
        """
        return self.config(surcharge)

    def dossier_cache(self) -> Path:
        """Aucun fichier ici : le défaut du cœur (`CACHE_DEFAUT`)."""
        return CACHE_DEFAUT


class SocleFixe:
    """Une `Config` déjà construite, injectée par l'appelant.

    Le point d'injection des tests sans réseau ni disque : un test — et demain la
    couche qui lira le profil dans PostgreSQL — donne une `Config` toute
    faite, sans fichier ni environnement. Lecture seule : il n'y a pas de
    dict TOML sous cette `Config` sur lequel fusionner une surcharge, et
    fabriquer un dict à partir d'une dataclasse validée rendrait un socle qui
    n'est plus celui qu'on a injecté. `enregistrer` refuse donc en le disant.
    """

    modifiable = False
    proprietaire: Proprietaire | None = None

    def __init__(self, config: Config) -> None:
        self._config = config

    def config(self, surcharge: dict) -> Config:
        del surcharge  # aucune ne peut exister : `enregistrer` refuse d'en écrire
        return self._config

    def config_ou_comblee(self, surcharge: dict) -> Config:
        """Identique à `config` : une `Config` injectée est toujours complète."""
        return self.config(surcharge)

    def dossier_cache(self) -> Path:
        return self._config.cache.dossier


class DepotProfils:
    """Le profil de chaque propriétaire, et la `Config` qui en sort.

    Le **socle** porte ce qu'aucun cycliste n'édite (cache, serveur BRouter,
    modèles météo). Le profil d'un propriétaire est une **surcharge** JSON,
    rangée dans son dossier, appliquée par-dessus avant validation.

    **Pourquoi ne pas réécrire le TOML.** Trois raisons, dans l'ordre : le
    fichier de l'exploitant porte ses commentaires et ses réglages fins, et un
    service web qui le réécrit les perd ; il n'y a qu'un fichier pour tous
    les propriétaires, donc y écrire ferait fuir le profil de l'un dans celui
    de l'autre ; et la surcharge par propriétaire est
    exactement la forme de la table PostgreSQL de demain (doctrine §10.1 :
    « `Config` gagnera un identifiant d'utilisateur et sera chargée depuis la
    base au lieu d'un TOML : le cœur ne le verra pas »).
    """

    def __init__(self, socle: SocleTOML | SocleVide | SocleFixe, dossier_donnees: Path) -> None:
        self._socle = socle
        self._dossier = dossier_donnees

    def dossier(self, proprietaire: Proprietaire) -> Path:
        """Le dossier de ce propriétaire, créé au besoin. La clause, en chemin."""
        chemin = self._dossier / proprietaire.identifiant
        chemin.mkdir(parents=True, exist_ok=True)
        return chemin

    def surcharge(self, proprietaire: Proprietaire) -> dict:
        """Ce que ce propriétaire a modifié, ou un dict vide."""
        chemin = self.dossier(proprietaire) / NOM_PROFIL
        if not chemin.is_file():
            return {}
        try:
            charge = json.loads(chemin.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError) as e:
            raise ErreurConfig(f"{chemin} : profil illisible ({e})") from e
        if not isinstance(charge, dict):
            raise ErreurConfig(f"{chemin} : profil attendu sous forme d'objet")
        return charge

    def config(self, proprietaire: Proprietaire) -> Config:
        """La `Config` de ce propriétaire : le socle, sa surcharge, puis la validation.

        **Un socle qui appartient à quelqu'un ne se sert qu'à lui.** Sans ce
        contrôle, tout ce qu'un propriétaire ne surcharge pas, il en hérite —
        y compris `[intervals] api_key`, `athlete_id` et `[depart]`, c'est-à-dire
        la clé et le domicile de l'exploitant, une fuite silencieuse : la surcharge par
        propriétaire n'a jamais eu pour but de partager les secrets du socle,
        seulement d'éviter de réécrire un TOML commenté.

        En mode **personnel**, le refus reste volontairement **total** — pas de
        socle personnel d'un autre propriétaire servi même pour ses seules
        sections « serveur » : le TOML du serveur y est le profil de
        son cycliste, et rien de ce qu'il porte — même `[cache]`, même
        `[meteo]` — n'a de sens pour quelqu'un d'autre.

        **En mode hébergé** (`socle.proprietaire is None`), ce contrôle-ci ne
        s'applique à personne, puisque le socle n'appartient justement à
        personne — l'invariant tient alors en deux moitiés. `SocleTOML.config`
        applique le découpage en tiers (décision Q35), section par section, pour que
        le tiers 3 (perso pur) ne soit jamais hérité du socle commun.
        `CHAMPS_MODIFIABLES`, `LISTES_MODIFIABLES` et `CHAMPS_RACINE_MODIFIABLES`
        plus haut appliquent le même découpage à **la propre surcharge d'un
        propriétaire** par-dessus ce socle. Ce que ce contrôle-ci refuse
        encore, dans les deux modes, est différent des deux : faire
        *partager* le socle TOML d'**une personne** (le cycliste du mode
        personnel) à un **autre** propriétaire, même limité aux sections
        serveur — c'est le partage d'un socle entre plusieurs comptes, qui
        reste à construire (doctrine §10.1 : `Config` viendra de
        PostgreSQL, pas d'un TOML propre à quelqu'un). Jusque-là, refuser est
        ce qui se fait de moins faux.

        **`config_ou_comblee`, pas `config`** : en mode hébergé,
        un propriétaire qui n'a pas encore complété son tiers 3 doit quand
        même pouvoir être lu — c'est le cas d'un compte tout juste activé,
        avant sa première écriture, que le front interroge sans condition au
        démarrage (`front/src/App.tsx`). Voir `SocleTOML.config_ou_comblee`
        pour ce que ça comble et pourquoi ce n'est pas une fuite du socle.
        """
        self.verifier_proprietaire(proprietaire)
        return self._socle.config_ou_comblee(self.surcharge(proprietaire))

    def verifier_proprietaire(self, proprietaire: Proprietaire) -> None:
        """Le seul contrôle de `config` qui vaille aussi **avant** une écriture.

        Il était fait en appelant `config` — donc en validant au passage un
        profil qu'on s'apprêtait justement à compléter. Sur une application au
        socle vide, cela rendait `PATCH /profil` impossible : la seule façon de
        donner un profil à cette application était refusée parce qu'elle n'en
        avait pas encore. La documentation de `SocleVide` promettait pourtant
        ce chemin-là depuis le début.
        """
        possesseur = self._socle.proprietaire
        if possesseur is not None and possesseur != proprietaire:
            raise ErreurConfig(
                f"profil de « {proprietaire} » : le socle de ce serveur est le profil de "
                f"« {possesseur} » (départ, clé Intervals) et ne se partage pas — ce serveur "
                "n'a pas de configuration pour ce propriétaire"
            )

    def enregistrer(self, proprietaire: Proprietaire, modifications: dict) -> Config:
        """Applique des modifications au profil, et rend la `Config` qui en résulte.

        Rien n'est écrit tant que ce qui est **donné** n'est pas individuellement
        valide : une FTP négative ou un vélo sans nom laisse le profil
        précédent intact, et le front reçoit le nom du champ fautif.

        **Une écriture partielle, elle, n'est pas refusée en mode hébergé**
        (`config_ou_comblee`) : l'assistant d'embarquement écrit
        son profil en plusieurs `PATCH /profil` (`front/src/ecrans/Assistant.tsx`,
        `{cycliste: {prenom, nom}}` d'abord, `{depart}` plus tard…), et le
        premier de ces appels, avant que `depart` existe, ne doit pas être
        pris pour une configuration invalide. Ce qui est réellement écrit sur
        le disque, `proposee`, ne porte jamais le comblement — seulement ce
        que ce propriétaire a lui-même donné.
        """
        if not self._socle.modifiable:
            raise ErreurUtilisateur(
                "profil : cette application sert une configuration injectée, en lecture seule — "
                "la construire depuis un fichier de configuration pour pouvoir la modifier"
            )
        self.verifier_proprietaire(proprietaire)  # même contrôle qu'en lecture
        proposee = fusionner(self.surcharge(proprietaire), valider(modifications))
        config = self._socle.config_ou_comblee(proposee)  # lève ErreurConfig si vraiment invalide
        ecrire_toml(
            self.dossier(proprietaire) / NOM_PROFIL,
            json.dumps(proposee, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        )
        return config

    def supprimer_profil(self, proprietaire: Proprietaire) -> bool:
        """Efface la surcharge de ce propriétaire. Rend vrai si elle existait.

        **Le socle n'est jamais touché** — ni celui du serveur, ni celui d'un
        autre propriétaire : ce n'est la donnée de personne qui demande son
        effacement. Pas de vérification de
        propriétaire ici, contrairement à `config`/`enregistrer` : le chemin
        est déjà borné au dossier de **ce** propriétaire (`dossier`), il n'y a
        rien à protéger de plus qu'une écriture normale ne protège déjà.
        """
        chemin = self.dossier(proprietaire) / NOM_PROFIL
        existait = chemin.is_file()
        chemin.unlink(missing_ok=True)
        return existait


@dataclass(frozen=True)
class Fichier:
    """Un fichier du dépôt : son identifiant opaque, son nom et son chemin."""

    identifiant: str
    nom: str
    chemin: Path
    type_contenu: str

    def json(self) -> dict:
        """Ce que le front reçoit : jamais le chemin sur le disque du serveur."""
        return {
            "id": self.identifiant,
            "nom": self.nom,
            "url": f"/api/v1/fichiers/{self.identifiant}",
        }


class DepotFichiers:
    """Les fichiers d'un propriétaire, adressés par un identifiant opaque.

    Un chemin de disque ne sort jamais d'ici : il dit où le serveur est
    installé, il ne sert à rien au front, et il invite à demander le fichier
    du voisin. L'identifiant, lui, ne dit rien — et le dépôt vérifie qu'il
    appartient bien au propriétaire qui le demande, **côté serveur**
    (doctrine §10.2), en le cherchant dans son dossier et nulle part ailleurs.
    """

    def __init__(self, dossier_donnees: Path) -> None:
        self._dossier = dossier_donnees

    def dossier(self, proprietaire: Proprietaire) -> Path:
        chemin = self._dossier / proprietaire.identifiant / "fichiers"
        chemin.mkdir(parents=True, exist_ok=True)
        return chemin

    def reserver(self, proprietaire: Proprietaire, nom: str) -> Fichier:
        """Un emplacement neuf pour un fichier que le cœur va écrire.

        `nom` sert à nommer le téléchargement côté navigateur ; il ne sert
        jamais à construire le chemin — c'est l'identifiant qui le fait — et
        il est assaini avant d'être gardé (`nom_sur`).
        """
        extension = _extension(nom)
        identifiant = uuid.uuid4().hex
        return Fichier(
            identifiant=identifiant,
            nom=nom_sur(nom),
            chemin=self.dossier(proprietaire) / f"{identifiant}{extension}",
            type_contenu=EXTENSIONS[extension],
        )

    def deposer(self, proprietaire: Proprietaire, nom: str, contenu: bytes) -> Fichier:
        """Range un fichier envoyé par le front (un `.ZWO`, un `.MRC`) et rend sa fiche."""
        fichier = self.reserver(proprietaire, nom)
        fichier.chemin.write_bytes(contenu)
        _ecrire_nom(fichier)
        return fichier

    def enregistrer(self, proprietaire: Proprietaire, fichier: Fichier) -> Fichier:
        """Note le nom d'affichage d'un fichier que le cœur vient d'écrire.

        Vérifie que le fichier est bien dans le dossier de ce propriétaire :
        la clause ne se contente pas d'être dans la signature, elle est
        contrôlée — c'est ce que la doctrine appelle « vérifiée côté serveur ».
        """
        if fichier.chemin.parent != self.dossier(proprietaire):
            raise ErreurUtilisateur(f"fichier {fichier.identifiant} : n'appartient pas à ce propriétaire")
        _ecrire_nom(fichier)
        return fichier

    def trouver(self, proprietaire: Proprietaire, identifiant: str) -> Fichier:
        """Le fichier de **ce** propriétaire portant cet identifiant.

        Lève `ErreurUtilisateur` si l'identifiant est mal formé ou si le
        fichier n'est pas dans le dossier de ce propriétaire — les deux cas
        se répondent de la même façon au front, qui n'a pas à apprendre si le
        fichier existe ailleurs.
        """
        if not FORME_IDENTIFIANT.match(identifiant or ""):
            raise ErreurUtilisateur(f"fichier {identifiant!r} : identifiant inconnu")
        dossier = self.dossier(proprietaire)
        for chemin in sorted(dossier.glob(f"{identifiant}.*")):
            if chemin.suffix == ".nom":
                continue
            nom = _lire_nom(chemin) or chemin.name
            return Fichier(
                identifiant=identifiant,
                nom=nom,
                chemin=chemin,
                type_contenu=EXTENSIONS.get(chemin.suffix, "application/octet-stream"),
            )
        raise ErreurUtilisateur(f"fichier {identifiant} : introuvable")

    def lister(self, proprietaire: Proprietaire) -> list[Fichier]:
        """Tous les fichiers de ce propriétaire — pour l'export.

        Même filtrage que `trouver` (l'extension, le sidecar `.nom` écarté) :
        c'est la même notion de « fichier de ce propriétaire », lue en une
        fois plutôt qu'identifiant par identifiant.
        """
        fichiers = []
        for chemin in sorted(self.dossier(proprietaire).glob("*")):
            if not chemin.is_file() or chemin.suffix == ".nom" or chemin.suffix not in EXTENSIONS:
                continue
            fichiers.append(
                Fichier(
                    identifiant=chemin.stem,
                    nom=_lire_nom(chemin) or chemin.name,
                    chemin=chemin,
                    type_contenu=EXTENSIONS.get(chemin.suffix, "application/octet-stream"),
                )
            )
        return fichiers

    def supprimer_tout(self, proprietaire: Proprietaire) -> int:
        """Efface tous les fichiers de ce propriétaire (et leur nom d'affichage).

        Rend le nombre de fichiers effacés. Le dossier lui-même disparaît
        s'il est vide ensuite ; s'il ne l'est pas (un dépôt concurrent y a
        écrit entre-temps), il reste — ce n'est pas une erreur.
        """
        dossier = self.dossier(proprietaire)
        fichiers = self.lister(proprietaire)
        for fichier in fichiers:
            fichier.chemin.unlink(missing_ok=True)
            _fichier_nom(fichier).unlink(missing_ok=True)
        try:
            dossier.rmdir()
        except OSError:
            pass
        return len(fichiers)


#: Combien de générations de parcours on garde, par serveur. Chacune pèse ses
#: deux ou trois GPX — 65 ko l'un, mesuré — soit ~4 Mo au
#: plafond. Court exprès : un cycliste choisit sa boucle dans la minute qui
#: suit, pas le lendemain.
GENERATIONS_GARDEES = 20


class DepotGenerations:
    """Les GPX des propositions d'une génération, gardés jusqu'au choix.

    **Aucun GPX à la génération, un GPX à la demande quand le cycliste choisit
    son parcours** (décision Q40 g, `docs/journal/questions/questions_mainteneur.md`).
    Écrire les trois, ce serait en jeter deux à chaque fois ; n'écrire que
    celle du classement, ce serait envoyer la mauvaise trace au compteur à qui choisissait « la plus
    sèche ». Ici **rien n'est écrit** : ni à la génération, ni au choix — la
    route rend le contenu, elle ne range pas un fichier de plus à chaque clic.

    **En mémoire, et borné.** Une génération qui n'y est plus — plafond
    atteint, ou serveur redémarré — lève `ErreurUtilisateur`, et la route
    répond 404 `generation_introuvable` : l'écran redemande une recherche,
    ce qui est honnête et prend cinq secondes. La tenir sur le disque
    coûterait exactement ce que la décision voulait éviter, puisque la
    géométrie d'une trace pèse ce que pèse son GPX.

    Les propositions reçues sont des `services.sortie.GpxPropose`, mais le
    dépôt n'en connaît que trois attributs (`numero`, `nom_fichier`, `texte`)
    et n'importe pas le cœur : il range des couples, pas des objets du cœur.
    """

    def __init__(self, taille: int = GENERATIONS_GARDEES) -> None:
        self._taille = max(int(taille), 1)
        self._generations: OrderedDict[tuple[str, str], dict[int, tuple[str, str]]] = OrderedDict()

    def retenir(self, proprietaire: Proprietaire, propositions: Iterable[object]) -> str:
        """Range les GPX d'une génération et rend son identifiant opaque."""
        par_numero = {int(p.numero): (str(p.nom_fichier), str(p.texte)) for p in propositions}
        identifiant = uuid.uuid4().hex
        self._generations[(proprietaire.identifiant, identifiant)] = par_numero
        while len(self._generations) > self._taille:
            self._generations.popitem(last=False)
        return identifiant

    def gpx(self, proprietaire: Proprietaire, identifiant: str, numero: int) -> tuple[str, str]:
        """(nom de fichier, contenu GPX) de **cette** proposition, pour ce propriétaire.

        La clé porte le propriétaire : l'identifiant d'un autre est
        introuvable ici, sans que la réponse dise s'il existe ailleurs —
        même règle que `DepotFichiers.trouver` (doctrine §10.2).
        """
        if not FORME_IDENTIFIANT.match(identifiant or ""):
            raise ErreurUtilisateur(f"génération {identifiant!r} : identifiant inconnu")
        generation = self._generations.get((proprietaire.identifiant, identifiant))
        if generation is None:
            raise ErreurUtilisateur(
                f"génération {identifiant} : introuvable — elle n'est plus en mémoire "
                "(serveur redémarré, ou trop de générations depuis) ; relancer la recherche"
            )
        gpx = generation.get(int(numero))
        if gpx is None:
            raise ErreurUtilisateur(
                f"génération {identifiant} : aucune proposition n° {numero} "
                f"(numéros servis : {', '.join(str(n) for n in sorted(generation))})"
            )
        return gpx

    def supprimer(self, proprietaire: Proprietaire) -> int:
        """Purge les générations en mémoire de ce propriétaire.

        Rien n'est écrit sur le disque : il n'y a donc qu'un dict à
        vider, mais la suppression n'est complète que si on le fait — sans
        ça, `.../propositions/{n}/gpx` continuerait de servir un GPX à
        quelqu'un dont on vient d'effacer le reste.
        """
        cles = [cle for cle in self._generations if cle[0] == proprietaire.identifiant]
        for cle in cles:
            del self._generations[cle]
        return len(cles)


#: Ce qu'un nom d'affichage a le droit de contenir. Tout le reste devient un
#: tiret bas. Fermé parce que ce nom **ressort dans un en-tête HTTP**
#: (`Content-Disposition`) : un guillemet y coupe l'en-tête, un retour chariot
#: en ajoute un autre. Le nom vient du front, donc de n'importe où.
CARACTERES_NOM = re.compile(r"[^A-Za-z0-9 ._-]")

#: Longueur maximale d'un nom d'affichage.
NOM_MAX = 120

#: Quand il ne reste rien du nom proposé.
NOM_PAR_DEFAUT = "fichier"


def nom_sur(nom: str) -> str:
    """Le nom d'affichage, réduit à son dernier segment et à des caractères sûrs."""
    base = str(nom or "").replace("\\", "/").rsplit("/", 1)[-1]
    propre = CARACTERES_NOM.sub("_", base).strip(" .")[:NOM_MAX]
    return propre or NOM_PAR_DEFAUT


def _extension(nom: str) -> str:
    extension = Path(nom).suffix.lower()
    if extension not in EXTENSIONS:
        raise ErreurUtilisateur(
            f"{nom} : extension {extension or 'absente'} refusée — attendu une de "
            f"{', '.join(sorted(EXTENSIONS))}"
        )
    return extension


def _fichier_nom(fichier: Fichier) -> Path:
    return fichier.chemin.with_suffix(".nom")


def _ecrire_nom(fichier: Fichier) -> None:
    """Le nom d'affichage, à côté du fichier. Un index SQLite serait de trop ici."""
    try:
        _fichier_nom(fichier).write_text(fichier.nom, encoding="utf-8")
    except OSError:  # pragma: no cover - le dossier vient d'être créé
        pass


def _lire_nom(chemin: Path) -> str | None:
    try:
        return chemin.with_suffix(".nom").read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def valider(modifications: dict) -> dict:
    """Ne garde que ce qu'un propriétaire a le droit de modifier. Refuse le reste.

    Refuser plutôt qu'ignorer : un champ tu, c'est un front qui croit avoir
    enregistré quelque chose. Le message nomme le champ.
    """
    if not isinstance(modifications, dict):
        raise ErreurUtilisateur("profil : objet attendu")
    propre: dict = {}
    modifiables = sorted([*CHAMPS_MODIFIABLES, *LISTES_MODIFIABLES, *CHAMPS_RACINE_MODIFIABLES])
    for section, contenu in modifications.items():
        if section in CHAMPS_RACINE_MODIFIABLES:
            # Champ scalaire à la racine (`historique_depuis`) : pas de sous-champ
            # à filtrer, mais pas non plus de section ou de liste ici.
            if isinstance(contenu, (dict, list)):
                raise ErreurUtilisateur(f"profil : « {section} » attendu sous forme de valeur simple")
            propre[section] = contenu
            continue
        if section in LISTES_MODIFIABLES:
            if not isinstance(contenu, list):
                raise ErreurUtilisateur(f"profil : « {section} » attendu sous forme de liste")
            propre[section] = contenu
            continue
        if section not in CHAMPS_MODIFIABLES:
            raise ErreurUtilisateur(
                f"profil : « {section} » n'est pas modifiable depuis l'interface — "
                f"modifiables : {', '.join(modifiables)}"
            )
        if not isinstance(contenu, dict):
            raise ErreurUtilisateur(f"profil : « {section} » attendu sous forme d'objet")
        autorises = CHAMPS_MODIFIABLES[section]
        for champ in contenu:
            if champ not in autorises:
                raise ErreurUtilisateur(
                    f"profil : « {section}.{champ} » n'est pas modifiable — "
                    f"modifiables dans cette section : {', '.join(autorises)}"
                )
        propre[section] = dict(contenu)
    return propre


def fusionner(socle: dict, surcharge: dict) -> dict:
    """Le socle, recouvert par la surcharge. Une section se complète, une liste se remplace.

    Ne mute ni l'un ni l'autre : les deux peuvent être relus ailleurs.
    """
    resultat = dict(socle)
    for cle, valeur in surcharge.items():
        ancien = resultat.get(cle)
        if isinstance(ancien, dict) and isinstance(valeur, dict):
            resultat[cle] = fusionner(ancien, valeur)
        else:
            resultat[cle] = valeur
    return resultat


class JournalServices:
    """Quand chaque service externe a **répondu pour de bon** à ce propriétaire.

    Une seule chose à mémoriser, et E15 · échec dit pourquoi : « "Plus lues
    depuis le 12 septembre" dit à quelqu'un ce qu'il a manqué ; "erreur de
    connexion" ne dit rien. » Cette date-là n'est pas déductible côté front —
    elle suppose qu'on ait retenu quand la clé marchait encore — et elle n'est
    pas non plus déductible côté cœur, qui ne sait pas qu'il a un appelant
    (le cœur ne lit ni configuration ni environnement). Elle appartient donc à l'API, par propriétaire.

    **Un fichier JSON à côté du profil, et c'est assez.** Ce n'est pas une
    donnée qu'on perd gravement : au pire le front n'affiche pas de date la
    première fois, ce qui est exactement l'état d'un compte neuf. Une écriture
    qui échoue ne fait donc jamais échouer une requête — ce serait échanger un
    écran un peu moins bon contre un écran cassé.
    """

    def __init__(self, dossier_donnees: Path) -> None:
        self._dossier = dossier_donnees

    def _chemin(self, proprietaire: Proprietaire) -> Path:
        chemin = self._dossier / proprietaire.identifiant
        chemin.mkdir(parents=True, exist_ok=True)
        return chemin / NOM_JOURNAL

    def _lire(self, proprietaire: Proprietaire) -> dict:
        chemin = self._chemin(proprietaire)
        if not chemin.is_file():
            return {}
        try:
            charge = json.loads(chemin.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            # Un journal illisible se réécrit ; il ne fait pas tomber l'écran
            # qu'il est censé enrichir.
            return {}
        return charge if isinstance(charge, dict) else {}

    def noter_succes(self, proprietaire: Proprietaire, *services: str, quand: datetime | None = None) -> None:
        """Retient que ces services ont répondu, maintenant."""
        if not services:
            return
        horodatage = (quand or datetime.now(UTC)).isoformat()
        charge = self._lire(proprietaire) | {service: horodatage for service in services}
        try:
            self._chemin(proprietaire).write_text(
                json.dumps(charge, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except OSError:
            return

    def dernier_succes(self, proprietaire: Proprietaire, service: str) -> str | None:
        """La date du dernier succès de ce service, ou `None` s'il n'y en a jamais eu."""
        valeur = self._lire(proprietaire).get(service)
        return valeur if isinstance(valeur, str) else None

    def tout(self, proprietaire: Proprietaire) -> dict:
        """Le journal complet de ce propriétaire — un instantané, pour l'export."""
        return dict(self._lire(proprietaire))

    def supprimer(self, proprietaire: Proprietaire) -> bool:
        """Efface le journal de ce propriétaire. Rend vrai s'il existait.

        `unlink(missing_ok=True)` plutôt que `if existait: unlink()` : deux
        `DELETE /moi` réellement simultanés sur le même propriétaire peuvent
        voir tous les deux `is_file() == True`, et le second lèverait alors
        `FileNotFoundError` (500) au lieu de rester idempotent. Même précaution
        que `DepotFichiers.supprimer_tout` plus haut.
        """
        chemin = self._chemin(proprietaire)
        existait = chemin.is_file()
        chemin.unlink(missing_ok=True)
        return existait


__all__ = [
    "CHAMPS_MODIFIABLES",
    "CHAMPS_RACINE_MODIFIABLES",
    "COMBLEMENT_EMBARQUEMENT",
    "EXTENSIONS",
    "GENERATIONS_GARDEES",
    "LISTES_MODIFIABLES",
    "NOM_JOURNAL",
    "SECTIONS_PERSO_PUR",
    "VARIABLES_PERSO_PUR",
    "DepotFichiers",
    "DepotGenerations",
    "DepotProfils",
    "Fichier",
    "JournalServices",
    "SocleFixe",
    "SocleTOML",
    "SocleVide",
    "fusionner",
    "nom_sur",
    "valider",
]
