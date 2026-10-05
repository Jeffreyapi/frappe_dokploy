"""Headless manifest validation checks. No files are written outside a temporary directory."""
import json
import tempfile
from pathlib import Path

from app_sources import load_manifest

REMOTE_A = {"name": "hermes_control", "url": "https://github.com/example/hermes_control",
            "revision": "a" * 40}
REMOTE_B = {"name": "other_app", "url": "https://github.com/example/other_app",
            "revision": "b" * 40}
LOCAL = {"name": "local_app", "path": "."}


def write(directory, entries):
    path = Path(directory) / "apps.json"
    path.write_text(json.dumps(entries), encoding="utf-8")
    return path


def main():
    with tempfile.TemporaryDirectory(prefix="app-sources-") as temporary:
        # All-remote manifest (no local app) is now accepted.
        assert load_manifest(write(temporary, [REMOTE_A, REMOTE_B])) == [REMOTE_A, REMOTE_B]

        # A single local app as the last entry is still accepted.
        assert load_manifest(write(temporary, [REMOTE_A, LOCAL])) == [REMOTE_A, LOCAL]

        # More than one local app is still rejected.
        try:
            load_manifest(write(temporary, [LOCAL, {**LOCAL, "name": "other_app"}]))
            raise AssertionError("Expected rejection of two local apps")
        except ValueError:
            pass

        # A local app that isn't the last entry is still rejected.
        try:
            load_manifest(write(temporary, [LOCAL, REMOTE_A]))
            raise AssertionError("Expected rejection of a local app not in last position")
        except ValueError:
            pass

        # Credentialed source URLs are still rejected.
        try:
            load_manifest(write(temporary, [{**REMOTE_A, "url": "https://user:pass@github.com/example/hermes_control"}]))
            raise AssertionError("Expected rejection of a credentialed URL")
        except ValueError:
            pass

        # Non-HTTPS source URLs are still rejected.
        try:
            load_manifest(write(temporary, [{**REMOTE_A, "url": "git://github.com/example/hermes_control"}]))
            raise AssertionError("Expected rejection of a non-HTTPS URL")
        except ValueError:
            pass

        # A revision that isn't a full 40-hex commit SHA is still rejected.
        try:
            load_manifest(write(temporary, [{**REMOTE_A, "revision": "main"}]))
            raise AssertionError("Expected rejection of a non-SHA revision")
        except ValueError:
            pass

    print("Manifest checks passed")


# Point d'entrée pytest (optionnel) : le fichier reste un runner autonome,
# mais `python -m pytest scripts/test_app_sources.py` collecte ce test.
def test_manifest_checks():
    main()


if __name__ == "__main__":
    main()
