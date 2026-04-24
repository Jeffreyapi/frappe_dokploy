#!/usr/bin/env python
"""
TUI Textual pour automatiser les étapes d'init d'une app Frappe avec le submodule frappe_dokploy.
"""

from __future__ import annotations

import shutil
from pathlib import Path

try:
    from textual.app import App, ComposeResult
    from textual.containers import Grid, Horizontal, VerticalScroll
    from textual.widgets import Button, Footer, Header, Input, Label, TextArea
except ImportError:
    raise SystemExit(
        "Textual n'est pas installé. Installez-le avec :\n\n  pip install textual\n"
    )

ROOT      = Path(__file__).resolve().parent.parent
TEMPLATES = ROOT / "templates"

COPY_MAP = {
    TEMPLATES / "docker-compose.app.yml"                       : Path("docker-compose.yml"),
    TEMPLATES / ".env.app.example"                             : Path(".env.example"),
    TEMPLATES / "Makefile"                                     : Path("Makefile"),
    TEMPLATES / "publish.app.yml"                              : Path(".github/workflows/publish.yml"),
    TEMPLATES / ".devcontainer" / "Dockerfile"                 : Path(".devcontainer/Dockerfile"),
    TEMPLATES / ".devcontainer" / "devcontainer.json"          : Path(".devcontainer/devcontainer.json"),
    TEMPLATES / ".devcontainer" / "devcontainer-post-create.sh": Path(".devcontainer/devcontainer-post-create.sh"),
}

# Fichiers dans lesquels MY_APP est remplacé
TARGETS_APP_NAME = [
    Path("docker-compose.yml"),
    Path(".env.example"),
    Path(".github/workflows/publish.yml"),
    Path(".devcontainer/devcontainer.json"),
    Path(".devcontainer/devcontainer-post-create.sh"),
]

# Fichier unique contenant toutes les variables de config
POST_CREATE = Path(".devcontainer/devcontainer-post-create.sh")


# ── Fonctions de transformation ───────────────────────────────────────────────

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
    if POST_CREATE.exists():
        POST_CREATE.chmod(POST_CREATE.stat().st_mode | 0o111)
        logs.append("  ✓  chmod +x devcontainer-post-create.sh")
    return logs


def replace_app_name(app_name: str) -> list[str]:
    logs: list[str] = []
    for file in TARGETS_APP_NAME:
        if not file.exists():
            continue
        content = file.read_text(encoding="utf-8")
        if "MY_APP" not in content:
            continue
        file.write_text(content.replace("MY_APP", app_name), encoding="utf-8")
        logs.append(f"  ✓  MY_APP → {app_name}  ({file})")
    return logs


def replace_script_vars(
    branch: str, site: str, admin_pw: str, db_pw: str,
    title: str, description: str, publisher: str, email: str, license_: str,
) -> list[str]:
    """Injecte toutes les variables dans devcontainer-post-create.sh."""
    if not POST_CREATE.exists():
        return ["  ⚠  devcontainer-post-create.sh introuvable"]

    text = POST_CREATE.read_text(encoding="utf-8")

    replacements = {
        # Environnement dev
        'FRAPPE_BRANCH="version-15"'          : f'FRAPPE_BRANCH="{branch}"',
        'SITE_NAME="development.localhost"'   : f'SITE_NAME="{site}"',
        'DB_ROOT_PASSWORD="123"'              : f'DB_ROOT_PASSWORD="{db_pw}"',
        'ADMIN_PASSWORD="admin"'              : f'ADMIN_PASSWORD="{admin_pw}"',
        # Métadonnées bench new-app
        'APP_TITLE="My App"'                  : f'APP_TITLE="{title}"',
        'APP_DESCRIPTION="My Frappe application"': f'APP_DESCRIPTION="{description}"',
        'APP_PUBLISHER="My Company"'          : f'APP_PUBLISHER="{publisher}"',
        'APP_EMAIL="admin@example.com"'       : f'APP_EMAIL="{email}"',
        'APP_LICENSE="mit"'                   : f'APP_LICENSE="{license_}"',
    }
    for needle, repl in replacements.items():
        text = text.replace(needle, repl)

    POST_CREATE.write_text(text, encoding="utf-8")

    return [
        f"  ✓  FRAPPE_BRANCH    → {branch}",
        f"  ✓  SITE_NAME        → {site}",
        "  ✓  DB_ROOT_PASSWORD → (défini)",
        "  ✓  ADMIN_PASSWORD   → (défini)",
        f"  ✓  APP_TITLE        → {title}",
        f"  ✓  APP_DESCRIPTION  → {description or '(vide)'}",
        f"  ✓  APP_PUBLISHER    → {publisher}",
        f"  ✓  APP_EMAIL        → {email}",
        f"  ✓  APP_LICENSE      → {license_}",
    ]


# ── TUI ───────────────────────────────────────────────────────────────────────

class FDApp(App):
    CSS = """
    Screen {
        background: #0d1117;
        align: center top;
    }

    #main {
        width: 80;
        margin-top: 1;
    }

    /* ── Titres de section ── */
    .section-label {
        color: #58a6ff;
        text-style: bold;
        height: 1;
        margin: 1 0 0 1;
    }

    /* ── Grille formulaire 2 colonnes ── */
    .form-grid {
        grid-size: 2;
        grid-columns: 20 1fr;
        border: solid #30363d;
        padding: 0 2 1 2;
        margin-bottom: 0;
        height: auto;
    }

    .form-grid Label {
        color: #8b949e;
        content-align: left middle;
        height: 3;
        padding: 0 1;
    }

    .form-grid Input {
        height: 3;
        background: #161b22;
        border: tall #30363d;
        color: #e6edf3;
    }

    .form-grid Input:focus {
        border: tall #58a6ff;
    }

    /* ── Boutons ── */
    #btn-row {
        height: 3;
        margin-top: 1;
        margin-bottom: 1;
    }

    #btn-init  { width: 1fr; }
    #btn-bench { width: 1fr; }
    #btn-quit  { width: 12; }

    /* ── Résultat ── */
    #output {
        height: 12;
        border: solid #30363d;
        background: #0d1117;
    }

    #hint {
        color: #484f58;
        text-align: center;
        margin-top: 1;
    }
    """

    BINDINGS = [("escape", "quit", "Quitter")]

    def __init__(self, app_name: str | None = None) -> None:
        super().__init__()
        self._default_name = app_name or default_app_name()
        self._logs: list[str] = []

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with VerticalScroll(id="main"):

            # ── Section APP ───────────────────────────────────────────
            yield Label("APP", classes="section-label")
            with Grid(classes="form-grid"):
                yield Label("Nom de l'app")
                yield Input(self._default_name, id="app-input")
                yield Label("Frappe branch")
                yield Input("version-15", id="branch-input")

            # ── Section INFOS (bench new-app) ─────────────────────────
            yield Label("INFOS  (bench new-app)", classes="section-label")
            with Grid(classes="form-grid"):
                yield Label("App title")
                yield Input(self._default_name, id="title-input")
                yield Label("Description")
                yield Input(self._default_name, id="desc-input")
                yield Label("Publisher")
                yield Input("EasyTalents", id="publisher-input")
                yield Label("Email")
                yield Input("admin@easytalents.fr", id="email-input")
                yield Label("Licence")
                yield Input("apache-2.0", id="license-input")

            # ── Section DEVCONTAINER ──────────────────────────────────
            yield Label("DEVCONTAINER", classes="section-label")
            with Grid(classes="form-grid"):
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
            yield Label("Tab = champ suivant  •  Échap = quitter", id="hint")

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
        name      = self._val("app-input",      self._default_name)
        branch    = self._val("branch-input",    "version-15")
        title     = self._val("title-input",     self._default_name)
        desc      = self._val("desc-input",      self._default_name)
        publisher = self._val("publisher-input",  "EasyTalents")
        email     = self._val("email-input",      "admin@easytalents.fr")
        license_  = self._val("license-input",    "apache-2.0")
        site      = self._val("site-input",       "development.localhost")
        admin     = self.query_one("#admin-input", Input).value or "admin"
        db        = self.query_one("#db-input",    Input).value or "123"

        self._logs.clear()
        self._push([f"── Init : {name} ──", ""])
        try:
            self._push(["Copie des templates…"])
            self._push(copy_templates())
            self._push(["", "Remplacement MY_APP…"])
            self._push(replace_app_name(name))
            self._push(["", "Injection des variables…"])
            self._push(replace_script_vars(branch, site, admin, db, title, desc, publisher, email, license_))
            self._push(["", f"✅  Init terminé — lance le Codespace pour démarrer automatiquement."])
        except Exception as exc:
            self._push([f"", f"❌  Erreur : {exc}"])

    def _show_bench(self) -> None:
        self._logs.clear()
        self._push([
            "── Commandes manuelles (si besoin) ──",
            "",
            "  # Relancer le script de setup :",
            f"  bash .devcontainer/devcontainer-post-create.sh",
            "",
            "  # Lancer le serveur de dev :",
            f"  cd ~/frappe-bench && bench start",
            "",
            f"  # URL : http://development.localhost:8000",
        ])


def main() -> None:
    FDApp().run()


if __name__ == "__main__":
    main()
