"""Executable completion-state coverage for the Windows Desktop handoff."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent
WINDOWS_PS1 = REPO_ROOT / "scripts" / "desktop-update" / "windows.ps1"


@pytest.mark.windows_only
def test_completion_requires_runtime_and_desktop_postconditions(tmp_path: Path) -> None:
    system_root = Path(os.environ.get("SystemRoot", r"C:\Windows"))
    powershell = (
        system_root / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    )
    if not powershell.is_file():
        pytest.skip(f"Windows PowerShell not found at {powershell}")

    result = subprocess.run(
        [
            str(powershell),
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(WINDOWS_PS1),
            "-SelfTestCompletion",
        ],
        capture_output=True,
        text=True,
        timeout=60,
        env={**os.environ, "TEMP": str(tmp_path), "TMP": str(tmp_path)},
        cwd=str(REPO_ROOT),
    )

    assert result.returncode == 0, (
        f"completion self-test exited {result.returncode}.\n"
        f"--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
    )
    assert "COMPLETION SELF-TEST: PASS" in result.stdout
