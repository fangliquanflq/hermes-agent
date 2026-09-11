"""Regression coverage for parent-free dependency-block respawn guards."""

from __future__ import annotations

from pathlib import Path

import pytest

from hermes_cli import kanban_db as kb
from hermes_cli import kanban_db_connect as kbc
from hermes_cli import kanban_db_dispatch as kbd


@pytest.fixture
def kanban_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / ".hermes"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    kb.init_db()
    return home


def _dependency_block(conn, title: str, *, comment_before: bool = False) -> str:
    task_id = kb.create_task(conn, title=title, assignee="worker")
    if comment_before:
        kb.add_comment(conn, task_id, author="operator", body="old context")
    claimed = kb.claim_task(conn, task_id, claimer="worker")
    assert claimed is not None
    assert kb.block_task(
        conn,
        task_id,
        reason="waiting for an external dependency",
        kind="dependency",
        expected_run_id=claimed.current_run_id,
    )
    return task_id


def test_parent_free_dependency_block_waits_for_real_new_input(
    kanban_home: Path, monkeypatch: pytest.MonkeyPatch, all_assignees_spawnable,
) -> None:
    """Bare auto-promotion is held; every explicit input path releases it.

    The frozen clock puts the old comment, blocked run, auto-promotion, and new
    input in the same whole second. Event-id ordering must distinguish them.
    """
    monkeypatch.setattr(kb.time, "time", lambda: 1_800_000_000)
    spawned: list[str] = []

    def spawn(task, workspace, board=None):
        spawned.append(task.id)
        return 4242

    with kbc.connect_closing() as conn:
        tasks = {
            name: _dependency_block(conn, name, comment_before=(name == "comment"))
            for name in ("comment", "unblock", "promote", "status")
        }

        for _ in range(3):
            result = kbd.dispatch_once(conn, spawn_fn=spawn)
            assert not result.spawned
        assert not spawned
        assert all(
            kbd.check_respawn_guard(conn, task_id) == "blocked_no_input"
            for task_id in tasks.values()
        )

        kb.add_comment(conn, tasks["comment"], author="operator", body="dependency resolved")
        assert kb.unblock_task(conn, tasks["unblock"])
        with kb.write_txn(conn):
            conn.execute("UPDATE tasks SET status = 'todo' WHERE id = ?", (tasks["promote"],))
        assert kb.promote_task(conn, tasks["promote"], actor="operator")[0]
        with kb.write_txn(conn):
            kb._append_event(conn, tasks["status"], "status", {"status": "ready"})

        result = kbd.dispatch_once(conn, spawn_fn=spawn)
        assert {task_id for task_id, _pid in result.spawned} == set(tasks.values())


def test_dependency_block_with_real_parent_resumes_after_parent_completion(
    kanban_home: Path, all_assignees_spawnable,
) -> None:
    spawned: list[str] = []

    def spawn(task, workspace, board=None):
        spawned.append(task.id)
        return 4242

    with kbc.connect_closing() as conn:
        parent = kb.create_task(conn, title="parent", assignee="worker")
        child = _dependency_block(conn, "child")
        kb.link_tasks(conn, parent_id=parent, child_id=child)

        first = kbd.dispatch_once(conn, spawn_fn=spawn)
        assert child not in {task_id for task_id, _pid in first.spawned}

        claimed_parent = kb.claim_task(conn, parent, claimer="worker")
        assert claimed_parent is not None
        assert kb.complete_task(
            conn,
            parent,
            result="dependency landed",
            expected_run_id=claimed_parent.current_run_id,
        )

        result = kbd.dispatch_once(conn, spawn_fn=spawn)
        assert child in {task_id for task_id, _pid in result.spawned}
