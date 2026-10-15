from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from homeassistant.components.number import (
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import lib
from .coordinator import SannceConfigEntry, SannceData
from .entity import SannceSettingsEntity

# one write at a time, so a scene's values reach the camera in order
PARALLEL_UPDATES = 1


@dataclass(frozen=True, kw_only=True)
class SannceNumberDescription(NumberEntityDescription):
    caps: frozenset[str]
    value_fn: Callable[[SannceData], int | None]
    set_fn: Callable[[lib.SannceCamera, int], Awaitable[None]]


NUMBERS = (
    SannceNumberDescription(
        key="volume",
        translation_key="volume",
        entity_category=EntityCategory.CONFIG,
        native_min_value=0,
        native_max_value=100,
        native_step=1,
        mode=NumberMode.SLIDER,
        caps=frozenset({"volume"}),
        value_fn=lambda data: data.volume,
        set_fn=lambda camera, value: camera.set_volume(value),
    ),
    SannceNumberDescription(
        key="motion_sensitivity",
        translation_key="motion_sensitivity",
        entity_category=EntityCategory.CONFIG,
        native_min_value=0,
        native_max_value=100,
        native_step=1,
        mode=NumberMode.SLIDER,
        caps=frozenset({"motion", "person", "vehicle"}),
        value_fn=lambda data: None
        if data.detection is None
        else data.detection.sensitivity,
        set_fn=lambda camera, value: camera.set_sensitivity(value),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SannceConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    caps = coordinator.camera.caps
    async_add_entities(
        SannceNumber(coordinator, description)
        for description in NUMBERS
        if description.caps & caps
    )


class SannceNumber(SannceSettingsEntity, NumberEntity):
    entity_description: SannceNumberDescription

    @property
    def native_value(self) -> int | None:
        return self.entity_description.value_fn(self.coordinator.data)

    async def async_set_native_value(self, value: float) -> None:
        await self._async_command(
            self.entity_description.set_fn(self.coordinator.camera, round(value))
        )
