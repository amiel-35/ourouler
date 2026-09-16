# Image de l'hébergé minimal (docs/heberge_minimal_contrat.md).
#
# Une seule image pour les deux rôles du contrat — « générateur » (exécute
# `ourouler sortie` une fois par jour) et « serveur » (sert le volume produit
# derrière une authentification basique) — sélectionnés par la commande passée
# au conteneur (voir docker-compose.yml). Le rôle serveur n'a besoin que de la
# bibliothèque standard, mais partager l'image évite d'en maintenir deux pour
# un gain de taille marginal sur ce lot.
#
# Aucune donnée personnelle ni clé ici : `ourouler.example.toml` n'existe pas
# dans l'image, seul le code source l'est. La configuration réelle (fichier
# TOML non-secrets + variables d'environnement pour les secrets) est fournie
# au lancement du conteneur, jamais au moment du build.

FROM python:3.12-slim

# `uv` : installateur rapide, déjà la doctrine du projet (pyproject.toml).
COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /uvx /usr/local/bin/

WORKDIR /app

# Couche de dépendances séparée du code : un changement de source ne réinstalle
# pas les paquets.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY README.md ./README.md
COPY src/ ./src/
COPY deploiement/generateur/entrypoint.py ./deploiement/generateur/entrypoint.py
COPY deploiement/serveur/serveur.py ./deploiement/serveur/serveur.py
RUN uv sync --frozen --no-dev

ENV PATH="/app/.venv/bin:${PATH}"

# Pas d'ENTRYPOINT/CMD fixe : le rôle (générateur ou serveur) est donné par
# la commande du service dans docker-compose.yml.
