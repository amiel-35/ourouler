# Le verrou de tâche de fond pendant la bascule « ne pas garder »

Type : feature
Statut : à valider

## Pourquoi

Passer à « ne pas garder ses fichiers d'origine »
(`2026-09-26-feature-choix-conservation-fichiers-bruts.md`) lance une tâche
de fond (`NATURE_CONSERVATION`) qui dérive puis efface, exactement comme un
import ou une calibration — et tient le **même verrou serveur entier**
(`api/taches_fond.VERROU`) qu'elles : une seule tâche lourde à la fois, pour
tout le service, quel que soit le compte. C'est un choix déjà assumé et
documenté (« le serveur est petit, partagé avec BRouter ») pour les trois
natures de tâche, pas un oubli — mais la protection de test qui va avec
n'est posée que d'un côté du dépôt, et c'est ce que cette fiche vient
corriger avant que ça ne coûte une fausse alerte en CI ou en prod. [déduit]

## Ce que je veux voir

- La même garantie de test des deux côtés du dépôt : un test qui commence
  avec `VERROU` déjà tenu doit échouer vite et clairement, pas expirer après
  un délai obscur ; un test qui **laisse tourner** une tâche de fond réelle
  (comme `test_revenir_a_garder_refuse_tant_que_l_effacement_de_ce_compte_tourne`,
  `tests/comptes/test_conservation_fichiers.py`, qui utilise `_ArchiveLente`
  pour garder une tâche `en_cours`) doit soit attendre sa fin avant de
  rendre la main au test suivant, soit le documenter explicitement si ce
  n'est pas nécessaire.
- Une fixture dans `tests/comptes/conftest.py` équivalente à
  `tests/api/conftest.py::taches_lourdes_rendues` : attendre que `VERROU`
  soit libre en tout début de test (avec un délai borné et un message
  explicite s'il ne l'est pas), pour que l'ordre de collecte des tests
  (alphabétique : `adversarial`, `api`, `caracterisation`, `compatibilite`,
  `comptes`…) ne fasse pas hériter `tests/comptes/` d'un verrou encore tenu
  par un fil de `tests/api/` qui vient de finir.
- Vérifier si le test d'import instable en CI mentionné par le mainteneur
  est bien celui que cette fenêtre explique : la fenêtre documentée dans
  `tests/api/conftest.py` (« quelques millisecondes après son fini ») est
  déjà connue et corrigée côté `tests/api/` — reste à savoir si l'instabilité
  observée vient de cette même fenêtre côté `tests/comptes/`, non protégée,
  ou d'autre chose. Cette fiche ne peut pas trancher sans le journal CI réel
  de l'échec ; le rapprochement ci-dessous est un risque plausible, pas une
  preuve.
- Documenter, dans `api/taches_fond.py` ou à côté, que `VERROU` est un objet
  de **module Python**, partagé par tous les tests d'un même processus
  `pytest` — pas seulement par les tests d'un même dossier — pour que la
  prochaine personne qui ajoute un dossier de tests qui touche une tâche de
  fond sache qu'elle doit, elle aussi, protéger son ordre d'exécution.

## C'est fini quand

`uv run pytest -q tests/comptes tests/api` (dans cet ordre, puis dans l'ordre
inverse) passe de façon répétée sans échec sur `tache_lourde_en_cours` ni sur
un verrou resté tenu ; une exécution volontairement cassée (un test de
`tests/comptes/` qui ne relâche pas `VERROU` en fin de tâche, simulée) est
détectée par la nouvelle fixture avec un message qui nomme le fichier
fautif, pas un délai silencieux.

## Hors sujet

- Changer la granularité du verrou (un verrou par nature de tâche plutôt
  qu'un seul pour les trois) : décision produit distincte, qui touche au
  budget mémoire du serveur (doctrine du module `taches_fond.py`), pas un
  sujet de test.
- Revoir `annuler_et_attendre`/`suspendre` (la suppression de compte pendant
  une tâche en cours) : déjà testés et documentés séparément, ce lot ne les
  touche pas.

## Acquis techniques

- Le verrou lui-même est déjà défensif à l'exécution : `taches_fond.lancer`
  relâche `VERROU` dans un `finally` qui couvre aussi l'échec de
  `Thread.start()` lui-même (`test_un_fil_qui_ne_demarre_pas_rend_le_verrou`,
  `tests/api/test_imports_fond.py`) — le risque traité ici est un risque de
  **test** (ordre, fenêtre de quelques millisecondes), pas un risque de
  verrou qui ne se relâche jamais en usage réel.
- `tests/api/conftest.py::taches_lourdes_rendues` donne déjà le patron exact
  à reproduire pour `tests/comptes/` : attendre `VERROU.acquire(blocking=False)`
  en boucle jusqu'à 30 s, puis le relâcher.

## Questions ouvertes

- Le mainteneur a-t-il le nom du test d'import qui est instable en CI et un
  lien vers l'échec réel ? Sans lui, cette fiche ne peut proposer qu'un
  rapprochement plausible avec la fenêtre déjà documentée, pas une preuve
  du lien de cause.

## Déjà en place / Doctrine révisée

- Constaté : `src/ourouler/api/taches_fond.py::VERROU` (`threading.Lock`,
  ligne 60) est un objet de module, partagé par tout processus qui importe
  `ourouler.api.taches_fond` — donc par tous les dossiers de tests qui
  tournent dans le même `pytest`, pas seulement `tests/api/`.
- Constaté : `tests/comptes/test_conservation_fichiers.py` importe et
  manipule directement `taches_fond.VERROU` (`test_bascule_refusee_tant_qu_une_tache_lourde_tourne`,
  ligne 153 ; `test_revenir_a_garder_refuse_tant_que_l_effacement_de_ce_compte_tourne`)
  et lance de vraies tâches de fond via l'API (`PUT /moi/fichiers-origine`,
  `routes/moi.py`, qui appelle `taches_fond.lancer(..., NATURE_CONSERVATION,
  ...)`, ligne 258).
- Constaté : `tests/comptes/conftest.py` ne contient **aucune** fixture qui
  attend ou vérifie l'état de `taches_fond.VERROU` — contrairement à
  `tests/api/conftest.py::taches_lourdes_rendues`, qui documente
  explicitement la fenêtre de quelques millisecondes après qu'une tâche se
  dit « finie » et avant qu'elle ait vraiment relâché le verrou, et le refus
  `import_deja_en_cours` que cette fenêtre a déjà causé une fois.
- Constaté : l'ordre de collecte par défaut de `pytest` (aucun plugin
  `pytest-xdist` ni `pytest-randomly` dans `pyproject.toml`) place
  `tests/api/` avant `tests/comptes/` (ordre alphabétique des dossiers) : un
  fil de `tests/api/` qui termine juste avant le passage à `tests/comptes/`
  tombe dans la fenêtre non protégée de ce second dossier.
- Constaté : `_ArchiveLente` (`tests/comptes/test_conservation_fichiers.py`)
  bloque volontairement une tâche `NATURE_CONSERVATION` jusqu'à 5 s
  (`threading.Event.wait(5.0)`) pour la garder « en_cours » le temps d'un
  test — si l'assertion du test échoue avant que ce délai soit écoulé, le
  fil continue de tourner en arrière-plan et de tenir `VERROU` après la fin
  apparente du test.
