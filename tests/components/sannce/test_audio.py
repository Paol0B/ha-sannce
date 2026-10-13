import asyncio
import sys
import types
from collections.abc import AsyncIterable, AsyncIterator, Iterator
from contextlib import contextmanager
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.components.media_source import PlayMedia
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.sannce import audio
from custom_components.sannce.coordinator import SannceCoordinator

from . import setup_integration
from .conftest import FakeSannceCamera


async def coordinator(
    hass: HomeAssistant, entry: MockConfigEntry
) -> SannceCoordinator:
    await setup_integration(hass, entry)
    return entry.runtime_data


def feed(*chunks: bytes):
    async def fake(hass: HomeAssistant, media_id: str) -> AsyncIterator[bytes]:
        for chunk in chunks:
            yield chunk

    return fake


async def test_helper_converts_and_streams(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_camera: FakeSannceCamera,
) -> None:
    coord = await coordinator(hass, mock_config_entry)

    with patch.object(audio, "_ffmpeg_pcm", feed(b"\x01\x02", b"\x03\x04")):
        await audio.play_media_to_camera(hass, coord, "http://host/a.mp3")

    assert mock_camera.play_audio.await_count == 1
    assert b"".join(mock_camera.played) == b"\x01\x02\x03\x04"
    assert mock_camera.talk_active is False
    assert (mock_camera.talk_starts, mock_camera.talk_stops) == (1, 1)


async def test_helper_resolves_a_media_source_url(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_camera: FakeSannceCamera,
) -> None:
    coord = await coordinator(hass, mock_config_entry)
    seen: list[str] = []

    async def record(hass: HomeAssistant, media_id: str) -> AsyncIterator[bytes]:
        seen.append(media_id)
        yield b"pcm"

    with (
        patch.object(audio.media_source, "is_media_source_id", return_value=True),
        patch.object(
            audio.media_source,
            "async_resolve_media",
            return_value=PlayMedia("http://host/tts.wav", "audio/wav"),
        ),
        patch.object(audio, "_ffmpeg_pcm", record),
    ):
        await audio.play_media_to_camera(
            hass, coord, "media-source://tts/x?message=hi"
        )

    assert seen == ["http://host/tts.wav"]
    assert b"".join(mock_camera.played) == b"pcm"


async def test_audio_helper_supersedes(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_camera: FakeSannceCamera,
) -> None:
    coord = await coordinator(hass, mock_config_entry)
    started = asyncio.Event()
    release = asyncio.Event()

    async def slow() -> AsyncIterator[bytes]:
        yield b"A1"
        started.set()
        await release.wait()
        yield b"A2"

    first = asyncio.create_task(coord.audio.play(slow()))
    await started.wait()

    with patch.object(audio, "_ffmpeg_pcm", feed(b"B1", b"B2")):
        await audio.play_media_to_camera(hass, coord, "http://host/b.mp3")

    assert await first is None
    assert not first.cancelled()
    assert mock_camera.played[-2:] == [b"B1", b"B2"]
    assert b"A1" in mock_camera.played
    assert b"A2" not in mock_camera.played
    assert mock_camera.play_audio.await_count == 2
    assert mock_camera.talk_active is False
    assert (mock_camera.talk_starts, mock_camera.talk_stops) == (2, 2)

    release.set()


async def test_stop_ends_the_current_play(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_camera: FakeSannceCamera,
) -> None:
    coord = await coordinator(hass, mock_config_entry)
    released = asyncio.Event()

    async def hold() -> AsyncIterator[bytes]:
        yield b"X"
        await released.wait()

    play = asyncio.create_task(coord.audio.play(hold()))
    await asyncio.sleep(0)
    assert coord.audio.playing is True

    await coord.audio.stop()

    assert await play is None
    assert coord.audio.playing is False
    assert mock_camera.talk_active is False
    released.set()


async def endless() -> AsyncIterator[bytes]:
    yield b"\x00\x01"
    await asyncio.Event().wait()


async def test_cancelled_play_closes_the_ffmpeg_stream(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_camera: FakeSannceCamera,
) -> None:
    coord = await coordinator(hass, mock_config_entry)
    receiving = asyncio.Event()
    closed = asyncio.Event()
    # a strong reference, so garbage collection cannot close the stream for us
    opened: list[AsyncIterator[bytes]] = []

    async def paced(pcm: AsyncIterable[bytes]) -> None:
        async for chunk in pcm:
            mock_camera.played.append(chunk)
            receiving.set()
            await asyncio.Event().wait()

    async def stream() -> AsyncIterator[bytes]:
        try:
            yield b"\x00\x01"
            yield b"\x02\x03"
        finally:
            closed.set()

    def ffmpeg(hass: HomeAssistant, media_id: str) -> AsyncIterator[bytes]:
        opened.append(source := stream())
        return source

    mock_camera.play_audio.side_effect = paced
    with patch.object(audio, "_ffmpeg_pcm", ffmpeg):
        play = asyncio.create_task(
            audio.play_media_to_camera(hass, coord, "http://host/long.mp3")
        )
        await receiving.wait()
        await coord.audio.stop()
        await play

    assert closed.is_set()


async def test_cancelling_the_caller_is_not_swallowed(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_camera: FakeSannceCamera,
) -> None:
    coord = await coordinator(hass, mock_config_entry)
    streaming = asyncio.Event()

    async def watch(pcm: AsyncIterable[bytes]) -> None:
        async for _ in pcm:
            streaming.set()

    mock_camera.play_audio.side_effect = watch
    caller = asyncio.create_task(coord.audio.play(endless()))
    await streaming.wait()
    caller.cancel()

    with pytest.raises(asyncio.CancelledError):
        await caller
    assert coord.audio.playing is False


async def test_cancelling_a_stop_is_not_swallowed(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_camera: FakeSannceCamera,
) -> None:
    coord = await coordinator(hass, mock_config_entry)
    streaming = asyncio.Event()
    stopping = asyncio.Event()

    async def slow_stop(pcm: AsyncIterable[bytes]) -> None:
        try:
            async for _ in pcm:
                streaming.set()
        finally:
            stopping.set()
            await asyncio.Event().wait()

    mock_camera.play_audio.side_effect = slow_stop
    play = asyncio.create_task(coord.audio.play(endless()))
    await streaming.wait()
    stop = asyncio.create_task(coord.audio.stop())
    await stopping.wait()
    stop.cancel()

    with pytest.raises(asyncio.CancelledError):
        await stop
    assert await play is None


class FakeProcess:
    def __init__(
        self, stdout: bytes, *, eof: bool, exit_code: int, stderr: bytes = b""
    ) -> None:
        self.stdout = asyncio.StreamReader()
        self.stdout.feed_data(stdout)
        if eof:
            self.stdout.feed_eof()
        self.returncode: int | None = None
        self.killed = False
        self._exit_code = exit_code
        self._stderr = stderr

    def kill(self) -> None:
        self.killed = True

    async def communicate(self) -> tuple[bytes, bytes]:
        self.returncode = -9 if self.killed else self._exit_code
        return b"", self._stderr


@contextmanager
def ffmpeg_running(proc: FakeProcess) -> Iterator[AsyncMock]:
    component = types.ModuleType("homeassistant.components.ffmpeg")
    component.get_ffmpeg_manager = lambda hass: types.SimpleNamespace(binary="ffmpeg")
    spawn = AsyncMock(return_value=proc)
    with (
        patch.dict(sys.modules, {"homeassistant.components.ffmpeg": component}),
        patch.object(audio.asyncio, "create_subprocess_exec", spawn),
    ):
        yield spawn


async def test_ffmpeg_converts_to_8khz_mono_pcm16(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    proc = FakeProcess(b"\x01\x02\x03\x04", eof=True, exit_code=0)

    with ffmpeg_running(proc) as spawn:
        pcm = [chunk async for chunk in audio._ffmpeg_pcm(hass, "http://host/a.mp3")]

    args = spawn.await_args.args
    assert b"".join(pcm) == b"\x01\x02\x03\x04"
    assert args[0] == "ffmpeg"
    assert "-nostdin" in args
    assert args[args.index("-i") + 1] == "http://host/a.mp3"
    assert args[-7:] == ("-ac", "1", "-ar", "8000", "-f", "s16le", "pipe:1")
    assert not proc.killed
    assert "ffmpeg failed" not in caplog.text


async def test_ffmpeg_failure_is_logged(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    proc = FakeProcess(b"", eof=True, exit_code=1, stderr=b"No such file")

    with ffmpeg_running(proc):
        pcm = [chunk async for chunk in audio._ffmpeg_pcm(hass, "http://host/x.mp3")]

    assert pcm == []
    assert "ffmpeg failed on http://host/x.mp3: No such file" in caplog.text


async def test_closing_the_stream_kills_ffmpeg_quietly(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    proc = FakeProcess(b"\x01\x02", eof=False, exit_code=0)

    with ffmpeg_running(proc):
        stream = audio._ffmpeg_pcm(hass, "http://host/long.mp3")
        assert await anext(stream) == b"\x01\x02"
        await stream.aclose()

    assert proc.killed
    assert "ffmpeg failed" not in caplog.text
