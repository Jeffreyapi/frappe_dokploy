# =============================================================================
#  Devcontainer Dockerfile — environnement de DÉVELOPPEMENT Frappe v16
#
#  Stack :
#    - Ubuntu 24.04
#    - Python 3.14  (via deadsnakes PPA — requis par Frappe v16)
#    - Node.js 18 LTS
#    - MariaDB 10.6
#    - Redis 7
# =============================================================================

FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

# ── Python 3.14 via deadsnakes PPA ───────────────────────────────────────────
RUN apt-get update && apt-get install -y software-properties-common && \
    add-apt-repository ppa:deadsnakes/ppa && \
    apt-get update && apt-get install -y \
    python3.14 \
    python3.14-dev \
    python3.14-venv \
 && rm -rf /var/lib/apt/lists/*

# ── Dépendances système ───────────────────────────────────────────────────────
RUN apt-get update && apt-get install -y \
    sudo \
    curl \
    git \
    build-essential \
    libffi-dev \
    libssl-dev \
    pkg-config \
    # MariaDB 10.6
    mariadb-server \
    mariadb-client \
    libmariadb-dev-compat \
    libmariadb-dev \
    # Redis
    redis-server \
    # Utilitaires
    wkhtmltopdf \
    xvfb \
    libfontconfig \
    cron \
 && rm -rf /var/lib/apt/lists/*

# ── pip pour Python 3.14 ─────────────────────────────────────────────────────
RUN curl -sS https://bootstrap.pypa.io/get-pip.py | python3.14

# ── Node.js 18 LTS + Yarn ────────────────────────────────────────────────────
RUN curl -fsSL https://deb.nodesource.com/setup_18.x | bash - && \
    apt-get install -y nodejs && \
    npm install -g yarn && \
    rm -rf /var/lib/apt/lists/*

# ── honcho (Procfile runner pour bench start) ─────────────────────────────────
RUN python3.14 -m pip install honcho

# ── User "frappe" — cohérent avec l'image ghcr.io/frappe/base ────────────────
RUN useradd -m -s /bin/bash frappe && \
    echo "frappe ALL=(ALL) NOPASSWD:ALL" >> /etc/sudoers

USER frappe
WORKDIR /workspaces
ENV PATH="/home/frappe/.local/bin:${PATH}"
