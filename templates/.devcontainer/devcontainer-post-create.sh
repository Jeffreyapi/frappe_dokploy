#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
#  devcontainer-post-create.sh
#  Exécuté une seule fois après la création du conteneur.
#
#  Ce script :
#    1. Démarre MariaDB 10.6 et Redis (services système)
#    2. Installe uv + frappe-bench
#    3. Initialise le bench avec frappe version-15
#    4. Installe les apps publiques listées dans apps.json (ex: ERPNext)
#    5. Installe l'app locale en mode ÉDITABLE (symlink → pip install -e)
#       → les modifications dans VS Code sont immédiatement actives dans le bench
#    6. Crée le site Frappe en mode développeur
#
#  Adapter : remplacer MY_APP par le nom de l'application
# =============================================================================

# ── Variables — adapter MY_APP ────────────────────────────────────────────────
WORKSPACE="/workspaces/MY_APP"
APP_NAME="MY_APP"
BENCH_DIR="$HOME/frappe-bench"
FRAPPE_BRANCH="version-15"
SITE_NAME="development.localhost"
DB_ROOT_PASSWORD="123"
ADMIN_PASSWORD="admin"

log() { echo "[devcontainer $(date +'%T')] $*"; }
export PATH="$HOME/.local/bin:$PATH"

# ── 1. MariaDB 10.6 ───────────────────────────────────────────────────────────
log "Démarrage de MariaDB 10.6..."
sudo service mariadb start || log "MariaDB déjà lancé"

log "Configuration du compte root MariaDB..."
# Le heredoc SQL n'est PAS dans un contexte bash-variable-expansion,
# on utilise une variable shell explicite pour le mot de passe.
sudo mysql --connect-expired-password -u root <<-SQL || log "Root déjà configuré, on continue"
	ALTER USER 'root'@'localhost' IDENTIFIED BY '${DB_ROOT_PASSWORD}';
	FLUSH PRIVILEGES;
SQL

# ── 2. Redis ──────────────────────────────────────────────────────────────────
log "Démarrage de Redis..."
sudo service redis-server start || log "Redis déjà lancé"

# ── 3. uv + frappe-bench ──────────────────────────────────────────────────────
if ! command -v uv >/dev/null 2>&1; then
  log "Installation de uv..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi

if ! command -v bench >/dev/null 2>&1; then
  log "Installation de frappe-bench via uv..."
  uv tool install frappe-bench
  export PATH="$HOME/.local/bin:$PATH"
fi
log "bench : $(bench --version 2>/dev/null || echo 'ok')"

# ── Si le bench existe déjà (relance du conteneur), on s'arrête ───────────────
if [ -d "$BENCH_DIR" ]; then
  log "Bench existant détecté dans $BENCH_DIR — skip init."
  log "Pour relancer depuis zéro : rm -rf $BENCH_DIR && bash .devcontainer/devcontainer-post-create.sh"
  exit 0
fi

# ── 4. bench init (frappe seulement) ─────────────────────────────────────────
log "Initialisation du bench frappe-bench (frappe $FRAPPE_BRANCH)..."
bench init \
  --frappe-branch "$FRAPPE_BRANCH" \
  --skip-redis-config-generation \
  "$BENCH_DIR"

cd "$BENCH_DIR"

# ── 5. Configurer Redis (instance unique en dev) + MariaDB ────────────────────
log "Configuration Redis & MariaDB dans common_site_config..."
bench set-config -g  db_host        "127.0.0.1"
bench set-config -gp db_port        3306
bench set-config -g  redis_cache    "redis://127.0.0.1:6379"
bench set-config -g  redis_queue    "redis://127.0.0.1:6379"
bench set-config -g  redis_socketio "redis://127.0.0.1:6379"
bench set-config -gp developer_mode 1

# ── 6. Apps publiques depuis apps.json (ex : ERPNext) ────────────────────────
# Les apps dont l'URL contient GH_PAT sont privées et seront gérées via
# le workspace local (étape 7). Les apps publiques (GitHub public) sont
# clonées normalement via bench get-app.
log "Lecture de apps.json pour les apps publiques..."
python3 - "$WORKSPACE" <<'PYEOF'
import json, subprocess, sys, os

workspace = sys.argv[1]
apps_file = os.path.join(workspace, "apps.json")

if not os.path.exists(apps_file):
    print(f"[skip] {apps_file} introuvable")
    sys.exit(0)

apps = json.load(open(apps_file))
for app in apps:
    url = app["url"]
    branch = app.get("branch", "main")
    # Ignorer les apps privées (URL avec token GH_PAT = l'app du workspace)
    if "${GH_PAT}" in url or "GH_PAT" in url:
        name = url.rstrip("/").split("/")[-1].replace(".git", "")
        print(f"[skip] app privée '{name}' → sera installée depuis le workspace local")
        continue
    print(f"[get-app] {url}  (branch: {branch})")
    subprocess.run(["bench", "get-app", "--branch", branch, url], check=True)
PYEOF

# ── 7. App locale en mode éditable (Option B) ─────────────────────────────────
# Un symlink pointe $BENCH_DIR/apps/MY_APP → /workspaces/MY_APP
# pip install -e enregistre l'app dans le venv bench sans copier les fichiers.
# Résultat : toute modification dans VS Code est immédiatement reflétée.
log "Installation de $APP_NAME en mode éditable depuis le workspace local..."
ln -sf "$WORKSPACE" "$BENCH_DIR/apps/$APP_NAME"
"$BENCH_DIR/env/bin/pip" install -e "$BENCH_DIR/apps/$APP_NAME"

# ── 8. Créer le site Frappe ───────────────────────────────────────────────────
log "Création du site $SITE_NAME..."
bench new-site \
  --db-root-username root \
  --db-root-password "$DB_ROOT_PASSWORD" \
  --mariadb-user-host-login-scope='%' \
  --admin-password "$ADMIN_PASSWORD" \
  "$SITE_NAME"

# ── 9. Installer les apps sur le site ─────────────────────────────────────────
log "Installation des apps publiques sur le site..."
python3 - "$WORKSPACE" "$SITE_NAME" <<'PYEOF'
import json, subprocess, sys, os

workspace = sys.argv[1]
site_name = sys.argv[2]
apps_file = os.path.join(workspace, "apps.json")

if not os.path.exists(apps_file):
    sys.exit(0)

apps = json.load(open(apps_file))
for app in apps:
    url = app["url"]
    if "${GH_PAT}" in url or "GH_PAT" in url:
        continue
    app_name = url.rstrip("/").split("/")[-1].replace(".git", "")
    print(f"[install-app] {app_name}")
    subprocess.run(
        ["bench", "--site", site_name, "install-app", app_name],
        check=True
    )
PYEOF

log "Installation de l'app locale : $APP_NAME"
bench --site "$SITE_NAME" install-app "$APP_NAME"

# ── 10. Finalisation ──────────────────────────────────────────────────────────
bench --site "$SITE_NAME" clear-cache

log ""
log "══════════════════════════════════════════════════════════"
log "  ✓ Devcontainer prêt !"
log ""
log "  Démarrer le serveur de développement :"
log "    cd ~/frappe-bench && bench start"
log ""
log "  URL   : http://development.localhost:8000"
log "  Login : Administrator / ${ADMIN_PASSWORD}"
log ""
log "  Mode éditable actif :"
log "  Les fichiers dans VS Code (${WORKSPACE}) sont"
log "  directement reflétés dans le bench — pas de redémarrage nécessaire"
log "  pour les changements Python (sauf hooks.py)."
log "══════════════════════════════════════════════════════════"
