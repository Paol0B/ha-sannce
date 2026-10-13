from typing import Any

from homeassistant.components import media_source
from homeassistant.components.media_player import (
    BrowseMedia,
    MediaPlayerDeviceClass,
    MediaPlayerEntity,
    MediaPlayerEntityDescription,
    MediaPlayerEntityFeature,
    MediaPlayerState,
    MediaType,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import lib
from .audio import play_media_to_camera
from .coordinator import SannceConfigEntry, SannceCoordinator
from .entity import SannceEntity

PARALLEL_UPDATES = 0

SPEAKER = MediaPlayerEntityDescription(key="speaker", translation_key="speaker")


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SannceConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    if "talk" in coordinator.camera.caps:
        async_add_entities([SannceSpeaker(coordinator, SPEAKER)])


class SannceSpeaker(SannceEntity, MediaPlayerEntity):
    _attr_device_class = MediaPlayerDeviceClass.SPEAKER
    _attr_media_content_type = MediaType.MUSIC
    _attr_supported_features = (
        MediaPlayerEntityFeature.PLAY_MEDIA
        | MediaPlayerEntityFeature.BROWSE_MEDIA
        | MediaPlayerEntityFeature.STOP
    )

    def __init__(
        self, coordinator: SannceCoordinator, description: MediaPlayerEntityDescription
    ) -> None:
        super().__init__(coordinator, description)
        self._attr_state = MediaPlayerState.IDLE
        self._play_token: object | None = None

    async def async_play_media(
        self, media_type: MediaType | str, media_id: str, **kwargs: Any
    ) -> None:
        token = object()
        self._play_token = token
        self._attr_state = MediaPlayerState.PLAYING
        self.async_write_ha_state()
        try:
            await play_media_to_camera(self.hass, self.coordinator, media_id)
        except lib.SannceError as err:
            raise HomeAssistantError(
                f"Cannot play media on {self.entity_id}: {err}"
            ) from err
        finally:
            # a superseded play wakes first; only the latest play may go idle
            if self._play_token is token:
                self._attr_state = MediaPlayerState.IDLE
                self.async_write_ha_state()

    async def async_media_stop(self) -> None:
        await self.coordinator.audio.stop()

    async def async_browse_media(
        self,
        media_content_type: MediaType | str | None = None,
        media_content_id: str | None = None,
    ) -> BrowseMedia:
        return await media_source.async_browse_media(
            self.hass,
            media_content_id,
            content_filter=lambda item: item.media_content_type.startswith("audio/"),
        )
