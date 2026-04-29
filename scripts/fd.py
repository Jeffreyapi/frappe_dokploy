#!/usr/bin/env python
"""
TUI frappe_dokploy — initialisation d'un repo d'app Frappe.

Génère les 7 fichiers projet-spécifiques :
  - .env.example                        (variables dev + prod)
  - apps.json                           (template avec ${GH_PAT})
  - .devcontainer/devcontainer.json     (pointe vers le submodule)
  - .github/workflows/publish.yml       (appelle le workflow réutilisable)
  - .vscode/launch.json                 (Run & Debug + Tests)
  - .vscode/settings.json               (Python, SQLTools, formatage)
  - .vscode/extensions.json             (extensions recommandées)

Tout le reste (Dockerfile, docker-compose, scripts) vit dans le submodule
et n'est jamais copié.
"""

from __future__ import annotations

import json
from pathlib import Path

try:
    from textual.app import App, ComposeResult
    from textual.containers import Grid, Horizontal, VerticalScroll
    from textual.widgets import Button, Footer, Header, Input, Label, TextArea
except ImportError:
    raise SystemExit("Textual n'est pas installé : pip install textual\n")

ROOT = Path(__file__).resolve().parent.parent


# ── Génération des fichiers ───────────────────────────────────────────────────

def gen_env_example(
    app_name: str, title: str, description: str,
    publisher: str, email: str, license_: str,
    python_version: str, frappe_branch: str,
    site: str, admin_pw: str, db_pw: str,
    image_name: str,
) -> list[str]:
    """Génère .env.example avec toutes les variables."""
    env_path = Path(".env.example")
    content = f"""\
# =============================================================================
#  .env.example — {app_name}
#  Copier en .env et adapter avant de lancer docker compose.
#  Ne jamais commiter .env (contient des secrets).
# =============================================================================

# ── App ───────────────────────────────────────────────────────────────────────
APP_NAME={app_name}
APP_TITLE={title}
APP_DESCRIPTION={description}
APP_PUBLISHER={publisher}
APP_EMAIL={email}
APP_LICENSE={license_}

# ── Frappe ────────────────────────────────────────────────────────────────────
PYTHON_VERSION={python_version}
FRAPPE_BRANCH={frappe_branch}

# ── Dev (devcontainer / Codespaces) ───────────────────────────────────────────
SITE_NAME={site}
DB_ROOT_PASSWORD={db_pw}
ADMIN_PASSWORD={admin_pw}

# ── Production (docker compose) ───────────────────────────────────────────────
# IMAGE_NAME={image_name}
# APP_VERSION=latest
# SITE_NAME=mon_app.example.com
# DB_ROOT_PASSWORD=changeme_strong_password
# ADMIN_PASSWORD=changeme_strong_password
# ENABLE_DB=1
# ENVIRONMENT=prod
# APPS={app_name}

# ── GitHub (apps privées dans apps.json) ──────────────────────────────────────
# GH_PAT=ghp_xxxxxxxxxxxx   ← passer en variable d'env, jamais dans .env commité
"""
    env_path.write_text(content, encoding="utf-8")
    return [f"  ✓  {env_path}"]


def gen_apps_json(app_name: str, github_owner: str) -> list[str]:
    """Génère apps.json si absent."""
    apps_path = Path("apps.json")
    if apps_path.exists():
        return [f"  —  apps.json déjà présent, ignoré"]
    data = [
        {
            "url": f"https://${{GH_PAT}}:x-oauth-basic@github.com/{github_owner}/{app_name}.git",
            "branch": "main",
        }
    ]
    apps_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return [f"  ✓  apps.json  (remplacer {github_owner} si nécessaire)"]


def gen_devcontainer_json(app_name: str) -> list[str]:
    """Génère .devcontainer/devcontainer.json — pointe vers le submodule."""
    dst = Path(".devcontainer/devcontainer.json")
    dst.parent.mkdir(parents=True, exist_ok=True)
    content = f"""\
{{
  "name": "{app_name}",
  "build": {{
    "dockerfile": "../frappe_deploy/.devcontainer/Dockerfile",
    "context": ".."
  }},
  "remoteUser": "frappe",
  "workspaceFolder": "/workspaces/{app_name}",
  "initializeCommand": "git submodule update --init frappe_deploy",
  "postCreateCommand": "bash frappe_deploy/scripts/devcontainer-setup.sh",
  "forwardPorts": [8000, 9000],
  "remoteEnv": {{
    "PATH": "/home/frappe/frappe-bench/env/bin:/home/frappe/.local/bin:${{containerEnv:PATH}}"
  }},
  "customizations": {{
    "vscode": {{
      "extensions": [
        "ms-python.python",
        "ms-python.debugpy",
        "ms-python.black-formatter",
        "ms-python.isort",
        "ms-python.pylint",
        "mtxr.sqltools",
        "mtxr.sqltools-driver-mysql",
        "anthropics.claude-code",
        "github.copilot",
        "github.copilot-chat"
      ]
    }}
  }},
  "mounts": [
    "source=${{localEnv:HOME}}${{localEnv:USERPROFILE}}/.ssh,target=/home/frappe/.ssh,type=bind,consistency=cached"
  ]
}}
"""
    dst.write_text(content, encoding="utf-8")
    return [f"  ✓  {dst}"]


def gen_publish_workflow(app_name: str, github_owner: str, frappe_branch: str) -> list[str]:
    """Génère .github/workflows/publish.yml — appelle le workflow réutilisable."""
    dst = Path(".github/workflows/publish.yml")
    dst.parent.mkdir(parents=True, exist_ok=True)
    content = f"""\
name: Build & publish

on:
  push:
    branches: [main]
    tags: ["v*"]
  workflow_dispatch:
    inputs:
      version:
        description: "Version tag (ex: v1.0.0)"
        required: true

jobs:
  build:
    uses: {github_owner}/frappe_dokploy/.github/workflows/build-image.yml@main
    with:
      image-name: ghcr.io/{github_owner}/{app_name}
      frappe-version: {frappe_branch}
    secrets: inherit
"""
    dst.write_text(content, encoding="utf-8")
    return [f"  ✓  {dst}"]


def gen_vscode_launch(app_name: str) -> list[str]:
    """Génère .vscode/launch.json — Run & Debug + Tests."""
    dst = Path(".vscode/launch.json")
    dst.parent.mkdir(parents=True, exist_ok=True)
    bench = "/home/frappe/frappe-bench"
    data = {
        "version": "0.2.0",
        "configurations": [
            {
                "name": "Frappe: Web Server",
                "type": "debugpy",
                "request": "launch",
                "program": f"{bench}/apps/frappe/frappe/utils/bench_helper.py",
                "args": ["frappe", "serve", "--port", "8000", "--noreload", "--nothreading"],
                "cwd": f"{bench}/sites",
                "env": {"DEV_SERVER": "1"},
                "justMyCode": False,
                "console": "integratedTerminal",
            },
            {
                "name": "Frappe: Run Current Test File",
                "type": "debugpy",
                "request": "launch",
                "program": f"{bench}/apps/frappe/frappe/utils/bench_helper.py",
                "args": [
                    "frappe", "--site", "development.localhost",
                    "run-tests", "--app", app_name,
                    "--module", "${fileBasenameNoExtension}",
                ],
                "cwd": f"{bench}",
                "env": {"DEV_SERVER": "1"},
                "justMyCode": False,
                "console": "integratedTerminal",
            },
            {
                "name": "Frappe: Run All App Tests",
                "type": "debugpy",
                "request": "launch",
                "program": f"{bench}/apps/frappe/frappe/utils/bench_helper.py",
                "args": [
                    "frappe", "--site", "development.localhost",
                    "run-tests", "--app", app_name,
                ],
                "cwd": f"{bench}",
                "env": {"DEV_SERVER": "1"},
                "justMyCode": False,
                "console": "integratedTerminal",
            },
        ],
    }
    dst.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return [f"  ✓  {dst}"]


def gen_vscode_settings(app_name: str, db_pw: str) -> list[str]:
    """Génère .vscode/settings.json — Python, SQLTools, formatage."""
    dst = Path(".vscode/settings.json")
    dst.parent.mkdir(parents=True, exist_ok=True)
    bench = "/home/frappe/frappe-bench"
    data = {
        # ── Python ────────────────────────────────────────────────────────────
        "python.defaultInterpreterPath": f"{bench}/env/bin/python",
        "python.terminal.activateEnvironment": True,
        "[python]": {
            "editor.defaultFormatter": "ms-python.black-formatter",
            "editor.formatOnSave": True,
            "editor.codeActionsOnSave": {
                "source.organizeImports": "explicit",
            },
        },
        "isort.args": ["--profile", "black"],
        "pylint.args": [
            f"--init-hook=import sys; sys.path.insert(0, '{bench}/apps/frappe')",
        ],
        # ── Tests ─────────────────────────────────────────────────────────────
        "python.testing.pytestEnabled": False,
        "python.testing.unittestEnabled": False,
        # Les tests Frappe se lancent via bench run-tests (voir launch.json)
        # ── SQLTools — connexion MariaDB dev ──────────────────────────────────
        "sqltools.connections": [
            {
                "name": "MariaDB dev",
                "driver": "MySQL",
                "server": "127.0.0.1",
                "port": 3306,
                "username": "root",
                "password": db_pw,
                "askForPassword": False,
                "connectionTimeout": 30,
            },
        ],
        "sqltools.autoOpenSessionFiles": False,
        # ── Éditeur ───────────────────────────────────────────────────────────
        "editor.rulers": [100],
        "editor.tabSize": 1,
        "files.exclude": {
            "**/__pycache__": True,
            "**/*.pyc": True,
        },
        # ── Terminal ──────────────────────────────────────────────────────────
        "terminal.integrated.defaultProfile.linux": "bash",
        "terminal.integrated.env.linux": {
            "PATH": f"{bench}/env/bin:/home/frappe/.local/bin:${{env:PATH}}",
        },
        "debug.node.autoAttach": "disabled",
    }
    dst.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return [f"  ✓  {dst}"]


def gen_vscode_extensions(app_name: str) -> list[str]:
    """Génère .vscode/extensions.json — extensions recommandées."""
    dst = Path(".vscode/extensions.json")
    dst.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "recommendations": [
            # Python
            "ms-python.python",
            "ms-python.debugpy",
            "ms-python.black-formatter",
            "ms-python.isort",
            "ms-python.pylint",
            # Base de données
            "mtxr.sqltools",
            "mtxr.sqltools-driver-mysql",
            # IA
            "anthropics.claude-code",
            "github.copilot",
            "github.copilot-chat",
            # Qualité / utilitaires
            "visualstudioexptteam.vscodeintellicode",
            "ms-vscode.live-server",
            "eamodio.gitlens",
        ],
    }
    dst.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return [f"  ✓  {dst}"]


# ── TUI ───────────────────────────────────────────────────────────────────────

class FDApp(App):
    CSS = """
    Screen { background: #0d1117; align: center top; }
    #main  { width: 80; margin-top: 1; }

    .section-label {
        color: #58a6ff; text-style: bold;
        height: 1; margin: 1 0 0 1;
    }
    .form-grid {
        grid-size: 2; grid-columns: 22 1fr;
        border: solid #30363d; padding: 0 2 1 2;
        height: auto; margin-bottom: 0;
    }
    .form-grid Label {
        color: #8b949e; content-align: left middle;
        height: 3; padding: 0 1;
    }
    .form-grid Input {
        height: 3; background: #161b22;
        border: tall #30363d; color: #e6edf3;
    }
    .form-grid Input:focus { border: tall #58a6ff; }

    #btn-row  { height: 3; margin-top: 1; margin-bottom: 1; }
    #btn-init { width: 1fr; }
    #btn-next { width: 1fr; }
    #btn-quit { width: 12; }

    #output {
        height: 14; border: solid #30363d; background: #0d1117;
    }
    #hint { color: #484f58; text-align: center; margin-top: 1; }
    """

    BINDINGS = [("escape", "quit", "Quitter")]

    def __init__(self) -> None:
        super().__init__()
        self._default_name = Path.cwd().name
        self._logs: list[str] = []

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with VerticalScroll(id="main"):

            # ── APP ───────────────────────────────────────────────────
            yield Label("APP", classes="section-label")
            with Grid(classes="form-grid"):
                yield Label("Nom de l'app")
                yield Input(self._default_name, id="app-name")
                yield Label("GitHub owner")
                yield Input("Jeffreyapi", id="github-owner")
                yield Label("Python version")
                yield Input("python3.14", id="python-version")
                yield Label("Frappe branch")
                yield Input("version-16", id="frappe-branch")

            # ── MÉTADONNÉES ───────────────────────────────────────────
            yield Label("MÉTADONNÉES", classes="section-label")
            with Grid(classes="form-grid"):
                yield Label("Title")
                yield Input(self._default_name, id="app-title")
                yield Label("Description")
                yield Input(self._default_name, id="app-desc")
                yield Label("Publisher")
                yield Input("EasyTalents", id="app-publisher")
                yield Label("Email")
                yield Input("admin@easytalents.fr", id="app-email")
                yield Label("Licence")
                yield Input("apache-2.0", id="app-license")

            # ── DEVCONTAINER ─────────────────────────────────────────
            yield Label("DEV", classes="section-label")
            with Grid(classes="form-grid"):
                yield Label("Site name")
                yield Input("development.localhost", id="site-name")
                yield Label("Admin password")
                yield Input("admin", password=True, id="admin-pw")
                yield Label("DB root password")
                yield Input("123", password=True, id="db-pw")

            # ── Actions ───────────────────────────────────────────────
            with Horizontal(id="btn-row"):
                yield Button("▶  Initialiser", id="btn-init", variant="success")
                yield Button("Étapes suivantes", id="btn-next", variant="primary")
                yield Button("Quitter", id="btn-quit", variant="error")

            yield TextArea("En attente…", id="output", read_only=True, theme="monokai")
            yield Label("Tab = champ suivant  •  Échap = quitter", id="hint")

        yield Footer()

    # ── Événements ────────────────────────────────────────────────────

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-init":
            self._do_init()
        elif event.button.id == "btn-next":
            self._show_next_steps()
        elif event.button.id == "btn-quit":
            self.exit()

    # ── Helpers ───────────────────────────────────────────────────────

    def _v(self, widget_id: str, fallback: str = "") -> str:
        return self.query_one(f"#{widget_id}", Input).value.strip() or fallback

    def _push(self, lines: list[str]) -> None:
        self._logs.extend(lines)
        ta = self.query_one("#output", TextArea)
        ta.load_text("\n".join(self._logs))
        ta.scroll_end()

    def _do_init(self) -> None:
        app_name      = self._v("app-name",       self._default_name)
        owner         = self._v("github-owner",    "Jeffreyapi")
        python_ver    = self._v("python-version",  "python3.14")
        frappe_branch = self._v("frappe-branch",   "version-16")
        title         = self._v("app-title",       app_name)
        desc          = self._v("app-desc",        app_name)
        publisher     = self._v("app-publisher",   "EasyTalents")
        email         = self._v("app-email",       "admin@easytalents.fr")
        license_      = self._v("app-license",     "apache-2.0")
        site          = self._v("site-name",       "development.localhost")
        admin_pw      = self.query_one("#admin-pw", Input).value or "admin"
        db_pw         = self.query_one("#db-pw",    Input).value or "123"
        image_name    = f"ghcr.io/{owner}/{app_name}"

        self._logs.clear()
        self._push([f"── Init : {app_name} ──", ""])
        try:
            self._push(["[1/7] .env.example…"])
            self._push(gen_env_example(
                app_name, title, desc, publisher, email, license_,
                python_ver, frappe_branch, site, admin_pw, db_pw, image_name,
            ))
            self._push(["", "[2/7] apps.json…"])
            self._push(gen_apps_json(app_name, owner))
            self._push(["", "[3/7] .devcontainer/devcontainer.json…"])
            self._push(gen_devcontainer_json(app_name))
            self._push(["", "[4/7] .github/workflows/publish.yml…"])
            self._push(gen_publish_workflow(app_name, owner, frappe_branch))
            self._push(["", "[5/7] .vscode/launch.json…"])
            self._push(gen_vscode_launch(app_name))
            self._push(["", "[6/7] .vscode/settings.json…"])
            self._push(gen_vscode_settings(app_name, db_pw))
            self._push(["", "[7/7] .vscode/extensions.json…"])
            self._push(gen_vscode_extensions(app_name))
            self._push(["", "✅  Fait ! Clique sur 'Étapes suivantes' pour la suite."])
        except Exception as exc:
            self._push([f"", f"❌  Erreur : {exc}"])

    def _show_next_steps(self) -> None:
        app_name = self._v("app-name", self._default_name)
        self._logs.clear()
        self._push([
            "── Étapes suivantes ──", "",
            "  1. Vérifier apps.json  (remplacer le owner GitHub si besoin)",
            "  2. Copier .env.example → .env  et ajuster les valeurs",
            "  3. Committer et pousser :",
            f"       git add -A && git commit -m 'init: {app_name}' && git push",
            "",
            "  4. Ouvrir un Codespace",
            "     → le postCreateCommand lance frappe_deploy/scripts/devcontainer-setup.sh",
            "     → F5 pour démarrer le serveur avec debugpy",
            "     → Ctrl+Shift+P → SQLTools: Connect → MariaDB dev",
            "",
            "  5. Si setup incomplet ou après un bump du submodule :",
            "       bash frappe_deploy/scripts/rebuild.sh",
            "",
            "  6. Première fois — committer l'app scaffoldée :",
            f"       git add {app_name}/ pyproject.toml",
            f"       git commit -m 'init: scaffold {app_name}'",
            "       git push",
        ])


def main() -> None:
    FDApp().run()


if __name__ == "__main__":
    main()
