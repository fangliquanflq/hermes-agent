"""Process-completion routing across live TUI/Desktop sessions."""

from __future__ import annotations

import queue
import threading

from tools.process_registry import process_registry
from tui_gateway import server


class _StopAfterOnePoll:
    def __init__(self) -> None:
        self._checks = 0

    def is_set(self) -> bool:
        self._checks += 1
        return self._checks > 1


def _session(key: str) -> dict:
    return {
        "session_key": key,
        "history_lock": threading.Lock(),
        "running": False,
    }


def test_any_live_poller_routes_completion_directly_to_its_owner(monkeypatch):
    """Completion latency must not depend on the owning poller winning a queue race."""
    owner = _session("owner-key")
    foreign = _session("foreign-key")
    delivered: list[tuple[str, str]] = []
    emitted: list[tuple] = []
    completion_queue: queue.Queue = queue.Queue()
    completion_queue.put({
        "type": "completion",
        "session_id": "proc_remote",
        "session_key": "owner-key",
        "command": "sleep 25; echo DONE",
        "exit_code": 0,
        "output": "DONE",
    })

    monkeypatch.setattr(process_registry, "completion_queue", completion_queue)
    monkeypatch.setattr(server, "_get_db", lambda: None)
    monkeypatch.setattr(server, "_emit", lambda *args: emitted.append(args))

    def _deliver(_rid, sid, session, text, **_kwargs):
        delivered.append((sid, text))
        session["running"] = False

    monkeypatch.setattr(server, "_run_prompt_submit", _deliver)
    server._sessions.update({"owner-sid": owner, "foreign-sid": foreign})
    process_registry._completion_consumed.discard("proc_remote")

    try:
        server._notification_poller_loop(
            _StopAfterOnePoll(), "foreign-sid", foreign
        )

        assert [sid for sid, _text in delivered] == ["owner-sid"]
        assert "proc_remote completed normally" in delivered[0][1]
        assert [args[1] for args in emitted if args[0] == "status.update"] == [
            "owner-sid"
        ]
        assert completion_queue.empty()
    finally:
        server._sessions.pop("owner-sid", None)
        server._sessions.pop("foreign-sid", None)
        process_registry._completion_consumed.discard("proc_remote")
