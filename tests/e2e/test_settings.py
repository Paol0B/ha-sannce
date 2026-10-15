import pytest
import pytest_asyncio


@pytest_asyncio.fixture(autouse=True, loop_scope="session")
async def floodlight_off(hass, entry):
    yield
    await hass.call("light", "turn_off", entry.entity_ids["floodlight"])


async def test_turning_the_floodlight_on_forces_color_mode(hass, camera, entry):
    light = entry.entity_ids["floodlight"]

    await hass.call("light", "turn_on", light)

    state = await camera.state()
    assert (state["light"], state["light_mode"]) == (True, "color")
    await hass.wait_state(light, "on", timeout=5)


async def test_the_floodlight_brightness_reaches_the_camera(hass, camera, entry):
    await hass.call(
        "light", "turn_on", entry.entity_ids["floodlight"], brightness_pct=40
    )

    state = await camera.state()
    assert (state["light"], state["light_power"]) == (True, 40)


async def test_turning_the_floodlight_off_restores_the_floodlight_mode(
    hass, camera, entry
):
    light = entry.entity_ids["floodlight"]
    mode = await hass.state(entry.entity_ids["light_mode"])
    await hass.call("light", "turn_on", light)

    await hass.call("light", "turn_off", light)

    state = await camera.state()
    assert (state["light"], state["light_mode"]) == (False, mode)
    await hass.wait_state(light, "off", timeout=5)


@pytest.mark.parametrize(
    ("start", "mode"),
    [("infrared", "color"), ("color", "smart"), ("smart", "infrared")],
)
async def test_the_light_mode_reaches_the_camera(hass, camera, entry, start, mode):
    select = entry.entity_ids["light_mode"]
    await hass.call("select", "select_option", select, option=start)
    await hass.wait_state(select, start, timeout=5)

    await hass.call("select", "select_option", select, option=mode)

    assert (await camera.state())["light_mode"] == mode
    await hass.wait_state(select, mode, timeout=5)


async def test_a_mode_chosen_while_the_floodlight_is_on_waits_for_off(
    hass, camera, entry
):
    light, select = entry.entity_ids["floodlight"], entry.entity_ids["light_mode"]
    await hass.call("select", "select_option", select, option="smart")
    await hass.call("light", "turn_on", light)

    await hass.call("select", "select_option", select, option="infrared")

    state = await camera.state()
    assert (state["light"], state["light_mode"]) == (True, "color")
    await hass.wait_state(select, "infrared", timeout=5)
    await hass.call("light", "turn_off", light)
    state = await camera.state()
    assert (state["light"], state["light_mode"]) == (False, "infrared")


@pytest.mark.parametrize("kind", ["person", "vehicle", "motion"])
async def test_each_detection_switch_reaches_the_camera(hass, camera, entry, kind):
    switch = entry.entity_ids[f"{kind}_detection"]

    for on in (False, True):
        await hass.call("switch", "turn_on" if on else "turn_off", switch)
        assert (await camera.state())["detection"][kind] is on
        await hass.wait_state(switch, "on" if on else "off", timeout=5)


async def test_the_volume_reaches_the_camera(hass, camera, entry):
    number = entry.entity_ids["volume"]

    await hass.call("number", "set_value", number, value=35)

    assert (await camera.state())["volume"] == 35
    await hass.wait_state(number, "35", timeout=5)


async def test_the_motion_sensitivity_reaches_the_camera(hass, camera, entry):
    number = entry.entity_ids["motion_sensitivity"]

    await hass.call("number", "set_value", number, value=40)

    assert (await camera.state())["detection"]["sensitivity"] == 40
    await hass.wait_state(number, "40", timeout=5)


async def test_the_siren_on_event_switch_starts_off_and_reaches_the_camera(
    hass, camera, entry
):
    switch = entry.entity_ids["siren_on_event"]
    assert await hass.state(switch) == "off"
    assert (await camera.state())["siren_on_event"] is False

    await hass.call("switch", "turn_on", switch)
    try:
        assert (await camera.state())["siren_on_event"] is True
        await hass.wait_state(switch, "on", timeout=5)
    finally:
        await hass.call("switch", "turn_off", switch)

    assert (await camera.state())["siren_on_event"] is False
    await hass.wait_state(switch, "off", timeout=5)


async def test_a_change_on_the_camera_shows_after_update_entity(hass, camera, entry):
    light = entry.entity_ids["floodlight"]
    await hass.call("light", "turn_off", light)
    await hass.wait_state(light, "off", timeout=5)

    await camera.settings(light=True)
    await hass.call("homeassistant", "update_entity", light)

    # 15 s: update_entity refreshes through the coordinator's 10 s debouncer
    await hass.wait_state(light, "on", timeout=15)
