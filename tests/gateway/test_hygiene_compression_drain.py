"""Shutdown contracts for executor-backed session-hygiene compression."""

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from agent.conversation_compression import CompressionCommitFence
from tests.gateway.restart_test_helpers import make_restart_runner


@pytest.mark.asyncio
async def test_drain_waits_for_hygiene_compression_future() -> None:
    runner, _adapter = make_restart_runner()
    future = asyncio.get_running_loop().create_future()
    fence = CompressionCommitFence()
    runner._track_hygiene_compression(future, fence, MagicMock())

    drain_task = asyncio.create_task(runner._drain_active_agents(2.0))
    await asyncio.sleep(0.1)

    assert not drain_task.done()
    assert runner._active_hygiene_compression_count() == 1

    future.set_result(([], ""))
    _snapshot, timed_out = await drain_task

    assert timed_out is False
    assert runner._active_hygiene_compression_count() == 0


def test_shutdown_interrupt_reaches_hygiene_compression() -> None:
    runner, _adapter = make_restart_runner()
    future = MagicMock()
    future.done.return_value = False
    fence = CompressionCommitFence()
    agent = MagicMock()
    runner._hygiene_compressions = {future: (fence, agent)}

    with patch("gateway.run.request_hard_interrupt") as interrupt:
        runner._interrupt_hygiene_compressions("gateway shutdown")

    assert fence.is_cancelled is True
    interrupt.assert_called_once_with(agent, "gateway shutdown")