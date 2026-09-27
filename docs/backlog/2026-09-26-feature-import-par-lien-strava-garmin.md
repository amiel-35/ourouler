# Import de l'historique par lien Strava ou Garmin

Type : feature
Statut : validée le 26/09/2026

## Pourquoi

Amiel a dit, en dogfooding le 25/09/2026, « pour Strava et Garmin on a vu aussi qu'une méthode pouvait être de copier-coller le lien » — reprenant la décision du 17/09/2026 ([[Q48]]) : « on ne fait pas traverser une archive de plusieurs centaines de mégaoctets à un navigateur ». Aujourd'hui `DepotHistorique.tsx` n'offre que le téléversement (L9.2) : sur mobile, une archive Strava de 665 Mo doit transiter par le téléphone avant d'arriver au serveur — exactement ce que le lien évite.

## Ce que je veux voir

- Sur l'écran de dépôt (assistant d'accueil et Réglages, `DepotHistorique.tsx`) : un champ « coller le lien reçu par courriel » à côté du bouton de dépôt de fichier existant, avec le texte « pour Strava ou Garmin, demandez votre export puis collez ici le lien reçu par courriel — le fichier ne transite jamais par votre appareil ».
- Le serveur va chercher l'archive lui-même : liste blanche par hôte **et** préfixe de chemin (S3 sert les deux plateformes depuis le même hôte), suivi des redirections uniquement tant qu'elles restent dans la liste blanche, refus de toute résolution vers une plage privée, plafond de taille et de durée. Un lien hors liste blanche donne un message clair (« ce lien ne vient pas d'une plateforme reconnue ») plutôt qu'une erreur technique.
- Le lien n'est jamais journalisé, jamais mis en paramètre d'URL visible, jamais conservé une fois l'import terminé — même régime que le mot de passe BRouter (`connecteurs/brouter.py`).
- Lecture par plage (`Range`) du répertoire central du zip pour ne télécharger que la liste des entrées, puis seulement les entrées utiles (`activities.csv`, `bikes.csv`, `activities/*.fit.gz`/`.gpx` côté Strava ; `DI_CONNECT/...` côté Garmin) : jamais les 500 Mo de photos et vidéos d'un export Strava, jamais `contacts.csv`/`followers.csv`/`messaging.json` et les autres fichiers personnels hors sujet listés dans `docs/services_externes.md`.
- Une fois l'import terminé, si la couverture temporelle trouvée est nettement plus courte que ce à quoi on s'attendrait (compte ancien, peu de sorties remontées), l'import se termine quand même normalement : un message dit « cet historique semble incomplet, la plateforme a peut-être scindé l'export en plusieurs liens », avec la couverture trouvée (première et dernière sortie), et propose de coller un second lien.
- Le lien expiré donne « ce lien a expiré, redemandez un export à la plateforme », jamais une erreur réseau brute. Le message ne cite aucune durée de validité (celle de Strava reste à mesurer).
- Le téléversement de fichier reste disponible en secours, inchangé, pour qui a déjà l'archive sur son disque.

## C'est fini quand

Amiel colle, depuis son téléphone, le vrai lien d'un export Strava ou Garmin qu'il vient de demander (ou une archive de test si le lien a expiré d'ici l'implémentation) ; l'import se termine sans qu'aucun fichier n'ait transité par son appareil, les sorties apparaissent dans son historique, et il vérifie qu'aucune trace du lien ne subsiste (logs, base) après coup.

## Hors sujet

- Toute plateforme hors Strava et Garmin (Polar, Wahoo, COROS) — V1 se limite aux deux que le mainteneur peut vérifier lui-même (Q48).
- L'estimation de puissance sans capteur à partir d'un import GPS seul — c'est [[Q49]], un sujet séparé.
- Un import automatique récurrent (revenir chercher les nouvelles sorties tout seul) : ici on importe un instantané, une fois, comme aujourd'hui par téléversement.

## Acquis techniques

- Le connecteur suit la convention du dépôt (client HTTP injectable, aucun secret en attribut ni en `repr`, tests sans réseau) comme `connecteurs/brouter.py`.
- La garde SSRF (liste blanche hôte+préfixe, résolution DNS puis vérification de plage privée, pas de redirection hors liste, plafond de taille et de durée) est un composant partagé, testable indépendamment de Strava et Garmin.
- Les liens enveloppés (Outlook safelinks, puis `email.strava.com`, mesurés sur l'export réel) sont suivis, mais seulement si la destination finale est dans la liste blanche hôte+préfixe ; chaque saut est revérifié.
- Le message « historique tronqué » compare la couverture temporelle trouvée (première et dernière activité du dérivé extrait) à `Config.historique_depuis` : si la première sortie trouvée est nettement postérieure à cette date pour un compte qui semble plus ancien, le doute se dit ; le seuil exact est un réglage interne, affiné après un premier import réel.

## Questions ouvertes

- La durée exacte de validité du lien Strava (le tableau de `services_externes.md` la note « à mesurer ») — à confirmer sur un prochain export réel avant d'écrire le message d'expiration.

## Déjà en place / Doctrine révisée

- `docs/services_externes.md` — mesure faite sur deux archives réelles (Strava, Garmin) : hôte final (s3.amazonaws.com), préfixe de chemin par plateforme, redirections traversées (safelinks Outlook puis email.strava.com pour Strava), tailles réelles (665 Mo Strava, 240 Mo Garmin), validité (3 jours Garmin confirmés ; Strava à mesurer précisément), HEAD refusé (403) sur les liens pré-signés, lecture par plage (Range/206) du répertoire central du zip sans tout télécharger (3 730 entrées lues en tirant 4 Mo sur 665).
- `docs/services_externes.md` — liste des chemins utiles et à ignorer par plateforme (`activities.csv`, `profile.csv`, `bikes.csv` côté Strava ; `DI_CONNECT/...` côté Garmin) et le piège des zones de puissance d'un autre sport dans l'export Garmin.
- `src/ourouler/activites/import_archive.py::importer` — décompression en mémoire (.gz, .zip, .zip imbriqués Garmin), plafonds de taille et de ratio vérifiés à la lecture (pas sur l'en-tête), fichier corrompu ou entrée hors liste jamais bloquant (`RapportImport.ignorees`).
- `src/ourouler/api/imports_fond.py` + `api/taches_fond.py` — tâche de fond partagée (verrou unique import/calibration), cloisonnement par propriétaire, suivi d'avancement, ménage des dépôts temporaires orphelins.
- `front/src/composants/DepotHistorique.tsx` — écran de dépôt (téléversement) déjà branché sur l'assistant d'accueil et sur Réglages, avec suivi de progression et reprise après rechargement.
- `src/ourouler/connecteurs/` — convention du dépôt pour un connecteur réseau : client HTTP injectable, jamais de secret en attribut ni en repr, tests sans réseau (`brouter.py` comme modèle).
- `docs/services_externes.md`, §Non vérifié — mesure QP8(c) déjà faite : sur l'archive Garmin réelle du mainteneur, aucun `_2` observé après un `_1.zip`, hypothèse retenue « une seule archive ».
- QP8 (25/09/2026) : (c) puis (b) — mesurer sur une vraie archive avant de coder l'écran, puis détecter un historique tronqué après import. Le (c) est fait ; la fiche portait sur ce qu'il restait — le connecteur lui-même et le (b).
- Q48 (17/09/2026) : le lien est la voie principale, le téléversement reste le secours ; on jette le brut, on garde le dérivé ; V1 couvre Strava et Garmin seulement ; pas de CLI pour les utilisateurs, le dépôt se fait sur le serveur ; le lien est un secret (jamais journalisé, jamais en paramètre d'URL, jamais conservé après usage) ; garde SSRF obligatoire (liste blanche hôte+préfixe, refus des plages privées après résolution DNS, aucune redirection hors liste blanche, plafond de taille et de durée) ; expiration à sept jours chez Strava (Garmin mesuré à 3 jours, voir `services_externes.md`).
- Préparation sprints 11/12 (25/09/2026) : cette fonctionnalité vient après B6 (même chaîne d'import — le brut jeté), placé au sprint 13 esquissé.
- Tranché le 26/09/2026 : avertir sans bloquer — l'import se termine, un message dit que l'historique semble incomplet et propose de coller un second lien.
