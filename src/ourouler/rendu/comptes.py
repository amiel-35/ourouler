"""Ce que les commandes de comptes affichent, en texte et en JSON.

`ourouler inviter`, `reinitialiser`, `invitations` et `retirer` : `cli.py` imprime
ces chaînes telles quelles. **Le lien s'affiche toujours**, que le courriel parte
ou non — l'exploitant doit pouvoir le relire et le renvoyer par un autre canal.
"""

from __future__ import annotations

import json
from datetime import UTC

from ourouler.services.comptes import InvitationListee, LienEmis, Retrait


def _echeance(instant) -> str:
    return instant.astimezone(UTC).strftime("%d/%m/%Y")


def texte_lien_emis(resultat: LienEmis) -> str:
    """Le résultat d'`inviter` ou de `reinitialiser`, en lignes lisibles."""
    if resultat.emise.deja_en_cours:
        entete = "ourouler : invitation déjà en cours — le même jeton est repris, rien n'est émis à neuf"
    else:
        entete = "ourouler : invitation créée"
    return "\n".join(
        (
            entete,
            f"lien           : {resultat.lien}",
            f"valable jusqu'au {_echeance(resultat.emise.invitation.expire_le)}",
            "courriel envoyé" if resultat.courriel_envoye else "courriel non envoyé (--sans-courriel)",
        )
    )


def json_lien_emis(resultat: LienEmis) -> str:
    """Le résultat d'`inviter` ou de `reinitialiser`, en JSON (`--json`)."""
    return json.dumps(
        {
            "lien": resultat.lien,
            "expire_le": resultat.emise.invitation.expire_le.isoformat(),
            "deja_en_cours": resultat.emise.deja_en_cours,
            "courriel_envoye": resultat.courriel_envoye,
        },
        ensure_ascii=False,
        indent=2,
    )


def texte_invitations(invitations: list[InvitationListee]) -> str:
    """Une ligne par invitation en cours, ou la phrase qui dit qu'il n'y en a aucune."""
    if not invitations:
        return "ourouler : aucune invitation en cours"
    return "\n".join(
        f"{invitation.adresse} — {invitation.lien} — valable jusqu'au {_echeance(invitation.expire_le)}"
        for invitation in invitations
    )


def json_invitations(invitations: list[InvitationListee]) -> str:
    """Les invitations en cours en JSON (`--json`) ; une liste vide s'écrit `[]`."""
    return json.dumps(
        [
            {
                "adresse": invitation.adresse,
                "lien": invitation.lien,
                "expire_le": invitation.expire_le.isoformat(),
            }
            for invitation in invitations
        ],
        ensure_ascii=False,
        indent=2,
    )


def question_retrait(adresse: str) -> str:
    """La question posée avant de retirer un compte, sans `--oui`."""
    return (
        f"Supprimer définitivement le compte {adresse} et toutes ses données "
        "personnelles (profil, fichiers déposés ou générés, cache d'activités) ? "
        "Les routes apprises de ses sorties resteront, collectives (doctrine §10.2). "
        "[o/N] "
    )


#: Ce que `retirer` écrit sur la sortie d'erreur quand la confirmation n'est pas donnée.
RETRAIT_ANNULE = "ourouler : annulé — rien n'a été supprimé"


def texte_retrait(retrait: Retrait) -> str:
    """Le bilan d'un retrait : ce qui est supprimé, et ce qui reste, collectif."""
    lignes = [f"ourouler : compte {retrait.adresse} retiré"]
    lignes += [f"  {cle} : {valeur}" for cle, valeur in retrait.donnees["supprime"].items()]
    lignes.append("conservé (collectif, doctrine §10.2) : routes apprises")
    return "\n".join(lignes)


def json_retrait(retrait: Retrait) -> str:
    """Le bilan d'un retrait en JSON (`--json`)."""
    return json.dumps({"adresse": retrait.adresse, **retrait.donnees}, ensure_ascii=False, indent=2)


__all__ = [
    "RETRAIT_ANNULE",
    "json_invitations",
    "json_lien_emis",
    "json_retrait",
    "question_retrait",
    "texte_invitations",
    "texte_lien_emis",
    "texte_retrait",
]
