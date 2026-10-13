from collections.abc import Mapping
from typing import Any

from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    CONF_HTTP_PORT,
    CONF_NVS_PORT,
    CONF_RTSP_PORT,
    DEFAULT_HTTP_PORT,
    DEFAULT_NVS_PORT,
    DEFAULT_RTSP_PORT,
)
from .sannce_aio import (
    AuthError,
    CameraInfo,
    ConnectError,
    Detection,
    DiscoveredCamera,
    Event,
    ProtocolError,
    SannceCamera,
    SannceError,
    TalkBusyError,
    discover,
    find_camera,
)

__all__ = [
    "AuthError",
    "CameraInfo",
    "ConnectError",
    "Detection",
    "DiscoveredCamera",
    "Event",
    "ProtocolError",
    "SannceCamera",
    "SannceError",
    "TalkBusyError",
    "create_camera",
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
