"""#76129: post-update Windows cold-start must not steal Desktop-owned lifecycle.

A vestigial Startup/Scheduled-Task autostart is not proof the user wants a
standalone ``gateway run``. When Desktop currently supervises this install's
control plane, the updater must not spawn a competing messaging daemon.

Serve/dashboard are the control plane, not the messaging gateway (#92091).
``looks_like_gateway_command_line`` stays strict; ownership is a separate
predicate.

#109538: ownership alone must not hide a gateway that *died*. The Desktop
hand-off exits the app before the updater starts and can kill the running
gateway in those same seconds, so discovery finds no live PID while a start
attestation still vouches for the dead one. In that case the cold-start
survives both the plan-time and the spawn-time ownership check — the Desktop
does not restart the messaging gateway itself.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

from hermes_cli import gateway as hermes_gateway
from hermes_cli import gateway_windows
from hermes_cli import main as cli_main
import hermes_cli.main_install_repair as main_install_repair
from hermes_cli import process_identity
from hermes_cli import profiles as profiles_mod
from hermes_cli import update_cmd
import hermes_cli.update_cmd_windows as update_cmd_windows


def _live_serve_ledger_entry() -> dict:
    return {
        "pid": 111,
        "create_time": 1.0,
        "purpose": "serve",
        "install": "abc",
        "spawner_pid": 99,
        "spawner_create": 0.5,
    }


def test_control_plane_argv_is_not_a_gateway():
    from gateway.status import looks_like_gateway_command_line

    serve = "C:\\Hermes\\.venv\\Scripts\\python.exe -m hermes_cli.main serve --host 127.0.0.1"
    run = "C:\\Hermes\\.venv\\Scripts\\python.exe -m hermes_cli.main gateway run"

    assert update_cmd._looks_like_desktop_control_plane(serve) is True
    assert looks_like_gateway_command_line(serve) is False
    assert update_cmd._looks_like_desktop_control_plane(run) is False
    assert looks_like_gateway_command_line(run) is True


def test_control_plane_classifier_is_token_based_not_substring():
    """#90778/#91869 class: flag values and lookalike tokens must not read
    as a control plane. The salvage swapped the original substring check
    for the parser-derived subcommand classifier."""
    py = "C:\\Hermes\\.venv\\Scripts\\python.exe -m hermes_cli.main"
    # "dashboard" as a FLAG VALUE, real subcommand is chat
    assert update_cmd._looks_like_desktop_control_plane(f"{py} -m dashboard chat") is False
    # "--preserve-cache" contains "serve"; real subcommand is kanban
    assert (
        update_cmd._looks_like_desktop_control_plane(f"{py} kanban --preserve-cache")
        is False
    )
    # profile selector before the real subcommand still classifies correctly
    assert (
        update_cmd._looks_like_desktop_control_plane(f"{py} --profile serve dashboard")
        is True
    )
    # dashboard as the real subcommand
    assert update_cmd._looks_like_desktop_control_plane(f"{py} dashboard") is True
    # undeterminable subcommand → NOT a control plane (never guess ownership)
    assert update_cmd._looks_like_desktop_control_plane("python.exe -c import time") is False


def test_ledger_live_serve_with_live_spawner_owns_lifecycle(monkeypatch):
    monkeypatch.setattr(
        process_identity, "ledger_entries", lambda **_k: [_live_serve_ledger_entry()]
    )
    monkeypatch.setattr(process_identity, "spawner_is_dead", lambda _e: False)
    monkeypatch.setattr(cli_main, "_detect_venv_python_processes", lambda: [])

    assert update_cmd._desktop_owns_gateway_lifecycle() is True


def test_orphaned_control_plane_does_not_own_lifecycle(monkeypatch):
    monkeypatch.setattr(
        process_identity, "ledger_entries", lambda **_k: [_live_serve_ledger_entry()]
    )
    monkeypatch.setattr(process_identity, "spawner_is_dead", lambda _e: True)
    monkeypatch.setattr(cli_main, "_detect_venv_python_processes", lambda: [])

    assert update_cmd._desktop_owns_gateway_lifecycle() is False


def test_pause_skips_cold_start_plan_when_desktop_owns_lifecycle(monkeypatch):
    monkeypatch.setattr(cli_main, "_is_windows", lambda: True)
    monkeypatch.setattr(main_install_repair, "_is_windows", lambda: True)
    monkeypatch.setattr(hermes_gateway, "find_gateway_pids", lambda **_k: [])
    monkeypatch.setattr(
        hermes_gateway, "find_windows_gateway_services", lambda **_k: []
    )
    monkeypatch.setattr(gateway_windows, "is_installed", lambda: True)
    monkeypatch.setattr(gateway_windows, "attested_death_generation", lambda **_k: None)
    monkeypatch.setattr(update_cmd, "_desktop_owns_gateway_lifecycle", lambda: True)
    monkeypatch.setattr(update_cmd_windows, "_desktop_owns_gateway_lifecycle", lambda: True)

    assert update_cmd._pause_windows_gateways_for_update() is None


def test_pause_still_cold_starts_when_autostart_and_no_desktop_owner(monkeypatch):
    monkeypatch.setattr(cli_main, "_is_windows", lambda: True)
    monkeypatch.setattr(main_install_repair, "_is_windows", lambda: True)
    monkeypatch.setattr(hermes_gateway, "find_gateway_pids", lambda **_k: [])
    monkeypatch.setattr(
        hermes_gateway, "find_windows_gateway_services", lambda **_k: []
    )
    monkeypatch.setattr(gateway_windows, "is_installed", lambda: True)
    monkeypatch.setattr(update_cmd, "_desktop_owns_gateway_lifecycle", lambda: False)
    monkeypatch.setattr(update_cmd_windows, "_desktop_owns_gateway_lifecycle", lambda: False)

    token = update_cmd._pause_windows_gateways_for_update()

    assert token == {
        "resume_needed": True,
        "profiles": {},
        "unmapped_pids": [],
        "unmapped": [],
        "cold_start_if_installed": True,
    }


def test_cold_start_aborts_when_desktop_owns_lifecycle(monkeypatch):
    spawned = []
    monkeypatch.setattr(cli_main, "_is_windows", lambda: True)
    monkeypatch.setattr(main_install_repair, "_is_windows", lambda: True)
    monkeypatch.setattr(hermes_gateway, "find_gateway_pids", lambda **_k: [])
    monkeypatch.setattr(gateway_windows, "attested_death_generation", lambda **_k: None)
    monkeypatch.setattr(update_cmd, "_desktop_owns_gateway_lifecycle", lambda: True)
    monkeypatch.setattr(update_cmd_windows, "_desktop_owns_gateway_lifecycle", lambda: True)
    monkeypatch.setattr(
        gateway_windows, "_spawn_detached", lambda: spawned.append(1) or 4242
    )

    update_cmd._cold_start_windows_gateway_after_update()

    assert spawned == []


def test_attested_dead_gateway_survives_desktop_ownership_and_marker_is_consumed_on_spawn(
    monkeypatch, tmp_path, capsys
):
    """#109538: the Desktop hand-off can kill the running gateway moments before update
    discovery runs, so a dead start attestation is the surviving "a gateway was up"
    evidence. It must keep the plan AND survive the spawn-time ownership re-check.
    Once the spawn happens the marker is consumed, so a stale crash marker cannot
    re-authorize a cold start against Desktop ownership on a later update."""
    monkeypatch.setattr("hermes_cli.config.get_hermes_home", lambda: str(tmp_path))
    monkeypatch.setattr(cli_main, "_is_windows", lambda: True)
    monkeypatch.setattr(main_install_repair, "_is_windows", lambda: True)
    monkeypatch.setattr(hermes_gateway, "find_gateway_pids", lambda **_k: [])
    monkeypatch.setattr(hermes_gateway, "find_windows_gateway_services", lambda **_k: [])
    monkeypatch.setattr(gateway_windows, "is_installed", lambda: True)
    monkeypatch.setattr(update_cmd, "_desktop_owns_gateway_lifecycle", lambda: True)
    monkeypatch.setattr(update_cmd_windows, "_desktop_owns_gateway_lifecycle", lambda: True)
    gateway_windows._write_start_attestation([555], "direct spawn (PID 555)")
    marker = tmp_path / "state" / "gateway.start-attestation.json"

    token = update_cmd._pause_windows_gateways_for_update()

    generation = token.pop("cold_start_profiles")["default"]
    assert generation == json.loads(marker.read_text(encoding="utf-8"))["generation"]
    assert token == {
        "resume_needed": True,
        "profiles": {},
        "unmapped_pids": [],
        "unmapped": [],
    }
    token["attested_generation"] = generation
    assert marker.exists()  # plan-time probe is read-only

    spawned = []
    monkeypatch.setattr(gateway_windows, "_spawn_detached", lambda: spawned.append(1) or 4242)
    monkeypatch.setattr(gateway_windows, "_wait_for_gateway_ready", lambda *a, **k: [4242])
    monkeypatch.setattr(gateway_windows, "_write_start_attestation", lambda *a, **k: None)

    # A token written by pre-generation code and resumed across this very update carries no
    # ``attested_generation`` key: the marker is probed again rather than the spawn skipped.
    legacy_token = {k: v for k, v in token.items() if k != "attested_generation"}
    assert update_cmd._cold_start_windows_gateway_after_update(legacy_token) is True
    assert spawned == [1]
    assert "Gateway started via cold-start after update (PID: 4242)" in capsys.readouterr().out
    assert not marker.exists()  # consumed by the spawn
    assert gateway_windows.attested_death_generation(current_pids=[]) is None


def test_cold_start_is_authorized_by_the_token_generation_not_the_mutable_marker(
    monkeypatch, tmp_path, capsys
):
    """#110020 review (a): the marker is a one-shot that a concurrent ``hermes gateway status``
    consumes between plan and execution. The spawn must still happen (authority lives on the
    token), and a *newer* marker written by a concurrent ``hermes gateway start`` must not be
    consumed as if it were ours."""
    monkeypatch.setattr("hermes_cli.config.get_hermes_home", lambda: str(tmp_path))
    monkeypatch.setattr(cli_main, "_is_windows", lambda: True)
    monkeypatch.setattr(main_install_repair, "_is_windows", lambda: True)
    monkeypatch.setattr(hermes_gateway, "find_gateway_pids", lambda **_k: [])
    monkeypatch.setattr(hermes_gateway, "find_windows_gateway_services", lambda **_k: [])
    monkeypatch.setattr(gateway_windows, "is_installed", lambda: True)
    monkeypatch.setattr(update_cmd, "_desktop_owns_gateway_lifecycle", lambda: True)
    monkeypatch.setattr(update_cmd_windows, "_desktop_owns_gateway_lifecycle", lambda: True)
    gateway_windows._write_start_attestation([555], "direct spawn (PID 555)")
    marker = tmp_path / "state" / "gateway.start-attestation.json"
    token = update_cmd._pause_windows_gateways_for_update()
    assert token["cold_start_profiles"]["default"]

    # Concurrent ``hermes gateway status`` consumed the marker...
    assert gateway_windows.check_start_attestation(current_pids=[]) is not None
    assert not marker.exists()
    # ...and a concurrent ``hermes gateway start`` wrote a fresh one for its own PID.
    gateway_windows._write_start_attestation([777], "direct spawn (PID 777)")
    newer = json.loads(marker.read_text(encoding="utf-8"))["generation"]
    generation = token["cold_start_profiles"]["default"]
    assert newer != generation

    spawned = []
    monkeypatch.setattr(gateway_windows, "_spawn_detached", lambda: spawned.append(1) or 4242)
    monkeypatch.setattr(gateway_windows, "_wait_for_gateway_ready", lambda *a, **k: [4242])
    monkeypatch.setattr(gateway_windows, "_write_start_attestation", lambda *a, **k: None)

    assert update_cmd._cold_start_windows_gateway_after_update({"attested_generation": generation}) is True
    assert spawned == [1]  # authorized by the token, not by the (consumed) marker
    assert json.loads(marker.read_text(encoding="utf-8"))["generation"] == newer  # not ours to consume


def test_dead_default_profile_is_cold_started_while_beta_is_relaunched(
    monkeypatch, tmp_path
):
    default_home = tmp_path / "default"
    beta_home = default_home / "profiles" / "beta"
    beta_home.mkdir(parents=True)
    beta = SimpleNamespace(profile="beta", path=beta_home, pid=202)
    monkeypatch.setattr(cli_main, "_is_windows", lambda: True)
    monkeypatch.setattr(main_install_repair, "_is_windows", lambda: True)
    monkeypatch.setattr(hermes_gateway, "find_gateway_pids", lambda **_k: [202])
    monkeypatch.setattr(hermes_gateway, "find_profile_gateway_processes", lambda **_k: [beta])
    monkeypatch.setattr(hermes_gateway, "find_windows_gateway_services", lambda **_k: [])
    monkeypatch.setattr(hermes_gateway, "_get_restart_drain_timeout", lambda: 0.1)
    monkeypatch.setattr(profiles_mod, "profiles_to_serve", lambda **_k: [
        ("default", default_home), ("beta", beta_home),
    ])
    monkeypatch.setattr(update_cmd, "_desktop_owns_gateway_lifecycle", lambda: True)
    monkeypatch.setattr(cli_main, "_venv_launcher_ancestors", lambda _pids: [])
    monkeypatch.setattr(cli_main, "_wait_for_windows_update_gateway_exit", lambda *_a, **_k: set())
    monkeypatch.setattr(
        gateway_windows, "attested_death_generation",
        lambda current_pids, home=None: "default-generation" if home == default_home else None,
    )

    token = update_cmd._pause_windows_gateways_for_update()

    assert token["profiles"] == {"beta": 202}
    assert token["cold_start_profiles"] == {"default": "default-generation"}

    events = []
    monkeypatch.setattr(cli_main, "_refresh_windows_gateway_launchers", lambda: None)
    monkeypatch.setattr(
        gateway_windows, "_spawn_detached",
        lambda **kwargs: events.append(("cold-start", kwargs)) or 303,
    )
    monkeypatch.setattr(
        gateway_windows, "_wait_for_gateway_ready",
        lambda **kwargs: events.append(("ready", kwargs)) or [303],
    )
    monkeypatch.setattr(
        gateway_windows, "_consume_start_attestation",
        lambda generation, home=None: events.append(("consume", generation, home)),
    )
    monkeypatch.setattr(gateway_windows, "_write_start_attestation", lambda *_a, **_k: None)
    monkeypatch.setattr(
        update_cmd_windows, "_relaunch_paused_gateways",
        lambda *_a: events.append(("relaunch", "beta")) or (["beta"], 0),
    )
    monkeypatch.setattr(update_cmd_windows, "_verify_relaunched_gateways_alive", lambda *_a: None)

    update_cmd._resume_windows_gateways_after_update(token)

    assert events[0] == ("cold-start", {"profile": "default", "home": default_home})
    assert ("ready", {"home": default_home}) in events
    assert ("consume", "default-generation", default_home) in events
    assert events.index(("relaunch", "beta")) > events.index(("consume", "default-generation", default_home))
    assert token["cold_start_profiles"] == {}
    assert token["relaunched_profiles"] == ["default", "beta"]
    assert token["resume_needed"] is False


def test_running_profile_does_not_create_unattested_cold_start_obligations(
    monkeypatch, tmp_path
):
    default_home = tmp_path / "default"
    beta_home = default_home / "profiles" / "beta"
    beta_home.mkdir(parents=True)
    beta = SimpleNamespace(profile="beta", path=beta_home, pid=202)
    monkeypatch.setattr(cli_main, "_is_windows", lambda: True)
    monkeypatch.setattr(main_install_repair, "_is_windows", lambda: True)
    monkeypatch.setattr(hermes_gateway, "find_gateway_pids", lambda **_k: [202])
    monkeypatch.setattr(hermes_gateway, "find_profile_gateway_processes", lambda **_k: [beta])
    monkeypatch.setattr(hermes_gateway, "find_windows_gateway_services", lambda **_k: [])
    monkeypatch.setattr(hermes_gateway, "_get_restart_drain_timeout", lambda: 0.1)
    monkeypatch.setattr(profiles_mod, "profiles_to_serve", lambda **_k: [
        ("default", default_home), ("beta", beta_home),
    ])
    monkeypatch.setattr(update_cmd, "_desktop_owns_gateway_lifecycle", lambda: True)
    monkeypatch.setattr(cli_main, "_venv_launcher_ancestors", lambda _pids: [])
    monkeypatch.setattr(cli_main, "_wait_for_windows_update_gateway_exit", lambda *_a, **_k: set())
    monkeypatch.setattr(gateway_windows, "attested_death_generation", lambda **_k: None)

    token = update_cmd._pause_windows_gateways_for_update()

    assert token["profiles"] == {"beta": 202}
    assert "cold_start_profiles" not in token
