# syntax=docker/dockerfile:1
# Named context app_source must be prepared with scripts/prepare_build.py.
ARG BUILD_IMAGE=ghcr.io/frappe/build@sha256:9e876dcf4f7b5b992ed4ab86bc0079c2dc84f5d2df7fe076e43b4cbbd2772163
ARG BASE_IMAGE=ghcr.io/frappe/base@sha256:86f2b7b9ec64a0b1d91a29e89b81ac708738bdec5e2e02b101c80942bf1bbba5
FROM ${BUILD_IMAGE} AS builder
ARG FRAPPE_VERSION=v16.33.1
ARG FRAPPE_REVISION=988e54f3c4c291e2077a83809663f123731abe76
USER frappe
WORKDIR /home/frappe
RUN bench init --frappe-branch=${FRAPPE_VERSION} --no-procfile --no-backups \
      --skip-redis-config-generation --skip-assets /home/frappe/frappe-bench && \
    test "$(git -C /home/frappe/frappe-bench/apps/frappe rev-parse HEAD)" = "$FRAPPE_REVISION"
COPY --chown=frappe:frappe scripts/app_sources.py /opt/frappe-deploy/app_sources.py
COPY --from=app_source --chown=frappe:frappe / /opt/app-source/
WORKDIR /home/frappe/frappe-bench
RUN python3 /opt/frappe-deploy/app_sources.py --project /opt/app-source --bench . && \
    bench build --hard-link --production && \
    cp /opt/app-source/apps.json /home/frappe/apps-manifest.json && \
    cp /opt/app-source/source.json /home/frappe/source.json && \
    cp -a sites/assets /home/frappe/image-assets && \
    find apps -mindepth 1 -type d -name .git -prune -exec rm -rf '{}' +

FROM ${BASE_IMAGE} AS runtime
ARG SOURCE_REVISION=unknown
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
LABEL org.opencontainers.image.revision=$SOURCE_REVISION
CMD ["gunicorn", "--chdir=/home/frappe/frappe-bench/sites", "--bind=0.0.0.0:8000", "--threads=4", "--workers=2", "--worker-class=gthread", "--worker-tmp-dir=/dev/shm", "--timeout=120", "--preload", "frappe.app:application"]
