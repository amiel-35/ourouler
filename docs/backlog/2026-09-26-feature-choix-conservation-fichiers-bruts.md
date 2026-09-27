# Choix de garder ou d'effacer ses fichiers d'origine

Type : feature
Statut : validée le 27/09/2026 (réécrite après la décision Q67 ; première version validée le 26/09/2026)

## Pourquoi

Depuis Q67 (27/09/2026), ourouler garde les fichiers d'origine (FIT/GPX/TCX) de chacun : rangés par compte, jamais montrés à un autre, inclus dans l'export de la personne, effacés avec le compte. C'est utile — un export déposé ne se re-télécharge pas, la calibration et le dédoublonnage s'en servent — mais ce sont des traces GPS qui partent du domicile : chacun doit pouvoir décider de ne pas les laisser sur le serveur, et changer d'avis. [déduit]

## Ce que je veux voir

- Après le premier import d'un historique ou le premier branchement d'Intervals.icu, une ligne d'information, pas une question : « Vos fichiers d'origine sont gardés sur ce serveur, pour vous seul. Vous pouvez les effacer dans Réglages. »
- Dans Réglages → Mon compte, l'état est visible — « Vous gardez vos fichiers d'origine (N fichiers) » ou « Vous ne gardez pas vos fichiers d'origine » — avec un bouton pour changer.
- Passer à « ne pas garder » demande une confirmation qui dit le coût avant d'agir : « Vos calibrations et votre historique restent. Si le calcul change un jour, il faudra redéposer un export (ou Intervals relira vos sorties). » Une fois confirmé, tous les fichiers d'origine du compte sont effacés tout de suite.
- En « ne pas garder », chaque nouvel import est lu, son dérivé gardé (mailles, coefficients, ce dont la calibration et le dédoublonnage ont besoin), puis le fichier effacé : aucun `.fit`/`.gpx`/`.tcx` ne reste sous le dossier du compte.
- La règle vaut quelle que soit la source : exports déposés comme Intervals.icu.
- Revenir à « garder » vaut pour les imports suivants ; les fichiers déjà effacés ne reviennent pas (l'écran le dit).
- « Entraîner le modèle » est nommé sur la page comme usage futur, marqué « pas encore utilisé », sans effet aujourd'hui.
- Pas de purge d'office : les comptes existants gardent leurs fichiers, avec le même défaut que tout le monde.

## C'est fini quand

Sur un compte de préprod avec les vrais fichiers du mainteneur : dépôt d'un export, puis passage à « ne pas garder » → le listage du dossier du compte ne montre plus aucun fichier d'origine ; un nouvel import n'en laisse aucun ; la calibration relancée depuis l'écran donne le même résultat qu'avant l'effacement (à 1e-9) ; revenir à « garder » puis réimporter garde de nouveau les fichiers.

## Hors sujet

- Définir ce qu'« entraîner le modèle » recouvrira (QP5 b, écarté au 25/09).
- L'import par lien Strava/Garmin : la fiche s'applique aux chemins d'import existants.
- Toute purge des fichiers déjà gardés sans geste de la personne.
- `DELETE /moi` : inchangé, il efface déjà tout.

## Acquis techniques

- Le choix est un enregistrement en base, horodaté, lié au compte : il survit à un redémarrage, figure dans `GET /moi/export` et disparaît avec `DELETE /moi`.
- La calibration et le dédoublonnage doivent fonctionner sur le dérivé : reprendre le calcul pur de la branche garée `q67-sans-brut` (commit `b40d0a69`, retiré du dépôt distant le 27/09/2026 mais récupérable par son SHA), recodé et non rebasé ; une table `derives` avec son fichier de compatibilité (`tests/compatibilite/`).
- Le dérivé se calcule à l'arrivée du fichier, avant tout effacement.

## Questions ouvertes

- Table dédiée ou colonne sur `comptes_proprietaires` pour le choix : détail de schéma à trancher au lot.

## Déjà en place / Doctrine révisée

- `Cache.supprimer_tout()` (`src/ourouler/activites/cache.py`) efface les fichiers d'origine d'un compte.
- `vie_privee.effacer_donnees` (`src/ourouler/api/vie_privee.py`) efface tout avec le compte (testé : `tests/api/test_api_vie_privee.py`).
- Rangement des fichiers d'origine par compte (`brut/comptes/<propriétaire>/`) depuis le 25/09/2026.
- Révise la version du 26/09/2026 (refus par défaut, question à l'arrivée, purge d'office en prod) pour suivre [Q67](../journal/questions/questions_mainteneur.md) et `doctrine_architecture.md` §5, tranchés le 27/09/2026 : garder par défaut, effacer au choix de chacun.
