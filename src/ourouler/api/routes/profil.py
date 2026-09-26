"""Le profil du cycliste : lecture, modification, zones et aperçus de FTP."""

from __future__ import annotations

from dataclasses import replace
from typing import Annotated

import httpx
from fastapi import Query, Request

from ourouler.api import vues
from ourouler.api.depots import schema_des_modifications
from ourouler.api.erreurs import ErreurApi, classer, message_profil_invalide, secrets_de
from ourouler.api.modeles import ApercuZones, DemandeVitesseCompteur
from ourouler.api.proprietaire import Proprietaire
from ourouler.api.reponses import ReponseProfil, ReponseProfilIntervals, ReponseZones, reponse_de
from ourouler.api.routes.commun import Contexte, Ctx, Qui, _config, _service, nouveau_routeur
from ourouler.config import Config
from ourouler.connecteurs.intervals import resoudre_athlete_id
from ourouler.noyau.erreurs import ErreurConfig

routeur = nouveau_routeur()


@routeur.get("/profil", **reponse_de(ReponseProfil))
def lire_profil(
    ctx: Ctx,
    qui: Qui,
) -> dict:
    """Le profil du cycliste : départ, poids, FTP, position dans la zone, vélos, services.

    `donnees.assistant_recommande` dit si ce propriétaire n'a **jamais**
    enregistré de surcharge (`DepotProfils.surcharge` vide) — un compte
    activé mais jamais passé par l'assistant, quel qu'ait été le socle qu'il
    a lu au démarrage. Sans lui, un compte neuf atterrirait sur l'écran du
    jour, qui réclame Intervals et échoue, au lieu de l'assistant qui
    construit le profil. Le premier
    `PATCH /profil` fait passer ce booléen à faux — pas un drapeau à part à
    tenir à jour, juste la conséquence de ce qui est déjà écrit sur le disque.
    """
    return {"proprietaire": str(qui), "donnees": _profil_avec_flags(ctx, qui, _config(ctx, qui))}


@routeur.patch(
    "/profil",
    **reponse_de(ReponseProfil),
    # Le corps est lu à la main (`await requete.json()`) et validé par
    # `depots.valider` : il n'a donc pas de modèle Pydantic, et FastAPI ne
    # publierait rien. Ce qu'il accepte est engendré de la liste blanche
    # elle-même — voir `depots.schema_des_modifications`.
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {"application/json": {"schema": schema_des_modifications()}},
        }
    },
)
async def modifier_profil(
    ctx: Ctx,
    qui: Qui,
    requete: Request,
) -> dict:
    """Modifie ce que l'assistant demande, et rend le profil qui en résulte.

    Corps : les sections à modifier, telles qu'elles se lisent
    (`{"cycliste": {"ftp_w": 262}}`). Ce qu'un cycliste n'a pas le droit de
    modifier est **refusé** et nommé, jamais ignoré (`depots.valider`).

    Rien n'est écrit si la configuration résultante est invalide : le profil
    précédent reste, et le front reçoit le champ fautif.
    """
    try:
        corps = await requete.json()
    except Exception as e:
        raise ErreurApi(code="requete_invalide", message="corps JSON illisible", statut=400) from e
    corps = _corps_avec_athlete_id_resolu(ctx, corps)
    try:
        config = ctx.profils.enregistrer(qui, corps)
    except ErreurConfig as e:
        # Ici, et seulement ici, une configuration invalide est la faute de
        # ce que le cycliste vient d'écrire : 422 et non 500. Le message est
        # traduit pour l'écran (sinon un poids fautif afficherait
        # « [cycliste] masse_kg = 7075.0 hors de [20, 300] » tel quel) ;
        # `details.champ` laisse le front l'afficher près du champ.
        message, details = message_profil_invalide(e)
        raise ErreurApi(code="profil_invalide", message=message, statut=422, details=details) from e
    except Exception as e:
        raise classer(e) from e
    return {"proprietaire": str(qui), "donnees": _profil_avec_flags(ctx, qui, config)}


def _corps_avec_athlete_id_resolu(ctx: Contexte, corps: dict) -> dict:
    """Complète `intervals.athlete_id` quand le corps pose une clé sans lui.

    L'assistant et Réglages n'envoient
    que `{"intervals": {"api_key": "…"}}` — aucun des deux ne demande
    l'`athlete_id` (`front/src/ecrans/Assistant.tsx`, `Reglages.tsx`). Sans ce
    complément, `ParametresIntervals.renseigne` reste faux et toutes les
    routes Intervals répondent `intervals_absent` (409), quelle que soit la
    clé. L'`athlete_id` ne peut pas venir du TOML du serveur : un socle ne se
    partage pas (`depots.DepotProfils.config`).

    `intervals.athlete_id` **vide** compte comme absent — un champ posé à
    `""` par un front plus ancien ne doit pas empêcher la résolution.
    N'écrit rien : c'est `ctx.profils.enregistrer`, juste après, qui écrit —
    une clé refusée ou Intervals injoignable lève avant, donc avant toute
    écriture (règle du profil : rien n'est stocké tant que ce n'est pas
    valide).
    """
    if not isinstance(corps, dict):
        return corps
    section = corps.get("intervals")
    if not isinstance(section, dict):
        return corps
    cle = section.get("api_key")
    identifiant = section.get("athlete_id")
    if not cle or identifiant:
        return corps
    resolu = _resoudre_athlete_id(ctx, cle)
    return {**corps, "intervals": {**section, "athlete_id": resolu}}


def _resoudre_athlete_id(ctx: Contexte, api_key: str) -> str:
    """Appelle Intervals.icu pour résoudre l'athlete_id — jamais la clé dans l'erreur.

    `ctx.clients.intervals` est le même point d'injection que le reste de
    l'API (voir `FABRIQUES_CONNECTEUR`) : un `httpx.Client` en test (bouchonné
    par un `MockTransport`), rien en service — le connecteur fabrique alors
    son propre client réel. Il ne peut pas passer par `Clients.connecteur`
    (qui exige une `Config` déjà valide, donc déjà un `athlete_id`) : c'est
    précisément ce qui manque encore à cet instant.

    Un `ClientIntervals` déjà construit (l'autre forme d'injection acceptée
    ailleurs, `test_un_connecteur_deja_construit_reste_accepte_tel_quel`) est
    aussi accepté : son transport interne (`_http`) est repris, pour qu'un
    test qui bouchonne Intervals une seule fois couvre les deux chemins.
    """
    donne = ctx.clients.intervals
    if isinstance(donne, httpx.Client):
        http = donne
    else:
        http = getattr(donne, "_http", None)
        http = http if isinstance(http, httpx.Client) else None
    try:
        return resoudre_athlete_id(api_key, http=http)
    except Exception as e:
        raise classer(e, secrets=(api_key,)) from e


def _profil_avec_flags(ctx: Contexte, qui: Proprietaire, config: Config) -> dict:
    """Le profil rendu par `vues.profil`, plus `assistant_recommande` (voir `lire_profil`).

    Factorisé pour que `GET /profil` et `PATCH /profil` rendent exactement le
    même calcul : sans ça, le front qui met à jour son état local depuis la
    réponse d'un `PATCH` (`Assistant.tsx`, `enregistrer()`) verrait le
    drapeau se figer jusqu'au prochain `GET`, alors qu'un premier `PATCH`
    est précisément ce qui doit le faire tomber.
    """
    donnees = vues.profil(config)
    donnees["assistant_recommande"] = not bool(ctx.profils.surcharge(qui))
    return donnees


@routeur.get("/profil/zones", **reponse_de(ReponseZones))
def lire_zones(
    ctx: Ctx,
    qui: Qui,
    velo: str | None = None,
    position: Annotated[float | None, Query(ge=-2, le=3)] = None,
) -> dict:
    """L'échelle des zones en watts, et les trois valeurs liées de l'écran de FTP.

    La troisième — la moyenne compteur attendue — dit toujours si son facteur
    est **mesuré** sur l'historique du cycliste ou **supposé** par le modèle
    (`facteur_mesure`, décision 8).
    """
    from ourouler.seance import ecran_ftp

    config = _config(ctx, qui)
    try:
        return {"proprietaire": str(qui), "donnees": ecran_ftp.rendu(config, velo, position=position)}
    except Exception as e:
        raise classer(e) from e


@routeur.post("/profil/zones/apercu", **reponse_de(ReponseZones))
def apercu_zones(
    ctx: Ctx,
    qui: Qui,
    demande: ApercuZones,
) -> dict:
    """Recalcule les trois valeurs liées **sans rien stocker**.

    C'est le geste de l'écran de FTP : on tape des watts ou une vitesse à
    plat, les autres valeurs suivent, et rien n'est enregistré tant que le
    cycliste n'a pas validé — auquel cas le front envoie la **position**
    obtenue ici à `PATCH /profil` (`seance.position_zone`), jamais les watts.
    """
    from ourouler.seance import ecran_ftp

    config = _config(ctx, qui)
    donnes = [
        demande.position_zone is not None,
        demande.puissance_w is not None,
        demande.vitesse_a_plat_kmh is not None,
    ]
    if sum(donnes) != 1:
        raise ErreurApi(
            code="requete_invalide",
            message="aperçu des zones : donner exactement une valeur — position_zone, "
            "puissance_w ou vitesse_a_plat_kmh (la moyenne compteur n'est pas éditable)",
            statut=400,
        )
    try:
        if demande.position_zone is not None:
            position = demande.position_zone
        else:
            position = ecran_ftp.position_pour(
                config,
                demande.velo,
                puissance_w=demande.puissance_w,
                vitesse_kmh=demande.vitesse_a_plat_kmh,
            )
        return {"proprietaire": str(qui), "donnees": ecran_ftp.rendu(config, demande.velo, position=position)}
    except Exception as e:
        raise classer(e) from e


@routeur.get("/profil/intervals", **reponse_de(ReponseProfilIntervals))
def profil_intervals(ctx: Ctx, qui: Qui) -> dict:
    """Ce qu'Intervals.icu sait de l'athlète — FTP, poids — **pour confirmation, sans rien écrire**.

    L'étage T1 de l'accueil (`docs/journal/ux/parcours_accueil.md` §4), une fois la
    clé Intervals posée : « on a trouvé ceci, c'est toujours d'actualité ? »
    plutôt que remplacer en silence ou reposer une question dont Intervals
    connaît déjà la réponse (décision Q64,
    `docs/journal/questions/questions_mainteneur.md`). Le front confirme ou
    corrige, puis envoie la valeur retenue à `PATCH /profil` comme n'importe
    quelle FTP ou
    masse déclarée — cette route ne fait que lire.

    401 nommé `intervals_absent` si la clé n'est pas encore posée : ce n'est
    ni une panne ni une faute, c'est un compte qui n'en est pas encore là.
    """
    from ourouler.connecteurs.intervals import ClientIntervals
    from ourouler.noyau.erreurs import ErreurIntervalsAbsent

    config = _config(ctx, qui)
    try:
        if not config.intervals.renseigne:
            raise ErreurIntervalsAbsent(
                "profil Intervals : la clé n'est pas encore renseignée pour ce compte"
            )
        client = _service(ctx, config, "intervals")
        if client is None:
            client = ClientIntervals(config.intervals.athlete_id, config.intervals.api_key)
        donnees = client.profil_athlete()
    except Exception as e:
        raise classer(e, secrets=secrets_de(config)) from e
    return {"proprietaire": str(qui), "donnees": donnees}


@routeur.post("/profil/ftp/apercu")
def apercu_ftp_depuis_terrain(
    ctx: Ctx,
    qui: Qui,
    demande: DemandeVitesseCompteur,
) -> dict:
    """T4 de l'accueil : une FTP à partir d'une vitesse au compteur et d'un terrain, **sans rien stocker**.

    Même geste que `POST /profil/zones/apercu` : la FTP rendue est un aperçu,
    le front l'affiche et l'envoie à `PATCH /profil` (`cycliste.ftp_w`) si le
    cycliste confirme. Elle est calculée à la `position_zone` déjà en
    vigueur dans la configuration — c'est établir une FTP là où il n'y en
    avait pas, pas déplacer une position (`seance.ecran_ftp.
    ftp_pour_vitesse_compteur`).
    """
    from ourouler.seance import ecran_ftp

    config = _config(ctx, qui)
    try:
        ftp_w = ecran_ftp.ftp_pour_vitesse_compteur(
            config,
            demande.velo,
            vitesse_compteur_kmh=demande.vitesse_kmh,
            denivele_m_par_km=demande.denivele_m_par_km,
        )
        config_avec_ftp = replace(config, cycliste=replace(config.cycliste, ftp_w=ftp_w))
        return {
            "proprietaire": str(qui),
            "donnees": ecran_ftp.rendu(config_avec_ftp, demande.velo),
        }
    except Exception as e:
        raise classer(e) from e


@routeur.get("/profil/ftp/generique", **reponse_de(ReponseZones))
def ftp_generique(ctx: Ctx, qui: Qui, velo: str | None = None) -> dict:
    """T5 de l'accueil, le fond du tunnel : une FTP à partir du seul poids, **sans rien stocker**.

    Ne peut pas échouer — `physique.litterature.ftp_defaut` ne demande que
    `cycliste.masse_kg`, qui n'est jamais facultative. C'est la garantie que
    l'entonnoir de `docs/journal/ux/parcours_accueil.md` promet à l'étage T5 : « rien
    à demander, jamais rien [en échec] ». Même geste que les deux routes
    d'aperçu voisines : le front affiche, et envoie `cycliste.ftp_w` à
    `PATCH /profil` si la personne continue.
    """
    from ourouler.physique.litterature import ftp_defaut
    from ourouler.seance import ecran_ftp

    config = _config(ctx, qui)
    try:
        ftp_w = ftp_defaut(config.cycliste.masse_kg)
        config_avec_ftp = replace(config, cycliste=replace(config.cycliste, ftp_w=ftp_w))
        return {"proprietaire": str(qui), "donnees": ecran_ftp.rendu(config_avec_ftp, velo)}
    except Exception as e:
        raise classer(e) from e
