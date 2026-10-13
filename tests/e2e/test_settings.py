import pytest


async def test_the_light_reaches_the_camera(hass, camera, entry):
    light = entry.entity_ids["floodlight"]

    await hass.call("light", "turn_on", light)
    assert (await camera.state())["light"] is True
    await hass.wait_state(light, "on", timeout=5)

    await hass.call("light", "turn_off", light)
    assert (await camera.state())["light"] is False
    await hass.wait_state(light, "off", timeout=5)


@pytest.mark.parametrize("mode", ["color", "smart", "infrared"])
async def test_the_light_mode_reaches_the_camera(hass, camera, entry, mode):
    select = entry.entity_ids["light_mode"]

    await hass.call("select", "select_option", select, option=mode)

    assert (await camera.state())["light_mode"] == mode
    await hass.wait_state(select, mode, timeout=5)


@pytest.mark.parametrize("kind", ["person", "vehicle", "motion"])
async def test_each_detection_switch_reaches_the_camera(hass, camera, entry, kind):
    switch = entry.entity_ids[f"{kind}_detection"]

    for on in (False, True):
        await hass.call("switch", "turn_on" if on else "turn_off", switch)
        assert (await camera.state())["detection"][kind] is on
        await hass.wait_state(switch, "on" if on else "off", timeout=5)


async def test_a_change_on_the_camera_shows_after_update_entity(hass, camera, entry):
    light = entry.entity_ids["floodlight"]
    await hass.call("light", "turn_off", light)
    await hass.wait_state(light, "off", timeout=5)

    await camera.settings(light=True)
    await hass.call("homeassistant", "update_entity", light)

    # 15 s: update_entity refreshes through the coordinator's 10 s debouncer
    await hass.wait_state(light, "on", timeout=15)
