# Discovery et parcours — l'interface de ourouler

Rédigé le 16/09/2026, à partir du brief du mainteneur (inscription modérée,
assistant de configuration, itinéraire manuel, import de séance, clé d'accès)
et de ce que le dépôt sait déjà faire au sprint 5.

**Ce document ne tranche rien.** Il décrit des parcours, un inventaire
d'écrans et leurs états, et il remonte au mainteneur tout ce qui demande un
arbitrage — en §5, numéroté. Aucune fonctionnalité n'y est inventée : ce qui
n'est ni dans le brief ni dans le dépôt est posé comme question, pas comme
décision. Les exemples de personnes, d'adresses et de valeurs sont inventés.

Cadre imposé, rappelé une fois : doctrine §10 (multi-utilisateur,
authentification déléguée, Postgres, isolation vérifiée côté serveur, RGPD
dès la première version hébergée), sprint 7 (API puis front), sprint 8 (un
invité se débrouille **sans** le mainteneur). La page HTML autonome du
sprint 5 est explicitement « la maquette du futur front » : ce document la
prolonge, il ne la jette pas.

---

## 1. Les deux utilisateurs

### 1.1 Ce qui les sépare, en une phrase chacun

**Le mainteneur** — tout est déjà renseigné, son Intervals est branché, son modèle
physique est calibré sur 162 sorties, il roule 3 à 4 fois par semaine depuis
le même point de départ, et il connaît le produit parce qu'il l'a écrit. Ce
qu'il veut d'une interface : **moins de gestes**, la page du jour sur son
téléphone, et le GPX dans son compteur. Il n'a pas besoin qu'on lui explique
ce qu'est un couloir de 11 km.

**L'invité** — un copain cycliste, invité par le mainteneur. Zéro sortie dans le
système, donc **aucune calibration possible** : le modèle physique tournera
sur des paramètres génériques et devra le dire (sprint 8, en toutes lettres).
Il ne connaît ni le vocabulaire du produit, ni ses limites mesurées. Et le
sprint 8 pose la barre : il doit créer son compte, renseigner son profil,
brancher son Intervals, obtenir une boucle qui tient la route **sans
déranger le mainteneur**. Un parcours qui suppose un coup de fil est un parcours raté.

### 1.2 Écran par écran, ce qui change

| Écran | Le mainteneur | L'invité |
|---|---|---|
| Demande d'accès (E1) | ne le voit jamais — son compte préexiste | **c'est son premier contact**, et il ne sait pas encore ce que fait l'outil |
| File de modération (E4) | **lui seul la voit** — c'est son écran d'administration | n'existe pas pour lui ; il n'en voit que le délai |
| Assistant, identité (E8) | déjà rempli | cinq champs, dont l'âge, dont il ne sait pas à quoi il sert |
| Assistant, FTP et zones (E9) | FTP connue, zones venues d'Intervals | **le point de rupture** : « FTP » peut ne rien lui dire, ou il peut ne pas la connaître |
| Assistant, départ (E10) | une adresse qu'il a déjà donnée | une adresse à saisir, et le produit ne rend pas le même service partout (Q31) |
| Assistant, vélo (E11) | deux vélos réels, calibrés séparément | un vélo, un type, un poids approximatif — aucune calibration derrière |
| Assistant, Intervals (E12) | branché depuis le sprint 1 | **facultatif et reportable** ; sans lui, tout le parcours « semaine » disparaît |
| Aujourd'hui (E14) | son écran par défaut, ouvert le matin | vide tant qu'il n'a rien demandé, s'il n'a pas branché Intervals |
| Ma semaine (E15) | 48 séances planifiées par son entraîneur, rythme connu | **écran inexistant sans Intervals** ; avec Intervals mais sans plan, écran vide |
| Itinéraire manuel (E16) | chemin secondaire — sa séance vient d'Intervals | **son chemin principal** s'il n'a pas branché Intervals |
| Propositions (E19) | lit les chiffres, sait ce que vaut « 1,3 feux/km » | a besoin qu'on lui dise **ce qui distingue** les trois, pas ce qui les mesure |
| Détail et emporter (E20) | le geste qui compte, trois fois par semaine | le geste de vérité : si le GPX n'arrive pas dans son compteur, il ne revient pas |
| Compte et données (E24) | accessoire | **obligatoire** dès la première version hébergée (RGPD, doctrine §10) |

### 1.3 Deux asymétries qui ne se rattrapent pas par du design

1. **Le temps estimé n'a pas la même valeur pour les deux.** Chez le mainteneur il
   est calibré (MAE 4,2 % et 2,4 % selon le vélo, sur sorties non vues). Chez
   l'invité il vient de paramètres génériques. C'est le même nombre à
   l'écran, ce n'est pas la même promesse — et la règle absolue 5 interdit de
   laisser croire l'inverse (question 4).
2. **Le produit ne rend pas le même service partout**, mesuré le 16/09 :
   distance de dégagement urbain 6 km dans la ville du mainteneur et à Angers, 12 km à Nantes,
   jamais atteinte à moins de 15 km aux Lilas. Un invité francilien aura
   des blocs qui portent quatre à cinq feux, et l'outil n'a pas aujourd'hui
   le mode circuit qui serait sa vraie réponse (Q32). L'interface peut le
   **dire honnêtement** ; elle ne peut pas le réparer (question 12).

---

## 2. Les parcours de bout en bout

Notation : `E<n>` renvoie à l'inventaire du §3. `→` enchaînement,
`⟂` branche.

### 2.1 Demande d'accès → modération → invitation → première connexion

```
E1 accueil public + formulaire de demande
   ⟂ champs invalides → E1 en erreur, le champ est nommé
   → E2 « demande enregistrée », et ce qu'il se passe ensuite
        ⟂ le demandeur ferme l'onglet : rien de plus n'est attendu de lui
E4 file de modération (le mainteneur)
   ⟂ accepter → envoi du message d'invitation (Brevo) → E3
   ⟂ refuser  → question 6 : message de refus, ou silence ?
   ⟂ ne rien faire → la demande vieillit (question 6 : délai annoncé ?)
E3 message d'invitation (hors application) : un lien, une phrase, rien d'autre
   → E6 activation : le lien ouvre la première connexion
        ⟂ lien expiré ou déjà utilisé → E6 en erreur, avec un chemin
          de rattrapage qui ne passe pas par le mainteneur (contrainte sprint 8)
   → E5 connexion (identité déléguée — question 5)
   → E7 assistant de configuration
```

Deux points de conception, pas des décisions :

- **E2 est le seul endroit où l'on peut amortir l'attente humaine.** Entre le
  formulaire et le message, il y a un humain. C'est le seul délai du parcours
  qu'aucune optimisation technique ne réduit (§4, moment M1).
- **Le lien d'invitation est le seul objet qui relie les deux moitiés du
  parcours.** S'il se perd, casse ou expire, l'invité n'a par construction
  aucun autre chemin — sauf à redemander en E1.

### 2.2 L'assistant de configuration

Ordre proposé, du plus sûr au plus fragile : on demande d'abord ce que tout
le monde sait, on garde pour la fin ce qui peut faire abandonner.

| Étape | On demande | Obligatoire ? | Reportable ? | Sans cette donnée, ce qui ne marche pas |
|---|---|---|---|---|
| E8 identité | prénom, nom, âge, poids | poids : oui | âge, nom : question 7 | le poids entre dans le modèle physique (masse totale) ; l'âge n'a pas d'usage établi dans le dépôt |
| E9 FTP et zones | FTP ; zones **dérivées** en V1, édition précise en V2 (brief) | FTP : oui | question 11 | sans FTP, aucune cible de puissance : ni placement des blocs, ni Z2 pour l'itinéraire manuel |
| E10 départ habituel | une adresse, géocodée | oui | non — rien ne tourne sans point de départ | tout |
| E11 vélo | type (route / CLM / gravel), poids | oui | non | la simulation ; le type conditionne le CdA de départ |
| E12 Intervals | clé d'API, identifiant d'athlète | **non** | **oui, à tout moment depuis E21** | la semaine (E15), la séance du jour automatique ; l'itinéraire manuel reste entier |
| E13 récapitulatif | rien — on montre et on lance | — | — | — |

Ce que l'assistant **ne** demande **pas**, et il faut le dire à voix haute :
CdA, coefficient de roulement, profil BRouter, modèle météo, élasticité des
zones 2, bornes de tenue. Ce sont des réglages du fichier de configuration
du mainteneur ; les exposer à un invité en V1 serait le meilleur moyen de le perdre.
Le brief est d'accord : « édition précise des zones en version 2 ».

Branches :

```
E7 → E8 → E9 → E10 → E11 → E12 → E13
      ⟂ E9 : « je ne connais pas ma FTP »  → question 2 et question 11
      ⟂ E10 : adresse introuvable → E10 en erreur, saisie de coordonnées
        ou choix sur une carte (aucun des deux n'existe aujourd'hui)
      ⟂ E10 : adresse en zone dense → question 12 (le dire, ou non)
      ⟂ E12 : « plus tard » → E13 avec un rappel, et E14/E15 en état
        « Intervals non branché » qui propose E16
      ⟂ E12 : clé refusée (HTTP 401) → message qui nomme la clé et
        l'identifiant d'athlète, comme le fait déjà le connecteur
E13 → première génération → E18 → E19
```

**Le second vélo.** Le brief demande « en V1 un seul vélo mais schéma qui
permet d'en avoir 2 ». Conséquence de parcours : E11 est une **liste à un
élément**, pas un formulaire unique — l'écran d'ajout n'est simplement pas
ouvert en V1. C'est la seule manière d'éviter une refonte d'écran le jour où
le second arrive (question 7 pour la suite : où se choisit le vélo ?).

### 2.3 La semaine type de quelqu'un qui a branché Intervals

```
Lundi soir — E15 « ma semaine » : les séances planifiées, une ligne chacune,
  avec durée, forme (à blocs / continue) et un bouton « proposer un parcours »
   ⟂ aucune séance planifiée → état vide qui renvoie vers E16
   ⟂ une séance dans plus de 3 jours → le bouton reste, mais le vent n'est
     pas promis (HORIZON_ORIENTATION_J = 3) — et le brief dit 2 (question 1)
Mercredi matin — E14 « aujourd'hui » : la séance du jour est déjà là,
  trois propositions calculées cette nuit (forme actuelle de l'hébergé minimal)
   ⟂ pas de séance planifiée aujourd'hui → l'écran le dit, il ne rend pas
     une erreur ni la page de la veille (contrat hébergé minimal, §4 et §5)
   ⟂ la page date d'hier → elle doit dire de quand elle date (idem, §5)
   → E19 les trois propositions → E20 détail → GPX au compteur
Samedi, sortie du club préparée le mercredi — E15 → E16 pour la date
   ⟂ au-delà de la portée d'AROME : le repli sur le modèle global est
     annoncé dans l'en-tête (Q19, mise en service §2)
```

Deux frictions déjà identifiées dans le dépôt, qui deviennent des choix
d'interface : la fenêtre de la semaine (le connecteur ne sait lire que les
événements **d'un jour**, `evenements(jour)`) et la fraîcheur du calcul —
question 13.

### 2.4 La semaine type de quelqu'un qui n'a pas branché Intervals

C'est le parcours de l'invité par défaut, et il doit tenir seul.

```
E14 « aujourd'hui », état « rien de prévu » → un seul appel à l'action :
  « demander un parcours »
   → E16 formulaire : durée, date, départ, vélo, et l'orientation au vent
        · durée : le brief dit « durée et préparation sur la zone 2 de la
          personne » → la séance implicite est une sortie Z2 (question 11)
        · date : « sans vent si plus de 2 jours » (brief) vs 3 jours mesurés
          (question 1) — c'est cette date qui fait apparaître ou non la
          question d'orientation au vent
        · départ : l'habituel prérempli, remplaçable ponctuellement (brief)
        · vent : « peu importe » est une réponse valable **et le défaut**,
          exactement comme dans `sortie/vent_demande.py`
        · la question du vent ne s'affiche pas si le vent est sous 8 km/h
          (SEUIL_VENT_SENSIBLE_KMH) — l'écran le dit, il ne cache pas sans
          raison
   → E18 génération → E19 → E20
```

Variante « j'ai un fichier de séance » (brief : `.FIT`, `.MRC`, `.ZWO`) :

```
E14 ou E16 → E17 import d'un fichier
   ⟂ format non reconnu → erreur nommée
   ⟂ fichier lu mais sans structure exploitable → on montre ce qu'on a compris
     avant de lancer quoi que ce soit : la liste des étapes, leur durée, leur
     puissance cible. C'est le seul moment où l'utilisateur peut corriger.
   → E18 → E19
```

**Attention, trou réel** : aucun de ces trois formats n'est lu aujourd'hui
**comme une prescription**. Le dépôt lit le FIT comme un fichier
d'**activité** (une sortie déjà faite), et `.MRC` / `.ZWO` n'apparaissent
nulle part. La séance structurée vient exclusivement d'Intervals
(`seance/intervals.py::depuis_workout_doc`). C'est un lot à écrire, pas un
branchement — et sa sémantique est la question 8.

### 2.5 Le jour de la sortie — consulter, choisir, emporter

```
E14 « aujourd'hui », sur le téléphone, avant de s'habiller
   → E19 les trois propositions, contrastées (chacune meilleure sur un axe
     différent : la plus sèche, la meilleure pour les blocs, la plus calme,
     la plus courte) + la phrase qui dit ce qui la distingue
   ⟂ deux propositions seulement, parce que les candidates ne se distinguent
     pas assez : le produit le dit déjà, et il dit pourquoi (L5.3)
   ⟂ une seule, ou aucune : voir les états de E19
   → E20 détail : carte (sélection en couleur pleine, les autres en pointillé
     gris — règle Q20), blocs à leur place, profil d'altitude, météo à l'heure
     de passage, tenue, et les chiffres
   → « emporter » : téléchargement du GPX avec le type MIME
     application/gpx+xml et un nom de fichier lisible sur le téléphone,
     puis partage système vers Garmin Connect / Coros (Q5, close le 15/09)
   ⟂ pas de téléchargement, pas de compte constructeur, pas de bibliothèque
     non officielle : c'est la décision du mainteneur, pas un pis-aller
```

La **tenue** se lit avant de partir et se décide au départ (Q3 : « le départ
est ce qui compte, parce que c'est là qu'on a froid »), avec les ajouts le
long du parcours — enlever, emporter, garder. Sa place dans l'écran suit
cette règle : la tenue de base est un bloc, les ajustements sont une liste
courte en dessous, pas un tableau par heure.

---

## 3. Inventaire des écrans

24 écrans, dont un hors application (E3, le message d'invitation).

| # | Écran | À quoi il sert | Qui le voit | D'où on y arrive | Où on en part |
|---|---|---|---|---|---|
| E1 | Accueil public et demande d'accès | dire ce que fait l'outil, recueillir une demande | tout le monde | lien du mainteneur, adresse directe | E2 |
| E2 | Demande enregistrée | dire ce qu'il se passe ensuite, et quand | demandeur | E1 | fin (le relais est le message) |
| E3 | Message d'invitation *(hors application)* | porter le lien d'activation | invité accepté | E4 (action du mainteneur) | E6 |
| E4 | File de modération | accepter, refuser, voir l'ancienneté des demandes | le mainteneur seul | E21 ou une adresse réservée | E4 (reste sur place) |
| E5 | Connexion | entrer | tous, à chaque retour | adresse directe, lien expiré | E14, ou E7 si profil vide |
| E6 | Activation de l'invitation | consommer le lien, créer le compte | invité | E3 | E7 |
| E7 | Assistant — ce qu'on va demander | annoncer les cinq étapes et leur durée | invité (le mainteneur : jamais) | E6 | E8 |
| E8 | Assistant — identité | prénom, nom, âge, poids | invité | E7 | E9 |
| E9 | Assistant — FTP et zones | FTP, zones dérivées (édition précise en V2) | invité | E8 | E10 |
| E10 | Assistant — départ habituel | l'adresse, géocodée | invité | E9 | E11 |
| E11 | Assistant — vélo | type, poids ; liste à un élément en V1 | invité | E10 | E12 |
| E12 | Assistant — Intervals | clé d'API, facultative et reportable | invité | E11 | E13 |
| E13 | Assistant — récapitulatif | montrer, corriger, lancer la première sortie | invité | E12 | E18 puis E19 |
| E14 | Aujourd'hui | la page du jour : séance, propositions, tenue | tous | connexion, retour, signet | E19, E16, E17 |
| E15 | Ma semaine | les séances planifiées et le bouton qui génère | comptes Intervals branchés | E14 | E18, E16 |
| E16 | Demander un itinéraire | durée, date, départ, vélo, orientation au vent | tous | E14, E15 | E18 |
| E17 | Importer une séance | déposer un `.FIT`, `.MRC` ou `.ZWO`, vérifier ce qui a été compris | tous | E14, E16 | E18 |
| E18 | Génération en cours | tenir l'attente d'un calcul long | tous | E13, E15, E16, E17 | E19 |
| E19 | Les propositions | choisir entre trois options contrastées | tous | E18, E14 | E20 |
| E20 | Détail d'une proposition, et emporter | carte, blocs, météo, tenue, GPX | tous | E19 | partage système (hors application) |
| E21 | Profil et réglages | modifier ce que l'assistant a demandé, brancher Intervals plus tard | tous | menu | E21, E4 (le mainteneur) |
| E22 | Clés d'accès | créer, nommer, révoquer une clé d'accès (« webkey ») | tous | E21 | E22 |
| E23 | Mes sorties proposées | retrouver une proposition passée et son GPX | tous | E14, menu | E20 |
| E24 | Compte et données | exporter, supprimer le compte | tous | E21 | fin |

### 3.1 États, écran par écran

Convention : **vide** · **chargement** · **erreur** · **succès** · *dégradé
métier*. « Sans objet » quand l'état ne peut pas exister.

**E1 Accueil public** — vide : sans objet (l'écran est son propre contenu) ·
chargement : sans objet · erreur : champ invalide, nommé, la saisie est
conservée ; adresse déjà demandée ; adresse déjà titulaire d'un compte →
renvoi vers E5 · succès : E2 · *dégradé : les demandes sont fermées (le mainteneur ne
modère plus, ou une borne de capacité) — l'écran le dit au lieu d'accepter
une demande qui ne sera jamais traitée.*

**E2 Demande enregistrée** — vide/chargement : sans objet · erreur : sans
objet · succès : ce qui va se passer, et **le délai annoncé si l'on décide
d'en annoncer un** (question 6) · *dégradé : sans délai annoncé, cet écran
est une impasse polie — c'est le moment M1 du §4.*

**E3 Message d'invitation** — pas d'états d'écran ; deux échecs propres à un
message : non délivré (Brevo rejette, boîte pleine) et classé indésirable.
Ni l'un ni l'autre n'est visible du produit. C'est un angle mort : **côté
mainteneur, E4 doit montrer qu'une invitation a été envoyée et qu'elle n'a pas été
consommée** — sinon personne ne sait que le parcours est cassé.

**E4 File de modération** — vide : « aucune demande en attente » · chargement :
liste · erreur : l'envoi du message a échoué → la demande **reste** en
attente, elle ne bascule pas en « acceptée » ; réessayer est offert · succès :
la demande passe en « invitée le …, non activée » · *dégradé : invitation
envoyée il y a plus de N jours et jamais activée — à distinguer visuellement
d'une demande neuve, c'est le seul signal que le mainteneur aura d'un lien perdu.*

**E5 Connexion** — vide : sans objet · chargement : redirection vers le
fournisseur d'identité · erreur : refus du fournisseur, compte inconnu (→ E1,
pas un message technique), compte supprimé · succès : E14, ou E7 si le profil
est vide · *dégradé : le fournisseur d'identité est indisponible — un compte
sans mot de passe n'a aucun chemin de secours, sauf la clé d'accès de E22
(question 5).*

**E6 Activation** — vide : sans objet · chargement : bref · erreur : lien
expiré, lien déjà consommé, lien inconnu → **et un chemin de rattrapage qui
ne passe pas par le mainteneur** (sprint 8) · succès : E7 · *dégradé : lien valide
mais compte déjà configuré → E14 directement, ne pas rejouer l'assistant.*

**E7-E13 Assistant** — vide : chaque étape s'ouvre vide, c'est son état
normal · chargement : seulement E10 (géocodage) et E12 (vérification de la
clé) · erreur : par champ, nommé, jamais une trace technique — E10 « adresse
introuvable », E12 « clé refusée » en reprenant les mots du connecteur
(« clé d'API refusée, vérifier api_key et athlete_id ») · succès : l'étape
suivante, avec une progression visible (« 3 sur 5 ») · *dégradé propre à
l'assistant : E12 sauté. L'assistant doit se terminer normalement, pas se
signaler comme incomplet — Intervals est facultatif, et le dire deux fois
donne l'impression d'un produit amputé.* · *dégradé E9 : FTP inconnue
(question 11).* · *dégradé E10 : adresse en zone dense (question 12).*

**E14 Aujourd'hui** — vide : compte neuf sans Intervals → un seul appel à
l'action vers E16 · chargement : la page est pré-calculée, donc « chargement »
ne devrait apparaître que le temps du transfert · erreur : le calcul de la
nuit a échoué → **le dire, avec la date de la dernière page réussie**, jamais
servir la veille en silence (contrat hébergé minimal §5) · succès : séance,
trois propositions, tenue · *dégradés, tous déjà rencontrés : (a) pas de
séance prévue aujourd'hui → l'écran le dit et propose E16 ; (b) la page date
d'hier → bandeau de date ; (c) météo repliée sur le modèle global parce
qu'AROME ne va pas jusque-là → l'en-tête nomme le modèle utilisé (Q19) ;
(d) plusieurs séances le même jour → la plus longue est retenue, les autres
sont nommées, comme le fait déjà `seance_du_jour`.*

**E15 Ma semaine** — vide : « aucune séance planifiée cette semaine » →
E16 · chargement : lecture d'Intervals · erreur : Intervals indisponible ou
clé révoquée → **E16 reste accessible**, une panne de source ne doit pas
fermer le produit · succès : la liste · *dégradé : séance non vélo, ou séance
dont la structure n'est pas lisible — la ligne existe et dit ce qui manque,
elle ne disparaît pas.*

**E16 Demander un itinéraire** — vide : formulaire prérempli avec le départ
habituel · chargement : sans objet, sauf la lecture du vent qui décide
d'afficher ou non la question d'orientation · erreur : durée hors bornes,
date hors fenêtre, adresse ponctuelle introuvable · succès : E18 · *dégradés :
(a) vent sous 8 km/h → la question d'orientation ne s'affiche pas, et l'écran
dit pourquoi plutôt que de l'escamoter ; (b) date au-delà de l'horizon → pas
de promesse de vent, avec le motif ; (c) départ ponctuel très éloigné du
départ habituel → rien n'interdit, mais les routes connues et la calibration
locale ne valent plus grand-chose.*

**E17 Importer une séance** — vide : zone de dépôt · chargement : lecture ·
erreur : format non reconnu, fichier tronqué ou vide → **une erreur nommée,
pas une exception brute** (règle déjà tenue par le lecteur d'activités) ·
succès : l'aperçu de ce qui a été compris, étape par étape, avant toute
génération · *dégradé : fichier lu mais structure pauvre (aucun bloc
identifiable) → traité comme une sortie continue, et l'écran le dit.*

**E18 Génération en cours** — vide : sans objet · chargement : **c'est
l'écran tout entier**, et sa forme est la question 3 · erreur : BRouter
injoignable (« aucun parcours n'a pu être tracé »), Open-Meteo injoignable,
délai dépassé · succès : E19 · *dégradés : (a) BRouter répond mais aucune
boucle ne tient la distance demandée → E19 en état « aucune boucle trouvée »
avec ce qu'il faudrait changer (durée, direction, départ) ; (b) météo
indisponible → deux options que seul le mainteneur peut trancher : proposer
des boucles sans météo ni tenue, ou ne rien proposer (elles ne sont pas
équivalentes — sans météo, l'outil perd sa question d'origine).*

**E19 Les propositions** — vide : « aucune boucle trouvée », avec des leviers
concrets · chargement : voir E18 · erreur : voir E18 · succès : trois
propositions contrastées, chacune avec sa phrase distinctive · *dégradés :
(a) **deux propositions au lieu de trois**, parce que les candidates ne
diffèrent pas assez — le cas existe déjà et le produit dit pourquoi ; ne
jamais compléter à trois avec une quasi-jumelle, c'est exactement ce que
L5.3 refuse ; (b) une seule proposition ; (c) séance amputée au-delà de 5 %
de la durée prescrite → l'alerte s'affiche, et **seulement** au-delà de ce
seuil, qui est déjà dans la configuration (`elasticite_calme_min`, Q21 a).*

**E20 Détail et emporter** — vide : sans objet · chargement : carte et tracés ·
erreur : GPX introuvable ou illisible — le seul échec qui annule tout le
reste · succès : le GPX est parti dans l'application du compteur · *dégradés :
(a) séance sans bloc — le cas le plus courant chez le mainteneur : le parcours
s'affiche plein, pas en pointillé pâle (Q20 c) ; (b) demi-tours dans le
parcours → le profil d'altitude superpose les blocs, défaut connu et ouvert ;
(c) une part de grands axes à afficher : `primary` seul, pas la catégorie
composite qui multipliait par quatre ce qui inquiète (Q21 c).*

**E21 Profil et réglages** — vide : sans objet · chargement : lecture ·
erreur : par champ · succès : enregistré, et **dire ce que le changement
invalide** — changer de départ habituel ou de vélo ne rend pas les
propositions d'hier fausses, mais il ne faut pas laisser croire qu'elles ont
suivi · *dégradé : clé Intervals devenue invalide → l'écran le signale ici,
c'est là qu'on la remplace.*

**E22 Clés d'accès** — vide : « aucune clé » · chargement : liste · erreur :
création impossible · succès : **la clé n'est montrée qu'une fois**, avec ce
qu'elle ouvre et comment la révoquer · *dégradé : clé jamais utilisée depuis
sa création — à montrer, c'est le seul indice d'une clé égarée.*

**E23 Mes sorties proposées** — vide : « rien encore » · chargement : liste ·
erreur : liste indisponible · succès : la liste · *dégradé : proposition
ancienne — sa météo et sa tenue sont périmées et doivent être marquées comme
telles ; le tracé, lui, reste valable.*

**E24 Compte et données** — vide : sans objet · chargement : préparation de
l'export · erreur : export échoué · succès : fichier d'export ; suppression
confirmée · *dégradé : suppression demandée alors qu'une génération est en
cours — ce qui se passe des données en cours de calcul est à décider.*

---

## 4. Les moments qui décident de tout

Cinq moments. Chacun est un endroit où **l'utilisateur part et ne revient
pas**, et où le remède n'est pas cosmétique.

**M1 — L'attente après la demande d'accès (E2 → E3).**
C'est le seul délai du parcours qui dépend d'un humain, et il est par nature
non borné : le mainteneur modère quand il ouvre sa file. L'invité, lui, vient de
décider d'essayer quelque chose ; c'est le pic de sa motivation, et il le
passe à attendre. **Pourquoi c'est décisif** : un invité qui reçoit son lien
quatre jours plus tard ne se souvient plus de ce qu'on lui avait promis, et
le lien tombe dans une boîte qu'il ne lit pas. Ce qui se joue vraiment ici,
c'est le **contenu de E2** (dire un délai, ou ne rien dire et laisser
imaginer) et la **visibilité de l'ancienneté en E4**. Voir question 6.

**M2 — L'étape FTP (E9).**
C'est la première question du parcours à laquelle un cycliste normal peut ne
pas savoir répondre. Le mainteneur connaît sa FTP au watt près ; un copain qui roule
sans plan structuré peut ne l'avoir jamais mesurée. **Pourquoi c'est
décisif** : ce n'est pas seulement un champ vide, c'est un champ qui
**bloque tout l'aval** — sans cible de puissance, il n'y a ni placement de
blocs, ni Z2 pour l'itinéraire manuel, donc plus de produit. Et c'est le
seul moment où l'invité se dit « en fait, cet outil n'est pas pour moi ».
Voir questions 2 et 11.

**M3 — L'attente de la première génération (E13 → E18 → E19).**
Une génération coûte environ 150 appels décomptés chez Open-Meteo pour une
sortie à 5 candidates (et ~240 à 8 candidates), plus plusieurs appels
BRouter. Ce n'est pas instantané, et c'est la **première fois** que l'invité
voit le produit faire quelque chose. **Pourquoi c'est décisif** : un écran
muet pendant un calcul long est indistinguable d'un écran cassé — il
recharge, il relance, et une relance coûte un second cycle complet d'appels.
Le sprint 8 exige en plus « un coût maîtrisé par utilisateur » : les
rechargements d'impatience sont exactement ce qui le fait déraper. Voir
question 3.

**M4 — Le passage du GPX dans le compteur (E20).**
Tout le produit converge ici. Le mainteneur a fermé Q5 sur ce point précis :
partage système du GPX depuis le mobile, pour toutes les marques, et rien
d'autre. **Pourquoi c'est décisif** : si ce geste échoue — mauvais type MIME,
nom de fichier illisible, navigateur qui ouvre le GPX au lieu de le partager
— l'utilisateur a fait tout le parcours pour rien et n'a aucun contournement
depuis son téléphone. Q22 l'a déjà établi côté bureau : « le téléchargement
du GPX fonctionne, mais depuis le Mac », et ça ne suffisait pas.

**M5 — La première proposition d'un invité qui habite en ville dense (E19).**
Mesuré : dans la ville du mainteneur et à Angers la densité de feux et stops retombe sous
0,40/km à 6 km du centre, à Nantes à 12 km, aux Lilas **jamais** à moins de
15 km — et elle y **remonte** entre 0-5 et 5-10 km. Un invité francilien
recevra donc des blocs qui portent quatre à cinq arrêts. **Pourquoi c'est
décisif** : il n'a aucun moyen de savoir que c'est sa géographie et non
l'outil ; il conclura que l'outil ne marche pas, et il aura raison pour lui.
La réponse technique — le mode circuit, tourner sur un anneau court sans feu
— est identifiée (Q32) mais n'est pas écrite. L'interface ne peut donc
choisir qu'entre le dire et le taire. Voir question 12.

---

## 5. Questions ouvertes

Aucune n'est tranchée ici. Chacune donne les options et ce qui bascule.

**1. L'horizon « sans vent » : 2 jours ou 3 ?**
Le brief dit deux fois « sans vent si plus de 2 jours ». Le produit a mesuré
et retenu **3 jours inclus** : `HORIZON_ORIENTATION_J = 3` dans
`src/ourouler/sortie/vent_demande.py`, sur 2 064 heures dans la ville du mainteneur en référence
ERA5 — la direction tombe dans le bon secteur de ±45° neuf fois sur dix à
1-3 jours (93 %, 92 %, 88 %) et 78 % à 5 jours ; le commentaire du module
tranche explicitement « trois jours inclus, quatre non ».
*Options* : (a) aligner l'interface sur la mesure, 3 jours ; (b) aligner le
code sur le brief, 2 jours, et documenter que c'est un choix de prudence
contre une mesure ; (c) en faire un réglage par utilisateur.
*Ce qui bascule* : le formulaire E16 (à quelle date la question d'orientation
apparaît), l'écran E15 (quelles séances de la semaine portent la promesse de
vent), et une constante mesurée du dépôt. **Si le mainteneur choisit (b), il
contredit une mesure du produit : la doctrine demande alors que la raison
soit écrite** (règle absolue 5).

**2. « capteur pour monter ou elle » — que faut-il lire ?**
La phrase du brief suit « possibilité de se connecter a intervals.icu en
demandant la clé ». Trois lectures plausibles, probablement une dictée :
(a) **« pour montrer où elle est »** — une aide contextuelle à l'étape E12
indiquant où trouver la clé (Intervals → Settings → Developer) ; (b) **« pour
monter [des fichiers] ou elle [la clé] »** — deux voies d'entrée des données
du capteur : téléverser ses fichiers, ou donner la clé ; (c) **« le capteur :
pour monter [sa FTP] ou elle »** — d'où vient la FTP, du capteur ou
d'Intervals.
*Ce qui bascule* : (a) est une ligne d'aide ; (b) est un lot entier — un
chemin d'import de fichiers d'activité par l'interface, en plus de
l'import de séance de E17, avec son cache et son stockage d'objets ; (c)
déplace la question 11 (la FTP comme donnée saisie ou donnée lue).

**3. Que voit l'utilisateur pendant que ça calcule ?**
Une génération coûte ~150 appels décomptés Open-Meteo à 5 candidates (~240 à
8) et plusieurs appels BRouter ; l'hébergé minimal contourne aujourd'hui le
problème en calculant **une fois par nuit**, sans aucune demande à traiter.
*Options* : (a) attente bloquante avec une progression réelle par étape
(séance lue → boucles tracées → météo le long → placement) ; (b) calcul
asynchrone, l'utilisateur quitte l'écran et retrouve le résultat en E23 —
avec ou sans message Brevo (lié à la question 14) ; (c) rester sur la
pré-génération quotidienne, et l'itinéraire manuel n'est alors pas « à la
demande » ; (d) résultat progressif : la météo par direction d'abord, les
tracés ensuite.
*Ce qui bascule* : l'existence d'une file de tâches côté serveur (sprint 7),
la nécessité du cache météo mutualisé (doctrine §10.1 : « au premier sprint
de l'hébergé »), le comportement en cas de rechargement, et le coût par
utilisateur exigé au sprint 8.

**4. L'invité n'a aucun historique : que montre-t-on à la place d'une
estimation calibrée ?**
Chez le mainteneur, la calibration donne une erreur mesurée (4,2 % et 2,4 % de MAE
selon le vélo, sur sorties non vues). Chez l'invité il n'y a rien, et le
sprint 8 dit : « le modèle doit tourner sur des paramètres génériques **et le
dire** ».
*Options* : (a) afficher les mêmes chiffres avec une mention « estimation non
calibrée » ; (b) afficher une fourchette au lieu d'un nombre ; (c) ne pas
afficher de temps ni de vitesse tant que rien n'est calibré, et ne montrer
que la distance et le terrain ; (d) calibrer progressivement dès que des
sorties arrivent par Intervals, avec un état d'avancement visible (« 12
sorties sur les 30 qu'il faudrait »).
*Ce qui bascule* : E19 et E20 en entier — l'axe « la séance tient » des
propositions contrastées **repose sur la simulation**, donc sur la
calibration ; si on retire le temps estimé, on retire aussi une partie de ce
qui distingue les trois propositions. Et le seuil (d) n'existe nulle part :
personne n'a mesuré combien de sorties il faut.

**5. Authentification : clé d'accès, identité déléguée, ou les deux ?**
Le brief dit « pour l'auth si la personne veut elle peut avoir une webkey ».
La doctrine §10.2 dit : OpenID Connect, Google d'abord, Apple ensuite,
**jamais de mot de passe chez nous**, identité interne opaque.
*Options* : (a) identité déléguée pour l'entrée, clé d'accès comme jeton
d'appareil ou d'accès programmatique en plus ; (b) lien à usage unique par
message (Brevo est déjà là pour l'invitation) ; (c) clé d'accès seule, ce qui
dispense de compte développeur Google mais met un secret porteur dans un
signet de téléphone.
*Ce qui bascule* : E5, E6, E22 ; la dépendance à un compte développeur ; et
si le mainteneur choisit (c), **la doctrine §10.2 doit être amendée dans la
même livraison** — c'est la règle du dépôt.

**6. La modération : délai annoncé, refus explicite, expiration du lien ?**
Le brief dit « inscription avec modération par moi ». Il ne dit pas ce que
voit le demandeur.
*Options*, indépendantes les unes des autres : annoncer un délai en E2 ou
non ; envoyer un message de refus ou rester silencieux ; faire expirer le
lien d'invitation (et sous quel délai) ou non ; conserver ou purger les
demandes refusées.
*Ce qui bascule* : le texte de E2 (moment M1), la colonne d'ancienneté de E4,
le chemin de rattrapage de E6, et une obligation RGPD — une demande refusée
conservée est une donnée personnelle conservée sans compte pour la porter.

**7. Ce que l'assistant demande vraiment, et ce que le second vélo devient.**
Le brief demande « nom prénom age poids » et « Vélo (type et poids) (type CLM
gravel Route) ». Deux trous : **l'âge n'a aucun usage dans le dépôt** (le
modèle physique utilise la masse, pas l'âge ; les zones viennent de la FTP,
pas de la fréquence cardiaque maximale) ; et « gravel » n'est pas un usage
connu de la configuration, qui ne connaît que `route | clm`.
*Options* : demander l'âge quand même (et dire pourquoi), le retirer de la V1,
ou le rendre facultatif ; ajouter `gravel` comme usage avec son propre CdA de
départ, ou le traiter comme `route`.
*Ce qui bascule* : E8 et E11, et — pour le gravel — une valeur physique
supplémentaire que personne n'a mesurée. Question jumelle pour plus tard :
quand le second vélo arrivera, **où se choisit-il** — dans l'assistant, dans
E16 à chaque demande, ou par règle attachée à la séance ?

**8. Le fichier de séance : `.FIT`, `.MRC`, `.ZWO` — prescription ou
activité ?**
Aucun des trois n'est lu aujourd'hui **comme une séance à réaliser**. Le FIT
est lu comme un fichier d'**activité** (une sortie déjà faite) ; `.MRC` et
`.ZWO` n'existent nulle part dans le dépôt. La séance structurée vient
exclusivement d'Intervals.
*Options* : (a) un lecteur de prescriptions pour les trois formats, alimentant
le même modèle `Seance` que `depuis_workout_doc` ; (b) commencer par `.ZWO`
et `.MRC` (formats de séance sans ambiguïté) et traiter le `.FIT` déposé
comme une activité, donc comme une donnée d'historique ; (c) accepter le FIT
Workout en plus du FIT d'activité et distinguer les deux à la lecture.
*Ce qui bascule* : E17 en entier, la taille du lot, et le message d'erreur
qu'un utilisateur verra en déposant un FIT de sortie en croyant déposer une
séance.

**9. Une carte par proposition, ou une seule ? (reprise de Q18, sur mobile)**
Q18 est ouverte depuis le 16/09 et la réponse change de nature sur un
téléphone, où il n'y a la place que pour une carte à la fois.
*Options* : (a) une carte plein écran avec un sélecteur des trois
propositions, méthode Strava — sélection en couleur pleine, les autres en
pointillé gris (règle Q20) ; (b) trois cartes empilées, une par proposition ;
(c) une liste de propositions (E19) et une carte au détail (E20), ce qui est
la structure supposée ici.
*Ce qui bascule* : E19 et E20 fusionnent ou restent séparés, et la charge de
la page — trois tracés complets contre un.

**10. Le départ : combien d'adresses, et stockées où ?**
Le brief demande un départ habituel **et** « une adresse de départ
spécifique ». Q3 évoquait « plusieurs départs nommés dans la configuration ».
*Options* : (a) un départ habituel + un champ ponctuel non mémorisé ; (b) une
liste de départs nommés (maison, travail, vacances) ; (c) un départ habituel
+ les trois derniers départs ponctuels, proposés en raccourci.
*Ce qui bascule* : E10, E16, E21 — et la quantité de données personnelles
stockées, donc le périmètre de l'export et de la suppression de E24. Un
départ est une coordonnée de domicile : c'est la donnée la plus sensible du
produit.

**11. La zone 2 de l'itinéraire manuel vient d'où, et la FTP est-elle
obligatoire ?**
Le brief dit « préparation sur la zone 2 de la personne ». Le dépôt a trois
sources possibles : les zones de puissance saisies, `puissance_endurance_pct`
(0,60 de la FTP, médiane mesurée sur les sorties extérieures du mainteneur, Q11),
ou les zones d'Intervals.
*Options* : (a) FTP obligatoire à l'assistant, Z2 dérivée ; (b) FTP
facultative et, sans elle, un itinéraire dimensionné en durée seule avec une
vitesse générique — l'outil rend alors une boucle mais pas une séance ;
(c) proposer une estimation de FTP à partir du poids et d'une auto-évaluation,
ce que **personne n'a mesuré** et que la règle absolue 5 rend coûteux à
affirmer.
*Ce qui bascule* : E9 devient bloquant ou non (moment M2), et la promesse
elle-même — « un parcours » ou « un parcours pour ta séance ».

**12. Dit-on à l'invité que le produit rend moins de service chez lui ?**
Mesuré le 16/09 : distance de dégagement urbain 6 km (ville du mainteneur, Angers), 12 km
(Nantes), jamais à moins de 15 km aux Lilas. Q31 et Q32 le posent comme un
constat produit ; le mode circuit qui serait la réponse n'est pas écrit.
*Options* : (a) mesurer la distance de dégagement à l'adresse saisie dès E10
et l'annoncer (« vos blocs porteront 4 à 5 arrêts ») ; (b) ne rien dire et le
laisser découvrir en E19 ; (c) le dire au moment où ça se voit, c'est-à-dire
sur la proposition elle-même ; (d) le dire au mainteneur en E4, au moment
d'accepter la demande.
*Ce qui bascule* : un calcul supplémentaire dans l'assistant (donc des appels,
donc la question 3), le sens de l'invitation, et la sincérité du produit —
c'est la règle absolue 5 appliquée à ce que l'outil **ne** sait **pas** faire.

**13. La semaine Intervals : quelle fenêtre, et rafraîchie quand ?**
Le connecteur ne sait lire que les événements **d'un jour**
(`ClientIntervals.evenements(jour)`) ; « récupération des séances de la
semaine » demande soit sept appels, soit une plage à ajouter au connecteur.
*Options* : semaine calendaire ou sept jours glissants ; rafraîchissement à
chaque ouverture de E15, une fois par jour, ou sur geste explicite.
*Ce qui bascule* : le nombre d'appels à Intervals par utilisateur et par jour,
l'état vide de E15, et la fraîcheur d'une séance que l'entraîneur vient de
modifier — le cas est réel, les séances du mainteneur sont planifiées par un tiers.

**14. Brevo sert-il seulement à l'invitation ?**
Le brief nomme Brevo pour l'inscription (« mail via Brevo, je filerai une
clé »). Rien n'est dit d'autres messages.
*Options* : (a) invitation seule ; (b) invitation + « votre parcours est
prêt » si la génération devient asynchrone (question 3) ; (c) invitation +
un message la veille d'une séance planifiée.
*Ce qui bascule* : le consentement à recueillir et à révoquer, donc un écran
de préférences dans E21 ou E24 ; et, pour (b), la forme du calcul long.
