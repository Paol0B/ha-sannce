from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import lib
from .coordinator import SannceConfigEntry, SannceCoordinator
from .entity import SannceEntity

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class SannceBinarySensorDescription(BinarySensorEntityDescription):
    caps: frozenset[str] = frozenset()
    kinds: frozenset[str]
    needs_smart_filter: bool = False


# a person arrives as MOTIONDETECT while all-motion is off (protocol.md, Start and stop)
EVENT_SENSORS = (
    SannceBinarySensorDescription(
        key="motion",
        device_class=BinarySensorDeviceClass.MOTION,
        caps=frozenset({"motion", "person", "vehicle"}),
        kinds=frozenset({"motion", "vehicle"}),
    ),
    SannceBinarySensorDescription(
        key="person",
        translation_key="person",
        device_class=BinarySensorDeviceClass.MOTION,
        caps=frozenset({"person"}),
        kinds=frozenset({"motion"}),
        needs_smart_filter=True,
    ),
    SannceBinarySensorDescription(
        key="vehicle",
        translation_key="vehicle",
        device_class=BinarySensorDeviceClass.MOTION,
        caps=frozenset({"vehicle"}),
        kinds=frozenset({"vehicle"}),
    ),
    SannceBinarySensorDescription(
        key="intrusion",
        translation_key="intrusion",
        device_class=BinarySensorDeviceClass.MOTION,
        entity_registry_enabled_default=False,
        kinds=frozenset({"intrusion"}),
    ),
    SannceBinarySensorDescription(
        key="line",
        translation_key="line",
        device_class=BinarySensorDeviceClass.MOTION,
        entity_registry_enabled_default=False,
        kinds=frozenset({"line"}),
    ),
    SannceBinarySensorDescription(
        key="tamper",
        device_class=BinarySensorDeviceClass.TAMPER,
        entity_registry_enabled_default=False,
        kinds=frozenset({"tamper"}),
    ),
    SannceBinarySensorDescription(
        key="video_loss",
        translation_key="video_loss",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        kinds=frozenset({"video_loss"}),
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
        SannceEventSensor(coordinator, description)
        for description in EVENT_SENSORS
        if not description.caps or description.caps & caps
    )


class SannceEventSensor(SannceEntity, BinarySensorEntity):
    entity_description: SannceBinarySensorDescription

    def __init__(
        self, coordinator: SannceCoordinator, description: SannceBinarySensorDescription
    ) -> None:
        super().__init__(coordinator, description)
        self._active: set[tuple[str, int]] = set()

    @property
    def available(self) -> bool:
        if not super().available:
            return False
        if not self.entity_description.needs_smart_filter:
            return True
        detection = self.coordinator.data.detection
        return detection is None or not detection.motion

    @property
    def is_on(self) -> bool:
        return bool(self._active)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            self.coordinator.async_add_event_listener(self._handle_event)
        )

    @callback
    def _handle_event(self, event: lib.Event) -> None:
        if event.kind not in self.entity_description.kinds:
            return
        key = (event.kind, event.channel)
        if event.active:
            self._active.add(key)
        else:
            self._active.discard(key)
        self.async_write_ha_state()
