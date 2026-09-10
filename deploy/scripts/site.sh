#!/usr/bin/env bash
set -Eeuo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
log() { printf '[site] %s\n' "$*" >&2; }
die() { log "$*"; exit 1; }

wait_prereqs() {
  wait-for-it -t 120 "${DB_HOST:-db}:${DB_PORT:-3306}"
  wait-for-it -t 120 "${REDIS_CACHE:-redis-cache:6379}"
  wait-for-it -t 120 "${REDIS_QUEUE:-redis-queue:6379}"
}
configure_common() {
  bench set-config -g db_host "${DB_HOST:-db}"
  bench set-config -gp db_port "${DB_PORT:-3306}"
  bench set-config -g redis_cache "redis://${REDIS_CACHE:-redis-cache:6379}"
  bench set-config -g redis_queue "redis://${REDIS_QUEUE:-redis-queue:6379}"
  bench set-config -g redis_socketio "redis://${REDIS_QUEUE:-redis-queue:6379}"
  bench set-config -gp socketio_port "${SOCKETIO_PORT:-9000}"
}
require_site_exists() {
  [[ -f "sites/$SITE_NAME/site_config.json" ]] || die "Incomplete or missing site: $SITE_NAME"
  bench --site "$SITE_NAME" list-apps --format json >/dev/null
}
ensure_site() {
  if [[ ! -d "sites/$SITE_NAME" ]]; then
    bench new-site "$SITE_NAME" --db-root-username root --db-root-password "$DB_ROOT_PASSWORD" \
      --mariadb-user-host-login-scope='%' --admin-password "$ADMIN_PASSWORD"
  fi
  require_site_exists
}
enable_maintenance() {
  bench --site "$SITE_NAME" set-config -p maintenance_mode 1
  bench --site "$SITE_NAME" set-config -p pause_scheduler 1
}
disable_maintenance() {
  bench --site "$SITE_NAME" set-config -p pause_scheduler 0
  bench --site "$SITE_NAME" set-config -p maintenance_mode 0
}
migration_failed() {
  local status=$?
  trap - ERR
  # Do not reopen a partially migrated/restored database.
  enable_maintenance || log "Could not reassert maintenance; stop application services"
  log "Operation failed ($status). Maintenance retained. Fix the cause and rerun update."
  exit "$status"
}
install_apps() {
  local apps installed app
  apps="${APPS:-}"
  if [[ -z "$apps" ]]; then
    apps="$(python3 -c 'import json; print(",".join(a["name"] for a in json.load(open("/opt/apps-manifest.json"))))')"
  fi
  [[ -n "$apps" ]] || die "No apps selected for installation"
  installed="$(bench --site "$SITE_NAME" list-apps --format json)"
  IFS=',' read -ra app_names <<< "$apps"
  for app in "${app_names[@]}"; do
    [[ "$app" =~ ^[a-z][a-z0-9_]*$ ]] || die "Invalid app name"
    if ! python3 -c 'import json,sys; sys.exit(sys.argv[1] not in json.loads(sys.argv[2])[sys.argv[3]])' "$app" "$installed" "$SITE_NAME"; then
      bench --site "$SITE_NAME" install-app "$app"
    fi
  done
  installed="$(bench --site "$SITE_NAME" list-apps --format json)"
  python3 -c 'import json,sys; missing=set(sys.argv[1].split(","))-set(json.loads(sys.argv[2])[sys.argv[3]]); assert not missing, missing' "$apps" "$installed" "$SITE_NAME"
}
migrate_site() {
  # Assets are built and checked in CI, never rebuilt on a production host.
  [[ -z "${SKIP_FIXTURES:-}" ]] || die "Runtime fixture mutation is unsupported; fix fixtures in source"
  bench --site "$SITE_NAME" migrate
  cp -a /opt/image-assets/. sites/assets/
  bench --site "$SITE_NAME" clear-cache
  bench --site "$SITE_NAME" clear-website-cache
}
backup_local() {
  python3 "$SCRIPT_DIR/backup.py" create
}
main() {
  : "${SITE_NAME:?SITE_NAME required}"
  : "${DEPLOYMENT_ID:?DEPLOYMENT_ID required}"
  : "${DB_ROOT_PASSWORD:?DB_ROOT_PASSWORD required}"
  : "${ADMIN_PASSWORD:?ADMIN_PASSWORD required}"
  [[ "$SITE_NAME" =~ ^[a-zA-Z0-9][a-zA-Z0-9.-]*$ && "$SITE_NAME" != *..* ]] || die "Invalid site name"
  local action="${1:-update}"
  wait_prereqs
  configure_common
  if [[ "$action" == configure ]]; then return; fi
  # Serialize lifecycle operations across site-manager containers sharing this volume.
  mkdir -p sites/.lifecycle-locks
  exec 9>"sites/.lifecycle-locks/$SITE_NAME"
  flock -n 9 || die "Another lifecycle operation is already running"
  case "$action" in
    create)
      ensure_site
      enable_maintenance
      trap migration_failed ERR
      install_apps
      migrate_site
      disable_maintenance
      trap - ERR
      ;;
    update)
      require_site_exists
      enable_maintenance
      trap migration_failed ERR
      install_apps
      migrate_site
      disable_maintenance
      trap - ERR
      ;;
    restore)
      ensure_site
      enable_maintenance
      trap migration_failed ERR
      if [[ -n "${RESTORE_DIRECTORY:-}" ]]; then
        python3 "$SCRIPT_DIR/backup.py" restore --directory "$RESTORE_DIRECTORY"
      else
        python3 "$SCRIPT_DIR/backup.py" restore
      fi
      install_apps
      migrate_site
      disable_maintenance
      trap - ERR
      ;;
    backup)
      require_site_exists
      backup_local
      ;;
    *) die "Expected create, update, restore, backup or configure";;
  esac
  log "Operation completed: $action"
}
if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then main "$@"; fi
