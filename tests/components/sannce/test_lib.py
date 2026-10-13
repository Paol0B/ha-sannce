from unittest.mock import MagicMock, patch

from homeassistant.config_entries import SOURCE_USER, ConfigEntryState
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from custom_components.sannce import lib
from custom_components.sannce.const import (
    CONF_HTTP_PORT,
    CONF_NVS_PORT,
    CONF_RTSP_PORT,
    DOMAIN,
)

from . import HOST, PASSWORD, USERNAME
from .conftest import FakeSannceCamera

LOGIN = {CONF_HOST: HOST, CONF_USERNAME: USERNAME, CONF_PASSWORD: PASSWORD}


async def test_create_camera_uses_default_ports(
    hass: HomeAssistant, mock_camera_class: MagicMock
) -> None:
    camera = lib.create_camera(hass, LOGIN)

    assert camera is mock_camera_class.return_value
    mock_camera_class.assert_called_once_with(
        HOST,
        USERNAME,
        PASSWORD,
        nvs_port=3000,
        http_port=80,
        rtsp_port=554,
        session=async_get_clientsession(hass),
    )


async def test_create_camera_uses_given_ports(
    hass: HomeAssistant, mock_camera_class: MagicMock
) -> None:
    ports = {CONF_NVS_PORT: 3001, CONF_HTTP_PORT: 8080, CONF_RTSP_PORT: 8554}

    lib.create_camera(hass, LOGIN | ports)

    _, kwargs = mock_camera_class.call_args
    assert (kwargs["nvs_port"], kwargs["http_port"], kwargs["rtsp_port"]) == (
        3001,
        8080,
        8554,
    )


async def test_flow_and_setup_build_the_camera_with_create_camera(
    hass: HomeAssistant, mock_camera: FakeSannceCamera
) -> None:
    with patch(
        "custom_components.sannce.lib.create_camera", return_value=mock_camera
    ) as create_camera:
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], LOGIN
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["result"].state is ConfigEntryState.LOADED
    assert [call.args[0] for call in create_camera.call_args_list] == [hass, hass]
    assert [call.args[1][CONF_HOST] for call in create_camera.call_args_list] == [
        HOST,
        HOST,
    ]
