#!/usr/bin/env python
"""
TUI Textual pour automatiser les étapes d'init d'une app Frappe avec le submodule frappe_dokploy.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

try:
    from textual.app import App, ComposeResult
    from textual.containers import Grid, Horizontal, Vertical
    from textual.widgets import Button, Footer, Header, Input, Label, TextArea
except ImportError:
    raise SystemExit(
        "Textual n'est pas installé. Installez-le avec :\n\n  pip install textual\n"
    )

ROOT = Path(__file__).resolve().parent.parent
TEMPLATES = ROOT / "templates"

COPY_MAP = {
    TEMPLATES / "docker-compose.app.yml": Path("docker-compose.yml"),
    TEMPLATES / ".env.app.example": Path(".env.example"),
    TEMPLATES / "Makefile": Path("Makefile"),
    TEMPLATES / "publish.app.yml": Path(".github/workflows/publish.yml"),
    TEMPLATES / ".devcontainer" / "Dockerfile": Path(".devcontainer/Dockerfile"),
    TEMPLATES / ".devcontainer" / "devcontainer.json": Path(".devcontainer/devcontainer.json"),
    TEMPLATES / ".devcontainer" / "devcontainer-post-create.sh": Path(
        ".devcontainer/devcontainer-post-create.sh"
    ),
}

TARGETS_REPLACE = [
    Path("docker-compose.yml"),
    Path(".env.example"),
    Path(".github/workflows/publish.yml"),
    Path(".devcontainer/devcontainer.json"),
    Path(".devcontainer/devcontainer-post-create.sh"),
]


def default_app_name() -> str:
    return Path.cwd().name


def ensure_parents(path: Path) -> None:
    if path.parent != Path("."):
        path.parent.mkdir(parents=True, exist_ok=True)


def copy_templates() -> list[str]:
    logs: list[str] = []
    for src, dst in COPY_MAP.items():
        ensure_parents(dst)
        shutil.copy2(src, dst)
        logs.append(f"  ✓  {dst}")
    dst = Path(".devcontainer/devcontainer-post-create.sh")
    if dst.exists():
        dst.chmod(dst.stat().st_mode | 0o111)
        logs.append("  ✓  chmod +x devcontainer-post-create.sh")
    return logs


def replace_my_app(app_name: str) -> list[str]:
    logs: list[str] = []
    for file in TARGETS_REPLACE:
        if not file.exists():
            continue
        content = file.read_text(encoding="utf-8")
        if "MY_APP" not in content:
            continue
        file.write_text(content.replace("MY_APP", app_name), encoding="utf-8")
        logs.append(f"  ✓  MY_APP → {app_name}  ({file})")
    return logs


def replace_dev_vars(branch: str, site: str, admin_pw: str, db_pw: str) -> list[str]:
    file = Path(".devcontainer/devcontainer-post-create.sh")
    if not file.exists():
        return ["  ⚠  devcontainer-post-create.sh introuvable"]
    text = file.read_text(encoding="utf-8")
    replacements = {
        'FRAPPE_BRANCH="version-15"': f'FRAPPE_BRANCH="{branch}"',
        'SITE_NAME="development.localhost"': f'SITE_NAME="{site}"',
        'DB_ROOT_PASSWORD="123"': f'DB_ROOT_PASSWORD="{db_pw}"',
        'ADMIN_PASSWORD="admin"': f'ADMIN_PASSWORD="{admin_pw}"',
    }
    for needle, repl in replacements.items():
        text = text.replace(needle, repl)
    file.write_text(text, encoding="utf-8")
    return [
        f"  ✓  FRAPPE_BRANCH → {branch}",
        f"  ✓  SITE_NAME → {site}",
        "  ✓  DB_ROOT_PASSWORD → (défini)",
        "  ✓  ADMIN_PASSWORD → (défini)",
    ]


def bench_commands(app_name: str) -> str:
    return f"""# À exécuter dans le devcontainer / Codespaces
cd ~/frappe-bench
bench new-app {app_name}

# Ramener le code dans le repo + symlink pour hot-reload
cp -a apps/{app_name}/. /workspaces/{app_name}/
rm -rf apps/{app_name}
ln -s /workspaces/{app_name} apps/{app_name}

# Installer l'app sur le site de dev
bench --site development.localhost install-app {app_name}
bench start  # http://development.localhost:8000"""


class FDApp(App):
    CSS = """
    Screen {
        background: #0d1117;
        align: center top;
    }

    #main {
        width: 76;
        margin-top: 1;
    }

    /* ── Formulaire en grille 2 colonnes ── */
    #form {
        grid-size: 2;
        grid-columns: 20 1fr;
        grid-rows: 3 3 3 3 3;
        border: solid #30363d;
        padding: 1 2;
        margin-bottom: 1;
        height: auto;
    }

    #form Label {
        color: #8b949e;
        content-align: left middle;
        height: 3;
        padding: 0 1;
    }

    #form Input {
        height: 3;
        background: #161b22;
        border: tall #30363d;
        color: #e6edf3;
    }

    #form Input:focus {
        border: tall #58a6ff;
    }

    /* ── Séparateur visuel dans le grid ── */
    .sep {
        column-span: 2;
        height: 1;
        color: #21262d;
        background: #21262d;
    }

    /* ── Boutons ── */
    #btn-row {
        height: 3;
        margin-bottom: 1;
    }

    #btn-init  { width: 1fr; }
    #btn-bench { width: 1fr; }
    #btn-quit  { width: 12; }

    /* ── Résultat ── */
    #output {
        height: 14;
        border: solid #30363d;
        background: #0d1117;
    }

    #hint {
        color: #484f58;
        text-align: center;
        margin-top: 1;
    }
    """

    BINDINGS = [("q", "quit", "Quitter")]

    def __init__(self, app_name: str | None = None) -> None:
        super().__init__()
        self._default_name = app_name or default_app_name()
        self._logs: list[str] = []

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Vertical(id="main"):

            # ── Formulaire ────────────────────────────────────────────
            with Grid(id="form"):
                # APP
                yield Label("Nom de l'app")
                yield Input(self._default_name, id="app-input")
                yield Label("Frappe branch")
                yield Input("version-15", id="branch-input")
                # DEVCONTAINER
                yield Label("Site name")
                yield Input("development.localhost", id="site-input")
                yield Label("Admin password")
                yield Input("admin", password=True, id="admin-input")
                yield Label("DB root password")
                yield Input("123", password=True, id="db-input")

            # ── Actions ───────────────────────────────────────────────
            with Horizontal(id="btn-row"):
                yield Button("▶  Lancer l'Init", id="btn-init", variant="success")
                yield Button("Commandes bench",  id="btn-bench", variant="primary")
                yield Button("Quitter",          id="btn-quit",  variant="error")

            # ── Résultat ──────────────────────────────────────────────
            yield TextArea("En attente…", id="output", read_only=True, theme="monokai")
            yield Label("Tab = champ suivant  •  q = quitter", id="hint")

        yield Footer()

    # ── Événements ────────────────────────────────────────────────────

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-init":
            self._do_init()
        elif event.button.id == "btn-bench":
            self._show_bench()
        elif event.button.id == "btn-quit":
            self.exit()

    # ── Helpers ───────────────────────────────────────────────────────

    def _val(self, widget_id: str, fallback: str = "") -> str:
        return self.query_one(f"#{widget_id}", Input).value.strip() or fallback

    def _push(self, lines: list[str]) -> None:
        self._logs.extend(lines)
        ta = self.query_one("#output", TextArea)
        ta.load_text("\n".join(self._logs))
        ta.scroll_end()

    def _do_init(self) -> None:
        name    = self._val("app-input",   self._default_name)
        branch  = self._val("branch-input", "version-15")
        site    = self._val("site-input",   "development.localhost")
        admin   = self.query_one("#admin-input", Input).value or "admin"
        db      = self.query_one("#db-input",    Input).value or "123"

        self._logs.clear()
        self._push([f"── Init : {name} ──"])
        try:
            self._push(copy_templates())
            self._push(replace_my_app(name))
            self._push(replace_dev_vars(branch, site, admin, db))
            self._push([f"", f"✅  Init terminé pour « {name} »"])
        except Exception as exc:
            self._push([f"❌  Erreur : {exc}"])

    def _show_bench(self) -> None:
        name = self._val("app-input", self._default_name)
        self._logs.clear()
        self._push(["── Commandes bench ──", bench_commands(name)])


def main() -> None:
    FDApp().run()


if __name__ == "__main__":
    main()
