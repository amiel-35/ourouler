# Le front

L'interface que le cycliste utilise. Elle **ne parle qu'à l'API**
(`src/ourouler/api/`), jamais au cœur Python : doctrine §10.2.

Les écrans viennent de `docs/journal/ux/maquettes_v1.html`, les arbitrages de
`docs/journal/ux/cycle_ux_contrat.md`, le contrat des réponses de
`docs/journal/ux/api_contrat.md`.

## Lancer

```sh
# dans un terminal : l'API, sur la configuration de la ligne de commande
uv sync --all-extras
uv run ourouler api --port 8000        # 8000 : ce que le proxy ci-dessous attend

# dans un autre : le front, qui lui renvoie /api
cd front
npm install
npm run dev            # http://localhost:5180, /api → http://127.0.0.1:8000
```

**Le port 8000 est celui des deux côtés**, et c'est la seule chose à ne pas
rater : le proxy de développement cherche l'API sur `http://127.0.0.1:8000`
(`vite.config.ts`), `ourouler api` écoute sur 8000 par défaut. Servir l'API
ailleurs sans le dire au proxy donne l'écran « Le serveur ne répond pas » —
correct, mais évitable ; `OUROULER_API` change la cible.

`OUROULER_API` est le **seul** réglage d'environnement du front, et il ne sert
qu'au serveur de développement : le code, lui, n'appelle que des chemins
relatifs sous `/api/v1`, si bien qu'en production l'API et le front se servent
depuis la même origine.

**Il y a deux fabriques d'API, et une seule sert un profil.** `ourouler api`
lance `ourouler.api.application:application`, qui lit le fichier de
configuration. `creer_application` est la fabrique de bibliothèque : elle ne
lit rien, et une application construite ainsi répond `profil_absent` (503) sur
toutes les routes de données tant que personne ne lui a donné de profil. Un
serveur qui démarre normalement et refuse tout est presque toujours ce
cas-là ; le détail est dans `docs/journal/ux/api_contrat.md`, « Les deux fabriques ».

```sh
npm run verifier       # types + tests
npm run build          # dist/
```

## Ce qu'il faut savoir avant d'y toucher

**Aucun écran ne fabrique une valeur.** Ce que l'API ne rend pas n'existe pas
dans `src/api/types.ts`, et ce qui peut valoir `null` le vaut : le cœur
distingue « zéro » de « on ne sait pas », l'interface aussi. Trois tests
gardent cette règle (`tests/provenance.test.tsx`), dont un qui rend le même
écran avec deux jeux de données disjoints et refuse la moindre valeur commune.

**Le front ne calcule rien.** Les nombres absolus de feux et stops viennent
de l'API (`feux`, `stops`), le front n'en fait qu'une somme ; le poids d'un
vélo neuf est un champ vide qui demande une réponse, jamais un défaut qui se
ferait passer pour une saisie.

**Les trois valeurs liées** (`src/composants/EcranFtp.tsx`) se recalculent par
l'API, jamais côté front — le modèle physique reste dans le cœur. Ce qui est
enregistré est la **position dans la zone**, jamais les watts : la FTP peut
changer sans que rien d'autre ne bouge. La moyenne compteur dit toujours si
son facteur est mesuré ou supposé.

**Le départ se saisit en quatre champs** (`src/composants/FormulaireAdresse.tsx`),
pas en une ligne de texte : numéro, voie, code postal, commune, tous
obligatoires : une adresse sans
commune rend cinq candidats dans cinq communes distinctes, séparés de deux
millièmes de score, et le premier est arbitraire. Le point géocodé se
**confirme à l'œil sur la carte** avant d'être retenu. « Utiliser ma position »
est proposé **en plus**, jamais à la place : le navigateur ne la donne que sur
HTTPS, après une autorisation qui peut être refusée — et un refus n'est pas une
erreur, c'est un choix. Faute de géocodage inverse, la position relevée reste
une coordonnée affichée en chiffres.

**Les échecs sont des écrans** (`src/composants/Echec.tsx`), choisis sur le
**code** de la panne et jamais sur son message. `Barriere` attrape en dernier
recours ce qu'aucun écran n'avait prévu : une page blanche est le pire des
états d'échec.

**« Le serveur ne répond pas » n'est pas « le serveur a refusé ».** Trois codes sont fabriqués par `src/api/client.ts`, pas reçus :
`serveur_injoignable`, `delai_depasse` et `reponse_illisible` — ils ont leur
écran, qui dit que la demande n'est jamais arrivée et que rien n'est perdu.
Le critère qui les reconnaît est le contrat, jamais le statut : l'API promet
du JSON pour toute réponse, pannes comprises, donc une réponse qui n'en porte
pas ne vient pas d'elle. C'est ce qui donne un vrai écran au cas le plus banal :
front lancé sans API derrière, proxy qui rend un `500 text/plain` vide.

**Les avertissements aussi portent un code** (`{code, message}`,
`api/erreurs.CODES_AVERTISSEMENT`) : le contrat déclare les phrases
reformulables, donc le bandeau « Pas de météo » se décide sur le code.
**Aucun écran ne lit une phrase pour en déduire un état.**

**Un fichier de séance déposé vaut pour un jour**, celui pour lequel il a été
déposé : c'est une séance à faire, pas un réglage. Il ne part
jamais avec la recherche d'un autre jour, un bandeau dit qu'il est en usage, et
il se retire. `tests/seance_deposee.test.tsx` garde l'invariant.

**L'attente est semi-synchrone** (`src/composants/Attente.tsx`). Le budget
annoncé vient de `/systeme/budgets` et dit d'où il vient ; l'avancement des
jalons est interpolé contre ce budget, et l'écran **le dit** — le cœur ne rend
pas compte de ses étapes, et inventer un résultat intermédiaire aurait été
inventer une mesure.

## Organisation

| dossier | quoi |
|---|---|
| `src/api/` | la frontière : types du contrat, client, mises en forme |
| `src/composants/` | ce qui sert à plusieurs écrans — carte, profil, zones, échecs |
| `src/ecrans/` | un fichier par écran des maquettes |
| `src/etat/` | chargement des ressources, mémoire du navigateur |
| `tests/` | aucun réseau : `tests/serveur.ts` remplace `fetch` |

**Un composant fait 300 lignes au plus** (`tests/taille_composants.test.ts`).
Un écran qui dépasse se découpe dans un sous-dossier à son nom, en minuscules
(`ecrans/reglages/` pour `Reglages.tsx`, `composants/carte/` pour
`Carte.tsx`) : un volet, une étape, une section par fichier, et les fonctions
pures à part dans un `.ts`. Le fichier d'origine réexporte ce que les autres
importaient déjà de lui, pour que personne n'ait à changer ses imports.
