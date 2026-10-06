"""Headless manifest validation checks. No files are written outside a temporary directory."""
import json
import tempfile
from pathlib import Path

from app_sources import (
    SLOTS, link_public_node_modules, load_manifest, register_apps, split_slots, write_slots,
)

REMOTE_A = {"name": "hermes_control", "url": "https://github.com/example/hermes_control",
            "revision": "a" * 40}
REMOTE_B = {"name": "other_app", "url": "https://github.com/example/other_app",
            "revision": "b" * 40}
LOCAL = {"name": "local_app", "path": "."}


def write(directory, entries):
    path = Path(directory) / "apps.json"
    path.write_text(json.dumps(entries), encoding="utf-8")
    return path


def remote(index, revision=None):
    return {"name": f"app_{index}", "url": f"https://github.com/example/app_{index}",
            "revision": revision or f"{index}" * 40}


def check_slots(temporary):
    root = Path(temporary)

    # Une app distante par slot, slots inutilisés vides, app locale exclue.
    groups = split_slots([remote(1), remote(2), remote(3), LOCAL])
    assert len(groups) == SLOTS
    assert [[app["name"] for app in group] for group in groups[:4]] == [["app_1"], ["app_2"], ["app_3"], []]
    assert all(group == [] for group in groups[3:])

    # Au-delà de SLOTS apps, le dernier slot reçoit toutes les restantes.
    groups = split_slots([remote(index) for index in range(1, SLOTS + 3)])
    assert len(groups) == SLOTS
    assert [len(group) for group in groups] == [1] * (SLOTS - 1) + [3]
    assert [app["name"] for app in groups[-1]] == [f"app_{index}" for index in range(SLOTS, SLOTS + 3)]

    # Clé de cache : modifier une app ne change que son slot (et le contenu ne
    # dépend pas de l'ordre des clés d'apps.json).
    def slot_files(entries, name):
        project = root / name
        project.mkdir()
        write(project, entries)
        write_slots(project, project / "slots")
        return [(project / "slots" / f"slot-{i}.json").read_text(encoding="utf-8") for i in range(1, SLOTS + 1)]

    before = slot_files([remote(1), remote(2), remote(3)], "before")
    reordered = {key: remote(3, "c" * 40)[key] for key in ("revision", "url", "name")}
    after = slot_files([remote(1), remote(2), reordered], "after")
    assert before[:2] == after[:2], "unchanged apps must keep identical slot files"
    assert before[2] != after[2]
    assert before[3:] == after[3:] == ["[]"] * (SLOTS - 3)

    # register_apps est idempotent et conserve l'ordre.
    bench = root / "bench"
    (bench / "apps").mkdir(parents=True)
    (bench / "sites").mkdir()
    for path in (bench / "apps" / "apps.txt", bench / "sites" / "apps.txt"):
        path.write_text("frappe\n", encoding="utf-8")
    register_apps(bench, ["app_1"])
    register_apps(bench, ["app_1", "app_2"])
    for path in (bench / "apps" / "apps.txt", bench / "sites" / "apps.txt"):
        assert path.read_text(encoding="utf-8") == "frappe\napp_1\napp_2\n"

    # public/node_modules : lien créé seulement si l'app a un node_modules,
    # lien cassé remplacé, lien valide conservé.
    with_modules = bench / "apps" / "app_1"
    (with_modules / "node_modules").mkdir(parents=True)
    (with_modules / "app_1" / "public").mkdir(parents=True)
    (with_modules / "app_1" / "docs").mkdir()
    link_public_node_modules(bench, "app_1")
    link = with_modules / "app_1" / "public" / "node_modules"
    assert link.is_symlink() and link.resolve() == (with_modules / "node_modules").resolve()
    assert not (with_modules / "app_1" / "docs" / "public").exists()
    link.unlink()
    link.symlink_to("missing")
    link_public_node_modules(bench, "app_1")
    assert link.resolve() == (with_modules / "node_modules").resolve()
    without_modules = bench / "apps" / "app_2"
    (without_modules / "app_2" / "public").mkdir(parents=True)
    link_public_node_modules(bench, "app_2")
    assert not (without_modules / "app_2" / "public" / "node_modules").exists()

    # Le Dockerfile référence chaque slot, dans l'ordre.
    dockerfile = (Path(__file__).resolve().parent.parent / "Dockerfile").read_text(encoding="utf-8")
    positions = [dockerfile.index(f"--slot /opt/slots/slot-{i}.json") for i in range(1, SLOTS + 1)]
    assert positions == sorted(positions)
    assert f"slot-{SLOTS + 1}.json" not in dockerfile


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

        check_slots(temporary)

    print("Manifest checks passed")


# Point d'entrée pytest (optionnel) : le fichier reste un runner autonome,
# mais `python -m pytest scripts/test_app_sources.py` collecte ce test.
def test_manifest_checks():
    main()


if __name__ == "__main__":
    main()
