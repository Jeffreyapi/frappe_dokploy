"""Export an allowlisted source context from the actual checkout, without Git credentials."""

import argparse
import hashlib
import json
import shutil
from pathlib import Path

from app_sources import load_manifest, package_name


def prepare(project, output, revision):
    project = project.resolve()
    name = package_name(project)
    entries = load_manifest(project / "apps.json")
    if entries[-1]["name"] != name:
        raise ValueError("Local manifest and package identity differ")
    if output.exists():
        raise ValueError("Build context already exists; use a fresh output directory")
    output.mkdir(parents=True)
    allowed = [name, "pyproject.toml", "README.md", "LICENSE", "license.txt", "apps.json",
               "package.json", "yarn.lock", "pnpm-lock.yaml"]
    for item in allowed:
        source = project / item
        if source.is_symlink():
            raise ValueError(f"Symlink metadata is not allowed: {source}")
        if source.is_dir():
            for path in source.rglob("*"):
                if path.is_symlink():
                    raise ValueError(f"Symlinks are not allowed in the image source: {path}")
            shutil.copytree(source, output / item, ignore=shutil.ignore_patterns(
                ".git", ".env", ".env.*", "__pycache__", "*.pyc", "node_modules"))
        elif source.is_file():
            shutil.copy2(source, output / item)
    digest = hashlib.sha256()
    for path in sorted(p for p in output.rglob("*") if p.is_file()):
        digest.update(path.relative_to(output).as_posix().encode() + b"\0" + path.read_bytes())
    (output / "source.json").write_text(json.dumps({
        "revision": revision, "source_sha256": digest.hexdigest(), "apps": entries,
    }, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--revision", required=True)
    args = parser.parse_args()
    prepare(args.project, args.output, args.revision)
