# Image de l'API et du front, servis depuis le même conteneur.
#
# Deux étages : le premier construit le front (`npm run build`), le second
# installe l'API Python et y copie le résultat du premier. Une seule image en
# sortie, un seul processus au démarrage (`entrypoint.py`, qui lance
# uvicorn) — voir `deploiement/api/README.md` pour pourquoi une seule origine
# plutôt que deux services et un proxy devant.
#
# **Rien n'est déployé par ce fichier.** Il décrit une image ; la construire
# et la lancer localement (`docker-compose.yml` à côté) sert à vérifier
# l'image, pas à la mettre en ligne (aucune installation sur un serveur sans
# l'accord de qui l'exploite, `AGENTS.md`).
#
# Aucune donnée personnelle ni clé ici : la configuration réelle (TOML
# non-secrets en base64 + variables d'environnement pour les secrets) est
# fournie au lancement du conteneur, jamais au moment du build — même
# contrainte que `deploiement/Dockerfile`, pour la même raison.

# --- étage 1 : le front -------------------------------------------------------

FROM node:20-slim AS front

WORKDIR /front

# Couche de dépendances séparée du code source : un changement dans
# `front/src/` ne réinstalle pas `node_modules/`.
COPY front/package.json front/package-lock.json ./
RUN npm ci

COPY front/ ./
RUN npm run build

# --- étage 2 : l'API, et le front construit dedans ----------------------------

FROM python:3.12-slim AS api

# `uv` : installateur rapide, déjà la doctrine du projet (pyproject.toml) —
# même image épinglée que `deploiement/Dockerfile`.
COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /uvx /usr/local/bin/

WORKDIR /app

# Couche de dépendances séparée du code : un changement de source ne
# réinstalle pas les paquets. `--extra api` : FastAPI et uvicorn, que le
# projet met derrière un extra pour que `ourouler` reste installable sans
# cadre web (pyproject.toml).
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --extra api --no-install-project

COPY README.md ./README.md
COPY src/ ./src/
COPY deploiement/api/entrypoint.py ./deploiement/api/entrypoint.py
RUN uv sync --frozen --no-dev --extra api

# Le front construit, copié depuis le premier étage — jamais reconstruit ici,
# `node` ne fait pas partie de cette image.
COPY --from=front /front/dist ./front/dist

ENV PATH="/app/.venv/bin:${PATH}"
# Le dossier que `application()` monte à la racine (`api/exploitation.py`,
# `VARIABLE_FRONT_DIST`) — posé ici, pas dans le code : c'est une donnée du
# déploiement, la même distinction qu'entre `cli/` et le cœur.
ENV OUROULER_FRONT_DIST=/app/front/dist

# La sonde ne demande aucune session : c'est ce qui la rend
# utilisable ici, avant même qu'une méthode d'authentification soit branchée.
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD python3 -c "import urllib.request as u; u.urlopen('http://127.0.0.1:8000/sante', timeout=2)" || exit 1

CMD ["python3", "deploiement/api/entrypoint.py"]
