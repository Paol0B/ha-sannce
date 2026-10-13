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


# keys are library event kinds. A person arrives as motion, so there is no person
# sensor. Only motion and vehicle have a capability to check; the rest always exist,
# so they start disabled: the I91FW may never send those events.
EVENT_SENSORS = (
    SannceBinarySensorDescription(
        key="motion",
        device_class=BinarySensorDeviceClass.MOTION,
        caps=frozenset({"motion", "person"}),
    ),
    SannceBinarySensorDescription(
        key="vehicle",
        translation_key="vehicle",
        device_class=BinarySensorDeviceClass.MOTION,
        caps=frozenset({"vehicle"}),
    ),
    SannceBinarySensorDescription(
        key="intrusion",
        translation_key="intrusion",
        device_class=BinarySensorDeviceClass.MOTION,
        entity_registry_enabled_default=False,
    ),
    SannceBinarySensorDescription(
        key="line",
        translation_key="line",
        device_class=BinarySensorDeviceClass.MOTION,
        entity_registry_enabled_default=False,
    ),
    SannceBinarySensorDescription(
        key="tamper",
        device_class=BinarySensorDeviceClass.TAMPER,
        entity_registry_enabled_default=False,
    ),
    SannceBinarySensorDescription(
        key="video_loss",
        translation_key="video_loss",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
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
        self._active_channels: set[int] = set()

    @property
    def is_on(self) -> bool:
        return bool(self._active_channels)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            self.coordinator.async_add_event_listener(self._handle_event)
        )

    @callback
    def _handle_event(self, event: lib.Event) -> None:
        if event.kind != self.entity_description.key:
            return
        if event.active:
            self._active_channels.add(event.channel)
        else:
            self._active_channels.discard(event.channel)
        self.async_write_ha_state()
