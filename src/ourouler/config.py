"""Configuration : objets de données + chargement TOML.

Règle absolue 2 de CLAUDE.md : ce module et `cli.py` sont les seuls
autorisés à lire un fichier, `Path.home()` ou une variable d'environnement.
Le reste du cœur reçoit un objet `Config` déjà construit.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from ourouler.erreurs import ErreurConfig

CHEMIN_CONFIG_DEFAUT = Path("~/.config/ourouler/config.toml")
HISTORIQUE_DEPUIS_DEFAUT = date(2023, 12, 1)
USAGES_VELO = ("route", "clm")


@dataclass(frozen=True)
class Depart:
    nom: str
    latitude: float
    longitude: float


@dataclass(frozen=True)
class Cycliste:
    masse_kg: float
    ftp_w: float


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
    intervals_gear: str = ""
    periodes: tuple[Periode, ...] = ()


@dataclass(frozen=True)
class ParametresMeteo:
    directions: int = 8
    distances_km: tuple[float, ...] = (15.0, 25.0, 40.0)
    modele: str = "meteofrance_arome_france_hd"
    second_avis: str = "icon_seamless"
    horizon_h: int = 6


@dataclass(frozen=True)
class ParametresIntervals:
    athlete_id: str = ""
    api_key: str = ""

    @property
    def renseigne(self) -> bool:
        return bool(self.athlete_id and self.api_key)


@dataclass(frozen=True)
class ParametresCache:
    dossier: Path = Path("~/.cache/ourouler")


@dataclass(frozen=True)
class Config:
    depart: Depart
    cycliste: Cycliste
    velos: tuple[Velo, ...] = ()
    meteo: ParametresMeteo = field(default_factory=ParametresMeteo)
    intervals: ParametresIntervals = field(default_factory=ParametresIntervals)
    cache: ParametresCache = field(default_factory=ParametresCache)
    historique_depuis: date = HISTORIQUE_DEPUIS_DEFAUT

    def velo(self, nom: str) -> Velo:
        for v in self.velos:
            if v.nom.casefold() == nom.casefold():
                return v
        raise ErreurConfig(f"velos : aucun vélo nommé « {nom} »")


# --- chargement -------------------------------------------------------------


def charger(chemin: Path | None = None) -> Config:
    """Lit un fichier TOML et construit la `Config`. Chemin par défaut : ~/.config/ourouler/config.toml."""
    chemin = (chemin or CHEMIN_CONFIG_DEFAUT).expanduser()
    if not chemin.is_file():
        raise ErreurConfig(
            f"fichier de configuration introuvable : {chemin} "
            "(copier config.example.toml et le renseigner, ou passer --config)"
        )
    try:
        with chemin.open("rb") as f:
            brut = tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        raise ErreurConfig(f"{chemin} : TOML invalide ({e})") from e
    config = depuis_dict(brut)
    # Seul endroit où « ~ » est développé : le cœur reçoit un chemin absolu.
    return _remplacer(config, cache=ParametresCache(config.cache.dossier.expanduser()))


def depuis_dict(d: dict[str, Any]) -> Config:
    """Construit la `Config` depuis un dictionnaire (contenu TOML déjà lu). Valide et nomme les champs."""
    depart = _section(d, "depart")
    cycliste = _section(d, "cycliste")
    velos = tuple(_velo(v, i) for i, v in enumerate(d.get("velos", []) or []))
    if not velos:
        velos = (Velo(nom="Route"),)
    meteo = d.get("meteo", {}) or {}
    intervals = d.get("intervals", {}) or {}
    cache = d.get("cache", {}) or {}
    return Config(
        depart=Depart(
            nom=str(depart.get("nom", "Départ")),
            latitude=_nombre(depart, "latitude", "depart", -90, 90),
            longitude=_nombre(depart, "longitude", "depart", -180, 180),
        ),
        cycliste=Cycliste(
            masse_kg=_nombre(cycliste, "masse_kg", "cycliste", 20, 300),
            ftp_w=_nombre(cycliste, "ftp_w", "cycliste", 50, 1000),
        ),
        velos=velos,
        meteo=ParametresMeteo(
            directions=int(meteo.get("directions", 8)),
            distances_km=tuple(float(x) for x in meteo.get("distances_km", (15, 25, 40))),
            modele=str(meteo.get("modele", ParametresMeteo.modele)),
            second_avis=str(meteo.get("second_avis", ParametresMeteo.second_avis)),
            horizon_h=int(meteo.get("horizon_h", 6)),
        ),
        intervals=ParametresIntervals(
            athlete_id=str(intervals.get("athlete_id", "") or ""),
            api_key=str(intervals.get("api_key", "") or ""),
        ),
        cache=ParametresCache(dossier=Path(str(cache.get("dossier", "~/.cache/ourouler")))),
        historique_depuis=_date(d.get("historique_depuis", HISTORIQUE_DEPUIS_DEFAUT), "historique_depuis"),
    )


def _section(d: dict[str, Any], nom: str) -> dict[str, Any]:
    s = d.get(nom)
    if not isinstance(s, dict):
        raise ErreurConfig(f"section [{nom}] manquante")
    return s


def _nombre(s: dict[str, Any], cle: str, section: str, mini: float, maxi: float) -> float:
    if cle not in s:
        raise ErreurConfig(f"[{section}] {cle} manquant")
    try:
        x = float(s[cle])
    except (TypeError, ValueError) as e:
        raise ErreurConfig(f"[{section}] {cle} : nombre attendu, reçu {s[cle]!r}") from e
    if not mini <= x <= maxi:
        raise ErreurConfig(f"[{section}] {cle} = {x} hors de [{mini}, {maxi}]")
    return x


def _date(x: Any, champ: str) -> date:
    if isinstance(x, date):
        return x
    try:
        return date.fromisoformat(str(x))
    except ValueError as e:
        raise ErreurConfig(f"{champ} : date AAAA-MM-JJ attendue, reçu {x!r}") from e


def _velo(v: Any, i: int) -> Velo:
    section = f"velos[{i}]"
    if not isinstance(v, dict) or not v.get("nom"):
        raise ErreurConfig(f"{section} : nom manquant")
    usage = str(v.get("usage", "route"))
    if usage not in USAGES_VELO:
        raise ErreurConfig(f"{section} usage = {usage!r}, attendu un de {USAGES_VELO}")
    periodes = []
    for j, p in enumerate(v.get("periodes", []) or []):
        if not isinstance(p, dict) or "debut" not in p:
            raise ErreurConfig(f"{section}.periodes[{j}] : debut manquant")
        periodes.append(
            Periode(
                debut=_date(p["debut"], f"{section}.periodes[{j}].debut"),
                fin=_date(p["fin"], f"{section}.periodes[{j}].fin") if p.get("fin") else None,
            )
        )
    return Velo(
        nom=str(v["nom"]),
        usage=usage,
        masse_kg=float(v["masse_kg"]) if v.get("masse_kg") is not None else None,
        cda_m2=float(v["cda_m2"]) if v.get("cda_m2") is not None else None,
        intervals_gear=str(v.get("intervals_gear", "") or ""),
        periodes=tuple(periodes),
    )


def _remplacer(config: Config, **champs: Any) -> Config:
    from dataclasses import replace

    return replace(config, **champs)
