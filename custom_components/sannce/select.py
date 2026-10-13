from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import SannceConfigEntry
from .entity import SannceSettingsEntity

PARALLEL_UPDATES = 1

# the camera can also report "custom", but it cannot be set, so it is not an option
LIGHT_MODE = SelectEntityDescription(
    key="light_mode",
    translation_key="light_mode",
    options=["infrared", "color", "smart"],
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SannceConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    if "light_mode" in coordinator.camera.caps:
        async_add_entities([SannceLightModeSelect(coordinator, LIGHT_MODE)])


class SannceLightModeSelect(SannceSettingsEntity, SelectEntity):
    @property
    def current_option(self) -> str | None:
        return self.coordinator.data.light_mode

    async def async_select_option(self, option: str) -> None:
        await self._async_command(self.coordinator.camera.set_light_mode(option))
