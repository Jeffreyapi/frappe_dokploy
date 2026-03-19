# =============================================================================
#  frappe_dokploy — Dockerfile
#  Construit une image Frappe avec les apps définies dans apps.json.
#
#  Build args:
#    FRAPPE_VERSION   : branche/tag Frappe (ex: version-15)
#    APPS_JSON_BASE64 : contenu de apps.json encodé en base64 (injecté par CI)
#    S5CMD_VERSION    : version de s5cmd pour les backups S3
# =============================================================================

# ── Stage 1 : image Frappe avec les apps ─────────────────────────────────────
ARG FRAPPE_VERSION=version-15
ARG APPS_JSON_BASE64
ARG PYTHON_VERSION=3.11.9
ARG NODE_VERSION=18.20.4
ARG DEBIAN_BASE=bookworm

FROM ghcr.io/frappe/base:${FRAPPE_VERSION} AS frappe_base

ARG APPS_JSON_BASE64
ENV APPS_JSON_BASE64=${APPS_JSON_BASE64}

USER frappe
WORKDIR /home/frappe/frappe-bench

# Installer les apps depuis apps.json
RUN if [ -n "$APPS_JSON_BASE64" ]; then \
      echo "$APPS_JSON_BASE64" | base64 -d > /tmp/apps.json && \
      bench get-app --resolve-deps /tmp/apps.json; \
    fi

# Build des assets
RUN bench build --hard-link --production || true

# ── Stage 2 : ajout des outils (s5cmd pour backup S3) ────────────────────────
ARG S5CMD_VERSION=2.2.0

FROM frappe_base AS tools

USER root

RUN set -eux; \
    ARCH="$(uname -m)"; \
    if [ "$ARCH" = "x86_64" ]; then ARCH="64bit"; fi; \
    if [ "$ARCH" = "aarch64" ]; then ARCH="arm64"; fi; \
    curl -fsSL "https://github.com/peak/s5cmd/releases/download/v${S5CMD_VERSION}/s5cmd_${S5CMD_VERSION}_Linux-${ARCH}.tar.gz" \
      | tar -xz -C /usr/local/bin s5cmd && \
    s5cmd version

# Intégrer le nginx-entrypoint et le template custom
COPY resources/nginx-entrypoint.sh /usr/local/bin/nginx-entrypoint.sh
COPY resources/nginx-template.conf /templates/nginx/frappe.conf.template
RUN chmod +x /usr/local/bin/nginx-entrypoint.sh

USER frappe

# ── Stage final ───────────────────────────────────────────────────────────────
FROM tools

LABEL org.opencontainers.image.source="https://github.com/Jeffreyapi/frappe_dokploy"
LABEL org.opencontainers.image.description="Generic Frappe deployment image"
