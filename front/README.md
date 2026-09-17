# Le front — lot F2

L'interface que le cycliste utilise. Elle **ne parle qu'à l'API** livrée au
lot F1 (`src/ourouler/api/`), jamais au cœur Python : doctrine §10.2.

Les écrans viennent de `docs/ux/maquettes_v1.html`, les arbitrages de
`docs/ux/cycle_ux_contrat.md`, le contrat des réponses de
`docs/ux/api_contrat.md`.

## Lancer

```sh
# dans un terminal : l'API, sur la configuration de la ligne de commande
uv sync --all-extras
uv run ourouler api --port 8000

# dans un autre : le front, qui lui renvoie /api
cd front
npm install
npm run dev            # http://localhost:5180
```

`OUROULER_API` change la cible du proxy de développement (défaut :
`http://127.0.0.1:8000`). C'est le **seul** réglage d'environnement du front,
et il ne sert qu'au serveur de développement : le code, lui, n'appelle que des
chemins relatifs sous `/api/v1`, si bien qu'en production l'API et le front se
servent depuis la même origine.

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

**La seule fonction qui calcule** est `compteArrets` (`src/api/formats.ts`) :
le JSON n'expose que des arrêts *au kilomètre*, l'affichage doit montrer un
nombre absolu. Elle retrouve l'entier d'origine, et **se tait** quand le
produit ne retombe pas juste.

**Les trois valeurs liées** (`src/composants/EcranFtp.tsx`) se recalculent par
l'API, jamais côté front — le modèle physique reste dans le cœur. Ce qui est
enregistré est la **position dans la zone**, jamais les watts (décision 7), et
la moyenne compteur dit toujours si son facteur est mesuré ou supposé
(décision 8).

**Les échecs sont des écrans** (`src/composants/Echec.tsx`), choisis sur le
**code** de la panne et jamais sur son message. `Barriere` attrape en dernier
recours ce qu'aucun écran n'avait prévu : une page blanche est le pire des
états d'échec.

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
