#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
#  frappe_dokploy — init.sh
#  Orchestrateur du site-manager.
#  Sélectionne automatiquement l'action : configure → create | restore | update
#  ou délègue à site.sh si une action explicite est demandée.
# =============================================================================

log() { echo "[init $(date +'%F %T')] $*"; }
die() { echo "[init ERR] $*" >&2; exit 1; }

SCRIPT_DIR="${SCRIPT_DIR:-/opt/frappe-deploy}"
SITE_SH="${SCRIPT_DIR}/site.sh"

SITE_NAME="${SITE_NAME:?SITE_NAME est requis}"
RESTORE="${RESTORE:-0}"
ACTION_OVERRIDE="${ACTION:-}"

# Si une action explicite est passée en argument, déléguer directement
if [[ "${1:-}" != "" ]]; then
  log "Action explicite demandée: $1"
  exec "$SITE_SH" "$1"
fi

# Si ACTION env est définie (et pas 'auto'), déléguer
if [[ -n "$ACTION_OVERRIDE" && "${ACTION_OVERRIDE,,}" != "auto" ]]; then
  log "ACTION=$ACTION_OVERRIDE (env) → délégation"
  exec "$SITE_SH" "$ACTION_OVERRIDE"
fi

log "Initialisation automatique (configure → restore | create | update)"

# 1. Toujours : s'assurer de la configuration commune (idempotent)
"$SITE_SH" configure

# 2. Choisir l'action selon l'état du site et de RESTORE
SITE_PATH="sites/$SITE_NAME"

if [[ "${RESTORE,,}" =~ ^(1|true|yes|on)$ ]]; then
  log "Mode RESTORE=1 → restauration du site"
  exec "$SITE_SH" restore
fi

if [[ -d "$SITE_PATH" ]]; then
  log "Site $SITE_NAME déjà présent → update"
  exec "$SITE_SH" update
else
  log "Site $SITE_NAME absent → create"
  exec "$SITE_SH" create
fi
