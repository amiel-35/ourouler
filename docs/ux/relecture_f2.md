# Relecture du lot F2 — le front React

Relu le 17/09/2026 sur `ux-discovery` à `41afafb`, contre
`docs/ux/maquettes_v1.html`, `docs/ux/cycle_ux_contrat.md`,
`docs/ux/api_contrat.md`, `CLAUDE.md` et `doctrine_architecture.md` §10.

**Comment j'ai relu.** Lecture intégrale de `front/src` et de `front/tests`,
puis l'interface **exercée en vrai** : API du mainteneur sur le port 8011,
front de ce commit servi sur 5181, navigation au téléphone émulé (375 × 812)
et trois générations réelles contre BRouter et Open-Meteo. `tsc --noEmit`
passe, les 42 tests Vitest passent. Ce que j'ai vu à l'écran est marqué
*vérifié en direct* ; le reste est établi par lecture du code et je le dis.

Trois bloquants, douze à corriger.

---

## Bloquants

### B1 — Une séance déposée ne se retire jamais, et s'applique à toutes les recherches suivantes

`front/src/App.tsx:66` déclare `fichierSeance`, `front/src/ecrans/Importer.tsx:41`
le remplit, `front/src/App.tsx:119` le renvoie à chaque appel de `POST /sorties`.
**Rien ne le remet à `null`** — ni le changement de jour, ni le changement
d'onglet, ni une séance Intervals retrouvée, ni la fin de la génération.

*Conséquence pour le cycliste.* Il dépose un `.ZWO` mardi parce qu'Intervals
était muet. Mercredi, Intervals a retrouvé la voix et l'écran « Aujourd'hui »
affiche correctement la séance du jour. Il appuie sur « Chercher le parcours du
jour » : le parcours est calculé **sur les blocs de mardi**. Aucun écran ne dit
qu'un fichier est en usage — ni « Demander », ni le détail du parcours. Il part
rouler avec le mauvais entraînement placé sur la bonne route, et l'interface a
l'air d'accord avec lui.

### B2 — Si `/profil/zones` échoue, l'application reste bloquée sur « Connexion au serveur… », sans un mot

`front/src/App.tsx:73` charge les zones, `front/src/App.tsx:178` interdit tout
affichage tant que `zonesCourantes` est `null`. Or `zones.erreur` **n'est
consulté nulle part** — la recherche sur tout `front/src` ne rend aucune
occurrence, alors que `systeme.erreur` et `profil.erreur` sont bien traités à la
ligne 162 juste au-dessus.

*Conséquence pour le cycliste.* Un écran gris qui dit « Connexion au serveur… »
pour toujours. Pas de code de panne, pas de bouton « Réessayer », pas de barre
d'onglets pour aller ailleurs. C'est exactement l'écran muet que la section
« Quand ça casse » des maquettes interdit, dans sa forme la plus nue : rien ne
distingue un serveur en panne d'une application cassée, et le seul geste
possible est de recharger — ce que l'écran de l'attente, lui, a pris soin de
déconseiller.

*Établi par lecture, pas exercé en direct* : `/profil/zones` n'a pas échoué
pendant la relecture. Le chemin de code, lui, ne laisse aucun doute.

### B3 — Le bandeau « Pas de météo » se déclenche sur une expression régulière appliquée à une phrase française

`front/src/composants/Echec.tsx:180-183` :

```ts
export function meteoManquante(avertissements: string[]): string | null {
  const trouve = avertissements.find((phrase) => /m[ée]t[ée]o/i.test(phrase));
  return trouve ?? null;
}
```

C'est le déclencheur des quatre bandeaux E14 dégradés (`Aujourdhui.tsx:42`,
`Propositions.tsx:112`, `Proposition.tsx:84`, `Boucles.tsx:30`). Il cherche le
mot « météo » dans une prose destinée à un humain.

Trois choses le rendent bloquant plutôt que discutable :

1. `docs/ux/api_contrat.md` pose la règle inverse en toutes lettres : « **Le
   code prime sur le message.** Le message vient du cœur, il est écrit pour un
   humain et **peut être reformulé** ; le code est une valeur du contrat. »
2. `front/README.md` affirme que le front l'applique : « Les échecs sont des
   écrans, **choisis sur le code de la panne et jamais sur son message**. » Trois
   des quatre échecs le font ; celui-ci non, et le README ne le dit pas.
3. La phrase visée, `src/ourouler/sortie/commande.py:349`, n'a aucun test qui
   fige son libellé côté cœur.

*Conséquence pour le cycliste.* Le jour où quelqu'un reformule cet
avertissement — « Open-Meteo injoignable », « prévisions indisponibles » — le
bandeau disparaît en silence. Reste un parcours servi, sans pluie, sans vent,
sans tenue, **et sans la phrase qui dit pourquoi**. C'est le cas que la maquette
E14 traite nommément : « Et la tenue dit pourquoi elle se tait. Un bloc vide
laisserait croire à un bug. » Là, ce serait pire qu'un bloc vide : un écran
d'apparence normale dont les affirmations météo ont disparu sans annonce.

*La correction ne m'a pas l'air d'être dans le front.* L'API rend
`avertissements` comme une liste de chaînes sans code — le front n'a aucun autre
levier. Il faudrait que `POST /sorties` rende un avertissement structuré
(`{code, message}`), ou que la réponse porte un drapeau du genre
`meteo_disponible`. À arbitrer avec F1 ; ce n'est pas une faute d'écriture du
front, c'est un trou du contrat que le front a bouché comme il a pu — sans le
dire.

---

## À corriger

### C1 — Le nombre de feux et stops est déduit alors que le cœur porte déjà l'entier, et par la méthode que le cœur nomme comme le piège

`front/src/api/formats.ts:98-103`, utilisé par `Aujourdhui.tsx:116`,
`Propositions.tsx:66` et `Proposition.tsx:121`.

**Le calcul est juste aujourd'hui, et je l'ai vérifié.**
`boucle/marqueurs.py:60` pose `NOEUDS_ARRET = {"traffic_signals", "stop"}` et
`marqueurs.py:121` somme exactement ces deux natures : le produit
`densite × distance` retrouve donc bien l'entier d'origine, et pas un composite
gonflé de passages piétons. La garde à 0,05 est sérieuse.

Trois raisons de le retirer quand même :

- **L'entier existe déjà dans le cœur, à l'endroit exact où la densité est
  sérialisée.** `sortie/contraste.py:248-249` porte `feux: int | None` et
  `stops: int | None`, sur le même objet `profil` que `sortie/commande.py:1717`
  lit pour écrire `densite_marqueurs_km`. Deux lignes de JSON suffiraient.
- **Le commentaire du cœur désigne précisément ce geste comme celui à ne pas
  faire.** `sortie/contraste.py:244-247` : « Feux et stops du parcours, en
  nombre absolu. Affiché tel quel. **Une densité au kilomètre invitait à
  multiplier** — “1,7 au km, donc 170 sur 100 km”. » Le front fait exactement
  l'inverse de ce que l'auteur du champ avait prévu, et il a raison sur les
  chiffres pour une raison que le commentaire n'anticipait pas.
- **Le chiffre disparaît sans explication au-delà d'environ 100 km.** La densité
  est arrondie à trois décimales (`commande.py:1720`) : l'erreur du produit vaut
  jusqu'à `0,0005 × distance`, soit 0,05 à 100 km — la tolérance exacte. Au-delà,
  le nombre s'efface. *Conséquence pour le cycliste* : celui qui prépare une
  sortie longue perd le seul chiffre qui sépare « la plus calme » des deux
  autres, et rien ne lui dit pourquoi.

### C2 — Des dates ISO brutes lues par le cycliste, et un test qui les verrouille

`front/src/composants/Echec.tsx:112` écrit « Vos séances ne sont plus lues depuis
le `{dernierSucces}` », et `App.tsx:232/337/395` lui passe la sortie de
`derniereLectureSeances()`, une chaîne `AAAA-MM-JJ`. À l'écran :
« **plus lues depuis le 2026-09-12** ».

La maquette E15 fait de cette phrase le point de l'écran : « La date compte plus
que le message. “Plus lues depuis le **12 septembre**” dit à quelqu'un ce qu'il a
manqué. » Le module `api/formats.ts` porte déjà `jourEnLettres()`, qui n'est pas
appelé ici.

Plus gênant : `front/tests/echecs.test.tsx:52` attend
`/plus lues depuis le 2026-09-12/`. Le test ne garde pas l'exigence, il fige
l'écart.

Même défaut, plus discret, à `front/src/ecrans/Reglages.tsx:218`, qui affiche
`historique_depuis` tel quel.

### C3 — La durée annoncée n'est nulle part avant qu'on attende

`front/src/ecrans/Demander.tsx:384-387` : sous le bouton, la ligne dit
« Départ estimé depuis Maison · environ 46,0 km » — et répète en petit
l'estimation déjà affichée en gros vingt centimètres plus haut. *Vérifié en
direct.* La maquette E16 met à cet endroit « **Environ cinq secondes.** », et
l'arbitrage 6 du mainteneur est précisément « en précisant que ça prend X
secondes ».

Le budget est pourtant déjà chargé au démarrage (`App.tsx:71`, `budgetDe` à la
ligne 82) : il suffirait de le passer à l'écran. Aujourd'hui il n'apparaît
qu'une fois l'attente commencée (`Attente.tsx:102`).

*Conséquence pour le cycliste.* Il apprend le prix de l'attente au moment où il
la subit. C'est exactement le rechargement que la maquette cherchait à éviter,
et un rechargement coûte un second cycle complet d'appels.

### C4 — Les cibles tactiles les plus importantes font 15 et 26 pixels

Mesuré en direct dans la page :

| élément | hauteur | où |
|---|---|---|
| « Modifier » — le seul retour vers les réglages depuis un résultat | **15 px** | `Propositions.tsx:127`, `Boucles.tsx:63` |
| les quatre onglets de navigation | **26 px** | `style.css:151-160` |
| « Essayer » sur les écrans d'échec | ~18 px | `Echec.tsx:72`, classe `.lien` |
| « Chercher cette adresse », « Là où il fait sec », « Ajouter ou retirer » | ~18 px | classe `.lien` |

La cause est unique : `style.css:505-515`, `.lien { padding: 0; font-size: 12.5px }`.

*Conséquence pour le cycliste.* Trois minutes avant de partir, debout, une main
sur le guidon, éventuellement des gants longs. Les gestes qu'on rate sont ceux
de la barre d'onglets — la navigation principale — et « Essayer » sur l'écran
« Aucune boucle », qui est le seul chemin de secours du produit. Manquer la
cible sur un écran d'échec, c'est ne pas partir rouler.

### C5 — Les phrases d'honnêteté sont les plus petites et les plus pâles de l'écran

`style.css:235-240` : `.mention` vaut 12 px en `--muet` `#6b7573` sur `#f7f8f7`,
soit un contraste de **4,53:1** — au ras du seuil AA (4,5), loin de l'AAA (7).

C'est la classe qui porte :

- « Facteur de compteur supposé, faute de mesure » (`Demander.tsx:185-191`) — la
  décision 8 ;
- « L'avancement affiché est indicatif » (`Attente.tsx:104-107`) ;
- la phrase de distinction de chaque proposition (`Propositions.tsx:172-176`) —
  ce qui sépare les trois parcours ;
- « Le fichier écrit est celui de la proposition retenue, pas de celle-ci »
  (`Proposition.tsx:256-261`).

Ce sont les seules phrases que la doctrine rend obligatoires, et ce sont les
seules que le soleil efface.

Second point du même ordre : `style.css:347-350`, `.bouton:disabled { opacity: .5 }`.
Vérifié en direct : le bouton « Chercher 3 parcours » désactivé — blanc à 50 %
sur bleu à 50 % — est très en dessous de 3:1 et se lit mal à l'écran, sans
parler du plein jour. Et il est désactivé dans le cas le plus fréquent : aucune
séance ce jour-là. Le cycliste appuie sur un bouton qu'il déchiffre mal, il ne
se passe rien, et l'explication est à six défilements au-dessus
(`Demander.tsx:213-219`).

### C6 — Sur les boucles libres, le titre annonce une distance et la ligne du dessous en annonce une autre

*Vérifié en direct.* `front/src/ecrans/Boucles.tsx:95` affiche `candidate.nom`
tel que le moteur le nomme. À l'écran :

```
Boucle 340° 5.8 km                    RETENUE
24,8 km   128 m D+   52 min
```

« 5.8 km » est le rayon de la boucle demandée au traceur, « 24,8 km » sa longueur
réelle. Deux distances contradictoires à trois centimètres l'une de l'autre, la
première avec un point décimal et la seconde avec une virgule.

*Conséquence pour le cycliste.* Le titre d'une carte est ce qu'on lit en
premier. Celui-ci ment de 19 kilomètres.

L'agent a signalé que cet écran n'a « ni phrase de distinction ni contraste »,
faute de `propositions` dans `POST /boucles` — c'est vrai, et c'est honnête.
Il n'a pas signalé que ce qui tient lieu de titre est un identifiant de moteur.

### C7 — « modèle calibration » s'affiche tel quel

*Vérifié en direct.* `front/src/ecrans/Demander.tsx:190` et
`front/src/composants/EcranFtp.tsx:228` impriment `liees.modele_physique`, la
provenance interne du modèle, sans la traduire. La phrase rendue se termine par
« — modèle **calibration** ». C'est du vocabulaire de serveur dans une phrase
écrite par ailleurs pour un cycliste, et `CLAUDE.md` demande du français dans
l'interface.

### C8 — Un poids de vélo inventé par le front

`front/src/ecrans/Reglages.tsx:345` (`masse_kg: "8"` pour un vélo neuf) et
`front/src/ecrans/Assistant.tsx:38` (`?? 8`). Ni l'un ni l'autre ne vient de
l'API. C'est la seule valeur numérique du front qui ne soit ni une mise en
forme ni la déduction de C1, et `front/README.md` affirme qu'il n'y en a aucune.

*Conséquence pour le cycliste.* Un nouveau venu qui ne corrige pas le champ voit
toutes ses estimations de distance calculées sur un poids que personne n'a
saisi — et l'écran ne le signale pas, contrairement au facteur de compteur qui,
lui, dit qu'il est supposé.

### C9 — Deux façons d'enregistrer dans le même volet, dont une silencieuse

Dans le volet FTP des réglages : la FTP part au `onBlur`
(`front/src/composants/EcranFtp.tsx:97`), tandis que la position dans la zone
attend le bouton « Enregistrer cette allure » (`front/src/ecrans/Reglages.tsx:101-112`).
Rien à l'écran ne dit que l'aperçu des trois valeurs n'est pas enregistré.

*Conséquence pour le cycliste.* Il règle sa puissance visée, voit les trois
valeurs se répondre, ferme le volet — et rien n'a été gardé. Il croit avoir
réglé ses zones.

### C10 — Le rattachement par `localStorage` ne couvre qu'aujourd'hui

`front/src/App.tsx:130` : `if (finale.jour === jour) setMemoire(retenirSortie(...))`.
Générer le parcours de demain depuis « Ma semaine » ne laisse donc aucune trace.
Le bouton reste « Générer le parcours » (`MaSemaine.tsx:65`, alimenté par
`App.tsx:431`), et le calcul — trois à sept secondes contre BRouter et
Open-Meteo — est à refaire.

L'agent a annoncé que « le rattachement d'un parcours à un jour passe par le
`localStorage` ». C'est vrai, mais incomplet : il ne passe que pour un jour, et
ce n'est écrit nulle part. Corollaire mort pour l'instant :
`App.tsx:433` ignore le `jour` que `MaSemaine` lui passe et rouvre toujours la
sortie d'aujourd'hui.

### C11 — Une clé Intervals révoquée sous l'onglet « Aujourd'hui » affiche un écran titré « Cette semaine »

`front/src/composants/Echec.tsx:106-117` rend toujours le même cadre pour le code
`intervals_refuse`, y compris quand l'erreur vient de `seanceDuJour`
(`App.tsx:333`). Le titre et le contexte ne sont pas d'accord.

### C12 — « confiance 69 / 100 » est une réinterprétation du score de géocodage

`front/src/ecrans/Demander.tsx:367` et `front/src/composants/ChoixAdresse.tsx:75`
multiplient `candidat.score` par 100 et l'appellent « confiance ». Mesuré en
direct sur l'API : la BAN rend des scores de pertinence de 0,69, 0,62, 0,60 pour
trois adresses toutes correctes. Présentés comme « confiance 69 / 100 », ils
suggèrent un doute qui n'existe pas. La mise à l'échelle est anodine ; le
renommage est une affirmation que l'API n'a pas faite.

---

## L'organisation de l'information du générateur — jugement séparé

*Vérifié en direct, c'est le point 4 de la consigne.*

**Ce qui est fait, et bien fait.** L'estimation est en haut, avant les réglages
(`Demander.tsx:162-193`), et elle bouge. Passé la durée de 2:00 à 3:30, le bloc
est passé de « 46 km · 2 h · retour vers 11 h 00 » à « 81 km · 3 h 30 · retour
vers 12 h 30 », sans rechargement et sans changer d'écran. Changer l'heure de
départ déplace l'heure de retour. C'est la méthode Strava, appliquée.

**Ce qui n'y est pas.** Quatre des six réglages ne déplacent rien :
l'orientation au vent, le jour, la direction, le départ. Pour trois d'entre eux
c'est une contrainte réelle — la maquette l'assume, le tracé ne se recalcule pas
à chaque frappe — mais **rien à l'écran ne distingue un réglage qui répond d'un
réglage qui ne peut pas répondre**. Le cycliste appuie sur « Rentrer avec », ne
voit rien bouger, et ne peut pas savoir s'il a raté le bouton, si le réglage est
sans effet, ou s'il faut lancer la recherche pour le savoir. Une ligne du genre
« le vent ne change pas l'estimation, il change les boucles cherchées »
refermerait ça.

**Un écart avec la maquette que l'agent n'a pas signalé.** En mode « Endurance
Z2 », la question du vent — l'idée du mainteneur, décision 4 du contrat, « posée
avant la recherche, elle réduit l'espace exploré » — **disparaît**, remplacée par
une rose des vents à huit segments (`Demander.tsx:287-310`). Aucune maquette ne
montre ce contrôle. C'est une conséquence de `POST /boucles` qui prend une
`direction` et non un `vent`, mais le résultat est qu'un cycliste sans séance
planifiée n'a jamais accès à l'idée centrale du mainteneur.

**Un cas à surveiller au même endroit.** `App.tsx:134-137` convertit la durée en
distance avec `moyenne_compteur_kmh ?? 0`, puis `Math.max(1, …)`. Sans vélo
enregistré, l'écran affiche « — » pour l'estimation mais le bouton reste actif
(`Demander.tsx:380` ne le désactive qu'en mode séance) et l'API reçoit une
demande de **boucle d'un kilomètre**. Le cas ne peut pas se produire sur la
configuration du mainteneur, qui a deux vélos ; il se produira au premier invité.

---

## Ce qui tient

Sans arrondir les angles : la charpente est solide, et deux ou trois choses sont
meilleures que ce que le contrat demandait.

**Les trois valeurs liées sont tenues, exactement comme les décisions 7 et 8 les
posent.** Vérifié ligne à ligne. Le front ne calcule rien : chaque frappe part en
`POST /profil/zones/apercu` avec **une** entrée (`EcranFtp.tsx:56-60`), et il
affiche ce qui revient. `facteur_mesure` est dit aux trois endroits qui montrent
la moyenne compteur — `EcranFtp.tsx:197-207`, `Demander.tsx:189`,
`Assistant.tsx:392` — et dans les deux branches à chaque fois, jamais en
omettant la mauvaise. `hors_bande` a son encart (`EcranFtp.tsx:219-225`), et il
explique le cas plutôt que de le corriger. Ce qui part au `PATCH` est
`seance.position_zone` (`Reglages.tsx:106`, `Assistant.tsx:168`), jamais des
watts ; j'ai vérifié côté cœur que `ecran_ftp.rendu` donne bien la même valeur à
`zones.position_zone` et à `valeurs_liees.position_zone` (`seance/ecran_ftp.py:153`
et `:168`), donc ce `PATCH` est correct et non approximatif. **Le seul chiffre du
projet qui ne soit pas une mesure ne s'affiche jamais comme une mesure.**

**Le test de provenance est un vrai test.** `front/tests/provenance.test.tsx`
rend le même écran avec deux jeux de données disjoints et refuse la moindre
valeur commune, jointures et zéro exceptés. C'est ce qui transforme « aucun
écran n'invente de valeur » d'une déclaration en une propriété vérifiable, et
c'est ce test — pas la relecture — qui trouverait le chiffre de maquette oublié.
Les tests de `tests/echecs.test.tsx` sont probants aussi, à l'exception notée en
C2. Aucun test n'appelle le réseau (`tests/serveur.ts` remplace `fetch`).

**Aucune donnée personnelle.** Vérifié indépendamment des tests du dépôt :
balayage de tout `front/` pour des coordonnées françaises, des noms de commune,
des noms de vélo, une FTP, une clé, un identifiant d'athlète — rien. Les
fixtures sont explicitement inventées et disent d'où vient leur point de
référence (`tests/fixtures.ts:1-12`). Règle absolue 1 tenue.

**Le front ne parle qu'à l'API.** Deux `fetch` dans tout `front/src` :
`api/client.ts:73` et `ecrans/Proposition.tsx:58`, ce dernier pour récupérer le
GPX que l'API vient de nommer. Aucun chemin absolu, aucune variable
d'environnement dans le code — `OUROULER_API` ne sert qu'au proxy de
développement. Doctrine §10.2 tenue.

**Les deux endroits où la maquette mentait ont été retirés, pas maquillés.** Le
parcours « généré à 6 h » n'existe pas côté serveur : l'écran montre le dernier
parcours réellement obtenu et **l'heure à laquelle il l'a été**
(`etat/memoire.ts:28`, `Aujourdhui.tsx:97`), et il dit en toutes lettres « Rien
n'est calculé à l'avance » (`Aujourdhui.tsx:148-150`). Le jalon « Le sud-est est
au sec » a sauté, et l'écran d'attente annonce que son avancement est indicatif
(`Attente.tsx:104-107`) au lieu de le laisser croire. Les deux choix sont les
bons, et les deux sont dits au cycliste, pas seulement au relecteur.

**L'attente dit d'où vient son chiffre.** `phraseBudget` (`Attente.tsx:42-51`)
distingue « mesuré sur ce serveur, sur N exécutions » de « valeur par défaut :
ce serveur n'a encore rien mesuré ». Peu de produits font ça, et c'est
exactement la règle absolue 5 appliquée à une barre de progression.

**La barrière de dernier recours existe** (`composants/Barriere.tsx`), et son
commentaire dit honnêtement quel bogue réel l'a motivée.

**Les quatre points laissés ouverts par l'agent sont exacts.** Vérifiés un par
un : l'étape d'identité est absente et l'écran le dit au cycliste plutôt qu'au
lecteur du code (`Assistant.tsx:129-133`), Q36 existe bien dans
`docs/questions_mainteneur.md:1675` ; `POST /boucles` ne rend pas de
propositions ; le rattachement passe par le `localStorage` (avec la réserve C10) ;
le jalon retiré l'est. Rien d'autre n'a été caché — les points ci-dessus sont des
choses qu'il n'a pas vues, pas des choses qu'il a tues.

---

## Prêt à être montré au mainteneur ?

**Oui pour le montrer, non pour le fusionner.**

Montrez-le. C'est du travail sérieux : l'ossature est juste, les deux décisions
qui structuraient tout le lot — la position dans la zone, le facteur mesuré ou
supposé — sont tenues sans approximation, et le lot n'a inventé aucune donnée
sauf une déduction qu'il a lui-même déclarée et un poids de vélo par défaut.
Le mainteneur peut cliquer dedans aujourd'hui et juger le produit, ce qui est le
but.

Ne le fusionnez pas en l'état. B1 fait rouler la mauvaise séance sans le dire —
c'est le seul défaut du lot qui puisse envoyer quelqu'un s'entraîner de travers,
et il se corrige en une ligne. B2 transforme une panne d'API en application
morte, ce que toute la section « Quand ça casse » cherchait à empêcher. B3 n'est
pas une faute du front mais un trou du contrat F1 qu'il faut boucher avant que
quelqu'un reformule une phrase et efface un bandeau.

C4 et C5 méritent d'être arbitrés avant le dogfooding plutôt qu'après : ce sont
les deux seuls points où l'interface échoue à l'endroit exact où le mainteneur a
placé son besoin — un téléphone, dehors, trois minutes avant de partir.

Le reste peut suivre.

---

## Ce qui a été corrigé — 17/09/2026

Les trois bloquants et neuf des douze. Vérifié en cliquant, contre l'API et la
configuration réelles du mainteneur (deux vélos, Intervals et BRouter branchés),
sur téléphone émulé — aucun `PATCH` envoyé, le profil est intact.

**B1.** L'invariant tenu est *une séance déposée ne part qu'avec une recherche
pour son propre jour*, et non « le fichier est remis à `null` » : remettre à
`null` aurait cassé la seconde recherche du même jour, qui est légitime. Q38
dit que le fichier est une prescription et `POST /seances/fichier` prend déjà un
jour — le front ne l'honorait pas. Un bandeau dit maintenant qu'un fichier est
en usage, pour quel jour, et le retire.
*Vérifié en direct* : un `.ZWO` synthétique déposé pour le 17, puis génération
du 19 depuis « Ma semaine » → le bandeau annonce « la recherche en cours porte
sur un autre jour, et ne s'en servira pas », et le parcours rendu fait 2 h 03
pour 57,8 km, soit la séance Intervals du 19, pas les 54 minutes déposées. Le
même fichier déposé pour le 19 donne 59 min sur 28,0 km : il sert pour son jour.

**Un défaut trouvé en cliquant, que la relecture n'avait pas vu.** `Importer`
recevait `demande.jour`, que `chercher` réécrit à chaque génération : après
avoir généré le parcours du 19, « Déposer une séance » depuis l'écran
**d'aujourd'hui** rattachait le fichier au 19. La garde de B1 tenait, mais elle
gardait le mauvais jour — le même défaut déplacé d'un cran. Le jour voyage
maintenant avec la vue, et l'écran de dépôt l'annonce.

**B2.** `zones.erreur` est traité comme `systeme.erreur` et `profil.erreur`.
*Établi par test, pas exercé en direct* : produire une panne de `/profil/zones`
seule contre le serveur réel demanderait de le trafiquer.

**B3.** Corrigé côté API, comme le relecteur le pressentait. `avertissements`
vaut `{code, message}`, avec un catalogue publié (`erreurs.CODES_AVERTISSEMENT`)
et un invariant qui rattache chaque fragment de phrase au module qui l'écrit —
même convention que `PREFIXES_SERVICE`, et même garde-fou : une reformulation
casse un test du dépôt avant d'effacer un bandeau chez le cycliste.
*Vérifié en direct* sur le chemin du géocodage, qui produit un vrai
avertissement codé sans qu'il faille faire tomber un service :
`{"code": "adresse_introuvable", "message": "aucune adresse trouvée pour …"}`.

**C1.** `sortie/commande.rendre_json` sérialise `feux` et `stops`. Un `xfail`
strict de `tests/api/test_api_promesses_maquettes.py` décrivait exactement ce
trou, et disait déjà comment le combler — il est levé.
*Vérifié en direct* : 14 feux + 2 stops = 16 affichés, là où l'ancien produit
donnait 16,005. Le chiffre ne dépend plus de la distance.

**C2, C3, C4, C5, C6, C7, C8, C10, C11** traités — dates en toutes lettres (et
le test qui gravait la forme ISO dit maintenant ce qu'il gravait), durée
annoncée sous le bouton, cibles à 44 px, contraste des phrases d'honnêteté porté
de 4,5:1 à 7,5:1 et bouton désactivé à 6,5:1, titre de boucle libre qui nomme sa
direction, « modèle calibration » traduit, plus de poids de vélo inventé, un
parcours retenu pour son jour et rouvert pour le bon.

**Laissés.** **C9** — les deux façons d'enregistrer dans le volet FTP : la
correction juste est un arbitrage produit (tout au `onBlur`, ou un bouton pour
les deux), et la trancher seul aurait été décider à la place du mainteneur.
**C12** — le score de géocodage renommé « confiance » : un agent travaille en
parallèle sur Q34, dont l'adresse est le périmètre.
Les remarques du jugement séparé sur le générateur (réglages qui ne déplacent
rien, rose des vents en Z2, boucle d'un kilomètre sans vélo enregistré) ne sont
pas traitées non plus : ce sont des questions produit, pas des défauts.
