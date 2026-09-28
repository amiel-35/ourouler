# Limiter les tentatives de connexion par mot de passe

Type : feature
Statut : à valider

## Pourquoi

`POST /connexion` égalise déjà le temps de réponse et le message entre une
adresse inconnue et un mauvais mot de passe (`DepotComptes.authentifier`,
doctrine §10.2) — c'est une protection contre l'oracle, pas contre le
martèlement. Rien ne borne le nombre d'essais sur cette route : ni par
adresse, ni par IP, ni globalement. Comparée aux routes voisines — le
formulaire de demande d'invitation (`LimiteAnonyme`, deux compteurs, IP et
global) et l'émission d'un lien de connexion/réinitialisation (« au plus 3
courriels par adresse et par heure, plus un plafond par IP », fiche
`2026-09-26-feature-connexion-par-lien-et-mot-de-passe-oublie.md`) — la
route qui vérifie un mot de passe est la seule des trois sans aucun débit.
Un invité réel est en prod depuis aujourd'hui : avant toute ouverture
publique plus large, c'est la priorité de ce lot. [déduit]

## Ce que je veux voir

- `POST /connexion` refuse au-delà d'un nombre d'essais par adresse et par
  fenêtre glissante (même ordre de grandeur que les compteurs déjà en place :
  quelques essais par adresse et par quart d'heure, à caler avec le
  mainteneur), et un plafond global par IP en plus — même patron que
  `LimiteAnonyme` (`api/demandes.py`) ou que `Plafond`/`Quotas`
  (`api/quotas.py`) : compteur en mémoire du processus, fenêtre glissante,
  réglable dans `service.toml`.
- Le refus rend la **même** forme d'erreur (401,
  `identifiants_refuses`) qu'un mot de passe faux — pas un code distinct qui
  dirait « cette adresse existe et vous martelez son mot de passe » ; sinon
  le débit devient lui-même un oracle. Un code dédié (429) reste possible
  **si** son message ne distingue pas une adresse existante d'une adresse
  inconnue.
- Un essai réussi remet le compteur de cette adresse à zéro (un cycliste qui
  se trompe deux fois puis retrouve son mot de passe ne doit pas rester
  bloqué par ses propres essais passés).
- `POST /entrer` et `POST /reinitialiser` (consommation d'un jeton à usage
  unique, haute entropie — `secrets.token_urlsafe`) restent hors de ce
  plafond par adresse : le risque n'est pas le même (deviner un jeton de 128
  bits n'est pas deviner un mot de passe humain) ; un plafond par IP peut
  leur être ajouté par prudence, sans bloquer un cycliste légitime qui se
  trompe de caractère en recopiant son lien.
- Le compteur ne fuit rien dans les journaux (mêmes règles que
  `api/quotas.py` et `api/demandes.py` : pas d'adresse en clair au-delà de ce
  qui sert déjà à authentifier).

## C'est fini quand

En préproduction, martèlement de `POST /connexion` sur une adresse réelle
avec un mauvais mot de passe : au-delà du plafond, la réponse refuse sans
appeler `authentifier` (donc sans hachage inutile), avec le même message que
d'habitude ; un essai avec le bon mot de passe après le plafond échoue
encore (le compte n'est pas déverrouillé par un bon essai tant que la
fenêtre n'est pas passée) ; passé le délai de la fenêtre, la connexion
légitime repasse.

## Hors sujet

- Un second facteur (TOTP, passkey) sur `/connexion` : distinct, et déjà
  écarté pour l'admin par QP6 pour une raison différente (tunnel SSH comme
  facteur fort) — l'admin n'est pas concernée ici, elle n'est jamais
  publique.
- Verrouillage de compte après N échecs (bloquer l'adresse elle-même plutôt
  que la fenêtre de débit) : plus dur à annuler pour un cycliste innocent
  derrière une IP partagée (NAT, VPN familial), écarté au profit d'une
  fenêtre glissante qui se résorbe seule.
- Captcha : comme pour le formulaire de demande d'invitation, un
  honeypot/délai minimal peut suffire ; un captcha visible se pose si l'abus
  se confirme, pas par anticipation.

## Acquis techniques

- Le patron existe déjà deux fois dans le dépôt à réutiliser tel quel :
  `LimiteAnonyme` (`api/demandes.py`, compteur par IP + compteur global,
  fenêtre glissante) et `Quotas`/`Plafond` (`api/quotas.py`, compteur par
  compte et par jour UTC). L'un des deux (ou un troisième, par **adresse**
  plutôt que par compte ou par IP seule) s'applique à `/connexion` sans
  réinventer le mécanisme.
- `DepotComptes.authentifier` égalise déjà le temps de réponse — ce lot
  n'y touche pas, il ajoute un refus **avant** cet appel quand le plafond est
  atteint.

## Questions ouvertes

- Le plafond par adresse doit-il être réglable dans `service.toml` (comme
  `[demandes]` pour le formulaire public) ou une constante de code comme
  `GENERATIONS_PAR_JOUR_DEFAUT` ? À trancher avec le mainteneur.
- Faut-il aussi un plafond par IP sur `POST /entrer` et `POST /reinitialiser`
  dans ce même lot, ou une fiche séparée ? Proposé hors sujet ci-dessus,
  à confirmer.

## Déjà en place / Doctrine révisée

- Constaté : `src/ourouler/api/routes/sessions.py::connexion` (`POST
  /connexion`) appelle `DepotComptes.authentifier` sans aucun compteur
  avant ; aucune trace de `Plafond`, `Quotas` ou `LimiteAnonyme` importée
  dans ce fichier.
- Constaté : `src/ourouler/api/comptes.py::authentifier` (ligne 955) égalise
  le temps de réponse et le message entre adresse inconnue et mot de passe
  faux (`_SECRET_BOUCHE_TROU`, hachage systématique), mais ne borne aucun
  nombre d'essais.
- Constaté : `src/ourouler/api/routes/demandes.py` construit
  `_LIMITE_PAR_IP` et `_LIMITE_GLOBALE` (`LimiteAnonyme`,
  `api/demandes.py`), objets de module en mémoire du processus, plafonds
  lus une fois depuis `service.toml` via `api/exploitation.py`.
- Constaté : `src/ourouler/api/quotas.py` documente le même choix de
  stockage (« en mémoire du processus… n'a pas besoin de survivre à un
  redémarrage — et le service tourne aujourd'hui en un seul processus »),
  directement réutilisable pour un compteur de tentatives.
- Constaté : la fiche
  `docs/backlog/2026-09-26-feature-connexion-par-lien-et-mot-de-passe-oublie.md`
  décrit déjà un débit sur l'**émission** des liens (« au plus 3 courriels
  par adresse et par heure, plus un plafond par IP ») — cette fiche-ci couvre
  la route symétrique restée sans limite, la **vérification** d'un mot de
  passe.
