import asyncio

import pytest


@pytest.mark.parametrize("kind", ["motion", "vehicle"])
async def test_a_start_turns_the_sensor_on_and_a_stop_turns_it_off(
    hass, camera, entry, kind
):
    sensor = entry.entity_ids[kind]
    await hass.wait_state(sensor, "off", timeout=2)

    await camera.event(kind, True)
    await hass.wait_state(sensor, "on", timeout=2)
    await camera.event(kind, False)
    await hass.wait_state(sensor, "off", timeout=2)


async def test_a_start_without_a_stop_turns_off_after_ten_seconds(
    hass, camera, entry
):
    sensor = entry.entity_ids["motion"]
    await hass.wait_state(sensor, "off", timeout=2)
    loop = asyncio.get_running_loop()
    started = loop.time()

    await camera.event("motion", True)
    await hass.wait_state(sensor, "on", timeout=2)
    await hass.wait_state(sensor, "off", timeout=15)

    # the library clears an event 10 s after its start (event_timeout)
    assert 9.5 <= loop.time() - started <= 12
