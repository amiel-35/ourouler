# Les archives d'export Garmin et Strava, mesurées sur de vraies données

Notes de mesure du 19/09/2026, déplacées ici depuis
`docs/services_externes.md`, qui n'en garde que les règles durables. Tel
qu'écrit à l'époque : l'import par **lien** dont il est question plus bas
n'a pas été construit ; l'import passe par un dépôt de fichier
(`src/ourouler/activites/import_archive.py`).

Tout ce chapitre vient de **deux archives réelles**, demandées et lues pour
l'occasion — pas d'une documentation de plateforme. Ce qu'on croyait savoir
avant était faux sur plusieurs points, tous corrigés ici.

## Le lien n'est pas celui de la plateforme, et il change à chaque saut

| | Garmin | Strava |
|---|---|---|
| hôte final | `s3.amazonaws.com` | `s3.amazonaws.com` |
| préfixe de chemin | `it-gdpr-bucket/` | `strava.portability/athlete/<id>/export/live/` |
| validité | **3 jours** (`X-Amz-Expires=259200`) | à mesurer |
| taille | 240 Mo | **665 Mo** |
| redirections avant d'y arriver | aucune | **deux** |

Trois conséquences qui décident de l'implémentation :

1. **La liste blanche porte sur l'hôte *et* le préfixe de chemin.** Les deux
   plateformes servent depuis `s3.amazonaws.com`, où la moitié d'Internet est
   hébergée : l'hôte seul ne filtre rien. C'est le préfixe qui discrimine.
2. **Elle s'applique à chaque saut, pas à ce que la personne colle.** Le lien
   Strava reçu lors de la mesure traversait une enveloppe
   `safelinks.protection.outlook.com` (ajoutée par sa messagerie) puis un
   traceur `email.strava.com`, avant d'atteindre S3. Vérifier seulement l'URL
   collée laisserait passer n'importe quoi ; ne pas suivre les redirections du
   tout casserait le cas normal.
3. **`HEAD` est refusé (403).** Une URL S3 pré-signée n'est valable que pour la
   méthode signée, ici `GET`. Sonder la taille avant de télécharger ne marche
   pas — il faut lire `Content-Length` sur le `GET` lui-même.

## On n'a pas besoin de télécharger l'archive

**S3 accepte les requêtes par plage** (`Range`, réponse `206`). Le répertoire
central d'un zip étant à la fin, on lit **la liste complète des entrées** en
récupérant les derniers mégaoctets, puis on ne va chercher que les octets des
entrées qu'on veut.

Mesuré sur l'archive Strava : **les 3 730 entrées lues en téléchargeant 4 Mo
sur 665**. Ce qui nous intéresse vraiment — `activities.csv`, `profile.csv`,
`bikes.csv` et un an de sorties — tient dans l'ordre de 20 Mo.

C'est ce qui fait de la **liste blanche d'entrées** la pièce centrale plutôt
qu'une précaution après coup : elle ne décide plus seulement de ce qu'on
extrait, elle décide de ce qu'on **télécharge**. Et moins on extrait, moins il
y a à isoler.

## Garmin : où sont les choses, et les pièges

```
DI_CONNECT/DI-Connect-Uploaded-Files/UploadedFiles_0-_Part{1..6}.zip   238 Mo
DI_CONNECT/DI-Connect-Wellness/<id>_powerZones.json
DI_CONNECT/DI-Connect-Wellness/<id>_heartRateZones.json
DI_CONNECT/DI-Connect-Wellness/<id>_bioMetrics_latest.json
customer_data/customer.json
```

Le profil **y est** : FTP et paliers de puissance, FCmax, FC de repos, seuil
lactique, zones cardiaques. C'est ce qui permet à l'étage export de rendre ce
que la route `athlete` d'Intervals rend — pour beaucoup plus de
monde, puisque peu de cyclistes ont Intervals.

Trois pièges, tous rencontrés :

- **Les zones trouvées peuvent être celles d'un autre sport.** Le
  `powerZones.json` mesuré porte `sport = RUNNING` et une FTP de course à
  pied bien plus haute que la FTP vélo. Prendre le premier fichier de zones
  donnerait un cycliste bien trop fort — et **la valeur reste plausible**, donc
  l'erreur ne se verrait pas. **Filtrer sur le sport.** La confirmation par
  l'utilisateur ne rattrape pas ce cas : celui qui ne connaît pas sa FTP —
  précisément celui pour qui l'entonnoir existe — cliquera « oui ».
- **Les sorties sont dans des archives imbriquées.** Six `.zip` dans le `.zip`.
- **Le ratio de décompression y est de 11**, quand celui de l'enveloppe
  extérieure est de 1,5 : 9 Mo qui deviennent 100, pour 2 487 fichiers. Un
  plafond de ratio posé sur l'enveloppe ne verrait rien.

## Strava : où sont les choses, et ce qu'on ignore

```
activities.csv        1,1 Mo   l'index de toutes les sorties, sans en ouvrir une
profile.csv                    l'athlète
bikes.csv                      les vélos, avec leurs noms
activities/           165 Mo   2 613 .fit.gz et 311 .gpx
media/                504 Mo   photos et vidéos — 76 % de l'archive
routes/                27 Mo
```

**76 % de l'archive sont des photos et des vidéos**, dont ce produit n'a aucun
usage. Sans liste blanche, on les ferait traverser le serveur pour rien.

Et ce qu'on ne doit **jamais** lire, présent dans la même archive :
`contacts.csv`, `followers.csv`, `following.csv`, `messaging.json`,
`reactions.csv`, `logins.csv`, `mobile_device_identifiers.csv`. Ne pas
extraire une donnée personnelle est la seule façon sûre de ne pas la
conserver (règle absolue 1).

## Ce que ça corrige

- « Garmin met plusieurs jours là où Strava met des heures » : l'archive
  Garmin mesurée est arrivée **le jour même**. La conclusion reste bonne —
  le parcours doit survivre à une interruption longue — mais parce que le
  délai **n'est pas garanti**, pas parce qu'il serait toujours long. Ne rien
  promettre au cycliste au-delà de « de quelques heures à quelques jours ».
- « durée de validité inconnue chez Garmin » : **3 jours**, dit par le
  courriel et confirmé par le paramètre signé.
- « agencement interne de l'archive, seul point qui demande un adaptateur » :
  vrai, et c'est plus que de la lecture — c'est la **liste de ce qu'on va
  chercher**, par plateforme, qui décide aussi du réseau consommé.

## Non vérifié

L'export en plusieurs parties. Le fichier Garmin s'appelle `<uuid>_1.zip`, ce
que le suffixe rend suspect, mais rien ne dit qu'un `_2` existe et aucun n'a
été observé. Hypothèse retenue : **une seule archive**. Si un jour un `_2` existe, il doit se **voir** plutôt que
d'importer la moitié d'un historique en silence.
