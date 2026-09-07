import asyncio
from concurrent.futures import Future
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from gateway.platforms.base import SendResult
from gateway.run_turn_runner import TurnRunner
from plugins.platforms.discord import adapter as discord_adapter
from plugins.platforms.discord.adapter import ExecApprovalView
from tools.approval import _gateway_queues
from tools.approval_gateway_wait import _ApprovalEntry


@pytest.fixture(autouse=True)
def _clear_gateway_approval_queues():
    _gateway_queues.clear()
    yield
    _gateway_queues.clear()


def _interaction(user_id: str):
    embed = MagicMock()
    return SimpleNamespace(
        user=SimpleNamespace(id=user_id, display_name=f"user-{user_id}", roles=[]),
        message=SimpleNamespace(embeds=[embed]),
        response=SimpleNamespace(send_message=AsyncMock(), edit_message=AsyncMock()),
    )


def test_gateway_carries_request_id_to_interactive_approval_metadata():
    captured = {}

    class Adapter:
        def pause_typing_for_chat(self, _chat_id):
            pass

        async def send_exec_approval(self, **kwargs):
            captured.update(kwargs)
            return SendResult(success=True)

    runner = object.__new__(TurnRunner)
    runner._ctx = SimpleNamespace(
        _status_adapter=Adapter(),
        _status_chat_id="channel",
        _status_thread_metadata={"thread_id": "thread"},
        session_key="discord:channel",
    )
    runner._close_native_stream_boundary = lambda _label: None

    def schedule(coro, _label):
        future = Future()
        future.set_result(asyncio.run(coro))
        return future

    runner._schedule = schedule
    runner._approval_notify_sync({"request_id": "request-b", "command": "do thing"})

    assert captured["metadata"] == {
        "thread_id": "thread",
        "_approval_request_id": "request-b",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("choice", ["once", "session", "always", "deny"])
async def test_exec_approval_card_resolves_only_its_request(choice):
    session_key = "discord:shared"
    first = _ApprovalEntry({"request_id": "request-a", "command": "first"})
    second = _ApprovalEntry({"request_id": "request-b", "command": "second"})
    _gateway_queues[session_key] = [first, second]
    view = ExecApprovalView(
        session_key=session_key,
        request_id="request-b",
        allowed_user_ids={"allowed"},
    )

    unauthorized = _interaction("other")
    await view._resolve(unauthorized, choice, 1, "resolved")
    assert [entry.data["request_id"] for entry in _gateway_queues[session_key]] == [
        "request-a",
        "request-b",
    ]

    authorized = _interaction("allowed")
    await view._resolve(authorized, choice, 1, "resolved")
    assert second.result == choice
    assert second.event.is_set()
    assert first.result is None
    assert _gateway_queues[session_key] == [first]

    await view._resolve(_interaction("allowed"), choice, 1, "resolved")
    assert _gateway_queues[session_key] == [first]
    assert first.result is None


@pytest.mark.asyncio
async def test_stale_exec_approval_card_does_not_resolve_newer_request(monkeypatch):
    monkeypatch.setattr(discord_adapter.discord.Color, "dark_grey", lambda: 0, raising=False)
    session_key = "discord:shared"
    current = _ApprovalEntry({"request_id": "request-b", "command": "current"})
    _gateway_queues[session_key] = [current]
    view = ExecApprovalView(
        session_key=session_key,
        request_id="expired-request-a",
        allowed_user_ids={"allowed"},
    )
    interaction = _interaction("allowed")

    await view._resolve(interaction, "once", 1, "Approved once")

    assert _gateway_queues[session_key] == [current]
    assert current.result is None
    assert not current.event.is_set()
    assert "expired" in interaction.message.embeds[0].set_footer.call_args.kwargs["text"].lower()
