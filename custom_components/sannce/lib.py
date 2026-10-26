from collections.abc import Mapping
from typing import Any

from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from sannce_aio import (
    AuthError,
    CameraInfo,
    ConnectError,
    Detection,
    DiscoveredCamera,
    Event,
    Floodlight,
    ProtocolError,
    RtspRelay,
    SannceCamera,
    SannceError,
    Speaker,
    TalkBusyError,
    discover,
    find_camera,
)

from .const import (
    CONF_HTTP_PORT,
    CONF_NVS_PORT,
    CONF_RTSP_PORT,
    DEFAULT_HTTP_PORT,
    DEFAULT_NVS_PORT,
    DEFAULT_RTSP_PORT,
    RELAY_HOST,
)

__all__ = [
    "AuthError",
    "CameraInfo",
    "ConnectError",
    "Detection",
    "DiscoveredCamera",
    "Event",
    "Floodlight",
    "ProtocolError",
    "RtspRelay",
    "SannceCamera",
    "SannceError",
    "Speaker",
    "TalkBusyError",
    "create_camera",
    "create_relay",
    "discover",
    "find_camera",
]


def create_camera(hass: HomeAssistant, data: Mapping[str, Any]) -> SannceCamera:
    return SannceCamera(
        data[CONF_HOST],
        data[CONF_USERNAME],
        data[CONF_PASSWORD],
        nvs_port=data.get(CONF_NVS_PORT, DEFAULT_NVS_PORT),
        http_port=data.get(CONF_HTTP_PORT, DEFAULT_HTTP_PORT),
        rtsp_port=data.get(CONF_RTSP_PORT, DEFAULT_RTSP_PORT),
        session=async_get_clientsession(hass),
    )


def create_relay(data: Mapping[str, Any], speaker: Speaker) -> RtspRelay:
    return RtspRelay(
        data[CONF_HOST],
        data.get(CONF_RTSP_PORT, DEFAULT_RTSP_PORT),
        listen_host=RELAY_HOST,
        speaker=speaker,
    )
