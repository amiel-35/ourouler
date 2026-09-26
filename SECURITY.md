# Sécurité

## Signaler une faille

Ne signalez pas une faille dans un ticket public, une PR ou une discussion.

Utilisez le signalement privé de GitHub : onglet **Security** du dépôt,
puis **Report a vulnerability**. Le rapport n'est visible que du
mainteneur. Indiquez ce qui est touché, les étapes pour reproduire, l'effet
constaté, et la version ou le commit concerné.

## Périmètre

Sont dans le périmètre, en priorité :

- l'API (routes, authentification, validation des entrées) ;
- la gestion des comptes et des sessions (invitation, activation,
  connexion, réinitialisation du mot de passe, jetons, déconnexion — il n'y
  a pas d'inscription libre) ;
- toute fuite de données entre comptes : un cycliste qui lit ou modifie les
  activités, la configuration ou les clés d'un autre ;
- une clé d'API tierce (Intervals.icu…) exposée dans une réponse, un
  journal ou le dépôt.

Hors périmètre : les services externes eux-mêmes (Open-Meteo,
Intervals.icu, moteur de tracé), qui se signalent à leurs auteurs.

## Tester sans nuire

Testez sur votre propre instance, lancée depuis ce dépôt. **Ne testez pas
sur un service en production qui ne vous appartient pas**, et n'accédez
jamais aux données d'un autre utilisateur au-delà de ce qui prouve la
faille.

## Délai de réponse

Le projet est maintenu par une seule personne, sur son temps libre. Le but
est d'accuser réception en quelques jours et de corriger vite ce qui
touche des données d'utilisateurs ; aucun délai n'est garanti. La
correction est publiée dans une version, mentionnée sous « Sécurité » dans
le `CHANGELOG.md`, avec votre nom si vous le souhaitez.
