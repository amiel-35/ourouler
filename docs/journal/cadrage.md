# Prompt de cadrage — projet « où rouler » (vélo × météo × séance)

À coller en premier message d'une nouvelle session Claude Code, dans le
dossier du nouveau projet (dépôt de code pur, pas un projet `pj`).
Rédigé le 12/09/2026 à partir d'une discussion avec Amiel.

---

## Qui je suis, ce que je veux

Je suis Amiel, cycliste avec capteur de puissance, entraînement suivi dans
Intervals.icu (FTP 258 W, 91 kg), montre et compteur Garmin, historique
depuis 2020 mais **n'utiliser que les données à partir de décembre 2023**
(plusieurs vélos, roues et positions avant ; calibrer par vélo et par
période). J'habite près de Rennes (Ille-et-Vilaine).

Le besoin, en une phrase : *« je vais faire du vélo ; au sud, au nord ou
à l'est, où va-t-il pleuvoir ? »* — puis en tirer un parcours de la bonne
durée dans la bonne direction, cohérent avec la séance du jour, avec la
tenue à mettre, et le pousser sur mon Garmin.

Je veux un **projet open source, autonome, utile à d'autres cyclistes** :
Python, ligne de commande + bibliothèque, aucune dépendance à Home
Assistant (HA pourra en consommer les résultats plus tard, pas avant).
Les données et les clés d'API restent chez l'utilisateur.

## Ce que l'outil doit faire (périmètre cible)

1. **Météo par direction et par heure** : depuis un point de départ, une
   couronne de points (par ex. 15/25/40 km dans 8 directions) sur les
   prochaines heures : pluie (mm/h, quantité — AROME ne donne pas de
   probabilité, la probabilité vient du modèle d'ensemble), vent (force et
   direction), température ressentie. Source : Open-Meteo, modèle
   **Météo-France AROME 1,3 km** en France (`models=meteofrance_arome_france_hd`,
   pluie horaire et par 15 min), ICON/ECMWF ailleurs ou en second avis ;
   le désaccord entre modèles = indice de confiance, pas une moyenne.
   Option : Solcast (rayonnement satellite, 10 appels/jour gratuits).
2. **La séance du jour** depuis Intervals.icu (API publique ; un MCP
   Intervals existe déjà dans mon environnement) : durée, structure
   (échauffement, blocs puissance × durée, récupérations), type de vélo
   (route ou CLM = paramètre).
3. **Le tracé** : générer des boucles candidates de la bonne distance
   dans la direction sèche, vent de face à l'aller et poussé au retour.
   Moteurs : **BRouter** (profils `fastbike-lowtraffic`/`verylowtraffic`,
   auto-hébergeable, GPX natif) ou **GraphHopper** (mode boucle par
   distance, API gratuite à petit volume). Strava n'a PAS d'API de
   génération (lecture/export GPX de mes itinéraires seulement) : prévoir
   l'import d'un GPX Strava comme alternative au générateur.
   **Critères de coût du tracé** : trafic, revêtement, et **préférence
   pour les carrefours à droite** (tourne-à-gauche plus cher, surtout sur
   route à trafic ; boucles dans le sens horaire en France, anti-horaire au
   Royaume-Uni).
4. **La boucle séance ↔ terrain** (le cœur, qui n'existe nulle part en
   libre) : 200 W ne font pas la même vitesse en montée qu'en descente.
   Un modèle physique (puissance, masse, CdA par vélo, roulement, pente,
   vent) **calibré sur mon historique réel** simule chaque candidate :
   vitesse et temps par segment, donc où tombent les blocs. On garde la
   boucle dont le terrain colle à la séance (seuil = plat/faux plat
   régulier sans carrefours ; force = côtes ; test = montée dégagée) ;
   sinon on change distance/direction et on itère.
5. **Sorties** : un GPX ; un résumé (départ conseillé, direction, distance,
   temps estimé, pluie/vent le long du parcours À L'HEURE OÙ J'Y SERAI) ;
   la **tenue** (règles à me demander : seuils de température ressentie,
   vent, pluie) ; envoi optionnel vers **Garmin Connect** (un accès existe :
   `~/.config/ha/garmin-token` / `garmin-user`, à ne jamais copier dans le
   dépôt).
6. **Ingestion de l'historique toutes sources** : dénominateur commun =
   fichiers **FIT / GPX / TCX** (export Garmin, export Strava complet,
   API Intervals, Wahoo…) → un seul lecteur + des connecteurs.

## Principes

- Natif et simple d'abord ; pas de service payant obligatoire ; tout doit
  tourner sur un Mac ou un petit serveur Linux.
- Configuration par fichier (point de départ, vélos avec masse/CdA de
  départ, règles de tenue, clés d'API) ; jamais de donnée personnelle
  dans le dépôt ; licence AGPL-3.0-or-later.
- Ne rien affirmer sans mesure : le modèle physique est validé sur des
  sorties qu'il n'a pas vues (erreur de temps par sortie), et la météo
  est comparée au réel après coup pour mesurer la fiabilité par modèle.
- Le module météo et le module tracé doivent être utilisables seuls
  (sous-commandes indépendantes) avant même que la boucle séance-terrain
  existe.

## Découpage proposé (à challenger)

- **S0 — Données** : lecteur FIT/GPX/TCX, connecteur Intervals, cache
  local ; premier inventaire de mes sorties depuis décembre 2023 par vélo.
- **S1 — Météo par direction** : sous-commande `meteo` (démo déjà faite le
  12/09 : 7 points à 25 km autour de Rennes, AROME, pluie 8h-14h + vent).
- **S2 — Tracé** : sous-commande `boucle` (BRouter ou GraphHopper, GPX,
  coûts de virage à droite, revérification pluie le long du tracé).
- **S3 — Modèle physique** : calibration par vélo sur l'historique,
  validation croisée, rapport d'erreur.
- **S4 — Boucle séance ↔ terrain** : sous-commande `sortie` qui enchaîne
  tout et produit GPX + résumé + tenue.
- **S5 — Garmin Connect** : envoi du parcours ; puis, plus tard, une
  page dans Home Assistant.

## Ce que tu dois me demander avant de coder

- Emplacement et nom du dépôt (je te dis où ; ne crée rien à la racine
  de `~/Projets` sans mon accord), gestionnaire (`uv` + `pyproject`).
- La liste de mes vélos (nom, usage route/CLM, masse, roues) et à quelles
  sorties Intervals ils correspondent.
- Mes règles de séance (que veut dire « un bloc doit tenir sur un
  terrain ») et mes règles de tenue.
- Le moteur de tracé à installer (BRouter auto-hébergé ou GraphHopper API)
  et où (Mac ou serveur Linux) — installation seulement avec mon accord.

## Façon de travailler

- Cadrage d'abord, en français, court ; puis lots avec critères
  d'acceptation mesurables ; le code substantiel par un sous-agent, relu
  par un second avant de me montrer ; un sujet à la fois.
- Chaque lot livré = une commande qui tourne sur mes vraies données, pas
  une promesse.
