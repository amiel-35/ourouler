-- Les demandes d'invitation déposées depuis le site public.
-- Sprint 12, 27/09/2026. Doctrine §10.2 (révisée le 26/09/2026) : le
-- formulaire public de demande d'invitation est autorisé, mais une demande
-- n'ouvre jamais de compte seule — elle attend un clic « Accepter » dans
-- l'administration, qui rejoue `services.comptes.inviter()` tel quel.
--
-- Cette table ne se modifie jamais (comme 0001 et 0002) : un ajustement
-- futur est une migration numérotée de plus.
--
-- **Pas de colonne d'état.** Une demande existe = elle est en attente ;
-- « refuser » l'efface (aucune trace gardée, aucune fuite d'information à
-- l'auteur : doctrine du formulaire) ; « accepter » l'efface aussi, dès que
-- l'invitation est émise — la ligne ne sert qu'à faire la queue, pas à
-- garder un historique.
--
-- **Pas d'adresse IP ici.** Le débit (par IP et global) se limite en
-- mémoire du processus API, sur le modèle d'`api/quotas.py` — un compteur
-- d'abus n'a pas besoin de survivre à un redémarrage, et ranger une adresse
-- IP en base serait une donnée personnelle de plus à protéger pour un
-- bénéfice nul (le compteur est déjà purgé chaque jour).
--
-- **Pas de contrainte d'unicité sur l'adresse.** Une même adresse peut
-- déposer plusieurs demandes au fil du temps (elle a pu être refusée puis
-- redemander) ; l'administration voit la file telle qu'elle est, à elle de
-- juger.

CREATE TABLE IF NOT EXISTS demandes_invitation (
    -- Identifiant opaque à nous, même forme que `comptes.id` — sert de clé
    -- dans les routes d'administration (« accepter cette demande-ci »).
    id       TEXT PRIMARY KEY
             CONSTRAINT demandes_invitation_id_forme CHECK (id ~ '^[a-z0-9][a-z0-9_-]{0,63}$'),
    -- Même normalisation que `comptes.email` (`normaliser_email`) : minuscules,
    -- sans espace de bord, aucun caractère de contrôle (vecteur d'injection
    -- d'en-tête de courriel).
    email    TEXT NOT NULL
             CONSTRAINT demandes_invitation_email_normalise CHECK (email = lower(btrim(email)))
             CONSTRAINT demandes_invitation_email_non_vide CHECK (length(email) > 0)
             CONSTRAINT demandes_invitation_email_borne CHECK (length(email) <= 320),
    -- « Un mot » facultatif — borné, texte brut, jamais interprété (ni HTML,
    -- ni Markdown) : composé dans le courriel d'alerte par `EmailMessage`,
    -- jamais par concaténation, comme `courriel.message_invitation`.
    message  TEXT
             CONSTRAINT demandes_invitation_message_borne CHECK (message IS NULL OR length(message) <= 500),
    cree_le  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- La file s'affiche des plus anciennes aux plus récentes (les plus anciennes
-- sont les plus urgentes à traiter) : index sur la date, pas une exigence
-- d'unicité.
CREATE INDEX IF NOT EXISTS demandes_invitation_cree_le ON demandes_invitation (cree_le);
