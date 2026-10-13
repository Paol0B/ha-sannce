import asyncio
from collections.abc import AsyncIterator
from unittest.mock import patch

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
