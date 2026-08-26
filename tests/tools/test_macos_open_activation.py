import json
from subprocess import CompletedProcess
from unittest.mock import MagicMock

import tools.macos_open_activation as macos_open
import tools.terminal_tool as terminal_tool
from gateway.session_context import clear_session_vars, set_session_vars


def test_parse_open_with_application_and_relative_target(tmp_path):
    request = macos_open.parse_macos_open_command(
        'open -a Preview "reports/q3 review.pdf"', str(tmp_path)
    )

    assert request == macos_open.MacOSOpenRequest(
        target=str(tmp_path / "reports" / "q3 review.pdf"),
        application="Preview",
    )


def test_parse_open_preserves_url_and_bundle_id(tmp_path):
    request = macos_open.parse_macos_open_command(
        "open -b com.apple.Safari https://example.com/report", str(tmp_path)
    )

    assert request == macos_open.MacOSOpenRequest(
        target="https://example.com/report",
        bundle_id="com.apple.Safari",
    )


def test_parse_open_skips_background_dynamic_and_changed_semantics(tmp_path):
    cwd = str(tmp_path)

    assert macos_open.parse_macos_open_command("open -g report.pdf", cwd) is None
    assert macos_open.parse_macos_open_command("open report.pdf && echo done", cwd) is None
    assert macos_open.parse_macos_open_command("open -R report.pdf", cwd) is None
    assert macos_open.parse_macos_open_command("open one.pdf two.pdf", cwd) is None
    assert macos_open.parse_macos_open_command("printf open", cwd) is None


def test_verify_request_reports_final_observed_frontmost_bundle():
    calls = []

    def runner(argv, **kwargs):
        calls.append((argv, kwargs))
        return CompletedProcess(
            argv,
            0,
            stdout=json.dumps(
                {
                    "verified": True,
                    "target_bundle_id": "com.apple.Preview",
                    "frontmost_bundle_id": "com.apple.Preview",
                    "error": "",
                }
            ),
            stderr="",
        )

    result = macos_open.verify_macos_open_request(
        macos_open.MacOSOpenRequest("/tmp/report.pdf", application="Preview"),
        runner=runner,
    )

    assert result.verified is True
    assert result.target_bundle_id == "com.apple.Preview"
    assert result.frontmost_bundle_id == "com.apple.Preview"
    argv, kwargs = calls[0]
    assert argv[:4] == ["/usr/bin/osascript", "-l", "JavaScript", "-e"]
    assert '"/tmp/report.pdf"' in argv[4]
    assert kwargs["timeout"] == 6
    assert kwargs["check"] is False


def test_verify_request_does_not_trust_successful_activation_attempt():
    def runner(argv, **_kwargs):
        return CompletedProcess(
            argv,
            0,
            stdout=json.dumps(
                {
                    "verified": False,
                    "target_bundle_id": "com.apple.Preview",
                    "frontmost_bundle_id": "com.google.Chrome",
                    "error": "target application is not frontmost",
                }
            ),
            stderr="",
        )

    result = macos_open.verify_macos_open_request(
        macos_open.MacOSOpenRequest("/tmp/report.pdf", application="Preview"),
        runner=runner,
    )

    assert result.attempted is True
    assert result.verified is False
    assert result.frontmost_bundle_id == "com.google.Chrome"
    assert result.error == "target application is not frontmost"


def test_desktop_open_gate_is_session_host_and_backend_scoped(tmp_path):
    kwargs = {
        "command": "open report.pdf",
        "cwd": str(tmp_path),
        "runner": lambda *_args, **_kwargs: None,
    }

    assert macos_open.verify_desktop_open_command(
        **kwargs, env_type="local", session_platform="desktop", host_platform="win32"
    ) is None
    assert macos_open.verify_desktop_open_command(
        **kwargs, env_type="ssh", session_platform="desktop", host_platform="darwin"
    ) is None
    assert macos_open.verify_desktop_open_command(
        **kwargs, env_type="local", session_platform="tui", host_platform="darwin"
    ) is None


def _run_terminal_with_verification(monkeypatch, tmp_path, verification):
    environment = MagicMock()
    environment.execute.return_value = {"output": "", "returncode": 0}
    config = {
        "env_type": "local",
        "timeout": 30,
        "cwd": str(tmp_path),
        "host_cwd": None,
        "modal_mode": "auto",
        "docker_image": "",
        "singularity_image": "",
        "modal_image": "",
        "daytona_image": "",
    }
    monkeypatch.setattr(terminal_tool, "_get_env_config", lambda: config)
    monkeypatch.setattr(terminal_tool, "_start_cleanup_thread", lambda: None)
    monkeypatch.setattr(
        terminal_tool, "_check_all_guards", lambda *_args, **_kwargs: {"approved": True}
    )
    monkeypatch.setattr(
        macos_open, "verify_desktop_open_command", lambda *_args, **_kwargs: verification
    )
    monkeypatch.setitem(terminal_tool._active_environments, "macos-open-test", environment)
    monkeypatch.setitem(terminal_tool._last_activity, "macos-open-test", 0.0)
    tokens = set_session_vars(platform="desktop", session_key="macos-open-test")
    try:
        return json.loads(
            terminal_tool.terminal_tool(
                command='open -a Preview "/tmp/report.pdf"',
                task_id="macos-open-test",
            )
        )
    finally:
        clear_session_vars(tokens)
        terminal_tool._active_environments.pop("macos-open-test", None)
        terminal_tool._last_activity.pop("macos-open-test", None)


def test_terminal_surfaces_open_foreground_verification_failure(monkeypatch, tmp_path):
    verification = macos_open.MacOSOpenVerification(
        attempted=True,
        verified=False,
        target_bundle_id="com.apple.Preview",
        frontmost_bundle_id="com.google.Chrome",
        error="target application is not frontmost",
    )

    result = _run_terminal_with_verification(monkeypatch, tmp_path, verification)

    assert result["exit_code"] == 1
    assert result["error"] == "target application is not frontmost"
    assert "File opened, but foreground verification failed" in result["output"]
    assert result["foreground_activation"]["frontmost_bundle_id"] == "com.google.Chrome"


def test_terminal_reports_verified_open_from_final_state(monkeypatch, tmp_path):
    verification = macos_open.MacOSOpenVerification(
        attempted=True,
        verified=True,
        target_bundle_id="com.apple.Preview",
        frontmost_bundle_id="com.apple.Preview",
    )

    result = _run_terminal_with_verification(monkeypatch, tmp_path, verification)

    assert result["exit_code"] == 0
    assert result["error"] is None
    assert result["foreground_activation"]["verified"] is True
