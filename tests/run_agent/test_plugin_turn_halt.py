import time


def _agent():
    from run_agent import AIAgent

    return AIAgent(
        api_key="test-key",
        base_url="https://openrouter.ai/api/v1",
        provider="openrouter",
        model="test/model",
        quiet_mode=True,
        skip_context_files=True,
        skip_memory=True,
    )


def _wait_for(predicate, timeout=1.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    assert predicate()


def test_pre_llm_hook_can_halt_turn_before_provider_call(monkeypatch):
    def invoke_hook(name, **_kwargs):
        if name == "pre_llm_call":
            return [{"action": "halt_turn", "response": "Stopped by policy."}]
        return []

    monkeypatch.setattr("hermes_cli.plugins.invoke_hook", invoke_hook)
    agent = _agent()

    result = agent.run_conversation("continue indefinitely", task_id="task-1")

    assert result["final_response"] == "Stopped by policy."
    assert result["turn_exit_reason"] == "plugin_halt_turn"
    assert result["api_calls"] == 0
    assert result["completed"] is True
    assert result["interrupted"] is False
    assert result["failed"] is False
    assert result["messages"][-1] == {"role": "assistant", "content": "Stopped by policy."}


def test_stream_hook_halt_is_adopted_without_blocking_token_callback(monkeypatch):
    from agent.plugin_stream_hooks import shutdown_plugin_stream_hook_dispatcher
    from agent.plugin_turn_control import close_plugin_turn, open_plugin_turn

    shutdown_plugin_stream_hook_dispatcher()
    monkeypatch.setattr("hermes_cli.config.cfg_get", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(
        "hermes_cli.plugins.iter_hook_callbacks",
        lambda name: (
            (lambda **_kwargs: {"action": "halt_turn", "response": "Reasoning budget reached."}),
        ) if name == "on_stream_delta" else (),
    )

    agent = _agent()
    agent._current_turn_id = "turn-stream-halt"
    agent._plugin_turn_halt_response = None
    agent._interrupt_requested = False
    open_plugin_turn(agent._current_turn_id)
    try:
        started = time.monotonic()
        agent._fire_reasoning_delta("first chunk")
        assert time.monotonic() - started < 0.05

        _wait_for(agent._poll_plugin_turn_halt)

        assert agent._interrupt_requested is True
        assert agent._plugin_turn_halt_response == "Reasoning budget reached."
    finally:
        close_plugin_turn(agent._current_turn_id)
        shutdown_plugin_stream_hook_dispatcher()


def test_halt_registry_accepts_only_first_valid_directive():
    from agent.plugin_turn_control import (
        close_plugin_turn,
        open_plugin_turn,
        record_plugin_turn_halt,
        take_plugin_turn_halt,
    )

    turn_id = "turn-first-wins"
    open_plugin_turn(turn_id)
    try:
        assert record_plugin_turn_halt(turn_id, {"action": "halt_turn", "response": ""}) is False
        assert record_plugin_turn_halt(turn_id, {"action": "halt_turn", "response": "first"}) is True
        assert record_plugin_turn_halt(turn_id, {"action": "halt_turn", "response": "second"}) is False
        assert take_plugin_turn_halt(turn_id).response == "first"
    finally:
        close_plugin_turn(turn_id)
