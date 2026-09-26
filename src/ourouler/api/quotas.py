"""Quotas journaliers par compte hébergé, contre le poste Open-Meteo partagé.

Doctrine §10.1 : Open-Meteo gratuit tolère ~10 000 appels par jour et par
adresse IP, et **un service hébergé les additionne pour tous ses comptes** —
une « sortie » à cinq candidates en coûte à elle seule ~150 (`1 + 2 ×
candidates` requêtes de 14 points), et `GET /meteo` (une couronne, deux
modèles) ~50. Le cache mutualisé des prévisions
(`ourouler.meteo.cache_previsions`) réduit ce coût quand plusieurs comptes
cherchent le même point à la même heure ; il ne l'annule pas — deux comptes
qui cherchent chacun un point différent le paient chacun, **et grouper
plusieurs points dans une requête n'économise aucun appel décompté : Open-
Meteo compte par coordonnée, pas par requête** (doctrine §10.1) : `GET
/meteo` n'est donc pas « groupé donc gratuit », il a son quota.
Le quota est le second levier — contre un compte, malveillant ou simplement
maladroit (un bouton qu'on martèle), qui épuiserait à lui seul le poste
partagé.

**Deux compteurs distincts, parce que deux coûts très différents** :

- `Quotas` (générations) borne `POST /sorties` et `POST /boucles` — les deux
  routes qui font tourner plusieurs candidates, ~150 appels chacune.
- `Quotas` (consultations météo, second `Quotas` construit avec son propre
  plafond) borne `GET /meteo` — ~50 appels, un seul aller-retour groupé, mais
  pas gratuit pour autant. `POST /simulations` et `GET /vent-depart` restent
  hors quota : le premier appelle Open-Meteo le long d'un tracé déjà connu
  (pas de fan-out de candidates), le second est **un** point et **une**
  heure, le poste le moins cher du produit (doctrine §10.1). À revoir si
  l'usage montre qu'ils pèsent, eux aussi.

Même code d'erreur pour les deux (`CODE_QUOTA_ATTEINT`, 429) : le front n'a
qu'un écran à savoir dessiner (`Echec.tsx`), et le message dit lequel des
deux plafonds est atteint (`Quotas.libelle`).

**Un crédit consommé qui ne sert à rien est rendu.** `consommer` décompte
*avant* le travail (fail fast : un compte au plafond ne doit rien coûter au
serveur) ; si la génération échoue ensuite — `calcul_en_cours` (409), une
panne BRouter ou Open-Meteo, n'importe quelle exception — `api/routes/`
appelle `rembourser` pour annuler ce décompte. Seul un aller-retour qui
aboutit consomme réellement le quota ; sinon un compte qui a la malchance de
tomber sur BRouter en panne trois fois de suite perdrait trois crédits pour
rien.

**Le mode personnel n'a pas de quota.** `api/routes/` n'appelle ni
`consommer` ni `rembourser` quand `ctx.session.mode == MODE_PERSONNEL` : un
cycliste chez lui (`ourouler api`) appelle Open-Meteo depuis sa propre
adresse IP, sans rien de partagé (doctrine §10.1, « en CLI, chacun appelle
depuis sa propre adresse : aucun sujet »).

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

#: Le plafond par défaut des **générations** (`POST /sorties`,
#: `POST /boucles`), réglable côté service (`[quotas] generations_par_jour`
#: de `service.toml`, lue par `api/exploitation.py`). **20**, pas plus :
#: 20 générations × ~150 appels = ~3 000, sur les 10 000 que tout le service
#: partage par jour et par adresse IP — de la place reste pour les
#: consultations météo (plafond séparé, ci-dessous) et pour les autres
#: comptes du même service. Un compte personnel n'est de toute façon pas
#: concerné (voir la docstring du module).
GENERATIONS_PAR_JOUR_DEFAUT = 20

#: Le plafond par défaut des **consultations météo** (`GET /meteo`),
#: réglable via `[quotas] consultations_meteo_par_jour`. ~50 appels chacune :
#: 100 × 50 = ~5 000, qui s'ajoutent aux ~3 000 du plafond de générations
#: sans dépasser le budget partagé à elles deux pour un compte qui les
#: userait toutes les deux à fond le même jour.
CONSULTATIONS_METEO_PAR_JOUR_DEFAUT = 100

#: Le plafond des **calibrations** (`POST /calibrations`), compteur
#: séparé des deux autres. **Une** par jour et par compte : une calibration
#: relit toutes les sorties du compte et demande l'archive météo de chaque
#: jour de sortie jamais vu (une fois dans la vie du cache partagé, mais ~150
#: appels au premier passage d'un historique de 150 jours) — et refaire la
#: même le même jour ne change rien au résultat. Remboursée si elle échoue.
CALIBRATIONS_PAR_JOUR_DEFAUT = 1

#: Le plafond des **imports d'historique** (`POST /activites/import`),
#: compteur séparé. Ce n'est pas
#: Open-Meteo qui paie ici, c'est le serveur : jusqu'à 750 Mo reçus, écrits,
#: décompressés et relus par import. **5** : de quoi déposer une archive en
#: plusieurs fois ou recommencer après une erreur de fichier, pas de
#: quoi occuper le serveur toute la journée. Remboursé si l'import échoue.
IMPORTS_PAR_JOUR_DEFAUT = 5

#: Le code d'erreur du contrat (`api/erreurs.CODES_PANNE`, `Echec.tsx`) —
#: partagé par les deux quotas : le front n'a qu'un écran à dessiner, le
#: message dit lequel des deux plafonds est atteint.
CODE_QUOTA_ATTEINT = "quota_atteint"


def _minuit_suivant(maintenant: datetime) -> datetime:
    """Le prochain minuit UTC après `maintenant` — quand le quota se libère."""
    lendemain = (maintenant.date()) + timedelta(days=1)
    return datetime(lendemain.year, lendemain.month, lendemain.day, tzinfo=UTC)


@dataclass
class Quotas:
    """Compte, pour un poste donné, ce qu'un compte a consommé aujourd'hui.

    Une instance par poste (générations, consultations météo) — `libelle`
    distingue les deux dans le message d'erreur, `CODE_QUOTA_ATTEINT` reste
    le même pour les deux.

    `horloge` est injectable : les tests avancent le jour sans attendre
    minuit, exactement comme `Budgets.fenetre` se règle sans mesurer de
    vraies exécutions.
    """

    plafond: int = GENERATIONS_PAR_JOUR_DEFAUT
    #: Le mot que le message d'erreur emploie — « générations » ou
    #: « consultations météo ». Purement cosmétique : ne participe à aucune
    #: clé, aucune décision.
    libelle: str = "générations"
    horloge: Callable[[], datetime] = field(default=lambda: datetime.now(UTC))
    _verrou: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)
    _compteurs: dict[tuple[str, date], int] = field(default_factory=dict, repr=False, compare=False)

    def refuser_si_epuise(self, proprietaire: Proprietaire) -> None:
        """Le refus de `consommer`, sans rien décompter — pour refuser **avant** un travail.

        Sert à `api/garde_avant_corps.py`, qui refuse un import avant d'en lire
        le corps ; le décompte, lui, reste fait par la route, une fois le corps
        reçu.
        """
        maintenant = self.horloge()
        with self._verrou:
            deja = self._compteurs.get((str(proprietaire), maintenant.date()), 0)
        if deja >= self.plafond:
            raise self._refus(maintenant)

    def _refus(self, maintenant: datetime) -> ErreurApi:
        liberation = _minuit_suivant(maintenant)
        return ErreurApi(
            code=CODE_QUOTA_ATTEINT,
            message=(
                f"quota journalier de {self.plafond} {self.libelle} atteint pour ce "
                f"compte — ça se libère à {liberation.strftime('%H:%M')} UTC"
            ),
            statut=429,
            details={
                "plafond": self.plafond,
                "reinitialisation_utc": liberation.isoformat(),
            },
        )

    def consommer(self, proprietaire: Proprietaire) -> None:
        """Décompte un crédit pour ce compte, ou refuse — jamais les deux.

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
                raise self._refus(maintenant)
            self._compteurs[cle] = deja + 1

    def rembourser(self, proprietaire: Proprietaire) -> None:
        """Annule un décompte qui n'a servi à rien — la génération a échoué.

        Sans effet si le jour a changé entre `consommer` et `rembourser`
        (une requête à cheval sur minuit, en pratique jamais vu) : il n'y a
        alors plus rien à rembourser sur le compteur d'aujourd'hui, et
        rembourser celui d'hier n'aurait aucun sens. Sans effet aussi si le
        compte n'a rien consommé aujourd'hui (rien à annuler).
        """
        maintenant = self.horloge()
        cle = (str(proprietaire), maintenant.date())
        with self._verrou:
            if cle in self._compteurs:
                self._compteurs[cle] = max(0, self._compteurs[cle] - 1)

    def restant(self, proprietaire: Proprietaire) -> int:
        """Combien de crédits restent aujourd'hui pour ce compte (`/systeme`)."""
        maintenant = self.horloge()
        cle = (str(proprietaire), maintenant.date())
        with self._verrou:
            return max(0, self.plafond - self._compteurs.get(cle, 0))


__all__ = [
    "CALIBRATIONS_PAR_JOUR_DEFAUT",
    "CODE_QUOTA_ATTEINT",
    "CONSULTATIONS_METEO_PAR_JOUR_DEFAUT",
    "GENERATIONS_PAR_JOUR_DEFAUT",
    "IMPORTS_PAR_JOUR_DEFAUT",
    "Quotas",
]
