import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from functools import partial
from urllib.parse import urlsplit

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import CONF_HOST
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from . import lib
from .audio import AudioPlayer
from .const import DOMAIN, RELAY_HOST, UPDATE_INTERVAL
from .transcode import TranscodeServer

_LOGGER = logging.getLogger(__name__)

_DETECTION_CAPS = frozenset({"motion", "person", "vehicle"})
LIGHT_MODES = ("infrared", "color", "smart")

type SannceConfigEntry = ConfigEntry[SannceCoordinator]


@dataclass(frozen=True)
class SannceData:
    floodlight: lib.Floodlight | None
    light_mode: str | None
    detection: lib.Detection | None
    volume: int | None
    siren_on_event: bool | None


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
        self.relay = lib.create_relay(config_entry.data, camera.speaker)
        self.transcoder = TranscodeServer(hass, self.relay_url)
        self.audio = AudioPlayer(self)
        self.connected = False
        self.base_mode: str | None = None
        self._floodlight_commands = 0
        self._floodlight_starts = 0
        self._event_listeners: list[Callable[[lib.Event], None]] = []
        camera.on_availability(self._handle_availability)
        camera.on_login_failed(self._handle_login_failed)
        config_entry.async_on_unload(camera.subscribe(self._handle_event))
        config_entry.async_on_unload(camera.speaker.subscribe(self._handle_speaker))

    def relay_url(self, stream: str) -> str:
        # go2rtc repeats a backchannel SETUP the camera refuses; the relay answers it
        url = urlsplit(self.camera.rtsp_url(stream))
        login = url.netloc.rpartition("@")[0]
        return url._replace(netloc=f"{login}@{RELAY_HOST}:{self.relay.port}").geturl()

    @callback
    def async_add_event_listener(
        self, listener: Callable[[lib.Event], None]
    ) -> CALLBACK_TYPE:
        self._event_listeners.append(listener)
        return partial(self._event_listeners.remove, listener)

    async def async_floodlight_command(self, command: Awaitable[None]) -> None:
        self._floodlight_commands += 1
        self._floodlight_starts += 1
        try:
            await command
        finally:
            self._floodlight_commands -= 1

    async def _async_update_data(self) -> SannceData:
        # a poll that overlaps a floodlight command can read its color-mode step
        idle = self._floodlight_commands == 0
        starts = self._floodlight_starts
        camera = self.camera
        caps = camera.caps
        host = self.config_entry.data[CONF_HOST]
        # a setting the camera lacks would fail every poll
        try:
            data = SannceData(
                floodlight=(
                    await camera.get_floodlight()
                    if {"white_light", "light_mode"} <= caps
                    else None
                ),
                light_mode=(
                    await camera.get_light_mode() if "light_mode" in caps else None
                ),
                detection=(
                    await camera.get_detection() if caps & _DETECTION_CAPS else None
                ),
                volume=await camera.get_volume() if "volume" in caps else None,
                siren_on_event=(
                    await camera.get_siren_on_event()
                    if "siren_on_event" in caps
                    else None
                ),
            )
        except lib.AuthError as err:
            raise ConfigEntryAuthFailed(
                translation_domain=DOMAIN,
                translation_key="login_failed",
                translation_placeholders={"host": host, "error": str(err)},
            ) from err
        except lib.SannceError as err:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="settings_read_failed",
                translation_placeholders={"host": host, "error": str(err)},
            ) from err
        # while the floodlight is forced on, the camera mode is not the user's choice
        forced_on = data.floodlight is not None and data.floodlight.on
        overlapped = not idle or starts != self._floodlight_starts
        if data.light_mode in LIGHT_MODES and not forced_on and not overlapped:
            self.base_mode = data.light_mode
        return data

    @callback
    def _handle_availability(self, available: bool) -> None:
        was_connected = self.connected
        self.connected = available
        self.async_update_listeners()
        # setup runs the first poll itself, and unload closes the camera on purpose
        if (
            available == was_connected
            or self.data is None
            or self.config_entry.state is not ConfigEntryState.LOADED
        ):
            return
        host = self.config_entry.data[CONF_HOST]
        if not available:
            _LOGGER.info("Camera %s is unavailable", host)
            return
        _LOGGER.info("Camera %s is back online", host)
        self.config_entry.async_create_background_task(
            self.hass, self.async_request_refresh(), "sannce reconnect refresh"
        )

    @callback
    def _handle_login_failed(self, error: lib.AuthError) -> None:
        self.config_entry.async_start_reauth(self.hass)

    @callback
    def _handle_speaker(self, owner: str | None) -> None:
        self.async_update_listeners()

    @callback
    def _handle_event(self, event: lib.Event) -> None:
        for listener in list(self._event_listeners):
            try:
                listener(event)
            except Exception:
                self.logger.exception("Event listener failed on %s event", event.kind)
