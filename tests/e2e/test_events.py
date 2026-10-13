import asyncio

import pytest
import pytest_asyncio

from bench.hass_client import EVENT_KINDS

RULE_KINDS = ("intrusion", "line", "tamper", "video_loss")


@pytest_asyncio.fixture(scope="module", loop_scope="session", autouse=True)
async def rule_sensors(hass, entry):
    for kind in RULE_KINDS:
        await hass.enable_entity(entry.entity_ids[kind])
    # Home Assistant reloads the entry 30 s after the last entity is enabled
    for kind in RULE_KINDS:
        await hass.wait_available(entry.entity_ids[kind], timeout=60)


@pytest.mark.parametrize("kind", EVENT_KINDS)
async def test_a_start_turns_the_sensor_on_and_a_stop_turns_it_off(
    hass, camera, entry, kind
):
    sensor = entry.entity_ids[kind]
    await hass.wait_state(sensor, "off", timeout=2)

    await camera.event(kind, True)
    await hass.wait_state(sensor, "on", timeout=2)
    await camera.event(kind, False)
    await hass.wait_state(sensor, "off", timeout=2)


async def test_a_start_without_a_stop_turns_off_after_ten_seconds(hass, camera, entry):
    sensor = entry.entity_ids["motion"]
    await hass.wait_state(sensor, "off", timeout=2)
    loop = asyncio.get_running_loop()
    started = loop.time()

    await camera.event("motion", True)
    await hass.wait_state(sensor, "on", timeout=2)
    await hass.wait_state(sensor, "off", timeout=15)

    # the library clears an event 10 s after its start (event_timeout)
    assert 9.5 <= loop.time() - started <= 12
