"""Leaf helpers for normalizing Hermes .env file content."""

from __future__ import annotations


def sanitize_env_lines(lines: list[str]) -> list[str]:
    """Normalize line endings and whitespace without changing assignment semantics."""
    sanitized: list[str] = []
    for line in lines:
        raw = line.rstrip("\r\n")
        stripped = raw.strip()
        # Blank lines and comments are preserved verbatim.
        sanitized.append((raw if not stripped or stripped.startswith("#") else stripped) + "\n")
    return sanitized
