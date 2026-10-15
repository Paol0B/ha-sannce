from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import lib
from .coordinator import SannceConfigEntry, SannceData
from .entity import SannceSettingsEntity

# set_detection reads then writes one shared setting, so parallel calls lose changes
PARALLEL_UPDATES = 1


@dataclass(frozen=True, kw_only=True)
class SannceSwitchDescription(SwitchEntityDescription):
    cap: str
    is_on_fn: Callable[[SannceData], bool | None]
    set_fn: Callable[[lib.SannceCamera, bool], Awaitable[None]]


def _detection(kind: str) -> Callable[[SannceData], bool | None]:
    def read(data: SannceData) -> bool | None:
        return None if data.detection is None else bool(getattr(data.detection, kind))

    return read


SWITCHES = (
    SannceSwitchDescription(
        key="person_detection",
        translation_key="person_detection",
        entity_category=EntityCategory.CONFIG,
        cap="person",
        is_on_fn=_detection("person"),
        set_fn=lambda camera, on: camera.set_detection(person=on),
    ),
    SannceSwitchDescription(
        key="vehicle_detection",
        translation_key="vehicle_detection",
        entity_category=EntityCategory.CONFIG,
        cap="vehicle",
        is_on_fn=_detection("vehicle"),
        set_fn=lambda camera, on: camera.set_detection(vehicle=on),
    ),
    SannceSwitchDescription(
        key="motion_detection",
        translation_key="motion_detection",
        entity_category=EntityCategory.CONFIG,
        cap="motion",
        is_on_fn=_detection("motion"),
        set_fn=lambda camera, on: camera.set_detection(motion=on),
    ),
    SannceSwitchDescription(
        key="siren_on_event",
        translation_key="siren_on_event",
        entity_category=EntityCategory.CONFIG,
        cap="siren_on_event",
        is_on_fn=lambda data: data.siren_on_event,
        set_fn=lambda camera, on: camera.set_siren_on_event(on),
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
        SannceSwitch(coordinator, description)
        for description in SWITCHES
        if description.cap in caps
    )


class SannceSwitch(SannceSettingsEntity, SwitchEntity):
    entity_description: SannceSwitchDescription

    @property
    def is_on(self) -> bool | None:
        return self.entity_description.is_on_fn(self.coordinator.data)

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._async_set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._async_set(False)

    async def _async_set(self, on: bool) -> None:
        await self._async_command(
            self.entity_description.set_fn(self.coordinator.camera, on)
        )
