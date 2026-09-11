from types import SimpleNamespace
from unittest.mock import patch

import pytest

from hermes_cli.auth import (
    AuthError,
    CODEX_RATE_LIMITED_CODE,
    should_try_fallback_on_auth_error,
)


def test_auth_fallback_policy_rejects_configuration_errors_only():
    for code in ("invalid_provider", "missing_api_key", "no_provider_configured"):
        assert should_try_fallback_on_auth_error(AuthError("bad config", code=code)) is False

    assert should_try_fallback_on_auth_error(
        AuthError("quota", code=CODEX_RATE_LIMITED_CODE)
    ) is True
    assert should_try_fallback_on_auth_error(AuthError("unknown")) is True


def test_missing_api_key_never_resolves_fallback_on_any_runtime_surface(monkeypatch):
    missing = AuthError(
        "No usable credentials found for provider 'deepseek'.",
        provider="deepseek",
        code="missing_api_key",
    )
    fallback = [{"provider": "gemini", "model": "gemini-2.5-flash"}]
    resolve_calls = []

    def fail_primary(**kwargs):
        resolve_calls.append(kwargs)
        raise missing

    from hermes_cli.cli_agent_setup_mixin import CLIAgentSetupMixin

    cli = SimpleNamespace(
        _fallback_model=fallback,
        requested_provider="deepseek",
        model="deepseek-chat",
    )
    assert CLIAgentSetupMixin._resolve_fallback_runtime(cli, missing) is None

    import cron.scheduler as scheduler

    cron_config = SimpleNamespace(
        model="deepseek-chat",
        cron_default_provider="deepseek",
        model_cfg={"provider": "deepseek"},
        cfg={"fallback_providers": fallback},
    )
    with patch("hermes_cli.runtime_provider.resolve_runtime_provider", side_effect=fail_primary):
        with pytest.raises(RuntimeError, match="No usable credentials"):
            scheduler._resolve_job_runtime({}, "job-id", cron_config)
    assert len(resolve_calls) == 1

    import gateway.run as gateway_run

    resolve_calls.clear()
    monkeypatch.setattr(
        gateway_run,
        "_try_resolve_fallback_provider",
        lambda: pytest.fail("gateway attempted fallback"),
    )
    with patch("hermes_cli.runtime_provider.resolve_runtime_provider", side_effect=fail_primary):
        with pytest.raises(RuntimeError, match="No usable credentials"):
            gateway_run._resolve_runtime_agent_kwargs()
    assert len(resolve_calls) == 1

    import tui_gateway.server as tui_server

    resolve_calls.clear()
    monkeypatch.setattr(
        tui_server,
        "_load_fallback_model",
        lambda: pytest.fail("TUI attempted fallback"),
    )
    with patch("hermes_cli.runtime_provider.resolve_runtime_provider", side_effect=fail_primary):
        with pytest.raises(AuthError, match="No usable credentials"):
            tui_server._resolve_runtime_with_fallback({"requested": "deepseek"})
    assert len(resolve_calls) == 1