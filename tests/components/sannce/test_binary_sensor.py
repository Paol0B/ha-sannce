import pytest
from homeassistant.components.binary_sensor import BinarySensorDeviceClass
from homeassistant.const import (
    ATTR_DEVICE_CLASS,
    ATTR_FRIENDLY_NAME,
    STATE_OFF,
    STATE_ON,
    STATE_UNAVAILABLE,
    EntityCategory,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.sannce import lib
from custom_components.sannce.const import DOMAIN

from . import setup_integration
from .conftest import ALL_CAPS, FakeSannceCamera

KINDS = ("motion", "vehicle", "intrusion", "line", "tamper", "video_loss")
UNGATED = ("intrusion", "line", "tamper", "video_loss")


def sensor_id(registry: er.EntityRegistry, entry: MockConfigEntry, key: str) -> str:
    entity_id = registry.async_get_entity_id(
        "binary_sensor", DOMAIN, f"{entry.unique_id}_{key}"
    )
    assert entity_id, f"no {key} binary sensor is registered"
    return entity_id


def registered_kinds(registry: er.EntityRegistry, entry: MockConfigEntry) -> set[str]:
    prefix = f"{entry.unique_id}_"
    return {
        item.unique_id.removeprefix(prefix)
        for item in er.async_entries_for_config_entry(registry, entry.entry_id)
        if item.domain == "binary_sensor"
    }


def states(hass: HomeAssistant, sensors: dict[str, str]) -> dict[str, str]:
    return {
        kind: hass.states.get(entity_id).state for kind, entity_id in sensors.items()
    }


async def push(
    hass: HomeAssistant,
    camera: FakeSannceCamera,
    kind: str,
    active: bool,
    channel: int = 0,
) -> None:
    camera.emit(lib.Event(kind, active, channel))
    await hass.async_block_till_done()


@pytest.fixture
async def sensors(
    hass: HomeAssistant,
    identified_entry: MockConfigEntry,
    mock_camera: FakeSannceCamera,
    entity_registry: er.EntityRegistry,
) -> dict[str, str]:
    await setup_integration(hass, identified_entry)
    return {kind: sensor_id(entity_registry, identified_entry, kind) for kind in KINDS}


async def test_sensors_start_clear(
    hass: HomeAssistant, sensors: dict[str, str]
) -> None:
    assert states(hass, sensors) == dict.fromkeys(KINDS, STATE_OFF)


async def test_motion_start_turns_the_sensor_on(
    hass: HomeAssistant, sensors: dict[str, str], mock_camera: FakeSannceCamera
) -> None:
    await push(hass, mock_camera, "motion", True)

    assert hass.states.get(sensors["motion"]).state == STATE_ON


async def test_stop_event_turns_the_sensor_off(
    hass: HomeAssistant, sensors: dict[str, str], mock_camera: FakeSannceCamera
) -> None:
    await push(hass, mock_camera, "motion", True)
    await push(hass, mock_camera, "motion", False)

    assert hass.states.get(sensors["motion"]).state == STATE_OFF


@pytest.mark.parametrize("kind", KINDS)
async def test_each_kind_drives_only_its_own_sensor(
    hass: HomeAssistant,
    sensors: dict[str, str],
    mock_camera: FakeSannceCamera,
    kind: str,
) -> None:
    await push(hass, mock_camera, kind, True)

    assert states(hass, sensors) == {
        other: STATE_ON if other == kind else STATE_OFF for other in KINDS
    }

    await push(hass, mock_camera, kind, False)

    assert states(hass, sensors) == dict.fromkeys(KINDS, STATE_OFF)


async def test_one_stop_ends_repeated_starts(
    hass: HomeAssistant, sensors: dict[str, str], mock_camera: FakeSannceCamera
) -> None:
    await push(hass, mock_camera, "motion", True)
    await push(hass, mock_camera, "motion", True)
    await push(hass, mock_camera, "motion", False)

    assert hass.states.get(sensors["motion"]).state == STATE_OFF


async def test_sensor_stays_on_while_any_channel_is_active(
    hass: HomeAssistant, sensors: dict[str, str], mock_camera: FakeSannceCamera
) -> None:
    await push(hass, mock_camera, "motion", True, channel=0)
    await push(hass, mock_camera, "motion", True, channel=1)
    await push(hass, mock_camera, "motion", False, channel=0)

    assert hass.states.get(sensors["motion"]).state == STATE_ON

    await push(hass, mock_camera, "motion", False, channel=1)

    assert hass.states.get(sensors["motion"]).state == STATE_OFF


async def test_there_is_no_person_sensor(
    hass: HomeAssistant,
    identified_entry: MockConfigEntry,
    sensors: dict[str, str],
    entity_registry: er.EntityRegistry,
    mock_camera: FakeSannceCamera,
) -> None:
    await push(hass, mock_camera, "person", True)

    assert registered_kinds(entity_registry, identified_entry) == set(KINDS)
    assert states(hass, sensors) == dict.fromkeys(KINDS, STATE_OFF)
    assert len(hass.states.async_entity_ids("binary_sensor")) == len(KINDS)


@pytest.mark.parametrize(
    ("caps", "expected"),
    [
        (ALL_CAPS, KINDS),
        (("motion",), ("motion", *UNGATED)),
        (("person",), ("motion", *UNGATED)),
        (("vehicle",), ("vehicle", *UNGATED)),
        (("white_light", "talk"), UNGATED),
        ((), UNGATED),
    ],
    ids=["all", "motion", "person", "vehicle", "no_detection", "none"],
)
async def test_motion_and_vehicle_sensors_follow_the_camera_caps(
    hass: HomeAssistant,
    identified_entry: MockConfigEntry,
    mock_camera: FakeSannceCamera,
    entity_registry: er.EntityRegistry,
    caps: tuple[str, ...],
    expected: tuple[str, ...],
) -> None:
    mock_camera.caps = frozenset(caps)

    await setup_integration(hass, identified_entry)

    assert registered_kinds(entity_registry, identified_entry) == set(expected)


@pytest.mark.parametrize(
    ("kind", "device_class", "name"),
    [
        ("motion", BinarySensorDeviceClass.MOTION, "I91FW Motion"),
        ("vehicle", BinarySensorDeviceClass.MOTION, "I91FW Vehicle"),
        ("intrusion", BinarySensorDeviceClass.MOTION, "I91FW Intrusion"),
        ("line", BinarySensorDeviceClass.MOTION, "I91FW Line crossing"),
        ("tamper", BinarySensorDeviceClass.TAMPER, "I91FW Tamper"),
        ("video_loss", BinarySensorDeviceClass.PROBLEM, "I91FW Video loss"),
    ],
)
async def test_sensor_device_class_and_name(
    hass: HomeAssistant,
    sensors: dict[str, str],
    kind: str,
    device_class: BinarySensorDeviceClass,
    name: str,
) -> None:
    state = hass.states.get(sensors[kind])

    assert state.attributes[ATTR_DEVICE_CLASS] == device_class
    assert state.attributes[ATTR_FRIENDLY_NAME] == name


async def test_only_video_loss_is_diagnostic(
    sensors: dict[str, str], entity_registry: er.EntityRegistry
) -> None:
    categories = {
        kind: entity_registry.async_get(entity_id).entity_category
        for kind, entity_id in sensors.items()
    }

    assert categories == {
        kind: EntityCategory.DIAGNOSTIC if kind == "video_loss" else None
        for kind in KINDS
    }


async def test_sensors_join_the_camera_device(
    hass: HomeAssistant,
    identified_entry: MockConfigEntry,
    sensors: dict[str, str],
    entity_registry: er.EntityRegistry,
    device_registry: dr.DeviceRegistry,
) -> None:
    (device,) = dr.async_entries_for_config_entry(
        device_registry, identified_entry.entry_id
    )

    for entity_id in sensors.values():
        assert entity_registry.async_get(entity_id).device_id == device.id


async def test_entities_unavailable_on_disconnect(
    hass: HomeAssistant, sensors: dict[str, str], mock_camera: FakeSannceCamera
) -> None:
    await push(hass, mock_camera, "motion", True)

    mock_camera.set_available(False)
    await hass.async_block_till_done()

    assert states(hass, sensors) == dict.fromkeys(KINDS, STATE_UNAVAILABLE)

    await push(hass, mock_camera, "motion", False)

    assert states(hass, sensors) == dict.fromkeys(KINDS, STATE_UNAVAILABLE)

    mock_camera.set_available(True)
    await hass.async_block_till_done()

    assert states(hass, sensors) == dict.fromkeys(KINDS, STATE_OFF)

    await push(hass, mock_camera, "motion", True)

    assert hass.states.get(sensors["motion"]).state == STATE_ON


async def test_failed_settings_poll_keeps_sensors_available(
    hass: HomeAssistant,
    identified_entry: MockConfigEntry,
    sensors: dict[str, str],
    mock_camera: FakeSannceCamera,
) -> None:
    await push(hass, mock_camera, "motion", True)
    mock_camera.get_light.side_effect = lib.ConnectError("unreachable")

    await identified_entry.runtime_data.async_refresh()
    await hass.async_block_till_done()

    assert identified_entry.runtime_data.last_update_success is False
    assert states(hass, sensors) == {
        kind: STATE_ON if kind == "motion" else STATE_OFF for kind in KINDS
    }


async def test_settings_update_keeps_the_event_state(
    hass: HomeAssistant,
    identified_entry: MockConfigEntry,
    sensors: dict[str, str],
    mock_camera: FakeSannceCamera,
) -> None:
    await push(hass, mock_camera, "motion", True)
    mock_camera.light_on = True

    await identified_entry.runtime_data.async_refresh()
    await hass.async_block_till_done()

    assert identified_entry.runtime_data.data.light is True
    assert hass.states.get(sensors["motion"]).state == STATE_ON


async def test_removed_sensor_stops_listening_for_events(
    hass: HomeAssistant,
    identified_entry: MockConfigEntry,
    sensors: dict[str, str],
    entity_registry: er.EntityRegistry,
) -> None:
    coordinator = identified_entry.runtime_data
    listening = len(coordinator._event_listeners)

    entity_registry.async_remove(sensors["motion"])
    await hass.async_block_till_done()

    assert len(coordinator._event_listeners) == listening - 1
