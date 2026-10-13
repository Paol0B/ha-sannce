from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_HOST, CONF_MAC, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant

from .const import CONF_SERIAL
from .coordinator import SannceConfigEntry

TO_REDACT = {CONF_HOST, CONF_USERNAME, CONF_PASSWORD, CONF_SERIAL, CONF_MAC}


# title and unique_id are left out on purpose: either can be the host or serial
async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: SannceConfigEntry
) -> dict[str, Any]:
    coordinator = entry.runtime_data
    camera = coordinator.camera
    return {
        "entry": async_redact_data(entry.data, TO_REDACT),
        "info": async_redact_data(asdict(camera.info), TO_REDACT),
        "caps": sorted(camera.caps),
        "coordinator": {
            "connected": coordinator.connected,
            "last_update_success": coordinator.last_update_success,
            "settings": asdict(coordinator.data),
        },
    }
