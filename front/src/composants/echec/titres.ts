/** Le titre de l'écran d'échec générique, par code de panne. */

// Tout ce qu'`Echec` ne traite pas par un écran dédié : une panne qu'on
// nomme, et ce qui marche encore.
//
// **Inventaire complet du 18/09/2026** (L7.D). Avant ce lot, 13 des 21
// codes d'`api/erreurs.CODES_PANNE` avaient un écran — 9 par une entrée de
// ce tableau, 4 par un écran dédié (`aucune_boucle`, `meteo_indisponible`,
// `meteo_hors_domaine`, `intervals_refuse`, tous traités plus haut). Les 8
// restants (`requete_invalide`, `fichier_introuvable`,
// `generation_introuvable`, `route_inconnue`, `methode_refusee`,
// `service_externe_indisponible`, `configuration_invalide`,
// `erreur_interne`) tombaient dans « Ça n'a pas marché » — pas un écran
// muet (le message et le code restaient affichés), mais pas non plus le
// titre qui dit ce qui s'est passé. `tests/inventaire_erreurs.test.tsx`
// relit `CODES_PANNE` dans les sources Python pour qu'un code qu'on y
// ajoute sans le nommer ici casse un test, plutôt que de retomber en
// silence dans le générique — c'est ainsi que `session_absente` (L7.A,
// mergé pendant ce lot) a été trouvé, et il a son propre écran plus haut.
export const TITRES_PANNE: Record<string, string> = {
  // Sans écran dédié : `App.tsx` intercepte ces quatre codes avant qu'ils
  // n'atteignent `Echec` (lot L7.2-D — l'écran de connexion, ou celui
  // d'activation d'une invitation, les traite lui-même). Un titre nommé
  // reste ici en filet, pour le jour où l'un d'eux échapperait à cette
  // interception.
  session_absente: "Vous n'êtes plus connecté",
  invitation_invalide: "Ce lien d'invitation n'est plus valable",
  identifiants_refuses: "Adresse ou mot de passe refusés",
  mot_de_passe_actuel_refuse: "Mot de passe actuel refusé",
  comptes_indisponibles: "Ce serveur ne gère pas de comptes",
  requete_invalide: "Cette demande n'est pas valide",
  profil_invalide: "Ce réglage ne tient pas",
  fichier_illisible: "Ce fichier n'a pas été compris",
  format_non_lu: "Ce format n'est pas encore lu",
  fichier_trop_gros: "Ce fichier est trop gros",
  fichier_introuvable: "Ce fichier n'est plus accessible",
  // Le GPX d'une génération oubliée : l'API le dit dans son message
  // (« relancer la recherche »), mais un titre qui reprend le mot
  // « introuvable » sans le nommer laisserait croire à un bug plutôt qu'à
  // une mémoire qui a fait sa place (`docs/ux/api_contrat.md`).
  generation_introuvable: "Cette recherche n'est plus disponible",
  // Pas « adresse » : ce mot désigne déjà l'adresse postale du départ
  // ailleurs dans l'écran (`FormulaireAdresse`, E16) — l'ambigüité aurait
  // fait croire à une adresse mal saisie plutôt qu'à un chemin d'API
  // inconnu.
  route_inconnue: "Cette route de l'API n'existe pas",
  methode_refusee: "Cette route n'accepte pas cette méthode",
  calcul_en_cours: "Un calcul occupe déjà le serveur",
  // L9.3 : un compte hébergé qui a épuisé son quota du jour. Le message de
  // l'API dit déjà quand ça se libère (minuit UTC) — pas de bouton
  // « réessayer » ici (absent de `reessayable`, `api/client.ts`) : un
  // nouvel essai immédiat échouera pareil.
  quota_atteint: "Quota quotidien atteint",
  import_deja_en_cours: "Un import occupe déjà le serveur",
  // L9.4 — la calibration depuis l'écran. `Reglages` montre d'ordinaire
  // ces refus dans la fiche vélo elle-même ; les titres restent ici en
  // filet, comme pour les autres codes.
  tache_lourde_en_cours: "Un calcul long occupe déjà le serveur",
  // Une seconde `DELETE /moi` pendant qu'une première attend la fin
  // d'une tâche de fond de ce compte (jusqu'à deux minutes) : elle
  // refuse tout de suite plutôt que d'attendre à son tour.
  suppression_deja_en_cours: "Suppression déjà en cours",
  velo_absent: "Aucun vélo déclaré",
  ftp_absente: "Votre FTP manque",
  sorties_insuffisantes: "Pas encore assez de sorties",
  pneu_absent: "Quels pneus sur ce vélo ?",
  brouter_indisponible: "Le traceur ne répond pas",
  intervals_indisponible: "intervals.icu est en panne",
  geocodage_indisponible: "L'annuaire d'adresses ne répond pas",
  service_externe_indisponible: "Un service externe ne répond pas",
  // Le serveur tourne et **refuse** : la distinction avec « ne répond pas »
  // se voit dès le titre, qui dit ce qui manque au serveur et non ce qui
  // manquerait à la demande.
  profil_absent: "Ce serveur n'a pas de profil",
  configuration_invalide: "La configuration du serveur ne tient pas",
  erreur_interne: "Quelque chose a cassé côté serveur",
};
