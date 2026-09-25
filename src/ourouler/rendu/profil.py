"""Le profil du cycliste en JSON : `ourouler config --json` et `GET /profil`.

Une seule fonction pour les deux surfaces, et le masquage des secrets fait au
même endroit pour les deux : la ligne de commande imprime `profil_json`, l'API
(`api/vues.py`) en retire ensuite ce qui décrit la machine.

Ce module reçoit une `Config` déjà chargée ; il ne lit ni fichier ni
environnement. `config.py` réexporte `MASQUE` et `en_dict_public` à leur
ancien chemin.
"""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # Annotation seulement : le rendu (couche 4) ne dépend pas, à l'exécution,
    # de l'entrée qui charge la configuration (couche 5).
    from ourouler.config import Config

#: Ce que `en_dict_public` écrit à la place d'un secret renseigné. Une chaîne
#: fixe, jamais un compte de caractères : la longueur d'une clé est déjà une
#: information.
MASQUE = "***"


def en_dict_public(config: Config) -> dict:
    """La configuration en dictionnaire, **secrets masqués**, prête à publier.

    Existe parce que `dataclasses.asdict` ne voit que les champs : il ignore
    les `__repr__` qui masquent, et il ignore aussi les propriétés dérivées.
    Un masquage qu'on réécrit est un masquage qu'on oublie : la ligne de
    commande et l'API passent toutes deux par ici.

    Ce que cette fonction garantit, et qui se teste :

    - la clé Intervals et le mot de passe BRouter ne sortent jamais en clair ;
    - un secret absent rend une chaîne vide, pas `MASQUE` — pour qu'un écran
      puisse distinguer « non renseigné » de « renseigné, caché » ;
    - `puissance_endurance_pct`, une **propriété** dérivée de la position dans
      la zone, reste présente : sans ça elle disparaîtrait du contrat d'API
      sans que rien ne le signale.

    Ce qui n'est **pas** un secret et sort en clair : l'URL du serveur BRouter
    et l'identifiant d'athlète Intervals — une adresse et un identifiant,
    publiables.
    """
    d = dataclasses.asdict(config)
    d["intervals"]["api_key"] = MASQUE if config.intervals.api_key else ""
    d["brouter"]["mot_de_passe"] = MASQUE if config.brouter.mot_de_passe else ""
    d["seance"]["puissance_endurance_pct"] = config.seance.puissance_endurance_pct
    return d


def profil_json(config: Config) -> dict:
    """La configuration en JSON, **clé et mot de passe masqués**.

    C'est la forme que rend `ourouler config --json`, et c'est donc le profil
    que l'API sert au front : une seule fonction, un seul contrat, et le
    masquage des secrets fait au même endroit pour les deux.
    """
    d = en_dict_public(config)
    # Troisième valeur de l'écran de FTP : `None` si la config ne porte aucun vélo.
    d["seance"]["vitesse_compteur"] = info_vitesse_compteur(config)
    return d


def info_vitesse_compteur(config: Config) -> dict | None:
    """La troisième valeur de l'écran de FTP — **déléguée**, jamais recalculée.

    Ces valeurs ont une seule implémentation, `seance.ecran_ftp.valeurs_liees`,
    que `GET /profil/zones` sert en entier. Ce qui est gardé ici : le
    **sous-ensemble** de champs que `ourouler config --json` publiait déjà,
    pour ne pas élargir son contrat au passage.

    `None` si la configuration ne porte aucun vélo : rien à calculer, et
    `ourouler config` doit rester utilisable sans vélo déclaré.
    """
    # Import différé : `config.py` réexporte ce module, et `seance.ecran_ftp`
    # importe encore `config.py` (dette du lot 7) ; l'importer au chargement
    # fermerait une boucle d'import à l'exécution.
    from ourouler.seance.ecran_ftp import valeurs_liees

    completes = valeurs_liees(config)
    if completes is None:
        return None
    gardes = (
        "velo",
        "puissance_endurance_w",
        "vitesse_a_plat_kmh",
        "moyenne_compteur_kmh",
        "facteur_compteur",
        # Mesuré sur l'historique, ou dérivé d'une sortie de référence
        # supposée. Tout écran qui l'affiche doit le dire.
        "facteur_mesure",
    )
    return {cle: completes[cle] for cle in gardes}


__all__ = ["MASQUE", "en_dict_public", "info_vitesse_compteur", "profil_json"]
