# =============================================================================
#  Devcontainer Dockerfile — environnement de DÉVELOPPEMENT Frappe
#
#  Ce conteneur est fait pour CODER l'app (bench en mode développeur, hot-reload,
#  debug Python). Il ne remplace pas la stack Docker Compose de frappe_deploy/
#  qui, elle, sert au DÉPLOIEMENT (prod/staging).
#
#  Versions alignées avec la stack de production (frappe_deploy/) :
#    - MariaDB  : 10.6  (Ubuntu 22.04 default → aucun repo externe nécessaire)
#    - Node.js  : 18    (LTS recommandé pour Frappe version-15)
#    - Python   : 3.10  (Ubuntu 22.04 default)
# =============================================================================

FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

# ── Dépendances système ───────────────────────────────────────────────────────
RUN apt-get update && apt-get install -y \
    sudo \
    curl \
    git \
    build-essential \
    python3 \
    python3-dev \
    python3-venv \
    python3-pip \
    libffi-dev \
    libssl-dev \
    # MariaDB 10.6 — fourni nativement par Ubuntu 22.04 (pas de repo externe)
    mariadb-server \
    mariadb-client \
    libmariadb-dev-compat \
    libmariadb-dev \
    # Redis
    redis-server \
    # Utilitaires
    cron \
    xvfb \
    libfontconfig \
    pkg-config \
    wkhtmltopdf \
 && rm -rf /var/lib/apt/lists/*

# ── Node.js 18 LTS + Yarn ────────────────────────────────────────────────────
RUN curl -fsSL https://deb.nodesource.com/setup_18.x | bash - && \
    apt-get install -y nodejs && \
    npm install -g yarn && \
    rm -rf /var/lib/apt/lists/*

# ── honcho (Procfile runner pour bench start) ─────────────────────────────────
RUN pip3 install honcho

# ── User "frappe" — cohérent avec l'image ghcr.io/frappe/base ────────────────
RUN useradd -m -s /bin/bash frappe && \
    echo "frappe ALL=(ALL) NOPASSWD:ALL" >> /etc/sudoers

USER frappe
WORKDIR /workspaces
ENV PATH="/home/frappe/.local/bin:${PATH}"
