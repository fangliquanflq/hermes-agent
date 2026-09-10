"""Safe display metadata for the credential currently serving an agent."""

from __future__ import annotations

from typing import Any


def active_credential_label(agent: Any) -> str:
    """Return the active pool entry's label without exposing credential material.

    The agent's entry id identifies the credential actually installed on its
    client. The pool's shared cursor can move independently, so it is not an
    authoritative display source.
    """
    pool = getattr(agent, "_credential_pool", None)
    entry_id = getattr(agent, "_credential_pool_entry_id", None)
    if pool is None or not isinstance(entry_id, str) or not entry_id:
        return ""
    try:
        entry = next((item for item in pool.entries() if item.id == entry_id), None)
    except Exception:
        return ""
    if entry is None:
        return ""
    return " ".join(str(entry.label or "").split())
