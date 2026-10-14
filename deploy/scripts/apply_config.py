"""Validate Quai's public config contract again and update each file atomically."""

import argparse
import fcntl
import json
import os
import re
import stat
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

COMMON_KEYS = {"scheduler_tick_interval"}
BOOLEAN_KEYS = {
    "developer_mode", "server_script_enabled", "deny_multiple_sessions", "disable_scheduler",
    "mute_emails", "disable_async", "enable_frappe_logger", "logging", "monitor", "skip_setup_wizard",
}
SITE_KEYS = BOOLEAN_KEYS | {"host_name", "allow_cors", "allowed_referrers", "rate_limit", "max_file_size"}
OWNERSHIP_KEY = "_quai_managed_keys"


def positive_integer(value):
    return type(value) is int and 1 <= value <= 2**53 - 1


def web_url(value, origin=False):
    if not isinstance(value, str) or len(value) > 2048 or any(c.isspace() or ord(c) < 32 for c in value):
        return False
    try:
        parsed = urlsplit(value)
        _ = parsed.port  # Validate the port as well as its text representation.
        return (parsed.scheme in {"http", "https"} and bool(parsed.hostname)
                and parsed.username is None and parsed.password is None and not parsed.fragment and not parsed.query
                and (not origin or parsed.path in {"", "/"}))
    except ValueError:
        return False


def validate(scope, config, environment="dev", cors_wildcard_confirmed=False):
    if not isinstance(config, dict) or any(not isinstance(key, str) for key in config):
        raise ValueError("Configuration must be a JSON object")
    whitelist = COMMON_KEYS if scope == "common" else SITE_KEYS
    if scope not in {"common", "site"} or set(config) - whitelist:
        raise ValueError("Configuration contains unknown or forbidden keys")
    for key, value in config.items():
        valid = False
        if key in BOOLEAN_KEYS:
            valid = type(value) is bool
            if key == "developer_mode" and value is True and environment.strip().lower() in {"prod", "production", "prd"}:
                raise ValueError("developer_mode is forbidden in production")
        elif key == "scheduler_tick_interval":
            valid = positive_integer(value) and value <= 86400
        elif key == "max_file_size":
            valid = positive_integer(value)
        elif key == "host_name":
            valid = web_url(value)
        elif key == "allow_cors":
            valid = isinstance(value, list) and len(value) <= 100 and all(
                (item == "*" and cors_wildcard_confirmed) or web_url(item, origin=True) for item in value)
        elif key == "allowed_referrers":
            valid = isinstance(value, list) and len(value) <= 100 and all(isinstance(item, str) and 0 < len(item) <= 2048 for item in value)
        elif key == "rate_limit":
            valid = (isinstance(value, dict) and set(value) == {"limit", "window"}
                     and all(positive_integer(item) for item in value.values()))
        if not valid:
            raise ValueError(f"Invalid configuration value for {key}")
    return config


def apply_config(path, scope, config, environment="dev", cors_wildcard_confirmed=False):
    validate(scope, config, environment, cors_wildcard_confirmed)
    whitelist = COMMON_KEYS if scope == "common" else SITE_KEYS
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise ValueError("Refusing to replace a symlinked configuration")
    with path.with_name(path.name + ".quai.lock").open("a", encoding="utf-8") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        document = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        if not isinstance(document, dict):
            raise TypeError("Existing configuration must be an object")
        previous = document.get(OWNERSHIP_KEY, [])
        if not isinstance(previous, list) or any(not isinstance(key, str) or key not in whitelist for key in previous):
            raise ValueError("Invalid managed-key ownership metadata")
        changes = {"added": [], "modified": [], "removed": []}
        for key in previous:
            if key not in config and key in document:
                del document[key]
                changes["removed"].append(key)
        for key, value in config.items():
            if key not in document:
                changes["added"].append(key)
            elif document[key] != value:
                changes["modified"].append(key)
            document[key] = value
        # Ownership and values commit in the same replacement; a crash cannot orphan keys.
        document[OWNERSHIP_KEY] = sorted(config)
        mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o600
        descriptor, temporary = tempfile.mkstemp(prefix=".quai-config-", dir=path.parent)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                os.fchmod(stream.fileno(), mode)
                json.dump(document, stream, sort_keys=True, separators=(",", ":"))
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
            directory = os.open(path.parent, os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        return {key: sorted(values) for key, values in changes.items()}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--bench", type=Path, default=Path("/home/frappe/frappe-bench"))
    parser.add_argument("--scope", choices=("common", "site"), required=True)
    parser.add_argument("--site", default=os.environ.get("SITE_NAME"))
    args = parser.parse_args()
    variable = "FRAPPE_COMMON_CONFIG" if args.scope == "common" else "FRAPPE_SITE_CONFIG"
    raw = os.environ.get(variable, "") or "{}"
    if len(raw.encode("utf-8")) > 65536:
        parser.error("Configuration payload exceeds 64 KiB")
    config = json.loads(raw)
    if args.scope == "common":
        path = args.bench / "sites/common_site_config.json"
    else:
        if not args.site or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9.-]*", args.site) or ".." in args.site:
            parser.error("Invalid site name")
        path = args.bench / "sites" / args.site / "site_config.json"
        if not path.is_file():
            parser.error("Site configuration is missing")
    changes = apply_config(path, args.scope, config, os.environ.get("ENVIRONMENT", "dev"),
                           os.environ.get("FRAPPE_ALLOW_CORS_WILDCARD", "0") == "1")
    print(json.dumps({"event": "config.applied", "scope": args.scope, "keys": changes}, sort_keys=True))


if __name__ == "__main__":
    main()
