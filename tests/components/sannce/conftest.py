from collections.abc import AsyncIterable, Callable, Generator, Iterable
from contextlib import suppress
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.const import (
    CONF_HOST,
    CONF_MAC,
    CONF_MODEL,
    CONF_PASSWORD,
    CONF_USERNAME,
)
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.sannce import lib
from custom_components.sannce.const import CONF_SERIAL, DOMAIN

from . import HOST, PASSWORD, USERNAME

ALL_CAPS = ("light_mode", "motion", "person", "talk", "vehicle", "white_light")
RTSP_PATHS = {"main": "/1/1", "sub": "/1/2"}


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
        self.light_on = False
        self.light_mode = "infrared"
        self.detection = lib.Detection(person=True, vehicle=True, motion=True)
        self.played: list[bytes] = []
        self.talk_active = False
        self.talk_starts = 0
        self.talk_stops = 0
        self._subscribers: list[Callable[[lib.Event], None]] = []
        self._availability_callbacks: list[Callable[[bool], None]] = []

        self.connect = AsyncMock(side_effect=self._connect)
        self.close = AsyncMock(side_effect=self._close)
        self.get_light = AsyncMock(side_effect=lambda: self.light_on)
        self.set_light = AsyncMock(side_effect=self._set_light)
        self.get_light_mode = AsyncMock(side_effect=lambda: self.light_mode)
        self.set_light_mode = AsyncMock(side_effect=self._set_light_mode)
        self.get_detection = AsyncMock(side_effect=lambda: self.detection)
        self.set_detection = AsyncMock(side_effect=self._set_detection)
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

    def emit(self, event: lib.Event) -> None:
        for callback in list(self._subscribers):
            callback(event)

    def set_available(self, available: bool) -> None:
        self.available = available
        for callback in list(self._availability_callbacks):
            callback(available)

    async def _connect(self) -> None:
        self.set_available(True)

    async def _close(self) -> None:
        self.set_available(False)

    async def _set_light(self, on: bool) -> None:
        self.light_on = on

    async def _set_light_mode(self, mode: str) -> None:
        self.light_mode = mode

    async def _set_detection(
        self,
        *,
        person: bool | None = None,
        vehicle: bool | None = None,
        motion: bool | None = None,
    ) -> None:
        self.detection = lib.Detection(
            person=self.detection.person if person is None else person,
            vehicle=self.detection.vehicle if vehicle is None else vehicle,
            motion=self.detection.motion if motion is None else motion,
        )

    async def _play_audio(self, pcm: AsyncIterable[bytes]) -> None:
        if self.talk_active:
            raise lib.TalkBusyError("talk is already active")
        self.talk_active = True
        self.talk_starts += 1
        try:
            async for chunk in pcm:
                self.played.append(chunk)
        finally:
            self.talk_active = False
            self.talk_stops += 1


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    return None


# the ffmpeg component imports haffmpeg, absent here; tests patch audio._ffmpeg_pcm
@pytest.fixture(autouse=True)
def mock_ffmpeg_component(hass: HomeAssistant) -> None:
    hass.config.components.add("ffmpeg")


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
