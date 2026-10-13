import asyncio
from collections.abc import AsyncIterable, AsyncIterator
from pathlib import Path
from unittest.mock import patch

import pytest
from homeassistant.components.media_source import PlayMedia
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.sannce import audio
from custom_components.sannce.coordinator import SannceCoordinator

from . import setup_integration
from .conftest import FakeProcess, FakeSannceCamera, ffmpeg_binary, ffmpeg_running


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

    play = asyncio.create_task(coord.audio.play(hold(), owner=object()))
    await asyncio.sleep(0)
    assert coord.audio.playing is True

    await coord.audio.stop()

    assert coord.audio.playing is False
    assert await play is None
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


async def drain(stream: AsyncIterator[bytes]) -> bytes:
    return b"".join([chunk async for chunk in stream])


async def test_ffmpeg_converts_to_8khz_mono_pcm16(hass: HomeAssistant) -> None:
    proc = FakeProcess(b"\x01\x02\x03\x04", eof=True, exit_code=0)

    with ffmpeg_running(proc) as spawn:
        pcm = await drain(audio._ffmpeg_pcm(hass, "http://host/a.mp3"))

    args = spawn.await_args.args
    assert pcm == b"\x01\x02\x03\x04"
    assert args[0] == "ffmpeg"
    assert "-nostdin" in args
    assert args[args.index("-i") + 1] == "http://host/a.mp3"
    assert args[-7:] == ("-ac", "1", "-ar", "8000", "-f", "s16le", "pipe:1")
    assert not proc.killed


LONG_STDERR = b"x" * 5000 + b"Bad header"


@pytest.mark.parametrize(
    ("stderr", "detail"),
    [
        (b"No such file\n", "No such file"),
        (b"", "exit code 1"),
        (LONG_STDERR, LONG_STDERR[-audio._ERROR_BYTES :].decode()),
    ],
    ids=["stderr", "silent", "long"],
)
@pytest.mark.usefixtures("translations")
async def test_ffmpeg_failure_raises(
    hass: HomeAssistant, stderr: bytes, detail: str
) -> None:
    proc = FakeProcess(b"", eof=True, exit_code=1, stderr=stderr)

    with ffmpeg_running(proc), pytest.raises(HomeAssistantError) as raised:
        await drain(audio._ffmpeg_pcm(hass, "http://host/x.mp3"))

    assert str(raised.value) == f"ffmpeg failed on http://host/x.mp3: {detail}"


async def test_closing_the_stream_kills_ffmpeg_quietly(hass: HomeAssistant) -> None:
    proc = FakeProcess(b"\x01\x02", eof=False, exit_code=0)

    with ffmpeg_running(proc):
        stream = audio._ffmpeg_pcm(hass, "http://host/long.mp3")
        assert await anext(stream) == b"\x01\x02"
        await stream.aclose()

    assert proc.killed


async def test_stopping_a_play_kills_ffmpeg_quietly(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_camera: FakeSannceCamera,
) -> None:
    coord = await coordinator(hass, mock_config_entry)
    proc = FakeProcess(b"\x00\x01", eof=False, exit_code=0)
    streaming = asyncio.Event()

    async def watch(pcm: AsyncIterable[bytes]) -> None:
        async for _ in pcm:
            streaming.set()

    mock_camera.play_audio.side_effect = watch
    with ffmpeg_running(proc):
        play = asyncio.create_task(
            audio.play_media_to_camera(hass, coord, "http://host/long.mp3")
        )
        await streaming.wait()
        await coord.audio.stop()

        assert await play is None
    assert proc.killed


@pytest.mark.parametrize("stdout_closed", [False, True], ids=["silent", "no_exit"])
@pytest.mark.usefixtures("translations")
async def test_stalled_ffmpeg_is_killed(
    hass: HomeAssistant, stdout_closed: bool
) -> None:
    proc = FakeProcess(b"", eof=False, exit_code=0)
    if stdout_closed:
        proc.stdout.feed_eof()

    with (
        ffmpeg_running(proc),
        patch.object(audio, "_STALL_SECONDS", 0.01),
        pytest.raises(
            HomeAssistantError, match="ffmpeg stalled for 0.01 s on http://host/stuck"
        ),
    ):
        async with asyncio.timeout(10):
            await drain(audio._ffmpeg_pcm(hass, "http://host/stuck.mp3"))

    assert proc.killed


def fake_ffmpeg(tmp_path: Path, script: str) -> str:
    binary = tmp_path / "ffmpeg"
    binary.write_text(f"#!/bin/sh\n{script}\n")
    binary.chmod(0o755)
    return str(binary)


async def test_noisy_ffmpeg_stderr_does_not_block_the_audio(
    hass: HomeAssistant, tmp_path: Path
) -> None:
    # more stderr than the pipe and the stream reader hold together
    binary = fake_ffmpeg(tmp_path, "head -c 8000000 /dev/zero >&2; printf pcm")

    with ffmpeg_binary(binary):
        async with asyncio.timeout(10):
            pcm = await drain(audio._ffmpeg_pcm(hass, "http://host/a.mp3"))

    assert pcm == b"pcm"


async def test_closing_a_busy_ffmpeg_does_not_hang(
    hass: HomeAssistant, tmp_path: Path
) -> None:
    binary = fake_ffmpeg(tmp_path, "exec head -c 8000000 /dev/zero")

    with ffmpeg_binary(binary):
        stream = audio._ffmpeg_pcm(hass, "http://host/a.mp3")
        async with asyncio.timeout(10):
            await anext(stream)
            # let unread output fill the pipe, so the stdout reader pauses
            await asyncio.sleep(0.2)
            await stream.aclose()
