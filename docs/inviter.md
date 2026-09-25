# Inviter quelqu'un sur où rouler

Mode d'emploi opérationnel du lot L9.5 (`docs/sprint9_contrat.md`). Ce
document ne redécide rien : il pointe vers le code qui fait foi, avec ses
chemins exacts, pour que le mainteneur puisse vérifier lui-même chaque
affirmation.

## 1. Avant la première invitation (une fois)

Le service hébergé (`docker-compose.api.coolify.yml`, à la racine du dépôt)
doit déjà tourner sur Coolify — voir `deploiement/api/README.md` pour le
déploiement complet. Trois choses à vérifier avant d'inviter qui que ce
soit :

### La branche suivie

Le service Coolify suit une branche du dépôt (posée à la création du
service, dans son panneau Coolify — pas dans un fichier de ce dépôt). Le
lot L9.5 ne change rien à ce réglage ; il se vérifie dans l'interface
Coolify elle-même.

### Le mode et la base de données

Dans `docker-compose.api.coolify.yml` (bloc `environment:`) :

- `OUROULER_MODE=${OUROULER_MODE}` — doit valoir `heberge` pour plusieurs
  cyclistes. Sans variable posée, le comportement par défaut du code
  (`api/exploitation.fournisseur_session`) est déjà `heberge` — mais le
  compose la répète pour ne rien laisser deviner.
- `OUROULER_DATABASE_URL=${OUROULER_DATABASE_URL}` — sans elle,
  `api/exploitation.fournisseur_session` rend `SessionHebergee`, qui
  n'ouvre jamais de compte : les quatre routes de comptes répondent que ce
  déploiement n'en gère pas. C'est le geste qui **allume** la fonction
  compte, à poser dans le panneau Coolify.

### Les secrets SMTP et les quotas

Deux fichiers TOML encodés en base64, distincts et tous deux à préparer
hors du dépôt :

- `service.example.toml` (racine du dépôt) — section `[brevo]` (six
  champs : `serveur`, `port`, `utilisateur`, `mot_de_passe`, `expediteur`,
  `nom_expediteur`, voir `src/ourouler/api/courriel.py:CHAMPS_REQUIS_BREVO`)
  pour le relais SMTP qui porte les invitations, et section `[quotas]`
  (`generations_par_jour = 20`, `consultations_meteo_par_jour = 100` —
  défauts documentés dans `src/ourouler/api/quotas.py`, facultative :
  absente, les défauts du code s'appliquent). Encodé dans
  `OUROULER_SERVICE_TOML_B64` (`- OUROULER_SERVICE_TOML_B64=${OUROULER_SERVICE_TOML_B64:-}`
  dans le compose). **Sans lui, `ourouler inviter` (hors `--sans-courriel`)
  refuse en disant que le fichier manque** — voir `_charger_service` dans
  `src/ourouler/cli.py`.
- `deploiement/api/config.example.toml` — le profil TOML non-secrets du
  conteneur. Encodé dans `OUROULER_CONFIG_TOML_B64`.

### L'action Q66a : vider les variables perso pur

Fermée le 22/09/2026 (`docs/questions_mainteneur.md`, Q66) : en mode
`heberge`, l'API **refuse de démarrer** si le TOML ou l'environnement du
serveur portent une valeur perso pur — parce qu'un serveur partagé qui les
porte les distribue à chaque personne invitée. Les noms exacts, lus par le
code (`src/ourouler/api/depots.py:SECTIONS_PERSO_PUR`,
`VARIABLES_PERSO_PUR`, `CHAMPS_RACINE_MODIFIABLES`) :

- Sections TOML à retirer : `[depart]`, `[cycliste]`, `[[velos]]`,
  `[intervals]`. `deploiement/api/config.example.toml`, tel qu'il est
  aujourd'hui, ne porte déjà ni `[depart]` ni `[intervals]` (voir sa
  docstring) — il ne reste donc à retirer que `[cycliste]` et `[[velos]]`
  avant de l'encoder.
- Champ racine à retirer : `historique_depuis`.
- Variables d'environnement à laisser **vides** dans le panneau Coolify :
  `OUROULER_DEPART_NOM`, `OUROULER_DEPART_LATITUDE`,
  `OUROULER_DEPART_LONGITUDE`, `OUROULER_INTERVALS_API_KEY`,
  `OUROULER_INTERVALS_ATHLETE_ID` (les cinq déjà nommées, sans valeur,
  dans `docker-compose.api.coolify.yml`).

Reconstruire `OUROULER_CONFIG_TOML_B64` sur macOS, à partir du modèle du
dépôt, en retirant `[cycliste]` et `[[velos]]` :

```bash
awk '/^\[cycliste\]/{skip=1} /^\[meteo\]/{skip=0} !skip' \
  deploiement/api/config.example.toml > /tmp/config-heberge.toml
base64 -i /tmp/config-heberge.toml
```

(Vérifier le résultat à l'œil avant de coller : `[cycliste]` et `[[velos]]`
doivent avoir disparu, `[meteo]` et la suite doivent rester intacts — la
commande `awk` ci-dessus suppose que `[meteo]` suit directement `[[velos]]`
dans le fichier, comme c'est le cas aujourd'hui ; si l'ordre des sections
change, l'éditer à la main plutôt que faire confiance à `awk`.)

**Ce qui arrive si une de ces variables ou sections est oubliée** : l'API
refuse de démarrer, avec un message qui nomme précisément ce qui est en
trop (`src/ourouler/api/application.py:_refuser_une_base_partagee`,
`ErreurConfig`) — pas un 500 silencieux, un refus lisible dans les logs du
conteneur.

## 2. Inviter quelqu'un

Depuis la ligne de commande du mainteneur, pas depuis le conteneur :

```bash
ourouler inviter adresse@example.com
```

Options réelles (`src/ourouler/cli.py:ajouter_inviter`, ~ligne 912) :
`adresse` (positionnel, obligatoire), `--sans-courriel` (n'envoie pas le
courriel, affiche seulement le lien), `--json` (hérité de `parent_json()`).
`ourouler invitations` liste les invitations en cours (adresse, lien,
échéance).

Secrets et paramètres lus, et par quoi (`_commande_inviter`,
`src/ourouler/cli.py` ~ligne 930) :

- `OUROULER_DATABASE_URL` — obligatoire, sinon refus nommant la variable
  (`_url_des_comptes`).
- `OUROULER_URL_PUBLIQUE` — l'URL publique devant laquelle `/entrer?jeton=…`
  s'ouvre ; obligatoire, sinon refus nommant la variable (`_url_publique`).
  Posée dans l'environnement du mainteneur le temps de la commande, pas
  dans le compose du service.
- `~/.config/ourouler/service.toml` (ou le chemin de `OUROULER_SERVICE`) —
  sauf `--sans-courriel` : section `[brevo]` (mêmes six champs que
  ci-dessus).

Ce que reçoit l'invité (`src/ourouler/api/courriel.py:message_invitation`) :
un courriel texte simple, sujet « Invitation à où rouler », qui dit qui
invite (si le mainteneur a renseigné son prénom/nom) ou « Vous êtes
invité·e » sinon, le lien `<url_publique>/entrer?jeton=<jeton>`, et
l'échéance au format `JJ/MM/AAAA`.

**Le lien s'affiche toujours en sortie de commande**, courriel envoyé ou
non — pour que le mainteneur puisse le relire et le renvoyer par un autre
canal.

Durée de validité du lien : **3 jours**
(`src/ourouler/api/comptes.py:DUREE_INVITATION = timedelta(days=3)`). Une
invitation relancée sur une adresse déjà invitée mais pas encore activée
reprend le même jeton, rien n'est réémis (`emise.deja_en_cours`).

## 3. Ce que voit l'invité

1. **Le lien** (`front/src/ecrans/Entrer.tsx`, E6) : `GET /invitation` dit
   si le jeton tient encore (valable, expiré, déjà consommé — les trois
   derniers cas rendent la même réponse `invitation_invalide`, pour ne pas
   renseigner un inconnu sur lequel des trois il a rencontré). Si valable,
   l'invité choisit son mot de passe et le compte s'active.
2. **L'assistant d'accueil** (`front/src/ecrans/Assistant.tsx`,
   `docs/ux/parcours_accueil.md`) : identité (prénom/nom), point de départ,
   puis un entonnoir en cinq étages qui cherche une puissance seuil du plus
   précis au plus flou — compte Intervals.icu (facultatif, clé API + athlète
   Intervals), sinon export Strava/Garmin, sinon une valeur déclarée, sinon
   le vécu en choix (vitesse/terrain), sinon la littérature seule à partir
   du poids et du vélo. Poids et vélo (avec, depuis L9.1, un pneu facultatif
   qui fixe le Crr par catégorie de littérature) se posent juste avant la
   première étape qui en a besoin.
   **À vérifier avant de montrer ce document à un invité** : l'étape
   « Export Strava ou Garmin » de cet assistant (`etape === "t2"` dans
   `Assistant.tsx`) affiche encore, telle quelle dans le code au 25/09/2026,
   « L'import d'un export Strava ou Garmin n'est pas encore proposé par
   ourouler » — alors que l'import lui-même existe déjà ailleurs (point
   suivant). L'assistant ne l'offre pas pendant l'accueil.
3. **Importer son historique, hors assistant** — L9.2. Ce n'est pas un
   écran de l'entonnoir d'accueil : c'est le bloc « Mes sorties passées »
   (`MesSortiesPassees`, dans `front/src/ecrans/Importer.tsx`), affiché
   sous le dépôt de séance du jour, sur l'écran atteint depuis « Aujourd'hui »
   ou « Ma semaine » en choisissant d'importer/déposer une séance. On y
   dépose un `.fit`/`.gpx`/`.tcx` (éventuellement `.gz`) isolé, ou
   l'archive d'export Strava (`strava.com/athlete/download_my_account`) ou
   Garmin (`garmin.com/en-US/account/datamanagement/`), lien direct affiché
   à l'écran. L'import tourne en tâche de fond côté serveur (`POST
   /activites/import` rend 202, `GET /activites/import/{id}` suit
   l'avancement) ; l'écran affiche une barre de progression et reprend le
   suivi après un rechargement de page.
4. **La calibration à partir d'un capteur de puissance** — L9.4 (« la
   boucle de correction, depuis l'écran »), codée et fusionnée le
   25/09/2026 (`front/src/composants/CalibrationVelo.tsx`,
   `src/ourouler/api/calibrations.py`). Sur la fiche vélo des Réglages, un
   bouton « Calibrer sur mes sorties » lance `POST /calibrations`, qui
   relit les sorties de ce vélo (importées ou synchronisées Intervals.icu),
   va chercher le vent de chaque jour de sortie et cherche le CdA qui
   explique le mieux les temps observés — même calcul que `ourouler
   calibrer` (`physique.commande.calibrer_velo`), pas une seconde
   implémentation, en tâche de fond parce que ça dure. L'écran affiche
   d'abord la puissance qu'il faut à 30 km/h sur le plat sans vent, l'écart
   mesuré sur des sorties que le calcul n'avait pas vues et la fourchette du
   porte à porte ; le CdA et le Crr ne sortent que dans un détail replié,
   présentés comme des paramètres de compensation (ils absorbent aussi
   l'étalonnage du capteur), pas comme des mesures du vélo à comparer à un
   catalogue.

   **Ce qu'il faut avant de pouvoir calibrer**, chacun avec son refus
   lisible si la condition manque : un vélo dans le profil
   (`velo_absent`), une FTP renseignée (`ftp_absente`, elle sert à écarter
   les efforts qui ne décrivent pas le vélo — sprints, relances), au moins
   **10 sorties exploitables** pour ce vélo — extérieures, 20 km et plus,
   avec un capteur de puissance, depuis la date d'historique du compte
   (`sorties_insuffisantes`, le refus dit combien il en faut et combien il
   y en a) —, et un pneu déclaré sur le vélo, ou calibrer quand même avec
   le Crr de l'usage (`pneu_absent`, ou l'option `sans_pneu`). Avec
   plusieurs vélos dans le profil, seules comptent les sorties qui
   désignent explicitement celui-ci (capteur de puissance, équipement
   Intervals, ou période déclarée) — l'écran dit ces préconditions avant le
   clic, le serveur les vérifie de toute façon.
5. **Ce qui reste générique, et le dit** : sans capteur ni historique
   importé, l'entonnoir descend jusqu'à l'étage littérature (poids + type de
   vélo) et l'écran le dit explicitement (`front/src/ecrans/Assistant.tsx`,
   phrase de confiance « Estimation générique, à partir de votre poids et
   de votre vélo seuls »).

## 4. Limites à annoncer à l'invité

- **Quotas journaliers par compte** (`src/ourouler/api/quotas.py`,
  remis à minuit UTC, comptés par compte — un mode personnel n'est jamais
  concerné) :
  - **20 générations par jour** (`POST /sorties`, `POST /boucles`,
    `GENERATIONS_PAR_JOUR_DEFAUT`) et **100 consultations météo par jour**
    (`GET /meteo`, `CONSULTATIONS_METEO_PAR_JOUR_DEFAUT`) — les deux
    réglables côté service, dans `service.example.toml` section `[quotas]`
    (`generations_par_jour`, `consultations_meteo_par_jour` ;
    `src/ourouler/api/exploitation.py`), défauts ci-dessus si la section ou
    le champ sont absents.
  - **1 calibration par jour** (`POST /calibrations`, L9.4,
    `CALIBRATIONS_PAR_JOUR_DEFAUT`) et **5 imports d'historique par jour**
    (`POST /activites/import`, L9.2, `IMPORTS_PAR_JOUR_DEFAUT`) — ces
    deux-là sont des constantes du code, **pas encore réglables** depuis
    `service.toml` (vérifié : `exploitation.py` n'expose que
    `generations_par_jour` et `consultations_meteo_par_jour`).

  Au-delà de n'importe lequel des quatre, `429 quota_atteint`
  (`front/src/composants/Echec.tsx` l'affiche lisiblement, le message dit
  lequel des plafonds est atteint). Une calibration ou un import qui
  échoue rembourse son crédit du jour.
- **Un seul calcul lourd à la fois, pour le serveur entier** : une
  génération de sortie/boucle qui croise un calcul déjà en cours rend
  `409 calcul_en_cours` ; un import ou une calibration qui croise un import
  ou une calibration déjà en cours rend `409 tache_lourde_en_cours`
  (`src/ourouler/api/taches_fond.py`, `src/ourouler/api/routes.py`). Une
  seconde suppression du même compte (`DELETE /moi`) pendant qu'une
  première attend jusqu'à deux minutes la fin d'une tâche de fond de ce
  compte rend `409 suppression_deja_en_cours` — elle n'attend pas à son
  tour. Pas d'attente silencieuse dans aucun de ces trois cas : un message,
  et réessayer plus tard.
- **Bornes sur un dépôt d'historique**
  (`src/ourouler/activites/import_archive.py`) : 750 Mo par requête
  (`TAILLE_MAX_REQUETE`), 20 000 fichiers rencontrés au total
  (`NOMBRE_MAX_FICHIERS`), 2 Go décompressés toutes archives confondues
  (`TAILLE_MAX_DECOMPRESSEE`), 200 Mo pour une archive `.zip` imbriquée
  (`TAILLE_MAX_FICHIER`), **16 Mo pour une activité isolée**
  (`TAILLE_MAX_ACTIVITE`, ramené de 50 à 16 Mo le 25/09/2026 — un `.gpx`
  synthétique de 50 Mo prenait +745 Mo de mémoire résidente à lire), ratio
  de décompression maximum 100 (`RATIO_MAX_DECOMPRESSION`), imbrication
  `.zip` dans `.zip` limitée à 3 niveaux (`PROFONDEUR_MAX_ARCHIVE`). Au-delà,
  l'entrée fautive est ignorée avec un motif lisible, pas un refus brutal de
  tout l'import.
- **Ce qui n'existe pas, vérifié dans le code au 25/09/2026** :
  - Pas de récupération de mot de passe oublié **en libre-service** — le
    commentaire de `front/src/ecrans/Connexion.tsx` le dit toujours :
    « Pas de récupération de mot de passe non plus ». Le mainteneur, lui,
    peut émettre un lien de nouveau mot de passe depuis sa ligne de
    commande (`ourouler reinitialiser`, §5) : ce n'est pas un trou resté
    ouvert, c'est un geste volontairement réservé à la ligne de commande
    (un « mot de passe oublié » en libre-service ouvrirait un relais de
    spam et un oracle d'énumération d'adresses).
  - Pas d'inscription libre ni de demande d'accès : l'entrée est
    uniquement par invitation (même fichier, même commentaire ; doctrine
    §10.2).
  - Pas de passkey (aucune occurrence du mot dans le dépôt) — cité comme
    hors périmètre de ce sprint dans `docs/sprint9_contrat.md`.
  - Import par lien Strava/Garmin direct : non, c'est un dépôt de fichier
    ou d'archive téléchargée à la main (voir §3.3) — [[Q48]], toujours pas
    fait.

## 5. Retirer quelqu'un / ses données

**Côté invité**, depuis l'écran (lot L9.6, `front/src/ecrans/Reglages.tsx`,
volet « Mon compte » — `Réglages → Mon compte → Gérer`) ou directement par
l'API (`src/ourouler/api/routes.py`) :

- **Export** — bouton « Export ZIP », qui pointe vers `GET /moi/export` :
  toutes ses données personnelles dans une archive ZIP non compressée, avec
  un `LISEZ-MOI.txt` à la racine qui dit ce qu'est chaque entrée.
- **Changer de mot de passe** — formulaire (mot de passe actuel + nouveau),
  `POST /moi/mot-de-passe`. Ne ferme pas les autres sessions ouvertes de ce
  compte (contrairement à `reinitialiser` ci-dessous).
- **Suppression** — bouton « Supprimer mon compte… », à double confirmation
  (un second écran résume ce qui part et ce qui reste, puis « Confirmer la
  suppression définitive »), qui appelle `DELETE /moi` : efface ses données
  personnelles, idempotent (rappeler la route sur un propriétaire qui n'a
  déjà rien laissé rend des compteurs à zéro, pas une erreur). Ferme aussi
  le compte quand ce déploiement en a un : `DepotComptes.
  supprimer_compte_du_proprietaire` efface la ligne `comptes`, la cascade
  du schéma révoque ses invitations et ses sessions ouvertes — son mot de
  passe ne rouvre plus rien après cet appel. **Une seconde suppression du
  même compte pendant qu'une première tourne encore refuse tout de suite**
  (`409 suppression_deja_en_cours`, lot de finition du 25/09/2026) plutôt
  que d'attendre elle aussi jusqu'à deux minutes.

  Ces trois gestes ne s'affichent que sur un déploiement hébergé avec un
  compte lié à la session (`GET /moi` rend `email: null` sinon — mode
  personnel, ou hébergé sans base de comptes) : sans compte, seul l'export
  reste proposé (il porte sur le propriétaire de la session, pas sur un
  compte).

**Côté mainteneur**, en ligne de commande :

- `ourouler reinitialiser <adresse>` — émet un lien de nouveau mot de passe
  pour un compte **déjà actif** qui l'a perdu (`src/ourouler/cli.py`,
  `ajouter_reinitialiser`/`_commande_reinitialiser`,
  `src/ourouler/api/invitation_commande.py`). Même patron que `inviter` :
  mêmes secrets `service.toml`, `--sans-courriel` pour n'afficher que le
  lien, jeton à usage unique dans la même table `invitations`
  (`src/ourouler/api/comptes.py:reinitialiser`). **Réservée à la ligne de
  commande, jamais une route HTTP** : un « mot de passe oublié » en
  libre-service ouvrirait un relais de spam et un oracle d'énumération
  d'adresses.
- `ourouler retirer <adresse>` — ferme un compte hébergé et efface ses
  données personnelles, **par le même chemin que `DELETE /moi`**
  (`src/ourouler/api/retrait_commande.py` appelle `vie_privee.
  effacer_donnees` telle quelle, pas une réimplémentation). `--oui` pour ne
  pas demander confirmation. **À lancer `docker exec` (ou équivalent) DANS
  le conteneur du serveur, jamais depuis le poste du mainteneur** : la
  commande reconstruit les mêmes dépôts (profil, fichiers, cache
  d'activités) que le serveur hébergé réellement lancé, à partir de la
  configuration et du dossier de données de la machine qui l'exécute — lancée
  depuis le Mac du mainteneur, elle fermerait bien le compte dans la base
  Postgres distante, mais chercherait les fichiers dans un dossier local
  presque toujours vide, laissant le vrai dépôt du propriétaire orphelin
  tout en annonçant un succès. `_depots_de_l_hebergement` (`cli.py`) refuse
  maintenant si le dossier de données attendu n'existe pas, mais ce n'est
  qu'un filet — voir `deploiement/api/README.md`.

## 6. Vérifier après déploiement

Trois vérifications concrètes, dans l'ordre :

```bash
# 1. Le service répond, sans ouvrir de session (sonde de santé).
curl https://<domaine attribué>/sante
# → {"etat": "ok", "version": "…"}

# 2. Une route de données refuse tant que personne n'est identifié.
curl -i https://<domaine attribué>/api/v1/systeme
# → 401, corps JSON avec erreur.code = "session_absente"

# 3. Une invitation de test, à sa propre adresse, sans envoyer de courriel.
OUROULER_DATABASE_URL=... OUROULER_URL_PUBLIQUE=https://<domaine attribué> \
  ourouler inviter mainteneur@son-domaine.example --sans-courriel
# → affiche le lien et l'échéance (3 jours) ; ouvrir le lien affiché
#   pour vérifier que /entrer active bien le compte.
```

## Sources vérifiées

`src/ourouler/cli.py` (`ajouter_inviter`, `_commande_inviter`,
`_url_des_comptes`, `_url_publique`, `_charger_service`, ~lignes 850-1070),
`src/ourouler/api/invitation_commande.py`, `src/ourouler/api/courriel.py`,
`src/ourouler/api/comptes.py` (`DUREE_INVITATION`, `DUREE_SESSION`),
`src/ourouler/api/depots.py` (`SECTIONS_PERSO_PUR`, `VARIABLES_PERSO_PUR`,
`CHAMPS_RACINE_MODIFIABLES`), `src/ourouler/api/application.py`
(`_refuser_une_base_partagee`), `src/ourouler/api/routes.py` (routes
`/invitation`, `/entrer`, `/activites/import*`, `/moi/export`, `/moi`),
`src/ourouler/api/quotas.py`, `src/ourouler/api/exploitation.py`,
`src/ourouler/api/imports_fond.py`, `src/ourouler/api/taches_fond.py`,
`src/ourouler/api/vie_privee.py`, `src/ourouler/api/erreurs.py`,
`src/ourouler/api/calibrations.py`, `src/ourouler/api/retrait_commande.py`,
`src/ourouler/activites/import_archive.py`, `docker-compose.api.coolify.yml`,
`deploiement/api/README.md`, `deploiement/api/config.example.toml`,
`service.example.toml`, `docs/questions_mainteneur.md` (Q66),
`front/src/ecrans/Assistant.tsx`, `front/src/ecrans/Importer.tsx`,
`front/src/ecrans/Connexion.tsx`, `front/src/ecrans/Entrer.tsx`,
`front/src/ecrans/Reglages.tsx` (`MonCompteVolet`),
`front/src/composants/CalibrationVelo.tsx`, `docs/ux/parcours_accueil.md`.
Cette révision (25/09/2026, lot de finition `l9-finition`) met à jour §3.4
(L9.4, calibration) et §5 (Mon compte, `reinitialiser`, `retirer`), ajoute
les quatre quotas et le refus `suppression_deja_en_cours` en §4, corrige la
borne d'activité isolée (16 Mo, pas 50), et retire les constats devenus faux
(absence de calibration codée, absence de bouton d'export/suppression,
absence de commande de retrait).
