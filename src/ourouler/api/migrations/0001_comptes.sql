-- Les comptes, les invitations, et le lien vers le propriétaire pseudonyme.
-- Lot L7.2-A, 18/09/2026. Doctrine §10.2 et [[Q46]].
--
-- Révisé le 18/09/2026 par décision du mainteneur (« c'est pas une banque » ;
-- « je trouve que tu compliques les choses, on va revenir au basique ») avant
-- toute mise en service : rien de ce schéma n'a encore tourné en dehors des
-- tests, la réécrire ici est donc un ajustement, pas une migration ultérieure.
-- Le cycle de vie retenu, en quatre étapes : inviter crée un compte inactif
-- et une invitation ; ouvrir le lien ne consomme rien ; poser un mot de passe
-- active le compte et consomme l'invitation, les trois dans une transaction ;
-- le reste de l'inscription se fait sous session normale.
--
-- Ce qui porte encore une contrainte plutôt qu'une règle de code :
--
--   1. L'identité d'un compte est un identifiant **à nous**, opaque, jamais
--      l'adresse et jamais un entier qui se devine. Il finit en segment de
--      chemin : sa forme est vérifiée ici, pas seulement en Python.
--   2. Une adresse ne peut être titulaire que d'un compte. C'est l'index
--      unique sur `lower(email)` qui le dit — un « SELECT puis INSERT » se
--      fait doubler par deux requêtes concurrentes, une contrainte non.
--   3. Un compte actif a toujours un secret, et un compte inactif n'en a
--      jamais : la base le dit par une contrainte, pas par une promesse du
--      code qui pose les deux colonnes dans le bon ordre.
--   4. Le compte et le propriétaire sont **deux** identifiants. Le premier
--      porte l'identité et l'accès, le second est la clé pseudonyme sous
--      laquelle vivent les données. `comptes_proprietaires` les relie, et
--      c'est cette ligne-là qu'on efface à la suppression d'un compte.

CREATE TABLE IF NOT EXISTS comptes (
    -- Sert de segment de chemin dans le dépôt de fichiers : une base qui
    -- accepterait « ../autre » ouvrirait une traversée de répertoire. Un
    -- test vérifie que cette forme et `FORME_IDENTIFIANT` (Python) disent la
    -- même chose.
    id       TEXT PRIMARY KEY
             CONSTRAINT comptes_id_forme CHECK (id ~ '^[a-z0-9][a-z0-9_-]{0,63}$'),
    -- L'adresse est une **donnée du profil**, pas la clé (doctrine §10.2 :
    -- « un utilisateur peut changer de fournisseur »). Rangée sous sa forme
    -- normalisée — minuscules, sans espaces de bord — par `normaliser_email`,
    -- que la contrainte répète pour qu'un appelant distrait se fasse
    -- refuser plutôt que cru. `btrim` ne coupe que l'espace ASCII : c'est
    -- `normaliser_email`, côté Python, qui refuse les caractères de contrôle
    -- (un saut de ligne dans une adresse est un vecteur d'injection d'en-tête
    -- de courriel).
    email    TEXT NOT NULL
             CONSTRAINT comptes_email_normalise CHECK (email = lower(btrim(email)))
             CONSTRAINT comptes_email_non_vide CHECK (length(email) > 0),
    -- Ce qui authentifie le compte : une petite indirection plutôt qu'une
    -- colonne « mot de passe » directe, parce que le mot de passe ne sera
    -- pas le seul moyen (passkey plus tard — non écrit aujourd'hui, il n'y
    -- en a pas). `methode_authentification` nomme le moyen (aujourd'hui la
    -- seule valeur possible : « mot_de_passe ») et `secret` porte sa
    -- représentation — pour un mot de passe, sel et empreinte scrypt.
    -- **Le mot de passe, lui, est toujours haché** : les gens réutilisent
    -- leurs mots de passe, et une fuite de cette base ne doit pas donner
    -- accès à autre chose qu'ourouler.
    methode_authentification TEXT,
    secret                    TEXT,
    -- Faux à la création : un compte fraîchement invité n'a **aucun** moyen
    -- de s'authentifier posé, donc aucun moyen de s'en servir. Il passe à
    -- vrai en même temps que `secret` est posé (voir la contrainte
    -- ci-dessous) et que l'invitation qui l'a créé est consommée — les trois
    -- dans la même transaction, côté `DepotComptes.activer`.
    actif    BOOLEAN NOT NULL DEFAULT false,
    cree_le  TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- **L'invariant du produit, tenu par la base et non par l'ordre dans
    -- lequel le code écrit ses colonnes** : un compte actif sans secret, ou
    -- un secret posé sur un compte resté inactif, sont deux états qui ne
    -- doivent pas pouvoir exister.
    CONSTRAINT comptes_actif_a_un_secret CHECK (
        actif = (methode_authentification IS NOT NULL AND secret IS NOT NULL)
    )
);

-- **La règle d'unicité du produit**, et elle est ici et nulle part ailleurs :
-- une adresse n'est jamais titulaire que d'un seul compte, actif ou non. Sur
-- `lower(email)` et non sur `email` : la contrainte de normalisation ci-dessus
-- rend les deux équivalents aujourd'hui, mais si elle tombait un jour, c'est
-- cet index qui continuerait de mordre.
CREATE UNIQUE INDEX IF NOT EXISTS comptes_email_unique ON comptes (lower(email));


CREATE TABLE IF NOT EXISTS invitations (
    -- **Le jeton, en clair.** Décision explicite du mainteneur : il veut
    -- pouvoir le relire et le renvoyer par le canal de son choix, ce qu'un
    -- condensé interdit. Le risque est borné autrement : une durée de vie
    -- courte (3 jours, voir `DUREE_INVITATION`) et un lien qui n'ouvre
    -- jamais qu'un compte vide. Ce jeton ne doit en revanche jamais partir
    -- dans un journal — c'est une règle de code (`InvitationEmise.__repr__`
    -- et consorts), pas une règle de schéma.
    jeton       TEXT PRIMARY KEY
                CONSTRAINT invitations_jeton_forme CHECK (jeton ~ '^[A-Za-z0-9_-]{20,255}$'),
    compte      TEXT NOT NULL REFERENCES comptes (id) ON DELETE CASCADE,
    cree_le     TIMESTAMPTZ NOT NULL,
    expire_le   TIMESTAMPTZ NOT NULL,
    consomme_le TIMESTAMPTZ,
    CONSTRAINT invitations_expire_apres_creation CHECK (expire_le > cree_le)
);

-- Au plus **une invitation non consommée** par compte, garanti par la base.
-- Choix du mainteneur : quand une invitation est déjà en cours, on n'en
-- fabrique pas une seconde — « le cas réel c'est qu'il ne l'a pas vue » — on
-- rend celle qui existe déjà (possible maintenant que le jeton est en clair).
-- Une invitation expirée reste non consommée, donc elle occupe encore la
-- place : c'est le dépôt qui la retire avant d'en poser une neuve, dans la
-- même transaction.
CREATE UNIQUE INDEX IF NOT EXISTS invitations_en_cours_unique
    ON invitations (compte) WHERE consomme_le IS NULL;


-- La table de correspondance de [[Q46]], décidée le 17/09/2026 — inchangée
-- par cette révision.
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
