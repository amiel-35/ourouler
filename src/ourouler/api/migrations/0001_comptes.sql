-- Les comptes, les invitations, et le lien vers le propriétaire pseudonyme.
-- Lot L7.2-A, 18/09/2026. Doctrine §10.2 et [[Q46]].
--
-- Trois idées portent ce fichier, et chacune est une contrainte plutôt qu'une
-- règle de code :
--
--   1. L'identité d'un compte est un identifiant **à nous**, opaque, jamais
--      l'adresse et jamais un entier qui se devine. Il finit en segment de
--      chemin : sa forme est vérifiée ici, pas seulement en Python.
--   2. Une adresse ne peut être titulaire que d'un compte. C'est l'index
--      unique sur `lower(email)` qui le dit — un « SELECT puis INSERT » se
--      fait doubler par deux requêtes concurrentes, une contrainte non.
--   3. Le compte et le propriétaire sont **deux** identifiants. Le premier
--      porte l'identité et l'accès, le second est la clé pseudonyme sous
--      laquelle vivent les données. `comptes_proprietaires` les relie, et
--      c'est cette ligne-là qu'on efface à la suppression d'un compte.

-- La forme d'un identifiant, telle que `api/proprietaire.py` la définit
-- (`FORME_IDENTIFIANT`). Elle est répétée ici exprès : une base qui accepte
-- « ../autre » pour un identifiant qui sert de segment de chemin dans le
-- dépôt de fichiers accepte une traversée de répertoire. Un test vérifie que
-- les deux écritures disent bien la même chose.

CREATE TABLE IF NOT EXISTS comptes (
    id       TEXT PRIMARY KEY
             CONSTRAINT comptes_id_forme CHECK (id ~ '^[a-z0-9][a-z0-9_-]{0,63}$'),
    -- L'adresse est une **donnée du profil**, pas la clé (doctrine §10.2 :
    -- « un utilisateur peut changer de fournisseur »). Elle est rangée sous
    -- sa forme normalisée — minuscules, sans espaces de bord — et la
    -- contrainte l'exige : sans elle, « Cycliste@Exemple.INVALID » et
    -- « cycliste@exemple.invalid » seraient deux lignes que l'index unique
    -- ci-dessous ne rapprocherait jamais, parce qu'il faut bien que quelqu'un
    -- décide de la forme canonique et que ce quelqu'un ne peut pas être
    -- l'appelant.
    --
    -- `btrim` ne coupe que l'espace ASCII : cette contrainte laisse donc
    -- passer « a\n@… ». C'est `normaliser_email` qui refuse les caractères de
    -- contrôle, et la note de cette fonction dit pourquoi ça compte.
    email    TEXT NOT NULL
             CONSTRAINT comptes_email_normalise CHECK (email = lower(btrim(email)))
             CONSTRAINT comptes_email_non_vide CHECK (length(email) > 0),
    cree_le  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- **La règle d'unicité du produit**, et elle est ici et nulle part ailleurs :
-- « inviter deux fois la même adresse répond qu'il a déjà un compte ». Sur
-- `lower(email)` et non sur `email` : la contrainte de normalisation ci-dessus
-- rend les deux équivalents aujourd'hui, mais si elle tombait un jour, c'est
-- cet index qui continuerait de mordre.
CREATE UNIQUE INDEX IF NOT EXISTS comptes_email_unique ON comptes (lower(email));


CREATE TABLE IF NOT EXISTS invitations (
    -- **Le condensé, jamais le jeton.** SHA-256 en hexadécimal : un jeton en
    -- base est un jeton qu'une fuite de sauvegarde rend utilisable, et une
    -- sauvegarde fuit plus souvent qu'une base.
    condense    TEXT PRIMARY KEY
                CONSTRAINT invitations_condense_forme CHECK (condense ~ '^[0-9a-f]{64}$'),
    compte      TEXT NOT NULL REFERENCES comptes (id) ON DELETE CASCADE,
    cree_le     TIMESTAMPTZ NOT NULL,
    expire_le   TIMESTAMPTZ NOT NULL,
    consomme_le TIMESTAMPTZ,
    CONSTRAINT invitations_expire_apres_creation CHECK (expire_le > cree_le)
);

-- Au plus **une invitation non consommée** par compte, garanti par la base.
-- Choix du mainteneur : quand une invitation est déjà en cours, on n'en
-- fabrique pas une seconde — « le cas réel c'est qu'il ne l'a pas vue ».
-- Une invitation expirée reste non consommée, donc elle occupe encore la
-- place : c'est le dépôt qui la retire avant d'en poser une neuve, dans la
-- même transaction. L'index n'a pas le droit de parler du temps qui passe
-- (`now()` n'est pas immuable), et c'est très bien : il dit « une seule en
-- attente », ce qui est vrai quoi qu'il arrive, plutôt qu'une règle qui
-- changerait de valeur entre deux lectures.
CREATE UNIQUE INDEX IF NOT EXISTS invitations_en_cours_unique
    ON invitations (compte) WHERE consomme_le IS NULL;


-- La table de correspondance de [[Q46]], décidée le 17/09/2026.
--
-- Deux identifiants distincts, et c'est tout l'intérêt : supprimer la ligne
-- d'ici coupe le lien entre quelqu'un et les données rangées sous son
-- propriétaire. Le profil, les fichiers et les clés partent avec le compte ;
-- les poids de routes appris restent sous un propriétaire que plus rien ne
-- rattache à une personne.
--
-- `compte` est la clé primaire (un compte, un propriétaire) et `proprietaire`
-- est unique (un propriétaire, un compte) : la correspondance est bijective,
-- et la base le dit au lieu de l'espérer.
CREATE TABLE IF NOT EXISTS comptes_proprietaires (
    compte       TEXT PRIMARY KEY REFERENCES comptes (id) ON DELETE CASCADE,
    proprietaire TEXT NOT NULL UNIQUE
                 CONSTRAINT comptes_proprietaires_forme
                 CHECK (proprietaire ~ '^[a-z0-9][a-z0-9_-]{0,63}$'),
    cree_le      TIMESTAMPTZ NOT NULL DEFAULT now()
);
