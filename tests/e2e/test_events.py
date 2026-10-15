import asyncio

import pytest
import pytest_asyncio

from bench.hass_client import EVENT_KINDS, POLL_SECONDS

RULE_KINDS = ("intrusion", "line", "tamper", "video_loss")


@pytest_asyncio.fixture(scope="module", loop_scope="session", autouse=True)
async def rule_sensors(hass, entry):
    for kind in RULE_KINDS:
        await hass.enable_entity(entry.entity_ids[kind])
    # Home Assistant reloads the entry 30 s after the last entity is enabled
    for kind in RULE_KINDS:
        await hass.wait_available(entry.entity_ids[kind], timeout=60)


async def states_during(hass, entity_id, seconds):
    loop = asyncio.get_running_loop()
    end = loop.time() + seconds
    seen = set()
    while loop.time() < end:
        seen.add(await hass.state(entity_id))
        await asyncio.sleep(POLL_SECONDS)
    return seen


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


async def test_a_held_event_stays_on_past_the_ten_second_fallback(
    hass, camera, entry
):
    sensor = entry.entity_ids["motion"]
    await hass.wait_state(sensor, "off", timeout=2)

    await camera.event("motion", True)
    await hass.wait_state(sensor, "on", timeout=2)
    # each start the camera repeats, once a second, restarts the 10 s event_timeout
    seen = await states_during(hass, sensor, 12)
    await camera.event("motion", False)

    assert seen == {"on"}
    await hass.wait_state(sensor, "off", timeout=2)


async def test_a_motion_event_turns_on_motion_and_person(hass, camera, entry):
    motion, person, vehicle = (
        entry.entity_ids[key] for key in ("motion", "person", "vehicle")
    )
    await hass.wait_state(person, "off", timeout=2)

    await camera.event("motion", True)
    await hass.wait_state(motion, "on", timeout=2)
    await hass.wait_state(person, "on", timeout=2)
    assert await hass.state(vehicle) == "off"
    await camera.event("motion", False)

    await hass.wait_state(motion, "off", timeout=2)
    await hass.wait_state(person, "off", timeout=2)


async def test_a_vehicle_event_turns_on_vehicle_and_motion(hass, camera, entry):
    motion, person, vehicle = (
        entry.entity_ids[key] for key in ("motion", "person", "vehicle")
    )
    await hass.wait_state(vehicle, "off", timeout=2)

    await camera.event("vehicle", True)
    await hass.wait_state(vehicle, "on", timeout=2)
    await hass.wait_state(motion, "on", timeout=2)
    assert await hass.state(person) == "off"
    await camera.event("vehicle", False)

    await hass.wait_state(vehicle, "off", timeout=2)
    await hass.wait_state(motion, "off", timeout=2)


async def test_person_is_unavailable_while_all_motion_detection_is_on(
    hass, camera, entry
):
    person = entry.entity_ids["person"]
    await hass.wait_state(person, "off", timeout=2)

    await camera.settings(detection={"motion": True})
    await hass.call("homeassistant", "update_entity", person)
    try:
        # 15 s: update_entity refreshes through the coordinator's 10 s debouncer
        await hass.wait_state(person, "unavailable", timeout=15)
    finally:
        await hass.call("switch", "turn_off", entry.entity_ids["motion_detection"])

    await hass.wait_state(person, "off", timeout=5)
