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


def set_id(day, suffix="a"):
    return f"202610{day:02d}T020000-{suffix * 32}"


def make_set(root, name, complete=True, age_seconds=0):
    directory = root / name
    directory.mkdir(parents=True)
    (directory / "database.sql.gz").write_text("x")
    if complete:
        (directory / "manifest.json").write_text("{}")
    if age_seconds:
        import os
        import time

        old = time.time() - age_seconds
        os.utime(directory, (old, old))
    return directory


def test_prune_keeps_the_latest_complete_sets_and_drops_stale_incomplete_ones(tmp_path):
    backup = load_backup_module()
    for day in (1, 2, 3):
        make_set(tmp_path, set_id(day))
    stale = make_set(tmp_path, set_id(4, "b"), complete=False, age_seconds=2 * 86400)
    running = make_set(tmp_path, set_id(5, "c"), complete=False)

    backup.prune_local_sets(tmp_path, keep=2)

    assert sorted(p.name for p in tmp_path.iterdir()) == sorted([set_id(2), set_id(3), running.name])
    assert not stale.exists()


def test_prune_ignores_foreign_entries_and_symlinks(tmp_path):
    backup = load_backup_module()
    foreign = tmp_path / "notes"
    foreign.mkdir()
    outside = tmp_path / "outside"
    make_set(outside, set_id(1))
    link = tmp_path / "sets" / set_id(2)
    link.parent.mkdir()
    link.symlink_to(outside / set_id(1))

    backup.prune_local_sets(tmp_path / "sets", keep=0)

    assert foreign.exists() and (outside / set_id(1) / "manifest.json").exists()


def test_legacy_sets_directory_is_adopted_so_frappe_cannot_trip_on_it(tmp_path):
    backup = load_backup_module()
    private = tmp_path / "sites/site.example.com/private"
    legacy = private / "backups" / "sets"
    make_set(legacy, set_id(1))
    (legacy / "stray.txt").write_text("not a set")

    backup.adopt_legacy_sets(tmp_path, "site.example.com")

    assert not legacy.exists()
    assert (private / "backup-sets" / set_id(1) / "manifest.json").exists()
    backup.adopt_legacy_sets(tmp_path, "site.example.com")  # idempotent, rien à adopter


def fake_create_steps(backup, monkeypatch, uploads):
    def fake_command(*args, cwd=None):
        return None

    def fake_manifest(directory, site, deployment):
        (directory / "manifest.json").write_text("{}")

    monkeypatch.setattr(backup, "command", fake_command)
    monkeypatch.setattr(backup, "make_manifest", fake_manifest)
    monkeypatch.setattr(backup, "upload", lambda directory, site, deployment: uploads.append(directory))


def test_create_drops_the_local_set_once_uploaded(tmp_path, monkeypatch):
    backup = load_backup_module()
    uploads = []
    fake_create_steps(backup, monkeypatch, uploads)
    monkeypatch.setenv("S3_BACKUP_ENABLED", "1")
    monkeypatch.delenv("BACKUP_LOCAL_KEEP", raising=False)

    backup.create(tmp_path, "site.example.com", "dep")

    assert len(uploads) == 1
    assert list((tmp_path / "sites/site.example.com/private/backup-sets").iterdir()) == []


def test_create_keeps_the_last_local_sets_when_s3_is_disabled(tmp_path, monkeypatch):
    backup = load_backup_module()
    fake_create_steps(backup, monkeypatch, [])
    monkeypatch.setenv("S3_BACKUP_ENABLED", "0")
    monkeypatch.delenv("BACKUP_LOCAL_KEEP", raising=False)
    root = tmp_path / "sites/site.example.com/private/backup-sets"
    for day in (1, 2, 3, 4):
        make_set(root, set_id(day))

    backup.create(tmp_path, "site.example.com", "dep")

    assert len(list(root.iterdir())) == backup.LOCAL_KEEP_WHEN_LOCAL_ONLY


def test_local_keep_override_must_be_a_number(monkeypatch):
    backup = load_backup_module()
    monkeypatch.setenv("BACKUP_LOCAL_KEEP", "2")
    assert backup.local_keep(True) == 2
    monkeypatch.setenv("BACKUP_LOCAL_KEEP", "-1")
    try:
        backup.local_keep(True)
    except ValueError:
        return
    raise AssertionError("expected ValueError")
