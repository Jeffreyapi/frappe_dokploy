#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
#  frappe_dokploy — site.sh
#  Gestion du cycle de vie d'un site Frappe.
#  Générique : aucune référence à un projet spécifique.
#
#  Actions :
#    create      Crée le site + installe les apps + migrate/build
#    restore     Restaure depuis S3 + installe les apps + migrate/build
#    update      Maintenance ON → neutralise fixtures → migrate → build → OFF
#    backup      Backup local + upload S3
#    configure   Initialise/met à jour common_site_config.json
# =============================================================================

# ── Paramètres (tous surchargeables par env) ──────────────────────────────────
APPS_DIR="${APPS_DIR:-/home/frappe/frappe-bench/apps}"
SITE_NAME="${SITE_NAME:?SITE_NAME est requis}"
DB_HOST="${DB_HOST:-db}"
DB_PORT="${DB_PORT:-3306}"
DB_ROOT_PASSWORD="${DB_ROOT_PASSWORD:?DB_ROOT_PASSWORD est requis}"
ADMIN_PASSWORD="${ADMIN_PASSWORD:-admin}"
S3_ENDPOINT_URL="${S3_ENDPOINT_URL:-}"
S3_BACKUP_BUCKET="${S3_BACKUP_BUCKET:-}"
S3_BACKUP_ACCESS_KEY="${S3_BACKUP_ACCESS_KEY:-}"
S3_BACKUP_SECRET_KEY="${S3_BACKUP_SECRET_KEY:-}"
ENVIRONMENT="${ENVIRONMENT:-dev}"
APPS="${APPS:-}"
UPDATE_APPS="${UPDATE_APPS:-}"
NEUTRALIZE_MODE="${NEUTRALIZE_MODE:-rm}"

# Fichier de patterns de fixtures à neutraliser (un pattern par ligne)
SKIP_FIXTURES_FILE="${SKIP_FIXTURES_FILE:-/opt/frappe-deploy-config/skip_fixtures.list}"
# Patterns inline supplémentaires (CSV, optionnel)
SKIP_FIXTURES="${SKIP_FIXTURES:-}"

MAINT_SET=0

# ── Helpers ───────────────────────────────────────────────────────────────────
log()  { echo "[$(date +'%F %T')] $*"; }
die()  { echo "ERR: $*" >&2; exit 1; }

usage() {
  cat <<'USAGE'
Usage:
  site.sh create      Crée le site (+ apps-install, migrate/build)
  site.sh restore     Restaure depuis S3 (+ apps-install, migrate/build)
  site.sh update      Maintenance ON → neutralize → migrate → build → OFF
  site.sh backup      Backup local + upload S3 si configuré
  site.sh configure   Initialise/met à jour common_site_config.json
USAGE
}

wait_prereqs() {
  log "Attente DB & Redis..."
  wait-for-it -t 120 "${DB_HOST}:${DB_PORT}"
  wait-for-it -t 120 redis-cache:6379
  wait-for-it -t 120 redis-queue:6379
}

ensure_common_ready() {
  log "Vérification sites/common_site_config.json..."
  local start
  start=$(date +%s)
  until [[ -n $(grep -hs ^ sites/common_site_config.json | jq -r ".db_host // empty") ]] && \
        [[ -n $(grep -hs ^ sites/common_site_config.json | jq -r ".redis_cache // empty") ]] && \
        [[ -n $(grep -hs ^ sites/common_site_config.json | jq -r ".redis_queue // empty") ]]; do
    sleep 5
    if (( $(date +%s) - start > 120 )); then
      die "common_site_config.json introuvable/incomplet après 120s"
    fi
  done
  log "common_site_config.json OK"
}

enable_maintenance() {
  log "Maintenance ON ($SITE_NAME)"
  bench --site "$SITE_NAME" set-config -p maintenance_mode 1
  bench --site "$SITE_NAME" set-config -p pause_scheduler 1
  MAINT_SET=1
}

disable_maintenance() {
  if [[ "$MAINT_SET" -eq 1 ]]; then
    log "Maintenance OFF ($SITE_NAME)"
    bench --site "$SITE_NAME" set-config -p maintenance_mode 0
    bench --site "$SITE_NAME" set-config -p pause_scheduler 0
    MAINT_SET=0
  fi
}

require_site_exists() {
  [[ -d "sites/$SITE_NAME" ]] || die "Le site '$SITE_NAME' est introuvable. Exécutez d'abord: site.sh create"
}

# ── Normalisation de listes (virgules → espaces) ──────────────────────────────
normalize_list() {
  echo "$1" | tr ',' ' ' | xargs -n1 | paste -sd ' ' -
}

# ── Fixtures : découverte dynamique par glob ───────────────────────────────────
# Lit les patterns depuis SKIP_FIXTURES_FILE + SKIP_FIXTURES inline.
# Pour chaque pattern, cherche les fichiers correspondants dans APPS_DIR
# en utilisant find + fnmatch insensible à la casse.
# Aucun chemin en dur — fonctionne pour n'importe quelle app Frappe.
collect_fixture_patterns() {
  local csv="$SKIP_FIXTURES"
  if [[ -f "$SKIP_FIXTURES_FILE" ]]; then
    local file_csv
    file_csv="$(grep -v -E '^\s*($|#)' "$SKIP_FIXTURES_FILE" | paste -sd, - || true)"
    [[ -n "$file_csv" ]] && csv="${csv:+$csv,}$file_csv"
  fi
  echo "$csv" | sed 's/[[:space:]]*,[[:space:]]*/,/g'
}

neutralize_fixtures() {
  local mode="$NEUTRALIZE_MODE"
  local patterns_csv
  patterns_csv=$(collect_fixture_patterns)

  if [[ -z "$patterns_csv" ]]; then
    log "Aucun pattern de fixture défini — neutralisation ignorée"
    return 0
  fi

  log "Neutralisation des fixtures (mode=$mode, patterns=$patterns_csv)"

  # Parcourir chaque pattern
  IFS=',' read -ra PATTERNS <<< "$patterns_csv"
  for pattern in "${PATTERNS[@]}"; do
    pattern="$(echo "$pattern" | xargs)"  # trim
    [[ -z "$pattern" ]] && continue

    # Recherche insensible à la casse dans tous les sous-dossiers fixtures/
    while IFS= read -r fixture_file; do
      if [[ -f "$fixture_file" ]]; then
        case "$mode" in
          rm)
            log "Suppression: $fixture_file"
            rm -f -- "$fixture_file"
            ;;
          empty)
            log "Neutralisation ([]): $fixture_file"
            printf '[]' > "$fixture_file"
            ;;
          *)
            log "NEUTRALIZE_MODE inconnu ($mode), fallback → rm"
            rm -f -- "$fixture_file"
            ;;
        esac
      fi
    done < <(find "$APPS_DIR" -type f -path "*/fixtures/*.json" \
               -iname "${pattern}.json" 2>/dev/null || true)
  done

  log "Neutralisation des fixtures terminée"
}

# ── Squelette du site ─────────────────────────────────────────────────────────
ensure_site_skeleton() {
  local site_path="sites/$SITE_NAME"
  if [[ ! -d "$site_path" ]]; then
    log "Création du squelette du site $SITE_NAME"
    bench new-site \
      --mariadb-user-host-login-scope='%' \
      --admin-password="$ADMIN_PASSWORD" \
      --db-root-username=root \
      --db-root-password="$DB_ROOT_PASSWORD" \
      "$SITE_NAME"
  fi
}

# ── Installation des apps ─────────────────────────────────────────────────────
install_apps_if_requested() {
  local apps norm installed
  apps="$APPS"
  [[ -n "$apps" ]] || return 0
  norm=$(normalize_list "$apps")
  installed=$(bench --site "$SITE_NAME" list-apps || true)
  for app in $norm; do
    if echo "$installed" | awk '{print $1}' | grep -qx "$app"; then
      log "App déjà installée: $app"
    else
      log "Installation de l'app: $app"
      bench --site "$SITE_NAME" install-app "$app"
    fi
  done
}

# ── Configuration commune ─────────────────────────────────────────────────────
configure_common() {
  log "Configuration commune (bench set-config -g)"
  bench set-config -g db_host "${DB_HOST:-db}"
  bench set-config -gp db_port "${DB_PORT:-3306}"
  [[ -n "${REDIS_CACHE:-}" ]] && bench set-config -g redis_cache "redis://${REDIS_CACHE}"
  [[ -n "${REDIS_QUEUE:-}" ]] && bench set-config -g redis_queue "redis://${REDIS_QUEUE}"
  [[ -n "${REDIS_QUEUE:-}" ]] && bench set-config -g redis_socketio "redis://${REDIS_QUEUE}"
  [[ -n "${SOCKETIO_PORT:-}" ]] && bench set-config -gp socketio_port "${SOCKETIO_PORT}"
  log "Configuration commune mise à jour"
}

# ── Migrate + build + clear cache ─────────────────────────────────────────────
migrate_build_clear() {
  log "Neutralisation des fixtures avant migrate"
  neutralize_fixtures

  log "bench migrate"
  bench --site "$SITE_NAME" migrate

  log "bench build"
  if [[ -n "${BUILD_APPS:-}" ]]; then
    # Build ciblé sur les apps demandées (CSV)
    # shellcheck disable=SC2086
    bench --site "$SITE_NAME" build --apps ${BUILD_APPS//,/ } --hard-link --production
  else
    bench --site "$SITE_NAME" build --hard-link --production
  fi

  log "Nettoyage des caches"
  bench --site "$SITE_NAME" clear-cache
  bench --site "$SITE_NAME" clear-website-cache
}

# ── Backup ────────────────────────────────────────────────────────────────────
backup_local() {
  require_site_exists
  log "bench backup"
  bench --site "$SITE_NAME" backup
  echo "sites/$SITE_NAME/private/backups"
}

backup_upload_s3() {
  local backup_dir="$1"
  [[ -n "$S3_BACKUP_BUCKET" ]]   || { log "S3_BACKUP_BUCKET vide → upload S3 ignoré"; return 0; }
  [[ -n "$S3_ENDPOINT_URL" ]]    || { log "S3_ENDPOINT_URL vide → upload S3 ignoré"; return 0; }

  export AWS_ACCESS_KEY_ID="$S3_BACKUP_ACCESS_KEY"
  export AWS_SECRET_ACCESS_KEY="$S3_BACKUP_SECRET_KEY"

  local ts prefix
  ts=$(date +%Y%m%d-%H%M%S)
  prefix="s3://$S3_BACKUP_BUCKET/$ts/"
  log "Upload vers $prefix"

  shopt -s nullglob
  local files=()
  files+=("$backup_dir"/*-database.sql.gz)
  files+=("$backup_dir"/*-files.tar)
  files+=("$backup_dir"/*-private-files.tar)
  shopt -u nullglob

  if (( ${#files[@]} == 0 )); then
    log "Aucun fichier de backup à uploader depuis $backup_dir"
    return 0
  fi

  for f in "${files[@]}"; do
    log "Upload: $f"
    s5cmd --endpoint-url "$S3_ENDPOINT_URL" cp "$f" "$prefix"
  done
  log "Upload S3 terminé"
}

# ── Restauration depuis S3 ────────────────────────────────────────────────────
discover_and_download_backup() {
  [[ -n "$S3_BACKUP_BUCKET" ]] || die "S3_BACKUP_BUCKET manquant"
  [[ -n "$S3_ENDPOINT_URL"  ]] || die "S3_ENDPOINT_URL manquant"

  export AWS_ACCESS_KEY_ID="$S3_BACKUP_ACCESS_KEY"
  export AWS_SECRET_ACCESS_KEY="$S3_BACKUP_SECRET_KEY"

  log "Recherche du dernier backup sur s3://$S3_BACKUP_BUCKET/"
  local last_dir
  last_dir=$(s5cmd --endpoint-url "$S3_ENDPOINT_URL" ls "s3://$S3_BACKUP_BUCKET/" \
              | awk '{print $NF}' | grep '/$' | sort | tail -n1 | tr -d '/')
  [[ -n "$last_dir" ]] || die "Aucun backup trouvé"
  log "Dossier: $last_dir"

  local list db_file priv_file pub_file cfg_bak
  list=$(s5cmd --endpoint-url "$S3_ENDPOINT_URL" ls "s3://$S3_BACKUP_BUCKET/$last_dir/")
  db_file=$(echo "$list"   | awk '{print $NF}' | grep -- '-database\.sql\.gz$'   | head -n1 | tr -d '\r')
  priv_file=$(echo "$list" | awk '{print $NF}' | grep -- '-private-files\.tar$'  | head -n1 | tr -d '\r' || true)
  pub_file=$(echo "$list"  | awk '{print $NF}' | grep -- '-files\.tar$' | grep -v 'private' | head -n1 | tr -d '\r' || true)
  cfg_bak=$(echo "$list"   | awk '{print $NF}' | grep -E 'site_config_backup\.json$' | head -n1 | tr -d '\r' || true)

  [[ -n "$db_file" ]] || die "Dump SQL introuvable dans $last_dir"

  local dest=/tmp/backup
  mkdir -p "$dest"
  s5cmd --endpoint-url "$S3_ENDPOINT_URL" cp "s3://$S3_BACKUP_BUCKET/$last_dir/$db_file" "$dest/"
  [[ -n "$priv_file" ]] && s5cmd --endpoint-url "$S3_ENDPOINT_URL" cp "s3://$S3_BACKUP_BUCKET/$last_dir/$priv_file" "$dest/"
  [[ -n "$pub_file"  ]] && s5cmd --endpoint-url "$S3_ENDPOINT_URL" cp "s3://$S3_BACKUP_BUCKET/$last_dir/$pub_file"  "$dest/"
  [[ -n "$cfg_bak"   ]] && s5cmd --endpoint-url "$S3_ENDPOINT_URL" cp "s3://$S3_BACKUP_BUCKET/$last_dir/$cfg_bak"  "$dest/"

  export FRAPPE_BACKUP_DIR="$dest"
  export FRAPPE_DB_FILE="$db_file"
  export FRAPPE_PRIV_FILE="$priv_file"
  export FRAPPE_PUB_FILE="$pub_file"
  export FRAPPE_SITE_CFG_BAK_FILE="$cfg_bak"

  log "Fichiers copiés dans $dest"
}

restore_from_s3() {
  discover_and_download_backup
  ensure_site_skeleton

  log "bench restore"
  bench --site "$SITE_NAME" --force restore "$FRAPPE_BACKUP_DIR/$FRAPPE_DB_FILE" \
    ${FRAPPE_PRIV_FILE:+--with-private-files "$FRAPPE_BACKUP_DIR/$FRAPPE_PRIV_FILE"} \
    ${FRAPPE_PUB_FILE:+--with-public-files  "$FRAPPE_BACKUP_DIR/$FRAPPE_PUB_FILE"} \
    --db-root-username=root \
    --db-root-password="$DB_ROOT_PASSWORD"
}

update_encryption_key_from_backup() {
  # En prod uniquement, si un site_config_backup.json est présent
  if [[ "${ENVIRONMENT,,}" != "prod" ]]; then
    log "ENVIRONMENT=$ENVIRONMENT → pas de mise à jour encryption_key"
    return 0
  fi
  [[ -z "${FRAPPE_SITE_CFG_BAK_FILE:-}" ]] && { log "Aucun site_config_backup.json → skip"; return 0; }

  local backup_cfg="$FRAPPE_BACKUP_DIR/$FRAPPE_SITE_CFG_BAK_FILE"
  local site_cfg="sites/$SITE_NAME/site_config.json"

  [[ -f "$backup_cfg" ]] || { log "Fichier backup introuvable: $backup_cfg → skip"; return 0; }
  [[ -f "$site_cfg"   ]] || { log "site_config.json introuvable: $site_cfg → skip"; return 0; }

  local ek
  ek=$(jq -r '.encryption_key // empty' "$backup_cfg")
  [[ -z "$ek" || "$ek" == "null" ]] && { log "encryption_key absent dans $backup_cfg → skip"; return 0; }

  log "Mise à jour encryption_key depuis backup"
  local tmp
  tmp=$(mktemp)
  jq --arg ek "$ek" '.encryption_key=$ek' "$site_cfg" > "$tmp"
  mv "$tmp" "$site_cfg"
  chmod 640 "$site_cfg"
}

# ── Main ──────────────────────────────────────────────────────────────────────
[[ "${FRAPPE_DEBUG:-0}" = "1" ]] && set -x

action="${1:-}"
if [[ -z "$action" ]]; then
  action="${RESTORE:-0}"
  [[ "${RESTORE,,}" =~ ^(1|true|yes|on)$ ]] && action="restore" || action="update"
fi

log "ENVIRONMENT=${ENVIRONMENT} | RESTORE=${RESTORE:-0} | ACTION=${action}"

case "$action" in
  create)
    wait_prereqs
    ensure_common_ready
    ensure_site_skeleton
    install_apps_if_requested
    BUILD_APPS="" migrate_build_clear
    ;;

  restore)
    wait_prereqs
    ensure_common_ready
    ensure_site_skeleton
    enable_maintenance
    trap 'disable_maintenance' EXIT
    restore_from_s3
    update_encryption_key_from_backup
    install_apps_if_requested
    BUILD_APPS="" migrate_build_clear
    disable_maintenance
    trap - EXIT
    ;;

  update)
    wait_prereqs
    ensure_common_ready
    require_site_exists
    enable_maintenance
    trap 'disable_maintenance' EXIT
    BUILD_APPS="$UPDATE_APPS" migrate_build_clear
    disable_maintenance
    trap - EXIT
    ;;

  backup)
    wait_prereqs
    ensure_common_ready
    require_site_exists
    dir=$(backup_local)
    backup_upload_s3 "$dir"
    ;;

  configure)
    wait_prereqs
    configure_common
    ;;

  *)
    usage
    exit 1
    ;;
esac

log "Done."
