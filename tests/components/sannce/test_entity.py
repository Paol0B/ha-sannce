import pytest
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC, DeviceInfo
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity import EntityDescription
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.sannce import lib
from custom_components.sannce.const import DOMAIN
from custom_components.sannce.coordinator import SannceCoordinator
from custom_components.sannce.entity import SannceEntity, SannceSettingsEntity

from . import HOST, PASSWORD, USERNAME, setup_integration
from .conftest import FakeSannceCamera

DESCRIPTION = EntityDescription(key="probe")


@pytest.mark.parametrize(
    ("connected", "polled", "push_available", "settings_available"),
    [
        (True, True, True, True),
        (True, False, True, False),
        (False, True, False, False),
        (False, False, False, False),
    ],
    ids=["all_up", "poll_failed", "disconnected", "both_down"],
)
async def test_availability_rules(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_camera: FakeSannceCamera,
    connected: bool,
    polled: bool,
    push_available: bool,
    settings_available: bool,
) -> None:
    coordinator = SannceCoordinator(hass, mock_config_entry, mock_camera)
    coordinator.connected = connected
    coordinator.last_update_success = polled

    assert SannceEntity(coordinator, DESCRIPTION).available is push_available
    assert (
        SannceSettingsEntity(coordinator, DESCRIPTION).available is settings_available
    )


async def test_unique_id_joins_entry_unique_id_and_key(
    hass: HomeAssistant,
    identified_entry: MockConfigEntry,
    mock_camera: FakeSannceCamera,
) -> None:
    coordinator = SannceCoordinator(hass, identified_entry, mock_camera)

    assert SannceEntity(coordinator, DESCRIPTION).unique_id == "SN123456_probe"


async def test_entry_without_unique_id_falls_back_to_entry_id(
    hass: HomeAssistant, mock_camera: FakeSannceCamera
) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_HOST: HOST, CONF_USERNAME: USERNAME, CONF_PASSWORD: PASSWORD},
    )

    entity = SannceEntity(SannceCoordinator(hass, entry, mock_camera), DESCRIPTION)

    assert entity.unique_id == f"{entry.entry_id}_probe"
    assert entity.device_info["identifiers"] == {(DOMAIN, entry.entry_id)}


async def test_device_info_uses_everything_known(
    hass: HomeAssistant,
    identified_entry: MockConfigEntry,
    mock_camera: FakeSannceCamera,
) -> None:
    mock_camera.info = lib.CameraInfo(firmware="2.4.1")

    entity = SannceEntity(
        SannceCoordinator(hass, identified_entry, mock_camera), DESCRIPTION
    )

    assert entity.device_info == DeviceInfo(
        identifiers={(DOMAIN, "SN123456")},
        connections={(CONNECTION_NETWORK_MAC, "aa:bb:cc:dd:ee:ff")},
        manufacturer="SANNCE",
        name="I91FW",
        model="I91FW",
        serial_number="SN123456",
        sw_version="2.4.1",
    )


async def test_device_info_when_only_the_host_is_known(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_camera: FakeSannceCamera,
) -> None:
    mock_camera.info = lib.CameraInfo()

    entity = SannceEntity(
        SannceCoordinator(hass, mock_config_entry, mock_camera), DESCRIPTION
    )

    assert entity.device_info == DeviceInfo(
        identifiers={(DOMAIN, HOST)},
        connections=set(),
        manufacturer="SANNCE",
        name=HOST,
        model=None,
        serial_number=None,
        sw_version=None,
    )


async def test_reolink_style_entity_ids(
    hass: HomeAssistant,
    identified_entry: MockConfigEntry,
    mock_camera: FakeSannceCamera,
    entity_registry: er.EntityRegistry,
) -> None:
    await setup_integration(hass, identified_entry)

    ids = {
        entry.unique_id.removeprefix("SN123456_"): entry.entity_id
        for entry in er.async_entries_for_config_entry(
            entity_registry, identified_entry.entry_id
        )
    }

    assert ids["main"] == "camera.i91fw_clear"
    assert ids["sub"] == "camera.i91fw_fluent"
    assert ids["person"] == "binary_sensor.i91fw_person"
    assert ids["motion"] == "binary_sensor.i91fw_motion"
    assert ids["vehicle"] == "binary_sensor.i91fw_vehicle"
