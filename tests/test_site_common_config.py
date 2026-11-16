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


def test_assets_volume_is_chowned_by_a_root_init_service_before_site_manager():
    compose = (SITE_SH.parents[2] / "docker-compose.yml").read_text()
    init = compose[compose.index("  volume-init:") : compose.index("  site-manager:")]
    assert "user: root" in init and "chown" in init and "sites/assets" in init
    manager = compose[compose.index("  site-manager:") :]
    assert "volume-init:\n        condition: service_completed_successfully" in manager[:400]


def _case(text, name):
    start = text.index(f"    {name})\n")
    return text[start : text.index("      ;;", start)]


def test_encryption_key_is_ensured_so_the_first_backup_can_succeed():
    text = SITE_SH.read_text()
    body = text[text.index("ensure_encryption_key() {") : text.index("\n}\n", text.index("ensure_encryption_key() {"))]
    assert "frappe.utils.password.get_encryption_key" in body
    # la valeur de retour EST la clé : jamais dans les logs
    assert ">/dev/null" in body
    assert "ensure_encryption_key" in _case(text, "create")
    assert "ensure_encryption_key" in _case(text, "update")


def test_the_key_is_not_generated_before_a_restore_which_brings_its_own():
    restore = _case(SITE_SH.read_text(), "restore")
    assert "ensure_encryption_key" not in restore  # la clé vient de la sauvegarde (backup.py restore)


def test_the_key_is_created_after_the_site_exists_and_before_maintenance_or_apps():
    create = _case(SITE_SH.read_text(), "create")
    assert create.index("ensure_site") < create.index("ensure_encryption_key") < create.index("install_apps")
    update = _case(SITE_SH.read_text(), "update")
    assert update.index("require_site_exists") < update.index("ensure_encryption_key") < update.index("install_apps")
