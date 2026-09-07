"""Regression coverage for CLI async-delegation completion ownership."""

import queue

from cli import HermesCLI


def test_cli_completion_drain_uses_visible_session_identity(monkeypatch):
    """A CLI window must not claim another window's restored completion."""
    cli = HermesCLI.__new__(HermesCLI)
    cli.session_id = "visible-session"
    cli._pending_input = queue.Queue()

    event = {
        "type": "async_delegation",
        "delegation_id": "deleg_visible",
        "session_key": "visible-session",
    }
    calls = []

    class FakeRegistry:
        def drain_notifications(self, *, session_key="", owns_event=None):
            calls.append((session_key, owns_event(event)))
            return [(event, "completion payload")]

    claimed = []
    completed = []

    monkeypatch.setattr(
        "tools.process_registry.process_registry",
        FakeRegistry(),
    )
    monkeypatch.setattr(
        "tools.async_delegation.claim_event_delivery",
        lambda evt, consumer: claimed.append((evt, consumer)) or "claim-token",
    )
    monkeypatch.setattr(
        "tools.async_delegation.complete_event_delivery",
        lambda evt, token: completed.append((evt, token)),
    )

    cli._drain_process_notifications("cli-idle")

    assert calls == [("visible-session", True)]
    assert cli._pending_input.get_nowait() == "completion payload"
    assert claimed == [(event, "cli-idle")]
    assert completed == [(event, "claim-token")]


def test_cli_completion_drain_batches_ready_process_completions(monkeypatch):
    cli = HermesCLI.__new__(HermesCLI)
    cli.session_id = "visible-session"
    cli._pending_input = queue.Queue()

    events = [
        {
            "type": "completion",
            "session_id": f"proc_{index}",
            "session_key": "visible-session",
        }
        for index in range(3)
    ]

    class FakeRegistry:
        consumed = set()

        def drain_notifications(self, *, session_key="", owns_event=None):
            assert session_key == "visible-session"
            assert all(owns_event(event) for event in events)
            return [(event, f"completion payload {index}") for index, event in enumerate(events)]

        def is_completion_consumed(self, session_id):
            return session_id in self.consumed

    completed = []
    monkeypatch.setattr("tools.process_registry.process_registry", FakeRegistry())
    monkeypatch.setattr(
        "tools.async_delegation.claim_event_delivery",
        lambda event, consumer: f"claim-{event['session_id']}",
    )
    monkeypatch.setattr(
        "tools.async_delegation.complete_event_delivery",
        lambda event, token: completed.append((event["session_id"], token)),
    )

    cli._drain_process_notifications("cli-idle")

    assert cli._pending_input.qsize() == 1
    FakeRegistry.consumed.add("proc_1")
    prompt, _is_voice, _is_seeded = cli._tui_unwrap_input(cli._pending_input.get_nowait())
    assert "completion payload 0" in prompt
    assert "completion payload 1" not in prompt
    assert "completion payload 2" in prompt
    assert completed == [
        (f"proc_{index}", f"claim-proc_{index}") for index in range(3)
    ]


def test_cli_completion_ownership_rejects_foreign_session():
    cli = HermesCLI.__new__(HermesCLI)
    cli.session_id = "visible-session"
    cli._session_db = None

    assert not cli._owns_process_notification(
        {"type": "async_delegation", "session_key": "foreign-session"}
    )


def test_cli_completion_ownership_accepts_compression_lineage():
    cli = HermesCLI.__new__(HermesCLI)
    cli.session_id = "visible-session"

    class FakeSessionDB:
        def resolve_resume_session_id(self, session_id):
            assert session_id == "pre-compression-session"
            return "visible-session"

    cli._session_db = FakeSessionDB()

    assert cli._owns_process_notification(
        {
            "type": "async_delegation",
            "session_key": "pre-compression-session",
        }
    )
