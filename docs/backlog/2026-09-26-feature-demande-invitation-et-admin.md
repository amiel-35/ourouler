# Demande d'invitation depuis le site et interface d'administration

Type : feature
Statut : validée le 26/09/2026

## Pourquoi

Amiel invite aujourd'hui en ligne de commande dans le conteneur — il faut se connecter en SSH pour inviter, lister ou supprimer un compte. Il veut que quelqu'un puisse demander à rejoindre le service depuis le site, sans lui écrire à côté, et pouvoir accepter ou refuser cette demande sans repasser par le terminal. [déduit] La demande du 26/09 lie explicitement les deux sujets : le formulaire de demande n'a de sens que s'il existe un endroit pour le modérer.

## Ce que je veux voir

- Sur le site public, un écran « Demander une invitation » : un champ adresse, un champ message facultatif (« un mot »), un bouton. Après envoi, un seul message, que l'adresse existe déjà ou non, qu'elle soit acceptée ou non plus tard : « Si votre demande est retenue, vous recevrez un courriel. »
- Chaque demande envoie un courriel à Amiel (« Nouvelle demande d'invitation : <adresse> — <message> »), immédiatement.
- Une interface d'administration, jamais exposée sur Internet : elle n'écoute qu'en local sur le serveur, on y entre par un tunnel SSH (`ssh -L ...`), avec un identifiant dédié défini dans `service.toml` (pas un compte cycliste). Depuis un navigateur ouvert sur ce tunnel, Amiel voit :
  - la file des demandes en attente, avec adresse et message ;
  - pour chacune, « Accepter » (envoie l'invitation, exactement comme `ourouler inviter`) ou « Refuser » (la demande disparaît, rien ne part) ;
  - la liste des invitations déjà en cours (adresse masquée), les comptes actifs, un bouton « Supprimer » avec double confirmation ;
  - les invitations en attente, les tâches de fond en cours, et la consommation du jour des quotas.
- Une demande refusée est purgée (pas gardée « au cas où »), une demande acceptée disparaît de la file dès l'envoi de l'invitation.

## C'est fini quand

Depuis un téléphone quelconque, hors réseau d'Amiel, quelqu'un remplit le formulaire public avec une adresse réelle ; Amiel reçoit le courriel d'alerte ; depuis son Mac, il ouvre un tunnel SSH vers le serveur de prod, voit la demande dans l'admin, clique « Accepter » ; l'invité reçoit le courriel d'invitation Brevo réel et peut créer son compte ; une seconde demande, refusée, ne laisse aucune trace ni fuite d'information à l'auteur.

## Hors sujet

- Les sujets 2 (lien de connexion à usage unique, mot de passe oublié) et 3 (zone rouge Réglages) du même backlog « comptes » : fiches séparées.
- Un second facteur (TOTP, passkey) sur l'admin : QP6 la met derrière un tunnel SSH, pas sur Internet ; le tunnel est déjà le facteur fort. On y revient seulement si l'admin devait un jour s'exposer.
- Toute automatisation de l'acceptation (adresse dans une liste blanche, domaine autorisé) : chaque demande passe par un geste humain d'Amiel, sans exception.

## Acquis techniques

- Le geste « Accepter » de l'admin appelle `services.comptes.inviter()` tel quel — même chemin que `ourouler inviter`, mêmes règles (Q59 : une invitation en cours reprend son jeton existant, unicité de l'adresse portée par contrainte SQL, jamais un `SELECT` préalable).
- Nouvelle table `demandes_invitation` (adresse, message, date, état) avec la même hygiène que `comptes` : rien en clair d'anormal, purge immédiate au refus.
- Débit limité sur le formulaire public : compteur par IP et par adresse, fenêtre glissante, sur le modèle de `api/quotas.py` (`Plafond`, `CODE_QUOTA_ATTEINT`), réglable dans `service.toml`. Anti-robot minimal (champ caché de type honeypot + délai minimal entre affichage et envoi) avant d'envisager un captcha.
- Session d'administration : un troisième mode à côté de `SessionPersonnelle`/`SessionHebergee` dans `api/session.py`, cookie dédié, jamais confondu avec une session cycliste ; testé comme l'isolation par propriétaire (aucune route d'admin atteinte par une session cycliste, ni l'inverse).
- Journal des actions d'administration (qui a accepté/refusé/supprimé quoi, quand) — déjà dans les critères d'acceptation du sprint 12.
- Suppression de la branche `backlog-admin` après recopie de son texte (fait séparément, hors code).

## Questions ouvertes

Aucune.

## Déjà en place / Doctrine révisée

- `src/ourouler/services/comptes.py` — `inviter()`, `invitations_en_cours()`, `retirer()` : le chemin complet invitation + courriel + retrait existe déjà et sert de socle à l'écran « accepter/refuser ».
- `src/ourouler/api/comptes.py` — `DepotComptes` : toute la logique d'état d'une invitation (en cours, expirée, compte déjà actif), unicité portée en base (contrainte SQL, jamais un `SELECT` préalable), secret haché au scrypt + `hmac.compare_digest`.
- `src/ourouler/api/courriel.py` — `ParametresBrevo`, `FabriqueSMTP`, `envoyer_invitation`, `message_invitation` : l'infrastructure d'envoi (Brevo/SMTP) tourne déjà pour l'invitation ; l'alerte au mainteneur s'y branche sans nouveau connecteur. Aucun courriel ne part vers le demandeur au dépôt de sa demande (sinon le formulaire devient un relais de spam) : il ne reçoit que l'invitation, si elle est acceptée.
- `src/ourouler/api/quotas.py` + `api/exploitation.py` — `Plafond`, `CODE_QUOTA_ATTEINT`, `_plafond_quota()` : le patron (compteur borné, réglable dans `service.toml`, code d'erreur dédié) sert de modèle direct pour le débit du formulaire public.
- `src/ourouler/api/session.py` — `SessionPersonnelle` / `SessionHebergee` : les deux modes existants montrent où accrocher un troisième mode « session d'administration », sans toucher aux deux autres.
- Branche `backlog-admin` (base b8c390d) : un seul commit, 38 lignes de doc dans l'ancien `docs/plan_sprints_agents.md`, aucun code — à recopier puis supprimer, pas à rebaser.
- QP6 (25/09/2026, tranchée (c)) : l'interface d'administration n'est jamais exposée publiquement, locale au serveur, joignable par tunnel SSH, identifiant dédié dans `service.toml` — appliquée telle quelle : seule la modération vit derrière le tunnel, le formulaire de demande reste public.
- Backlog « les comptes… » (demande du mainteneur, 26/09/2026, sujet 1) : formulaire public (adresse, un mot), file d'attente, modération dans l'admin (accepter → invitation part, refuser → rien), alerte courriel à chaque demande, débit limité et anti-robot sur le formulaire, aucune fuite d'existence de compte, purge des demandes refusées — repris tel quel comme périmètre de la fiche.
- Q59 (close 18/09/2026) : une invitation déjà en cours et non consommée reprend le même jeton, rien n'est réémis (le jeton est stocké en clair depuis la révision du 18/09/2026, pour que le mainteneur puisse le relire ; il ne part jamais dans un journal) — le geste « accepter » de l'admin appelle `inviter()`, qui applique déjà cette règle sans rien y ajouter.
- Doctrine §10.2 (18-19/09/2026), partie qui ne bouge pas : le secret n'est jamais en clair (base, journal, repr, message d'erreur) et se vérifie en temps constant — vaut aussi pour le jeton de demande et l'identifiant de l'admin.
- Tranché le 26/09/2026 : `doctrine_architecture.md` §10.2 est révisée — le formulaire public de demande d'invitation est autorisé ; le principe qui compte reste que le seul chemin vers un compte est un geste explicite du mainteneur (rien n'entre automatiquement) : une demande n'ouvre jamais de compte seule, elle attend un clic « Accepter » dans l'admin, qui rejoue exactement le `inviter()` actuel. Mettre à jour §10.2 fait partie de la PR. L'écran d'administration porte les cinq fonctions proposées : modération, gestion des comptes, invitations en attente, tâches de fond en cours, consommation du jour des quotas.
