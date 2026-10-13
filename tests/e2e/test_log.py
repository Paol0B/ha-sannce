async def test_the_log_has_no_traceback_from_the_integration(hass):
    log = await hass.text("/api/error_log")

    # traceback frames name the file; plain log lines only name the logger
    frames = [line for line in log.splitlines() if "/custom_components/sannce/" in line]
    assert frames == []
