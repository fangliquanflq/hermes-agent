from hermes_cli.update_cmd import _macos_tcc_stale_grant_notice


def test_macos_tcc_notice_requires_preexisting_desktop_app():
    notice = _macos_tcc_stale_grant_notice(
        platform="darwin",
        had_desktop_app_before_update=True,
    )

    assert notice is not None
    assert "tccutil reset ScreenCapture com.nousresearch.hermes" in notice
    assert (
        _macos_tcc_stale_grant_notice(
            platform="darwin",
            had_desktop_app_before_update=False,
        )
        is None
    )
    assert (
        _macos_tcc_stale_grant_notice(
            platform="linux",
            had_desktop_app_before_update=True,
        )
        is None
    )
