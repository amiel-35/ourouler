-- Le choix de garder ou d'effacer ses fichiers d'origine, par compte.
-- Fiche « choix de garder ou d'effacer ses fichiers d'origine », lot du
-- sprint 12. Décision du mainteneur (Q67 révisée le 27/09/2026,
-- doctrine_architecture.md §5) : le brut est gardé par défaut, et chacun
-- peut choisir de ne pas le garder, et changer d'avis.
--
-- Deux colonnes sur `comptes` plutôt qu'une table à part (question ouverte de
-- la fiche, tranchée ici) : c'est un réglage du compte, un seul par compte,
-- jamais interrogé sans lui — une jointure de plus n'aurait rien apporté.
-- Additive, comme le veut `tests/compatibilite/LISEZMOI.md` : `ADD COLUMN`
-- avec un défaut, aucune ligne existante à retoucher. Elle disparaît avec le
-- compte : `comptes` n'a pas de `ON DELETE CASCADE` à poser, c'est la ligne
-- elle-même qui part (`DepotComptes.supprimer_compte_du_proprietaire`).

ALTER TABLE comptes
    ADD COLUMN IF NOT EXISTS conserver_fichiers_bruts BOOLEAN NOT NULL DEFAULT true;

ALTER TABLE comptes
    ADD COLUMN IF NOT EXISTS conserver_fichiers_bruts_le TIMESTAMPTZ NOT NULL DEFAULT now();
