# =============================================================================
#  Template : Makefile — à placer à la RACINE du repo app.
#  Raccourcis pour les commandes Docker Compose du projet Frappe.
#
#  Prérequis :
#    - Docker Compose v2 installé (docker compose)
#    - .env configuré (cp .env.example .env)
#    - Réseau Dokploy créé (make init le fait automatiquement)
# =============================================================================

.PHONY: init up build down restart logs shell backup restore update configure

# ── Initialisation (première fois ou après git clone) ────────────────────────
init:
	@echo "→ Initialisation du submodule frappe_deploy..."
	git submodule update --init --recursive
	@if [ ! -f .env ]; then \
	  cp .env.example .env; \
	  echo "→ .env créé depuis .env.example — renseigner les valeurs avant de continuer"; \
	else \
	  echo "→ .env déjà présent"; \
	fi
	@docker network inspect dokploy-network >/dev/null 2>&1 \
	  && echo "→ Réseau dokploy-network déjà présent" \
	  || (docker network create dokploy-network && echo "→ Réseau dokploy-network créé")

# ── Démarrer la stack (image depuis GHCR) ────────────────────────────────────
up:
	docker compose up -d

# ── Reconstruire l'image localement et démarrer ───────────────────────────────
# Requiert GH_PAT en variable d'environnement :
#   export GH_PAT=ghp_xxx && make build
build:
	@[ -n "$(GH_PAT)" ] || { echo "ERR: GH_PAT non défini. Faire : export GH_PAT=ghp_xxx"; exit 1; }
	@envsubst < apps.json > /tmp/apps.build.json
	APPS_JSON_BASE64="$$(base64 -w 0 /tmp/apps.build.json)" \
	  docker compose \
	    -f docker-compose.yml \
	    -f frappe_deploy/docker-compose.build.yml \
	    up --build -d

# ── Arrêter la stack ──────────────────────────────────────────────────────────
down:
	docker compose down

# ── Redémarrer sans reconstruire ──────────────────────────────────────────────
restart:
	docker compose restart

# ── Suivre les logs ───────────────────────────────────────────────────────────
logs:
	docker compose logs -f

# ── Ouvrir un shell dans le conteneur backend ─────────────────────────────────
shell:
	docker compose exec backend bash

# ── Actions du site-manager ───────────────────────────────────────────────────
backup:
	docker compose run --rm site-manager backup

restore:
	docker compose run --rm -e RESTORE=1 site-manager restore

update:
	docker compose run --rm site-manager update

configure:
	docker compose run --rm site-manager configure
