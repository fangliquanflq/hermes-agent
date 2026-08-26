"""Verify that a macOS ``open`` command surfaced its target application.

The ``open`` process reports only whether LaunchServices accepted the request.
For Desktop sessions that is not enough: the document can exist behind the
Hermes window. This module recognizes conservative, single-command invocations,
activates the resolved application through AppKit, then reports the final
frontmost bundle instead of trusting an activation method's return value.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Sequence


@dataclass(frozen=True)
class MacOSOpenRequest:
    target: str
    application: str = ""
    bundle_id: str = ""


@dataclass(frozen=True)
class MacOSOpenVerification:
    attempted: bool
    verified: bool
    target_bundle_id: str = ""
    frontmost_bundle_id: str = ""
    error: str = ""

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


# Dynamic shell constructs make the path seen by ``open`` unknowable here. Keep
# this parser deliberately narrower than bash rather than guessing a target.
_DYNAMIC_SHELL_CHARS = frozenset(";&|`$<>()\n\r")
_FLAGS_WITH_VALUE = {"-a", "-b"}
_SAFE_FLAGS = {"-n", "-W"}
_BACKGROUND_FLAGS = {"-g", "-j"}


def parse_macos_open_command(command: str, cwd: str) -> MacOSOpenRequest | None:
    """Return the target of a conservative, foreground ``open`` invocation."""
    if not command or any(char in command for char in _DYNAMIC_SHELL_CHARS):
        return None
    try:
        argv = shlex.split(command, posix=True)
    except ValueError:
        return None
    if not argv or Path(argv[0]).name != "open":
        return None

    application = ""
    bundle_id = ""
    targets: list[str] = []
    index = 1
    while index < len(argv):
        token = argv[index]
        if token == "--":
            targets.extend(argv[index + 1 :])
            break
        if token in _BACKGROUND_FLAGS:
            return None
        if token in _FLAGS_WITH_VALUE:
            index += 1
            if index >= len(argv):
                return None
            if token == "-a":
                application = argv[index]
            else:
                bundle_id = argv[index]
        elif token in _SAFE_FLAGS:
            pass
        elif token.startswith("-"):
            # -R, -f, -e, -t and --args change target/application semantics.
            return None
        else:
            targets.append(token)
        index += 1

    if len(targets) != 1:
        return None

    target = targets[0]
    if "://" not in target and not os.path.isabs(target):
        target = os.path.abspath(os.path.join(cwd, target))
    return MacOSOpenRequest(target=target, application=application, bundle_id=bundle_id)


_JXA_VERIFY_SCRIPT = r"""
ObjC.import('AppKit')

function unwrap(value) {
  if (value === null || value === undefined) return ''
  try { return ObjC.unwrap(value) || '' } catch (_) { return '' }
}
function sleep(seconds) { $.NSThread.sleepForTimeInterval(seconds) }

const target = __TARGET__
const requestedApplication = __APPLICATION__
let bundleId = __BUNDLE_ID__
const workspace = $.NSWorkspace.sharedWorkspace

if (!bundleId && requestedApplication) {
  const appPath = unwrap(workspace.fullPathForApplication(requestedApplication))
  if (appPath) {
    bundleId = unwrap($.NSBundle.bundleWithPath(appPath).bundleIdentifier)
  }
}
if (!bundleId) {
  const targetUrl = target.includes('://')
    ? $.NSURL.URLWithString(target)
    : $.NSURL.fileURLWithPath(target)
  const appUrl = workspace.URLForApplicationToOpenURL(targetUrl)
  if (appUrl) {
    bundleId = unwrap($.NSBundle.bundleWithURL(appUrl).bundleIdentifier)
  }
}
if (!bundleId) {
  console.log(JSON.stringify({ verified: false, error: 'could not resolve target application' }))
} else {
  function runningApplications() {
    return $.NSRunningApplication.runningApplicationsWithBundleIdentifier(bundleId)
  }
  function activate() {
    const applications = runningApplications()
    for (let index = 0; index < applications.count; index += 1) {
      const application = applications.objectAtIndex(index)
      application.unhide()
      application.activateWithOptions(3) // all windows + ignoring other apps
    }
  }
  function frontmostBundle() {
    const application = workspace.frontmostApplication
    return application ? unwrap(application.bundleIdentifier) : ''
  }

  // LaunchServices may return before NSRunningApplication publishes the app.
  for (let index = 0; index < 15 && runningApplications().count === 0; index += 1) {
    sleep(0.1)
  }
  activate()
  sleep(0.8)
  if (frontmostBundle() !== bundleId) {
    // Re-assert once after the settle window to absorb a queued focus race.
    activate()
    sleep(0.8)
  }
  const frontmost = frontmostBundle()
  console.log(JSON.stringify({
    verified: frontmost === bundleId,
    target_bundle_id: bundleId,
    frontmost_bundle_id: frontmost,
    error: frontmost === bundleId ? '' : 'target application is not frontmost'
  }))
}
"""


def _verification_script(request: MacOSOpenRequest) -> str:
    return (
        _JXA_VERIFY_SCRIPT.replace("__TARGET__", json.dumps(request.target))
        .replace("__APPLICATION__", json.dumps(request.application))
        .replace("__BUNDLE_ID__", json.dumps(request.bundle_id))
    )


def verify_macos_open_request(
    request: MacOSOpenRequest,
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> MacOSOpenVerification:
    """Activate and verify ``request`` using AppKit via JavaScript for Automation."""
    try:
        completed = runner(
            ["/usr/bin/osascript", "-l", "JavaScript", "-e", _verification_script(request)],
            capture_output=True,
            text=True,
            timeout=6,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return MacOSOpenVerification(attempted=True, verified=False, error=str(exc))

    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "osascript failed").strip()
        return MacOSOpenVerification(attempted=True, verified=False, error=detail)
    try:
        payload = json.loads((completed.stdout or "").strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError):
        return MacOSOpenVerification(
            attempted=True,
            verified=False,
            error="foreground verification returned no valid result",
        )
    return MacOSOpenVerification(
        attempted=True,
        verified=payload.get("verified") is True,
        target_bundle_id=str(payload.get("target_bundle_id") or ""),
        frontmost_bundle_id=str(payload.get("frontmost_bundle_id") or ""),
        error=str(payload.get("error") or ""),
    )


def verify_desktop_open_command(
    command: str,
    cwd: str,
    *,
    env_type: str,
    session_platform: str,
    host_platform: str | None = None,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> MacOSOpenVerification | None:
    """Verify eligible local macOS Desktop ``open`` commands, otherwise return None."""
    current_platform = host_platform or sys.platform
    if current_platform != "darwin" or env_type != "local" or session_platform != "desktop":
        return None
    request = parse_macos_open_command(command, cwd)
    if request is None:
        return None
    return verify_macos_open_request(request, runner=runner)
