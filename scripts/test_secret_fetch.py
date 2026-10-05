"""Headless checks for fetching private remote apps via the BuildKit secret.

No network, no Docker: a fake `git` (prepended to the PATH) records the answer
returned by the credential helper. Run with: python scripts/test_secret_fetch.py
"""
import base64
import os
import re
import stat
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import app_sources  # import tardif : le sys.path ci-dessus est nécessaire

SHA = "a" * 40
ENTRY = {
    "name": "hermes_control",
    "url": "https://github.com/example/hermes_control",
    "revision": SHA,
}
# Format d'un PAT GitHub : la valeur du secret n'est JAMAIS un contenu libre.
TOKEN = "ghp_0123456789abcdef0123456789abcdef01234567"
EXPECTED_HEADER = "Basic " + base64.b64encode(("x-access-token:" + TOKEN).encode("utf-8")).decode("ascii")

# Fake git : sur fetch, invoque GIT_ASKPASS comme git le ferait pour un prompt
# « Password for ... » et journalise la réponse ; rev-parse renvoie le SHA attendu.
FAKE_GIT = """#!/bin/sh
if [ "$1" = "fetch" ]; then
  answer=none
  code=0
  if [ -n "$GIT_ASKPASS" ]; then
    answer=$("$GIT_ASKPASS" "Password for 'https://x-access-token@github.com':")
    code=$?
  fi
  printf 'askpass_code=%s answer=%s terminal_prompt=%s\\n' \\
    "$code" "$answer" "$(printenv GIT_TERMINAL_PROMPT || echo unset)" >> "$FAKE_PROBE"
fi
case "$1" in
  rev-parse) printf '%s\\n' "$FAKE_EXPECTED_SHA" ;;
  init) mkdir -p "$2" && printf '[project]\\nname = "hermes_control"\\n' > "$2/pyproject.toml" ;;
esac
exit 0
"""

PROBE_LINE = re.compile(r"askpass_code=(\d+) answer=(.*) terminal_prompt=(\S+)")


def checkout(token_value: str | None, root: Path, apps_name: str) -> str:
    """Run checkout_remote once into a fresh apps/ dir and return the probe log."""
    apps_dir = root / apps_name
    apps_dir.mkdir()
    probe = root / f"probe-{apps_name}.log"
    os.environ["FAKE_PROBE"] = str(probe)
    os.environ["FAKE_EXPECTED_SHA"] = SHA
    for name in ("GIT_ASKPASS", "GIT_TERMINAL_PROMPT", "GIT_CREDENTIAL_HEADER"):
        os.environ.pop(name, None)
    if token_value is None:
        os.environ.pop("GITHUB_TOKEN", None)
    else:
        os.environ["GITHUB_TOKEN"] = token_value
    app_sources.checkout_remote(dict(ENTRY), apps_dir / ENTRY["name"])
    assert (apps_dir / ENTRY["name"]).exists(), "checkout_remote did not install the app"
    return probe.read_text(encoding="utf-8")


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="git-secret-") as temporary:
        root = Path(temporary)
        fake_bin = root / "bin"
        fake_bin.mkdir()
        fake_git = fake_bin / "git"
        fake_git.write_text(FAKE_GIT, encoding="utf-8")
        fake_git.chmod(fake_git.stat().st_mode | stat.S_IEXEC)
        os.environ["PATH"] = str(fake_bin) + os.pathsep + os.environ["PATH"]

        # 1. Secret présent (token brut) : le fetch demande le mot de passe au
        #    helper et reçoit le header Basic x-access-token — pas de prompt tty.
        probe = checkout(TOKEN, root, "apps-token")
        match = PROBE_LINE.search(probe)
        assert match, f"no fetch probe line: {probe!r}"
        assert match.group(1) == "0", "askpass invocation failed"
        assert match.group(2) == EXPECTED_HEADER, probe
        assert match.group(3) == "0", "GIT_TERMINAL_PROMPT must be disabled for the fetch"

        # 2. Secret absent : fetch anonyme strictement identique à l'ancien.
        probe = checkout(None, root, "apps-anonymous")
        match = PROBE_LINE.search(probe)
        assert match, f"no fetch probe line: {probe!r}"
        assert match.group(2) == "none", probe
        assert match.group(3) == "unset", probe

        # 3. Secret vide : traité comme absent (pas de helper monté pour rien).
        assert PROBE_LINE.search(checkout("", root, "apps-empty")).group(2) == "none"

        # 4. Déjà encodé « Basic <b64> » : transmis tel quel.
        probe = checkout(
            "Basic " + base64.b64encode(b"user:password").decode("ascii"),
            root,
            "apps-basic",
        )
        assert "answer=Basic dXNlcjpwYXNzd29yZA==" in probe, probe

        # 5. Câblage du Dockerfile : le montage secret ne vise QUE le RUN qui
        #    fetch les apps (syntaxe >= 1.10 pour l'option env=).
        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        directive = re.fullmatch(r"# syntax=docker/dockerfile:1\.(\d+)", dockerfile.splitlines()[0])
        assert directive and int(directive.group(1)) >= 10, "env= requires Dockerfile syntax 1.10"
        lines = dockerfile.splitlines()
        anchor = next(
            i for i, line in enumerate(lines)
            if "app_sources.py --project /opt/app-source --bench ." in line
        )
        start = anchor
        while not lines[start].startswith("RUN "):
            start -= 1
        end = start
        while lines[end].endswith("\\"):
            end += 1
        statement = "\n".join(lines[start : end + 1])
        assert "RUN --mount=type=secret,id=git_token,env=GITHUB_TOKEN" in statement, statement
        assert dockerfile.count("--mount=type=secret") == 1, "the secret mount must be unique"
        assert "ghp_" not in dockerfile, "no literal token in the Dockerfile"

    print("Git secret checks passed")


if __name__ == "__main__":
    main()