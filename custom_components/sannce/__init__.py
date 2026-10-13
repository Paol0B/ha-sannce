from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady

from . import lib
from .const import PLATFORMS
from .coordinator import SannceConfigEntry, SannceCoordinator


async def async_setup_entry(hass: HomeAssistant, entry: SannceConfigEntry) -> bool:
    host = entry.data[CONF_HOST]
    camera = lib.create_camera(hass, entry.data)
    # listen before connect(): it reports the first availability
    coordinator = SannceCoordinator(hass, entry, camera)
    try:
        await camera.connect()
    except lib.AuthError as err:
        raise ConfigEntryAuthFailed(f"Login to {host} failed: {err}") from err
    except lib.SannceError as err:
        raise ConfigEntryNotReady(f"Cannot connect to {host}: {err}") from err

    entry.async_on_unload(camera.close)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: SannceConfigEntry) -> bool:
    # end talk while the camera is connected: camera.close runs after this
    await entry.runtime_data.audio.stop()
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
