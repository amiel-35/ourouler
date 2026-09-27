"""L'administration n'existe **jamais** dans l'application publique ni son contrat.

Sprint 12, QP6 (25/09/2026, tranchée (c)). `api/admin.py` construit une
**seconde** application FastAPI, distincte de celle que sert
`api/application.py` ; ce test-ci prouve la séparation par l'effet plutôt
que par lecture du code : aucune route `/admin/...` dans les routes montées
de l'application publique, et aucune dans son schéma OpenAPI publié — le
contrat que le front (et n'importe quel client) peut lire.
"""

from __future__ import annotations

import outils_api


def test_aucune_route_admin_dans_l_application_publique():
    application = outils_api.charger_application()
    chemins = [str(getattr(route, "path", "")) for route in application.routes]
    admin = [c for c in chemins if c.startswith("/admin")]
    assert admin == [], f"des routes d'administration existent dans l'application publique : {admin}"


def test_aucune_route_admin_dans_l_openapi_publie():
    client = outils_api.client_api()
    schema = outils_api.schema_openapi(client)
    chemins_admin = [c for c in (schema.get("paths") or {}) if c.startswith("/admin")]
    assert chemins_admin == [], (
        f"des routes d'administration figurent dans le schéma publié : {chemins_admin}"
    )
