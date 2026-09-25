"""Quota journalier de générations coûteuses par compte hébergé (lot L9.3).

Doctrine §10.1 : Open-Meteo gratuit tolère ~10 000 appels par jour et par
adresse IP, et **un service hébergé les additionne pour tous ses comptes** —
une « sortie » à cinq candidates en coûte à elle seule ~150. Le cache
mutualisé des prévisions (`ourouler.meteo.cache_previsions`) réduit ce coût
quand plusieurs comptes cherchent le même point à la même heure ; il ne
l'annule pas : deux comptes qui cherchent chacun un point différent le
paient chacun. Le quota est le second levier — contre un compte, malveillant
ou simplement maladroit (un bouton « chercher » qu'on martèle), qui
épuiserait à lui seul le poste partagé.

**Ce qui est compté : une « génération »**, au sens du produit — un appel à
`POST /sorties` ou `POST /boucles`, les deux routes qui font tourner
plusieurs candidates, chacune avec son aller-retour BRouter et Open-Meteo
(doctrine §10.1). Les autres routes météo (`GET /meteo`, `GET /vent-depart`,
`POST /simulations`) font un seul aller-retour groupé, sans "rafale" de
candidates : elles ne sont pas comptées ici. À revoir si l'usage montre
qu'elles pèsent, elles aussi — rien ne l'indique aujourd'hui.

**Le mode personnel n'a pas de quota.** `api/routes.py` n'appelle `Quotas`
que lorsque `ctx.session.mode != MODE_PERSONNEL` : un cycliste chez lui
(`ourouler api`) appelle Open-Meteo depuis sa propre adresse IP, sans rien de
partagé (doctrine §10.1, « en CLI, chacun appelle depuis sa propre adresse :
aucun sujet »).

**Stockage : en mémoire du processus, par (compte, jour UTC).** Même choix,
pour la même raison, que `Budgets` (`api/adaptateur.py`) : un compteur qui
sert à limiter un abus, pas à facturer, n'a pas besoin de survivre à un
redémarrage — et le service tourne aujourd'hui en un seul processus
(`deploiement/api/entrypoint.py` ne lance qu'un `uvicorn.run`). Si le service
passe un jour à plusieurs processus ou plusieurs instances, le quota devient
*par instance* : c'est une dégradation vers plus strict (chaque instance
reste sous le plafond, leur somme peut le dépasser), jamais une fuite — à
revoir alors, pas avant.

**Le jour se compte en UTC**, pas dans le fuseau d'un compte : un seul repère
pour tous, quel que soit le fuseau depuis lequel on roule.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

from ourouler.api.erreurs import ErreurApi
from ourouler.api.proprietaire import Proprietaire

#: Le plafond par défaut, réglable côté service (section `[quotas]` de
#: `service.toml`, lue par `api/exploitation.py`). Choisi large pour un usage
#: personnel intensif (plusieurs recherches, plusieurs relances dans la même
#: journée) et étroit devant ce qu'un seul compte pourrait tirer du quota
#: Open-Meteo partagé avant d'en priver les autres (10 000 appels / jour ÷
#: ~150 par génération ≈ 66 générations, tous comptes confondus).
GENERATIONS_PAR_JOUR_DEFAUT = 40

#: Le code d'erreur du contrat (`api/erreurs.CODES_PANNE`, `Echec.tsx`).
CODE_QUOTA_ATTEINT = "quota_atteint"


def _minuit_suivant(maintenant: datetime) -> datetime:
    """Le prochain minuit UTC après `maintenant` — quand le quota se libère."""
    lendemain = (maintenant.date()) + timedelta(days=1)
    return datetime(lendemain.year, lendemain.month, lendemain.day, tzinfo=UTC)


@dataclass
class Quotas:
    """Compte les générations d'aujourd'hui par compte, et refuse au-delà.

    `horloge` est injectable : les tests avancent le jour sans attendre
    minuit, exactement comme `Budgets.fenetre` se règle sans mesurer de
    vraies exécutions.
    """

    plafond: int = GENERATIONS_PAR_JOUR_DEFAUT
    horloge: Callable[[], datetime] = field(default=lambda: datetime.now(UTC))
    _verrou: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)
    _compteurs: dict[tuple[str, date], int] = field(
        default_factory=dict, repr=False, compare=False
    )

    def consommer(self, proprietaire: Proprietaire) -> None:
        """Décompte une génération pour ce compte, ou refuse — jamais les deux.

        Purge, au passage, les compteurs d'un jour révolu : `Quotas` ne garde
        que le jour courant en mémoire, ce qui vaut à la fois la remise à
        zéro du lendemain et une borne naturelle sur sa taille.
        """
        maintenant = self.horloge()
        aujourdhui = maintenant.date()
        cle = (str(proprietaire), aujourdhui)
        with self._verrou:
            for perimee in [c for c in self._compteurs if c[1] != aujourdhui]:
                del self._compteurs[perimee]
            deja = self._compteurs.get(cle, 0)
            if deja >= self.plafond:
                liberation = _minuit_suivant(maintenant)
                raise ErreurApi(
                    code=CODE_QUOTA_ATTEINT,
                    message=(
                        f"quota journalier de {self.plafond} générations atteint pour ce "
                        f"compte — ça se libère à {liberation.strftime('%H:%M')} UTC"
                    ),
                    statut=429,
                    details={
                        "plafond": self.plafond,
                        "reinitialisation_utc": liberation.isoformat(),
                    },
                )
            self._compteurs[cle] = deja + 1

    def restant(self, proprietaire: Proprietaire) -> int:
        """Combien de générations restent aujourd'hui pour ce compte (`/systeme`)."""
        maintenant = self.horloge()
        cle = (str(proprietaire), maintenant.date())
        with self._verrou:
            return max(0, self.plafond - self._compteurs.get(cle, 0))


__all__ = ["CODE_QUOTA_ATTEINT", "GENERATIONS_PAR_JOUR_DEFAUT", "Quotas"]
