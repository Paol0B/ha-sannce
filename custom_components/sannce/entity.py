from homeassistant.const import CONF_MAC, CONF_MODEL
from homeassistant.helpers.device_registry import (
    CONNECTION_NETWORK_MAC,
    DeviceInfo,
    format_mac,
)
from homeassistant.helpers.entity import EntityDescription
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_SERIAL, DOMAIN, MANUFACTURER
from .coordinator import SannceCoordinator


class SannceEntity(CoordinatorEntity[SannceCoordinator]):
    _attr_has_entity_name = True

    def __init__(
        self, coordinator: SannceCoordinator, description: EntityDescription
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        entry = coordinator.config_entry
        device_id = entry.unique_id or entry.entry_id
        mac = entry.data.get(CONF_MAC)
        self._attr_unique_id = f"{device_id}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_id)},
            connections={(CONNECTION_NETWORK_MAC, format_mac(mac))} if mac else set(),
            manufacturer=MANUFACTURER,
            name=entry.title,
            model=entry.data.get(CONF_MODEL),
            serial_number=entry.data.get(CONF_SERIAL),
            sw_version=coordinator.camera.info.firmware,
        )

    # CoordinatorEntity also needs the poll; entities that skip it must stay up
    @property
    def available(self) -> bool:
        return self.coordinator.connected


class SannceSettingsEntity(SannceEntity):
    @property
    def available(self) -> bool:
        return super().available and self.coordinator.last_update_success
