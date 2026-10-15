from dataclasses import dataclass
from urllib.parse import urlsplit

from homeassistant.components.camera import (
    Camera,
    CameraEntityDescription,
    CameraEntityFeature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import RELAY_HOST
from .coordinator import SannceConfigEntry, SannceCoordinator
from .entity import SannceEntity

PARALLEL_UPDATES = 0


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

    async def stream_source(self) -> str:
        # go2rtc repeats a backchannel SETUP the camera refuses; the relay answers it
        url = urlsplit(self.coordinator.camera.rtsp_url(self.entity_description.stream))
        login = url.netloc.rpartition("@")[0]
        netloc = f"{login}@{RELAY_HOST}:{self.coordinator.relay.port}"
        return url._replace(netloc=netloc).geturl()
