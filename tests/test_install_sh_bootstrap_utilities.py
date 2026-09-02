"""Behavioral coverage for install.sh bootstrap utility checks."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest


INSTALL_SH = Path(__file__).resolve().parents[1] / "scripts" / "install.sh"
_REQUIRED_COMMANDS = (
    "awk",
    "cat",
    "chmod",
    "dirname",
    "grep",
    "gzip",
    "head",
    "id",
    "ln",
    "ls",
    "mkdir",
    "mktemp",
    "mv",
    "rm",
    "sed",
    "sh",
    "tr",
)


def _link_commands(bin_dir: Path, *, omit: frozenset[str] = frozenset()) -> None:
    bin_dir.mkdir()
    for name in _REQUIRED_COMMANDS:
        if name in omit:
            continue
        source = shutil.which(name)
        assert source, f"test host is missing {name}"
        (bin_dir / name).symlink_to(source)


def _write_executable(path: Path, body: str) -> None:
    path.write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8")
    path.chmod(0o755)


def _run_installer(tmp_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    bash = shutil.which("bash")
    assert bash, "behavioral installer tests require bash"
    env = os.environ.copy()
    env.update(
        {
            "HOME": str(tmp_path / "home"),
            "HERMES_HOME": str(tmp_path / "hermes-home"),
            "PATH": str(tmp_path / "bin"),
        }
    )
    return subprocess.run(
        [bash, str(INSTALL_SH), *args],
        capture_output=True,
        text=True,
        timeout=30,
        env=env,
    )


@pytest.mark.linux_only
def test_prerequisites_fail_fast_with_actionable_hint_when_awk_is_missing(
    tmp_path: Path,
) -> None:
    bin_dir = tmp_path / "bin"
    _link_commands(bin_dir, omit=frozenset({"awk"}))
    _write_executable(
        bin_dir / "uname",
        'if [ "${1:-}" = "-m" ]; then echo x86_64; else echo Linux; fi',
    )
    _write_executable(bin_dir / "curl", "exit 99")
    _write_executable(bin_dir / "tar", "exit 99")

    result = _run_installer(tmp_path, "--stage", "prerequisites", "--json")

    assert result.returncode != 0
    output = result.stdout + result.stderr
    assert "Missing required system utilities: awk" in output
    assert "gawk" in output
    assert "install" in output
    assert '"ok":false' in output
    assert "Installing managed uv" not in output


@pytest.mark.linux_only
def test_node_uses_tar_gz_when_xz_is_unavailable(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    _link_commands(bin_dir)
    _write_executable(
        bin_dir / "uname",
        'if [ "${1:-}" = "-m" ]; then echo x86_64; else echo Linux; fi',
    )
    _write_executable(
        bin_dir / "curl",
        """output=""
while [ "$#" -gt 0 ]; do
    if [ "$1" = "-o" ]; then output="$2"; shift 2; continue; fi
    shift
done
if [ -n "$output" ]; then
    : > "$output"
else
    printf '%s\\n' \
      'node-v26.8.1-linux-x64.tar.xz' \
      'node-v26.8.1-linux-x64.tar.gz'
fi""",
    )
    _write_executable(
        bin_dir / "tar",
        """archive="$2"
destination="$4"
printf '%s\\n' "$archive" > "$HERMES_TEST_TAR_RECORD"
mkdir -p "$destination/node-v26.8.1-linux-x64/bin"
for command in node npm npx; do
    cat > "$destination/node-v26.8.1-linux-x64/bin/$command" <<'EOF'
#!/bin/sh
echo v26.8.1
EOF
    chmod +x "$destination/node-v26.8.1-linux-x64/bin/$command"
done""",
    )

    record = tmp_path / "selected-archive.txt"
    env_record = str(record)
    bash = shutil.which("bash")
    assert bash
    env = os.environ.copy()
    env.update(
        {
            "HOME": str(tmp_path / "home"),
            "HERMES_HOME": str(tmp_path / "hermes-home"),
            "HERMES_TEST_TAR_RECORD": env_record,
            "PATH": str(bin_dir),
        }
    )
    result = subprocess.run(
        [bash, str(INSTALL_SH), "--ensure", "node"],
        capture_output=True,
        text=True,
        timeout=30,
        env=env,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert record.read_text(encoding="utf-8").strip().endswith(".tar.gz")
    assert ".tar.xz" not in record.read_text(encoding="utf-8")
