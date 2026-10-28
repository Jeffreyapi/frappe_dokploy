"""Layer source installation, runtime dependency closure and asset finalization checks."""

import json
import os
import subprocess
from pathlib import Path
from unittest.mock import patch

import app_sources
import pytest
from finalize_layer import finalize
from prune_node_modules import build_slice, closure, materialize

ROOT = Path(__file__).resolve().parents[1]

def package(root, name, dependencies=None, optional=None):
    path = root / name
    path.mkdir(parents=True)
    (path / "package.json").write_text(json.dumps({"name": name, "dependencies": dependencies or {},
                                                 "optionalDependencies": optional or {}}))
    (path / "runtime.js").write_text("module.exports = 1;\n")
    return path


def test_nested_and_hoisted_runtime_closure(tmp_path):
    root = tmp_path / "node_modules"
    parent = package(root, "server", {"@scope/shared": "1", "nested": "2"}, {"absent": "1"})
    package(root, "@scope/shared", {"leaf": "1"})
    package(root, "leaf", {"server": "1"})  # cycle
    package(parent / "node_modules", "nested")
    package(root, "unused_build_tool")
    paths = materialize(root, ["server"], tmp_path / "slice")
    assert set(paths) == {"server", "@scope/shared", "leaf", "server/node_modules/nested"}
    assert (tmp_path / "slice/server/node_modules/nested/runtime.js").is_file()
    assert not (tmp_path / "slice/unused_build_tool").exists()
    assert (root / "unused_build_tool").is_dir()  # Parent remains buildable.


def test_missing_dependency_and_escape_are_rejected(tmp_path):
    root = tmp_path / "node_modules"
    package(root, "server", {"missing": "1"})
    with pytest.raises(ValueError, match="Missing dependency"):
        closure(root, ["server"])
    outside = package(tmp_path, "outside")
    (root / "escape").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="escapes"):
        closure(root, ["escape"])
    with pytest.raises(ValueError, match="Invalid runtime package"):
        closure(root, ["../outside"])


def test_app_declarations_and_empty_slices(tmp_path):
    bench = tmp_path / "bench"
    app = bench / "apps/custom"
    root = app / "node_modules"
    package(root, "server")
    package(root, "browser")
    (app / "runtime-node-modules.txt").write_text("server: server\nassets: browser # lazy UI\n")
    result = build_slice(bench, "custom", tmp_path / "slices")
    assert result == {"server": ["server"], "assets": ["browser"]}
    (bench / "apps/empty").mkdir()
    assert build_slice(bench, "empty", tmp_path / "slices") == {"server": [], "assets": []}
    assert (tmp_path / "slices/empty/assets-node_modules").is_dir()


def frappe_bench(tmp_path, dependencies, installed):
    app = tmp_path / "bench/apps/frappe"
    for name in installed:
        package(app / "node_modules", name)
    (app / "package.json").write_text(json.dumps({"dependencies": {name: "1" for name in dependencies}}))
    return tmp_path / "bench"


def test_builtin_roots_follow_the_dependencies_of_the_frappe_version(tmp_path):
    # Frappe 15 ne déclare pas photoswipe ; ses autres racines intégrées restent exigées.
    roots = ["socket.io", "@redis/client", "cookie", "qz-tray", "js-sha256", "html5-qrcode", "frappe-gantt", "ace-builds"]
    bench = frappe_bench(tmp_path, roots, roots)
    result = build_slice(bench, "frappe", tmp_path / "slices")
    assert "photoswipe" not in result["assets"] and "ace-builds" in result["assets"]
    with_photoswipe = frappe_bench(tmp_path / "v16", [*roots, "photoswipe"], [*roots, "photoswipe"])
    assert "photoswipe" in build_slice(with_photoswipe, "frappe", tmp_path / "slices16")["assets"]


def test_declared_builtin_root_missing_from_node_modules_is_still_an_error(tmp_path):
    bench = frappe_bench(tmp_path, ["photoswipe", "socket.io"], ["socket.io"])
    with pytest.raises(ValueError, match="Missing runtime root package"):
        build_slice(bench, "frappe", tmp_path / "slices")


def test_only_installs_selected_dependencies_and_preserves_parent(tmp_path):
    project, bench = tmp_path / "project", tmp_path / "bench"
    project.mkdir(); (bench / "sites").mkdir(parents=True)
    (bench / "sites/apps.txt").write_text("frappe\nerpnext\n")
    entry = {"name": "custom", "url": "https://github.com/example/custom", "revision": "a" * 40}
    (project / "apps.json").write_text(json.dumps([entry]))

    def checkout(entry, path):
        path.mkdir()
        (path / "package.json").write_text("{}")

    with patch.object(app_sources, "checkout_remote", side_effect=checkout), patch.object(app_sources.subprocess, "run") as run:
        assert app_sources.install_sources(project, bench, only="custom") == ["frappe", "erpnext", "custom"]
    calls = [item.args[0] for item in run.call_args_list]
    assert len(calls) == 2
    assert calls[0][:3] == ["uv", "pip", "install"]
    assert calls[1] == ["yarn", "install", "--frozen-lockfile"]
    assert (bench / "sites/apps.txt").read_text() == "frappe\nerpnext\ncustom\n"
    with pytest.raises(ValueError, match="already exists"):
        app_sources.install_sources(project, bench, only="custom")


def test_finalizer_keeps_parent_assets_and_per_app_translations(tmp_path):
    home, project = tmp_path / "home", tmp_path / "project"
    bench = home / "frappe-bench"
    assets = bench / "sites/assets"
    (assets / "custom").mkdir(parents=True)
    (assets / "custom/bundle.js").write_text("built")
    # Lien versionné par erreur dans le dépôt de l'app, vers un chemin de poste de dev.
    public = bench / "apps/custom/custom/public"
    public.mkdir(parents=True)
    (public / "node_modules 2").symlink_to("/workspace/development/custom/node_modules")
    locale = assets / "locale/fr/LC_MESSAGES"
    locale.mkdir(parents=True); (locale / "custom.mo").write_bytes(b"translation")
    (assets / "assets.json").write_text(json.dumps({"custom.bundle.js": "/assets/custom/dist/new.js"}))
    image = home / "image-assets"
    image.mkdir(); (image / "assets.json").write_text(json.dumps({"frappe.bundle.js": "/assets/frappe/dist/parent.js"}))
    project.mkdir()
    entry = {"name": "custom", "url": "https://github.com/example/custom", "revision": "b" * 40}
    (project / "apps.json").write_text(json.dumps([entry]))
    finalize(bench, project, "custom", home, tmp_path / "slices")
    assert json.loads((image / "assets.json").read_text()) == {
        "frappe.bundle.js": "/assets/frappe/dist/parent.js", "custom.bundle.js": "/assets/custom/dist/new.js"}
    assert (tmp_path / "slices/custom/locale/fr/LC_MESSAGES/custom.mo").read_bytes() == b"translation"
    assert sorted(path.name for path in (image / "custom").iterdir()) == ["bundle.js"]
    assert not (public / "node_modules 2").is_symlink()
    assert json.loads((home / "apps-manifest.json").read_text()) == [entry]


def test_gunicorn_env_wrapper(tmp_path):
    executable = tmp_path / "gunicorn"
    executable.write_text("#!/bin/sh\nprintf '%s\\n' \"$@\"\n"); executable.chmod(0o755)
    env = {**os.environ, "PATH": f"{tmp_path}:{os.environ['PATH']}", "GUNICORN_WORKERS": "3", "GUNICORN_MAX_REQUESTS": "500"}
    result = subprocess.run(["bash", str(ROOT / "deploy/scripts/gunicorn.sh")], env=env, capture_output=True, text=True, check=False)
    assert result.returncode == 0 and "--workers=3" in result.stdout and "--max-requests=500" in result.stdout
    env["GUNICORN_WORKERS"] = "3;echo secret"
    assert subprocess.run(["bash", str(ROOT / "deploy/scripts/gunicorn.sh")], env=env, capture_output=True, check=False).returncode != 0




@pytest.mark.parametrize("dockerfile", ["Dockerfile.layer", "Dockerfile.runtime"])
def test_frappe_group_exists_before_it_is_used_in_chown(dockerfile):
    # Frappe 15 crée l'utilisateur `frappe` avec le groupe root : sans groupe `frappe`,
    # `chown frappe:frappe` et `COPY --chown=frappe:frappe` échouent.
    text = (ROOT / dockerfile).read_text()
    guard = text.index("RUN getent group frappe")
    uses = [text.index(m) for m in ("-R frappe:frappe", "--chown=frappe:frappe") if m in text]
    assert uses and all(guard < use for use in uses)


def test_layer_links_node_modules_only_into_the_apps_own_module():
    # `frontend/public` (Vite) lié vers le workspace racine bouclerait : ELOOP à la copie du public/.
    text = (ROOT / "Dockerfile.layer").read_text()
    assert 'apps/"$LAYER_APP"/*/public' not in text
    assert 'public=apps/"$LAYER_APP"/"$LAYER_APP"/public' in text
