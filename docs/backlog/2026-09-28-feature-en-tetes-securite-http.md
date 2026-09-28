# En-têtes de sécurité HTTP sur l'API et le front servi

Type : feature
Statut : à valider

## Pourquoi

Un cycliste ouvre ourouler dans un navigateur, sur une page qui affiche sa
masse, sa FTP, son point de départ et sa position — la même origine sert le
front et l'API (`docs/retour_arriere.md`, `deploiement/api/README.md`, un
seul conteneur, un seul domaine Coolify). Traefik termine le TLS devant, mais
rien derrière ne dit au navigateur comment se comporter avec ce qu'il reçoit :
pas de politique de contenu, pas d'obligation de rester en HTTPS, pas de
consigne contre l'auto-détection de type. Un invité réel est en prod depuis
aujourd'hui (28/09/2026) ; ce sont des en-têtes qui coûtent quelques lignes et
qui ferment des portes qu'on n'a pas encore eu besoin d'ouvrir. [déduit]

## Ce que je veux voir

- Sur **toute** réponse de l'API (`/api/v1/...`, `/sante`, `/openapi.json`)
  et sur le front servi (`index.html`, `/assets/...`) :
  - `X-Content-Type-Options: nosniff` ;
  - `Referrer-Policy: strict-origin-when-cross-origin` (ou plus strict) ;
  - `Strict-Transport-Security` (avec `includeSubDomains`, une durée longue —
    à discuter avec le mainteneur avant `preload`, qui engage le domaine) ;
  - une `Content-Security-Policy` qui couvre au moins `default-src 'self'`,
    `frame-ancestors 'none'`, et les origines réelles que le front appelle
    (tuiles Leaflet, polices) — à établir en lisant `front/src/` pour ne
    manquer aucune source légitime ;
  - `X-Frame-Options: DENY` étendu à toutes les réponses, pas seulement aux
    pages HTML de l'administration.
- Un seul endroit qui les pose, pas une ligne par route : un middleware
  ASGI (aux côtés de `LimiteTailleCorps`, `GardeAvantCorps`,
  `ProxyHeadersMiddleware` déjà posés dans `application.py`), pour que
  personne n'ajoute une route qui les oublie.
- Le HSTS ne se pose que si la réponse est déjà servie en HTTPS : en local
  (`ourouler api`, `http://127.0.0.1`) le middleware ne doit rien casser.
- Aucune régression sur le mode personnel ni sur l'administration (tunnel
  SSH, `X-Frame-Options: DENY` déjà posé dans `api/admin.py` — à ne pas
  dupliquer si le middleware général couvre déjà ce cas).

## C'est fini quand

Sur la préproduction, `curl -I` sur `/`, sur une route `/api/v1/...` et sur
l'admin (par le tunnel) montrent chacune les cinq en-têtes ; un test d'API
vérifie leur présence sur au moins une route de chaque catégorie (JSON,
front statique, admin) pour qu'une régression future casse la CI plutôt que
d'être découverte en prod.

## Hors sujet

- Un pare-feu applicatif (WAF) devant Traefik : hors périmètre de ce lot,
  au-delà de ce que Coolify propose déjà.
- `Permissions-Policy` détaillée (caméra, micro, géolocalisation…) : la CSP
  et les quatre autres en-têtes sont la priorité ; à revoir si un besoin
  précis apparaît (le front demande déjà la géolocalisation du navigateur
  pour le départ — vérifier que la CSP ne la bloque pas par erreur).
- Réécrire `_StaticFilesAvecCache` au-delà d'y ajouter ces en-têtes.

## Acquis techniques

- `src/ourouler/api/application.py` pose déjà trois middlewares dans cet
  ordre (`LimiteTailleCorps`, `GardeAvantCorps`, `ProxyHeadersMiddleware`) :
  un quatrième s'ajoute au même endroit, sans changer les trois autres.
- `_StaticFilesAvecCache.file_response` (`application.py`) montre déjà le
  point d'entrée pour ajouter un en-tête par réponse statique
  (`Cache-Control` aujourd'hui) : le même geste vaut pour les en-têtes de
  sécurité si le middleware général ne suffit pas à couvrir les fichiers
  statiques.

## Questions ouvertes

- La CSP doit-elle autoriser des tuiles de carte externes (si Leaflet en
  charge un jour) ou seulement ce que le front sert lui-même ? À trancher en
  lisant `front/src/` avant d'écrire la politique.
- HSTS avec `preload` ou non : engage le domaine au-delà de ce dépôt, à
  poser au mainteneur plutôt qu'à décider ici.

## Déjà en place / Doctrine révisée

- Constaté : `src/ourouler/api/application.py` pose trois middlewares
  (`app.add_middleware(LimiteTailleCorps, ...)`, `GardeAvantCorps`,
  `ProxyHeadersMiddleware`) et aucun n'ajoute d'en-tête de sécurité — recherche
  de `Content-Security-Policy`, `Strict-Transport-Security`,
  `X-Content-Type-Options`, `Referrer-Policy`, `Permissions-Policy` sur tout
  le dépôt (hors `.venv`) : aucune occurrence.
- Constaté : `src/ourouler/api/admin.py::_page` pose
  `X-Frame-Options: DENY` (ligne 207) et `Cache-Control: no-store`, mais
  seulement sur les pages HTML de l'administration — les réponses JSON de
  `/api/v1/...` et le front statique n'ont rien.
- Constaté : `front/index.html` ne porte aucune balise `<meta
  http-equiv="Content-Security-Policy">`.
- Constaté : `docker-compose.api.coolify.yml` ne déclare aucune étiquette
  Traefik (`labels:` absent) — Coolify pose le domaine et le TLS
  (`SERVICE_FQDN_API_8000`) mais rien de plus ; les en-têtes de réponse, s'il
  y en avait, viendraient de l'application, pas du proxy.
- Constaté : `_StaticFilesAvecCache` (`application.py`) montre déjà le geste
  d'ajouter un en-tête par réponse statique (`Cache-Control`), un patron
  direct pour y ajouter les en-têtes de sécurité si le middleware général ne
  les couvre pas pour les fichiers servis par `StaticFiles`.
