from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .coordinator import LIGHT_MODES, SannceConfigEntry
from .entity import SannceSettingsEntity

PARALLEL_UPDATES = 1

# the camera can also report "custom", but it cannot be set, so it is not an option
LIGHT_MODE = SelectEntityDescription(
    key="light_mode", translation_key="light_mode", options=list(LIGHT_MODES)
)
_DEFAULT_BASE_MODE = "smart"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SannceConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    if "light_mode" in coordinator.camera.caps:
        async_add_entities([SannceLightModeSelect(coordinator, LIGHT_MODE)])


class SannceLightModeSelect(SannceSettingsEntity, SelectEntity, RestoreEntity):
    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if self.coordinator.base_mode is not None:
            return
        last = await self.async_get_last_state()
        restored = last.state if last is not None else None
        self.coordinator.base_mode = (
            restored if restored in self.options else _DEFAULT_BASE_MODE
        )

    @property
    def current_option(self) -> str | None:
        return self.coordinator.base_mode

    async def async_select_option(self, option: str) -> None:
        floodlight = self.coordinator.data.floodlight
        if floodlight is not None and floodlight.on:
            self.coordinator.base_mode = option
            self.async_write_ha_state()
            return
        # the poll after the write sets the base mode, so a refused write changes nothing
        await self._async_command(self.coordinator.camera.set_light_mode(option))
