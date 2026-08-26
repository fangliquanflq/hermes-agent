"""Regression tests for profile-dependent tool schema paths."""


def _schema_for(definitions: list[dict], tool_name: str) -> dict:
    return next(
        definition["function"]
        for definition in definitions
        if definition["function"]["name"] == tool_name
    )


def test_tool_schema_paths_follow_active_profile_without_reimport(tmp_path, monkeypatch):
    profile_a = tmp_path / "profiles" / "alpha"
    profile_b = tmp_path / "profiles" / "beta"
    profile_a.mkdir(parents=True)
    profile_b.mkdir(parents=True)
    monkeypatch.setenv("HERMES_HOME", str(profile_a))
    monkeypatch.setenv("HERMES_INTERACTIVE", "1")

    # Import once under profile A, matching a long-lived multi-profile process.
    from tools import cronjob_tools, skill_manager_tool, tts_tool
    from hermes_constants import display_hermes_home
    from model_tools import _clear_tool_defs_cache, get_tool_definitions

    _clear_tool_defs_cache()

    def resolved_paths() -> tuple[str, str, str]:
        definitions = get_tool_definitions(
            enabled_toolsets=["cronjob", "skills", "tts"],
            quiet_mode=True,
        )
        cron_schema = _schema_for(definitions, "cronjob")
        skill_schema = _schema_for(definitions, "skill_manage")
        tts_schema = _schema_for(definitions, "text_to_speech")
        return (
            cron_schema["parameters"]["properties"]["script"]["description"],
            skill_schema["description"],
            tts_schema["parameters"]["properties"]["output_path"]["description"],
        )

    expected_a = display_hermes_home()
    first = resolved_paths()
    monkeypatch.setenv("HERMES_HOME", str(profile_b))
    expected_b = display_hermes_home()
    second = resolved_paths()

    for description in first:
        assert expected_a in description
        assert expected_b not in description
    for description in second:
        assert expected_b in description
        assert expected_a not in description

    # The module-level schemas remain profile-neutral and cannot leak the
    # profile that happened to import them first.
    static_schemas = (
        cronjob_tools.CRONJOB_SCHEMA,
        skill_manager_tool.SKILL_MANAGE_SCHEMA,
        tts_tool.TTS_SCHEMA,
    )
    for schema in static_schemas:
        assert expected_a not in str(schema)
        assert expected_b not in str(schema)