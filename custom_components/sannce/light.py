from typing import Any

from homeassistant.components.light import (
    ColorMode,
    LightEntity,
    LightEntityDescription,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import SannceConfigEntry, SannceCoordinator
from .entity import SannceSettingsEntity

PARALLEL_UPDATES = 1

FLOODLIGHT = LightEntityDescription(key="floodlight", translation_key="floodlight")


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SannceConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    if "white_light" in coordinator.camera.caps:
        async_add_entities([SannceFloodlight(coordinator, FLOODLIGHT)])


class SannceFloodlight(SannceSettingsEntity, LightEntity):
    _attr_color_mode = ColorMode.ONOFF

    def __init__(
        self, coordinator: SannceCoordinator, description: LightEntityDescription
    ) -> None:
        super().__init__(coordinator, description)
        self._attr_supported_color_modes = {ColorMode.ONOFF}

    @property
    def is_on(self) -> bool | None:
        return self.coordinator.data.light

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._async_command(self.coordinator.camera.set_light(True))

    # off hands the lamp back to the camera (auto mode), it does not force it off
    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._async_command(self.coordinator.camera.set_light(False))
