#!/usr/bin/env sh
# Remplace toutes les occurrences de MY_APP par le nom du dossier courant.
# À lancer depuis la racine du repo applicatif après avoir copié les templates.

set -euo pipefail

APP_NAME=${APP_NAME:-$(basename "$PWD")}
TARGETS="
docker-compose.yml
.env.example
.github/workflows/publish.yml
.devcontainer/devcontainer.json
.devcontainer/devcontainer-post-create.sh
"

replace_file() {
  file="$1"
  [ -f "$file" ] || return 0
  if grep -q "MY_APP" "$file"; then
    python3 - "$APP_NAME" "$file" <<'PY'
import sys, pathlib
app, fname = sys.argv[1:]
p = pathlib.Path(fname)
text = p.read_text()
if "MY_APP" in text:
    p.write_text(text.replace("MY_APP", app))
PY
    echo "[ok] ${file}"
  else
    echo "[skip] ${file} (aucun MY_APP)"
  fi
}

for f in $TARGETS; do
  replace_file "$f"
done
