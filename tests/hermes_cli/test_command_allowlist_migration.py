"""Contracts for legacy stringified command_allowlist recovery."""

from unittest.mock import patch

import yaml

from hermes_cli import config as config_mod
from tools import approval as approval_mod


def _write_legacy_config(tmp_path, value):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "_config_version": config_mod.DEFAULT_CONFIG["_config_version"] - 1,
                "command_allowlist": value,
            }
        ),
        encoding="utf-8",
    )
    return config_path


def test_stringified_allowlist_fails_closed_then_migrates(tmp_path):
    expected = ["script execution via -e/-c flag", "git status"]
    config_path = _write_legacy_config(tmp_path, yaml.safe_dump(expected, default_flow_style=True).strip())

    with patch.dict("os.environ", {"HERMES_HOME": str(tmp_path)}):
        config_mod._LOAD_CONFIG_CACHE.clear()
        approval_mod._permanent_approved.clear()

        assert approval_mod.load_permanent_allowlist() == set()
        assert any(
            issue.severity == "error" and "command_allowlist" in issue.message
            for issue in config_mod.validate_config_structure(config_mod.read_raw_config())
        )

        results = config_mod.migrate_config(interactive=False, quiet=True)
        migrated = yaml.safe_load(config_path.read_text(encoding="utf-8"))

        config_mod._LOAD_CONFIG_CACHE.clear()
        approval_mod._permanent_approved.clear()
        assert approval_mod.load_permanent_allowlist() == set(expected)

    config_mod._LOAD_CONFIG_CACHE.clear()
    approval_mod._permanent_approved.clear()
    assert migrated["command_allowlist"] == expected
    assert any("command_allowlist" in warning for warning in results["warnings"])


def test_migration_drops_string_that_is_not_a_string_list(tmp_path):
    config_path = _write_legacy_config(tmp_path, "git *")

    with patch.dict("os.environ", {"HERMES_HOME": str(tmp_path)}):
        config_mod._LOAD_CONFIG_CACHE.clear()
        results = config_mod.migrate_config(interactive=False, quiet=True)
        migrated = yaml.safe_load(config_path.read_text(encoding="utf-8"))

    config_mod._LOAD_CONFIG_CACHE.clear()
    assert migrated["command_allowlist"] == []
    assert any("ignored" in warning and "command_allowlist" in warning for warning in results["warnings"])
