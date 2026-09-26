# Le parcours d'accueil — l'arbre de décision

Écrit le 19/09/2026, à la demande du mainteneur après un test réel : compte
d'essai ouvert sur le service déployé, atterrissage direct sur l'écran du
jour, qui réclame Intervals. Verdict : « c'est moche pas très graphique, les
écrans sont denses et pas au niveau, les explications sont débiles […] genre
"c'est pas calculé c'est une valeur comme ça 0,807" […] Y a pas l'onboarding
qui demande les informations qu'il n'a pas. »

**Révisé le 19/09/2026, même jour, après relecture adverse et conversation
avec le mainteneur.** La première rédaction a été relue de façon
contradictoire ; quatre points de structure et plusieurs points de contenu se
sont révélés faux ou insuffisamment fondés. Ce document est la version qui en
tient compte — il ne raconte pas l'historique de la relecture, il donne
l'état qui fait foi maintenant. Ce qui a changé, en résumé :

1. **La FTP n'est plus l'ancre, la Z2 l'est.** Une vitesse ou une moyenne
   déclarée par quelqu'un est sa puissance d'endurance, pas un maximum — les
   étages bas ne « donnent » pas une FTP, ils positionnent dans la Z2. La FTP
   devient **facultative** dans le cœur (`Cycliste.ftp_w`).
2. **La question du seuil se pose à tout le monde**, y compris à qui a
   branché Intervals — mais sous la forme « lire, puis confirmer », jamais
   « redemander ce qu'on a déjà ».
3. **Le connecteur Intervals ne lisait pas le profil de l'athlète**, seulement
   ses sorties. C'est corrigé : `GET /api/v1/athlete/{id}` est maintenant
   appelé, et son résultat fait confirmer plutôt que remplacer en silence.
4. **Les questions à choix sont le produit, pas le filet** — l'étage le plus
   fréquenté (le vécu, en choix) est aussi celui qui mérite le plus de soin,
   parce que l'étage le plus précis (Intervals) est le plus rare.
5. **Les tranches de vitesse font 2 km/h**, mesuré.
6. **On ne demande pas une vitesse « à plat, sans vent »** : personne ne roule
   dans ces conditions. On demande la moyenne au compteur sur une sortie
   solo, et un terrain — le facteur compteur fait la conversion.
7. **Le terrain se donne en dénivelé par sortie**, pas en m/km, et la case la
   plus raide change ouvertement ce qu'on en tire.
8. **La question de vitesse se pose par vélo**, après le choix du vélo —
   posée sans préciser lequel, elle mélange les réponses de deux vélos.
9. **L'assistant ne traite qu'un vélo**, le premier ; les autres s'ajoutent
   plus tard dans les réglages.
10. **L'étage cardiaque sort de l'entonnoir.** Sa place au-dessus de la
    question de vitesse n'était soutenue par aucune mesure, et la méthode qui
    le justifierait ne l'est pas non plus. Il n'est pas supprimé du produit —
    il est repoussé à un lot séparé (L8.3), annoncé honnêtement.
11. **Historique importé : un an par défaut**, avec sa raison. « Une dizaine
    de sorties » reste le seuil où un réglage commence à s'apprendre.
12. **On jette le fichier brut, on garde le dérivé** (doctrine §5, réécrite le
    19/09/2026) — ce document ne le redécide pas, il s'y conforme.
13. **Tout ce qui est importé se fait confirmer**, et l'écran dit toujours
    d'où la valeur sort.

**Ce document ne code rien.** Il donne l'arbre complet du premier contact
d'un invité, écran par écran, avec sa raison à chaque embranchement. Les
écrans qu'il implique sont listés en §11 — c'est ce qui sert ensuite à les
produire. Aucune donnée personnelle, aucune adresse ni valeur du mainteneur
n'y figure.

**Une affirmation de la première rédaction était fausse, et ce document ne la
reprend pas** : il n'existe **aucune** « sonde de couverture » écrite le
17/09/2026 qui lirait une archive importée et rendrait sa couverture réelle
(GPS, puissance, cadence, FC…). Aucun fichier, aucun commit ne le confirme.
Le constat de couverture, pour l'étage Intervals comme pour un futur import,
reste **à écrire** (voir §10).

**Sources lues avant d'écrire** : `doctrine_architecture.md` (§5, §10),
`docs/journal/ux/discovery_parcours.md`, `discovery_donnees.md`, `front_contrat.md`,
`cycle_ux_contrat.md`, `api_contrat.md` (le patron d'attente déjà en
service), `front/src/ecrans/Assistant.tsx`, `front/src/composants/
EcranFtp.tsx`, `src/ourouler/physique/litterature.py` et `modele.py`,
`src/ourouler/config.py`, `src/ourouler/connecteurs/intervals.py`, et dans
`docs/journal/questions/questions_mainteneur.md` : [[Q34]] (départ), [[Q36]] (identité),
[[Q46]] (propriétaire), [[Q48]] (import, en entier), [[Q49]]–[[Q52]]
(estimer sans capteur), [[Q60]], [[Q63]], [[Q64]] (les trois tranchées le
19/09/2026, voir §2 et §5).

## 0. Ce qui ne bouge pas

**L'entrée reste par invitation, uniquement** (doctrine §10.2, tranchée le
18/09/2026) : pas de formulaire d'inscription, pas de demande d'accès. Ce
document commence donc **après** l'activation du lien — le compte existe, le
mot de passe est posé (`front/src/ecrans/Entrer.tsx`, déjà livré). Ce qu'il
redécrit, c'est ce qui suit : l'assistant qui construit le profil.

## 1. L'accueil, avant toute question

Contenu de l'écran qui ouvre l'assistant :

> **Bienvenue sur ourouler.**
> Vous dites où et quand vous voulez rouler, ourouler regarde la météo dans
> toutes les directions et vous propose un parcours qui colle à votre
> séance — puis l'envoie sur votre compteur.
>
> Pour ça, on a besoin de vous connaître un peu : votre poids, votre vélo,
> d'où vous partez, et une idée de votre niveau. On part de ce que vous avez
> de plus précis ; si vous n'avez rien, on s'en sort quand même. Quatre
> minutes, et vous pourrez toujours corriger plus tard.

Raison de chaque phrase : la première dit ce que fait l'outil sans
vocabulaire du dépôt ; la deuxième annonce la logique d'entonnoir avant de la
faire vivre, pour que personne ne s'inquiète de ne pas avoir la « bonne »
réponse ; la durée annoncée et « corriger plus tard » désamorcent l'abandon.

## 2. Deux axes, pas une échelle

**C'était le bug rencontré en vrai** (relecture adverse, point A2) : la
première rédaction fondait deux questions indépendantes en une seule
échelle, et ça voulait dire que quelqu'un dont la clé Intervals est branchée
ne se voyait jamais poser « connaissez-vous votre FTP » — il gardait la FTP
générique du serveur, sans jamais le savoir. C'est très exactement le défaut
que le mainteneur a constaté sur son propre compte d'essai.

Les deux axes :

- **D'où viennent vos sorties.** Intervals (compte branché, historique lu et
  recalibré en continu) > export d'une plateforme (pas encore, voir §10) >
  rien (le vécu déclaré, ou la littérature seule). C'est cet axe qui donne
  une **calibration**, continue ou ponctuelle.
- **Connaissez-vous votre seuil (FTP).** Indépendant du premier : on peut
  très bien avoir un compte Intervals rempli par son coach et ne s'être
  jamais soucié de connaître son propre chiffre, ou l'inverse — un test en
  salle sans historique numérique du tout. Cette question se pose **à tout
  le monde**, mais jamais deux fois pour la même donnée : si l'axe précédent
  a déjà trouvé un chiffre exploitable, elle devient une **confirmation**
  plutôt qu'une question ouverte (§5).

L'entonnoir qui suit descend ces deux axes **en même temps**, dans l'ordre où
ils apportent le plus de précision pour le moins d'effort — mais aucun ne
fait taire l'autre.

## 3. L'entonnoir : cinq étages, du plus précis au plus flou

Une seule descente. À chaque étage, une question fermée : la personne a ou
n'a pas ce que l'étage demande. « Non », un échec, ou un constat qui ne
trouve rien d'exploitable font passer à l'étage suivant, immédiatement, sans
écran d'impasse.

| Étage | Ce qu'on demande | Ce qu'on en tire | Ce qu'on perd en descendant d'un cran |
|---|---|---|---|
| **T1 — Compte intervals.icu** | « Avez-vous un compte intervals.icu ? » puis, une fois la clé posée, la **lecture du profil de l'athlète** (§4) | Si le profil porte une FTP : elle est **proposée, à confirmer** — la seule voie vers une vraie calibration continue | Pas de calibration continue, pas de séances planifiées lues automatiquement |
| **T2 — Export Strava ou Garmin** | « Pouvez-vous nous transmettre un export de vos sorties ? » | **Rien pour l'instant** — ce chemin existe dans l'arbre et se nomme franchement « pas encore » (§10, lot L8.1) | Pas de modèle de « routes qui vous ressemblent », pas de niveau dérivé de sorties réelles |
| **T3 — Une valeur que vous connaissez** | « Connaissez-vous votre puissance seuil (FTP), en watts ? » — ou, si T1 en a déjà trouvé une, l'écran de confirmation du §4 | Un chiffre exact, auto-déclaré ou confirmé — « la valeur déclarée est le jugement de la personne sur elle-même » ([[Q52]]) | Pas de FTP directe : l'estimation reposera sur le vécu |
| **T4 — Le vécu, en choix** | La question de vitesse au compteur, par vélo, croisée avec le terrain (§5.2) | Un repère personnel, même approximatif — la seule question dont [[Q52]] a mesuré qu'elle améliore l'estimation en dernier recours | Aucun repère personnel |
| **T5 — Littérature par type de vélo** | *(rien à demander — le fond du tunnel)* | Un chiffre plausible à partir du seul poids et du type de vélo (§5.3), jamais rien | — c'est le filet, il ne peut pas échouer |

**L'étage cardiaque n'est plus dans cet entonnoir** (§7). Ce n'est pas un
oubli : c'est une conséquence mesurée de [[Q63]], voir cette section pour le
détail et pour ce qui disparaît avec lui (l'âge).

## 4. T1 : Intervals lit, puis fait confirmer — jamais ne remplace en silence

**Le constat, vérifié sur un vrai compte le 19/09/2026** ([[Q64]]) :
`GET /api/v1/athlete/{id}` d'Intervals.icu rend, pour qui a rempli son
profil, l'essentiel de ce que cet entonnoir cherche à établir : FTP vélo,
FCmax, LTHR, zones de puissance et cardiaques, poids, FC de repos, date de
naissance. **`src/ourouler/connecteurs/intervals.py` ne l'appelait jamais** —
il lit `activities`, `gear`, `events` et le fichier d'une activité, jamais le
réglage. C'est exactement ce qui explique le défaut constaté en vrai : un
compte branché sur Intervals gardait la FTP générique du serveur, parce que
personne n'allait la lire là où elle vivait déjà.

**Ce que ça change pour l'écran.** Une fois la clé posée et acceptée :

1. Le profil de l'athlète est lu (un appel de plus, synchrone — voir §6).
2. Si le profil porte une FTP vélo (et, si présents, un poids et une FC de
   repos), l'écran les montre et **fait confirmer**, jamais ne les pose en
   silence :

   > On a trouvé dans votre profil Intervals : FTP 235 W, poids 90,7 kg.
   > C'est toujours d'actualité ? ○ Oui ○ Je corrige

   La personne garde le dernier mot — « je corrige » ouvre un champ, pré-
   rempli avec la valeur trouvée, pour qu'elle n'ait qu'à changer le chiffre
   fautif plutôt que de tout retaper.
3. Si le profil ne porte **aucune** FTP exploitable, l'écran ne prétend rien
   avoir trouvé : il descend directement à T3, posé comme une question
   ouverte.

**Ce que cet écran ne fait pas** : il ne lit ni la FCmax ni les zones
cardiaques pour en tirer une décision — l'étage cardiaque est hors de
l'entonnoir (§7), et une valeur qu'on ne va pas utiliser ne mérite pas une
ligne de confirmation de plus.

**D'où sort la valeur, toujours dit.** Chaque valeur confirmée porte sa
source à l'écran (« trouvée dans votre profil Intervals ») — sans quoi
personne ne peut repérer qu'on lui montre, par exemple, les zones d'un autre
sport que le vélo si son compte en porte plusieurs.

## 5. Les questions

### 5.1 Le socle — avant l'entonnoir, quel que soit l'étage où l'on s'arrête

**L'ordre du socle est un ordre humain, pas une dépendance de calcul**
(relecture adverse, point A4) : rien ne se calcule avant le récapitulatif, et
la première rédaction faisait comme si l'ordre des questions imposait un
ordre de calcul. Il ne l'impose pas. L'ordre retenu :

| # | On demande | Formulation | Choix | Place |
|---|---|---|---|---|
| AC2 | Identité | « Comment vous appelez-vous ? » (prénom, nom) | champs libres | **En premier** — décision du mainteneur (« nom prénom obligatoire car c'est la base », [[Q36]]), et la seule question dont personne ne peut ignorer la réponse |
| AC5 | Départ habituel | (déjà écrit, `FormulaireAdresse`) | adresse en champs séparés + carte de confirmation, ou position du téléphone | **Juste après** — obligatoire, non reportable, et sans rapport avec l'entonnoir |
| — | *(l'entonnoir, T1 à T5, commence ici)* | | | |
| AC3 | Poids du cycliste | « Votre poids » | champ numérique, kg | **Juste avant la conversion** qui en a besoin (T1-confirmation, T3, T4) — jamais posé avant que quelque chose en dépende |
| AC4 | Vélo | « Avec quoi roulez-vous ? » — type (Route / Chrono), poids du vélo | deux boutons pour le type, champ numérique **facultatif** | Même place — le poids du vélo est facultatif (`MASSE_VELO_DEFAUT_KG = 9.0` sert de défaut, dit à l'écran) |

**Pourquoi le poids et le vélo bougent, et pas l'identité ni le départ.**
Poids et vélo n'ont de sens que rapportés à un calcul physique — ils
entrent dans la conversion vitesse ↔ puissance dès T1 (confirmation d'une
FTP Intervals, qui a quand même besoin du poids pour situer une position
dans la zone) et systématiquement à T3/T4. Les poser plus tôt les isolerait
d'une phrase qui explique pourquoi on les demande ; les poser juste avant
l'usage permet cette phrase.

**L'assistant ne traite qu'un vélo, le premier.** Les autres s'ajoutent plus
tard, dans Profil et réglages — `discovery_parcours.md` §2.2 l'avait déjà
tranché.

### 5.2 T4 — le vécu, en choix

C'est l'étage le plus fréquenté de tout l'entonnoir — le compte Intervals
rempli et exploitable est, par construction, le cas le plus rare — et c'est
pour ça qu'il porte le plus de soin, pas le moins (point 4 de l'introduction).
Il se pose **par vélo**, juste après que le vélo courant a été choisi (AC4) :
poser la question sans préciser lequel mélange les réponses de deux vélos —
c'est très exactement ce qui est arrivé en interrogeant le mainteneur sans
lui dire pour quel vélo répondre : 25 et 27 km/h, un écart de 10 W entre ses
deux vélos par la mauvaise méthode, 1,6 W par la bonne.

**Ce n'est pas une vitesse « à plat, sans vent ».** Personne ne roule dans
ces conditions, et la réponse serait fausse de bonne foi — ce n'est pas ce
que quelqu'un sait dire de lui-même. Ce qu'on demande est la **moyenne au
compteur sur une sortie solo**, la même chose qu'on lit sur l'écran du vélo
en rentrant, plus un repère de terrain :

| Formulation exacte | Choix de réponse | Ce qu'elle permet d'estimer |
|---|---|---|
| « Sur vos sorties en solo, votre moyenne au compteur tourne autour de quelle vitesse ? » | Moins de 20 km/h · 20 à 22 · 22 à 24 · 24 à 26 · 26 à 28 · 28 à 30 · Plus de 30 · Je ne sais pas trop | La moyenne au compteur, `vitesse_compteur_kmh` |
| « Et sur ce genre de sortie, ça grimpe comment ? » | ○ Plat — moins de 250 m sur 50 km ○ Vallonné — 250 à 600 m ○ Ça grimpe — 600 à 1000 m ○ Montagne — plus de 1000 m | Le dénivelé de référence à appliquer à la conversion (§6) |

**Les tranches de vitesse font 2 km/h, mesuré** ([[Q60]], sur la calibration
réelle du mainteneur, RCR 63 sorties, BMC 26, autour de 25 km/h) :

| largeur de tranche | erreur depuis le milieu |
|---|---|
| 3 km/h | ± 13 W |
| 2 km/h | ± 9 W |

Le plancher de bruit de la méthode est 15 W ([[Q51]]) : des tranches de 3
ajoutent autant d'erreur que la méthode en contient déjà, des tranches de 2
le ramènent nettement en dessous.

**Pourquoi la moyenne au compteur, et pas la vitesse à plat.** La vitesse à
plat sans vent est une abstraction du modèle physique, pas une expérience —
personne ne sait répondre « à quelle vitesse je roule quand il n'y a ni côte
ni vent », parce que ça n'arrive jamais sur une vraie sortie. La moyenne au
compteur, elle, se lit sur l'écran en rentrant : c'est une vraie question, et
c'est le facteur compteur — mesuré s'il existe, ou dérivé du terrain déclaré
sinon — qui fait ensuite la conversion vers ce dont le modèle a besoin.

**« Je ne sais pas trop » descend à T5, sans friction**, sur les deux
questions : pas de vitesse connue, ou pas de terrain à décrire, retombent
tous les deux sur le filet de littérature.

### 5.3 T5 — littérature seule, le fond du tunnel

Inchangé dans son principe (aucune mesure ne le remet en cause) : un chiffre
plausible à partir du seul poids du cycliste et du type de vélo. C'est le
**seul étage nouveau côté cœur** — jusqu'ici, `physique/litterature.py`
donnait des valeurs aérodynamiques (CdA, Crr), jamais une puissance seuil.
Ce document ne prétend pas que le chiffre qu'il propose est mesuré : c'est
une **convention** du même ordre que celles déjà assumées dans
`litterature.py` (« pas une mesure du cycliste qui les reçoit »), posée par
manque d'alternative plutôt que par confiance, et à réviser dès qu'une
mesure existe — voir [[Q65]] en §12, sur le modèle de [[Q57]] déjà ouverte
pour les jeux aérodynamiques.

## 6. Le terrain change ce qu'on en tire, ou le dit

**La dernière case doit changer ce qu'on en tire, ou dire honnêtement qu'on
estime mal** — les deux, en fait, ici. La conversion de la vitesse compteur
en position dans la zone passe par `physique.modele.facteur_compteur_defaut`,
qui accepte déjà un paramètre de dénivelé de référence
(`denivele_m_par_km`) — un levier qui existait dans le cœur sans qu'aucun
écran ne s'en serve. Le terrain déclaré choisit ce paramètre au lieu de
toujours utiliser le même défaut :

| Terrain déclaré | Dénivelé retenu | Statut |
|---|---|---|
| Plat | 3 m/km | convention, non mesurée |
| Vallonné | 10 m/km | convention déjà en place dans le cœur (`DENIVELE_REFERENCE_M_PAR_KM`) |
| Ça grimpe | 18 m/km | convention, non mesurée |
| Montagne | 30 m/km | convention, non mesurée — **et la tranche est ouverte** (« plus de 1000 m » n'a pas de plafond) |

**Ce que ça ne prétend pas.** Aucun de ces quatre chiffres, hors celui déjà
en place, n'est mesuré : rien dans le dépôt n'établit qu'une sortie
« vallonnée » grimpe *exactement* 10 m/km plutôt que 8 ou 13, et la case
« Montagne » recouvre aussi bien 1 100 m que 3 000 m sur 50 km. C'est pour
ça que la phrase de confiance du récapitulatif (§9) doit, pour cette
dernière case spécifiquement, dire l'estimation moins sûre plutôt que de la
présenter avec la même assurance que les trois autres — **c'est la partie
« dire honnêtement » de la phrase du mainteneur**, en plus de la partie
« changer ce qu'on en tire ».

## 7. L'étage cardiaque, sorti de l'entonnoir ([[Q63]])

**Ce qui a été essayé, et pourquoi ça ne marche pas.** En relisant l'arbre,
le mainteneur a proposé d'appliquer l'entonnoir *à l'intérieur* de l'étage
cardiaque (FCmax connue, sinon `220 − âge`), puis, devant la mesure
contre-intuitive de [[Q51]] (`220 − âge` fait *mieux* que la FCmax observée,
11,5 contre 17,9 W), la réserve cardiaque — qui corrigerait en principe
exactement ce décalage. **Elle ne le corrige pas** : sur les données
mesurées du mainteneur, la Z2 réelle reste sous la convention dans les deux
systèmes, et l'écart **s'aggrave** en passant à la réserve (3 points en
dessous devient 10). Le problème n'est pas le repère du cœur au repos, c'est
le rapport entre l'effort mesuré et la convention elle-même.

**Ce qu'il faut en retenir** : rien ne soutient de placer cet étage
au-dessus de la question de vitesse, et rien ne soutient la méthode qui le
justifierait. Il **sort de l'entonnoir** plutôt que de continuer à y occuper
une place non gagnée. Il n'est pas abandonné : c'est un lot séparé (L8.3,
§10), annoncé honnêtement comme « pas encore » plutôt que construit sur une
base qui ne tient pas.

**Ce qui disparaît avec lui : l'âge.** La méthode mesurée pour dériver une
Z2 depuis la FC demande l'âge (pour `220 − âge`) ; sans cet étage dans
l'entonnoir, il n'y a plus de raison de le demander. [[Q39]] avait déjà
tranché son retrait pour la même absence d'usage ; rien ne le fait revenir.

## 8. Le temps que ça prend : ce qui est synchrone, et ce qui ne l'est pas

Le service a déjà un patron pour l'attente : `sortie` reste **sur la
requête**, avec un budget annoncé qui dit s'il est mesuré ou par défaut
(`api_contrat.md`, décision 6 du cycle UX). Ce patron convient à tout ce que
cet arbre demande **aujourd'hui**, parce que rien de ce qui est construit
maintenant ne dépasse l'échelle de la seconde :

- **Le branchement de la clé Intervals** (T1) — un aller-retour HTTP, déjà
  écrit.
- **La lecture du profil de l'athlète** (T1, §4) — un second appel, du même
  ordre de grandeur.
- **La confirmation, la question de FTP, la question de vitesse et de
  terrain** (T3, T4) — un `PATCH /profil` ou un aperçu, comme le reste de
  l'assistant existant.

**Ce qui ne l'est pas, et que ce document ne construit pas** : la
synchronisation complète de l'historique Intervals (`inventaire
--synchroniser`, une commande de ligne de commande aujourd'hui) et l'import
d'un export Strava/Garmin (T2, lot L8.1). Les deux sont hors du périmètre de
ce lot, et l'écran de T2 le dit en toutes lettres plutôt que de laisser
croire à une fonctionnalité qui n'existe pas (§10).

## 9. Le récapitulatif : une phrase de confiance par étage atteint

**Proposition, reprise sans changement de fond de la première rédaction.**
Pendant l'usage quotidien (page du jour, propositions, détail d'une sortie),
les chiffres s'affichent **sans** la mention technique. Le principe se
respecte à deux endroits, chacun une seule fois :

1. **Le récapitulatif** porte une phrase qui nomme l'étage atteint :
   « estimation confirmée depuis votre profil Intervals » (T1) ·
   « à partir de la FTP que vous avez donnée » (T3) ·
   « à partir de ce que vous nous avez dit de vos sorties » (T4, terrain
   Plat/Vallonné/Ça grimpe) · « à partir de ce que vous nous avez dit —
   en montagne, cette estimation est moins fiable qu'ailleurs » (T4, terrain
   Montagne — la partie « dire honnêtement » du §6) · « générique, à partir
   de votre poids et de votre vélo seuls » (T5). La même phrase dit ce que
   monter d'un cran apporterait.
2. **Profil et réglages** garde le détail pour qui veut creuser, derrière un
   geste explicite, comme le fait déjà `EcranFtp.tsx`.

**Une exception ne bouge pas** : quand la valeur conditionne une décision
risquée (alerte « hors de votre zone », dépassement de 5 % d'une séance), le
niveau de confiance redevient visible immédiatement.

## 10. Ce qui existe déjà, ce qui n'existe pas, et ce que ça coûte

| Brique | État |
|---|---|
| Conversion vitesse ↔ puissance, stockage en position dans la zone | **Écrite.** `POST /profil/zones/apercu`, `EcranFtp.tsx` |
| Valeurs aérodynamiques de littérature par type de vélo | **Écrites.** `physique/litterature.py` ([[Q57]] encore ouverte sur le choix entre deux jeux d'une même famille) |
| FTP facultative dans le cœur (`Cycliste.ftp_w`) | **N'existe pas avant ce lot.** `config.py` l'exige aujourd'hui (50–1000 W) |
| Un chiffre de FTP plausible à partir du seul poids + type de vélo (T5) | **N'existe pas.** Nouveau dans `litterature.py` ou `ecran_ftp.py` ; convention non mesurée, [[Q65]] |
| Lecture du profil athlète Intervals (FTP, poids…) | **N'existe pas.** `connecteurs/intervals.py` ne lit ni FTP ni zones ni poids |
| Écran de confirmation « on a trouvé… c'est toujours d'actualité ? » | **N'existe pas.** |
| Conversion vitesse compteur + terrain → position (T4) | **N'existe pas comme écran.** Le levier physique (`denivele_m_par_km`) existe déjà dans `physique/modele.facteur_compteur_defaut` |
| Présentation de la question de vitesse en choix, par vélo | **N'existe pas.** `EcranFtp.tsx` est un champ numérique libre aujourd'hui |
| Question de terrain, en choix | **N'existe pas.** |
| Import Strava/Garmin par lien (T2) | **N'existe pas** (L8.1). Coût détaillé dans [[Q48]] : route serveur, liste blanche hôte + préfixe de chemin, décompression, sandbox de fetch hors des secrets de l'API, état persistant de suivi, traitement asynchrone de durée non garantie. Un constat de couverture reste **à écrire** — aucune « sonde » n'existe déjà, contrairement à ce qu'une version antérieure de ce document affirmait |
| Zone 2 déduite de la FC (L8.3) | **N'existe pas, et sort de l'entonnoir de ce lot** (§7). Méthode mesurée ([[Q49]]–[[Q51]]), place non soutenue par la mesure ([[Q63]]) |
| Un compte neuf atterrit dans l'assistant, pas sur l'écran du jour | **N'existe pas avant ce lot.** Défaut constaté en vrai le 19/09/2026 : un compte sans profil rempli tombait sur « Aujourd'hui », qui réclame Intervals et échoue |

## 11. Les écrans que l'arbre implique

| Écran | Statut | Contenu |
|---|---|---|
| AC1 Bienvenue | nouveau, remplace l'écran actuel | §1 |
| AC2, AC5 Identité, départ | existants, en tête du socle | §5.1 |
| AC3, AC4 Poids, vélo | existants, déplacés juste avant l'entonnoir | §5.1 |
| T1 « avez-vous un compte Intervals ? » | nouveau, question fermée | §3 |
| AC6-1 Clé Intervals | inchangé | §3 |
| Confirmation du profil Intervals | nouveau | §4 |
| T2 « pouvez-vous exporter ? » | nouveau, question fermée, répond honnêtement « pas encore » | §3, §10 |
| T3 « connaissez-vous votre FTP ? » | nouveau, réutilise le champ existant | §3 |
| T4 vitesse au compteur + terrain, par vélo | nouveaux composants (QCM) | §5.2 |
| T5 littérature seule | silencieux, pas d'écran propre | §5.3 |
| Récapitulatif | modifié, phrase de confiance par étage, terrain « Montagne » signalé moins fiable | §9 |

## 12. Questions posées au mainteneur

Ajoutées à `docs/journal/questions/questions_mainteneur.md` :

- **[[Q65]]** — le chiffre de FTP par défaut du filet de littérature (T5,
  §5.3) : quel W/kg, et faut-il le distinguer route/chrono comme les jeux
  aérodynamiques le sont déjà ? Posé sur le même modèle que [[Q57]], jamais
  tranché ici faute de mesure.

Restent ouvertes depuis la première rédaction, inchangées par cette
révision : [[Q61]] (taille de la fenêtre récente lue par le constat T1),
[[Q62]] (un export en plusieurs archives).
