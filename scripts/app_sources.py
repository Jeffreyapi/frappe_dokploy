"""Install explicitly named, immutable sources, without inferring identity from URLs."""

import argparse
import base64
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
import uuid
from pathlib import Path
from urllib.parse import urlparse

import tomllib

ASKPASS_TEMPLATE = """#!/bin/sh
case "$1" in
  Username*) echo "x-access-token" ;;
  Password*) echo "$GIT_CREDENTIAL_RESPONSE" ;;
esac
"""


def credential_prompt_env() -> dict[str, str]:
    """Extra git environment for an authenticated fetch, or {} for anonymous.

    The token comes from GITHUB_TOKEN, present only inside the RUN decorated
    with --mount=type=secret in the Dockerfile (never in build args, never in
    apps.json, never in the image layers; anonymous fetch when unset/empty).
    It is passed to git out-of-band via a short-lived askpass helper (mode
    0700, unlinked right after the fetch) answering with an HTTP Basic auth
    header — ``Basic b64(\"x-access-token:<token>\")`` for a raw token, or a
    pre-encoded \"Basic ...\" value left as is.
    """
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if not token:
        return {}
    response = (
        token
        if token.startswith("Basic ")
        else "Basic "
        + base64.b64encode(("x-access-token:" + token).encode("utf-8")).decode("ascii")
    )
    fd, helper = tempfile.mkstemp(prefix=".git-askpass-")
    os.write(fd, ASKPASS_TEMPLATE.encode("ascii"))
    os.close(fd)
    os.chmod(helper, stat.S_IRWXU)
    return {
        "GIT_ASKPASS": helper,
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_CREDENTIAL_RESPONSE": response,
    }


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
    if len(local) > 1 or (local and entries[-1] != local[0]):
        raise ValueError("At most one local app is allowed, and it must be the last entry")
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
        extra_env = credential_prompt_env()
        try:
            subprocess.run(
                ["git", "fetch", "--depth=1", "origin", app["revision"]],
                cwd=staged,
                check=True,
                env={**os.environ, **extra_env},
            )
        finally:
            helper = extra_env.get("GIT_ASKPASS")
            if helper:
                os.unlink(helper)  # vécu ~une commande ; le token n'y reste pas
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


def install_sources(project, bench, development=False, revision=None):
    entries = load_manifest(project / "apps.json")
    if entries and "path" in entries[-1] and package_name(project) != entries[-1]["name"]:
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
            # Bench instantiates git.Repo on every on-disk app during
            # `bench setup requirements`, so the copied local app needs a
            # repository. A single-commit snapshot (no remote) is enough:
            # the authoritative source identity stays in source.json.
            snapshot = revision
            if not snapshot:
                manifest = project / "source.json"
                if manifest.exists():
                    snapshot = json.loads(manifest.read_text(encoding="utf-8")).get("revision")
            subprocess.run(["git", "init", "-q", str(destination)], check=True)
            subprocess.run(["git", "-C", str(destination), "add", "-A"], check=True)
            subprocess.run(
                ["git", "-C", str(destination), "-c", "user.name=frappe-deploy",
                 "-c", "user.email=build@frappe-deploy.invalid", "commit", "--no-gpg-sign",
                 "-q", "-m", f"Local app snapshot for bench (source {snapshot or 'unknown'})"],
                check=True,
            )
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
        revision = None
        source_manifest = args.project / "source.json"
        if source_manifest.exists():
            revision = json.loads(source_manifest.read_text(encoding="utf-8")).get("revision")
        install_sources(args.project, args.bench, args.development, revision)


if __name__ == "__main__":
    main()
