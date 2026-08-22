"""Regression tests for #92250: lazy CLI model switches rebind pools."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from hermes_cli.model_switch import ModelSwitchResult


class _StubCLI:
    model = "old-model"
    provider = "openrouter"
    requested_provider = "openrouter"
    api_key = "sk-old"
    _explicit_api_key = "sk-old"
    base_url = "https://openrouter.ai/api/v1"
    _explicit_base_url = "https://openrouter.ai/api/v1"
    api_mode = "chat_completions"
    acp_command = None
    acp_args = []
    service_tier = None
    agent = None
    conversation_history = []
    _pending_model_switch_note = None
    _pending_one_turn_model_restore = None

    def __init__(self, pool):
        self._credential_pool = pool

    def _confirm_expensive_model_switch(self, result):
        return True

    def _rebind_model_switch_credential_pool(self, result):
        import cli as cli_mod

        return cli_mod.HermesCLI._rebind_model_switch_credential_pool(self, result)


def _result() -> ModelSwitchResult:
    return ModelSwitchResult(
        success=True,
        new_model="glm-5.2",
        target_provider="ollama-cloud",
        provider_changed=True,
        api_key="sk-pool-primary",
        base_url="https://ollama.com/v1",
        api_mode="chat_completions",
        warning_message="",
        provider_label="Ollama Cloud",
        resolved_via_alias=False,
        capabilities=None,
        model_info=None,
        is_global=False,
    )


def _patch_switch_dependencies(monkeypatch, target_pool):
    import cli as cli_mod

    monkeypatch.setattr(cli_mod, "_cprint", lambda *args, **kwargs: None)
    monkeypatch.setattr(cli_mod, "save_config_value", lambda *args, **kwargs: None)
    monkeypatch.setattr("agent.credential_pool.load_pool", lambda provider: target_pool)
    monkeypatch.setattr(
        "hermes_cli.model_switch.resolve_display_context_length",
        lambda *args, **kwargs: None,
    )
    return cli_mod


@pytest.mark.parametrize("switch_path", ["picker", "typed"])
def test_pre_first_turn_provider_switch_rebinds_cli_pool(
    monkeypatch, switch_path,
):
    """The first turn must inherit the selected provider's rotation pool."""
    old_pool = SimpleNamespace(provider="openrouter")
    target_pool = SimpleNamespace(provider="ollama-cloud")
    cli = _StubCLI(old_pool)
    cli_mod = _patch_switch_dependencies(monkeypatch, target_pool)

    if switch_path == "picker":
        cli_mod.HermesCLI._apply_model_switch_result(cli, _result(), False)
    else:
        cli_mod.HermesCLI._confirm_and_apply_cli_model_switch(
            cli, _result(), False, False
        )

    assert cli.agent is None
    assert cli._credential_pool is target_pool
    assert cli._explicit_api_key is None
    assert cli._explicit_base_url is None
    route = cli_mod.HermesCLI._resolve_turn_agent_config(cli, "hello")
    assert route["runtime"]["credential_pool"] is target_pool


def test_model_runtime_snapshot_restores_cli_pool():
    """A one-turn switch restores the original provider's pool reference."""
    import cli as cli_mod

    old_pool = SimpleNamespace(provider="openrouter")
    cli = _StubCLI(old_pool)
    snapshot = cli_mod.HermesCLI._snapshot_model_runtime(cli)

    cli._credential_pool = SimpleNamespace(provider="ollama-cloud")
    cli_mod.HermesCLI._restore_model_runtime_snapshot(cli, snapshot)

    assert cli._credential_pool is old_pool


@pytest.mark.parametrize("switch_path", ["picker", "typed"])
def test_failed_in_place_switch_restores_cli_pool(monkeypatch, switch_path):
    """A failed agent rebuild must roll the CLI back to its original pool."""

    class _FailingAgent:
        _custom_providers = None
        _config_context_length = None

        def switch_model(self, **kwargs):
            raise RuntimeError("client rebuild failed")

    old_pool = SimpleNamespace(provider="openrouter")
    target_pool = SimpleNamespace(provider="ollama-cloud")
    cli = _StubCLI(old_pool)
    cli.agent = _FailingAgent()
    cli_mod = _patch_switch_dependencies(monkeypatch, target_pool)

    if switch_path == "picker":
        cli_mod.HermesCLI._apply_model_switch_result(cli, _result(), False)
    else:
        cli_mod.HermesCLI._confirm_and_apply_cli_model_switch(
            cli, _result(), False, False
        )

    assert cli.provider == "openrouter"
    assert cli._credential_pool is old_pool
