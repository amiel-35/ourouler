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
   boucle de correction, depuis l'écran ») **n'est pas codée à la date du
   25/09/2026** : aucun écran `front/src/ecrans/*.tsx` ne contient le mot
   « calibr » (vérifié par recherche dans le dépôt), et le lot ne figure
   pas dans les commits fusionnés de la branche `sprint-9` (seuls L9.1,
   L9.2 et L9.3 y sont fusionnés à ce jour). Un invité avec capteur n'a donc
   aujourd'hui aucun moyen, depuis l'écran, de lancer sa propre calibration
   — c'est encore la ligne de commande du mainteneur (`ourouler calibrer`)
   qui en est capable, et elle ne tourne que sur la machine du mainteneur.
   À corriger dans ce document dès que L9.4 est fusionné.
5. **Ce qui reste générique, et le dit** : sans capteur ni historique
   importé, l'entonnoir descend jusqu'à l'étage littérature (poids + type de
   vélo) et l'écran le dit explicitement (`front/src/ecrans/Assistant.tsx`,
   phrase de confiance « Estimation générique, à partir de votre poids et
   de votre vélo seuls »).

## 4. Limites à annoncer à l'invité

- **Quotas journaliers par compte** (`service.example.toml`, section
  `[quotas]`, défauts effectifs si la section est absente —
  `src/ourouler/api/quotas.py:GENERATIONS_PAR_JOUR_DEFAUT`,
  `CONSULTATIONS_METEO_PAR_JOUR_DEFAUT`) : **20 générations par jour**
  (`POST /sorties`, `POST /boucles`) et **100 consultations météo par jour**
  (`GET /meteo`), remis à minuit UTC. Au-delà, `429 quota_atteint`
  (`front/src/composants/Echec.tsx` l'affiche lisiblement, le message dit
  lequel des deux plafonds est atteint).
- **Un seul calcul lourd à la fois, pour le serveur entier** : une
  génération de sortie/boucle qui croise un calcul déjà en cours rend
  `409 calcul_en_cours` ; un import qui croise un import déjà en cours rend
  `409 import_deja_en_cours` (`src/ourouler/api/imports_fond.py`,
  `src/ourouler/api/routes.py`). Pas d'attente silencieuse : un message,
  et réessayer plus tard.
- **Bornes sur un dépôt d'historique**
  (`src/ourouler/activites/import_archive.py`) : 750 Mo par requête
  (`TAILLE_MAX_REQUETE`), 20 000 fichiers rencontrés au total
  (`NOMBRE_MAX_FICHIERS`), 2 Go décompressés toutes archives confondues
  (`TAILLE_MAX_DECOMPRESSEE`), 200 Mo pour une archive `.zip` imbriquée
  (`TAILLE_MAX_FICHIER`), 50 Mo pour une activité isolée
  (`TAILLE_MAX_ACTIVITE`), ratio de décompression maximum 100
  (`RATIO_MAX_DECOMPRESSION`), imbrication `.zip` dans `.zip` limitée à 3
  niveaux (`PROFONDEUR_MAX_ARCHIVE`). Au-delà, l'entrée fautive est ignorée
  avec un motif lisible, pas un refus brutal de tout l'import.
- **Ce qui n'existe pas, vérifié dans le code au 25/09/2026** :
  - Pas de récupération de mot de passe oublié. Le commentaire de
    `front/src/ecrans/Connexion.tsx` le dit explicitement : « Pas de
    récupération de mot de passe non plus : lot à part, à trancher par le
    mainteneur. »
  - Pas d'inscription libre ni de demande d'accès : l'entrée est
    uniquement par invitation (même fichier, même commentaire ; doctrine
    §10.2).
  - Pas de passkey (aucune occurrence du mot dans le dépôt) — cité comme
    hors périmètre de ce sprint dans `docs/sprint9_contrat.md`.
  - Import par lien Strava/Garmin direct : non, c'est un dépôt de fichier
    ou d'archive téléchargée à la main (voir §3.3).

## 5. Retirer quelqu'un / ses données

Côté invité, deux routes de son propre compte
(`src/ourouler/api/routes.py`) :

- `GET /moi/export` — toutes ses données personnelles dans une archive ZIP
  non compressée, avec un `LISEZ-MOI.txt` à la racine qui dit ce qu'est
  chaque entrée.
- `DELETE /moi` — efface ses données personnelles, idempotent (rappeler la
  route sur un propriétaire qui n'a déjà rien laissé rend des compteurs à
  zéro, pas une erreur). Ferme aussi le compte quand ce déploiement en a
  un : `DepotComptes.supprimer_compte_du_proprietaire` efface la ligne
  `comptes`, la cascade du schéma révoque ses invitations et ses sessions
  ouvertes — son mot de passe ne rouvre plus rien après cet appel.

**À vérifier** : aucun écran du front (`front/src/ecrans/Reglages.tsx`
compris) n'appelle `GET /moi/export` ni `DELETE /moi` — recherche dans
`front/src` sans résultat au 25/09/2026. Le docstring de `Reglages.tsx` le
dit lui-même : « les clés d'accès, l'export et la suppression appartiennent
aux comptes (lot F3) » — ces deux routes existent côté API mais ne sont pas
encore accessibles depuis un bouton. Un invité qui veut exporter ou
supprimer ses données aujourd'hui doit appeler l'API directement (`curl`,
avec sa session ouverte), pas depuis un écran.

Côté mainteneur, **aucune commande n'a été trouvée pour retirer un compte
ou révoquer une invitation depuis la ligne de commande** — `ourouler
invitations` ne fait que lister ; `grep -n "revoquer\|supprimer_compte" cli.py`
ne remonte rien. Si le mainteneur doit fermer un compte hébergé sans
attendre que la personne le fasse elle-même via `DELETE /moi`, ce geste
n'existe pas encore dans le dépôt.

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
`src/ourouler/api/quotas.py`, `src/ourouler/api/imports_fond.py`,
`src/ourouler/activites/import_archive.py`, `docker-compose.api.coolify.yml`,
`deploiement/api/README.md`, `deploiement/api/config.example.toml`,
`service.example.toml`, `docs/questions_mainteneur.md` (Q66),
`front/src/ecrans/Assistant.tsx`, `front/src/ecrans/Importer.tsx`,
`front/src/ecrans/Connexion.tsx`, `front/src/ecrans/Entrer.tsx`,
`front/src/ecrans/Reglages.tsx`, `docs/ux/parcours_accueil.md`.
