from unittest.mock import patch

from homeassistant.components.camera import (
    CameraEntityFeature,
    CameraState,
    async_get_image,
    async_get_stream_source,
)
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import (
    ATTR_FRIENDLY_NAME,
    ATTR_SUPPORTED_FEATURES,
    CONF_HOST,
    CONF_PASSWORD,
    CONF_USERNAME,
    STATE_UNAVAILABLE,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC
from homeassistant.helpers.entity_registry import RegistryEntryDisabler
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.sannce import lib
from custom_components.sannce.const import DOMAIN

from . import HOST, PASSWORD, USERNAME, setup_integration
from .conftest import FakeSannceCamera

SUB_URL = f"rtsp://{USERNAME}:{PASSWORD}@{HOST}:554/1/2"
MAIN_URL = f"rtsp://{USERNAME}:{PASSWORD}@{HOST}:554/1/1"


def camera_id(registry: er.EntityRegistry, entry: MockConfigEntry, key: str) -> str:
    entity_id = registry.async_get_entity_id(
        "camera", DOMAIN, f"{entry.unique_id}_{key}"
    )
    assert entity_id, f"no {key} camera is registered"
    return entity_id


async def test_sub_camera_is_enabled_and_main_is_not(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_camera: FakeSannceCamera,
    entity_registry: er.EntityRegistry,
) -> None:
    await setup_integration(hass, mock_config_entry)

    sub_id = camera_id(entity_registry, mock_config_entry, "sub")
    main_id = camera_id(entity_registry, mock_config_entry, "main")
    assert entity_registry.async_get(sub_id).disabled_by is None
    assert (
        entity_registry.async_get(main_id).disabled_by
        is RegistryEntryDisabler.INTEGRATION
    )
    assert hass.states.get(sub_id).state == CameraState.IDLE
    assert hass.states.get(main_id) is None


async def test_sub_stream_source_is_the_sub_rtsp_url(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_camera: FakeSannceCamera,
    entity_registry: er.EntityRegistry,
) -> None:
    await setup_integration(hass, mock_config_entry)

    sub_id = camera_id(entity_registry, mock_config_entry, "sub")
    assert await async_get_stream_source(hass, sub_id) == SUB_URL


async def test_main_camera_streams_the_main_rtsp_url_once_enabled(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_camera: FakeSannceCamera,
    entity_registry: er.EntityRegistry,
) -> None:
    await setup_integration(hass, mock_config_entry)
    main_id = camera_id(entity_registry, mock_config_entry, "main")

    entity_registry.async_update_entity(main_id, disabled_by=None)
    await hass.config_entries.async_reload(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.LOADED
    assert hass.states.get(main_id).state == CameraState.IDLE
    assert await async_get_stream_source(hass, main_id) == MAIN_URL


async def test_cameras_support_streaming(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_camera: FakeSannceCamera,
    entity_registry: er.EntityRegistry,
) -> None:
    await setup_integration(hass, mock_config_entry)

    state = hass.states.get(camera_id(entity_registry, mock_config_entry, "sub"))
    assert state.attributes[ATTR_SUPPORTED_FEATURES] == CameraEntityFeature.STREAM


async def test_snapshot_comes_from_the_stream(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_camera: FakeSannceCamera,
    entity_registry: er.EntityRegistry,
) -> None:
    await setup_integration(hass, mock_config_entry)
    sub_id = camera_id(entity_registry, mock_config_entry, "sub")

    with patch(
        "homeassistant.components.camera.async_get_stream_image",
        return_value=b"jpeg",
    ) as stream_image:
        image = await async_get_image(hass, sub_id)

    assert image.content == b"jpeg"
    stream_image.assert_awaited_once()


async def test_camera_names_are_translated(
    hass: HomeAssistant,
    identified_entry: MockConfigEntry,
    mock_camera: FakeSannceCamera,
    entity_registry: er.EntityRegistry,
) -> None:
    await setup_integration(hass, identified_entry)

    sub_id = camera_id(entity_registry, identified_entry, "sub")
    main_id = camera_id(entity_registry, identified_entry, "main")
    assert hass.states.get(sub_id).attributes[ATTR_FRIENDLY_NAME] == "I91FW Sub stream"
    assert entity_registry.async_get(sub_id).original_name == "Sub stream"
    assert entity_registry.async_get(main_id).original_name == "Main stream"


async def test_cameras_share_one_device_per_entry(
    hass: HomeAssistant,
    identified_entry: MockConfigEntry,
    mock_camera: FakeSannceCamera,
    entity_registry: er.EntityRegistry,
    device_registry: dr.DeviceRegistry,
) -> None:
    mock_camera.info = lib.CameraInfo(firmware="2.4.1")

    await setup_integration(hass, identified_entry)

    devices = dr.async_entries_for_config_entry(
        device_registry, identified_entry.entry_id
    )
    assert len(devices) == 1
    device = devices[0]
    assert device.identifiers == {(DOMAIN, "SN123456")}
    assert device.connections == {(CONNECTION_NETWORK_MAC, "aa:bb:cc:dd:ee:ff")}
    assert (
        device.manufacturer,
        device.name,
        device.model,
        device.serial_number,
        device.sw_version,
    ) == ("SANNCE", "I91FW", "I91FW", "SN123456", "2.4.1")
    for key in ("sub", "main"):
        entry = entity_registry.async_get(
            camera_id(entity_registry, identified_entry, key)
        )
        assert entry.device_id == device.id


async def test_device_when_only_the_host_is_known(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_camera: FakeSannceCamera,
    device_registry: dr.DeviceRegistry,
) -> None:
    await setup_integration(hass, mock_config_entry)

    (device,) = dr.async_entries_for_config_entry(
        device_registry, mock_config_entry.entry_id
    )
    assert device.identifiers == {(DOMAIN, HOST)}
    assert (device.name, device.model, device.serial_number) == (HOST, None, None)
    assert device.connections == set()
    assert device.sw_version == "1.0.0"


async def test_each_entry_gets_its_own_device_and_cameras(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_camera: FakeSannceCamera,
    entity_registry: er.EntityRegistry,
    device_registry: dr.DeviceRegistry,
) -> None:
    other = MockConfigEntry(
        domain=DOMAIN,
        title="192.168.1.11",
        unique_id="192.168.1.11",
        data={
            CONF_HOST: "192.168.1.11",
            CONF_USERNAME: USERNAME,
            CONF_PASSWORD: PASSWORD,
        },
    )

    await setup_integration(hass, mock_config_entry)
    await setup_integration(hass, other)

    first = camera_id(entity_registry, mock_config_entry, "sub")
    second = camera_id(entity_registry, other, "sub")
    (first_device,) = dr.async_entries_for_config_entry(
        device_registry, mock_config_entry.entry_id
    )
    (second_device,) = dr.async_entries_for_config_entry(
        device_registry, other.entry_id
    )
    assert first != second
    assert entity_registry.async_get(first).device_id == first_device.id
    assert entity_registry.async_get(second).device_id == second_device.id
    assert first_device.id != second_device.id


async def test_cameras_follow_the_private_connection(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_camera: FakeSannceCamera,
    entity_registry: er.EntityRegistry,
) -> None:
    await setup_integration(hass, mock_config_entry)
    sub_id = camera_id(entity_registry, mock_config_entry, "sub")

    mock_camera.set_available(False)
    await hass.async_block_till_done()
    assert hass.states.get(sub_id).state == STATE_UNAVAILABLE

    mock_camera.set_available(True)
    await hass.async_block_till_done()
    assert hass.states.get(sub_id).state == CameraState.IDLE


async def test_failed_settings_poll_keeps_cameras_available(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_camera: FakeSannceCamera,
    entity_registry: er.EntityRegistry,
) -> None:
    await setup_integration(hass, mock_config_entry)
    sub_id = camera_id(entity_registry, mock_config_entry, "sub")
    mock_camera.get_light.side_effect = lib.ConnectError("unreachable")

    await mock_config_entry.runtime_data.async_refresh()
    await hass.async_block_till_done()

    assert mock_config_entry.runtime_data.last_update_success is False
    assert hass.states.get(sub_id).state == CameraState.IDLE
