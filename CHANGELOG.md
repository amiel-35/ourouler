<!--
Règle de rangement : une PR mergée dans `main` depuis une branche `sprint-N`
se fond dans la mineure de ce sprint (étiquette sur le dernier merge de la
branche) ; une PR mergée directement dans `main` hors branche de sprint est un
correctif de la mineure précédente, un par merge sur `main`, dans l'ordre où
ils ont atterri (une PR fusionnée dans une autre branche suit celle-ci) ;
des merges arrivés ensemble à quelques secondes d'écart font un seul correctif,
étiqueté sur le dernier.
-->

# Journal des changements

Toutes les évolutions notables d'ourouler sont consignées ici.

Le format suit [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/), et
les numéros de version suivent [SemVer](https://semver.org/lang/fr/) en `0.x` :
un sprint livré fait une version mineure, un correctif ou une petite livraison
entre deux sprints fait un correctif. La `1.0.0` viendra avec l'ouverture
publique. Les versions 0.1.0 à 0.9.3 ont été reconstruites après coup, à
partir des PR.

## [Non publié]

### Ajouté

- Analyser un parcours qu'on a déjà (un brevet, la boucle du club) : on
  dépose son GPX, l'outil dit le temps estimé, la météo le long du tracé et
  le vent, sans rien retracer. Aussi en ligne de commande :
  `ourouler analyser`.

## [0.9.6] — 2026-09-25

### Corrigé

- Après la mise en route d'un nouveau compte, « Aujourd'hui » affiche la
  séance dès qu'intervals.icu est branché ; il restait sur « pas encore
  relié » jusqu'au rechargement de la page.
- Après une mise à jour du service, le navigateur ne garde plus l'ancienne
  page en cache : elle réclamait des fichiers disparus et l'écran restait
  blanc.
- Les messages d'erreur s'affichent avec leurs accents dans tous les
  navigateurs.

## [0.9.5] — 2026-09-25

### Corrigé

- Dans Réglages, l'enregistrement de la clé intervals.icu dit juste sous le
  bouton si la clé est vérifiée ou pourquoi elle est refusée ; le message
  s'affichait en haut de l'écran, hors de vue sur téléphone. (#37)

## [0.9.4] — 2026-09-25

### Corrigé

- La météo, la tenue et le placement sont calculés pour l'heure de départ
  demandée ; ils l'étaient deux heures plus tard. (#35)

## [0.9.3] — 2026-09-25

### Corrigé

- Un invité peut brancher Intervals.icu avec sa seule clé d'API :
  l'identifiant Intervals est retrouvé tout seul. (#29)
- Une clé refusée ou un Intervals injoignable donne un message lisible, et
  rien n'est enregistré. (#29)
- Les appels à Intervals ne sont plus bloqués par son pare-feu. (#29)

## [0.9.2] — 2026-09-25

### Modifié

- La carte se cadre sur la boucle choisie, et se recadre quand on en choisit
  une autre. (#28)
- Les étiquettes de vent ne se chevauchent plus, quel que soit le zoom. (#28)
- La phrase sous « Ce que ça donnera » se simplifie : estimation d'après le
  profil et le vélo, ou d'après les sorties quand ils sont mesurés. (#28)

## [0.9.1] — 2026-09-25

### Corrigé

- Les commandes d'invitation et de gestion des comptes fonctionnent dans le
  conteneur du serveur, sans profil de cycliste dans sa configuration. (#27)
- Le lien d'invitation porte l'adresse publique du service. (#27)

## [0.9.0] — 2026-09-25

### Ajouté

- Importer son historique : fichiers `.fit`, `.gpx`, `.tcx` et archives
  Strava ou Garmin, traités en tâche de fond. (#26)
- Calibrer son vélo depuis Réglages, sans la ligne de commande. (#26)
- Un écran « Mon compte » : exporter ses données, supprimer son compte,
  changer son mot de passe. (#26)
- Un type de pneu par vélo ; la calibration ne cherche plus que la
  traînée aérodynamique. (#26)
- Le temps porte à porte devient une fourchette, mesurée sur les sorties
  quand il y en a. (#26)

### Modifié

- Prévisions météo partagées entre comptes et quotas journaliers par compte,
  remboursés en cas d'échec ; accueil de l'invité revu. (#26)

## [0.8.0] — 2026-09-21

### Ajouté

- Une rose des huit directions pour choisir où rouler : la pluie par secteur,
  une girouette pour le vent, une hachure quand les deux modèles divergent,
  et chaque secteur atteignable au clavier. (#23)
- Une identité visuelle : l'interface en noir et blanc, les données en
  couleur. (#23)
- Le profil d'altitude coloré par la pente, et le vent dessiné tout le long
  du tracé. (#23)

### Corrigé

- Un utilisateur ne peut plus voir les données d'un autre : trois fuites
  entre comptes fermées. (#22)
- « Utiliser ma position » amène la carte à l'écran sur téléphone, et « Je ne
  sais pas » est à portée de main sur l'écran FTP. (#24)
- La FTP s'affiche en watts entiers, et les écrans « Assistant » et
  « Importer » ont un bouton retour. (#23, #24)

## [0.7.1] — 2026-09-18

### Ajouté

- Un fichier d'exemple pour les réglages propres au service, séparé de celui
  du cycliste. (#21)

## [0.7.0] — 2026-09-18

### Ajouté

- Exporter toutes ses données et supprimer son compte depuis l'API. (#20)
- Une image et un fichier compose pour héberger l'API et l'écran, avec une
  sonde de santé. (#20)
- Chaque panne du serveur a son écran d'explication, au lieu d'un message
  générique. (#20)

### Corrigé

- Le dénivelé d'une trace enregistrée vient du tracé rerouté, et plus de
  l'altimètre de l'appareil, qui le gonflait parfois d'un facteur quatre. (#20)

### Sécurité

- Une requête sans session ne voit plus aucune donnée. (#20)

## [0.6.4] — 2026-09-18

### Modifié

- Licence AGPL-3.0-or-later à la place de MIT, avec le fichier `LICENSE`
  qui manquait. (#19)

## [0.6.3] — 2026-09-18

### Ajouté

- Un vélo sans calibration reçoit un modèle tiré de valeurs publiées, et
  l'outil dit d'où il vient. (#18)
- `--vitesse-a-plat` à la place de `--puissance`, pour qui n'a pas de FTP ;
  une table indicative FTP → vitesse à plat → moyenne compteur se lit dans
  les deux sens. (#17, #18)
- Des pauses déclarées (`--pause`), même une nuit : l'heure de passage météo
  et l'heure d'arrivée en tiennent compte. (#18)
- Un GPX importé reçoit trafic, revêtement et feux, repris d'un tracé
  rerouté ; au-delà de 25 m, l'outil dit qu'il ne sait pas. (#16, #18)

### Modifié

- Entre deux boucles, la plus proche de la distance demandée l'emporte ; à
  écart égal, la plus longue. (#15)

### Corrigé

- Le temps porte à porte suit la puissance demandée, et l'écran dit à partir
  de quel kilomètre la prévision change de modèle. (#18)

## [0.6.2] — 2026-09-18

### Corrigé

- Les culs-de-sac sont coupés par le moteur de tracé lui-même. (#14)
- Les boucles ne sont plus systématiquement trop courtes. (#14)

## [0.6.1] — 2026-09-18

### Ajouté

- Deux durées côte à côte : le temps en roulant et le porte à porte, arrêts
  compris, avec l'explication de leur écart. (#13)
- Le facteur entre vitesse et moyenne compteur se règle par vélo. (#13)

## [0.6.0] — 2026-09-18

### Corrigé

- Les fichiers TCX et GPX précédés d'un préambule (BOM, blancs) se lisent.
  (#12)

### Sécurité

- Aucun fichier d'activité réel ne peut partir dans le dépôt par erreur. (#12)

Sprint de mesure : trois corrections du modèle annoncées ont été réfutées
avant d'être codées. (#12)

## [0.5.2] — 2026-09-17

### Ajouté

- Une API et un écran web : demander une boucle ou une sortie, régler son
  profil et ses vélos dans un assistant. (#11)
- Deux façons de donner une direction ; sans direction, la commande `boucle`
  balaie tout l'horizon. (#11)
- L'outil dit quelles propositions il écarte parce qu'elles se ressemblent.
  (#11)

Grosse livraison hors sprint : l'arrivée de l'API et de l'interface web.
(#11)

## [0.5.1] — 2026-09-16

### Ajouté

- La page du jour peut tourner en conteneur chez un hébergeur, derrière une
  authentification. (#10)

## [0.5.0] — 2026-09-16

### Ajouté

- Le vent entre dans le placement des blocs : un bloc vent de face n'a pas
  la même longueur que vent de dos. (#7)
- Toute la séance est visible, échauffement, récupérations et retour au calme
  compris. (#7)
- Trois propositions contrastées, chacune meilleure sur un axe, et le
  cycliste choisit. (#7, #8)
- La page du jour : les propositions superposées sur une carte, un GPX par
  proposition, et des flèches de vent. (#7, #8)
- Au-delà de la portée du modèle fin, la météo bascule sur le modèle global
  au lieu de disparaître. (#9)

### Corrigé

- Feux et passages piétons comptés à nouveau après l'élagage des antennes ;
  une étape libre compte dans la distance. (#7)
- Des chiffres plus justes sur la page : part de nationales, nombre de feux,
  alerte de séance raccourcie seulement au-delà du seuil réglé. (#9)

## [0.4.0] — 2026-09-15

### Ajouté

- `ourouler sortie` : la séance du jour lue dans Intervals.icu, ses blocs
  placés sur le terrain, le GPX du parcours réellement roulé, une carte et
  la tenue conseillée. (#5)
- `ourouler seance` : la longueur de route nécessaire à chaque bloc, et
  celle qu'il faut pour faire demi-tour. (#5)

### Modifié

- Le retour au calme peut s'allonger, mais plus être raccourci. (#6)

## [0.3.0] — 2026-09-13

### Ajouté

- Les culs-de-sac des boucles sont détectés et retirés. (#4)
- `ourouler routes` : rejouer ses sorties pour comparer le moteur de tracé
  à ses routes réelles. (#4)
- `ourouler calibrer` : le modèle physique de chaque vélo, validé sur des
  sorties qu'il n'a pas vues. (#4)
- `ourouler simuler` et `ourouler comparer` ; le temps estimé par le modèle
  s'affiche dans `boucle`. (#4)

## [0.2.0] — 2026-09-13

### Ajouté

- `ourouler boucle` : des boucles de la distance et de la direction voulues,
  comparées sur le trafic, le revêtement, les virages, la pluie et le vent à
  l'heure de passage, avec le GPX de la meilleure. (#2, #3)
- `--gpx` évalue un parcours existant. (#2, #3)
- `ourouler inventaire --synchroniser` : chaque sortie rattachée à son vélo
  par son capteur de puissance. (#2, #3)

## [0.1.0] — 2026-09-13

### Ajouté

- `ourouler meteo` : pluie, vent et ressenti par direction et par heure
  autour du point de départ, avec un second modèle en indice de confiance.
  (#1)
- `ourouler inventaire` : les sorties FIT, GPX et TCX par vélo et par mois,
  depuis Intervals.icu et un cache local. (#1)
- `ourouler config` : vérifier sa configuration, clé masquée. (#1)
