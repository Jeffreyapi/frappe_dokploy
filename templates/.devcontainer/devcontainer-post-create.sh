#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
#  devcontainer-post-create.sh  —  IDEMPOTENT
#
#  Peut être lancé plusieurs fois sans danger.
#  Chaque étape vérifie son propre état avant d'agir.
#
#  Étapes :
#    1.  MariaDB + Redis
#    2.  uv + frappe-bench (CLI)
#    3.  bench init (frappe)
#    4.  Config Redis/MariaDB dans bench
#    5.  Apps publiques depuis apps.json
#    6.  Scaffold de MY_APP via bench new-app (non-interactif)
#    7.  Copie workspace + symlink + pip install -e
#    8.  Création du site
#    9.  Installation des apps sur le site
#    10. Finalisation
#
#  Variables générées par le TUI frappe_dokploy — ne pas éditer à la main.
# =============================================================================

# ── Variables ─────────────────────────────────────────────────────────────────
APP_NAME="MY_APP"
WORKSPACE="/workspaces/MY_APP"
BENCH_DIR="$HOME/frappe-bench"

# App metadata (bench new-app)
APP_TITLE="My App"
APP_DESCRIPTION="My Frappe application"
APP_PUBLISHER="My Company"
APP_EMAIL="admin@example.com"
APP_LICENSE="mit"

# Environnement de développement
FRAPPE_BRANCH="version-15"
SITE_NAME="development.localhost"
DB_ROOT_PASSWORD="123"
ADMIN_PASSWORD="admin"

# ── Helpers ───────────────────────────────────────────────────────────────────
log()  { echo "[devcontainer $(date +'%T')] $*"; }
ok()   { echo "[devcontainer $(date +'%T')] ✓ $*"; }
skip() { echo "[devcontainer $(date +'%T')] — skip: $*"; }

export PATH="$HOME/.local/bin:$PATH"

# ═══════════════════════════════════════════════════════════════════════════════
# 1. MariaDB + Redis
# ═══════════════════════════════════════════════════════════════════════════════
log "Démarrage de MariaDB..."
sudo service mariadb start 2>/dev/null || skip "MariaDB déjà lancé"

# Configurer le mot de passe root seulement si nécessaire
if mysql -u root -p"${DB_ROOT_PASSWORD}" -e "SELECT 1" >/dev/null 2>&1; then
  skip "MariaDB root déjà configuré avec le bon mot de passe"
else
  log "Configuration du mot de passe root MariaDB..."
  sudo mysql --connect-expired-password -u root <<-SQL || skip "Root déjà configuré"
	ALTER USER 'root'@'localhost' IDENTIFIED BY '${DB_ROOT_PASSWORD}';
	FLUSH PRIVILEGES;
SQL
fi

log "Démarrage de Redis..."
sudo service redis-server start 2>/dev/null || skip "Redis déjà lancé"

# ═══════════════════════════════════════════════════════════════════════════════
# 2. uv + frappe-bench CLI
# ═══════════════════════════════════════════════════════════════════════════════
if ! command -v uv >/dev/null 2>&1; then
  log "Installation de uv..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
else
  skip "uv $(uv --version)"
fi

if ! command -v bench >/dev/null 2>&1; then
  log "Installation de frappe-bench via uv..."
  uv tool install frappe-bench
  export PATH="$HOME/.local/bin:$PATH"
else
  skip "bench $(bench --version 2>/dev/null)"
fi

# ═══════════════════════════════════════════════════════════════════════════════
# 3. bench init
# ═══════════════════════════════════════════════════════════════════════════════
if [ ! -d "$BENCH_DIR" ]; then
  log "Initialisation du bench (frappe $FRAPPE_BRANCH)..."
  bench init \
    --frappe-branch "$FRAPPE_BRANCH" \
    --skip-redis-config-generation \
    "$BENCH_DIR"
else
  skip "bench déjà initialisé dans $BENCH_DIR"
fi

cd "$BENCH_DIR"

# ═══════════════════════════════════════════════════════════════════════════════
# 4. Config Redis + MariaDB dans common_site_config
# ═══════════════════════════════════════════════════════════════════════════════
if ! grep -q '"db_host"' sites/common_site_config.json 2>/dev/null; then
  log "Configuration Redis & MariaDB dans common_site_config..."
  bench set-config -g  db_host        "127.0.0.1"
  bench set-config -gp db_port        3306
  bench set-config -g  redis_cache    "redis://127.0.0.1:6379"
  bench set-config -g  redis_queue    "redis://127.0.0.1:6379"
  bench set-config -g  redis_socketio "redis://127.0.0.1:6379"
  bench set-config -gp developer_mode 1
else
  skip "common_site_config déjà configuré"
fi

# ═══════════════════════════════════════════════════════════════════════════════
# 5. Apps publiques depuis apps.json
# ═══════════════════════════════════════════════════════════════════════════════
log "Lecture de apps.json pour les apps publiques..."
python3 - "$WORKSPACE" "$BENCH_DIR" <<'PYEOF'
import json, subprocess, sys, os
from pathlib import Path

workspace  = sys.argv[1]
bench_dir  = sys.argv[2]
apps_file  = Path(workspace) / "apps.json"

if not apps_file.exists():
    print(f"[skip] {apps_file} introuvable")
    sys.exit(0)

apps = json.loads(apps_file.read_text())
for app in apps:
    url    = app["url"]
    branch = app.get("branch", "main")
    if "${GH_PAT}" in url or "GH_PAT" in url:
        name = url.rstrip("/").split("/")[-1].replace(".git", "")
        print(f"[skip] app privée '{name}' — installée depuis le workspace")
        continue
    app_name = url.rstrip("/").split("/")[-1].replace(".git", "")
    if (Path(bench_dir) / "apps" / app_name).exists():
        print(f"[skip] {app_name} déjà présent")
        continue
    print(f"[get-app] {url}  (branch: {branch})")
    subprocess.run(["bench", "get-app", "--branch", branch, url], check=True)
PYEOF

# ═══════════════════════════════════════════════════════════════════════════════
# 6. Scaffold de l'app (bench new-app non-interactif)
#    Seulement si le workspace n'a pas encore de pyproject.toml / setup.py
# ═══════════════════════════════════════════════════════════════════════════════
if [ ! -f "$WORKSPACE/pyproject.toml" ] && [ ! -f "$WORKSPACE/setup.py" ]; then
  log "Scaffold de $APP_NAME via bench new-app (non-interactif)..."

  # Supprimer le symlink s'il existe déjà (bench new-app a besoin du slot libre)
  [ -L "$BENCH_DIR/apps/$APP_NAME" ] && rm "$BENCH_DIR/apps/$APP_NAME"
  [ -d "$BENCH_DIR/apps/$APP_NAME" ] && rm -rf "$BENCH_DIR/apps/$APP_NAME"

  # Envoyer des lignes vides → bench utilise ses propres defaults calculés
  # depuis le nom de l'app (plus robuste que passer nos valeurs qui peuvent
  # échouer à la validation et décaler tout le stdin).
  # Les métadonnées (title, publisher, email…) sont patchées juste après.
  printf "\n\n\n\n\n\nN\n" | bench new-app "$APP_NAME"

  log "Patch des métadonnées dans pyproject.toml / hooks.py..."
  PYPROJECT="$BENCH_DIR/apps/$APP_NAME/pyproject.toml"
  HOOKS="$BENCH_DIR/apps/$APP_NAME/$APP_NAME/hooks.py"

  # pyproject.toml
  if [ -f "$PYPROJECT" ]; then
    sed -i "s/^name = .*/name = \"$APP_NAME\"/" "$PYPROJECT"
  fi

  # hooks.py — remplacer les valeurs bench new-app par les nôtres
  if [ -f "$HOOKS" ]; then
    sed -i "s/^app_title = .*/app_title = \"$APP_TITLE\"/"             "$HOOKS"
    sed -i "s/^app_description = .*/app_description = \"$APP_DESCRIPTION\"/" "$HOOKS"
    sed -i "s/^app_publisher = .*/app_publisher = \"$APP_PUBLISHER\"/"   "$HOOKS"
    sed -i "s/^app_email = .*/app_email = \"$APP_EMAIL\"/"               "$HOOKS"
    sed -i "s/^app_license = .*/app_license = \"$APP_LICENSE\"/"         "$HOOKS"
  fi

  log "Copie des fichiers générés dans le workspace $WORKSPACE..."
  cp -a "$BENCH_DIR/apps/$APP_NAME/." "$WORKSPACE/"
  rm -rf "$BENCH_DIR/apps/$APP_NAME"
  ok "Scaffold terminé"
else
  skip "App déjà scaffoldée dans $WORKSPACE (pyproject.toml ou setup.py présent)"
fi

# ═══════════════════════════════════════════════════════════════════════════════
# 7. Symlink workspace → bench/apps + pip install -e
# ═══════════════════════════════════════════════════════════════════════════════
if [ ! -L "$BENCH_DIR/apps/$APP_NAME" ]; then
  log "Création du symlink apps/$APP_NAME → $WORKSPACE"
  ln -sf "$WORKSPACE" "$BENCH_DIR/apps/$APP_NAME"
else
  skip "Symlink apps/$APP_NAME déjà présent"
fi

log "pip install -e (mode éditable)..."
"$BENCH_DIR/env/bin/pip" install -e "$BENCH_DIR/apps/$APP_NAME" --quiet
ok "pip install -e OK"

# ═══════════════════════════════════════════════════════════════════════════════
# 8. Création du site
# ═══════════════════════════════════════════════════════════════════════════════
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

# ═══════════════════════════════════════════════════════════════════════════════
# 9. Installation des apps sur le site
# ═══════════════════════════════════════════════════════════════════════════════
log "Installation des apps sur le site $SITE_NAME..."
python3 - "$WORKSPACE" "$SITE_NAME" "$BENCH_DIR" <<'PYEOF'
import json, subprocess, sys
from pathlib import Path

workspace  = sys.argv[1]
site_name  = sys.argv[2]
bench_dir  = sys.argv[3]
apps_file  = Path(workspace) / "apps.json"

if not apps_file.exists():
    sys.exit(0)

# Apps déjà installées sur le site
installed_file = Path(bench_dir) / "sites" / site_name / "apps.txt"
installed = set(installed_file.read_text().splitlines()) if installed_file.exists() else set()

apps = json.loads(apps_file.read_text())
for app in apps:
    url = app["url"]
    if "${GH_PAT}" in url or "GH_PAT" in url:
        continue
    app_name = url.rstrip("/").split("/")[-1].replace(".git", "")
    if app_name in installed:
        print(f"[skip] {app_name} déjà installé sur {site_name}")
        continue
    print(f"[install-app] {app_name}")
    subprocess.run(["bench", "--site", site_name, "install-app", app_name], check=True)
PYEOF

# App locale
INSTALLED_APPS="$BENCH_DIR/sites/$SITE_NAME/apps.txt"
if ! grep -qx "$APP_NAME" "$INSTALLED_APPS" 2>/dev/null; then
  log "Installation de $APP_NAME sur $SITE_NAME..."
  bench --site "$SITE_NAME" install-app "$APP_NAME"
  ok "$APP_NAME installé"
else
  skip "$APP_NAME déjà installé sur $SITE_NAME"
fi

# ═══════════════════════════════════════════════════════════════════════════════
# 10. Finalisation
# ═══════════════════════════════════════════════════════════════════════════════
bench --site "$SITE_NAME" clear-cache

log ""
log "══════════════════════════════════════════════════════════"
log "  ✓ Environnement prêt !"
log ""
log "  Lancer le serveur :"
log "    cd ~/frappe-bench && bench start"
log ""
log "  URL   : http://${SITE_NAME}:8000"
log "  Login : Administrator / ${ADMIN_PASSWORD}"
log ""
log "  Mode éditable : modifications VS Code → bench sans redémarrage"
log "══════════════════════════════════════════════════════════"
