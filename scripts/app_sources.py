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
    0700, unlinked right after the fetch) answering with the raw token: git
    itself composes the HTTP authorization header. A pre-encoded \"Basic ...\"
    value found in the secret is decoded defensively (b64 payload after the
    prefix, keeping the part after the colon); on decode failure or empty
    result the fetch stays anonymous.
    """
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if not token:
        return {}
    if token.startswith("Basic "):
        try:
            decoded = base64.b64decode(token[len("Basic "):]).decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            return {}
        response = decoded.split(":", 1)[1] if ":" in decoded else decoded
        if not response:
            return {}
    else:
        response = token
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


def validate_remote(app):
    name = app.get("name", "")
    if set(app) != {"name", "url", "revision"}:
        raise ValueError(f"Invalid remote app fields: {name}")
    url = urlparse(app["url"])
    if url.scheme != "https" or not url.hostname or url.username or url.password or url.query or url.fragment:
        raise ValueError("Use a credential-free HTTPS source URL")
    if not re.fullmatch(r"[0-9a-f]{40}", app["revision"]):
        raise ValueError(f"A full immutable commit SHA is required for {name}")


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
            validate_remote(app)
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


def install_entry(project, bench, app, development=False, revision=None):
    destination = bench / "apps" / app["name"]
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


def install_sources(project, bench, development=False, revision=None):
    entries = load_manifest(project / "apps.json")
    if entries and "path" in entries[-1] and package_name(project) != entries[-1]["name"]:
        raise ValueError("Local package identity differs from apps.json")
    apps_dir = bench / "apps"
    apps_dir.mkdir(exist_ok=True)
    for app in entries:
        install_entry(project, bench, app, development, revision)
    names = ["frappe", *(app["name"] for app in entries)]
    for path in (apps_dir / "apps.txt", bench / "sites" / "apps.txt"):
        path.write_text("\n".join(names) + "\n", encoding="utf-8")
    subprocess.run(["bench", "setup", "requirements"], cwd=bench, check=True)
    return names


# --- Build incrémental (une couche Docker par app) -------------------------
# Le Dockerfile n'a pas de boucle : le nombre de couches est fixe. `split`
# répartit donc les apps distantes sur SLOTS fichiers, un par couche ; la
# dernière couche reçoit toutes les apps restantes. BuildKit compare le
# contenu de chaque fichier (COPY) : une app inchangée garde sa couche en
# cache tant que celles qui la précèdent n'ont pas changé non plus.
SLOTS = 6


def split_slots(entries, slots=SLOTS):
    remote = [app for app in entries if "url" in app]
    groups = [[app] for app in remote[: slots - 1]]
    if remote[slots - 1 :]:
        groups.append(remote[slots - 1 :])
    return groups + [[] for _ in range(slots - len(groups))]


def write_slots(project, out, slots=SLOTS):
    groups = split_slots(load_manifest(project / "apps.json"), slots)
    out.mkdir(parents=True, exist_ok=True)
    for index, group in enumerate(groups, 1):
        # sort_keys : le contenu (donc la clé de cache) ne dépend pas de l'ordre des clés.
        (out / f"slot-{index}.json").write_text(json.dumps(group, sort_keys=True), encoding="utf-8")


def register_apps(bench, names):
    for path in (bench / "apps" / "apps.txt", bench / "sites" / "apps.txt"):
        current = path.read_text(encoding="utf-8").split() if path.exists() else []
        current += [name for name in names if name not in current]
        path.write_text("\n".join(current) + "\n", encoding="utf-8")


def link_public_node_modules(bench, name):
    """Les bundles vite/esbuild d'une app résolvent `public/node_modules` : on le
    relie au node_modules de l'app (équivalent de l'ancienne boucle shell)."""
    app_dir = bench / "apps" / name
    if not (app_dir / "node_modules").is_dir():
        return
    for module_dir in sorted(p for p in app_dir.iterdir() if (p / "public").is_dir()):
        link = module_dir / "public" / "node_modules"
        if link.exists():
            continue
        if link.is_symlink():
            link.unlink()
        link.symlink_to("../../node_modules")


def build_app(bench, name):
    # `--app` : esbuild, commande de build et traductions de cette app seulement ;
    # assets.json est fusionné avec le résultat des builds précédents.
    # Pas de `--hard-link` ici : chaque `bench build --hard-link` supprime puis
    # recopie sites/assets/<app> depuis <app>/public, ce qui effacerait le dist/
    # des apps déjà construites. En liens symboliques, dist/ est écrit dans
    # apps/<app>/<app>/public et survit aux builds suivants ; la copie réelle
    # est faite une seule fois à la fin (copy_assets).
    link_public_node_modules(bench, name)
    subprocess.run(["bench", "build", "--app", name, "--production"], cwd=bench, check=True)


def copy_assets(bench):
    """Remplace les liens sites/assets/<app> par des copies : l'image doit
    embarquer ses assets (image-assets est copié hors du bench, les liens
    seraient cassés). Équivalent de l'ancien `bench build --hard-link`."""
    # setup() initialise les globales (assets_path) dont make_asset_dirs dépend.
    code = (
        "import frappe; from frappe.build import make_asset_dirs, setup; "
        "frappe.init(''); setup(); make_asset_dirs(hard_link=True)"
    )
    subprocess.run([str(bench / "env" / "bin" / "python"), "-c", code], cwd=bench / "sites", check=True)


def build_base(bench):
    subprocess.run(["bench", "setup", "requirements", "frappe"], cwd=bench, check=True)
    build_app(bench, "frappe")


def add_apps(project, bench, entries, development=False, revision=None):
    for app in entries:
        install_entry(project, bench, app, development, revision)
        register_apps(bench, [app["name"]])
        subprocess.run(["bench", "setup", "requirements", app["name"]], cwd=bench, check=True)
        build_app(bench, app["name"])


def add_slot(bench, slot):
    entries = json.loads(Path(slot).read_text(encoding="utf-8"))
    for app in entries:
        validate_remote(app)
    add_apps(None, bench, entries)


def add_local(project, bench, revision=None):
    entries = load_manifest(project / "apps.json")
    if "path" not in entries[-1]:
        return
    if package_name(project) != entries[-1]["name"]:
        raise ValueError("Local package identity differs from apps.json")
    add_apps(project, bench, entries[-1:], revision=revision)


def install_on_site(project, bench, site):
    expected = ["frappe", *(app["name"] for app in load_manifest(project / "apps.json"))]
    installed = json.loads(run("bench", "--site", site, "list-apps", "--format", "json", cwd=bench))[site]
    for name in expected:
        if name not in installed:
            subprocess.run(["bench", "--site", site, "install-app", name], cwd=bench, check=True)
    installed = json.loads(run("bench", "--site", site, "list-apps", "--format", "json", cwd=bench))[site]
    if set(expected) - set(installed):
        raise ValueError("Site installation incomplete")


def source_revision(project):
    manifest = project / "source.json"
    if manifest.exists():
        return json.loads(manifest.read_text(encoding="utf-8")).get("revision")
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path)
    parser.add_argument("--bench", type=Path)
    parser.add_argument("--development", action="store_true")
    parser.add_argument("--site")
    parser.add_argument("--split-to", type=Path, help="write one slot-N.json per app under this directory")
    parser.add_argument("--base", action="store_true", help="install and build frappe alone")
    parser.add_argument("--slot", type=Path, help="install and build the apps listed in this slot file")
    parser.add_argument("--local", action="store_true", help="install and build the local app, if any")
    parser.add_argument("--copy-assets", action="store_true", help="turn sites/assets links into real copies")
    args = parser.parse_args()
    if args.split_to:
        write_slots(args.project, args.split_to)
    elif args.base:
        build_base(args.bench)
    elif args.slot:
        add_slot(args.bench, args.slot)
    elif args.copy_assets:
        copy_assets(args.bench)
    elif args.local:
        add_local(args.project, args.bench, source_revision(args.project))
    elif args.site:
        install_on_site(args.project, args.bench, args.site)
    else:
        install_sources(args.project, args.bench, args.development, source_revision(args.project))


if __name__ == "__main__":
    main()
