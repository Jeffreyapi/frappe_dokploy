"""Write cumulative manifests and one app's materialized assets for assembly."""

import argparse
import json
import os
import shutil
from pathlib import Path

from app_sources import load_manifest


def skip_unmaterializable(directory, names):
    """node_modules, et les liens symboliques qui ne pointent sur rien : un dépôt d'app peut en
    versionner par erreur (cible absolue d'un poste de dev) et `copytree` échouerait dessus."""
    base = Path(directory)
    return [name for name in names
            if name == "node_modules" or ((base / name).is_symlink() and not (base / name).exists())]


def finalize(bench, project, app, home, slices=Path("/opt/runtime-slice")):
    manifest_path = home / "apps-manifest.json"
    entries = json.loads(manifest_path.read_text()) if manifest_path.exists() else []
    if app != "frappe":
        selected = load_manifest(project / "apps.json")
        if len(selected) != 1 or selected[0]["name"] != app or any(item["name"] == app for item in entries):
            raise ValueError("Layer manifest must contain exactly one new app")
        entries.extend(selected)
    manifest_path.write_text(json.dumps(entries, separators=(",", ":")) + "\n")
    (home / "source.json").write_text(json.dumps({"revision": os.environ.get("SOURCE_REVISION", "unknown"),
                                                "apps": entries}, separators=(",", ":")) + "\n")
    assets = home / "image-assets"
    assets.mkdir(exist_ok=True)
    target = assets / app
    if target.exists():
        shutil.rmtree(target)
    source = bench / "sites/assets" / app
    if source.exists():
        # The bench's app asset directories are symlinks; materialize them so the
        # immutable runtime copy does not point back into a build bench.
        shutil.copytree(source, target, symlinks=False, ignore=skip_unmaterializable)
    else:
        target.mkdir()
    for name in ("assets.json", "assets-rtl.json"):
        source = bench / "sites/assets" / name
        current = json.loads(source.read_text()) if source.exists() else {}
        previous = assets / name
        merged = json.loads(previous.read_text()) if previous.exists() else {}
        # Drop only entries belonging to the rebuilt app, retain other bundles.
        merged = {key: value for key, value in merged.items()
                  if not isinstance(value, str) or not value.startswith((f"/{app}/", f"/assets/{app}/"))}
        merged.update(current)
        previous.write_text(json.dumps(merged, sort_keys=True, separators=(",", ":")) + "\n")
        source.write_text(previous.read_text())
    locale = slices / app / "locale"
    locale.mkdir(parents=True, exist_ok=True)
    for source in (bench / "sites/assets/locale").glob(f"*/LC_MESSAGES/{app}.mo"):
        destination = locale / source.relative_to(bench / "sites/assets/locale")
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--bench", type=Path, required=True)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--app", required=True)
    args = parser.parse_args()
    finalize(args.bench, args.project, args.app, args.bench.resolve().parent)


if __name__ == "__main__":
    main()
