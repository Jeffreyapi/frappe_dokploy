"""Atomic, public Frappe configuration and historical-image compatibility checks."""

import importlib.util
import json
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("apply_config", ROOT / "deploy/scripts/apply_config.py")
apply = importlib.util.module_from_spec(spec)
spec.loader.exec_module(apply)

def test_config_removal_preserves_secrets_and_ownership_is_atomic(tmp_path):
    path = tmp_path / "site_config.json"
    path.write_text(json.dumps({"db_password": "retained", "encryption_key": "retained", "custom_key": 7}))
    path.chmod(0o640)
    assert apply.apply_config(path, "site", {"mute_emails": True}) == {
        "added": ["mute_emails"], "modified": [], "removed": []}
    assert apply.apply_config(path, "site", {})["removed"] == ["mute_emails"]
    config = json.loads(path.read_text())
    assert config["db_password"] == "retained" and config["encryption_key"] == "retained"
    assert config["custom_key"] == 7 and config[apply.OWNERSHIP_KEY] == []
    assert path.stat().st_mode & 0o777 == 0o640
    before = path.read_bytes()
    with patch.object(apply.os, "replace", side_effect=OSError("interrupted")), pytest.raises(OSError):
        apply.apply_config(path, "site", {"monitor": True})
    assert path.read_bytes() == before
    assert not list(tmp_path.glob(".quai-config-*"))


@pytest.mark.parametrize("scope,config", [
    ("site", {"db_password": "forbidden"}), ("site", {"developer_mode": 1}),
    ("site", {"rate_limit": {"limit": True, "window": 1}}),
    ("site", {"allow_cors": ["https://user:password@example.com"]}),
    ("site", {"host_name": "javascript:alert(1)"}), ("site", {"maintenance_mode": True}),
    ("common", {"scheduler_tick_interval": 0}), ("common", {"scheduler_tick_interval": 86401}),
    ("site", {"max_file_size": 2**53}), ("site", {"host_name": "https://example.com?secret=value"}),
    ("site", {"host_name": "https://@example.com"}), ("site", {"host_name": "https://exa\x00mple.com"}),
    ("site", {"allowed_referrers": ["example.com"] * 101}),
])
def test_config_double_validation(scope, config):
    with pytest.raises(ValueError):
        apply.validate(scope, config)


@pytest.mark.parametrize("environment", ["prod", " Production ", "PRD"])
def test_production_and_wildcard_guards(environment):
    with pytest.raises(ValueError, match="production"):
        apply.validate("site", {"developer_mode": True}, environment)
    with pytest.raises(ValueError):
        apply.validate("site", {"allow_cors": ["*"]})
    assert apply.validate("site", {"allow_cors": ["*"]}, cors_wildcard_confirmed=True)


def test_compose_preserves_historical_image_backend_command():
    # Older registry images have their Gunicorn CMD but no new wrapper script.
    compose = (ROOT / "docker-compose.yml").read_text()
    backend = compose.split("  backend:\n", 1)[1].split("  frontend:\n", 1)[0]
    assert "    command:" not in backend
    assert "    entrypoint:" not in backend


