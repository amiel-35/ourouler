# Le bouton retour du navigateur quitte l'appli au lieu de revenir au formulaire

Type : bug
Statut : validée le 27/09/2026
Gravité : gênant
Signalé le 27/09/2026

## Constat

Sur la page de résultats « 3 boucles », un retour arrière du navigateur ne
ramène pas au formulaire « Demander » : il affiche une réponse JSON brute,
« {"erreur":{"code":"route_inconnue","message":"cette route n'existe pas sur
ce serveur — la liste de celles qui sont servies est dans /openapi.json",…}} »,
avec en plus « â€” » à la place du tiret dans Safari.

## Où

Interface web, écran de résultats après « Chercher 3 parcours » ; prod,
v0.11.0 ; Safari sur Mac.

## Pour reproduire

1. Ouvrir l'appli, onglet « Demander », « Chercher 3 parcours ».
2. Sur la page « 3 boucles », retour arrière du navigateur.

## Attendu

Retour au formulaire « Demander », la demande telle qu'elle était (comme
« Modifier la demande »).

## Observé

Le navigateur quitte l'appli et revient à la page précédente de l'onglet —
ici une erreur JSON `route_inconnue`.

## Gravité

Gênant — tout invité ; contournable par « Modifier la demande », mais sur
téléphone le retour se fait par réflexe et les boucles sont perdues.

## Piste

- Constaté : le front n'inscrit aucun écran dans l'historique du navigateur.
  `front/src/app/navigation.ts` ne fait qu'un `replaceState` pour `/entrer` ;
  aucun `pushState` ni `popstate` dans `front/src/`. Rejoué en local (image
  0.11.0, mode personnel) : `history.length` vaut 2 sur « 3 boucles », et le
  retour sort de l'appli.
- Constaté : le serveur ne rend `route_inconnue` que pour `/api`, `/sante`,
  `/openapi.json`, `/docs`, `/redoc` ou un chemin de fichier
  (`src/ourouler/api/application.py`, `_erreur_du_cadre`) ; tout autre chemin
  sert l'appli. La page d'avant dans l'onglet était donc l'une de ces
  adresses.
- [déduit] Les « â€” » viennent de l'affichage JSON de Safari : la prod
  annonce bien `application/json; charset=utf-8` (vérifié en lecture).
- [déduit] Correctif : inscrire chaque écran (onglet, formulaire → résultats)
  dans l'historique (`pushState`) et redessiner sur `popstate` ; les
  résultats sont déjà gardés côté front (`front/src/etat/memoire.ts`), le
  retour peut les retrouver sans recalcul.

## C'est corrigé quand

Sur la préprod, dans Safari et Chrome sur téléphone : Demander → Chercher →
retour ramène au formulaire rempli ; avancer ramène aux mêmes boucles sans
nouveau calcul ; aucun retour depuis l'appli ne tombe sur une erreur JSON.

## Questions ouvertes

- Quelle page l'onglet affichait-il juste avant ? L'appli ne produit pas
  elle-même d'adresse `/api` dans l'historique, sauf peut-être un lien de GPX
  ouvert par Safari au lieu d'être téléchargé : à rejouer dans Safari.
- L'adresse doit-elle porter l'écran (`/?onglet=demander`, `/boucles`) pour
  qu'un rechargement y ramène, ou seul le retour compte-t-il ?
