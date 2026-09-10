"""Thread-safe turn-halt directives returned by plugin hooks.

Hook dispatch may run on bounded worker threads and streaming observers always run
asynchronously. This registry lets those callbacks request a controlled stop without
mutating an ``AIAgent`` from a plugin-owned thread. Turn ids are explicitly opened and
closed so delayed observer results cannot leak into a later turn.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any, Iterable


@dataclass(frozen=True)
class PluginTurnHalt:
    response: str


_lock = threading.Lock()
_active_turns: set[str] = set()
_pending: dict[str, PluginTurnHalt] = {}


def open_plugin_turn(turn_id: str) -> None:
    if not turn_id:
        return
    with _lock:
        _pending.pop(turn_id, None)
        _active_turns.add(turn_id)


def close_plugin_turn(turn_id: str) -> None:
    if not turn_id:
        return
    with _lock:
        _active_turns.discard(turn_id)
        _pending.pop(turn_id, None)


def record_plugin_turn_halt(turn_id: str, result: Any) -> bool:
    """Record the first valid ``halt_turn`` result for an active turn."""
    if not turn_id or not isinstance(result, dict) or result.get("action") != "halt_turn":
        return False
    response = result.get("response")
    if not isinstance(response, str) or not response.strip():
        return False
    with _lock:
        if turn_id not in _active_turns or turn_id in _pending:
            return False
        _pending[turn_id] = PluginTurnHalt(response=response)
    return True


def record_plugin_turn_halts(turn_id: str, results: Iterable[Any]) -> bool:
    for result in results:
        if record_plugin_turn_halt(turn_id, result):
            return True
    return False


def take_plugin_turn_halt(turn_id: str) -> PluginTurnHalt | None:
    if not turn_id:
        return None
    with _lock:
        return _pending.pop(turn_id, None)
