from contextvars import ContextVar
from dataclasses import dataclass

from homeassistant.components.camera import (
    Camera,
    CameraEntityDescription,
    CameraEntityFeature,
)
from homeassistant.components.stream import Stream
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import SannceConfigEntry, SannceCoordinator
from .entity import SannceEntity

PARALLEL_UPDATES = 0

# set while this task builds the HLS stream; go2rtc asks from other tasks
_BUILDING_HLS: ContextVar[bool] = ContextVar("sannce_building_hls", default=False)


@dataclass(frozen=True, kw_only=True)
class SannceCameraDescription(CameraEntityDescription):
    stream: str


CAMERAS = (
    SannceCameraDescription(key="sub", translation_key="sub", stream="sub"),
    SannceCameraDescription(key="main", translation_key="main", stream="main"),
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

    async def async_create_stream(self) -> Stream | None:
        token = _BUILDING_HLS.set(True)
        try:
            return await super().async_create_stream()
        finally:
            _BUILDING_HLS.reset(token)

    async def stream_source(self) -> str:
        stream = self.entity_description.stream
        # the HLS stream drops G.711 audio, so it reads the AAC copy
        if _BUILDING_HLS.get():
            return self.coordinator.transcoder.url(stream)
        return self.coordinator.relay_url(stream)
