"""Read-only Windows environment probes used by ``hermes doctor``."""

from __future__ import annotations

import errno
import os
import shutil
import subprocess
import tempfile
from pathlib import Path


PreflightRow = tuple[str, str, str, str | None]


def symlink_preflight() -> PreflightRow:
    """Probe whether this Windows process can create symbolic links."""
    try:
        with tempfile.TemporaryDirectory(prefix="hermes-doctor-symlink-") as tmp:
            root = Path(tmp)
            target = root / "target.txt"
            link = root / "link.txt"
            target.write_text("hermes doctor\n", encoding="utf-8")
            link.symlink_to(target)
    except OSError as exc:
        if getattr(exc, "winerror", None) == 1314 or exc.errno in {
            errno.EACCES,
            errno.EPERM,
        }:
            fix = (
                "Run `cmd.exe /c start ms-settings:developers`, enable Developer "
                "Mode, then reopen the terminal (or run Hermes elevated)."
            )
            return (
                "warn",
                "Symbolic-link creation is not permitted",
                "(tests and staging operations that preserve symlinks can fail)",
                fix,
            )
        return (
            "info",
            "Symlink privilege probe skipped",
            f"({exc})",
            None,
        )
    return ("ok", "Symbolic-link creation permitted", "", None)


def git_preflight() -> PreflightRow:
    """Warn when a Windows credential helper may prompt in background jobs."""
    git = shutil.which("git")
    if not git:
        return (
            "info",
            "Non-interactive Git probe skipped",
            "(git not found)",
            None,
        )

    try:
        from hermes_cli._subprocess_compat import windows_hide_flags

        result = subprocess.run(
            [git, "config", "--get-all", "credential.helper"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdin=subprocess.DEVNULL,
            timeout=5,
            creationflags=windows_hide_flags(),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return (
            "info",
            "Non-interactive Git probe skipped",
            f"({exc})",
            None,
        )

    if result.returncode not in (0, 1):
        detail = (result.stderr or f"git config exited {result.returncode}").strip()
        return (
            "info",
            "Non-interactive Git probe skipped",
            f"({detail})",
            None,
        )

    helpers = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    interactive = [
        helper
        for helper in helpers
        if any(token in helper.lower() for token in ("manager", "wincred"))
    ]
    prompts_disabled = os.environ.get("GIT_TERMINAL_PROMPT") == "0"
    gcm_disabled = os.environ.get("GCM_INTERACTIVE", "").lower() == "never"
    if not interactive:
        return (
            "ok",
            "Git credential helper will not open an interactive Windows prompt",
            "(no Git Credential Manager or wincred helper configured)",
            None,
        )
    if prompts_disabled and gcm_disabled:
        return (
            "ok",
            "Git credential prompts disabled for background commands",
            "(GIT_TERMINAL_PROMPT=0, GCM_INTERACTIVE=Never)",
            None,
        )

    helper_names = ", ".join(interactive)
    fix = (
        "For custom Git Bash background jobs, run "
        "`export GIT_TERMINAL_PROMPT=0 GCM_INTERACTIVE=Never` before Git. "
        "Hermes internal Git operations already apply these safeguards."
    )
    return (
        "warn",
        "Interactive Git credential helper may block custom background jobs",
        f"(credential.helper={helper_names})",
        fix,
    )


def bash_path_preflight(project_root: Path) -> PreflightRow:
    """Verify Hermes' Git Bash can round-trip a native Windows path."""
    try:
        from hermes_cli._subprocess_compat import windows_hide_flags
        from tools.environments.local import _find_bash

        bash = _find_bash()
    except Exception as exc:  # diagnostics must fail open
        return (
            "warn",
            "Git Bash required by the local terminal is unavailable",
            f"({exc})",
            "Run `winget install --id Git.Git -e`, reopen the terminal, then rerun `hermes doctor`.",
        )

    native = project_root.resolve().as_posix()
    command = (
        'native="$1"; unix="$(cygpath -u "$native")" || exit $?; '
        'cygpath -m "$unix"'
    )
    try:
        result = subprocess.run(
            [bash, "-lc", command, "hermes-doctor", native],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdin=subprocess.DEVNULL,
            timeout=5,
            creationflags=windows_hide_flags(),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return (
            "info",
            "Git Bash path round-trip probe skipped",
            f"({exc})",
            None,
        )

    round_tripped = result.stdout.strip()
    expected_norm = os.path.normcase(os.path.normpath(native))
    actual_norm = os.path.normcase(os.path.normpath(round_tripped))
    if result.returncode == 0 and round_tripped and actual_norm == expected_norm:
        return (
            "ok",
            "Git Bash round-trips native Windows paths",
            f"({native})",
            None,
        )

    detail = (result.stderr or round_tripped or f"exit {result.returncode}").strip()
    if len(detail) > 240:
        detail = detail[:237] + "..."
    return (
        "warn",
        "Git Bash cannot round-trip native Windows paths",
        f"({detail})",
        "Repair Git for Windows or set HERMES_GIT_BASH_PATH to a working `bash.exe`, then rerun `hermes doctor`.",
    )


def long_paths_preflight() -> PreflightRow:
    """Read the Windows long-path policy without modifying the registry."""
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SYSTEM\CurrentControlSet\Control\FileSystem",
            0,
            winreg.KEY_READ,
        ) as key:
            enabled, _value_type = winreg.QueryValueEx(key, "LongPathsEnabled")
        enabled = int(enabled)
    except (ImportError, OSError, TypeError, ValueError) as exc:
        return (
            "info",
            "Windows long-path policy probe skipped",
            f"({exc})",
            None,
        )

    if enabled == 1:
        return ("ok", "Windows long paths enabled", "", None)
    fix = (
        "From an elevated terminal run `reg add "
        '"HKLM\\SYSTEM\\CurrentControlSet\\Control\\FileSystem" '
        "/v LongPathsEnabled /t REG_DWORD /d 1 /f`, then restart affected applications."
    )
    return (
        "warn",
        "Windows long paths disabled",
        "(deep checkouts and node_modules trees can exceed MAX_PATH)",
        fix,
    )


def collect_windows_preflight_rows(project_root: Path) -> list[PreflightRow]:
    """Collect all read-only Windows environment preflight rows."""
    return [
        symlink_preflight(),
        git_preflight(),
        bash_path_preflight(project_root),
        long_paths_preflight(),
    ]
