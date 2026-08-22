"""Native-Windows behavior tests for the doctor environment preflight."""

from __future__ import annotations

import errno
import subprocess
import sys
import types
from pathlib import Path

import pytest

from hermes_cli import doctor
from hermes_cli import windows_preflight as preflight


pytestmark = pytest.mark.windows_only


def _completed(*, stdout: str = "", stderr: str = "", returncode: int = 0):
    return subprocess.CompletedProcess([], returncode, stdout, stderr)


def test_symlink_probe_reports_actionable_privilege_failure(monkeypatch):
    error = OSError(errno.EPERM, "privilege not held")
    error.winerror = 1314
    monkeypatch.setattr(
        Path,
        "symlink_to",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(error),
    )

    status, text, _detail, fix = preflight.symlink_preflight()

    assert status == "warn"
    assert "not permitted" in text
    assert "ms-settings:developers" in fix
    assert "Developer Mode" in fix


def test_git_probe_warns_for_gcm_without_noninteractive_environment(monkeypatch):
    monkeypatch.setattr(preflight.shutil, "which", lambda command: "C:/Git/bin/git.exe")
    monkeypatch.setattr(
        preflight.subprocess,
        "run",
        lambda *_args, **_kwargs: _completed(stdout="manager-core\n"),
    )
    monkeypatch.delenv("GIT_TERMINAL_PROMPT", raising=False)
    monkeypatch.delenv("GCM_INTERACTIVE", raising=False)

    status, text, detail, fix = preflight.git_preflight()

    assert status == "warn"
    assert "background jobs" in text
    assert "manager-core" in detail
    assert "GIT_TERMINAL_PROMPT=0" in fix
    assert "GCM_INTERACTIVE=Never" in fix
    assert "internal Git operations already apply" in fix


def test_git_probe_accepts_noninteractive_environment(monkeypatch):
    monkeypatch.setattr(preflight.shutil, "which", lambda command: "C:/Git/bin/git.exe")
    monkeypatch.setattr(
        preflight.subprocess,
        "run",
        lambda *_args, **_kwargs: _completed(stdout="manager\n"),
    )
    monkeypatch.setenv("GIT_TERMINAL_PROMPT", "0")
    monkeypatch.setenv("GCM_INTERACTIVE", "Never")

    status, text, detail, fix = preflight.git_preflight()

    assert status == "ok"
    assert "disabled" in text
    assert "GCM_INTERACTIVE=Never" in detail
    assert fix is None


def test_git_probe_skips_when_git_is_unavailable(monkeypatch):
    monkeypatch.setattr(preflight.shutil, "which", lambda command: None)

    status, text, detail, fix = preflight.git_preflight()

    assert status == "info"
    assert "skipped" in text
    assert "git not found" in detail
    assert fix is None


def test_bash_probe_round_trips_native_path(monkeypatch):
    fake_local = types.SimpleNamespace(_find_bash=lambda: "C:/Git/bin/bash.exe")
    monkeypatch.setitem(sys.modules, "tools.environments.local", fake_local)
    monkeypatch.setattr(
        preflight.subprocess,
        "run",
        lambda *_args, **_kwargs: _completed(stdout="C:/workspace/hermes-agent\n"),
    )

    status, text, detail, fix = preflight.bash_path_preflight(
        Path("C:/workspace/hermes-agent")
    )

    assert status == "ok"
    assert "round-trips" in text
    assert "C:/workspace/hermes-agent" in detail
    assert fix is None


def test_bash_probe_reports_missing_terminal_dependency(monkeypatch):
    def _missing_bash():
        raise RuntimeError("Git Bash not found")

    fake_local = types.SimpleNamespace(_find_bash=_missing_bash)
    monkeypatch.setitem(sys.modules, "tools.environments.local", fake_local)

    status, text, detail, fix = preflight.bash_path_preflight(Path("C:/repo"))

    assert status == "warn"
    assert "unavailable" in text
    assert "Git Bash not found" in detail
    assert "winget install --id Git.Git -e" in fix


def test_long_paths_probe_warns_with_copy_pasteable_registry_fix(monkeypatch):
    class _Key:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    fake_winreg = types.SimpleNamespace(
        HKEY_LOCAL_MACHINE=object(),
        KEY_READ=1,
        OpenKey=lambda *_args: _Key(),
        QueryValueEx=lambda *_args: (0, 4),
    )
    monkeypatch.setitem(sys.modules, "winreg", fake_winreg)

    status, text, detail, fix = preflight.long_paths_preflight()

    assert status == "warn"
    assert "disabled" in text
    assert "MAX_PATH" in detail
    assert "reg add" in fix
    assert "LongPathsEnabled" in fix


def test_long_paths_probe_skips_when_registry_is_unreadable(monkeypatch):
    fake_winreg = types.SimpleNamespace(
        HKEY_LOCAL_MACHINE=object(),
        KEY_READ=1,
        OpenKey=lambda *_args: (_ for _ in ()).throw(PermissionError("denied")),
    )
    monkeypatch.setitem(sys.modules, "winreg", fake_winreg)

    status, text, detail, fix = preflight.long_paths_preflight()

    assert status == "info"
    assert "skipped" in text
    assert "denied" in detail
    assert fix is None


def test_report_collects_only_warning_remediations(monkeypatch, capsys):
    monkeypatch.setattr(
        preflight,
        "collect_windows_preflight_rows",
        lambda _project_root: [
            ("ok", "healthy", "", None),
            ("info", "skipped", "(unavailable)", None),
            ("warn", "needs attention", "(detail)", "run repair-command"),
        ],
    )
    manual_issues: list[str] = []

    doctor._report_windows_preflight(manual_issues)

    output = capsys.readouterr().out
    assert "Windows Preflight" in output
    assert "healthy" in output
    assert "skipped" in output
    assert "Fix: run repair-command" in output
    assert manual_issues == ["run repair-command"]
