# syntax=docker/dockerfile:1.10
# Named context app_source: populated two ways, either works.
#   1. --build-context app_source=<dir prepared by scripts/prepare_build.py>
#      (CI flow, exactly one local app pinned by revision in apps.json).
#   2. Left unset (defaults to this empty stage) + ARG APPS_JSON_BASE64 set
#      (platform-triggered builds, e.g. Dokploy's native GitHub build, which
#      cannot supply a named context, only build args). Every app.json entry
#      is then typically remote (url+revision) — no local app required.
# Whichever apps.json lands in /opt/app-source/ first (context copy) wins;
# APPS_JSON_BASE64 only fills the gap when the context brought nothing.
# NB: ces ARG DOIVENT précéder le premier FROM — en buildkit, un ARG placé
# après un FROM est scopé à ce stage et reste indéfini pour les FROM suivants.
ARG BUILD_IMAGE=ghcr.io/frappe/build@sha256:9e876dcf4f7b5b992ed4ab86bc0079c2dc84f5d2df7fe076e43b4cbbd2772163
ARG BASE_IMAGE=ghcr.io/frappe/base@sha256:86f2b7b9ec64a0b1d91a29e89b81ac708738bdec5e2e02b101c80942bf1bbba5
FROM scratch AS app_source
FROM ${BUILD_IMAGE} AS builder
ARG FRAPPE_VERSION=v16.33.1
ARG FRAPPE_REVISION=988e54f3c4c291e2077a83809663f123731abe76
USER frappe
WORKDIR /home/frappe
# Réseau instable du hôte source : yarn abandonne au 1er timeout de socket
# (30 s hard-coded) ; ESOCKETTIMEDOUT a tué 2 builds consécutifs (05/10, #7).
# Plafond à 10 min par requête, posé avant tout RUN qui lance yarn.
RUN yarn config set network-timeout 600000 -g
# bench init clone la TÊTE de branche ; si la branche avance (release upstream), HEAD ≠
# FRAPPE_REVISION épinglé → le test rev-parse échouait (vécu 06/10 : pin 16.36.1, branche
# passée à 16.50.0). On recale le checkout sur le pin exact avant le test : si le SHA
# n'est pas dans le clone (shallow), un fetch ciblé le ramène.
RUN bench init --frappe-branch=${FRAPPE_VERSION} --no-procfile --no-backups \
      --skip-redis-config-generation --skip-assets /home/frappe/frappe-bench && \
    cd /home/frappe/frappe-bench/apps/frappe && \
    (git cat-file -e "${FRAPPE_REVISION}^{commit}" 2>/dev/null || \
     git fetch --depth=1 origin "${FRAPPE_REVISION}") && \
    git checkout "${FRAPPE_REVISION}" && \
    test "$(git rev-parse HEAD)" = "$FRAPPE_REVISION"
COPY --chown=frappe:frappe scripts/app_sources.py /opt/frappe-deploy/app_sources.py
COPY --from=app_source --chown=frappe:frappe / /opt/app-source/
# Ces deux ARG changent à chaque build (empreinte des commits, apps.json) :
# BuildKit les injecte dans l'env de tous les RUN qui suivent leur déclaration
# et les inclut dans la clé de cache. Les déclarer ici garde `bench init`
# (clone + deps de Frappe) en cache tant que FRAPPE_VERSION/REVISION ne bougent pas.
ARG SOURCE_REVISION=unknown
ARG APPS_JSON_BASE64=""
RUN if [ ! -f /opt/app-source/apps.json ]; then \
      test -n "$APPS_JSON_BASE64" || { \
        echo "apps.json missing: pass --build-context app_source=<dir> or the APPS_JSON_BASE64 build arg" >&2; \
        exit 1; \
      }; \
      echo "$APPS_JSON_BASE64" | base64 -d > /opt/app-source/apps.json; \
    fi
RUN test -f /opt/app-source/source.json || python3 -c "import json, os; apps = json.load(open('/opt/app-source/apps.json')); json.dump({'revision': os.environ['SOURCE_REVISION'], 'apps': apps}, open('/opt/app-source/source.json', 'w'))"
WORKDIR /home/frappe/frappe-bench
# GITHUB_TOKEN est un secret BuildKit (id=git_token) : disponible uniquement
# pour ce RUN via l'env (syntaxe >= 1.10), donc ni dans les build args/etageres
# d'image, ni dans apps.json (les URLs sources restent sans credential) —
# app_sources.py en dérive un helper askpass éphémère pour les apps privées ;
# absent (builds à contexte local / apps publiques), le fetch reste anonyme.
# Caches yarn/uv persistants entre builds (daemon de build) : un nouveau commit
# d'app invalide cette couche mais ne re-télécharge plus les paquets inchangés
# (~250 s de « Fetching packages » sur un build à froid). Hors image finale.
# uid/gid 1000 = utilisateur frappe des images ghcr.io/frappe/*.
RUN --mount=type=secret,id=git_token,env=GITHUB_TOKEN \
    --mount=type=cache,target=/home/frappe/.cache/yarn,uid=1000,gid=1000 \
    --mount=type=cache,target=/home/frappe/.cache/uv,uid=1000,gid=1000 \
    YARN_CACHE_FOLDER=/home/frappe/.cache/yarn UV_CACHE_DIR=/home/frappe/.cache/uv UV_LINK_MODE=copy \
    python3 /opt/frappe-deploy/app_sources.py --project /opt/app-source --bench . && \
    for app_dir in apps/*/; do \
      node_modules="$app_dir/node_modules"; \
      [ -d "$node_modules" ] || continue; \
      for pymod_dir in "$app_dir"/*/; do \
        [ -d "$pymod_dir/public" ] || continue; \
        [ -e "$pymod_dir/public/node_modules" ] || ln -sfn ../../node_modules "$pymod_dir/public/node_modules"; \
      done; \
    done && \
    bench build --hard-link --production && \
    cp /opt/app-source/apps.json /home/frappe/apps-manifest.json && \
    cp /opt/app-source/source.json /home/frappe/source.json && \
    cp -a sites/assets /home/frappe/image-assets && \
    find apps -mindepth 1 -type d -name .git -prune -exec rm -rf '{}' +

FROM ${BASE_IMAGE} AS runtime
ARG S5CMD_VERSION=2.2.0
USER root
RUN apt-get update && apt-get install -y --no-install-recommends util-linux && rm -rf /var/lib/apt/lists/*
RUN set -eu; \
    case "$(uname -m)" in x86_64) arch=64bit;; aarch64) arch=arm64;; *) exit 1;; esac; \
    curl -fsSL "https://github.com/peak/s5cmd/releases/download/v${S5CMD_VERSION}/s5cmd_${S5CMD_VERSION}_Linux-${arch}.tar.gz" -o /tmp/s5cmd.tar.gz; \
    tar -xzf /tmp/s5cmd.tar.gz -C /usr/local/bin s5cmd; \
    rm /tmp/s5cmd.tar.gz; s5cmd version
COPY --from=builder --chown=frappe:frappe /home/frappe/frappe-bench /home/frappe/frappe-bench
COPY --from=builder --chown=frappe:frappe /home/frappe/image-assets /opt/image-assets
COPY --from=builder /home/frappe/apps-manifest.json /opt/apps-manifest.json
COPY --from=builder /home/frappe/source.json /opt/source.json
COPY deploy/scripts/ /opt/frappe-deploy/
COPY deploy/config/ /opt/frappe-deploy-config/
COPY resources/nginx-entrypoint.sh /usr/local/bin/nginx-entrypoint.sh
COPY resources/nginx-template.conf /templates/nginx/frappe.conf.template
RUN chmod 755 /opt/frappe-deploy/*.sh /usr/local/bin/nginx-entrypoint.sh
ENV PATH="/home/frappe/frappe-bench/env/bin:${PATH}"
USER frappe
WORKDIR /home/frappe/frappe-bench
ARG SOURCE_REVISION=unknown
LABEL org.opencontainers.image.revision=$SOURCE_REVISION
CMD ["gunicorn", "--chdir=/home/frappe/frappe-bench/sites", "--bind=0.0.0.0:8000", "--threads=4", "--workers=2", "--worker-class=gthread", "--worker-tmp-dir=/dev/shm", "--timeout=120", "--preload", "frappe.app:application"]
