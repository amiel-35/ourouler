# Vérification des valeurs par défaut sur les invités

Type : feature
Statut : validée le 26/09/2026

## Pourquoi

Le filet pour un cycliste jamais calibré (assistant d'accueil, T5) sert deux conventions : un jeu de littérature CdA/Crr par usage (`route`, `clm`) et une FTP par défaut (2,2 W/kg). Les deux ont été choisies par mesure — mais **sur un seul cycliste, ses deux vélos** (Amiel lui-même). Q57 et Q65 le disent en toutes lettres dans le code : « n = 1 », rien vérifié sur un autre gabarit. [déduit] Avec des invités réels depuis le 25/09, certains désormais calibrés, la mesure qui manquait — comparer la convention à un second cycliste — est enfin possible, plutôt que de rester une hypothèse indéfiniment.

## Ce que je veux voir

- Seuls les invités qui ont donné leur accord explicite entrent dans la mesure : on leur demande (message ou case dédiée) avant de lire quoi que ce soit. Sans accord, leurs données ne sont pas lues. Utiliser les données d'un invité pour régler une valeur qui sert à tous relève d'« entraîner le modèle » (QP5 : nommé, sans usage, refus par défaut).
- Une mesure (script, sur le modèle de la campagne du 17/09 pour les jeux de littérature, ou de `facteur_compteur_retrospectif.py` pour le principe) qui, pour chaque invité **désormais calibré et ayant donné son accord** (CdA/Crr propres, via `POST /calibrations`), compare :
  - son FTP réel (déclaré ou mesuré) à ce que `ftp_defaut(masse_kg)` aurait rendu pour lui ;
  - son F@27 calibré à celui du jeu de littérature que sa catégorie (`route`/`clm`) lui aurait servi.
- Un rapport écrit noir sur blanc, dans le même style que les campagnes déjà faites (nombre d'invités et de sorties, écart en minutes sur une boucle de 2 h, dans quel sens), pas une conclusion sans les chiffres.
- Si la convention actuelle tient (écart du même ordre que celui déjà mesuré sur Amiel), le dire et fermer Q57/Q65 en l'état. Si elle ne tient pas, dire précisément sur quoi elle se trompe (FTP trop haute/basse, quel usage, de combien).
- Exemple : au bout de quelques invités calibrés, un tableau du type « FTP par défaut : 3 invités, écart moyen +0,3 W/kg (surestime légèrement) » — pas une phrase vague.
- Aucune constante (jeu de littérature, FTP par défaut) ne change sans une décision explicite du mainteneur : la mesure produit un rapport, elle ne déclenche jamais elle-même un changement de valeur.

## C'est fini quand

Amiel a sous les yeux, sur les vraies données d'au moins un invité réellement calibré et ayant donné son accord explicite (pas une simulation), un tableau mesuré comparant la convention actuelle à sa calibration personnelle — dans le même format que les campagnes du 17/09 et du 23/09 — avec de quoi juger si Q57 et Q65 doivent bouger ou rester en l'état.

## Hors sujet

- Pas de troisième jeu de littérature, pas de méthode plus fine par âge ou fréquence de pratique (option (c) de Q65, déjà écartée par le mainteneur).
- Pas d'ouverture d'un usage vélo supplémentaire (gravel, etc.) : `USAGES_VELO` reste `("route", "clm")`.

## Acquis techniques

- La méthode de mesure (F@27 comme critère, `mae × 120` pour convertir en minutes sur 2 h) est déjà celle retenue par la campagne du 17/09 — pas à réinventer, juste à rejouer sur un second échantillon.
- Aucune modification de `litterature.py` tant que la mesure ne conclut pas : le module dit déjà « n = 1 », ce n'est pas un défaut caché, juste incomplet.
- Aucun réseau, aucune donnée individuelle d'un invité recopiée hors du serveur ni dans le dépôt : le rapport ne contient que des écarts, sans identité. La mesure ne lit que les comptes dont l'accord est enregistré en base (preuve horodatée, même mécanique que la fiche « Choix de conservation des fichiers bruts »).
- Tout changement de constante, si l'écart mesuré est net, est toujours remonté en question au mainteneur avant d'être appliqué — jamais un ajustement automatique, y compris pour la FTP seule.

## Questions ouvertes

- Combien d'invités calibrés suffisent pour que la mesure soit jugée solide plutôt qu'anecdotique (le dépôt n'a pas encore de convention sur ce seuil, contrairement au minimum de sorties pour une calibration individuelle) — à juger au moment où les premiers chiffres arrivent, pas maintenant sans données.

## Déjà en place / Doctrine révisée

- `physique/litterature.py` : `PAR_USAGE` (jeu CdA/Crr par usage, choisi par F@27 le plus proche de la référence mesurée sur Amiel) et `ftp_defaut()` (`FTP_W_PAR_KG_DEFAUT = 2,2`, borné [50, 1000]) — les deux conventions existent et sont déjà appliquées à l'assistant d'accueil, marquées « non mesuré au-delà de n=1 » dans leurs commentaires.
- Méthode de mesure (campagne du 17/09, F@27 et `mae×120`) déjà écrite et documentée.
- Q65 option (c) — méthode plus fine par âge/fréquence — écartée par le mainteneur, non reposée ici.
- Préparation sprints 11/12 §1 (cette fonctionnalité) : « leur option "attendre un deuxième cycliste" est devenue jouable, les invités sont là » — reprise telle quelle comme déclencheur de cette fiche.
- Aucune doctrine révisée. QP5 (25/09/2026) appliquée : « entraîner le modèle » exige un accord explicite, refus par défaut.
- Tranché le 26/09/2026 : la mesure ne porte que sur les invités qui ont donné leur accord explicite ; elle dépend en pratique de la fiche « Choix de conservation des fichiers bruts » (même mécanique de preuve). Aucune constante ne change sans décision explicite du mainteneur, y compris pour la FTP seule ; la mesure produit un rapport, jamais un ajustement automatique.
