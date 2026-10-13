from dataclasses import dataclass
from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import SannceConfigEntry
from .entity import SannceSettingsEntity

# set_detection reads then writes one shared setting, so parallel calls lose changes
PARALLEL_UPDATES = 1


@dataclass(frozen=True, kw_only=True)
class SannceSwitchDescription(SwitchEntityDescription):
    kind: str


DETECTION_SWITCHES = (
    SannceSwitchDescription(
        key="person_detection",
        translation_key="person_detection",
        entity_category=EntityCategory.CONFIG,
        kind="person",
    ),
    SannceSwitchDescription(
        key="vehicle_detection",
        translation_key="vehicle_detection",
        entity_category=EntityCategory.CONFIG,
        kind="vehicle",
    ),
    SannceSwitchDescription(
        key="motion_detection",
        translation_key="motion_detection",
        entity_category=EntityCategory.CONFIG,
        kind="motion",
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
        SannceDetectionSwitch(coordinator, description)
        for description in DETECTION_SWITCHES
        if description.kind in caps
    )


class SannceDetectionSwitch(SannceSettingsEntity, SwitchEntity):
    entity_description: SannceSwitchDescription

    @property
    def is_on(self) -> bool | None:
        detection = self.coordinator.data.detection
        if detection is None:
            return None
        return bool(getattr(detection, self.entity_description.kind))

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._async_set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._async_set(False)

    async def _async_set(self, on: bool) -> None:
        change = {self.entity_description.kind: on}
        await self._async_command(self.coordinator.camera.set_detection(**change))
