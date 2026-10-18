"""`bench set-config -g` échoue si sites/common_site_config.json n'existe pas (volume ancien)."""

from pathlib import Path

SITE_SH = Path(__file__).resolve().parents[1] / "deploy/scripts/site.sh"


def test_common_site_config_is_created_before_the_first_global_set_config():
    text = SITE_SH.read_text()
    guard = text.index("[[ -f sites/common_site_config.json ]] || printf '{}\\n' > sites/common_site_config.json")
    assert guard < text.index("bench set-config -g db_host")


def test_an_empty_app_list_means_frappe_only_not_a_failure():
    text = SITE_SH.read_text()
    assert 'die "No apps selected for installation"' not in text
    start = text.index("install_apps() {")
    body = text[start : text.index("\n}\n", start)]
    empty_branch = body.index('if [[ -z "$apps" ]]; then\n    log "No additional apps')
    assert "return 0" in body[empty_branch : empty_branch + 200]
    assert empty_branch < body.index("list-apps")


def test_apps_list_is_resynced_from_the_image_before_any_bench_command():
    text = SITE_SH.read_text()
    assert "cp /opt/apps.txt sites/apps.txt" in text
    main = text[text.index("main() {") :]
    assert main.index("sync_apps_list") < main.index("configure_common")
