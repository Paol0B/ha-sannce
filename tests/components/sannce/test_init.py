from unittest.mock import MagicMock

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.sannce import lib
from custom_components.sannce.const import (
    CONF_HTTP_PORT,
    CONF_NVS_PORT,
    CONF_RTSP_PORT,
    DOMAIN,
)

from . import HOST, PASSWORD, USERNAME, setup_integration
from .conftest import FakeSannceCamera


async def test_setup_and_unload_entry(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_camera_class: MagicMock,
    mock_camera: FakeSannceCamera,
) -> None:
    await setup_integration(hass, mock_config_entry)

    assert mock_config_entry.state is ConfigEntryState.LOADED
    mock_camera_class.assert_called_once_with(
        HOST,
        USERNAME,
        PASSWORD,
        nvs_port=3000,
        http_port=80,
        rtsp_port=554,
        session=async_get_clientsession(hass),
    )
    mock_camera.connect.assert_awaited_once()
    assert mock_config_entry.runtime_data.camera is mock_camera
    mock_camera.close.assert_not_awaited()

    assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.NOT_LOADED
    mock_camera.close.assert_awaited_once()


async def test_setup_uses_entry_ports(
    hass: HomeAssistant,
    mock_camera_class: MagicMock,
) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_HOST: HOST,
            CONF_USERNAME: USERNAME,
            CONF_PASSWORD: PASSWORD,
            CONF_NVS_PORT: 3001,
            CONF_HTTP_PORT: 8080,
            CONF_RTSP_PORT: 8554,
        },
    )

    await setup_integration(hass, entry)

    assert entry.state is ConfigEntryState.LOADED
    _, kwargs = mock_camera_class.call_args
    assert (kwargs["nvs_port"], kwargs["http_port"], kwargs["rtsp_port"]) == (
        3001,
        8080,
        8554,
    )


async def test_setup_retries_when_camera_unreachable(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_camera: FakeSannceCamera,
) -> None:
    mock_camera.connect.side_effect = lib.ConnectError("unreachable")

    await setup_integration(hass, mock_config_entry)

    assert mock_config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_setup_error_on_bad_credentials(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_camera: FakeSannceCamera,
) -> None:
    mock_camera.connect.side_effect = lib.AuthError("bad password")

    await setup_integration(hass, mock_config_entry)

    assert mock_config_entry.state is ConfigEntryState.SETUP_ERROR
    assert "bad password" in mock_config_entry.reason
