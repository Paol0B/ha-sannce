import asyncio
from collections.abc import AsyncIterable, AsyncIterator
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.components.media_player import (
    ATTR_MEDIA_CONTENT_ID,
    ATTR_MEDIA_CONTENT_TYPE,
    DOMAIN as MP_DOMAIN,
    SERVICE_PLAY_MEDIA,
    MediaPlayerEntityFeature,
    MediaPlayerState,
    MediaType,
)
from homeassistant.components.media_source import Unresolvable
from homeassistant.components.siren import DOMAIN as SIREN_DOMAIN
from homeassistant.const import (
    ATTR_ENTITY_ID,
    ATTR_SUPPORTED_FEATURES,
    SERVICE_MEDIA_STOP,
    SERVICE_TURN_ON,
    STATE_ON,
    STATE_UNAVAILABLE,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.sannce import audio, lib, media_player
from custom_components.sannce.const import DOMAIN

from . import setup_integration
from .conftest import ALL_CAPS, FakeProcess, FakeSannceCamera, ffmpeg_running

TTS_URL = "media-source://tts/cloud?message=hello"


def speaker_id(registry: er.EntityRegistry, entry: MockConfigEntry) -> str | None:
    return registry.async_get_entity_id(
        MP_DOMAIN, DOMAIN, f"{entry.unique_id}_speaker"
    )


async def play_media(hass: HomeAssistant, entity_id: str, media_id: str) -> None:
    await hass.services.async_call(
        MP_DOMAIN,
        SERVICE_PLAY_MEDIA,
        {
            ATTR_ENTITY_ID: entity_id,
            ATTR_MEDIA_CONTENT_TYPE: MediaType.MUSIC,
            ATTR_MEDIA_CONTENT_ID: media_id,
        },
        blocking=True,
    )


@pytest.fixture
async def speaker(
    hass: HomeAssistant,
    identified_entry: MockConfigEntry,
    mock_camera: FakeSannceCamera,
    entity_registry: er.EntityRegistry,
) -> str:
    await setup_integration(hass, identified_entry)
    entity_id = speaker_id(entity_registry, identified_entry)
    assert entity_id, "no speaker is registered"
    return entity_id


async def test_speaker_starts_idle(hass: HomeAssistant, speaker: str) -> None:
    assert hass.states.get(speaker).state == MediaPlayerState.IDLE


async def test_play_media_reaches_the_helper(
    hass: HomeAssistant,
    identified_entry: MockConfigEntry,
    speaker: str,
) -> None:
    helper = AsyncMock()
    with patch.object(media_player, "play_media_to_camera", helper):
        await play_media(hass, speaker, TTS_URL)

    helper.assert_awaited_once()
    args = helper.await_args.args
    assert args[0] is hass
    assert args[1] is identified_entry.runtime_data
    assert args[2] == TTS_URL


async def test_play_media_streams_pcm(
    hass: HomeAssistant, speaker: str, mock_camera: FakeSannceCamera
) -> None:
    async def fake(hass: HomeAssistant, media_id: str) -> AsyncIterator[bytes]:
        yield b"\xaa\xbb"
        yield b"\xcc\xdd"

    with patch.object(audio, "_ffmpeg_pcm", fake):
        await play_media(hass, speaker, "http://host/clip.mp3")

    assert b"".join(mock_camera.played) == b"\xaa\xbb\xcc\xdd"
    assert hass.states.get(speaker).state == MediaPlayerState.IDLE


async def test_state_is_playing_while_streaming(
    hass: HomeAssistant, speaker: str, mock_camera: FakeSannceCamera
) -> None:
    release = asyncio.Event()

    async def hold(pcm: AsyncIterable[bytes]) -> None:
        async for _ in pcm:
            await release.wait()

    mock_camera.play_audio.side_effect = hold

    async def fake(hass: HomeAssistant, media_id: str) -> AsyncIterator[bytes]:
        yield b"\x00\x01"

    with patch.object(audio, "_ffmpeg_pcm", fake):
        call = hass.async_create_task(play_media(hass, speaker, "http://host/x.mp3"))
        for _ in range(10):
            await asyncio.sleep(0)

        assert hass.states.get(speaker).state == MediaPlayerState.PLAYING

        release.set()
        await call

    assert hass.states.get(speaker).state == MediaPlayerState.IDLE


def feed(*chunks: bytes):
    async def fake(hass: HomeAssistant, media_id: str) -> AsyncIterator[bytes]:
        for chunk in chunks:
            yield chunk

    return fake


@pytest.mark.parametrize(
    ("error", "raised"),
    [
        (ValueError("ffmpeg component not initialized"), ValueError),
        (FileNotFoundError("ffmpeg"), FileNotFoundError),
        (Unresolvable("unknown media"), Unresolvable),
        (lib.TalkBusyError("talk is busy"), HomeAssistantError),
    ],
    ids=["no_ffmpeg", "no_binary", "unresolvable", "talk_busy"],
)
async def test_failed_play_returns_to_idle(
    hass: HomeAssistant,
    speaker: str,
    mock_camera: FakeSannceCamera,
    error: Exception,
    raised: type[Exception],
) -> None:
    mock_camera.play_audio.side_effect = error

    with patch.object(audio, "_ffmpeg_pcm", feed(b"\x00\x01")), pytest.raises(raised):
        await play_media(hass, speaker, "http://host/x.mp3")

    assert hass.states.get(speaker).state == MediaPlayerState.IDLE


async def test_ffmpeg_failure_fails_the_play_media_call(
    hass: HomeAssistant, speaker: str
) -> None:
    proc = FakeProcess(b"", eof=True, exit_code=1, stderr=b"Invalid data found")

    with (
        ffmpeg_running(proc),
        pytest.raises(HomeAssistantError, match="Invalid data found"),
    ):
        await play_media(hass, speaker, "http://host/bad.mp3")

    assert hass.states.get(speaker).state == MediaPlayerState.IDLE


async def test_superseding_play_keeps_the_speaker_playing(
    hass: HomeAssistant, speaker: str, mock_camera: FakeSannceCamera
) -> None:
    holding = asyncio.Event()
    release = asyncio.Event()

    async def hold(pcm: AsyncIterable[bytes]) -> None:
        async for _ in pcm:
            holding.set()
            await release.wait()

    mock_camera.play_audio.side_effect = hold

    with patch.object(audio, "_ffmpeg_pcm", feed(b"\x00\x01")):
        first = hass.async_create_task(play_media(hass, speaker, "http://host/1.mp3"))
        await holding.wait()
        holding.clear()
        second = hass.async_create_task(
            play_media(hass, speaker, "http://host/2.mp3")
        )
        await holding.wait()
        await first

        assert hass.states.get(speaker).state == MediaPlayerState.PLAYING

        release.set()
        await second

    assert hass.states.get(speaker).state == MediaPlayerState.IDLE


async def test_media_stop_cancels_the_play(
    hass: HomeAssistant, speaker: str, mock_camera: FakeSannceCamera
) -> None:
    streaming = asyncio.Event()

    async def endless(hass: HomeAssistant, media_id: str) -> AsyncIterator[bytes]:
        yield b"\x00\x01"
        streaming.set()
        await asyncio.Event().wait()

    features = hass.states.get(speaker).attributes[ATTR_SUPPORTED_FEATURES]
    assert features & MediaPlayerEntityFeature.STOP

    with patch.object(audio, "_ffmpeg_pcm", endless):
        call = hass.async_create_task(play_media(hass, speaker, "http://host/x.mp3"))
        await streaming.wait()
        assert hass.states.get(speaker).state == MediaPlayerState.PLAYING

        await hass.services.async_call(
            MP_DOMAIN, SERVICE_MEDIA_STOP, {ATTR_ENTITY_ID: speaker}, blocking=True
        )
        await asyncio.wait_for(call, 10)

    assert hass.states.get(speaker).state == MediaPlayerState.IDLE
    assert mock_camera.talk_active is False


async def test_media_stop_leaves_the_siren_playing(
    hass: HomeAssistant,
    identified_entry: MockConfigEntry,
    speaker: str,
    mock_camera: FakeSannceCamera,
    entity_registry: er.EntityRegistry,
) -> None:
    siren = entity_registry.async_get_entity_id(
        SIREN_DOMAIN, DOMAIN, f"{identified_entry.unique_id}_siren"
    )
    sounding = asyncio.Event()
    release = asyncio.Event()

    async def hold(pcm: AsyncIterable[bytes]) -> None:
        async for _ in pcm:
            sounding.set()
            await release.wait()

    mock_camera.play_audio.side_effect = hold
    await hass.services.async_call(
        SIREN_DOMAIN, SERVICE_TURN_ON, {ATTR_ENTITY_ID: siren}, blocking=True
    )
    await sounding.wait()

    await hass.services.async_call(
        MP_DOMAIN, SERVICE_MEDIA_STOP, {ATTR_ENTITY_ID: speaker}, blocking=True
    )
    await hass.async_block_till_done()

    assert identified_entry.runtime_data.audio.playing is True
    assert hass.states.get(siren).state == STATE_ON
    release.set()


async def test_speaker_follows_the_connection(
    hass: HomeAssistant, speaker: str, mock_camera: FakeSannceCamera
) -> None:
    mock_camera.set_available(False)
    await hass.async_block_till_done()

    assert hass.states.get(speaker).state == STATE_UNAVAILABLE


@pytest.mark.parametrize(
    "caps",
    [tuple(cap for cap in ALL_CAPS if cap != "talk"), ()],
    ids=["no_talk", "none"],
)
async def test_no_speaker_without_the_talk_cap(
    hass: HomeAssistant,
    identified_entry: MockConfigEntry,
    mock_camera: FakeSannceCamera,
    entity_registry: er.EntityRegistry,
    caps: tuple[str, ...],
) -> None:
    mock_camera.caps = frozenset(caps)

    await setup_integration(hass, identified_entry)

    assert speaker_id(entity_registry, identified_entry) is None
    assert hass.states.async_entity_ids(MP_DOMAIN) == []
