"""Lifecycle-status visibility follows per-platform display settings."""

from types import SimpleNamespace

import pytest

from gateway.config import Platform
from gateway.run import TurnRunner, _prepare_gateway_status_message
from gateway.turn_context import TurnContext


LEASE_STATUS_MESSAGES = [
    (
        "⏳ Another Hermes process is using this session; waiting for it to "
        "finish before starting your turn..."
    ),
    "⏳ Still waiting for the other Hermes process on this session (30s)...",
    "Session is free; loading the latest transcript...",
]


@pytest.mark.parametrize("platform", [Platform.WHATSAPP, Platform.TELEGRAM, Platform.SLACK])
@pytest.mark.parametrize("message", LEASE_STATUS_MESSAGES)
def test_chat_lifecycle_statuses_follow_interim_visibility(platform, message):
    assert (
        _prepare_gateway_status_message(
            platform,
            "lifecycle",
            message,
            interim_assistant_messages_enabled=False,
        )
        is None
    )
    assert (
        _prepare_gateway_status_message(
            platform,
            "lifecycle",
            message,
            interim_assistant_messages_enabled=True,
        )
        == message
    )


def test_lifecycle_mute_preserves_required_provider_errors():
    raw = (
        "API call failed after 3 retries: HTTP 401 Unauthorized — "
        "Authorization: Bearer sk-" + "A" * 24
    )

    prepared = _prepare_gateway_status_message(
        Platform.WHATSAPP,
        "lifecycle",
        raw,
        interim_assistant_messages_enabled=False,
    )

    assert prepared is not None
    assert "provider" in prepared.lower()
    assert "HTTP 401" not in prepared
    assert "sk-" + "A" * 24 not in prepared


def test_lifecycle_mute_does_not_hide_warning_events():
    warning = "⚠ Context is full; start a new session."

    assert (
        _prepare_gateway_status_message(
            Platform.WHATSAPP,
            "warn",
            warning,
            interim_assistant_messages_enabled=False,
        )
        == warning
    )


def test_programmatic_surfaces_keep_lifecycle_statuses_when_muted():
    message = LEASE_STATUS_MESSAGES[0]

    for platform in (Platform.LOCAL, Platform.API_SERVER, Platform.WEBHOOK):
        assert (
            _prepare_gateway_status_message(
                platform,
                "lifecycle",
                message,
                interim_assistant_messages_enabled=False,
            )
            == message
        )


def test_turn_runner_threads_interim_visibility_into_status_filter(monkeypatch):
    scheduled = []

    def capture_schedule(coro, *_args, **_kwargs):
        scheduled.append(coro)
        coro.close()
        return None

    monkeypatch.setattr("gateway.run.safe_schedule_threadsafe", capture_schedule)
    source = SimpleNamespace(platform=Platform.WHATSAPP)
    ctx = TurnContext(
        source=source,
        _run_still_current=lambda: True,
        interim_assistant_messages_enabled=False,
        _status_adapter=object(),
        _status_chat_id="chat",
        _status_thread_metadata=None,
        _loop_for_step=object(),
    )
    turn_runner = TurnRunner(SimpleNamespace(), ctx)

    turn_runner._status_callback_sync("lifecycle", LEASE_STATUS_MESSAGES[0])
    assert scheduled == []

    ctx.interim_assistant_messages_enabled = True
    turn_runner._status_callback_sync("lifecycle", LEASE_STATUS_MESSAGES[0])
    assert len(scheduled) == 1
