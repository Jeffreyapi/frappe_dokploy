#!/usr/bin/env bash
set -Eeuo pipefail
trap 'printf "Setup failed at line %s. Resolve the error and rerun this script.\n" "$LINENO" >&2' ERR
PROJECT_ROOT="$(pwd -P)"
BENCH_DIR="${BENCH_DIR:-$HOME/frappe-bench}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Parse literal dotenv values; never source an environment file as shell code.
load_env() {
  local line key value
  while IFS= read -r line || [[ -n "$line" ]]; do
    line="${line%$'\r'}"
    [[ "$line" =~ ^([A-Za-z_][A-Za-z0-9_]*)=(.*)$ ]] || continue
    key="${BASH_REMATCH[1]}"; value="${BASH_REMATCH[2]}"
    if [[ "$value" == \"*\" || "$value" == \'*\' ]]; then value="${value:1:${#value}-2}"; fi
    export "$key=$value"
  done < "$1"
}
if [[ -f .env ]]; then load_env .env; else load_env .env.example; fi
: "${APP_NAME:?APP_NAME required}"
: "${DB_ROOT_PASSWORD:?DB_ROOT_PASSWORD required}"
: "${ADMIN_PASSWORD:?ADMIN_PASSWORD required}"
FRAPPE_BRANCH="${FRAPPE_BRANCH:-v16.33.1}"
FRAPPE_REVISION="${FRAPPE_REVISION:-988e54f3c4c291e2077a83809663f123731abe76}"
SITE_NAME="${SITE_NAME:-development.localhost}"
DB_HOST="${DB_HOST:-db}"
DB_PORT="${DB_PORT:-3306}"
REDIS_CACHE="${REDIS_CACHE:-redis-cache:6379}"
REDIS_QUEUE="${REDIS_QUEUE:-redis-queue:6379}"
[[ "$SITE_NAME" =~ ^[a-zA-Z0-9][a-zA-Z0-9.-]*$ ]] || { echo "Invalid site name" >&2; exit 1; }
[[ -f "$PROJECT_ROOT/pyproject.toml" ]] || { echo "Scaffold the app before running setup" >&2; exit 1; }
wait-for-it -t 120 "$DB_HOST:$DB_PORT"
wait-for-it -t 120 "$REDIS_CACHE"
wait-for-it -t 120 "$REDIS_QUEUE"

if [[ ! -d "$BENCH_DIR" ]]; then
  bench init "$BENCH_DIR" --python "${PYTHON_VERSION:-python3.14}" \
    --frappe-branch "$FRAPPE_BRANCH" --skip-redis-config-generation --skip-assets
fi
# A partial bench must never be accepted merely because its directory exists.
[[ -x "$BENCH_DIR/env/bin/python" && -f "$BENCH_DIR/sites/common_site_config.json" ]] || {
  echo "Incomplete bench at $BENCH_DIR. Archive it or use rebuild.sh --reset." >&2; exit 1;
}
[[ "$(git -C "$BENCH_DIR/apps/frappe" rev-parse HEAD)" == "$FRAPPE_REVISION" ]] || {
  echo "Frappe revision mismatch. Recreate the bench after preserving local changes." >&2; exit 1;
}
cd "$BENCH_DIR"
bench set-config -g db_host "$DB_HOST"
bench set-config -gp db_port "$DB_PORT"
bench set-config -g redis_cache "redis://$REDIS_CACHE"
bench set-config -g redis_queue "redis://$REDIS_QUEUE"
bench set-config -g redis_socketio "redis://$REDIS_QUEUE"
bench set-config -gp developer_mode 1
bench set-config -gp serve_default_site true
python3 "$SCRIPT_DIR/app_sources.py" --project "$PROJECT_ROOT" --bench "$BENCH_DIR" --development
"$BENCH_DIR/env/bin/python" -m pip install debugpy
bench build
if [[ ! -d "sites/$SITE_NAME" ]]; then
  bench new-site "$SITE_NAME" --db-root-username root --db-root-password "$DB_ROOT_PASSWORD" \
    --mariadb-user-host-login-scope='%' --admin-password "$ADMIN_PASSWORD"
else
  [[ -f "sites/$SITE_NAME/site_config.json" ]] || { echo "Incomplete site directory" >&2; exit 1; }
  bench --site "$SITE_NAME" list-apps --format json >/dev/null
fi
python3 "$SCRIPT_DIR/app_sources.py" --project "$PROJECT_ROOT" --bench "$BENCH_DIR" --site "$SITE_NAME"
bench --site "$SITE_NAME" migrate
bench use "$SITE_NAME"
bench --site "$SITE_NAME" clear-cache
printf 'Setup complete. Run: cd %s && bench start\n' "$BENCH_DIR"
