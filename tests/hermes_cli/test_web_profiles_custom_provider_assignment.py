"""Regression tests for cross-profile model assignment."""

import yaml


def test_write_profile_model_copies_missing_custom_provider(tmp_path, monkeypatch):
    from hermes_constants import get_hermes_home
    from hermes_cli.web_routers.profiles import _write_profile_model

    source_home = get_hermes_home()
    source_home.mkdir(parents=True, exist_ok=True)
    provider_entry = {
        "name": "scnet",
        "base_url": "https://api.scnet.example/v1",
        "model": "GLM-5.3-Flash",
        "discover_models": True,
        "models": {"GLM-5.3-Flash": {"context_length": 131072}},
        "key_env": "HERMES_CUSTOM_SCNET_API_KEY",
        "api_key": "${HERMES_CUSTOM_SCNET_API_KEY}",
    }
    (source_home / "config.yaml").write_text(
        yaml.safe_dump({"providers": {"scnet": provider_entry}}, sort_keys=False),
        encoding="utf-8",
    )
    monkeypatch.setenv("HERMES_CUSTOM_SCNET_API_KEY", "must-not-be-persisted")

    target_home = tmp_path / "profiles" / "procure_helper"
    target_home.mkdir(parents=True)
    (target_home / "config.yaml").write_text("{}\n", encoding="utf-8")

    _write_profile_model(target_home, "scnet", "GLM-5.3-Flash")

    persisted = yaml.safe_load((target_home / "config.yaml").read_text(encoding="utf-8"))
    assert persisted["model"]["provider"] == "scnet"
    assert persisted["model"]["default"] == "GLM-5.3-Flash"
    assert persisted["providers"]["scnet"] == provider_entry
    assert "must-not-be-persisted" not in (target_home / "config.yaml").read_text(encoding="utf-8")
