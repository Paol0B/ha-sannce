import logging

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

KINDS = ("motion", "person", "vehicle", "intrusion", "line", "tamper", "video_loss")
UNGATED = ("intrusion", "line", "tamper", "video_loss")
INTERCOM = "binary_sensor.i91fw_intercom"


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


def on_only(*kinds: str) -> dict[str, str]:
    return {kind: STATE_ON if kind in kinds else STATE_OFF for kind in KINDS}


async def push(
    hass: HomeAssistant,
    camera: FakeSannceCamera,
    kind: str,
    active: bool,
    channel: int = 0,
) -> None:
    camera.emit(lib.Event(kind, active, channel))
    await hass.async_block_till_done()


async def refresh(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()


@pytest.fixture
async def sensors(
    hass: HomeAssistant,
    identified_entry: MockConfigEntry,
    mock_camera: FakeSannceCamera,
    entity_registry: er.EntityRegistry,
    entity_registry_enabled_by_default: None,
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


@pytest.mark.parametrize(
    ("kind", "turned_on"),
    [
        ("motion", ("motion", "person")),
        ("vehicle", ("vehicle", "motion")),
        ("intrusion", ("intrusion",)),
        ("line", ("line",)),
        ("tamper", ("tamper",)),
        ("video_loss", ("video_loss",)),
    ],
)
async def test_each_kind_drives_its_own_sensors(
    hass: HomeAssistant,
    sensors: dict[str, str],
    mock_camera: FakeSannceCamera,
    kind: str,
    turned_on: tuple[str, ...],
) -> None:
    await push(hass, mock_camera, kind, True)

    assert states(hass, sensors) == on_only(*turned_on)

    await push(hass, mock_camera, kind, False)

    assert states(hass, sensors) == dict.fromkeys(KINDS, STATE_OFF)


async def test_motiondetect_turns_on_person_and_motion(
    hass: HomeAssistant, sensors: dict[str, str], mock_camera: FakeSannceCamera
) -> None:
    await push(hass, mock_camera, "motion", True)

    assert hass.states.get("binary_sensor.i91fw_person").state == STATE_ON
    assert hass.states.get("binary_sensor.i91fw_motion").state == STATE_ON
    assert hass.states.get("binary_sensor.i91fw_vehicle").state == STATE_OFF


async def test_a_vehicle_turns_on_vehicle_and_motion_only(
    hass: HomeAssistant, sensors: dict[str, str], mock_camera: FakeSannceCamera
) -> None:
    await push(hass, mock_camera, "vehicle", True)

    assert hass.states.get("binary_sensor.i91fw_vehicle").state == STATE_ON
    assert hass.states.get("binary_sensor.i91fw_motion").state == STATE_ON
    assert hass.states.get("binary_sensor.i91fw_person").state == STATE_OFF


async def test_motion_stays_on_until_every_kind_stops(
    hass: HomeAssistant, sensors: dict[str, str], mock_camera: FakeSannceCamera
) -> None:
    await push(hass, mock_camera, "motion", True)
    await push(hass, mock_camera, "vehicle", True)
    await push(hass, mock_camera, "motion", False)

    assert states(hass, sensors) == on_only("motion", "vehicle")

    await push(hass, mock_camera, "vehicle", False)

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


async def test_person_is_unavailable_while_all_motion_is_on(
    hass: HomeAssistant,
    identified_entry: MockConfigEntry,
    mock_camera: FakeSannceCamera,
    entity_registry_enabled_by_default: None,
) -> None:
    mock_camera.detection = lib.Detection(
        person=True, vehicle=True, motion=True, sensitivity=76
    )

    await setup_integration(hass, identified_entry)

    assert hass.states.get("binary_sensor.i91fw_person").state == STATE_UNAVAILABLE
    assert hass.states.get("binary_sensor.i91fw_motion").state == STATE_OFF


async def test_person_returns_when_all_motion_is_switched_off(
    hass: HomeAssistant,
    identified_entry: MockConfigEntry,
    sensors: dict[str, str],
    mock_camera: FakeSannceCamera,
) -> None:
    mock_camera.detection = lib.Detection(
        person=True, vehicle=True, motion=True, sensitivity=76
    )
    await refresh(hass, identified_entry)

    assert hass.states.get("binary_sensor.i91fw_person").state == STATE_UNAVAILABLE

    mock_camera.detection = lib.Detection(
        person=True, vehicle=True, motion=False, sensitivity=76
    )
    await refresh(hass, identified_entry)

    assert hass.states.get("binary_sensor.i91fw_person").state == STATE_OFF


async def test_all_motion_leaves_the_other_sensors_available(
    hass: HomeAssistant,
    identified_entry: MockConfigEntry,
    sensors: dict[str, str],
    mock_camera: FakeSannceCamera,
) -> None:
    mock_camera.detection = lib.Detection(
        person=True, vehicle=True, motion=True, sensitivity=76
    )
    await refresh(hass, identified_entry)
    await push(hass, mock_camera, "motion", True)

    assert states(hass, sensors) == on_only("motion") | {"person": STATE_UNAVAILABLE}


@pytest.mark.parametrize(
    ("caps", "expected"),
    [
        (ALL_CAPS, (*KINDS, "intercom")),
        (("motion",), ("motion", *UNGATED)),
        (("person",), ("motion", "person", *UNGATED)),
        (("vehicle",), ("motion", "vehicle", *UNGATED)),
        (("white_light", "speaker"), (*UNGATED, "intercom")),
        (("white_light",), UNGATED),
        ((), UNGATED),
    ],
    ids=["all", "motion", "person", "vehicle", "speaker_only", "no_speaker", "none"],
)
async def test_detection_sensors_follow_the_camera_caps(
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
        ("person", BinarySensorDeviceClass.MOTION, "I91FW Person"),
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
    mock_camera.get_floodlight.side_effect = lib.ConnectError("unreachable")

    await identified_entry.runtime_data.async_refresh()
    await hass.async_block_till_done()

    assert identified_entry.runtime_data.last_update_success is False
    assert states(hass, sensors) == on_only("motion", "person")


async def test_settings_update_keeps_the_event_state(
    hass: HomeAssistant,
    identified_entry: MockConfigEntry,
    sensors: dict[str, str],
    mock_camera: FakeSannceCamera,
) -> None:
    await push(hass, mock_camera, "motion", True)
    mock_camera.volume = 30

    await identified_entry.runtime_data.async_refresh()
    await hass.async_block_till_done()

    assert identified_entry.runtime_data.data.volume == 30
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


async def test_rule_sensors_start_disabled(
    hass: HomeAssistant,
    identified_entry: MockConfigEntry,
    mock_camera: FakeSannceCamera,
    entity_registry: er.EntityRegistry,
) -> None:
    await setup_integration(hass, identified_entry)

    ids = {kind: sensor_id(entity_registry, identified_entry, kind) for kind in KINDS}
    disabled = {
        kind
        for kind, entity_id in ids.items()
        if entity_registry.async_get(entity_id).disabled_by
        is er.RegistryEntryDisabler.INTEGRATION
    }
    shown = {kind for kind, entity_id in ids.items() if hass.states.get(entity_id)}
    assert disabled == set(UNGATED)
    assert shown == {"motion", "person", "vehicle"}


@pytest.fixture
async def intercom(
    hass: HomeAssistant,
    identified_entry: MockConfigEntry,
    mock_camera: FakeSannceCamera,
    entity_registry: er.EntityRegistry,
) -> str:
    await setup_integration(hass, identified_entry)
    return sensor_id(entity_registry, identified_entry, "intercom")


async def test_intercom_is_off_until_a_talk_owns_the_speaker(
    hass: HomeAssistant, intercom: str, mock_camera: FakeSannceCamera
) -> None:
    assert intercom == INTERCOM
    assert hass.states.get(INTERCOM).state == STATE_OFF

    mock_camera.speaker.set_owner("talk")
    await hass.async_block_till_done()

    assert hass.states.get(INTERCOM).state == STATE_ON

    mock_camera.speaker.set_owner(None)
    await hass.async_block_till_done()

    assert hass.states.get(INTERCOM).state == STATE_OFF


async def test_a_play_does_not_turn_the_intercom_on(
    hass: HomeAssistant, intercom: str, mock_camera: FakeSannceCamera
) -> None:
    mock_camera.speaker.set_owner("play")
    await hass.async_block_till_done()

    assert hass.states.get(INTERCOM).state == STATE_OFF


async def test_intercom_follows_camera_availability(
    hass: HomeAssistant, intercom: str, mock_camera: FakeSannceCamera
) -> None:
    mock_camera.speaker.set_owner("talk")
    mock_camera.set_available(False)
    await hass.async_block_till_done()

    assert hass.states.get(INTERCOM).state == STATE_UNAVAILABLE

    mock_camera.set_available(True)
    await hass.async_block_till_done()

    assert hass.states.get(INTERCOM).state == STATE_ON


async def test_intercom_name_and_registry_entry(
    hass: HomeAssistant,
    identified_entry: MockConfigEntry,
    intercom: str,
    entity_registry: er.EntityRegistry,
) -> None:
    entry = entity_registry.async_get(INTERCOM)

    assert hass.states.get(INTERCOM).attributes[ATTR_FRIENDLY_NAME] == "I91FW Intercom"
    assert ATTR_DEVICE_CLASS not in hass.states.get(INTERCOM).attributes
    assert entry.unique_id == "SN123456_intercom"
    assert entry.translation_key == "intercom"
    assert entry.entity_category is None
    assert entry.disabled_by is None


async def test_no_intercom_without_a_speaker(
    hass: HomeAssistant,
    identified_entry: MockConfigEntry,
    mock_camera: FakeSannceCamera,
    entity_registry: er.EntityRegistry,
) -> None:
    mock_camera.caps = frozenset(("siren", "motion"))

    await setup_integration(hass, identified_entry)

    assert hass.states.get(INTERCOM) is None
    assert "intercom" not in registered_kinds(entity_registry, identified_entry)


async def test_unload_stops_listening_to_the_speaker(
    hass: HomeAssistant,
    identified_entry: MockConfigEntry,
    intercom: str,
    mock_camera: FakeSannceCamera,
) -> None:
    assert mock_camera.speaker.subscribers

    assert await hass.config_entries.async_unload(identified_entry.entry_id)
    await hass.async_block_till_done()
    mock_camera.speaker.set_owner("talk")
    await hass.async_block_till_done()

    assert mock_camera.speaker.subscribers == []
    assert hass.states.get(INTERCOM).state == STATE_UNAVAILABLE


async def test_unloading_during_a_talk_leaves_no_error(
    hass: HomeAssistant,
    identified_entry: MockConfigEntry,
    intercom: str,
    mock_camera: FakeSannceCamera,
    caplog: pytest.LogCaptureFixture,
) -> None:
    mock_camera.speaker.set_owner("talk")
    await hass.async_block_till_done()

    assert await hass.config_entries.async_unload(identified_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_camera.speaker.owner is None
    assert hass.states.get(INTERCOM).state == STATE_UNAVAILABLE
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]
