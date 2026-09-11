"""1Password browser-vault authentication contracts."""

from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

from agent.vault_backends import unlock as unlock_mod
from agent.vault_backends.onepassword import OnePasswordLoginBackend


def test_successful_tokenless_signin_uses_desktop_app_auth():
    """App-integrated op succeeds without minting an OP_SESSION token."""
    unlock_mod.lock("onepassword")
    with patch("agent.secret_scope.get_secret", return_value=""):
        backend = OnePasswordLoginBackend({"account": "work.1password.com"})

    signin = CompletedProcess(["op", "signin", "--raw"], 0, "", "")
    command = CompletedProcess(["op", "item", "list"], 0, "[]", "")
    try:
        with patch.object(backend, "_op", return_value=Path("op")), \
             patch("agent.vault_backends.onepassword.run_with_stdin_secret", return_value=signin), \
             patch("agent.vault_backends.onepassword.run_cli", return_value=command) as run_cli:
            backend.unlock("account password")
            assert backend.is_unlocked()
            assert backend._run("item", "list") == "[]"

        child_env = run_cli.call_args.kwargs["env"]
        assert child_env["OP_ACCOUNT"] == "work.1password.com"
        assert not any(name.startswith("OP_SESSION") for name in child_env)
    finally:
        unlock_mod.lock("onepassword")