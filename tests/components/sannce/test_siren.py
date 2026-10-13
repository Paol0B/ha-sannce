import asyncio
import math
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

from custom_components.sannce.audio import SAMPLE_RATE, SAMPLE_WIDTH
from custom_components.sannce.const import DOMAIN
from custom_components.sannce.siren import _TONES, _make_tone

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


@pytest.mark.parametrize("tone", list(_TONES))
def test_tone_repeats_one_computed_cycle(tone: str) -> None:
    freqs, segment = _TONES[tone]
    cycle = int(SAMPLE_RATE * segment) * len(freqs) * SAMPLE_WIDTH

    with patch.object(math, "sin", wraps=math.sin) as sin:
        pcm = _make_tone(10, tone)

    assert sin.call_count == cycle // SAMPLE_WIDTH
    assert len(pcm) == SAMPLE_RATE * 10 * SAMPLE_WIDTH
    assert pcm == pcm[:cycle] * (len(pcm) // cycle)


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
