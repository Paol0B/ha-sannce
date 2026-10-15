from typing import Any

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
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
_DEFAULT_BASE_MODE = "smart"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SannceConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    if {"white_light", "light_mode"} <= coordinator.camera.caps:
        async_add_entities([SannceFloodlight(coordinator, FLOODLIGHT)])


class SannceFloodlight(SannceSettingsEntity, LightEntity):
    _attr_color_mode = ColorMode.BRIGHTNESS

    def __init__(
        self, coordinator: SannceCoordinator, description: LightEntityDescription
    ) -> None:
        super().__init__(coordinator, description)
        self._attr_supported_color_modes = {ColorMode.BRIGHTNESS}

    @property
    def is_on(self) -> bool | None:
        floodlight = self.coordinator.data.floodlight
        return None if floodlight is None else floodlight.on

    @property
    def brightness(self) -> int | None:
        floodlight = self.coordinator.data.floodlight
        if floodlight is None or floodlight.brightness is None:
            return None
        return round(floodlight.brightness * 255 / 100)

    async def async_turn_on(self, **kwargs: Any) -> None:
        level = kwargs.get(ATTR_BRIGHTNESS)
        percent = None if level is None else max(1, round(level * 100 / 255))
        await self._async_command(
            self.coordinator.async_floodlight_command(
                self.coordinator.camera.set_floodlight(True, brightness=percent)
            )
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        base_mode = self.coordinator.base_mode or _DEFAULT_BASE_MODE
        await self._async_command(
            self.coordinator.async_floodlight_command(
                self.coordinator.camera.set_floodlight(False, base_mode=base_mode)
            )
        )
