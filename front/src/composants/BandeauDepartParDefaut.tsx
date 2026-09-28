/** Le bandeau d'un calcul parti du départ de repli du produit, faute de
 * départ renseigné.
 *
 * Fiche `docs/backlog/2026-09-28-bug-depart-fictif-golfe-de-guinee.md` : un
 * compte hébergé sans départ calculait depuis (0, 0) — un point où BRouter
 * n'a pas de carte, « Le traceur ne répond pas » en retour. Le serveur part
 * maintenant du repli du produit (« Paris ») et le dit
 * (`Sortie.depart_par_defaut`/`Boucle.depart_par_defaut`) ; ce bandeau
 * porte l'information jusqu'à l'écran, avec le geste qui la fait
 * disparaître : renseigner son propre départ.
 *
 * `.encart.info` (« Repère ») : ce n'est pas une panne — la recherche a
 * abouti — ni un avertissement du cœur, seulement un fait sur ce calcul-ci.
 */
export function BandeauDepartParDefaut({ actif, nom }: { actif: boolean; nom: string }) {
  if (!actif) return null;
  return (
    <div className="encart info">
      <b>Départ par défaut : {nom}.</b>{" "}
      <a href="/?onglet=reglages">Renseignez le vôtre dans Réglages</a>.
    </div>
  );
}
