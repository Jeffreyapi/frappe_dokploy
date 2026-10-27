"""`toolchains.json` : images de build et d'exécution par version majeure de Frappe.

Tant que le consommateur (Quai) ne lit pas ce fichier, la ligne `16` doit rester identique
aux `ARG` par défaut des Dockerfiles : il n'y a ainsi qu'une seule vérité.
"""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TABLE = json.loads((ROOT / "toolchains.json").read_text())
FIELDS = {"status", "build_image", "base_image", "python", "node", "validated_with"}
BUILD = re.compile(r"ghcr\.io/frappe/build@sha256:[0-9a-f]{64}")
BASE = re.compile(r"ghcr\.io/frappe/base@sha256:[0-9a-f]{64}")


def test_the_table_is_a_versioned_map_of_frappe_majors():
    assert TABLE["schema"] == 1
    assert set(TABLE) == {"schema", "toolchains"}
    assert TABLE["toolchains"], "au moins une version majeure"
    for major, entry in TABLE["toolchains"].items():
        assert major.isdigit(), major
        assert set(entry) == FIELDS, major
        assert entry["status"] in {"todo", "candidate", "ready"}, major


def test_images_are_pinned_by_digest_and_a_usable_toolchain_is_complete():
    for major, entry in TABLE["toolchains"].items():
        for field, pattern in (("build_image", BUILD), ("base_image", BASE)):
            value = entry[field]
            if entry["status"] in {"candidate", "ready"}:
                assert value is not None, f"{major}.{field} requis pour un toolchain utilisable"
            if value is not None:
                assert pattern.fullmatch(value), f"{major}.{field} doit être épinglé par digest"
        if entry["status"] == "ready":
            assert entry["validated_with"], f"{major}: indiquer le tag de Frappe réellement construit"


def test_only_a_ready_toolchain_claims_a_validation():
    for major, entry in TABLE["toolchains"].items():
        if entry["status"] != "ready":
            assert entry["validated_with"] is None, major


def _default(dockerfile, name):
    text = (ROOT / dockerfile).read_text()
    match = re.search(rf"^ARG {name}=(\S+)$", text, re.MULTILINE)
    assert match, f"{dockerfile}: ARG {name} introuvable"
    return match.group(1)


def test_version_16_matches_the_dockerfile_defaults():
    current = TABLE["toolchains"]["16"]
    for dockerfile in ("Dockerfile", "Dockerfile.layer"):
        assert _default(dockerfile, "BUILD_IMAGE") == current["build_image"], dockerfile
    for dockerfile in ("Dockerfile", "Dockerfile.runtime"):
        assert _default(dockerfile, "BASE_IMAGE") == current["base_image"], dockerfile
