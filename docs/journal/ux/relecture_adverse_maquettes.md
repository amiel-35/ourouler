# Relecture adverse des maquettes v1

Relecture du 16/09/2026 de `docs/journal/ux/maquettes_v1.html` (commit `9fe7431`),
par un agent qui n'a pas participé à leur conception. Les numéros de ligne
renvoient à ce fichier. Chaque constat dit s'il est **vérifié** (dans le
code, la config ou les documents du cycle, chemin à l'appui) ou **supposé**.
Aucune correction n'est proposée : le travail ici est de trouver ce qui ne
tient pas, pas de le réparer.

Grille de gravité :

- **Bloquant** — le contrat du cycle (`cycle_ux_contrat.md`, « Comment les
  maquettes seront jugées ») n'est pas rempli, ou la maquette affirme
  quelque chose de faux sur le produit.
- **Grave** — une décision qui appartient au mainteneur est prise en
  silence, ou un parcours ne peut pas être suivi de bout en bout.
- **Moyen** — un chiffre ou un libellé contredit le code ; une incohérence
  interne ; un manque qui coûtera au sprint de construction.
- **Bénin** — à corriger, sans conséquence de fond.

Décompte : 5 bloquants, 9 graves, 10 moyens, 5 bénins.

---

## Bloquant

### B1. Aucun état d'échec n'est dessiné — sur seize cadres, zéro

Le contrat exige que « chaque écran a ses états dégradés dessinés, pas
seulement son état heureux : pas de séance, météo indisponible, aucune
boucle trouvée, une seule proposition au lieu de trois ». **Vérifié** en
lisant les seize cadres : aucun d'eux n'est un état d'erreur. Les seuls
éléments non nominaux sont un avertissement d'ancienneté dans une file par
ailleurs heureuse (E4, l. 318), une ligne « sans le vent » (E15, l. 538) et
un encart d'information (E20, l. 722).

Ce qui manque, écran par écran, en reprenant `discovery_parcours.md` §3.1 :

- E1 : champ invalide, adresse déjà titulaire d'un compte.
- E5 : compte inconnu, e-mail jamais arrivé, **utilisateur qui n'a pas
  encore de clé d'accès** — le bouton « Entrer avec ma clé d'accès » (l. 334)
  est le premier de l'écran et rien ne dit ce qu'il fait pour quelqu'un qui
  n'en a pas posé.
- E9 : « je ne connais pas ma FTP » — les onglets « L'estimer » et « Depuis
  Intervals » (l. 361) existent comme libellés, aucun n'est dessiné. C'est
  le moment décisif M2, et son état de rupture n'a pas d'écran.
- E10 : adresse introuvable ; **adresse en zone dense** — c'est le moment
  décisif M5, et la maquette ne dessine que son contraire (voir B4).
- E12 : clé refusée (HTTP 401), le seul cas d'erreur dont le message
  existe déjà dans le code (`connecteurs/intervals.py:206`).
- E14 : **rien de prévu aujourd'hui**, calcul de la nuit échoué, page
  d'hier, Intervals non branché. Le premier est l'état par défaut de
  l'invité (voir B2).
- E15 : semaine vide, Intervals en panne ou clé révoquée.
- E16 : durée hors bornes, date hors fenêtre, adresse ponctuelle
  introuvable.
- E17 : format non reconnu, fichier tronqué, structure pauvre.
- E18 : BRouter injoignable, Open-Meteo injoignable, délai dépassé.
- E19 : aucune boucle, **deux propositions** (le cas existe dans le code et
  la note l. 695 le décrit sans le dessiner), une seule, séance amputée au-delà
  de 5 %.
- E20 : partage système impossible (navigateur de bureau, ou mobile sans
  API de partage), GPX illisible.
- E21 : clé Intervals devenue invalide.

Conséquence : le sprint de construction devra inventer une vingtaine
d'écrans que le cycle UX avait précisément pour mission de dessiner, et les
inventera sans le regard du mainteneur. Le pied de page (l. 787) annonce
« quatre décisions bloquent la suite » : la cinquième, c'est celle-ci, et
elle n'est pas nommée.

### B2. E14 n'est pas l'écran de l'invité — c'est celui du mainteneur

Le titre du document est « Où rouler, pour quelqu'un d'autre que soi »
(l. 226). Or E14 (l. 483-519) montre une séance venue d'Intervals et un
parcours « Généré à 6:00 » par le calcul nocturne. La note l. 514 le dit :
« c'est ce que fait déjà la version en ligne ». **Vérifié** : cette version
en ligne est la page du mainteneur, mono-utilisateur, calculée pour lui.

L'invité par défaut, selon `discovery_parcours.md` §2.4, **n'a pas branché
Intervals** — son E14 est « rien de prévu → demander un parcours », et ce
parcours « doit tenir seul ». Il n'est pas dessiné. L'écran d'arrivée de la
personne pour qui le document est écrit n'existe donc pas dans le document.

Ajout : E17 s'intitule « Sans Intervals » (l. 552), mais le seul écran d'où
l'on peut y arriver (E14) suppose Intervals. Le parcours sans Intervals n'a
ni point d'entrée ni écran d'accueil.

### B3. Des pastilles vertes posées sur des données qui n'existent pas

Le contrat dit qu'une pastille `existe` signifie « la donnée sort déjà
d'une commande, en JSON » (légende, l. 777). Confrontation à
`discovery_donnees.md` et au code :

**E21, l. 770 — « tous les champs existent en config ».** Faux sur trois
lignes de l'écran. « Camille Ruiz » (l. 744) : `Cycliste` n'a ni nom ni
prénom (`discovery_donnees.md` §3, « Aucun champ »). « Clés d'accès · 1 ·
iPhone » (l. 757) : rien n'existe, la pastille de E5 (l. 348) dit elle-même
« WebAuthn à écrire ». « intervals.icu · Branché » (l. 756) : seul un booléen
`renseigne` existe, pas « la clé marche ». **Vérifié.**

**E16, l. 616 — « modèle physique calibré ».** La calibration est une
propriété de la configuration du mainteneur (162 sorties), pas du produit.
Pour Camille, qui a zéro sortie, il n'y a aucun modèle calibré — c'est la
question ouverte 2 du contrat, que le pied de page (l. 790) reconnaît.
Poser la pastille verte sur l'écran de l'invitée contredit ce pied de page.
La note l. 613 va plus loin : « l'estimation, elle, est vraie ». Pour
l'invitée, elle est générique. **Vérifié** (`discovery_parcours.md` §1.3).

**E14, l. 517 — « tous les chiffres existent ».** Trois ne sortent pas du
JSON. « Généré à 6:00 » : l'horodatage n'existe que dans la page HTML
(`sortie/carte.py:881`), pas dans `rendre_json`
(`sortie/commande.py:1553-1640`, aucun champ d'horodatage — **vérifié**).
« 10 feux » : le JSON expose `densite_marqueurs_km`, où les marqueurs sont
feux **et** stops, cédez-le-passage, mini-giratoires, passages piétons
(`boucle/marqueurs.py:47`) ; le compte de feux seuls existe dans un profil
interne (`sortie/contraste.py:321`) mais **n'est pas dans le JSON**
(**vérifié**, aucune clé `"feux"` dans `rendre_json`). Et la note l. 515
(« jamais 1,7 au kilomètre ») contredit un choix mesuré du code : le pas de
contraste est une densité par kilomètre, calibrée sur 143 boucles
(`contraste.py:153-164`).

**E10, l. 418 — « mesure de densité faite ».** La mesure est une étude
ponctuelle sur quatre villes (`docs/journal/questions/questions_mainteneur.md:1479-1484`),
pas une fonction appelable sur une adresse. **Vérifié** : aucune occurrence
de « dégagement » dans `src/`. Pacé n'a jamais été mesurée : « à 4 km de chez
vous, la densité tombe à 0,3 » (l. 410) est un chiffre inventé présenté
comme une mesure. Et la note l. 416 dit « aux Lilas, jamais avant 30 km »
alors que la source dit **15 km** (`questions_mainteneur.md:1482`,
`discovery_parcours.md:68`).

**E20, l. 732 — « motif du placement affiché ».** Les motifs que produit le
code sont des reproches : « x km en zone bâtie », « montée de … », « pente
irrégulière », « descente de … » (`seance/terrain.py:883-919`). La maquette
affiche des raisons positives par bloc — « plat, 1 seul carrefour » (l. 717)
se déduit des champs `pente_moyenne`/`carrefours` ; **« vent de dos »
(l. 719) n'existe pas par bloc** : le vent n'est pas un champ de
`emplacements` (`discovery_donnees.md` §2), il n'intervient qu'à
l'intérieur de la simulation (`seance/placement.py:1287`). **Vérifié.**

**E12, l. 473 — « connecteur Intervals existe ».** Vrai, mais l'écran omet
un champ obligatoire : le connecteur refuse de s'instancier sans
`athlete_id` (`connecteurs/intervals.py:61-63`). L'écran tel que dessiné ne
peut pas se connecter. **Vérifié.**

### B4. Le moment décisif M5 est dessiné à l'envers

`discovery_parcours.md` §4 décrit M5 : l'invité francilien reçoit des blocs
qui portent quatre à cinq arrêts, « il conclura que l'outil ne marche pas,
et il aura raison pour lui ». La seule réponse de la maquette est l'encart
vert de E10 (l. 410) : « Bonne nouvelle pour vous ». On a dessiné le cas où
le produit marche, pour illustrer le moment où il ne marche pas. La note
l. 416 en discute honnêtement, mais discuter n'est pas dessiner : l'écran de
la personne pour qui c'est un problème n'existe pas.

### B5. « Environ une minute » — un chiffre que personne n'a mesuré

E16, l. 607 : « Environ une minute ». `discovery_donnees.md` §4 est formel :
« aucune mesure de temps d'horloge n'est consignée nulle part », la seule
borne explicite est un timeout BRouter de 120 s **par appel**, et il y a
deux passes BRouter par candidate (`sortie/commande.py:1-45`). La note
l. 615 justifie pourquoi annoncer un ordre de grandeur ; elle ne dit pas d'où
vient celui-ci. C'est la règle absolue 5 appliquée à la maquette elle-même,
et c'est le chiffre que l'utilisateur retiendra. **Vérifié** (absence de
mesure).

---

## Grave

### G1. Décisions déguisées — sept questions ouvertes tranchées par le dessin

Pour chacune, ce que la maquette montre comme acquis et la question qu'elle
préempte (numérotation de `discovery_parcours.md` §5) :

- **Q6, expiration du lien.** E2, l. 290 : « Le lien reste valable sept
  jours ». Q6 laisse ouvert « faire expirer le lien (et sous quel délai) ».
  La note de E4 (l. 323) construit ensuite dessus : « le seuil de sept jours
  … c'est la durée de validité du lien annoncée en E2 ». Une décision non
  prise sert de fondation à un second écran. Les pastilles de E2 (l. 301)
  n'en disent rien.
- **Q14, Brevo au-delà de l'invitation.** E18, l. 636 : « On vous prévient
  quand c'est prêt ». C'est un message transactionnel supplémentaire, donc
  un consentement à recueillir et à révoquer (Q14, `discovery_parcours.md`
  l. 653-660). La pastille « notification à écrire » (l. 645) présente une
  décision RGPD comme un lot technique. Le pied de page (l. 789) assume le
  pari de l'asynchrone (Q3) ; il ne mentionne pas Q14.
- **Q11, estimation de FTP.** L'onglet « L'estimer » (l. 361) est dessiné
  à égalité avec « Je la connais ». Q11 (c) dit de cette estimation : « ce
  que personne n'a mesuré et que la règle absolue 5 rend coûteux à
  affirmer ». L'onglet n'est pas une réponse possible, c'est une promesse.
- **Q11 encore, d'où vient la Z2.** E9 (l. 374) et E16 (l. 588) disent
  « à 160 W en Z2 ». **Vérifié** : la cible d'endurance du code est
  `puissance_endurance_pct = 0,60` (`config.py:173`), soit **147 W** pour
  245 W de FTP. 160 W, c'est 65 %, un chiffre qui ne vient de nulle part. La
  pastille « Z2 depuis les zones » (l. 616) suppose que la Z2 est la zone de
  la table (137-184 W), alors que le code utilise un pourcentage distinct.
  La maquette répond deux fois à Q11, différemment, sans dire qu'elle
  répond.
- **Q7, l'âge et E8.** Le brief demande « nom, prénom, âge, poids ». L'écran
  E8 n'est pas dessiné, et le pied de page (l. 794) affirme qu'il « ne
  posait aucune question nouvelle ». Faux : Q7 porte exactement sur lui
  (« l'âge n'a aucun usage dans le dépôt »). Le brief est ignoré et la
  question effacée d'un même geste.
- **Q10, combien d'adresses.** E16, l. 605 : « Partir d'ailleurs cette
  fois » — option (a) de Q10, un champ ponctuel non mémorisé, choisie sans le
  dire. Q10 rappelle que c'est « la donnée la plus sensible du produit ».
- **Q9, une carte ou trois.** E19 dessine une carte unique à trois tracés
  et l'attribue au mainteneur (l. 691). C'est ce que fait la page existante
  (`sortie/carte.py:52-57`), donc cohérent avec le code ; mais Q9 reste
  formellement ouverte dans la discovery et n'est pas signalée fermée.

### G2. L'assistant met le point d'abandon en deuxième position, et se contredit sur ce qui bloque

`discovery_parcours.md` §2.2 propose l'ordre « du plus sûr au plus fragile :
on demande d'abord ce que tout le monde sait, on garde pour la fin ce qui
peut faire abandonner ». La maquette annonce un autre principe (l. 356 :
« du bloquant vers le reportable ») et place la FTP — le moment décisif M2,
« le seul moment où l'invité se dit : cet outil n'est pas pour moi » — en
étape 2 sur 5, avant l'adresse et le vélo, deux champs que tout cycliste sait
remplir.

Elle se contredit ensuite : E9, l. 380, « ce champ bloque tout l'aval » ;
E10, l. 415, « le seul champ strictement bloquant du parcours ». Les deux
écrans réclament le même titre. Le principe d'ordre annoncé n'est donc pas
appliqué non plus.

### G3. « Depuis Intervals » à l'étape 2, Intervals à l'étape 5

E9, l. 361, propose de lire la FTP depuis Intervals. Intervals se branche à
l'étape 5 (l. 448). Dans l'ordre dessiné, cet onglet est inatteignable. Et
**vérifié** : le connecteur ne lit pas la FTP du compte
(`connecteurs/intervals.py`, aucune occurrence de `ftp`) ; `seance/intervals.py`
ne fait que convertir des `%ftp` avec la FTP de la config. L'onglet n'a ni
place dans le parcours ni code derrière, et aucune pastille ne le dit.

### G4. Aucune navigation, nulle part

Sur seize cadres, aucun menu, aucune barre d'onglets, aucun bouton de retour.
`discovery_parcours.md` §3 dit que E21 s'atteint « par le menu » et que E15,
E16, E17 partent de E14. Depuis E14 tel que dessiné (l. 509), les seules
sorties sont « Autre parcours » et « Ouvrir ». Un invité ne peut atteindre ni
ses réglages, ni sa semaine, ni l'import. Le contrat demande qu'« un
cycliste qui n'a pas écrit le code comprend chaque écran » ; ici il ne peut
pas passer de l'un à l'autre.

### G5. Le fil E16 → E19 → E20 raconte trois séances différentes

E16 demande « Endurance Z2 », 2 h (l. 594-596). E19 confirme « 2 h · Z2 »
(l. 657). E20 (l. 715-720) montre une séance à **deux blocs de 15 min à
220 W** — ni l'endurance continue de E16 (aucun bloc), ni le fichier de E17
(quatre blocs). L'écran de détail, « où tout le produit converge » (l. 728),
détaille une séance que personne n'a demandée. Et l'onglet « Une séance » de
E16 (l. 596), qui aurait pu la porter, ne mène nulle part de dessiné.

### G6. E16 ne sait pas choisir une date

Le brief demande « itinéraire manuel avec durée et date ». Le contrôle
« Quand » (l. 598) offre trois pastilles : aujourd'hui, demain, vendredi.
`discovery_parcours.md` §2.3 décrit le cas « samedi, sortie du club préparée
le mercredi — E15 → E16 pour la date » : impossible ici. E15 (l. 537) offre
« Générer le parcours » pour dimanche, un jour que E16 ne peut pas
sélectionner. De plus « Départ à 9 h 40 » (l. 599) est affiché, pas
saisissable, alors qu'il commande l'heure de retour et la réponse au vent
(`--heure-depart` existe en CLI, `discovery_donnees.md` §1).

### G7. E17 court-circuite la demande

« Chercher un parcours » (l. 566) part directement du fichier. Quel jour ?
Quelle heure ? D'où ? Quelle orientation au vent ? Tout ce que E16 demande
est sauté. Soit E17 doit enchaîner sur E16 (non dessiné), soit il génère
sans ces réponses, ce qui contredit la règle « la question du vent est posée
avant la recherche » (l. 614).

### G8. Une séance de home-trainer reçoit une boucle de 17 km

E14 et E15 (l. 485, 525) : « HT reprise — très facile ». HT, en vocabulaire
d'entraînement, c'est home-trainer : une séance en intérieur. La maquette
lui génère un parcours extérieur, sous « Parcours prêt ». `discovery_parcours.md`
§3.1 prévoit exactement l'inverse pour E15 : « séance non vélo … la ligne
existe et dit ce qui manque ». **Supposé** : je n'ai pas vérifié si ce
libellé est inventé ou recopié du plan réel du mainteneur (je n'ai pas lu son
compte Intervals). S'il est recopié, c'est une donnée personnelle de plus
dans le dépôt, même bénigne.

### G9. Le compte des écrans est faux, et les absents ne sont pas ceux annoncés

L. 794 : « Dix-huit écrans dessinés sur vingt-quatre. Les six absents —
activation du lien, identité, récapitulatif, sorties passées, compte et
données ». **Vérifié** en comptant : seize cadres, couvrant dix-sept
identifiants (E21 et E22 fusionnés, l. 765). Absents : E3, E6, E7, E8, E13,
E23, E24 — **sept**, dont le pied de page n'en nomme que cinq. Les deux
oubliés : E7 (l'annonce des cinq étapes) et surtout **E3, le message
d'invitation**, que la discovery appelle « le seul objet qui relie les deux
moitiés du parcours » (§2.1). Quant à E22, compté comme dessiné : son
contenu (créer, nommer, révoquer, « la clé n'est montrée qu'une fois ») se
réduit à une ligne « 1 · iPhone » (l. 757).

---

## Moyen

### M1. Les pastilles manquantes (à écrire non signalé)

- E14, l. 509 : « Autre parcours » — que fait-il ? S'il relance, c'est
  ~150 appels météo ; s'il montre les deux autres propositions déjà
  calculées, il faut le dire. Rien ne le dit.
- E16 : la conversion durée → distance n'existe pas pour une demande
  manuelle (`boucle --distance` prend une distance ; `discovery_donnees.md`
  §3 : « logique à extraire »). Pas de pastille.
- E18 : les cinq jalons supposent que le cœur émet une progression.
  **Vérifié** : aucun mécanisme de rappel ou d'avancement dans
  `sortie/commande.py` ni `boucle/commande.py`. Pas de pastille.
- E20 : « Envoyer vers mon compteur » suppose un GPX servi par HTTP et
  l'API de partage du navigateur ; le JSON ne porte qu'un chemin disque
  (`sortie/commande.py:1585`). E20 n'a **aucune** pastille orange, alors
  que E19 en pose une pour la même carte (« géométrie du tracé en JSON »,
  l. 696). Deux écrans, même carte, deux verdicts.
- E12, l. 461 : « Elle reste chiffrée chez nous » — le chiffrement au repos
  est un engagement de la doctrine §10.1, rien n'existe.

### M2. Les jalons de E18 décrivent un pipeline qui n'est pas celui du code

L. 630-634 : relevé sur 8 directions → « le sud-est est au sec » → boucles →
terrain → retenus. **Vérifié** : `sortie` ne fait aucune couronne de
directions (aucune occurrence de `couronne` dans `sortie/commande.py`) ; son
ordre est séance → vent **en un point** → boucles → placement → météo le
long des tracés → replacement → coûts, météo, tenue → tri → contraste
(docstring, l. 1-45). Le premier jalon est la commande `meteo`, pas la
commande `sortie`. Un utilisateur qui lit « le sud-est est au sec » croira
que le produit a choisi une direction pour la pluie ; il ne l'a pas fait.

### M3. Les zones de E9 ont des trous, et ce sont celles du mainteneur

L. 368-372 : Z1 < 135, Z2 137-184, Z3 186-221, Z4 223-257, Z5 260-294. Les
bornes laissent 136, 185, 222, 258 et 259 W sans zone. **Vérifié** : c'est
un artefact fidèle de la table du code, en pourcentages entiers (0,55 / 0,56,
`seance/modele.py:52-60`). Un utilisateur qui roule à 185 W demandera dans
quelle zone il est. Le code a sept zones, la maquette cinq. Et la table est
documentée comme « calée sur les zoneTimes observés du compte du
mainteneur » : ce que l'écran appelle « Vos zones » est la découpe d'Amiel,
appliquée à tout le monde.

### M4. « 27 km/h à 160 W » habille une constante en résultat physique

L. 374 et 591. **Vérifié** : `vitesse_moyenne_kmh = 27` est une constante de
configuration commentée « en attendant le modèle physique »
(`config.py:244`, `config.example.toml:50`). Elle ne dérive pas de 160 W ni
d'aucun modèle. La maquette présente un bouche-trou comme une prédiction.

### M5. E4 n'a pas l'état que la discovery jugeait le plus important

`discovery_parcours.md` §3.1, E3 et E4 : « côté Amiel, E4 doit montrer
qu'une invitation a été envoyée et qu'elle n'a pas été consommée — sinon
personne ne sait que le parcours est cassé ». La file (l. 309-317) ne montre
que des demandes non traitées. L'unique signal d'un lien perdu n'existe pas.
Par ailleurs, les « sept jours » de E4 (ancienneté d'une demande, l. 318) et
ceux de E2 (validité d'un lien envoyé, l. 290) sont deux durées différentes
que la note l. 323 confond.

### M6. La tenue, l'un des quatre résultats du produit, n'a pas d'écran

Le produit rend séance, parcours, météo, **tenue**. La tenue existe en JSON
(`tenue{base, a_emporter, a_enlever, motifs}`) et le mainteneur a tranché
Q3 sur sa lecture (« le départ est ce qui compte »). Dans la maquette, elle
n'est qu'un onglet non dessiné (E20, l. 704) et absente de E14, l'écran
« avant de s'habiller » (l. 513). Le profil d'altitude prévu par la
discovery pour E20 est absent aussi.

### M7. E14 régresse par rapport à la page existante sans l'expliquer

La page hébergée actuelle montre deux ou trois propositions superposées
(`sortie/carte.py:795-818`) ; la discovery la qualifie de « maquette du
futur front » qu'elle « prolonge, ne jette pas ». E14 (l. 492-508) n'en
montre qu'une. C'est peut-être un bon choix pour un écran « trois secondes
bras tendu » ; il n'est ni justifié ni signalé comme un écart.

### M8. Les colonnes qui changent d'une carte à l'autre rendent E19 incomparable

L. 676, 681, 686 : la première montre feux et nationales, la deuxième la
pluie, la troisième le temps. La note l. 693 y voit une économie de lecture.
La conséquence non dite : impossible de comparer la pluie ou les feux entre
les trois — la « plus calme » a-t-elle pris la pluie ? La phrase de
distinction fait déjà le travail de hiérarchie ; retirer les colonnes retire
la vérification. **Supposé** : je ne sais pas ce qu'un cycliste préfère ;
je constate que la comparaison est empêchée.

### M9. Les affirmations « la recherche est nette » n'ont pas de source dans le dépôt

L. 298 (position dans la file), l. 345 (« la seule recommandation qui fasse
consensus dans les données d'adoption »), l. 381 (TrainerRoad, Zwift,
intervals.icu), l. 347 et 468 (citations). Le contrat renvoie à
`discovery_benchmark.md`. **Vérifié** : ce fichier n'existe pas sur la
branche (`ls docs/ux/`). Ces affirmations portent des choix d'écran et
personne ne peut les relire. La règle 5 vaut pour l'UX aussi.

### M10. Deux signaux de E2 ne se composent pas

« 3 devant vous » (l. 286) et « une fois par semaine » (l. 288). Si le
mainteneur traite toute sa file en une fois, la position n'apporte rien ;
si elle apporte quelque chose, la cadence n'est pas hebdomadaire. Les deux
chiffres ensemble laissent imaginer un délai que ni l'un ni l'autre ne
donne.

---

## Bénin

### b1. « Clé d'accès » désigne deux objets

E5 (l. 334-335) : une passkey (visage, empreinte). E22 selon la discovery :
« créer, nommer, révoquer une clé d'accès (“webkey”) », un secret porteur.
Le brief parlait de webkey ; le contrat a choisi la passkey. La maquette
garde le nom de l'un pour désigner l'autre, et E21 (« 1 · iPhone ») n'aide
pas à trancher lequel.

### b2. Le prénom du modérateur dans l'interface publique

E1, l. 261 et 269 ; E2, l. 288 : « Amiel ouvre la porte ». Pas une fuite
(il est déjà dans `CLAUDE.md`), mais un choix produit pour un service que la
doctrine §10 veut multi-utilisateur : le texte suppose qu'il n'y aura jamais
d'autre modérateur.

### b3. Un bouton mort dans l'assistant

E11, l. 436 : « Ajouter un second vélo plus tard », un contrôle qui ne fait
rien en V1, sur un écran d'installation.

### b4. « Chercher trois parcours » promet ce que le code ne garantit pas

E16, l. 606. Le code rend « deux ou trois » (`sortie/commande.py`, docstring
point 8), parfois une (« la seule candidate », l. 976). Le bouton fixe un
nombre que l'écran suivant devra démentir.

### b5. Le JSON ne sait pas rendre « 3 séances planifiées cette semaine »

E12, l. 462. Le contrôle de clé, s'il est écrit, le sera avec le connecteur
mono-jour. La pastille de E15 le signale (l. 546), celle de E12 non.

---

## Ce qui tient

Peu de choses, mais elles sont solides, et elles sont vérifiées.

- **La règle absolue 1 est respectée.** Comparaison oui/non de chaque valeur
  de la maquette à la configuration réelle du mainteneur (adresse, code
  postal, FTP 245, masse 72, vélo 8,4 kg, nom du vélo, clé Intervals) :
  aucune correspondance. « Pacé » n'apparaît nulle part ailleurs dans le
  dépôt. La clé de E12 n'est ni dans le dépôt ni dans la config.
- **Les trois arbitrages du contrat qui se voient sont appliqués
  littéralement** : E12 montre le chemin vers la clé, en trois étapes ; E15
  retire le vent à quatre jours avec des chiffres exacts (88 % et 67 h,
  vérifiés dans `cycle_ux_contrat.md` et `meteo/openmeteo.py:262`) ; E5 ne
  cache pas le lien derrière la passkey.
- **Quatre chiffres de E19 sont ceux du code** : « plus de 25 % des mêmes
  routes » (`SEUIL_RECOUVREMENT = 0.25`, `contraste.py:209`), la phrase de
  distinction (`contraste.py:483`), « % de nationales » (label du code,
  `commande.py:1245`), l'orientation au vent par proposition.
- **Trois idées d'écran valent d'être gardées quel que soit le sort du
  reste** : les zones affichées comme contrôle de la FTP (E9, l. 382) ; des
  jalons nommés plutôt qu'un rond qui tourne (E18, l. 641) — même si les
  jalons dessinés sont faux ; « Envoyer vers mon compteur » avant
  « Télécharger » (E20), conforme à Q5.
- **Le dispositif des pastilles est bon**, et il est honnête sur E17
  (aucun format lu), E10 (géocodage absent), E11 (gravel), E15 (connecteur
  mono-jour). Le problème n'est pas l'outil, c'est qu'il est mal appliqué
  sur cinq écrans (B3).
- **Le pied de page dit la vérité sur quatre questions** — il en manque au
  moins autant (B1, G1).

## Ce que je n'ai pas pu juger

- **Le rendu.** Je n'ai pas ouvert le fichier dans un navigateur : densité
  réelle d'un cadre de 375 px, lisibilité « bras tendu en plein soleil »,
  cibles tactiles, débordements, mode sombre. Le jugement « Apple, sobre »
  se fait à l'œil, pas au HTML. Je note seulement que E14 empile date, nom
  de séance, durée, trois étapes, carte, quatre chiffres, une ligne météo et
  deux boutons — neuf unités d'information pour un écran qui se veut lisible
  en trois secondes.
- **Les affirmations sur les autres produits** (TrainerRoad, Zwift, Strava,
  passkeys) : le benchmark cité n'est pas sur la branche.
- **Si « HT reprise » et « 4 × 15 SST » sont des séances réelles** du
  mainteneur : je n'ai pas lu son compte Intervals.
- **Le format d'une clé intervals.icu** : je n'ai pas vérifié que la chaîne
  de E12 en respecte la forme ; seulement qu'elle n'est ni dans le dépôt ni
  dans la config.
- **La durée réelle d'une génération** : personne ne l'a mesurée, moi non
  plus ; B5 dit seulement qu'elle est affirmée sans mesure.
- **Le geste de partage sur un vrai téléphone** (M4) : rien dans un HTML
  statique ne permet de savoir si un navigateur mobile partagera un GPX vers
  Garmin Connect.
