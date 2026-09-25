"""Profil du cycliste : les objets que le domaine reçoit, sans rien lire.

Le cycliste, ses vélos, son point de départ, ses préférences de météo, de
boucle, de séance, de tenue et de calibration, ses zones à éviter et les
accès aux services (Intervals, BRouter). Rangés au noyau (lot 4) pour que le
domaine les connaisse sans importer `config.py`, qui lit le TOML et
l'environnement, les compose dans `Config` et les réexporte.

Reste dans `config.py` ce qui touche à la machine ou au chargement :
`ParametresCache` (son dossier par défaut se résout depuis le répertoire de
l'utilisateur), `Config` qui le contient, et les bornes de validation.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Protocol

from ourouler.noyau.seance import ZONES_PUISSANCE_DEFAUT
from ourouler.noyau.zones import POSITION_ENDURANCE_DEFAUT, puissance_endurance_pct

#: Nombres de directions acceptés pour la couronne. Défini ici, et non dans
#: `meteo.couronne`, pour que la validation ait lieu au chargement : c'est
#: `config.py` qui doit nommer le champ fautif. `couronne.py` le réimporte.
DIRECTIONS_ACCEPTEES = (8, 16)

#: Horizon maximal accepté, en heures : au-delà, AROME HD n'a plus rien à dire.
HORIZON_MAX_H = 48

#: Jusqu'à combien de jours en avant on accepte de demander une météo pour un
#: parcours (Q40 a). **Mesuré le 17/09/2026 sur le vrai service**, depuis un
#: point français, avec les deux modèles par défaut : AROME HD rendait sa
#: dernière valeur le 19/09 à 03 h (J+2), `icon_seamless` le 24/09 à 12 h
#: (J+7). C'est donc le **modèle de repli** qui fixe la portée du produit.
#:
#: Réglable parce que la portée appartient au modèle et non au projet :
#: quelqu'un qui configure un autre second avis a un autre horizon, et un
#: chiffre en dur mentirait pour lui. Au-delà, le parcours est servi et la
#: météo déclarée absente sans qu'Open-Meteo soit appelé (`meteo.portee`).
HORIZON_JOURS_DEFAUT = 7


@dataclass(frozen=True)
class Depart:
    nom: str
    latitude: float
    longitude: float


@dataclass(frozen=True)
class Cycliste:
    masse_kg: float
    #: La puissance seuil, en watts. **Facultative depuis le 19/09/2026**
    #: (`docs/ux/parcours_accueil.md`) : ce que quelqu'un donne à l'accueil —
    #: « je roule à 25 de moyenne » — est sa puissance d'**endurance**, pas
    #: son seuil, et rien n'oblige plus à en connaître un pour avoir un
    #: profil qui tourne. `None` veut dire « pas encore établie » : les zones
    #: en watts ne se calculent pas (`seance.ecran_ftp`), mais le reste du
    #: cœur (terrain, lecture de séance ZWO/MRC) sait déjà fonctionner sans
    #: (`seance/terrain.py`, `seance/zwo.py`, conçus pour ça avant même ce
    #: changement). Quand elle est donnée, la borne [50, 1000] W reste celle
    #: d'avant — une FTP hors de cette plage est toujours une faute de
    #: frappe, pas une valeur rare.
    ftp_w: float | None = None

    #: Identité du compte. Décision du mainteneur (17/09/2026, Q36) : « nom
    #: prénom obligatoire car c'est la base, voilà, point. » L'assistant de
    #: configuration **est** la création du profil (Q36) — il n'y a pas
    #: d'étape « identité » séparée des autres — et il refuse maintenant de
    #: continuer sans les deux, au même titre que sans point de départ.
    #:
    #: **Optionnels ici, dans le cœur, et c'est volontaire.** L'obligation est
    #: une règle de *parcours* (l'assistant), pas une règle de *chargement* :
    #: une configuration écrite avant ce lot — celle du mainteneur comprise —
    #: ne porte ni l'un ni l'autre, et doit continuer à se charger et à se
    #: modifier (FTP, poids, vélos, tout le reste) sans qu'on lui invente un
    #: nom. Même traitement que la migration `puissance_endurance_pct` →
    #: `position_zone` (`config._position_zone`) et que la colonne
    #: propriétaire des dépôts (`api/depots.py`) : ce qui existait déjà
    #: continue de tourner, la nouvelle règle s'applique à ce qui s'écrit à
    #: partir de maintenant. Une valeur absente reste une chaîne vide, jamais
    #: un nom inventé — la règle absolue 1 l'interdirait de toute façon.
    #:
    #: **Aucun calcul du cœur ne s'en sert aujourd'hui** — ni le modèle
    #: physique, ni les zones, ni la tenue (règle absolue 5 : on n'affirme pas
    #: un usage qui n'existe pas). L'usage réel attend le lot F3 des comptes
    #: multi-utilisateurs : l'e-mail d'invitation et l'affichage d'un compte
    #: parmi plusieurs. Jusque-là, c'est une donnée de compte pure.
    prenom: str = ""
    nom: str = ""


@dataclass(frozen=True)
class Periode:
    """Intervalle de dates pendant lequel un vélo a servi. `fin` None = encore en service."""

    debut: date
    fin: date | None = None

    def contient(self, jour: date) -> bool:
        return self.debut <= jour and (self.fin is None or jour <= self.fin)


@dataclass(frozen=True)
class Velo:
    nom: str
    usage: str = "route"
    masse_kg: float | None = None
    cda_m2: float | None = None
    #: Coefficient de roulement. Écrit à la main, il est **respecté et figé**
    #: par `ourouler calibrer`, comme celui d'un pneu (L9.1) : seul le CdA est
    #: alors cherché.
    crr: float | None = None
    intervals_gear: str = ""
    intervals_gear_id: str = ""
    capteur_puissance: str = ""  # valeur exacte du champ Intervals `power_meter`, ex. « MARQUE 1234 »
    periodes: tuple[Periode, ...] = ()

    #: Rapport entre la moyenne d'une vraie sortie — distance divisée par le
    #: **temps écoulé**, arrêts compris — et la vitesse à plat, sans vent,
    #: lancé, que le modèle prédit à la même puissance. C'est la troisième
    #: valeur de l'écran de FTP (décision 8 du cycle UX) : celle qui empêche
    #: quelqu'un de saisir sa moyenne de compteur dans le champ « à plat » et
    #: de décaler tout son escalier de zones.
    #:
    #: **Par vélo, et non par cycliste** : le chrono et la route n'ont ni la
    #: même aérodynamique ni les mêmes parcours, et la mesure du 16/09/2026 les
    #: sépare de trois points. **Réglage utilisateur, et non constante** : le
    #: facteur dépend de la masse du cycliste autant que de ses routes, et un
    #: chiffre écrit en dur serait celui d'un seul homme.
    #:
    #: `None` — le cas d'un vélo neuf ou d'un utilisateur sans historique —
    #: fait tomber le cœur sur `physique.modele.facteur_compteur_defaut`, qui
    #: le dérive du modèle et de la masse sur une sortie de référence. C'est
    #: une supposition, pas une mesure, et l'écran doit le dire. La mesure se
    #: fait avec `tests/validation/facteur_compteur_retrospectif.py`.
    facteur_compteur: float | None = None

    #: La catégorie de pneu (une des `config.PNEUS_VELO`), ou `None`. Elle donne le
    #: Crr du vélo par la littérature (`physique.litterature.PNEUS`) : la
    #: calibration le garde alors fixe et ne cherche que le CdA (L9.1). Sans
    #: pneu, rien ne change — le Crr vient du jeu de l'usage, et la
    #: calibration ajuste les deux.
    pneu: str | None = None


@dataclass(frozen=True)
class ParametresMeteo:
    directions: int = 8
    distances_km: tuple[float, ...] = (15.0, 25.0, 40.0)
    modele: str = "meteofrance_arome_france_hd"
    second_avis: str = "icon_seamless"
    horizon_h: int = 6
    #: Jusqu'à combien de jours en avant on accepte de demander une météo
    #: (Q40 a). Au-delà, le parcours est servi et la météo déclarée absente,
    #: **sans appeler Open-Meteo** — voir `meteo.portee`. La valeur par défaut
    #: est celle du modèle de repli, mesurée sur le vrai service.
    horizon_jours: int = HORIZON_JOURS_DEFAUT


@dataclass(frozen=True, repr=False)
class ParametresIntervals:
    """`repr` explicite (d'où `repr=False` sur la dataclass) : la clé ne doit jamais s'imprimer.

    Une trace pytest (`-l`), un futur log de contexte ou un `print(config)`
    suffirait à publier la clé d'API si le `repr` engendré était conservé.
    `Config` imprime ses champs avec leur `repr`, le masquage se propage donc.
    """

    athlete_id: str = ""
    api_key: str = ""

    @property
    def renseigne(self) -> bool:
        return bool(self.athlete_id and self.api_key)

    def __repr__(self) -> str:
        etat = "***" if self.api_key else ""
        return f"ParametresIntervals(athlete_id={self.athlete_id!r}, api_key={etat!r})"


@dataclass(frozen=True, repr=False)
class ParametresBrouter:
    """Serveur BRouter (auto-hébergé sur Coolify). Le mot de passe n'apparaît jamais dans `repr`."""

    url: str = ""
    utilisateur: str = ""
    mot_de_passe: str = ""
    profil: str = "fastbike"
    timeout_s: float = 120.0

    @property
    def renseigne(self) -> bool:
        return bool(self.url)

    def __repr__(self) -> str:
        etat = "***" if self.mot_de_passe else ""
        return (
            f"ParametresBrouter(url={self.url!r}, utilisateur={self.utilisateur!r}, "
            f"mot_de_passe={etat!r}, profil={self.profil!r}, timeout_s={self.timeout_s!r})"
        )


@dataclass(frozen=True)
class ParametresSeance:
    """Marge de placement d'une séance sur une boucle (sprint 4).

    Seules les zones 2 d'ouverture et de fermeture sont élastiques : toutes
    les récupérations font partie de la prescription et ne bougent pas.

    Les deux élasticités ne sont pas la même chose (Q14, close le 13/09/2026).
    La Z2 d'**ouverture** est le levier de placement : l'allonger fait
    coulisser les blocs jusqu'à un bon couloir, et le mainteneur a fixé sa
    fenêtre à −5 % / +20 %. Le **retour au calme**, lui, ne place rien : il
    referme une boucle dont la longueur n'est jamais exacte, et sa fenêtre est
    largement ouverte vers le haut — « le retour au calme en fait peut dépasser
    de plus, c'est souvent ce que je fais car c'est incontrôlable de faire
    parfait, et c'est du kilomètre facile. Faut réduire le dépassement au max. »
    """

    elasticite_z2_max: float = 0.20  # allongement maximal de la Z2 d'ouverture
    elasticite_z2_min: float = -0.05  # raccourcissement maximal

    #: Allongement maximal du **retour au calme** avant qu'il soit signalé
    #: comme anormal : +150 %. Ce n'est pas une autorisation de dépasser —
    #: chaque minute de dépassement se paie déjà, au prorata et sans seuil
    #: (`seance.placement.PENALITE_CALME_ALLONGE_KM_PAR_H`) — c'est la limite
    #: au-delà de laquelle le dépassement n'est plus « la boucle qui ne tombe
    #: pas juste » mais une boucle qui ne va pas avec la séance.
    elasticite_calme_max: float = 1.5
    #: Raccourcissement maximal du retour au calme, inchangé : amputer une
    #: séance reste un vrai défaut, et il se paie très cher
    #: (`seance.placement.PENALITE_SEANCE_NON_TENUE`).
    elasticite_calme_min: float = -0.05

    demi_tour_penalite: float = 1.0  # coût d'un bloc qui reprend le segment précédent à l'envers

    #: Les bornes des zones de **puissance**, en fraction de FTP, de Z1 à Z7.
    #:
    #: Éditable depuis la décision 7 du cycle UX : la table était jusque-là une
    #: constante Python que rien ne reliait à `Config`, contrairement à tous
    #: les autres réglages de séance. Le défaut est la table de Coggan
    #: (`seance/modele.ZONES_PUISSANCE_DEFAUT`), celle que le compte
    #: Intervals.icu du mainteneur renvoie au pourcent près.
    zones_pct: tuple[tuple[float, float], ...] = ZONES_PUISSANCE_DEFAUT

    #: **La position du cycliste dans sa bande**, entre 0 (bas de la zone) et
    #: 1 (haut). C'est la seule chose qu'on stocke, et c'est la décision 7 :
    #: « on stocke la position dans la zone, pas la valeur — comme ça la FTP
    #: change ou les zones décalent, on suit ». Elle se propage à toutes les
    #: zones fermées : qui se met au milieu de sa Z2 prend le milieu de sa Z3.
    #:
    #: Le défaut n'est pas un chiffre choisi mais la position qu'occupe la
    #: puissance d'endurance **mesurée** du mainteneur (0,60 de FTP, Q11) dans
    #: la Z2 de la table par défaut — de sorte que la dérivation ne change
    #: aucun comportement (règle absolue 5).
    #:
    #: Bornes de chargement : [`config.POSITION_ZONE_MINI`, `config.POSITION_ZONE_MAXI`],
    #: soit au plus une largeur de bande au-dessous ou au-dessus. Une position
    #: hors bande se voit et se dit ; elle ne se corrige pas à l'insu du
    #: cycliste (décision 8). Le chemin de migration depuis
    #: `puissance_endurance_pct` passe par **ces bornes-là** (`config._position_zone`)
    #: : ce qui se charge doit pouvoir se recharger.
    position_zone: float = POSITION_ENDURANCE_DEFAUT

    @property
    def puissance_endurance_pct(self) -> float:
        """Puissance d'endurance en fraction de FTP — **dérivée**, plus stockée.

        Elle sert de cible aux étapes prescrites en **zone de fréquence
        cardiaque basse** (Z1, Z2 de FC), dont la traduction par la table des
        zones de puissance donne un résultat faux (Q11, close le 13/09/2026).
        Depuis la décision 7 elle n'est plus un réglage : elle se lit dans la
        Z2 de `zones_pct`, à `position_zone`. C'est une
        propriété et non un champ — les appelants ne changent pas, et il n'y a
        plus deux définitions de « la Z2 » qui puissent diverger.
        """
        return puissance_endurance_pct(self.position_zone, self.zones_pct)

    #: Sous cette part de FTP, une étape n'est pas un bloc : c'est de
    #: l'échauffement, de la récupération ou du retour au calme. Dernier
    #: recours du typage, quand la séance ne porte ni marqueur ni texte —
    #: c'est le cas des séances de coach en pourcentage de FTP.
    seuil_recuperation_pct: float = 0.75

    #: Écart relatif de note de placement en dessous duquel deux boucles
    #: comptent comme équivalentes. Depuis le sprint 5 la note inclut le
    #: vent, donc deux boucles ne sont quasiment plus jamais égales au bit
    #: près : sans cette tolérance, le vent l'emporterait toujours, même sur
    #: un écart de note minuscule, et la pluie ne départagerait plus jamais
    #: comme au sprint 4. Au-dessus du seuil, c'est la note — vent compris —
    #: qui décide directement.
    #:
    #: **Ce n'est pas un réglage technique, c'est une préférence du
    #: cycliste** : « le vent doit-il faire préférer une boucle plus mouillée
    #: à une boucle plus sèche ? » Le défaut ci-dessous répond non dans le cas
    #: mesuré en L5.1 (deux boucles de même relief, seul le vent les
    #: distingue) : voir `docs/journal/sprints/sprint5_contrat.md` §1.6 pour la mesure sur
    #: les boucles réelles du mainteneur qui le justifie. 0.0 = le vent
    #: tranche toujours, sans tolérance — l'autre réponse possible.
    tolerance_egalite: float = 0.15


@dataclass(frozen=True)
class ParametresTenue:
    """Seuils de tenue. Les bornes sont en ressenti, croissantes."""

    #: très froid < 3 ; froid < 9 ; frais < 15 ; modéré < 22 ; chaud < 30 ; canicule au-delà.
    bornes_c: tuple[float, ...] = (3.0, 9.0, 15.0, 22.0, 30.0)
    #: sec < 0,2 ; humide < 0,5 ; averses < 1,0 ; pluie au-delà, en mm/h.
    bornes_pluie_mmh: tuple[float, ...] = (0.2, 0.5, 1.0)
    vent_veste_kmh: float = 30.0
    #: Tenue par catégorie de température : {"froid": ["collant", "veste"], …}.
    #: Vide = le jeu par défaut de `seance/tenue.py`. Les catégories données
    #: remplacent celles du défaut, une par une.
    tenues: tuple[tuple[str, tuple[str, ...]], ...] = ()

    def tenue_de(self, categorie: str) -> tuple[str, ...] | None:
        """Les vêtements configurés pour une catégorie, ou None si non configurée."""
        for nom, pieces in self.tenues:
            if nom == categorie:
                return pieces
        return None


@dataclass(frozen=True)
class ParametresCalibration:
    # Une sortie dont le nom contient un de ces mots est écartée de la
    # calibration (peloton). Les quatre valeurs du contrat de sprint §0 : la
    # recherche étant par sous-chaîne, « club » couvre déjà « sortie club »,
    # mais la valeur par défaut doit dire ce que le contrat écrit.
    mots_groupe: tuple[str, ...] = ("club", "groupe", "peloton", "sortie club")
    part_validation: float = 0.25  # part des sorties (les plus récentes) réservée au test
    vitesse_min_kmh: float = 8.0
    #: Part de signal de groupe au-delà de laquelle une sortie d'apprentissage
    #: ne sert pas à chercher le CdA sur le temps (L9.1). 0,30 et non 0,50 :
    #: mesuré le 25/09/2026, les sorties d'apprentissage du vélo de route du
    #: mainteneur portent 36 % de signal de groupe en moyenne (20 % en
    #: validation) — une roue partielle que le seuil de 50 % laisse passer, et
    #: qui fait paraître le vélo plus fin qu'il n'est. À 0,30 : erreur de
    #: validation 3,5 % au lieu de 4,6 %, biais −0,8 % au lieu de −4,2 %.
    part_groupe_max: float = 0.30


@dataclass(frozen=True)
class Evitement:
    """Zone à éviter, transmise au moteur de tracé (nogo BRouter)."""

    nom: str
    latitude: float
    longitude: float
    rayon_m: float = 200.0


@dataclass(frozen=True)
class ParametresBoucle:
    vitesse_moyenne_kmh: float = 27.0  # en attendant le modèle physique (S3)
    sens: str = "horaire"  # sens de boucle préféré (horaire en France, antihoraire au Royaume-Uni)
    candidates: int = 5
    tolerance_distance: float = 0.10  # écart relatif accepté sur la distance cible


class PorteVelos(Protocol):
    """Ce qui déclare les vélos du cycliste : `config.Config` en est un.

    Pour les fonctions qui ne lisent de la configuration que ses vélos (le
    rattachement d'une sortie à un vélo, `activites.inventaire`) : elles
    reçoivent toujours la `Config`, sans avoir à importer `config.py`.
    """

    @property
    def velos(self) -> tuple[Velo, ...]: ...
