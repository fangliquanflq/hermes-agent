"""Regression coverage for stale Windows editable-install mappings (#97819)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
import hermes_cli.main as main_mod

from hermes_cli import _install_repair as install_repair
from hermes_cli import _startup_fast


def _write_project(root: Path) -> None:
    (root / "hermes_cli").mkdir(parents=True)
    (root / "pyproject.toml").write_text(
        '[project]\nname = "hermes-agent"\n', encoding="utf-8"
    )


def _write_editable_metadata(site_packages: Path, source: Path) -> None:
    dist_info = site_packages / "hermes_agent-0.20.6.dist-info"
    dist_info.mkdir(parents=True)
    (dist_info / "direct_url.json").write_text(
        json.dumps(
            {
                "url": source.as_uri(),
                "dir_info": {"editable": True},
            }
        ),
        encoding="utf-8",
    )


def _write_finder(site_packages: Path, mapping: dict[str, str]) -> None:
    (site_packages / "__editable__.hermes_agent-0.20.6.pth").write_text(
        "import __editable___hermes_agent_0_20_6_finder; "
        "__editable___hermes_agent_0_20_6_finder.install()\n",
        encoding="utf-8",
    )
    (site_packages / "__editable___hermes_agent_0_20_6_finder.py").write_text(
        f"MAPPING = {mapping!r}\nNAMESPACES = {{}}\n",
        encoding="utf-8",
    )


def test_project_root_uses_editable_source_when_loaded_from_site_packages(tmp_path):
    source = tmp_path / "checkout"
    _write_project(source)
    site_packages = tmp_path / "venv" / "Lib" / "site-packages"
    package_file = site_packages / "hermes_cli" / "_startup_fast.py"
    package_file.parent.mkdir(parents=True)
    _write_editable_metadata(site_packages, source)

    assert _startup_fast.project_root_str(package_file=str(package_file)) == str(
        source.resolve()
    )


def test_project_root_rejects_non_editable_direct_url(tmp_path):
    installed = tmp_path / "venv" / "Lib" / "site-packages"
    package_file = installed / "hermes_cli" / "_startup_fast.py"
    package_file.parent.mkdir(parents=True)
    source = tmp_path / "checkout"
    _write_project(source)
    _write_editable_metadata(installed, source)
    direct_url = next(installed.glob("*.dist-info/direct_url.json"))
    direct_url.write_text(
        json.dumps({"url": source.as_uri(), "dir_info": {"editable": False}}),
        encoding="utf-8",
    )

    assert _startup_fast.project_root_str(package_file=str(package_file)) == str(
        installed.resolve()
    )


def test_editable_mapping_rejects_missing_and_wrong_root_targets(tmp_path):
    source = tmp_path / "checkout"
    _write_project(source)
    (source / "tools").mkdir()
    site_packages = tmp_path / "venv" / "Lib" / "site-packages"
    site_packages.mkdir(parents=True)
    stale = site_packages / "physical-copy"
    _write_finder(
        site_packages,
        {
            "hermes_cli": str(stale / "hermes_cli"),
            "tools": str(stale / "tools"),
        },
    )

    assert not install_repair.editable_mapping_is_healthy(
        source, site_packages=site_packages
    )


def test_editable_mapping_accepts_source_tree_targets(tmp_path):
    source = tmp_path / "checkout"
    _write_project(source)
    (source / "tools").mkdir()
    (source / "hermes_bootstrap.py").write_text("", encoding="utf-8")
    site_packages = tmp_path / "venv" / "Lib" / "site-packages"
    site_packages.mkdir(parents=True)
    _write_finder(
        site_packages,
        {
            "hermes_cli": str(source / "hermes_cli"),
            "tools": str(source / "tools"),
            "hermes_bootstrap": str(source / "hermes_bootstrap"),
        },
    )

    assert install_repair.editable_mapping_is_healthy(
        source, site_packages=site_packages
    )


def test_require_editable_mapping_raises_after_successful_but_stale_install(
    tmp_path,
):
    source = tmp_path / "checkout"
    _write_project(source)
    site_packages = tmp_path / "venv" / "Lib" / "site-packages"
    site_packages.mkdir(parents=True)
    _write_finder(
        site_packages,
        {"hermes_cli": str(site_packages / "hermes_cli")},
    )

    with pytest.raises(RuntimeError, match="editable mapping"):
        install_repair.require_healthy_editable_mapping(
            source, site_packages=site_packages
        )


def test_core_recovery_forces_reinstall_when_success_keeps_stale_mapping(
    tmp_path, monkeypatch
):
    source = tmp_path / "checkout"
    _write_project(source)
    commands: list[list[str]] = []
    checks = iter([False, True])

    monkeypatch.setattr(
        install_repair, "_resolve_install_target", lambda _root: (["uv", "pip"], {})
    )
    monkeypatch.setattr(
        install_repair,
        "_run_install_cmd",
        lambda cmd, **_kwargs: commands.append(list(cmd)),
    )
    monkeypatch.setattr(
        install_repair,
        "editable_mapping_is_healthy",
        lambda _root, **_kwargs: next(checks),
        raising=False,
    )

    install_repair.run_core_install(source)

    assert commands[0] == ["uv", "pip", "install", "-e", ".[all]"]
    assert commands[1] == [
        "uv",
        "pip",
        "install",
        "--reinstall",
        "-e",
        ".[all]",
    ]


def test_update_forces_reinstall_when_success_keeps_stale_mapping(
    tmp_path, monkeypatch
):
    source = tmp_path / "checkout"
    _write_project(source)
    commands: list[list[str]] = []
    checks = iter([False, True])

    monkeypatch.setattr(main_mod, "PROJECT_ROOT", source)
    monkeypatch.setattr(main_mod, "_is_windows", lambda: False)
    monkeypatch.setattr(main_mod, "_venv_scripts_dir", lambda: None)
    monkeypatch.setattr(main_mod, "_verify_console_scripts_installed", lambda *a, **k: None)
    monkeypatch.setattr(
        main_mod,
        "_run_quarantined_install",
        lambda cmd, **_kwargs: commands.append(list(cmd)),
    )
    monkeypatch.setattr(
        install_repair,
        "editable_mapping_is_healthy",
        lambda _root, **_kwargs: next(checks),
    )

    main_mod._install_python_dependencies_with_optional_fallback(["uv", "pip"])

    assert commands == [
        ["uv", "pip", "install", "-e", ".[all]"],
        ["uv", "pip", "install", "--reinstall", "-e", ".[all]"],
    ]


def test_core_recovery_verifies_mapping_after_optional_extra_fallback(
    tmp_path, monkeypatch
):
    source = tmp_path / "checkout"
    _write_project(source)
    commands: list[list[str]] = []
    checks = iter([False, True])

    def run(cmd, **_kwargs):
        commands.append(list(cmd))
        if len(commands) == 1:
            raise subprocess.CalledProcessError(1, cmd)

    monkeypatch.setattr(
        install_repair, "_resolve_install_target", lambda _root: (["uv", "pip"], {})
    )
    monkeypatch.setattr(install_repair, "_run_install_cmd", run)
    monkeypatch.setattr(
        install_repair, "_load_installable_optional_extras", lambda *_args: []
    )
    monkeypatch.setattr(
        install_repair,
        "editable_mapping_is_healthy",
        lambda _root, **_kwargs: next(checks),
    )

    install_repair.run_core_install(source)

    assert commands[-2:] == [
        ["uv", "pip", "install", "-e", "."],
        ["uv", "pip", "install", "--reinstall", "-e", "."],
    ]