#!/usr/bin/env python
"""
Test headless de la logique fd.py (copie + replace).
Lance depuis la racine du repo :  python scripts/test_fd.py

Crée un dossier temporaire, y exécute copy_templates / replace_my_app /
replace_dev_vars, puis affiche les résultats et vérifie les fichiers attendus.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

# Ajouter scripts/ au path pour importer fd sans l'installer
sys.path.insert(0, str(Path(__file__).parent))

import fd  # noqa: E402  (import après manipulation de sys.path)

# ── Paramètres de test ────────────────────────────────────────────────────────
TEST_APP    = "test_app"
TEST_BRANCH = "version-15"
TEST_SITE   = "development.localhost"
TEST_ADMIN  = "admin_test"
TEST_DB     = "db_test"

EXPECTED_FILES = [
    "docker-compose.yml",
    ".env.example",
    "Makefile",
    ".github/workflows/publish.yml",
    ".devcontainer/Dockerfile",
    ".devcontainer/devcontainer.json",
    ".devcontainer/devcontainer-post-create.sh",
]

# ── Helpers ───────────────────────────────────────────────────────────────────

def sep(title: str) -> None:
    print(f"\n── {title} {'─' * (50 - len(title))}")


def ok(msg: str) -> None:
    print(f"  \033[32m✓\033[0m  {msg}")


def err(msg: str) -> None:
    print(f"  \033[31m✗\033[0m  {msg}")


# ── Test principal ────────────────────────────────────────────────────────────

def run_tests(sandbox: Path) -> int:
    failures = 0
    original_cwd = Path.cwd()

    try:
        os.chdir(sandbox)

        # 1. copy_templates
        sep("copy_templates")
        logs = fd.copy_templates()
        for line in logs:
            print(f"  {line}")

        # 2. Vérification des fichiers copiés
        sep("Fichiers attendus")
        for rel in EXPECTED_FILES:
            p = Path(rel)
            if p.exists():
                ok(rel)
            else:
                err(f"MANQUANT : {rel}")
                failures += 1

        # 3. replace_my_app
        sep("replace_my_app")
        logs = fd.replace_my_app(TEST_APP)
        for line in logs:
            print(f"  {line}")

        # Vérifier que MY_APP n'apparaît plus dans les fichiers remplacés
        sep("Vérification MY_APP remplacé")
        for rel in fd.TARGETS_REPLACE:
            p = Path(rel)
            if not p.exists():
                continue
            content = p.read_text(encoding="utf-8")
            if "MY_APP" in content:
                err(f"MY_APP encore présent dans {rel}")
                failures += 1
            elif TEST_APP in content:
                ok(f"{rel}  (MY_APP → {TEST_APP})")

        # 4. replace_dev_vars
        sep("replace_dev_vars")
        logs = fd.replace_dev_vars(TEST_BRANCH, TEST_SITE, TEST_ADMIN, TEST_DB)
        for line in logs:
            print(f"  {line}")

        # Vérifier que les variables ont bien été injectées
        sep("Vérification variables devcontainer")
        sh = Path(".devcontainer/devcontainer-post-create.sh")
        if sh.exists():
            content = sh.read_text(encoding="utf-8")
            checks = {
                f'FRAPPE_BRANCH="{TEST_BRANCH}"': "FRAPPE_BRANCH",
                f'SITE_NAME="{TEST_SITE}"':        "SITE_NAME",
                f'DB_ROOT_PASSWORD="{TEST_DB}"':   "DB_ROOT_PASSWORD",
                f'ADMIN_PASSWORD="{TEST_ADMIN}"':  "ADMIN_PASSWORD",
            }
            for needle, label in checks.items():
                if needle in content:
                    ok(f"{label} injecté")
                else:
                    err(f"{label} NON trouvé dans le script")
                    failures += 1

    finally:
        os.chdir(original_cwd)

    return failures


def main() -> None:
    sandbox = Path(tempfile.mkdtemp(prefix="frappe_fd_test_"))
    print(f"Sandbox : {sandbox}")

    failures = run_tests(sandbox)

    print()
    if failures == 0:
        print("\033[32m✅  Tous les tests sont passés.\033[0m")
        print(f"   Fichiers générés dans : {sandbox}")
    else:
        print(f"\033[31m❌  {failures} échec(s).\033[0m")
        sys.exit(1)


if __name__ == "__main__":
    main()
