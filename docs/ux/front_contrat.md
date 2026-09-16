# Cadrage du front — ce qu'on construit, dans quel ordre

Clos le 16/09/2026, à la fin du cycle discovery et UX. Les décisions produit
sont dans `cycle_ux_contrat.md`, les écrans dans `maquettes_v1.html`, ce que
le code sait rendre dans `discovery_donnees.md`.

## Les trois choix de technique du mainteneur

**React**, et non du HTML autonome. J'avais recommandé l'inverse au motif que
ça romprait le « pas de framework » du projet. L'argument était mal posé : ce
principe protège **un mainteneur qui relit le code**, et le mainteneur a dit
qu'il ne le relit pas. Ses mots : « c'est pas toi qui... c'est pas moi qui
code mais toi, tu connais React, tes maquettes sont quasi des artefacts
React ». Les écrans dessinés sont effectivement déjà découpés en composants.

**L'API avant le front**, et non une verticale mince. Argument du mainteneur :
« l'api json ça va, pareil, du code vide ». Il a raison sur le coût — les dix
sous-commandes rendent déjà du JSON, il ne reste que cinq trous nommés.

**Les comptes après**, et c'est lui qui a changé d'avis : « les comptes ça
peut effectivement se brancher après, je te l'accorde ». Le cœur reçoit déjà
un profil en paramètre, donc rien ne sera à réécrire.

## Ce que la doctrine autorise, et ce qu'il faut y corriger

`doctrine_architecture.md:74` dit « pas de Pydantic **tant qu'il n'y a pas
d'API** ». L'API arrive : FastAPI redevient légitime. En revanche
`CLAUDE.md:49` résume en « pas de Pydantic » tout court, plus strict que la
doctrine dont il est le résumé — **à corriger dans la même livraison**.

## Les lots, dans l'ordre

### F0 — Combler les cinq trous de JSON

Aucun ne se contourne, tous sont nommés dans `discovery_donnees.md`.

| trou | ce qu'il bloque | coût |
|---|---|---|
| **La géométrie du tracé** n'est nulle part en JSON — les coordonnées ne vivent que dans le GPX et le HTML Leaflet | toute carte, donc la moitié des écrans | le plus gros |
| **Le géocodage d'une adresse** n'existe pas ; `--adresse-depart` est un nom réservé non livré | l'assistant, le départ ponctuel | dépendance externe à choisir |
| **Le connecteur Intervals ne lit qu'un jour** à la fois | « Ma semaine » | faible |
| **Les zones de puissance sont figées** dans `seance/modele.py`, jamais reliées à `Config` | l'écran de FTP et la décision 7 | moyen |
| **Ni `.ZWO` ni `.MRC` ne sont lus** comme une prescription | l'import de séance | moyen, sans dépendance nouvelle |

La décision 7 se construit ici : ce qu'on stocke est **la position dans la
zone**, jamais la valeur. `puissance_endurance_pct` cesse d'être un réglage.

### F1 — L'API

Elle expose ce que la CLI rend déjà, une route par sous-commande, plus les
écritures du profil. Isolation par propriétaire **dès maintenant** dans la
forme des requêtes, même sans comptes : c'est gratuit à écrire et impossible
à rattraper après.

### F2 — Le front React

Les vingt écrans des maquettes, moins ceux des comptes. Ce qui est à tenir et
que le prototype fixe déjà : la **méthode Strava** sur le générateur (réglages
et résultat qui cohabitent, le résultat bouge quand on touche un réglage), les
**états d'échec dessinés** pour chaque écran, et les **trois valeurs liées**
de l'écran de FTP.

### F3 — Les comptes

Demande d'accès modérée, Brevo, lien à usage unique, passkeys, Postgres,
isolation vérifiée. Décision 1 du contrat. Quand le mainteneur voudra
vraiment inviter quelqu'un.

## Ce qui n'est pas dans ce cadrage

- **La cible de course** (Q33) — V2, et elle est bloquée par `CDA_MIN`.
- **La boucle de vérification** — comparer ce que l'outil annonce à ce qui a
  été roulé, à partir du FIT du retour. Proposée au sprint 6, jamais tranchée.
- **Les quatre questions ouvertes** au pied de `maquettes_v1.html` : l'invité
  sans historique, la géographie qu'on dit ou non, prescription contre
  activité pour les fichiers déposés, et l'âge qui ne sert à rien.
