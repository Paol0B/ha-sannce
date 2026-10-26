from unittest.mock import MagicMock, patch

import pytest
import sannce_aio
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
from custom_components.sannce.lib import create_relay

from . import HOST, PASSWORD, USERNAME
from .conftest import FakeSannceCamera

LOGIN = {CONF_HOST: HOST, CONF_USERNAME: USERNAME, CONF_PASSWORD: PASSWORD}


def test_lib_reexports_the_library_api() -> None:
    assert set(sannce_aio.__all__) <= set(lib.__all__)
    assert all(
        getattr(lib, name) is getattr(sannce_aio, name) for name in sannce_aio.__all__
    )


async def test_create_camera_uses_default_ports(
    hass: HomeAssistant, mock_camera_class: MagicMock
) -> None:
    camera = lib.create_camera(hass, LOGIN)

    assert camera is mock_camera_class.return_value
    mock_camera_class.assert_called_once_with(
        HOST,
        USERNAME,
        PASSWORD,
        nvs_port=3002,
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


# the autouse relay fixture patches lib.create_relay; this name holds the real one
def test_create_relay_listens_on_localhost_for_the_rtsp_port() -> None:
    speaker = FakeSannceCamera().speaker

    with patch("custom_components.sannce.lib.RtspRelay") as relay_class:
        relay = create_relay(LOGIN, speaker)

    assert relay is relay_class.return_value
    relay_class.assert_called_once_with(
        HOST, 554, listen_host="127.0.0.1", speaker=speaker
    )


def test_create_relay_uses_the_given_rtsp_port() -> None:
    with patch("custom_components.sannce.lib.RtspRelay") as relay_class:
        create_relay(LOGIN | {CONF_RTSP_PORT: 8554}, FakeSannceCamera().speaker)

    assert relay_class.call_args.args == (HOST, 8554)


def test_create_relay_passes_the_speaker() -> None:
    speaker = FakeSannceCamera().speaker

    with patch("custom_components.sannce.lib.RtspRelay") as relay_class:
        create_relay(LOGIN, speaker)

    assert relay_class.call_args.kwargs["speaker"] is speaker


@pytest.mark.usefixtures("mock_find_camera")
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
