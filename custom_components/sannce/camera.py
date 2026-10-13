from dataclasses import dataclass

from homeassistant.components.camera import (
    Camera,
    CameraEntityDescription,
    CameraEntityFeature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import SannceConfigEntry, SannceCoordinator
from .entity import SannceEntity

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class SannceCameraDescription(CameraEntityDescription):
    stream: str


CAMERAS = (
    SannceCameraDescription(key="sub", translation_key="sub", stream="sub"),
    SannceCameraDescription(
        key="main",
        translation_key="main",
        stream="main",
        entity_registry_enabled_default=False,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SannceConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(
        SannceCameraEntity(coordinator, description) for description in CAMERAS
    )


class SannceCameraEntity(SannceEntity, Camera):
    entity_description: SannceCameraDescription
    _attr_supported_features = CameraEntityFeature.STREAM

    def __init__(
        self, coordinator: SannceCoordinator, description: SannceCameraDescription
    ) -> None:
        SannceEntity.__init__(self, coordinator, description)
        Camera.__init__(self)

    @property
    def use_stream_for_stills(self) -> bool:
        return True

    async def stream_source(self) -> str:
        return self.coordinator.camera.rtsp_url(self.entity_description.stream)
