"""Headless generator checks. No files are written outside a temporary directory."""
import json
import os
import tempfile
from pathlib import Path

import fd


def main():
    previous = Path.cwd()
    with tempfile.TemporaryDirectory(prefix="frappe-generator-") as temporary:
        try:
            os.chdir(temporary)
            fd.gen_apps_json("hermes_control", "Example")
            assert json.loads(Path("apps.json").read_text()) == [{"name": "hermes_control", "path": "."}]
            fd.gen_devcontainer_json("hermes_control")
            config = json.loads(Path(".devcontainer/devcontainer.json").read_text())
            assert config["service"] == "workspace"
            assert "mariadb:11.8" in Path(".devcontainer/docker-compose.yml").read_text()
            fd.gen_vscode_settings("hermes_control", "must-not-be-committed")
            assert "must-not-be-committed" not in Path(".vscode/settings.json").read_text()
            fd.gen_publish_workflow("hermes_control", "Example", "v16.33.1")
            assert "@main" not in Path(".github/workflows/publish.yml").read_text()
        finally:
            os.chdir(previous)
    print("Generator checks passed")


if __name__ == "__main__":
    main()
