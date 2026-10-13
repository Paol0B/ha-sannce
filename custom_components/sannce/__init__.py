from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from . import lib
from .const import (
    CONF_HTTP_PORT,
    CONF_NVS_PORT,
    CONF_RTSP_PORT,
    DEFAULT_HTTP_PORT,
    DEFAULT_NVS_PORT,
    DEFAULT_RTSP_PORT,
    PLATFORMS,
)

type SannceConfigEntry = ConfigEntry[lib.SannceCamera]


async def async_setup_entry(hass: HomeAssistant, entry: SannceConfigEntry) -> bool:
    host = entry.data[CONF_HOST]
    camera = lib.SannceCamera(
        host,
        entry.data[CONF_USERNAME],
        entry.data[CONF_PASSWORD],
        nvs_port=entry.data.get(CONF_NVS_PORT, DEFAULT_NVS_PORT),
        http_port=entry.data.get(CONF_HTTP_PORT, DEFAULT_HTTP_PORT),
        rtsp_port=entry.data.get(CONF_RTSP_PORT, DEFAULT_RTSP_PORT),
        session=async_get_clientsession(hass),
    )
    try:
        await camera.connect()
    except lib.AuthError as err:
        raise ConfigEntryAuthFailed(f"Login to {host} failed: {err}") from err
    except lib.SannceError as err:
        raise ConfigEntryNotReady(f"Cannot connect to {host}: {err}") from err

    entry.runtime_data = camera
    entry.async_on_unload(camera.close)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: SannceConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
