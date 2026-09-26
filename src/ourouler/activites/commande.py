"""Cas d'usage `ourouler inventaire` : importer, synchroniser, puis compter.

Reçoit une `DemandeInventaire` déjà interprétée par l'entrée
(`commandes/inventaire.py`) et un `Contexte` ; ne lit aucun fichier de
configuration, n'affiche jamais de clé, n'imprime rien : il rend
l'inventaire et le journal de ce qu'il a fait.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

from ourouler.activites.cache import Cache
from ourouler.activites.inventaire import Inventaire, inventaire
from ourouler.noyau.erreurs import ErreurUtilisateur
from ourouler.noyau.profil import Profil
from ourouler.services.contexte import Contexte


@dataclass(frozen=True)
class DemandeInventaire:
    """Depuis quand compter, et ce qu'il faut faire entrer dans le cache avant."""

    depuis: date
    importer: Path | None = None
    synchroniser: bool = False
    rafraichir_meta: bool = True


@dataclass(frozen=True)
class ResultatInventaire:
    """L'inventaire, et les lignes du journal d'import et de synchronisation."""

    inventaire: Inventaire
    journal: tuple[str, ...] = ()


def executer(
    demande: DemandeInventaire, contexte: Contexte, cache: Cache | None = None
) -> ResultatInventaire:
    """Exécute `ourouler inventaire`.

    **`cache` s'injecte, exactement comme un client HTTP** (règle 3 de
    CLAUDE.md, et c'est déjà la forme de `client_brouter` dans
    `apprentissage/commande.py`). Absent — le cas de la ligne de commande —
    le service le construit sur `contexte.dossier_cache` et avec le
    propriétaire par défaut.

    C'est ce qui tient la décision Q58
    (`docs/journal/questions/questions_mainteneur.md`) sans faire entrer la
    notion de service dans le cœur : le service reçoit un dépôt déjà fait et ne
    prononce jamais le mot
    « propriétaire ». Le seul endroit qui le prononce est l'appelant — pour
    l'API, `api/routes/`, qui construit
    `Cache(config.cache.dossier, proprietaire=str(qui))`, exactement comme
    `api/vie_privee.py` le fait déjà. Doctrine §10.1 : « le propriétaire entre
    au constructeur du dépôt, et nulle part ailleurs […] en hébergé, c'est la
    couche web qui construira le dépôt avec l'identifiant de l'utilisateur
    authentifié ».
    """
    cache = cache if cache is not None else Cache(contexte.dossier_cache)
    journal: list[str] = []

    if demande.importer:
        ajoutes = cache.indexer_dossier(demande.importer)
        journal.append(f"Import de {demande.importer} : {ajoutes} activité(s) ajoutée(s).")
        for echec in cache.echecs:
            journal.append(f"  ignoré — {echec}")

    if demande.synchroniser:
        journal.extend(
            _synchroniser(
                cache, contexte.profil, demande.depuis, rafraichir_meta=demande.rafraichir_meta
            )
        )

    return ResultatInventaire(
        inventaire=inventaire(cache, contexte.profil, demande.depuis), journal=tuple(journal)
    )


def date_depuis(brut: str | None, defaut: date) -> date:
    """`--depuis` en date ; absent, le début de l'historique du profil."""
    if not brut:
        return defaut
    try:
        return date.fromisoformat(brut)
    except ValueError as e:
        raise ErreurUtilisateur(f"--depuis : date AAAA-MM-JJ attendue, reçu « {brut} »") from e


def _synchroniser(
    cache: Cache, profil: Profil, depuis: date, *, rafraichir_meta: bool = True
) -> list[str]:
    """Rapatrie les activités Intervals.icu manquantes. Import paresseux : le
    connecteur n'est chargé que si on s'en sert."""
    if not profil.intervals.renseigne:
        raise ErreurUtilisateur(
            "--synchroniser : [intervals] athlete_id et api_key doivent être "
            "renseignés dans la configuration (Intervals.icu → Settings → Developer)"
        )
    from ourouler.connecteurs.intervals import ClientIntervals, synchroniser

    client = ClientIntervals(profil.intervals.athlete_id, profil.intervals.api_key)
    rapport = synchroniser(client, cache, depuis, rafraichir_meta=rafraichir_meta)
    journal = [
        f"Synchronisation Intervals.icu depuis le {depuis.isoformat()} : "
        f"{rapport.vues} vue(s), {rapport.ajoutees} ajoutée(s), "
        f"{rapport.ignorees} déjà en cache (dont {rapport.mises_a_jour} "
        f"métadonnées mises à jour), {rapport.autres_sports} autre(s) sport(s), "
        f"{rapport.sans_contenu} sans contenu, {rapport.echecs} échec(s)."
    ]
    journal.extend(f"  échec — {m}" for m in rapport.messages)
    return journal
