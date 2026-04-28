#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
#  devcontainer-setup.sh — environnement de développement Frappe
#
#  Ce script vit dans le submodule frappe_deploy/scripts/.
#  Il est JAMAIS copié dans le repo projet.
#
#  Appelé par : postCreateCommand dans .devcontainer/devcontainer.json
#  Lancé depuis : la racine du repo projet (workspaceFolder)
#
#  Lit la configuration depuis .env (à la racine du projet).
#  Idempotent : peut être relancé sans danger.
#
#  Étapes :
#    1. MariaDB + Redis
#    2. uv + frappe-bench CLI
#    3. bench init (avec python et branche configurés)
#    4. Config Redis/MariaDB dans common_site_config
#    5. Apps publiques depuis apps.json
#    6. bench new-app (non-interactif via printf) — si pyproject.toml absent
#    7. Copie de l'app dans le workspace (cp -n, sans écraser l'existant)
#    8. Symlink + pip install -e
#    9. bench new-site (non-interactif, flags complets)
#   10. bench install-app
#   11. Finalisation
# =============================================================================

# ── Racine du projet (là où postCreateCommand est lancé) ─────────────────────
PROJECT_ROOT="${PWD}"

# ── Charger .env si présent ───────────────────────────────────────────────────
# Extrait clé et valeur séparément — n'interprète jamais la valeur comme du code.
# Gère : espaces dans les valeurs, commentaires inline, lignes vides, quotes.
_load_env() {
  local file="$1"
  local key value line
  while IFS= read -r line || [ -n "$line" ]; do
    # ignorer lignes vides et commentaires
    [[ "$line" =~ ^[[:space:]]*$ ]]  && continue
    [[ "$line" =~ ^[[:space:]]*#  ]] && continue
    # n'accepter que KEY=... avec un identifiant valide
    [[ "$line" =~ ^([A-Za-z_][A-Za-z0-9_]*)=(.*)$ ]] || continue
    key="${BASH_REMATCH[1]}"
    value="${BASH_REMATCH[2]}"
    # retirer les guillemets englobants éventuels (" ou ')
    value="${value%\"}"  ; value="${value#\"}"
    value="${value%\'}"  ; value="${value#\'}"
    export "$key"="$value"
  done < "$file"
}

if [ -f "$PROJECT_ROOT/.env" ]; then
  _load_env "$PROJECT_ROOT/.env"
elif [ -f "$PROJECT_ROOT/.env.example" ]; then
  echo "[warn] .env absent — utilisation de .env.example pour les valeurs par défaut"
  _load_env "$PROJECT_ROOT/.env.example"
fi

# ── Variables avec valeurs par défaut ─────────────────────────────────────────
APP_NAME="${APP_NAME:-$(basename "$PROJECT_ROOT")}"
WORKSPACE="/workspaces/${APP_NAME}"
BENCH_DIR="$HOME/frappe-bench"

PYTHON_VERSION="${PYTHON_VERSION:-python3.14}"
FRAPPE_BRANCH="${FRAPPE_BRANCH:-version-16}"
SITE_NAME="${SITE_NAME:-development.localhost}"
DB_ROOT_PASSWORD="${DB_ROOT_PASSWORD:-123}"
ADMIN_PASSWORD="${ADMIN_PASSWORD:-admin}"

APP_TITLE="${APP_TITLE:-$APP_NAME}"
APP_DESCRIPTION="${APP_DESCRIPTION:-$APP_NAME}"
APP_PUBLISHER="${APP_PUBLISHER:-EasyTalents}"
APP_EMAIL="${APP_EMAIL:-admin@easytalents.fr}"
APP_LICENSE="${APP_LICENSE:-apache-2.0}"

export PATH="$HOME/.local/bin:$PATH"

# ── Helpers ───────────────────────────────────────────────────────────────────
log()  { echo "[setup $(date +'%T')] $*"; }
ok()   { echo "[setup $(date +'%T')] ✓ $*"; }
skip() { echo "[setup $(date +'%T')] — skip: $*"; }

log "Projet   : $APP_NAME"
log "Python   : $PYTHON_VERSION"
log "Frappe   : $FRAPPE_BRANCH"
log "Site     : $SITE_NAME"
echo ""

# ═════════════════════════════════════════════════════════════════════════════
# 1. MariaDB + Redis
# ═════════════════════════════════════════════════════════════════════════════
log "Démarrage de MariaDB..."
sudo service mariadb start 2>/dev/null || skip "MariaDB déjà lancé"

if mysql -u root -p"${DB_ROOT_PASSWORD}" -e "SELECT 1" >/dev/null 2>&1; then
  skip "MariaDB root déjà configuré"
else
  log "Configuration du mot de passe root MariaDB..."
  sudo mysql --connect-expired-password -u root <<-SQL || skip "Root déjà configuré"
	ALTER USER 'root'@'localhost' IDENTIFIED BY '${DB_ROOT_PASSWORD}';
	FLUSH PRIVILEGES;
SQL
fi

log "Démarrage de Redis..."
sudo service redis-server start 2>/dev/null || skip "Redis déjà lancé"

# ═════════════════════════════════════════════════════════════════════════════
# 2. uv + frappe-bench CLI
# ═════════════════════════════════════════════════════════════════════════════
if ! command -v uv >/dev/null 2>&1; then
  log "Installation de uv..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
else
  skip "uv $(uv --version)"
fi

if ! command -v bench >/dev/null 2>&1; then
  log "Installation de frappe-bench..."
  uv tool install frappe-bench
  export PATH="$HOME/.local/bin:$PATH"
else
  skip "bench $(bench --version 2>/dev/null)"
fi

# ═════════════════════════════════════════════════════════════════════════════
# 3. bench init
# ═════════════════════════════════════════════════════════════════════════════
if [ ! -d "$BENCH_DIR" ]; then
  log "bench init (frappe $FRAPPE_BRANCH, $PYTHON_VERSION)..."
  bench init "$BENCH_DIR" \
    --python "$PYTHON_VERSION" \
    --frappe-branch "$FRAPPE_BRANCH" \
    --skip-redis-config-generation
  ok "bench init OK"
else
  skip "bench déjà présent dans $BENCH_DIR"
fi

cd "$BENCH_DIR"

# ═════════════════════════════════════════════════════════════════════════════
# 4. Config Redis + MariaDB dans common_site_config
# ═════════════════════════════════════════════════════════════════════════════
if ! grep -q '"db_host"' sites/common_site_config.json 2>/dev/null; then
  log "Configuration bench (Redis + MariaDB)..."
  bench set-config -g  db_host        "127.0.0.1"
  bench set-config -gp db_port        3306
  bench set-config -g  redis_cache    "redis://127.0.0.1:6379"
  bench set-config -g  redis_queue    "redis://127.0.0.1:6379"
  bench set-config -g  redis_socketio "redis://127.0.0.1:6379"
  bench set-config -gp developer_mode 1
  ok "Config bench OK"
else
  skip "common_site_config déjà configuré"
fi

# ═════════════════════════════════════════════════════════════════════════════
# 5. Apps publiques depuis apps.json
# ═════════════════════════════════════════════════════════════════════════════
log "Lecture de apps.json..."
python3 - "$PROJECT_ROOT" "$BENCH_DIR" <<'PYEOF'
import json, subprocess, sys
from pathlib import Path

project = Path(sys.argv[1])
bench   = Path(sys.argv[2])
apps_file = project / "apps.json"

if not apps_file.exists():
    print(f"  [skip] apps.json absent dans {project}")
    sys.exit(0)

for app in json.loads(apps_file.read_text()):
    url    = app["url"]
    branch = app.get("branch", "main")
    if "${GH_PAT}" in url or "GH_PAT" in url:
        name = url.rstrip("/").split("/")[-1].replace(".git", "")
        print(f"  [skip] app privée '{name}' — installée depuis le workspace")
        continue
    app_name = url.rstrip("/").split("/")[-1].replace(".git", "")
    if (bench / "apps" / app_name).exists():
        print(f"  [skip] {app_name} déjà présent")
        continue
    print(f"  [get-app] {app_name} (branch: {branch})")
    subprocess.run(["bench", "get-app", "--branch", branch, url], check=True)
PYEOF

# ═════════════════════════════════════════════════════════════════════════════
# 6. bench new-app — uniquement si l'app n'est pas encore scaffoldée
#    Utilise printf pour être 100% non-interactif.
#    Ordre des 6 prompts bench new-app :
#      1. App Title       (obligatoire)
#      2. App Description (obligatoire)
#      3. App Publisher   (obligatoire)
#      4. App Email       (obligatoire, format email)
#      5. App License     (valeur acceptée par bench)
#      6. GitHub workflow (N = on a le nôtre ; répondre y demanderait un 7e prompt : branch)
# ═════════════════════════════════════════════════════════════════════════════
if [ ! -f "$WORKSPACE/pyproject.toml" ] && [ ! -f "$WORKSPACE/setup.py" ]; then
  log "bench new-app $APP_NAME (non-interactif)..."

  # Sanitiser les valeurs : bench n'accepte que [A-Za-z0-9 _] pour le titre,
  # et un email valide. On nettoie plutôt que de bloquer.
  _safe_title=$(echo "$APP_TITLE" | tr -cd 'A-Za-z0-9 _' | sed 's/^[^A-Za-z]*//')
  [ -z "$_safe_title" ] && _safe_title="$APP_NAME"
  _safe_desc=$(echo "$APP_DESCRIPTION" | tr -cd 'A-Za-z0-9 _.-')
  [ -z "$_safe_desc" ] && _safe_desc="$APP_NAME"
  # Email : si invalide (pas de @), utiliser le fallback
  echo "$APP_EMAIL" | grep -qE '^[^@]+@[^@]+\.[^@]+$' \
    || APP_EMAIL="admin@easytalents.fr"

  # Libérer le slot apps/ si un symlink ou dossier existe déjà
  [ -L "$BENCH_DIR/apps/$APP_NAME" ] && rm "$BENCH_DIR/apps/$APP_NAME"
  [ -d "$BENCH_DIR/apps/$APP_NAME" ] && rm -rf "$BENCH_DIR/apps/$APP_NAME"

  # 7 prompts bench new-app (v16) :
  #  1. App Title       2. App Description  3. App Publisher
  #  4. App Email       5. App License      6. GitHub Workflow [y/N]
  #  7. Branch Name     (toujours posé, même si réponse N au prompt 6)
  printf "%s\n%s\n%s\n%s\n%s\nN\n%s\n" \
    "$_safe_title" \
    "$_safe_desc" \
    "$APP_PUBLISHER" \
    "$APP_EMAIL" \
    "$APP_LICENSE" \
    "$FRAPPE_BRANCH" \
    | bench new-app "$APP_NAME"

  ok "bench new-app OK"

  # ── Copier dans le workspace (sans écraser les fichiers existants) ─────────
  log "Copie de l'app vers le workspace (cp -n)..."
  cp -rn "$BENCH_DIR/apps/$APP_NAME/." "$WORKSPACE/"
  ok "Copie OK — pense à : git add $APP_NAME/ pyproject.toml && git push"

  # Supprimer le dossier bench (remplacé par le symlink à l'étape suivante)
  rm -rf "$BENCH_DIR/apps/$APP_NAME"
else
  skip "App déjà scaffoldée dans $WORKSPACE"
fi

# ═════════════════════════════════════════════════════════════════════════════
# 7. Symlink workspace → bench/apps
# ═════════════════════════════════════════════════════════════════════════════
if [ ! -L "$BENCH_DIR/apps/$APP_NAME" ]; then
  log "Symlink apps/$APP_NAME → $WORKSPACE"
  ln -sf "$WORKSPACE" "$BENCH_DIR/apps/$APP_NAME"
  ok "Symlink OK"
else
  skip "Symlink apps/$APP_NAME déjà présent"
fi

# ═════════════════════════════════════════════════════════════════════════════
# 8. pip install -e (mode éditable)
# ═════════════════════════════════════════════════════════════════════════════
log "pip install -e..."
"$BENCH_DIR/env/bin/pip" install -e "$BENCH_DIR/apps/$APP_NAME" --quiet
ok "pip install -e OK"

# ═════════════════════════════════════════════════════════════════════════════
# 9. bench new-site (100% non-interactif)
# ═════════════════════════════════════════════════════════════════════════════
if [ ! -d "$BENCH_DIR/sites/$SITE_NAME" ]; then
  log "Création du site $SITE_NAME..."
  bench new-site \
    --db-root-username root \
    --db-root-password "$DB_ROOT_PASSWORD" \
    --mariadb-user-host-login-scope='%' \
    --admin-password "$ADMIN_PASSWORD" \
    "$SITE_NAME"
  ok "Site $SITE_NAME créé"
else
  skip "Site $SITE_NAME déjà existant"
fi

# ═════════════════════════════════════════════════════════════════════════════
# 10. bench install-app (non-interactif)
# ═════════════════════════════════════════════════════════════════════════════
log "Installation des apps sur le site..."
python3 - "$PROJECT_ROOT" "$SITE_NAME" "$BENCH_DIR" "$APP_NAME" <<'PYEOF'
import json, subprocess, sys
from pathlib import Path

project   = Path(sys.argv[1])
site_name = sys.argv[2]
bench_dir = Path(sys.argv[3])
local_app = sys.argv[4]

installed_file = bench_dir / "sites" / site_name / "apps.txt"
installed = set(installed_file.read_text().splitlines()) if installed_file.exists() else set()

apps_file = project / "apps.json"
if apps_file.exists():
    for app in json.loads(apps_file.read_text()):
        url = app["url"]
        if "${GH_PAT}" in url or "GH_PAT" in url:
            continue
        app_name = url.rstrip("/").split("/")[-1].replace(".git", "")
        if app_name in installed:
            print(f"  [skip] {app_name} déjà installé")
            continue
        print(f"  [install-app] {app_name}")
        subprocess.run(["bench", "--site", site_name, "install-app", app_name], check=True)

if local_app not in installed:
    print(f"  [install-app] {local_app} (app locale)")
    subprocess.run(["bench", "--site", site_name, "install-app", local_app], check=True)
else:
    print(f"  [skip] {local_app} déjà installé")
PYEOF

# ═════════════════════════════════════════════════════════════════════════════
# 11. Finalisation
# ═════════════════════════════════════════════════════════════════════════════
bench --site "$SITE_NAME" clear-cache

echo ""
log "══════════════════════════════════════════════════════════"
log "  ✓ Environnement prêt !"
log ""
log "  Lancer le serveur :"
log "    cd ~/frappe-bench && bench start"
log ""
log "  URL   : http://${SITE_NAME}:8000"
log "  Login : Administrator / ${ADMIN_PASSWORD}"
if [ ! -f "$WORKSPACE/pyproject.toml" ] 2>/dev/null; then
  log ""
  log "  ⚠  Première fois : committe l'app scaffoldée :"
  log "     git add ${APP_NAME}/ pyproject.toml && git commit -m 'init: scaffold app' && git push"
fi
log "══════════════════════════════════════════════════════════"
