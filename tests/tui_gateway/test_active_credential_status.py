from __future__ import annotations

import threading
from types import SimpleNamespace
from unittest.mock import patch

import tui_gateway.server as server


def _agent():
    entries = [
        SimpleNamespace(id="personal", label="personal@example.com", access_token="secret-personal"),
        SimpleNamespace(id="work", label="work@example.com", access_token="secret-work"),
    ]
    return SimpleNamespace(
        _credential_pool=SimpleNamespace(entries=lambda: entries),
        _credential_pool_entry_id="personal",
        model="claude-test",
        provider="anthropic",
        reasoning_config=None,
        service_tier=None,
        session_id="session-key",
    )


def test_session_info_and_live_ticker_follow_credential_rotation():
    agent = _agent()
    info = server._session_info(agent)
    assert info["account_label"] == "personal@example.com"
    assert "secret-" not in str(info)

    rotated = threading.Event()
    emitted = []

    def capture(event, sid, payload):
        emitted.append((event, sid, payload))
        if event == "session.info" and payload.get("account_label") == "work@example.com":
            rotated.set()

    with patch.object(server, "_get_usage", return_value={}), \
            patch.object(server, "_emit", side_effect=capture):
        stop, thread = server._start_usage_ticker("sid", agent, interval=0.01)
        agent._credential_pool_entry_id = "work"
        assert rotated.wait(2.0)
        stop.set()
        thread.join(timeout=2.0)

    assert not thread.is_alive()
    assert not any(event == "session.usage" for event, _, _ in emitted)