from copy import deepcopy

from fastapi.testclient import TestClient


def test_bulk_factory_regression_requires_explicit_reset():
    from hermes_cli.config import DEFAULT_CONFIG, load_config, save_config
    from hermes_cli.web_server import _SESSION_HEADER_NAME, _SESSION_TOKEN, app

    changed = deepcopy(DEFAULT_CONFIG)
    changed["agent"]["gateway_timeout"] += 1
    changed["compression"]["enabled"] = not changed["compression"]["enabled"]
    changed["display"]["skin"] = "scope-drift-sentinel"
    changed["display"]["streaming"] = not changed["display"]["streaming"]
    changed["logging"]["level"] = "DEBUG"
    changed["memory"]["memory_enabled"] = not changed["memory"]["memory_enabled"]
    changed["security"]["redact_secrets"] = not changed["security"]["redact_secrets"]
    changed["terminal"]["backend"] = "docker"
    save_config(changed)

    client = TestClient(app)
    client.headers[_SESSION_HEADER_NAME] = _SESSION_TOKEN

    rejected = client.put("/api/config", json={"config": DEFAULT_CONFIG})

    assert rejected.status_code == 409
    assert load_config()["display"]["skin"] == "scope-drift-sentinel"

    accepted = client.put(
        "/api/config",
        json={"allow_default_reset": True, "config": DEFAULT_CONFIG},
    )

    assert accepted.status_code == 200
    assert load_config()["display"]["skin"] == DEFAULT_CONFIG["display"]["skin"]
