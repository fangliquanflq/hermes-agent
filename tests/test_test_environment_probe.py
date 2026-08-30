from __future__ import annotations

from scripts.check_test_environment import find_missing_test_dependencies


def test_probe_reports_every_missing_dependency() -> None:
    missing_modules = {"pytest", "pytest_asyncio", "croniter", "psutil"}

    def import_module(name: str) -> object:
        if name in missing_modules:
            raise ModuleNotFoundError(name)
        return object()

    assert find_missing_test_dependencies(import_module) == [
        "pytest",
        "pytest-asyncio",
        "croniter",
        "psutil",
    ]


def test_probe_treats_broken_import_as_unavailable() -> None:
    def import_module(name: str) -> object:
        if name == "PIL":
            raise RuntimeError("binary extension cannot load")
        return object()

    assert find_missing_test_dependencies(import_module) == ["Pillow"]
