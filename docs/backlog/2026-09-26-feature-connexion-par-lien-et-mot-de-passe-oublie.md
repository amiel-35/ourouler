# Connexion par lien à usage unique + mot de passe oublié

Type : feature
Statut : validée le 26/09/2026

## Pourquoi

Un invité qui oublie son mot de passe doit m'écrire, et moi je dois faire
ssh + docker exec + `ourouler reinitialiser`. [déduit] Et pour quelqu'un qui
se connecte rarement, recevoir un lien est plus simple que retrouver son mot
de passe.

## Ce que je veux voir

- Page de connexion : le formulaire adresse + mot de passe reste tel quel.
  En dessous, deux liens : « Recevoir un lien de connexion » et « Mot de
  passe oublié ».
- Chacun ouvre un champ adresse. Après envoi, toujours le même message :
  « Si un compte existe pour cette adresse, un courriel vient de partir. »
  Que l'adresse existe ou non, que le compte soit actif ou non.
- Lien de connexion : un clic me connecte directement (session habituelle
  de 30 jours) et m'amène sur l'accueil.
- Mot de passe oublié : le lien ouvre l'écran « Nouveau mot de passe ».
  Valider pose le nouveau mot de passe, ferme mes autres sessions ouvertes
  et me connecte.
- Les deux liens sont valables 15 minutes et ne servent qu'une fois. Un lien
  expiré ou déjà utilisé affiche : « Ce lien n'est plus valable. » avec un
  bouton pour en redemander un.
- Exemple : Paul a oublié son mot de passe un dimanche matin. Il clique
  « Mot de passe oublié », reçoit le courriel, en pose un nouveau, et il est
  dans l'app en moins d'une minute, sans m'écrire.

## Acquis techniques (réglés, pas à trancher)

- Au plus 3 courriels par adresse et par heure, plus un plafond par IP.
  Au-delà, même message, rien ne part.
- Une adresse inconnue ou un compte pas encore activé ne reçoit rien.
- Jeton jamais dans les journaux. Consommation par un seul
  `UPDATE … RETURNING` (même règle que l'invitation, doctrine §10.2).
- Réutilise le jeton et l'écran existants de `reinitialiser` et de
  `/entrer`, pas une seconde implémentation.

## C'est fini quand

En prod, depuis mon téléphone, déconnecté :

1. je demande un lien de connexion, je le reçois, je suis connecté ; je
   rouvre le même lien → « plus valable » ;
2. je fais « Mot de passe oublié », je pose un nouveau mot de passe, ma
   session sur l'ordinateur est fermée, je me reconnecte avec le nouveau ;
3. je demande un lien pour une adresse inventée → même message, aucun
   courriel parti (vérifié dans les journaux Brevo).

## Hors sujet

- Pas de passkey.
- Pas de création de compte par ce chemin.
- Pas de suppression du mot de passe : le lien vient en plus.
- `ourouler reinitialiser` (CLI) reste.
- Durée des sessions (30 jours) inchangée.

## Questions ouvertes

- Aucune.

## Déjà en place / Doctrine révisée

- Le lien de nouveau mot de passe existe déjà, émis en CLI seulement :
  `services.comptes.reinitialiser` → `DepotComptes.reinitialiser`
  (`api/comptes.py`). Il est consommé par `POST /reinitialiser`
  (`api/routes/sessions.py`), qui pose le mot de passe, ferme les sessions
  ouvertes et en ouvre une neuve. Manquent la route publique qui émet le lien
  depuis une adresse, et l'écran.
- Aucun lien de connexion aujourd'hui, mais la doctrine l'avait prévu (§10.2 :
  « le lien à usage unique reste le filet »).
- Déjà au backlog : sujet 2 de « les comptes, côté cycliste et côté
  mainteneur » (`docs/journal/sprints/plan_sprints_agents.md`, 26/09/2026).
  Cette fiche en est la version tranchée.
- **Révise la décision du lot L9.6** : « aucune route HTTP anonyme n'appelle
  `reinitialiser` » (note de module de `DepotComptes.reinitialiser`). Mettre à
  jour cette note, la docstring de `services.comptes.reinitialiser` et de la
  route `POST /reinitialiser`, l'en-tête de `front/src/ecrans/Connexion.tsx`
  et `docs/inviter.md` §4 fait partie de la PR.
