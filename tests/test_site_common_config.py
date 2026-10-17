"""`bench set-config -g` échoue si sites/common_site_config.json n'existe pas (volume ancien)."""

from pathlib import Path

SITE_SH = Path(__file__).resolve().parents[1] / "deploy/scripts/site.sh"


def test_common_site_config_is_created_before_the_first_global_set_config():
    text = SITE_SH.read_text()
    guard = text.index("[[ -f sites/common_site_config.json ]] || printf '{}\\n' > sites/common_site_config.json")
    assert guard < text.index("bench set-config -g db_host")
