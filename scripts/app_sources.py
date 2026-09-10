"""Install explicitly named, immutable sources, without inferring identity from URLs."""

import argparse
import json
import re
import shutil
import subprocess
import tempfile
import tomllib
import uuid
from pathlib import Path
from urllib.parse import urlparse


def run(*args, cwd=None):
    return subprocess.check_output(args, cwd=cwd, text=True).strip()


def load_manifest(path):
    entries = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(entries, list) or not entries:
        raise ValueError("An ordered, nonempty apps manifest is required")
    names, local = set(), []
    for app in entries:
        name = app.get("name", "")
        if not re.fullmatch(r"[a-z][a-z0-9_]*", name) or name in names or name == "frappe":
            raise ValueError(f"Invalid or duplicate app name: {name}")
        names.add(name)
        if "path" in app:
            if set(app) != {"name", "path"} or app["path"] != ".":
                raise ValueError("The local app must reference the project root")
            local.append(app)
        else:
            if set(app) != {"name", "url", "revision"}:
                raise ValueError(f"Invalid remote app fields: {name}")
            url = urlparse(app["url"])
            if url.scheme != "https" or not url.hostname or url.username or url.password or url.query or url.fragment:
                raise ValueError("Use a credential-free HTTPS source URL")
            if not re.fullmatch(r"[0-9a-f]{40}", app["revision"]):
                raise ValueError(f"A full immutable commit SHA is required for {name}")
    if len(local) != 1 or entries[-1] != local[0]:
        raise ValueError("Exactly one local app must be the last entry")
    return entries


def package_name(project):
    with (project / "pyproject.toml").open("rb") as stream:
        return tomllib.load(stream)["project"]["name"]


def checkout_remote(app, destination):
    if destination.exists():
        if run("git", "rev-parse", "HEAD", cwd=destination) != app["revision"]:
            raise ValueError(f"Different revision in {destination}; archive it before changing the pin")
        if run("git", "status", "--porcelain", cwd=destination):
            raise ValueError(f"Local edits in {destination}; refusing to replace them")
        return
    with tempfile.TemporaryDirectory(prefix=".fetch-", dir=destination.parent) as temporary:
        staged = Path(temporary) / app["name"]
        subprocess.run(["git", "init", str(staged)], check=True)
        subprocess.run(["git", "remote", "add", "origin", app["url"]], cwd=staged, check=True)
        subprocess.run(["git", "fetch", "--depth=1", "origin", app["revision"]], cwd=staged, check=True)
        subprocess.run(["git", "checkout", "--detach", "FETCH_HEAD"], cwd=staged, check=True)
        if run("git", "rev-parse", "HEAD", cwd=staged) != app["revision"]:
            raise ValueError("Fetched revision differs from the manifest")
        if package_name(staged) != app["name"]:
            raise ValueError("Package identity differs from the manifest")
        staged.rename(destination)


def link_local(project, destination):
    if destination.is_symlink() and destination.resolve() == project.resolve():
        return
    if destination.exists() or destination.is_symlink():
        archive = destination.parent.parent / "archived" / "apps"
        archive.mkdir(parents=True, exist_ok=True)
        target = archive / f"{destination.name}-{uuid.uuid4().hex}"
        destination.rename(target)
        print(f"Previous app preserved in {target}")
    destination.symlink_to(project.resolve(), target_is_directory=True)


def install_sources(project, bench, development=False):
    entries = load_manifest(project / "apps.json")
    if package_name(project) != entries[-1]["name"]:
        raise ValueError("Local package identity differs from apps.json")
    apps_dir = bench / "apps"
    apps_dir.mkdir(exist_ok=True)
    for app in entries:
        destination = apps_dir / app["name"]
        if "url" in app:
            checkout_remote(app, destination)
        elif development:
            link_local(project, destination)
        elif not destination.exists():
            shutil.copytree(project, destination, ignore=shutil.ignore_patterns(".git", "__pycache__"))
        else:
            raise ValueError(f"Refusing to overwrite {destination}")
    names = ["frappe", *(app["name"] for app in entries)]
    for path in (apps_dir / "apps.txt", bench / "sites" / "apps.txt"):
        path.write_text("\n".join(names) + "\n", encoding="utf-8")
    subprocess.run(["bench", "setup", "requirements"], cwd=bench, check=True)
    return names


def install_on_site(project, bench, site):
    expected = ["frappe", *(app["name"] for app in load_manifest(project / "apps.json"))]
    installed = json.loads(run("bench", "--site", site, "list-apps", "--format", "json", cwd=bench))[site]
    for name in expected:
        if name not in installed:
            subprocess.run(["bench", "--site", site, "install-app", name], cwd=bench, check=True)
    installed = json.loads(run("bench", "--site", site, "list-apps", "--format", "json", cwd=bench))[site]
    if set(expected) - set(installed):
        raise ValueError("Site installation incomplete")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--bench", type=Path, required=True)
    parser.add_argument("--development", action="store_true")
    parser.add_argument("--site")
    args = parser.parse_args()
    if args.site:
        install_on_site(args.project, args.bench, args.site)
    else:
        install_sources(args.project, args.bench, args.development)


if __name__ == "__main__":
    main()
