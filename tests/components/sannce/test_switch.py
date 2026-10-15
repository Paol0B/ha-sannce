import asyncio

import pytest
from homeassistant.components.switch import DOMAIN as SWITCH_DOMAIN
from homeassistant.const import (
    ATTR_ENTITY_ID,
    ATTR_FRIENDLY_NAME,
    SERVICE_TOGGLE,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    STATE_OFF,
    STATE_ON,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
    EntityCategory,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import translation
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.sannce import lib
from custom_components.sannce.const import DOMAIN

from . import setup_integration
from .conftest import ALL_CAPS, FakeSannceCamera

KINDS = ("person", "vehicle", "motion")
NAMES = {
    "person": "Person detection",
    "vehicle": "Vehicle detection",
    "motion": "Motion detection",
}


def switch_ids(
    registry: er.EntityRegistry, entry: MockConfigEntry
) -> dict[str, str | None]:
    return {
        kind: registry.async_get_entity_id(
            SWITCH_DOMAIN, DOMAIN, f"{entry.unique_id}_{kind}_detection"
        )
        for kind in KINDS
    }


def detection(*on: str) -> lib.Detection:
    return lib.Detection(**{kind: kind in on for kind in KINDS})


def onoff(*on: str) -> dict[str, str]:
    return {kind: STATE_ON if kind in on else STATE_OFF for kind in KINDS}


def states(hass: HomeAssistant, ids: dict[str, str]) -> dict[str, str]:
    return {kind: hass.states.get(entity_id).state for kind, entity_id in ids.items()}


async def call(hass: HomeAssistant, service: str, entity_id: str) -> None:
    await hass.services.async_call(
        SWITCH_DOMAIN, service, {ATTR_ENTITY_ID: entity_id}, blocking=True
    )


async def refresh(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()


@pytest.fixture
async def switches(
    hass: HomeAssistant,
    identified_entry: MockConfigEntry,
    mock_camera: FakeSannceCamera,
    entity_registry: er.EntityRegistry,
) -> dict[str, str]:
    mock_camera.detection = detection(*KINDS)
    await setup_integration(hass, identified_entry)
    ids = switch_ids(entity_registry, identified_entry)
    assert all(ids.values()), f"switches missing: {ids}"
    return ids


@pytest.mark.parametrize("kind", KINDS)
async def test_each_switch_reads_its_own_field(
    hass: HomeAssistant,
    identified_entry: MockConfigEntry,
    mock_camera: FakeSannceCamera,
    entity_registry: er.EntityRegistry,
    kind: str,
) -> None:
    mock_camera.detection = detection(kind)

    await setup_integration(hass, identified_entry)

    ids = switch_ids(entity_registry, identified_entry)
    assert states(hass, ids) == onoff(kind)


async def test_switches_follow_the_poll(
    hass: HomeAssistant,
    identified_entry: MockConfigEntry,
    switches: dict[str, str],
    mock_camera: FakeSannceCamera,
) -> None:
    assert states(hass, switches) == onoff(*KINDS)

    mock_camera.detection = detection("motion")
    await refresh(hass, identified_entry)

    assert states(hass, switches) == onoff("motion")

    mock_camera.detection = detection("person", "vehicle")
    await refresh(hass, identified_entry)

    assert states(hass, switches) == onoff("person", "vehicle")


@pytest.mark.parametrize("kind", KINDS)
async def test_turn_on_sets_only_its_field(
    hass: HomeAssistant,
    identified_entry: MockConfigEntry,
    switches: dict[str, str],
    mock_camera: FakeSannceCamera,
    kind: str,
) -> None:
    mock_camera.detection = detection()
    await refresh(hass, identified_entry)
    assert states(hass, switches) == onoff()

    await call(hass, SERVICE_TURN_ON, switches[kind])

    mock_camera.set_detection.assert_awaited_once_with(**{kind: True})
    assert states(hass, switches) == onoff(kind)


@pytest.mark.parametrize("kind", KINDS)
async def test_turn_off_sets_only_its_field(
    hass: HomeAssistant,
    switches: dict[str, str],
    mock_camera: FakeSannceCamera,
    kind: str,
) -> None:
    await call(hass, SERVICE_TURN_OFF, switches[kind])

    mock_camera.set_detection.assert_awaited_once_with(**{kind: False})
    assert states(hass, switches) == onoff(*(k for k in KINDS if k != kind))


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("was_on", [False, True], ids=["off", "on"])
async def test_toggle_flips_only_its_switch(
    hass: HomeAssistant,
    identified_entry: MockConfigEntry,
    switches: dict[str, str],
    mock_camera: FakeSannceCamera,
    kind: str,
    was_on: bool,
) -> None:
    mock_camera.detection = detection(*KINDS) if was_on else detection()
    await refresh(hass, identified_entry)

    await call(hass, SERVICE_TOGGLE, switches[kind])

    mock_camera.set_detection.assert_awaited_once_with(**{kind: not was_on})
    others = tuple(k for k in KINDS if k != kind)
    assert states(hass, switches) == onoff(*(others if was_on else (kind,)))


async def test_commands_refresh_the_settings(
    hass: HomeAssistant, switches: dict[str, str], mock_camera: FakeSannceCamera
) -> None:
    assert mock_camera.get_detection.await_count == 1

    await call(hass, SERVICE_TURN_OFF, switches["person"])

    assert mock_camera.get_detection.await_count == 2


async def test_state_follows_back_to_back_commands(
    hass: HomeAssistant, switches: dict[str, str]
) -> None:
    await call(hass, SERVICE_TURN_OFF, switches["person"])
    await call(hass, SERVICE_TURN_OFF, switches["vehicle"])

    assert states(hass, switches) == onoff("motion")

    await call(hass, SERVICE_TURN_ON, switches["person"])

    assert states(hass, switches) == onoff("person", "motion")


async def test_commands_run_one_at_a_time(
    hass: HomeAssistant, switches: dict[str, str], mock_camera: FakeSannceCamera
) -> None:
    started: list[dict[str, bool]] = []
    release = asyncio.Event()

    async def hold(**change: bool) -> None:
        started.append(change)
        await release.wait()

    mock_camera.set_detection.side_effect = hold
    person = hass.async_create_task(call(hass, SERVICE_TURN_OFF, switches["person"]))
    vehicle = hass.async_create_task(call(hass, SERVICE_TURN_OFF, switches["vehicle"]))
    for _ in range(10):
        await asyncio.sleep(0)

    assert started == [{"person": False}]

    release.set()
    await asyncio.gather(person, vehicle)

    assert started == [{"person": False}, {"vehicle": False}]


@pytest.mark.parametrize(
    "error",
    [
        lib.ConnectError("unreachable"),
        lib.AuthError("credentials rejected"),
        lib.ProtocolError("bad reply"),
    ],
    ids=["connect", "auth", "protocol"],
)
async def test_failed_command_raises_an_ha_error(
    hass: HomeAssistant,
    switches: dict[str, str],
    mock_camera: FakeSannceCamera,
    error: lib.SannceError,
) -> None:
    mock_camera.set_detection.side_effect = error

    with pytest.raises(HomeAssistantError, match=f"{switches['person']}: {error}"):
        await call(hass, SERVICE_TURN_OFF, switches["person"])

    assert states(hass, switches) == onoff(*KINDS)
    assert mock_camera.get_detection.await_count == 1


async def test_switches_follow_the_private_connection(
    hass: HomeAssistant, switches: dict[str, str], mock_camera: FakeSannceCamera
) -> None:
    mock_camera.set_available(False)
    await hass.async_block_till_done()

    assert states(hass, switches) == dict.fromkeys(KINDS, STATE_UNAVAILABLE)

    mock_camera.set_available(True)
    await hass.async_block_till_done()

    assert states(hass, switches) == onoff(*KINDS)


async def test_failed_poll_makes_the_switches_unavailable(
    hass: HomeAssistant,
    identified_entry: MockConfigEntry,
    switches: dict[str, str],
    mock_camera: FakeSannceCamera,
) -> None:
    working = mock_camera.get_detection.side_effect
    mock_camera.get_detection.side_effect = lib.ConnectError("unreachable")
    await refresh(hass, identified_entry)

    assert states(hass, switches) == dict.fromkeys(KINDS, STATE_UNAVAILABLE)

    mock_camera.get_detection.side_effect = working
    await refresh(hass, identified_entry)

    assert states(hass, switches) == onoff(*KINDS)


async def test_missing_detection_reads_as_unknown(
    hass: HomeAssistant,
    identified_entry: MockConfigEntry,
    switches: dict[str, str],
    mock_camera: FakeSannceCamera,
) -> None:
    mock_camera.caps = frozenset()
    await refresh(hass, identified_entry)

    assert states(hass, switches) == dict.fromkeys(KINDS, STATE_UNKNOWN)


@pytest.mark.parametrize("kind", KINDS)
async def test_no_switch_without_its_cap(
    hass: HomeAssistant,
    identified_entry: MockConfigEntry,
    mock_camera: FakeSannceCamera,
    entity_registry: er.EntityRegistry,
    kind: str,
) -> None:
    mock_camera.caps = frozenset(cap for cap in ALL_CAPS if cap != kind)

    await setup_integration(hass, identified_entry)

    ids = switch_ids(entity_registry, identified_entry)
    assert {k for k, entity_id in ids.items() if entity_id} == set(KINDS) - {kind}
    assert len(hass.states.async_entity_ids(SWITCH_DOMAIN)) == len(KINDS)


async def test_no_switches_without_any_detection_cap(
    hass: HomeAssistant,
    identified_entry: MockConfigEntry,
    mock_camera: FakeSannceCamera,
    entity_registry: er.EntityRegistry,
) -> None:
    mock_camera.caps = frozenset({"light_mode", "speaker", "white_light"})

    await setup_integration(hass, identified_entry)

    assert not any(switch_ids(entity_registry, identified_entry).values())
    assert hass.states.async_entity_ids(SWITCH_DOMAIN) == []


async def test_switches_are_config_entities(
    switches: dict[str, str], entity_registry: er.EntityRegistry
) -> None:
    assert {
        entity_registry.async_get(entity_id).entity_category
        for entity_id in switches.values()
    } == {EntityCategory.CONFIG}


async def test_switches_join_the_camera_device(
    hass: HomeAssistant,
    identified_entry: MockConfigEntry,
    switches: dict[str, str],
    entity_registry: er.EntityRegistry,
    device_registry: dr.DeviceRegistry,
) -> None:
    (device,) = dr.async_entries_for_config_entry(
        device_registry, identified_entry.entry_id
    )

    assert {
        kind: hass.states.get(entity_id).attributes[ATTR_FRIENDLY_NAME]
        for kind, entity_id in switches.items()
    } == {kind: f"I91FW {name}" for kind, name in NAMES.items()}
    assert {entity_registry.async_get(e).device_id for e in switches.values()} == {
        device.id
    }


async def test_every_switch_has_a_translated_name(
    hass: HomeAssistant, switches: dict[str, str]
) -> None:
    translations = await translation.async_get_translations(
        hass, "en", "entity", [DOMAIN]
    )

    assert {
        kind: translations[f"component.{DOMAIN}.entity.switch.{kind}_detection.name"]
        for kind in KINDS
    } == NAMES


async def test_siren_on_event_is_a_config_switch_that_starts_off(
    hass: HomeAssistant,
    identified_entry: MockConfigEntry,
    mock_camera: FakeSannceCamera,
    entity_registry: er.EntityRegistry,
) -> None:
    await setup_integration(hass, identified_entry)
    entity_id = "switch.i91fw_siren_on_event"

    assert hass.states.get(entity_id).state == STATE_OFF
    assert entity_registry.async_get(entity_id).entity_category is EntityCategory.CONFIG
    mock_camera.set_siren_on_event.assert_not_awaited()


async def test_siren_on_event_switch_reaches_the_camera(
    hass: HomeAssistant,
    identified_entry: MockConfigEntry,
    mock_camera: FakeSannceCamera,
) -> None:
    await setup_integration(hass, identified_entry)
    entity_id = "switch.i91fw_siren_on_event"

    await call(hass, SERVICE_TURN_ON, entity_id)

    mock_camera.set_siren_on_event.assert_awaited_once_with(True)
    assert hass.states.get(entity_id).state == STATE_ON

    await call(hass, SERVICE_TURN_OFF, entity_id)

    mock_camera.set_siren_on_event.assert_awaited_with(False)
    assert hass.states.get(entity_id).state == STATE_OFF


async def test_siren_on_event_follows_the_poll(
    hass: HomeAssistant,
    identified_entry: MockConfigEntry,
    mock_camera: FakeSannceCamera,
) -> None:
    await setup_integration(hass, identified_entry)
    entity_id = "switch.i91fw_siren_on_event"

    mock_camera.siren_on_event = True
    await refresh(hass, identified_entry)

    assert hass.states.get(entity_id).state == STATE_ON


async def test_siren_on_event_command_failure_raises_an_ha_error(
    hass: HomeAssistant,
    identified_entry: MockConfigEntry,
    mock_camera: FakeSannceCamera,
) -> None:
    await setup_integration(hass, identified_entry)
    entity_id = "switch.i91fw_siren_on_event"
    mock_camera.set_siren_on_event.side_effect = lib.ProtocolError("bad reply")

    with pytest.raises(HomeAssistantError, match=f"{entity_id}: bad reply"):
        await call(hass, SERVICE_TURN_ON, entity_id)

    assert hass.states.get(entity_id).state == STATE_OFF


async def test_no_siren_on_event_switch_without_its_cap(
    hass: HomeAssistant,
    identified_entry: MockConfigEntry,
    mock_camera: FakeSannceCamera,
    entity_registry: er.EntityRegistry,
) -> None:
    mock_camera.caps = frozenset(cap for cap in ALL_CAPS if cap != "siren_on_event")

    await setup_integration(hass, identified_entry)

    assert (
        entity_registry.async_get_entity_id(
            SWITCH_DOMAIN, DOMAIN, f"{identified_entry.unique_id}_siren_on_event"
        )
        is None
    )
    assert len(hass.states.async_entity_ids(SWITCH_DOMAIN)) == len(KINDS)


async def test_siren_on_event_switch_has_a_translated_name(
    hass: HomeAssistant,
    identified_entry: MockConfigEntry,
    mock_camera: FakeSannceCamera,
) -> None:
    await setup_integration(hass, identified_entry)
    translations = await translation.async_get_translations(
        hass, "en", "entity", [DOMAIN]
    )

    assert (
        translations[f"component.{DOMAIN}.entity.switch.siren_on_event.name"]
        == "Siren on event"
    )
    assert (
        hass.states.get("switch.i91fw_siren_on_event").attributes[ATTR_FRIENDLY_NAME]
        == "I91FW Siren on event"
    )
