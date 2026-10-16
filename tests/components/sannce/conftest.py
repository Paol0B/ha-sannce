import asyncio
import dataclasses
import sys
import types
from collections.abc import (
    AsyncIterable,
    Callable,
    Generator,
    Iterable,
    Iterator,
    Mapping,
)
from contextlib import contextmanager, suppress
from typing import Any
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import pytest
from homeassistant.const import (
    CONF_HOST,
    CONF_MAC,
    CONF_MODEL,
    CONF_PASSWORD,
    CONF_USERNAME,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import translation
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.sannce import audio, lib
from custom_components.sannce.const import CONF_SERIAL, DOMAIN

from . import HOST, PASSWORD, USERNAME

ALL_CAPS = (
    "light_mode",
    "motion",
    "person",
    "siren",
    "siren_on_event",
    "speaker",
    "vehicle",
    "volume",
    "white_light",
)
RTSP_PATHS = {"main": "/1/1", "sub": "/1/2"}


class FakeSpeaker:
    def __init__(self) -> None:
        self.owner: str | None = None
        self.subscribers: list[Callable[[str | None], None]] = []

    def subscribe(self, callback: Callable[[str | None], None]) -> Callable[[], None]:
        self.subscribers.append(callback)

        def unsubscribe() -> None:
            with suppress(ValueError):
                self.subscribers.remove(callback)

        return unsubscribe

    def set_owner(self, owner: str | None) -> None:
        self.owner = owner
        for callback in list(self.subscribers):
            callback(owner)


class FakeSannceCamera:
    def __init__(
        self,
        *,
        info: lib.CameraInfo | None = None,
        caps: Iterable[str] = ALL_CAPS,
    ) -> None:
        self.info = info or lib.CameraInfo(firmware="1.0.0")
        self.caps = frozenset(caps)
        self.available = False
        self.floodlight_on = False
        self.brightness: int | None = 100
        self.light_mode = "infrared"
        self.detection = lib.Detection(
            person=True, vehicle=True, motion=False, sensitivity=76
        )
        self.volume = 80
        self.siren_on_event = False
        self.sound_count = 3
        self.sounds: list[tuple[int, int]] = []
        self.played: list[bytes] = []
        # a play waits after each chunk until the gate is set
        self.audio_gate: asyncio.Event | None = None
        self.talk_active = False
        self.talk_starts = 0
        self.talk_stops = 0
        self.speaker = FakeSpeaker()
        self._play: asyncio.Task[Any] | None = None
        self._preempted: set[asyncio.Task[Any]] = set()
        self._subscribers: list[Callable[[lib.Event], None]] = []
        self._availability_callbacks: list[Callable[[bool], None]] = []
        self._login_failed_callbacks: list[Callable[[lib.AuthError], None]] = []

        self.connect = AsyncMock(side_effect=self._connect)
        self.close = AsyncMock(side_effect=self._close)
        self.get_floodlight = AsyncMock(
            side_effect=lambda: lib.Floodlight(
                on=self.floodlight_on, brightness=self.brightness
            )
        )
        self.set_floodlight = AsyncMock(side_effect=self._set_floodlight)
        self.get_light_mode = AsyncMock(side_effect=lambda: self.light_mode)
        self.set_light_mode = AsyncMock(side_effect=self._set_light_mode)
        self.get_detection = AsyncMock(side_effect=lambda: self.detection)
        self.set_detection = AsyncMock(side_effect=self._set_detection)
        self.set_sensitivity = AsyncMock(side_effect=self._set_sensitivity)
        self.get_volume = AsyncMock(side_effect=lambda: self.volume)
        self.set_volume = AsyncMock(side_effect=self._set_volume)
        self.get_siren_on_event = AsyncMock(side_effect=lambda: self.siren_on_event)
        self.set_siren_on_event = AsyncMock(side_effect=self._set_siren_on_event)
        self.play_sound = AsyncMock(side_effect=self._play_sound)
        self.stop_sound = AsyncMock(side_effect=self._stop_sound)
        self.play_audio = AsyncMock(side_effect=self._play_audio)

    def rtsp_url(self, stream: str = "main") -> str:
        return f"rtsp://{USERNAME}:{PASSWORD}@{HOST}:554{RTSP_PATHS[stream]}"

    def subscribe(self, callback: Callable[[lib.Event], None]) -> Callable[[], None]:
        self._subscribers.append(callback)

        def unsubscribe() -> None:
            with suppress(ValueError):
                self._subscribers.remove(callback)

        return unsubscribe

    def on_availability(self, callback: Callable[[bool], None]) -> None:
        self._availability_callbacks.append(callback)

    def on_login_failed(self, callback: Callable[[lib.AuthError], None]) -> None:
        self._login_failed_callbacks.append(callback)

    def emit(self, event: lib.Event) -> None:
        for callback in list(self._subscribers):
            callback(event)

    def set_available(self, available: bool) -> None:
        self.available = available
        for callback in list(self._availability_callbacks):
            callback(available)

    def fail_login(self, error: lib.AuthError) -> None:
        for callback in list(self._login_failed_callbacks):
            callback(error)

    async def _connect(self) -> None:
        self.set_available(True)

    async def _close(self) -> None:
        if self.speaker.owner is not None:
            self.speaker.set_owner(None)
        self.set_available(False)

    async def _set_floodlight(
        self, on: bool, *, brightness: int | None = None, base_mode: str = "smart"
    ) -> None:
        if not on:
            self.floodlight_on = False
            self.light_mode = base_mode
            return
        self.floodlight_on = True
        if self.light_mode != "custom":
            self.light_mode = "color"
        if brightness is not None:
            self.brightness = brightness

    async def _set_light_mode(self, mode: str) -> None:
        self.light_mode = mode

    async def _set_detection(
        self,
        *,
        person: bool | None = None,
        vehicle: bool | None = None,
        motion: bool | None = None,
    ) -> None:
        self.detection = dataclasses.replace(
            self.detection,
            person=self.detection.person if person is None else person,
            vehicle=self.detection.vehicle if vehicle is None else vehicle,
            motion=self.detection.motion if motion is None else motion,
        )

    async def _set_sensitivity(self, level: int) -> None:
        self.detection = dataclasses.replace(self.detection, sensitivity=level)

    async def _set_volume(self, volume: int) -> None:
        self.volume = volume

    async def _set_siren_on_event(self, on: bool) -> None:
        self.siren_on_event = on

    async def _play_sound(self, sample: int) -> None:
        self.sounds.append((sample, 1))

    async def _stop_sound(self, sample: int) -> None:
        self.sounds.append((sample, 0))

    def preempt(self) -> None:
        self._end_play()
        self.speaker.set_owner("talk")

    def _end_play(self) -> None:
        play = self._play
        if play is not None and not play.done():
            self._preempted.add(play)
            play.cancel()

    async def _play_audio(self, pcm: AsyncIterable[bytes]) -> bool:
        self._end_play()
        play = self._play = asyncio.current_task()
        assert play is not None
        self.talk_active = True
        self.talk_starts += 1
        self.speaker.set_owner("play")
        try:
            async for chunk in pcm:
                self.played.append(chunk)
                if self.audio_gate is not None:
                    await self.audio_gate.wait()
        except asyncio.CancelledError:
            if play not in self._preempted:
                raise
            play.uncancel()
            return False
        finally:
            self._preempted.discard(play)
            self.talk_stops += 1
            if self._play is play:
                self._play = None
                self.talk_active = False
                if self.speaker.owner == "play":
                    self.speaker.set_owner(None)
        return True


class FakeRelay:
    def __init__(
        self,
        data: Mapping[str, Any],
        speaker: FakeSpeaker | None = None,
        number: int = 0,
    ) -> None:
        self.data = data
        self.speaker = speaker
        self.port = 0
        self._number = number
        self.start = AsyncMock(side_effect=self._start)
        self.close = AsyncMock()

    async def _start(self) -> None:
        self.port = 18554 + self._number


class FakeProcess:
    def __init__(
        self, stdout: bytes, *, eof: bool, exit_code: int, stderr: bytes = b""
    ) -> None:
        self.stdout = asyncio.StreamReader()
        self.stdout.feed_data(stdout)
        self.stderr = asyncio.StreamReader()
        self.stderr.feed_data(stderr)
        self.returncode: int | None = None
        self.killed = False
        self._exited = asyncio.Event()
        if eof:
            self._exit(exit_code)

    def kill(self) -> None:
        self.killed = True
        self._exit(-9)

    async def wait(self) -> int:
        await self._exited.wait()
        return self.returncode

    def _exit(self, code: int) -> None:
        self.stdout.feed_eof()
        self.stderr.feed_eof()
        self.returncode = code
        self._exited.set()


@contextmanager
def ffmpeg_binary(binary: str) -> Iterator[None]:
    component = types.ModuleType("homeassistant.components.ffmpeg")
    component.get_ffmpeg_manager = lambda hass: types.SimpleNamespace(binary=binary)
    with patch.dict(sys.modules, {"homeassistant.components.ffmpeg": component}):
        yield


@contextmanager
def ffmpeg_running(proc: FakeProcess) -> Iterator[AsyncMock]:
    spawn = AsyncMock(return_value=proc)
    with (
        ffmpeg_binary("ffmpeg"),
        patch.object(audio.asyncio, "create_subprocess_exec", spawn),
    ):
        yield spawn


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    return None


# ffmpeg imports haffmpeg and stream imports av, both absent here
@pytest.fixture(autouse=True)
def mock_media_components(hass: HomeAssistant) -> None:
    hass.config.components.add("ffmpeg")
    hass.config.components.add("stream")


# without setup, a translated error reads as its key: messages come only
# from the strings of loaded components
@pytest.fixture
async def translations(hass: HomeAssistant) -> None:
    await translation.async_load_integrations(hass, {DOMAIN})
    hass.config.components.add(DOMAIN)


@pytest.fixture
def entity_registry_enabled_by_default() -> Generator[None]:
    with patch(
        "homeassistant.helpers.entity.Entity.entity_registry_enabled_default",
        new_callable=PropertyMock,
        return_value=True,
    ):
        yield


@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title=HOST,
        unique_id=HOST,
        data={CONF_HOST: HOST, CONF_USERNAME: USERNAME, CONF_PASSWORD: PASSWORD},
    )


@pytest.fixture
def identified_entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title="I91FW",
        unique_id="SN123456",
        data={
            CONF_HOST: HOST,
            CONF_USERNAME: USERNAME,
            CONF_PASSWORD: PASSWORD,
            CONF_MODEL: "I91FW",
            CONF_SERIAL: "SN123456",
            CONF_MAC: "AA-BB-CC-DD-EE-FF",
        },
    )


# the HA test plugin blocks sockets, so every flow that searches needs this
@pytest.fixture
def mock_find_camera() -> Generator[AsyncMock]:
    with patch(
        "custom_components.sannce.lib.find_camera", AsyncMock(return_value=None)
    ) as find_camera:
        yield find_camera


# the HA test plugin blocks sockets, and every setup starts a relay
@pytest.fixture(autouse=True)
def mock_relays() -> Generator[list[FakeRelay]]:
    relays: list[FakeRelay] = []

    def create(data: Mapping[str, Any], speaker: FakeSpeaker) -> FakeRelay:
        relays.append(FakeRelay(data, speaker, len(relays)))
        return relays[-1]

    with patch("custom_components.sannce.lib.create_relay", side_effect=create):
        yield relays


@pytest.fixture
def mock_camera_class() -> Generator[MagicMock]:
    with patch(
        "custom_components.sannce.lib.SannceCamera",
        autospec=True,
        return_value=FakeSannceCamera(),
    ) as camera_class:
        yield camera_class


@pytest.fixture
def mock_camera(mock_camera_class: MagicMock) -> FakeSannceCamera:
    return mock_camera_class.return_value
