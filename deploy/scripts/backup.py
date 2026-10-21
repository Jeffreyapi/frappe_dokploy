"""Versioned backup sets. Upload the manifest last; verify all bytes before restore."""

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

SET_ID = re.compile(r"\d{8}T\d{6}-[0-9a-f]{32}")
# Un ensemble sans manifest est un backup interrompu ; en dessous de cet âge il peut encore
# être en cours d'écriture par une autre exécution.
INCOMPLETE_MAX_AGE = 24 * 3600
LOCAL_KEEP_WHEN_UPLOADED = 0
LOCAL_KEEP_WHEN_LOCAL_ONLY = 3

ROLES = {"database": "*-database.sql.gz", "public": "*-files.tar",
         "private": "*-private-files.tar", "config": "*site_config_backup.json"}


def identity(value):
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._-]*", value) or ".." in value:
        raise ValueError("Invalid backup identity")
    return value


def checksum(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def command(*args, cwd=None):
    subprocess.run(args, cwd=cwd, check=True, stdout=sys.stderr)


def make_manifest(directory, site, deployment):
    files = {}
    for role, pattern in ROLES.items():
        matches = [p for p in directory.glob(pattern) if p.is_file() and not p.is_symlink()]
        if role == "public":
            matches = [p for p in matches if not p.name.endswith("-private-files.tar")]
        if len(matches) != 1 or matches[0].stat().st_size == 0:
            raise ValueError(f"Backup requires exactly one nonempty {role} file")
        path = matches[0]
        files[role] = {"name": path.name, "size": path.stat().st_size, "sha256": checksum(path)}
    config = json.loads((directory / files["config"]["name"]).read_text())
    if not config.get("encryption_key"):
        raise ValueError("Backup configuration has no encryption_key")
    manifest = {"schema": 1, "site": identity(site), "deployment": identity(deployment),
                "id": identity(directory.name), "files": files}
    (directory / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def validate_manifest(manifest, site, deployment):
    if manifest.get("schema") != 1 or manifest.get("site") != site or manifest.get("deployment") != deployment:
        raise ValueError("Backup tenant/environment identity mismatch")
    identity(manifest["id"])
    if set(manifest.get("files", {})) != set(ROLES):
        raise ValueError("Incomplete backup manifest")
    names = set()
    for item in manifest["files"].values():
        name = identity(item["name"])
        if name in names or not re.fullmatch(r"[a-f0-9]{64}", item["sha256"]) or item["size"] <= 0:
            raise ValueError("Invalid backup file metadata")
        names.add(name)


def verify(directory, site, deployment):
    manifest = json.loads((directory / "manifest.json").read_text())
    validate_manifest(manifest, site, deployment)
    for item in manifest["files"].values():
        path = directory / item["name"]
        if path.is_symlink() or not path.is_file() or path.stat().st_size != item["size"] or checksum(path) != item["sha256"]:
            raise ValueError(f"Missing or corrupt backup file: {item['name']}")
    return manifest


def s3_command():
    result = ["s5cmd"]
    if os.environ.get("S3_ENDPOINT_URL"):
        result += ["--endpoint-url", os.environ["S3_ENDPOINT_URL"]]
    # An IAM role is also supported when static credentials are omitted.
    for source, target in (("S3_BACKUP_ACCESS_KEY", "AWS_ACCESS_KEY_ID"),
                           ("S3_BACKUP_SECRET_KEY", "AWS_SECRET_ACCESS_KEY"),
                           ("S3_BACKUP_REGION", "AWS_REGION")):
        if os.environ.get(source):
            os.environ[target] = os.environ[source]
    return result


def s3_root(site, deployment):
    bucket = os.environ.get("S3_BACKUP_BUCKET", "")
    if not re.fullmatch(r"[a-z0-9][a-z0-9.-]+", bucket):
        raise ValueError("S3_BACKUP_BUCKET required")
    return f"s3://{bucket}/{identity(deployment)}/{identity(site)}/"


def upload(directory, site, deployment):
    manifest = verify(directory, site, deployment)
    prefix = s3_root(site, deployment) + manifest["id"] + "/"
    for item in manifest["files"].values():
        command(*s3_command(), "cp", str(directory / item["name"]), prefix)
    # Discovery only sees complete sets. A failed upload has no commit marker.
    command(*s3_command(), "cp", str(directory / "manifest.json"), prefix)


def sets_root(bench, site):
    # Hors de `private/backups/` : `bench backup` y supprime (`os.remove`) tout ce qui est ancien,
    # y compris un dossier `sets`, et échoue alors en IsADirectoryError.
    return bench / "sites" / identity(site) / "private" / "backup-sets"


def adopt_legacy_sets(bench, site):
    """Vide l'ancien `private/backups/sets` : sur un volume existant il fait échouer `bench backup`."""
    legacy = bench / "sites" / identity(site) / "private" / "backups" / "sets"
    if legacy.is_symlink() or not legacy.is_dir():
        return
    root = sets_root(bench, site)
    root.mkdir(parents=True, mode=0o700, exist_ok=True)
    for child in legacy.iterdir():
        target = root / child.name
        if SET_ID.fullmatch(child.name) and child.is_dir() and not child.is_symlink() and not target.exists():
            child.rename(target)
    # Ce dossier n'a jamais été créé que par ce script : ce qui reste n'est pas un ensemble valide.
    shutil.rmtree(legacy)


def prune_local_sets(root, keep, now=None):
    """Garde les `keep` ensembles complets les plus récents et supprime les ensembles
    interrompus de plus de 24 h. Ne touche qu'aux dossiers nommés `<horodatage>-<uuid>`."""
    now = time.time() if now is None else now
    candidates = sorted(p for p in root.iterdir() if SET_ID.fullmatch(p.name) and p.is_dir() and not p.is_symlink())
    complete = [p for p in candidates if (p / "manifest.json").is_file()]
    for path in candidates:
        if path not in complete and now - path.stat().st_mtime > INCOMPLETE_MAX_AGE:
            shutil.rmtree(path)
    for path in complete[: max(len(complete) - keep, 0)]:
        shutil.rmtree(path)


def local_keep(uploaded):
    default = LOCAL_KEEP_WHEN_UPLOADED if uploaded else LOCAL_KEEP_WHEN_LOCAL_ONLY
    value = os.environ.get("BACKUP_LOCAL_KEEP") or str(default)
    if not value.isdigit():
        raise ValueError("BACKUP_LOCAL_KEEP must be a non-negative integer")
    return int(value)


def create(bench, site, deployment):
    adopt_legacy_sets(bench, site)
    backup_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex
    directory = sets_root(bench, site) / backup_id
    directory.mkdir(parents=True, mode=0o700)
    command("bench", "--site", site, "backup", "--with-files", "--backup-path", str(directory), cwd=bench)
    make_manifest(directory, site, deployment)
    uploaded = os.environ.get("S3_BACKUP_ENABLED", "0").lower() in ("1", "true")
    if uploaded:
        upload(directory, site, deployment)
    else:
        print("S3 disabled; verified backup is local only", file=sys.stderr)
    # Après l'envoi vérifié, la copie S3 fait foi ; sans S3, la copie locale est la seule.
    prune_local_sets(sets_root(bench, site), local_keep(uploaded))
    return directory


def download(directory, site, deployment, backup_id=None):
    root = s3_root(site, deployment)
    if not backup_id:
        listing = subprocess.check_output([*s3_command(), "ls", root + "*/manifest.json"], text=True)
        candidates = [line.split()[-1].rstrip("/").split("/")[-2]
                      for line in listing.splitlines() if line.strip().endswith("/manifest.json")]
        if not candidates:
            raise ValueError("No complete backup found")
        backup_id = max(identity(value) for value in candidates)
    prefix = root + identity(backup_id) + "/"
    command(*s3_command(), "cp", prefix + "manifest.json", str(directory / "manifest.json"))
    manifest = json.loads((directory / "manifest.json").read_text())
    validate_manifest(manifest, site, deployment)
    if manifest["id"] != backup_id:
        raise ValueError("Backup id differs from its storage prefix")
    for item in manifest["files"].values():
        command(*s3_command(), "cp", prefix + item["name"], str(directory / item["name"]))
    verify(directory, site, deployment)


def restore(bench, directory, site, deployment):
    manifest = verify(directory, site, deployment)
    files = {role: directory / item["name"] for role, item in manifest["files"].items()}
    key = json.loads(files["config"].read_text()).get("encryption_key")
    if not key:
        raise ValueError("Cannot restore encrypted values without their encryption key")
    command("bench", "--site", site, "--force", "restore", str(files["database"]),
            "--with-public-files", str(files["public"]), "--with-private-files", str(files["private"]),
            "--db-root-username", "root", "--db-root-password", os.environ["DB_ROOT_PASSWORD"], cwd=bench)
    config_path = bench / "sites" / site / "site_config.json"
    config = json.loads(config_path.read_text())
    # Restore only the key, never the source environment's DB connection/credentials.
    config.update(encryption_key=key, maintenance_mode=1, pause_scheduler=1)
    with tempfile.NamedTemporaryFile(mode="w", dir=config_path.parent, delete=False) as stream:
        json.dump(config, stream, indent=2)
        temporary = Path(stream.name)
    temporary.chmod(0o600)
    temporary.replace(config_path)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("create", "restore", "verify"))
    parser.add_argument("--directory", type=Path)
    args = parser.parse_args()
    bench = Path.cwd().resolve()
    site = identity(os.environ["SITE_NAME"])
    deployment = identity(os.environ["DEPLOYMENT_ID"])
    if args.action == "create":
        print(create(bench, site, deployment))
    elif args.action == "verify":
        verify(args.directory, site, deployment)
    elif args.directory:
        restore(bench, args.directory.resolve(), site, deployment)
    else:
        with tempfile.TemporaryDirectory(prefix="frappe-restore-") as temporary:
            directory = Path(temporary)
            download(directory, site, deployment, os.environ.get("BACKUP_ID"))
            restore(bench, directory, site, deployment)


if __name__ == "__main__":
    main()
