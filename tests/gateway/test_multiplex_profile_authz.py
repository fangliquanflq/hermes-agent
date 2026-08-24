"""Regression tests for multiplex profile-aware own-policy authorization."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from agent import secret_scope
from gateway.config import GatewayConfig, Platform, PlatformConfig
from gateway.session import SessionSource


def _clear_auth_env(monkeypatch) -> None:
    for key in (
        "WECOM_ALLOWED_USERS",
        "GATEWAY_ALLOWED_USERS",
        "GATEWAY_ALLOW_ALL_USERS",
        "WECOM_ALLOW_ALL_USERS",
    ):
        monkeypatch.delenv(key, raising=False)


def _make_multiplex_runner(monkeypatch):
    """Runner with default allowlist WeCom and secondary open-policy WeCom."""
    from gateway.run import GatewayRunner

    _clear_auth_env(monkeypatch)

    runner = object.__new__(GatewayRunner)
    runner.config = GatewayConfig(multiplex_profiles=True)

    default_adapter = SimpleNamespace(
        send=AsyncMock(),
        enforces_own_access_policy=True,
        _dm_policy="allowlist",
        _group_policy="pairing",
    )
    secondary_adapter = SimpleNamespace(
        send=AsyncMock(),
        enforces_own_access_policy=True,
        _dm_policy="open",
        _group_policy="open",
    )

    runner.adapters = {Platform.WECOM: default_adapter}
    runner._profile_adapters = {
        "coder": {Platform.WECOM: secondary_adapter},
    }
    runner.pairing_store = MagicMock()
    runner.pairing_store.is_approved.return_value = False
    return runner, default_adapter, secondary_adapter


def test_default_profile_still_trusts_own_allowlist(monkeypatch):
    """Default-profile allowlist trust is unchanged when profile is unstamped."""
    runner, _default_adapter, _secondary_adapter = _make_multiplex_runner(monkeypatch)

    source = SessionSource(
        platform=Platform.WECOM,
        user_id="allowed-user",
        chat_id="dm-chat",
        user_name="allowed-user",
        chat_type="dm",
        profile=None,
    )

    assert runner._is_user_authorized(source) is True


def test_active_profile_stamp_resolves_primary_adapter(monkeypatch):
    """A single-profile gateway stamps its active profile but stores adapters as primary."""
    runner, default_adapter, _secondary_adapter = _make_multiplex_runner(monkeypatch)
    runner._active_profile_name = lambda: "dev"

    assert runner._authorization_adapter(Platform.WECOM, profile="dev") is default_adapter


def test_secondary_allowlist_dm_behavior_ignores_unauthorized(monkeypatch):
    """Unauthorized-DM behavior must read the secondary adapter's dm_policy."""
    runner, _default_adapter, secondary_adapter = _make_multiplex_runner(monkeypatch)
    secondary_adapter._dm_policy = "allowlist"

    assert runner._get_unauthorized_dm_behavior(
        Platform.WECOM,
        profile="coder",
    ) == "ignore"
    assert runner._get_unauthorized_dm_behavior(Platform.WECOM) == "ignore"


def test_adapter_auth_check_stamps_secondary_profile(monkeypatch):
    """The adapter auth-check callback must stamp its own secondary profile.

    Regression for the gap where ``_make_adapter_auth_check`` built a
    profile-less ``SessionSource``, so a secondary adapter's external-context
    authorization (e.g. Slack/Discord thread-reply lookups) silently
    resolved the *active* profile's allowlist scope instead of its own.
    """
    from gateway.run import GatewayRunner

    _clear_auth_env(monkeypatch)

    runner = object.__new__(GatewayRunner)
    runner.config = GatewayConfig(multiplex_profiles=True)

    captured: dict = {}

    def fake_is_user_authorized(source):
        captured["profile"] = source.profile
        return True

    runner._is_user_authorized = fake_is_user_authorized

    check = runner._make_adapter_auth_check(Platform.WECOM, profile_name="coder")
    assert check("some-user", "dm", "dm-chat") is True
    assert captured["profile"] == "coder"


def test_secondary_open_policy_fails_startup_guard(monkeypatch):
    """Secondary profiles must pass the same open-policy startup guard."""
    from gateway.run import _own_policy_open_startup_violation

    _clear_auth_env(monkeypatch)

    secondary_cfg = GatewayConfig(multiplex_profiles=True)
    secondary_cfg.platforms = {
        Platform.WECOM: PlatformConfig(
            enabled=True,
            extra={"dm_policy": "open"},
        ),
    }

    violation = _own_policy_open_startup_violation(secondary_cfg)
    assert violation is not None
    assert "wecom" in violation
    assert "open policy" in violation


@pytest.fixture()
def multiplex_scope():
    previous = secret_scope.is_multiplex_active()
    secret_scope.set_multiplex_active(True)
    try:
        yield
    finally:
        secret_scope.set_multiplex_active(previous)


def test_secondary_adapter_authorization_reads_its_profile_scope(
    multiplex_scope, monkeypatch
):
    """Each own-policy adapter must snapshot the secondary profile's authz."""
    from gateway.platforms.signal import SignalAdapter
    from gateway.platforms.weixin import WeixinAdapter
    from gateway.platforms.yuanbao import YuanbaoAdapter
    from plugins.platforms.wecom.adapter import WeComAdapter

    environ = {
        "WEIXIN_DM_POLICY": "disabled",
        "WEIXIN_ALLOWED_USERS": "default-user",
        "WEIXIN_GROUP_POLICY": "disabled",
        "WEIXIN_GROUP_ALLOWED_USERS": "default-group",
        "YUANBAO_DM_POLICY": "disabled",
        "YUANBAO_DM_ALLOW_FROM": "default-user",
        "YUANBAO_GROUP_POLICY": "disabled",
        "YUANBAO_GROUP_ALLOW_FROM": "default-group",
        "SIGNAL_ALLOWED_USERS": "default-user",
        "SIGNAL_GROUP_ALLOWED_USERS": "default-group",
        "WECOM_DM_POLICY": "disabled",
        "WECOM_ALLOWED_USERS": "default-user",
        "WECOM_GROUP_POLICY": "disabled",
    }
    scoped = {
        "WEIXIN_DM_POLICY": "allowlist",
        "WEIXIN_ALLOWED_USERS": "secondary-user",
        "WEIXIN_GROUP_POLICY": "allowlist",
        "WEIXIN_GROUP_ALLOWED_USERS": "secondary-group",
        "YUANBAO_DM_POLICY": "allowlist",
        "YUANBAO_DM_ALLOW_FROM": "secondary-user",
        "YUANBAO_GROUP_POLICY": "allowlist",
        "YUANBAO_GROUP_ALLOW_FROM": "secondary-group",
        "SIGNAL_ALLOWED_USERS": "secondary-user",
        "SIGNAL_GROUP_ALLOWED_USERS": "secondary-group",
        "WECOM_DM_POLICY": "allowlist",
        "WECOM_ALLOWED_USERS": "secondary-user",
        "WECOM_GROUP_POLICY": "allowlist",
    }
    for name, value in environ.items():
        monkeypatch.setenv(name, value)

    token = secret_scope.set_secret_scope(scoped)
    try:
        weixin = WeixinAdapter(PlatformConfig(enabled=True))
        yuanbao = YuanbaoAdapter(PlatformConfig(enabled=True))
        signal = SignalAdapter(PlatformConfig(enabled=True))
        wecom = WeComAdapter(PlatformConfig(enabled=True))
    finally:
        secret_scope.reset_secret_scope(token)

    assert weixin._dm_policy == "allowlist"
    assert weixin._allow_from == ["secondary-user"]
    assert weixin._group_policy == "allowlist"
    assert weixin._group_allow_from == ["secondary-group"]
    assert yuanbao._access_policy.dm_policy == "allowlist"
    assert yuanbao._access_policy.is_dm_allowed("secondary-user") is True
    assert yuanbao._access_policy.is_dm_allowed("default-user") is False
    assert yuanbao._access_policy.group_policy == "allowlist"
    assert yuanbao._access_policy.is_group_allowed("secondary-group") is True
    assert yuanbao._access_policy.is_group_allowed("default-group") is False
    assert signal.dm_allow_from == {"secondary-user"}
    assert signal.group_allow_from == {"secondary-group"}
    assert wecom._dm_policy == "allowlist"
    assert wecom._allow_from == ["secondary-user"]
    assert wecom._group_policy == "allowlist"


@pytest.mark.parametrize(
    ("module_name", "class_name", "allow_all_env"),
    [
        ("gateway.platforms.weixin", "WeixinAdapter", "GATEWAY_ALLOW_ALL_USERS"),
        ("gateway.platforms.weixin", "WeixinAdapter", "WEIXIN_ALLOW_ALL_USERS"),
        ("gateway.platforms.yuanbao", "YuanbaoAdapter", "GATEWAY_ALLOW_ALL_USERS"),
        ("gateway.platforms.yuanbao", "YuanbaoAdapter", "YUANBAO_ALLOW_ALL_USERS"),
        ("plugins.platforms.wecom.adapter", "WeComAdapter", "GATEWAY_ALLOW_ALL_USERS"),
        ("plugins.platforms.wecom.adapter", "WeComAdapter", "WECOM_ALLOW_ALL_USERS"),
    ],
)
def test_secondary_open_policy_does_not_borrow_default_allow_all(
    multiplex_scope, monkeypatch, module_name, class_name, allow_all_env
):
    """A scoped miss must not inherit the default profile's open-world opt-in."""
    import importlib

    monkeypatch.setenv(allow_all_env, "true")
    token = secret_scope.set_secret_scope({"SOME_OTHER_KEY": "x"})
    try:
        adapter_cls = getattr(importlib.import_module(module_name), class_name)
        adapter = adapter_cls(PlatformConfig(enabled=True))
        policy_owner = getattr(adapter, "_access_policy", adapter)
        assert policy_owner._open_dm_opted_in() is False
    finally:
        secret_scope.reset_secret_scope(token)


def test_secondary_startup_guard_does_not_borrow_default_allow_all(
    multiplex_scope, monkeypatch
):
    """The shared startup guard must validate the secondary profile's opt-in."""
    from gateway.run import _own_policy_open_startup_violation

    monkeypatch.setenv("GATEWAY_ALLOW_ALL_USERS", "true")
    config = GatewayConfig(multiplex_profiles=True)
    config.platforms = {
        Platform.YUANBAO: PlatformConfig(
            enabled=True,
            extra={"dm_policy": "open"},
        ),
    }

    token = secret_scope.set_secret_scope({"SOME_OTHER_KEY": "x"})
    try:
        violation = _own_policy_open_startup_violation(config)
    finally:
        secret_scope.reset_secret_scope(token)

    assert violation is not None
    assert "yuanbao" in violation
