#!/usr/bin/env python
"""
TUI Textual pour automatiser les étapes d'init d'une app Frappe avec le submodule frappe_dokploy.

Fonctions :
- Init : copie les templates depuis frappe_deploy, remplace MY_APP par le nom choisi.
- Bench cmds : affiche les commandes à exécuter dans un environnement disposant de bench (devcontainer/Codespaces).

Contraintes :
- Aucune action Docker.
- App par défaut = nom du dossier courant (surchage possible).
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

try:
    from textual.app import App, ComposeResult
    from textual.containers import Horizontal, Vertical
    from textual.widgets import Button, Footer, Header, Input, Label, Static, TextArea
    from textual.message import Message
except ImportError:  # pragma: no cover - guidance for users sans dépendances
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
        logs.append(f"copié: {dst}")
    dst = Path(".devcontainer/devcontainer-post-create.sh")
    if dst.exists():
        dst.chmod(dst.stat().st_mode | 0o111)
        logs.append("chmod +x devcontainer-post-create.sh")
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
        logs.append(f"MY_APP -> {app_name} : {file}")
    return logs


def bench_commands(app_name: str) -> str:
    return f"""# A exécuter dans le devcontainer / Codespaces (bench déjà dispo)
cd ~/frappe-bench
bench new-app {app_name}

# ramener le code dans le repo et symlink pour hot-reload
cp -a apps/{app_name}/. /workspaces/{app_name}/
rm -rf apps/{app_name}
ln -s /workspaces/{app_name} apps/{app_name}

# installer l'app sur le site de dev
bench --site development.localhost install-app {app_name}
bench start  # http://development.localhost:8000
"""


class InitCompleted(Message):
    def __init__(self, logs: list[str]) -> None:
        super().__init__()
        self.logs = logs


class FDApp(App):
    CSS = """
    Screen {align: center middle;}
    #panel {width: 90%; height: 80%;}
    #actions Button {margin: 1 1;}
    #logs {height: 12; border: solid #666;}
    """

    BINDINGS = [("q", "quit", "Quitter")]

    def __init__(self, app_name: str | None = None) -> None:
        super().__init__()
        self._app_name = app_name or default_app_name()
        self.logs: list[str] = []

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="panel"):
            yield Label("frappe_dokploy TUI — init & aide bench", id="title")
            with Horizontal(id="actions"):
                yield Button("Init (copie + replace)", id="btn-init", variant="success")
                yield Button("Voir commandes bench", id="btn-bench", variant="primary")
                yield Button("Quitter", id="btn-quit", variant="error")
            yield Input(self._app_name, placeholder="Nom de l'app", id="app-input")
            yield Static("Logs :", id="log-label")
            yield TextArea("", id="logs", read_only=True, theme="monokai")
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-init":
            self.do_init()
        elif event.button.id == "btn-bench":
            self.show_bench()
        elif event.button.id == "btn-quit":
            self.exit()

    def write_logs(self, lines: list[str]) -> None:
        if not lines:
            return
        self.logs.extend(lines)
        ta = self.query_one("#logs", TextArea)
        ta.load_text("\n".join(self.logs))
        ta.scroll_end()

    def app_name(self) -> str:
        return self.query_one("#app-input", Input).value.strip() or default_app_name()

    def do_init(self) -> None:
        name = self.app_name()
        try:
            log_copy = copy_templates()
            log_replace = replace_my_app(name)
            self.write_logs([f"[ok] Init terminé pour {name}"] + log_copy + log_replace)
        except Exception as exc:  # pragma: no cover
            self.write_logs([f"[err] {exc}"])

    def show_bench(self) -> None:
        cmds = bench_commands(self.app_name())
        self.write_logs(["[info] commandes bench prêtes; ouvrir l'aide complète"])
        self.push_screen(CommandScreen(cmds))


class CommandScreen(App):
    CSS = """
    Screen {align: center middle;}
    #wrap {width: 90%; height: 90%;}
    #cmds {border: solid #666;}
    """

    BINDINGS = [("escape", "pop_screen", "Retour"), ("q", "pop_screen", "Retour")]

    def __init__(self, commands: str) -> None:
        super().__init__()
        self.commands = commands

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Vertical(id="wrap"):
            yield Label("Commandes à exécuter dans le devcontainer", id="subtitle")
            yield TextArea(self.commands, id="cmds", read_only=True, theme="monokai")
        yield Footer()

    def action_pop_screen(self) -> None:
        self.pop_screen()


def main() -> None:
    app = FDApp()
    app.run()


if __name__ == "__main__":
    main()
