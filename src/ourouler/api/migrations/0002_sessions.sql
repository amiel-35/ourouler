-- Les sessions : un jeton opaque, révocable, borné dans le temps.
-- Lot L7.2-C, 19/09/2026. Doctrine §10.2.
--
-- Décision du mainteneur, même esprit que 0001_comptes.sql (« pas une
-- banque ») : pas de cookie signé, pas de clé de serveur à gérer — un jeton
-- opaque tiré au hasard, rangé en base, vaut plus simple et se révoque
-- gratuitement (une ligne effacée, ce que fait POST /sortir). Pas de
-- renouvellement glissant non plus : l'échéance est posée une fois, à la
-- création, et n'est jamais repoussée par l'usage — une session expire à
-- date fixe, elle ne s'étire pas.
--
-- Table d'identité, au même titre que `comptes` et `invitations`
-- (TABLES_IDENTITE, tests/test_invariants.py et
-- tests/api/test_api_isolation_proprietaire.py) : une session précède la
-- résolution d'un `Proprietaire`, elle ne lui appartient pas — c'est
-- justement son rôle de la produire (`DepotComptes.proprietaire_de_la_session`).
-- Lui demander une colonne `proprietaire` serait circulaire, comme pour les
-- deux autres tables d'identité.

CREATE TABLE IF NOT EXISTS sessions (
    -- Même forme que le jeton d'invitation, et pour la même raison : 32
    -- octets d'entropie tirés par `secrets.token_urlsafe` (voir
    -- `comptes.OCTETS_JETON_SESSION`), hors de portée d'une recherche
    -- exhaustive.
    jeton     TEXT PRIMARY KEY
              CONSTRAINT sessions_jeton_forme CHECK (jeton ~ '^[A-Za-z0-9_-]{20,255}$'),
    compte    TEXT NOT NULL REFERENCES comptes (id) ON DELETE CASCADE,
    cree_le   TIMESTAMPTZ NOT NULL DEFAULT now(),
    expire_le TIMESTAMPTZ NOT NULL,
    CONSTRAINT sessions_expire_apres_creation CHECK (expire_le > cree_le)
);
