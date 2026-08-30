#!/usr/bin/env python
"""Reject test interpreters whose missing imports can falsify results."""

from __future__ import annotations

import importlib
from collections.abc import Callable


_REQUIRED_TEST_IMPORTS = (
    ("pytest", "pytest"),
    ("pytest_asyncio", "pytest-asyncio"),
    ("croniter", "croniter"),
    ("psutil", "psutil"),
    ("PIL", "Pillow"),
)


def find_missing_test_dependencies(
    import_module: Callable[[str], object] = importlib.import_module,
) -> list[str]:
    missing = []
    for module_name, distribution_name in _REQUIRED_TEST_IMPORTS:
        try:
            import_module(module_name)
        except Exception:
            missing.append(distribution_name)
    return missing


def main() -> int:
    missing = find_missing_test_dependencies()
    if not missing:
        return 0
    print(", ".join(missing))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
