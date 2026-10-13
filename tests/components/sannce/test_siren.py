import asyncio
import math
import struct
from collections.abc import AsyncIterable
from unittest.mock import patch

import pytest
from homeassistant.components.siren import DOMAIN as SIREN_DOMAIN
from homeassistant.components.siren import SirenEntityFeature
from homeassistant.const import (
    ATTR_ENTITY_ID,
    ATTR_SUPPORTED_FEATURES,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    STATE_OFF,
    STATE_ON,
    STATE_UNAVAILABLE,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.sannce import lib
from custom_components.sannce.audio import SAMPLE_RATE, SAMPLE_WIDTH
from custom_components.sannce.const import DOMAIN
from custom_components.sannce.siren import (
    _CHUNK_BYTES,
    _TONES,
    _tone_chunks,
    _tone_cycle,
)

from . import setup_integration
from .conftest import ALL_CAPS, FakeSannceCamera


def siren_id(registry: er.EntityRegistry, entry: MockConfigEntry) -> str | None:
    return registry.async_get_entity_id(
        SIREN_DOMAIN, DOMAIN, f"{entry.unique_id}_siren"
    )


async def turn_on(hass: HomeAssistant, entity_id: str, **data: object) -> None:
    await hass.services.async_call(
        SIREN_DOMAIN,
        SERVICE_TURN_ON,
        {ATTR_ENTITY_ID: entity_id, **data},
        blocking=True,
    )


@pytest.fixture
async def siren(
    hass: HomeAssistant,
    identified_entry: MockConfigEntry,
    mock_camera: FakeSannceCamera,
    entity_registry: er.EntityRegistry,
) -> str:
    await setup_integration(hass, identified_entry)
    entity_id = siren_id(entity_registry, identified_entry)
    assert entity_id, "no siren is registered"
    return entity_id


async def test_siren_starts_off_and_declares_features(
    hass: HomeAssistant, siren: str
) -> None:
    state = hass.states.get(siren)

    assert state.state == STATE_OFF
    features = SirenEntityFeature(state.attributes[ATTR_SUPPORTED_FEATURES])
    assert SirenEntityFeature.TURN_ON in features
    assert SirenEntityFeature.TURN_OFF in features
    assert SirenEntityFeature.DURATION in features


async def test_turn_on_streams_a_tone(
    hass: HomeAssistant, siren: str, mock_camera: FakeSannceCamera
) -> None:
    await turn_on(hass, siren, duration=1)
    await hass.async_block_till_done(wait_background_tasks=True)

    assert mock_camera.play_audio.await_count == 1
    pcm = b"".join(mock_camera.played)
    assert len(pcm) == SAMPLE_RATE * 1 * SAMPLE_WIDTH
    assert any(byte != 0 for byte in pcm)
    assert mock_camera.talk_active is False


async def tone_pcm(duration: int, tone: str) -> list[bytes]:
    return [chunk async for chunk in _tone_chunks(duration, tone)]


@pytest.mark.parametrize("tone", list(_TONES))
async def test_tone_repeats_one_cached_cycle(tone: str) -> None:
    freqs, segment = _TONES[tone]
    cycle = int(SAMPLE_RATE * segment) * len(freqs) * SAMPLE_WIDTH
    _tone_cycle.cache_clear()

    with patch.object(math, "sin", wraps=math.sin) as sin:
        chunks = await tone_pcm(10, tone)
        again = await tone_pcm(10, tone)

    pcm = b"".join(chunks)
    assert sin.call_count == cycle // SAMPLE_WIDTH
    assert again == chunks
    assert max(len(chunk) for chunk in chunks) <= _CHUNK_BYTES
    assert len(pcm) == SAMPLE_RATE * 10 * SAMPLE_WIDTH
    assert pcm == pcm[:cycle] * (len(pcm) // cycle)


async def test_tone_ends_inside_a_cycle() -> None:
    with patch.dict(_TONES, {"test": ((440.0, 880.0), 0.33)}):
        chunks = await tone_pcm(1, "test")
        cycle = _tone_cycle("test")
    _tone_cycle.cache_clear()

    pcm = b"".join(chunks)
    assert all(chunks)
    assert len(cycle) < len(pcm) < 2 * len(cycle)
    assert pcm == (cycle * 2)[: SAMPLE_RATE * SAMPLE_WIDTH]


async def test_turn_off_cancels_the_tone(
    hass: HomeAssistant, siren: str, mock_camera: FakeSannceCamera
) -> None:
    release = asyncio.Event()

    async def hold(pcm: AsyncIterable[bytes]) -> None:
        mock_camera.talk_active = True
        try:
            async for chunk in pcm:
                mock_camera.played.append(chunk)
                await release.wait()
        finally:
            mock_camera.talk_active = False

    mock_camera.play_audio.side_effect = hold

    await turn_on(hass, siren, duration=5)
    assert hass.states.get(siren).state == STATE_ON
    assert mock_camera.talk_active is True

    await hass.services.async_call(
        SIREN_DOMAIN, SERVICE_TURN_OFF, {ATTR_ENTITY_ID: siren}, blocking=True
    )

    assert hass.states.get(siren).state == STATE_OFF
    assert mock_camera.talk_active is False
    release.set()


async def test_unload_while_playing_stops_talk(
    hass: HomeAssistant,
    identified_entry: MockConfigEntry,
    siren: str,
    mock_camera: FakeSannceCamera,
) -> None:
    release = asyncio.Event()

    async def hold(pcm: AsyncIterable[bytes]) -> None:
        mock_camera.talk_active = True
        try:
            async for chunk in pcm:
                mock_camera.played.append(chunk)
                await release.wait()
        finally:
            mock_camera.talk_active = False

    mock_camera.play_audio.side_effect = hold
    await turn_on(hass, siren, duration=5)
    assert mock_camera.talk_active is True

    assert await hass.config_entries.async_unload(identified_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_camera.talk_active is False
    release.set()


async def test_siren_follows_the_connection(
    hass: HomeAssistant, siren: str, mock_camera: FakeSannceCamera
) -> None:
    mock_camera.set_available(False)
    await hass.async_block_till_done()

    assert hass.states.get(siren).state == STATE_UNAVAILABLE

    mock_camera.set_available(True)
    await hass.async_block_till_done()

    assert hass.states.get(siren).state == STATE_OFF


@pytest.mark.parametrize(
    "caps",
    [tuple(cap for cap in ALL_CAPS if cap != "talk"), ()],
    ids=["no_talk", "none"],
)
async def test_no_siren_without_the_talk_cap(
    hass: HomeAssistant,
    identified_entry: MockConfigEntry,
    mock_camera: FakeSannceCamera,
    entity_registry: er.EntityRegistry,
    caps: tuple[str, ...],
) -> None:
    mock_camera.caps = frozenset(caps)

    await setup_integration(hass, identified_entry)

    assert siren_id(entity_registry, identified_entry) is None
    assert hass.states.async_entity_ids(SIREN_DOMAIN) == []


def test_tone_is_little_endian_pcm() -> None:
    _tone_cycle.cache_clear()
    cycle = _tone_cycle("alarm")
    peak = int(32767 * 0.6)

    samples = struct.unpack(f"<{len(cycle) // SAMPLE_WIDTH}h", cycle)

    assert samples[:4] == tuple(
        int(peak * math.sin(2 * math.pi * 800.0 * n / SAMPLE_RATE)) for n in range(4)
    )
    # the second segment, 0.25 s in, plays 1000 Hz
    assert samples[2001] == int(peak * math.sin(2 * math.pi * 1000.0 * 2001 / 8000))


async def test_removing_the_siren_while_it_plays_stops_the_tone(
    hass: HomeAssistant,
    siren: str,
    mock_camera: FakeSannceCamera,
    entity_registry: er.EntityRegistry,
) -> None:
    release = asyncio.Event()

    async def hold(pcm: AsyncIterable[bytes]) -> None:
        mock_camera.talk_active = True
        try:
            async for chunk in pcm:
                mock_camera.played.append(chunk)
                await release.wait()
        finally:
            mock_camera.talk_active = False

    mock_camera.play_audio.side_effect = hold
    await turn_on(hass, siren, duration=5)
    assert mock_camera.talk_active is True

    entity_registry.async_remove(siren)
    await hass.async_block_till_done()

    assert mock_camera.talk_active is False
    assert hass.states.get(siren) is None
    release.set()


async def test_a_failed_tone_turns_the_siren_off_and_logs_once(
    hass: HomeAssistant,
    siren: str,
    mock_camera: FakeSannceCamera,
    caplog: pytest.LogCaptureFixture,
) -> None:
    mock_camera.play_audio.side_effect = lib.TalkBusyError("talk is already active")

    await turn_on(hass, siren, duration=1)
    await hass.async_block_till_done(wait_background_tasks=True)

    assert hass.states.get(siren).state == STATE_OFF
    assert caplog.text.count("siren playback failed: talk is already active") == 1
