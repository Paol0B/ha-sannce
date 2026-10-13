import logging
from collections.abc import Callable
from dataclasses import dataclass
from functools import partial

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from . import lib
from .audio import AudioPlayer
from .const import UPDATE_INTERVAL

_LOGGER = logging.getLogger(__name__)

_DETECTION_CAPS = frozenset({"motion", "person", "vehicle"})

type SannceConfigEntry = ConfigEntry[SannceCoordinator]


@dataclass(frozen=True)
class SannceData:
    light: bool | None
    light_mode: str | None
    detection: lib.Detection | None


class SannceCoordinator(DataUpdateCoordinator[SannceData]):
    config_entry: SannceConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: SannceConfigEntry,
        camera: lib.SannceCamera,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name=config_entry.title,
            update_interval=UPDATE_INTERVAL,
            always_update=False,
        )
        self.camera = camera
        self.audio = AudioPlayer(self)
        self.connected = False
        self._event_listeners: list[Callable[[lib.Event], None]] = []
        camera.on_availability(self._handle_availability)
        camera.on_login_failed(self._handle_login_failed)
        config_entry.async_on_unload(camera.subscribe(self._handle_event))

    @callback
    def async_add_event_listener(
        self, listener: Callable[[lib.Event], None]
    ) -> CALLBACK_TYPE:
        self._event_listeners.append(listener)
        return partial(self._event_listeners.remove, listener)

    async def _async_update_data(self) -> SannceData:
        camera = self.camera
        caps = camera.caps
        host = self.config_entry.data[CONF_HOST]
        # a setting the camera lacks would fail every poll
        try:
            return SannceData(
                light=await camera.get_light() if "white_light" in caps else None,
                light_mode=(
                    await camera.get_light_mode() if "light_mode" in caps else None
                ),
                detection=(
                    await camera.get_detection() if caps & _DETECTION_CAPS else None
                ),
            )
        except lib.AuthError as err:
            raise ConfigEntryAuthFailed(f"Login to {host} failed: {err}") from err
        except lib.SannceError as err:
            raise UpdateFailed(f"Cannot read settings from {host}: {err}") from err

    @callback
    def _handle_availability(self, available: bool) -> None:
        self.connected = available
        self.async_update_listeners()
        # setup runs the first poll itself
        if available and self.data is not None:
            self.config_entry.async_create_background_task(
                self.hass, self.async_request_refresh(), "sannce reconnect refresh"
            )

    @callback
    def _handle_login_failed(self, error: lib.AuthError) -> None:
        self.config_entry.async_start_reauth(self.hass)

    @callback
    def _handle_event(self, event: lib.Event) -> None:
        for listener in list(self._event_listeners):
            try:
                listener(event)
            except Exception:
                self.logger.exception("Event listener failed on %s event", event.kind)
