# Inventaire du système visuel — le contrat de couverture

Écrit le 20/09/2026, avant toute ligne de `jetons-systeme.css` ou de
`composants-systeme.css` — c'est l'ordre demandé : l'inventaire d'abord, la
couleur ensuite. Il liste ce que l'application utilise réellement (relevé à
la fois à la main, fichier par fichier, et par un balayage mécanique
indépendant) et où chaque besoin trouve sa réponse dans le nouveau système.
Aucun écran n'a été modifié pour produire cet inventaire ni pour le vérifier.

## Périmètre balayé

- `front/src/style.css` (1278 lignes, la source actuelle).
- Les 11 écrans de `front/src/ecrans/*.tsx`.
- Les 12 composants partagés de `front/src/composants/*.tsx`.
- `front/src/App.tsx` (la coquille : onglets, navigation, états de
  chargement globaux) — hors des douze composants nommés dans le brief,
  mais réellement utilisateur de classes de `style.css`.

**98 classes CSS distinctes** sont utilisées par les écrans et les
composants (hors `App.tsx`) ; `App.tsx` en ajoute deux qu'aucun des deux
premiers groupes n'utilise (`onglets`, déjà connue de `style.css` ; et
confirme qu'aucune des deux n'est `marque`, voir plus bas).

## Couverture : 98/98 classes recensées ont une réponse

Chaque classe utilisée par `front/src/ecrans/` ou `front/src/composants/`
trouve son équivalent, **sous le même nom**, dans
`front/directions/composants-systeme.css` — c'est un choix délibéré : le
fichier reprend la structure section par section de `front/src/style.css`
(mêmes commentaires `/* ---------- x ---------- */`), pour qu'une
comparaison ligne à ligne soit directe et pour qu'une éventuelle application
future soit une substitution de fichier plutôt qu'une réécriture des
écrans.

Table de correspondance par section (voir `composants-systeme.css` pour le
détail de chaque règle) :

| Section de `style.css` | Classes concernées | Section de `composants-systeme.css` |
|---|---|---|
| Coquille, en-tête | `coquille`, `app-tete`, `quand`, `a-droite` | § COQUILLE, EN-TÊTE, ONGLETS |
| Barre d'onglets | `onglets` (+ états repos/survol/actif) | idem |
| Blocs | `bloc`, `bloc-tete`, `doux`, `choisi`, `hero`, `liste`, `rang` | § BLOCS |
| Chiffres et titres | `chiffres`, `espace`, `grand`, `secondaire`, `second-chiffre`, `liste-simple`, `estimation-duo` | § CHIFFRES, TITRES, MENTIONS |
| Mentions et encarts | `mention`, `centre`, `forte`, `encart`, `info`, `attention`, `alerte`, `bien` | idem |
| Saisies | `champ`, `aide`, `saisie`, `mono`, `saisie-unite`, `unite` | § SAISIES ET BOUTONS |
| Boutons et liens | `bouton`, `second`, `fantome`, `boutons`, `retour`, `carte-bouton`, `lien` | idem |
| Segments | `segments`, `colle`, `enveloppe` | idem |
| Zones de puissance | `zones`, `zone-l`, `n`, `jauge`, `v`, `endurance` | § ZONES DE PUISSANCE |
| Étapes | `etapes`, `etape`, `pt`, `km`, `nom` | § ÉTAPES DE LA SÉANCE |
| Rangées de réglages | `rangee`, `cle`, `val`, `texte`, `velo-ligne` | § RANGÉES DE RÉGLAGES |
| Jalons et avancement | `barre-avance`, `jalons`, `jalon`, `etat`, `fait`, `cours`, `suite` | § ATTENTE |
| Dépôt de fichier | `depot`, `survole`, `grosse`, `mt-depot`, `fmt` | § DÉPÔT DE FICHIER |
| Carte et vent | `carte`, `haute`, `vent-marqueur`, `vent-fleche`, `vent-face`, `vent-dos`, `vent-travers`, `vent-swatch`, `legende-vent`, `profil-alt` | § CARTE ET VENT |
| Formulaire d'adresse | `champs-adresse`, `liste-candidats` | § FORMULAIRE D'ADRESSE |
| Arbitrage | `arbitrage`, `verdicts`, `verdict-tete`, `etiquette`, `sort-retenue`, `sort-ecartee`, `sort-place`, `matrice`, `matrice-cadre`, `case-diagonale`, `case-sous`, `case-au-dessus`, `phrase-essais`, `avant-contraste`, `invisible` | § ARBITRAGE |
| Temps écoulé | `temps-ecoule` | § TEMPS ÉCOULÉ |
| Divers | `etapes-assistant`, `vide` | § DIVERS |

**Classes composées dynamiquement**, repérées séparément parce qu'aucune
recherche littérale `className="x"` ne les trouve (elles se construisent en
template string ou en expression conditionnelle) — toutes vérifiées comme
couvertes :

- `` `jalon ${etat}` `` (`Attente.tsx:90`), `etat ∈ {fait, cours, suite}`.
- `` `etiquette ${classe}` `` et `classe` seule (`Arbitrage.tsx:169,172`),
  `classe ∈ {sort-retenue, sort-ecartee, sort-place}`.
- `` `zone-l${… ? " endurance" : ""}` `` (`EcranFtp.tsx:125`).
- Les booléens simples `"bloc choisi"`/`"bloc"`, `"depot survole"`/`"depot"`,
  `"carte haute"`/`"carte"`, `"case-au-dessus"`/`"case-sous"`.

## Ce qui a été trouvé et n'est **pas** repris

- **`marque` et `.pile`** existent dans `front/src/style.css` mais
  n'apparaissent dans **aucun** `.tsx` du dépôt (ni les écrans, ni les
  composants, ni `App.tsx`) — vérifié par balayage. Ce sont deux classes
  mortes de l'ancien système. Elles n'ont pas de réponse dans
  `composants-systeme.css` : la règle d'admission (§3 de la doctrine)
  n'ajoute un jeton ou une règle que pour un besoin réel, pas pour couvrir
  une classe qui ne sert plus. Ce constat vaut aussi bien pour signaler que
  `front/src/style.css` pourrait perdre ces deux règles à l'application,
  sans perte fonctionnelle.

## Ce que l'inventaire a révélé au-delà des douze composants nommés

Le brief citait douze composants ; l'inventaire en a trouvé d'autres qui
méritaient une réponse propre parce qu'ils portent une vraie logique
visuelle, pas seulement un style hérité :

- **Le dépôt de fichier** (`.depot`, écran `Importer`) — glisser-déposer un
  FIT/GPX/TCX. Traité au même rang que les douze, avec ses deux états
  (repos, survolé par un fichier glissé).
- **`RetourEnTete`** est bien l'un des douze (`Retour.tsx`), mais sa classe
  (`.retour`) n'apparaissait qu'une fois dans le balayage initial —
  confirmé qu'elle est correctement isolée et documentée.
- **Le vent inconnu** (`.vent-inconnu`, repli défensif de `Carte.tsx` quand
  `relatif` manque côté cœur) n'est décrit nulle part dans
  `direction_visuelle.md`, qui ne parle que de face/dos/travers. Traité
  comme une incertitude, jamais comme une mesure (règle absolue 5) : encre
  très atténuée, pointillé plus fin et plus lâche que le travers connu, pour
  qu'il ne s'y confonde jamais.

## Ce que je n'ai pas su clore complètement

- **Les couleurs de `composants/Carte.tsx` sont fixées en JavaScript**
  (`styleDe()`, `icone()`), pas en CSS : Leaflet dessine en SVG, mais via
  des options JS (`L.PolylineOptions`), pas des classes par défaut pour les
  tracés (les flèches de vent, elles, passent déjà par des classes CSS
  injectées en HTML — celles-là sont entièrement couvertes). J'ai ajouté
  quatre classes prêtes à l'emploi (`.trace-retenue`, `.trace-non-choisie`,
  `.trace-ecartee`, `.trace-depart`) dans `composants-systeme.css`, et
  recommandé que `Carte.tsx` passe un `className` à Leaflet plutôt que de
  dupliquer une couleur en chaîne JS — c'est la voie qui garde une source
  unique de vérité. **Non vérifié dans ce lot** : je n'ai pas de front
  branché sur Leaflet ici pour confirmer que Leaflet applique bien la classe
  au `<path>` SVG rendu ; c'est une recette pour le lot d'application, pas
  un fait vérifié.
- **`ProfilAltitude` reçoit une couleur de bloc en `prop`** (`bloc.couleur`,
  fournie par l'écran parent). Le composant lui-même est couvert (le
  polygone, la ligne, les deux chiffres d'échelle), mais *quelle* teinte
  sémantique choisir pour un bloc de séance sous la courbe d'altitude — la
  couleur d'effort de l'étape ? une teinte neutre ? — n'est pas tranché ici,
  parce que ça dépend de ce que l'écran veut dire à cet endroit précis, une
  décision de lot d'application, pas de système.
- **Le mapping exact `COULEUR_TYPE → jetons d'effort`** (`echauffement`,
  `bloc`, `recuperation`, `calme`) proposé dans `composants-systeme.css`
  (§ ÉTAPES) est une proposition raisonnable, pas une décision : rien dans
  la direction ni dans le code ne dit si le bloc principal doit être en
  `effort-5` (le plus soutenu) ou si l'échelle doit rester plus resserrée.
  À confirmer au lot d'application.
- **`--sv-encre-att` sous le seuil 7,5:1** que le mainteneur avait fixé —
  détaillé dans `docs/ux/doctrine_design_system.md` §7, point 4. Signalé,
  pas corrigé : corriger appartient à `jetons-suisse-vivante.css`, hors du
  périmètre de ce lot.
