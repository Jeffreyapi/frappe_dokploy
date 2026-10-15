"""Le socle ne doit plus exiger APP_VERSION sous un fallback imbriqué.

Piège compose v2.32 (vécu 13/10 production-run) : `${A:-${B:?msg}}` évalue le
fallback interne même quand `A` est défini — un `:?` sous un fallback tue le
deploy (`required variable APP_VERSION`). Default souple obligatoire.
"""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def _frappe_base_image() -> str:
    doc = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
    return doc["x-frappe-base"]["image"]


def test_image_socle_default_souple_app_version():
    image = _frappe_base_image()
    assert "${APP_VERSION:-latest}" in image
    assert ":?APP_VERSION" not in image


def test_fallback_image_reference_et_registry_prefix_intacts():
    image = _frappe_base_image()
    assert "${IMAGE_REGISTRY:+${IMAGE_REGISTRY}/}" in image
    assert (
        "${IMAGE_REFERENCE:-${IMAGE_NAME:-ghcr.io/jeffreyapi/frappe}:"
        in image
    )