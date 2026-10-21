"""`bench backup` supprime avec `os.remove` tout ce qui est ancien dans `private/backups/`."""

import importlib.util
from pathlib import Path

BACKUP_PY = Path(__file__).resolve().parents[1] / "deploy/scripts/backup.py"


def load_backup_module():
    spec = importlib.util.spec_from_file_location("backup_script", BACKUP_PY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_backup_sets_live_outside_the_directory_frappe_cleans(tmp_path, monkeypatch):
    backup = load_backup_module()
    calls = []

    def fake_command(*args, cwd=None):
        calls.append(args)
        raise RuntimeError("stop after the bench call")

    monkeypatch.setattr(backup, "command", fake_command)
    try:
        backup.create(tmp_path, "site.example.com", "dep")
    except RuntimeError:
        pass

    path = Path(calls[0][calls[0].index("--backup-path") + 1])
    frappe_backups = tmp_path / "sites/site.example.com/private/backups"
    assert path.is_dir()
    assert frappe_backups not in path.parents
    assert path.parent == tmp_path / "sites/site.example.com/private/backup-sets"
