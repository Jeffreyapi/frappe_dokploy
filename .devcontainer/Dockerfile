# Python 3.14 / Node 24 and build dependencies from the Frappe builder.
# MariaDB 11.8 and Redis 7 run as separate Compose services.
ARG BUILD_IMAGE=ghcr.io/frappe/build@sha256:9e876dcf4f7b5b992ed4ab86bc0079c2dc84f5d2df7fe076e43b4cbbd2772163
FROM ${BUILD_IMAGE}
USER root
RUN apt-get update && apt-get install -y --no-install-recommends sudo && \
    rm -rf /var/lib/apt/lists/* && \
    echo "frappe ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/frappe && \
    python3 -m pip install honcho debugpy
USER frappe
ENV PATH="/home/frappe/frappe-bench/env/bin:/home/frappe/.local/bin:${PATH}"
WORKDIR /workspaces/hermes_control
CMD ["sleep", "infinity"]
