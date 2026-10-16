import asyncio
import inspect
import logging
import math
import struct
from collections.abc import AsyncIterable, AsyncIterator, Callable
from unittest.mock import patch

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.components.media_player import (
    ATTR_MEDIA_CONTENT_ID,
    ATTR_MEDIA_CONTENT_TYPE,
    MediaPlayerState,
    MediaType,
)
from homeassistant.components.media_player import DOMAIN as MP_DOMAIN
from homeassistant.components.media_player import SERVICE_PLAY_MEDIA
from homeassistant.components.siren import DOMAIN as SIREN_DOMAIN
from homeassistant.components.siren import SirenEntityFeature
from homeassistant.const import (
    ATTR_ENTITY_ID,
    ATTR_SUPPORTED_FEATURES,
    SERVICE_MEDIA_STOP,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    STATE_OFF,
    STATE_ON,
    STATE_UNAVAILABLE,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.sannce import audio, lib
from custom_components.sannce import siren as sannce_siren
from custom_components.sannce.audio import SAMPLE_RATE, SAMPLE_WIDTH
from custom_components.sannce.const import DOMAIN
from custom_components.sannce.sannce_aio.backchannel import Backchannel

from . import setup_integration
from .conftest import ALL_CAPS, FakeSannceCamera

SPEAKER = "media_player.i91fw_speaker"
FULL_SCALE = 32767


def without(*caps: str) -> tuple[str, ...]:
    return tuple(cap for cap in ALL_CAPS if cap not in caps)


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


async def turn_off(hass: HomeAssistant, entity_id: str) -> None:
    await hass.services.async_call(
        SIREN_DOMAIN, SERVICE_TURN_OFF, {ATTR_ENTITY_ID: entity_id}, blocking=True
    )


async def pass_time(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, seconds: float
) -> None:
    freezer.tick(seconds)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


async def until(condition: Callable[[], bool]) -> None:
    for _ in range(100):
        if condition():
            return
        await asyncio.sleep(0)
    pytest.fail("the condition never held")


def gate_play(
    mock_camera: FakeSannceCamera, count: int
) -> tuple[list[asyncio.Event], Callable[[], bool]]:
    working = mock_camera.play_sound.side_effect
    gates = [asyncio.Event() for _ in range(count)]

    async def gated(sample: int) -> None:
        call = mock_camera.play_sound.await_count - 1
        if call < count:
            await gates[call].wait()
        await working(sample)

    mock_camera.play_sound.side_effect = gated
    return gates, lambda: mock_camera.play_sound.await_count == count


def hold_audio(mock_camera: FakeSannceCamera) -> asyncio.Event:
    mock_camera.audio_gate = asyncio.Event()
    return mock_camera.audio_gate


async def play_on_speaker(hass: HomeAssistant, media_id: str) -> None:
    await hass.services.async_call(
        MP_DOMAIN,
        SERVICE_PLAY_MEDIA,
        {
            ATTR_ENTITY_ID: SPEAKER,
            ATTR_MEDIA_CONTENT_TYPE: MediaType.MUSIC,
            ATTR_MEDIA_CONTENT_ID: media_id,
        },
        blocking=True,
    )


def feed(*chunks: bytes) -> Callable[[HomeAssistant, str], AsyncIterator[bytes]]:
    async def fake(hass: HomeAssistant, media_id: str) -> AsyncIterator[bytes]:
        for chunk in chunks:
            yield chunk

    return fake


def samples(pcm: bytes) -> list[int]:
    return [sample for (sample,) in struct.iter_unpack("<h", pcm)]


def power(pcm: list[int], frequency: float) -> float:
    # Goertzel: the DFT power at one frequency
    coefficient = 2 * math.cos(2 * math.pi * frequency / SAMPLE_RATE)
    previous = before = 0.0
    for sample in pcm:
        previous, before = sample + coefficient * previous - before, previous
    return previous * previous + before * before - coefficient * previous * before


def peak_frequency(pcm: list[int]) -> int:
    return max(range(200, 2001, 50), key=lambda frequency: power(pcm, frequency))


def played_seconds(mock_camera: FakeSannceCamera) -> float:
    return len(b"".join(mock_camera.played)) / (SAMPLE_RATE * SAMPLE_WIDTH)


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
    assert SirenEntityFeature.TONES in features


@pytest.mark.parametrize(
    ("caps", "tones"),
    [
        (ALL_CAPS, ["alarm", "sound_1", "sound_2", "sound_3"]),
        (without("speaker"), ["sound_1", "sound_2", "sound_3"]),
        (without("siren"), ["alarm"]),
    ],
    ids=["both", "no_speaker", "no_sounds"],
)
async def test_the_tones_follow_the_caps(
    hass: HomeAssistant,
    identified_entry: MockConfigEntry,
    mock_camera: FakeSannceCamera,
    entity_registry: er.EntityRegistry,
    caps: tuple[str, ...],
    tones: list[str],
) -> None:
    mock_camera.caps = frozenset(caps)

    await setup_integration(hass, identified_entry)

    entity_id = siren_id(entity_registry, identified_entry)
    assert entity_id, "no siren is registered"
    assert hass.states.get(entity_id).attributes["available_tones"] == tones


async def test_the_default_tone_is_the_alarm(
    hass: HomeAssistant, siren: str, mock_camera: FakeSannceCamera
) -> None:
    hold_audio(mock_camera)

    await turn_on(hass, siren)

    mock_camera.play_audio.assert_awaited_once()
    mock_camera.play_sound.assert_not_awaited()
    assert hass.states.get(siren).state == STATE_ON


async def test_without_a_speaker_the_default_tone_is_the_first_sound(
    hass: HomeAssistant,
    identified_entry: MockConfigEntry,
    mock_camera: FakeSannceCamera,
    entity_registry: er.EntityRegistry,
) -> None:
    mock_camera.caps = frozenset(without("speaker"))
    await setup_integration(hass, identified_entry)
    entity_id = siren_id(entity_registry, identified_entry)
    assert entity_id, "no siren is registered"

    await turn_on(hass, entity_id)

    mock_camera.play_sound.assert_awaited_once_with(0)
    mock_camera.play_audio.assert_not_awaited()
    assert hass.states.get(entity_id).state == STATE_ON


async def test_turn_on_with_a_tone_plays_that_sound(
    hass: HomeAssistant, siren: str, mock_camera: FakeSannceCamera
) -> None:
    await turn_on(hass, siren, tone="sound_3")

    mock_camera.play_sound.assert_awaited_with(2)


async def test_the_sound_repeats_until_the_duration_ends(
    hass: HomeAssistant,
    siren: str,
    mock_camera: FakeSannceCamera,
    freezer: FrozenDateTimeFactory,
) -> None:
    await turn_on(hass, siren, tone="sound_1", duration=12)
    for _ in range(3):
        await pass_time(hass, freezer, 5)

    assert mock_camera.play_sound.await_count == 3
    assert hass.states.get(siren).state == STATE_OFF


async def test_without_a_duration_it_keeps_sounding_until_turned_off(
    hass: HomeAssistant,
    siren: str,
    mock_camera: FakeSannceCamera,
    freezer: FrozenDateTimeFactory,
) -> None:
    await turn_on(hass, siren, tone="sound_1")
    for _ in range(20):
        await pass_time(hass, freezer, 5)

    assert mock_camera.play_sound.await_count == 21
    assert hass.states.get(siren).state == STATE_ON

    await turn_off(hass, siren)

    assert hass.states.get(siren).state == STATE_OFF


async def test_without_a_duration_it_stops_after_300_seconds(
    hass: HomeAssistant,
    siren: str,
    freezer: FrozenDateTimeFactory,
) -> None:
    await turn_on(hass, siren, tone="sound_1")
    await pass_time(hass, freezer, 301)

    assert hass.states.get(siren).state == STATE_OFF


async def test_the_repeat_runs_for_300_seconds_and_no_longer(
    hass: HomeAssistant,
    siren: str,
    mock_camera: FakeSannceCamera,
    freezer: FrozenDateTimeFactory,
) -> None:
    await turn_on(hass, siren, tone="sound_1")
    for _ in range(60):
        await pass_time(hass, freezer, 5)

    assert hass.states.get(siren).state == STATE_OFF
    assert mock_camera.play_sound.await_count == 60


async def test_a_longer_duration_is_capped_at_300_seconds(
    hass: HomeAssistant,
    siren: str,
    freezer: FrozenDateTimeFactory,
) -> None:
    await turn_on(hass, siren, tone="sound_1", duration=1000)
    await pass_time(hass, freezer, 301)

    assert hass.states.get(siren).state == STATE_OFF


async def test_turn_off_stops_the_repeat_and_sends_stop(
    hass: HomeAssistant,
    siren: str,
    mock_camera: FakeSannceCamera,
    freezer: FrozenDateTimeFactory,
) -> None:
    await turn_on(hass, siren, tone="sound_2")
    await turn_off(hass, siren)
    await pass_time(hass, freezer, 10)

    assert mock_camera.play_sound.await_count == 1
    mock_camera.stop_sound.assert_awaited_with(1)
    assert hass.states.get(siren).state == STATE_OFF


async def test_a_refused_stop_still_turns_the_siren_off(
    hass: HomeAssistant, siren: str, mock_camera: FakeSannceCamera
) -> None:
    mock_camera.stop_sound.side_effect = lib.ProtocolError("refused")
    await turn_on(hass, siren, tone="sound_1")

    await turn_off(hass, siren)

    assert hass.states.get(siren).state == STATE_OFF


async def test_a_second_turn_on_replaces_the_first(
    hass: HomeAssistant,
    siren: str,
    mock_camera: FakeSannceCamera,
    freezer: FrozenDateTimeFactory,
) -> None:
    await turn_on(hass, siren, tone="sound_1")
    await turn_on(hass, siren, tone="sound_2")
    await pass_time(hass, freezer, 5)

    assert [c.args[0] for c in mock_camera.play_sound.await_args_list] == [0, 1, 1]


async def test_a_failed_first_play_raises_a_readable_error(
    hass: HomeAssistant,
    siren: str,
    mock_camera: FakeSannceCamera,
    translations: None,
) -> None:
    mock_camera.play_sound.side_effect = lib.ProtocolError("Device Error")

    with pytest.raises(HomeAssistantError, match="Device Error") as raised:
        await turn_on(hass, siren, tone="sound_1")

    assert raised.value.translation_key == "siren_failed"
    assert str(raised.value) == f"Cannot sound {siren}: Device Error"
    assert hass.states.get(siren).state == STATE_OFF


async def test_a_failed_turn_on_while_sounding_turns_the_siren_off(
    hass: HomeAssistant,
    siren: str,
    mock_camera: FakeSannceCamera,
    freezer: FrozenDateTimeFactory,
) -> None:
    await turn_on(hass, siren, tone="sound_1")
    mock_camera.play_sound.side_effect = lib.ConnectError("gone")

    with pytest.raises(HomeAssistantError):
        await turn_on(hass, siren, tone="sound_2")
    await pass_time(hass, freezer, 10)

    assert hass.states.get(siren).state == STATE_OFF
    assert mock_camera.play_sound.await_count == 2


async def test_a_failed_replay_ends_the_siren(
    hass: HomeAssistant,
    siren: str,
    mock_camera: FakeSannceCamera,
    freezer: FrozenDateTimeFactory,
    caplog: pytest.LogCaptureFixture,
) -> None:
    await turn_on(hass, siren, tone="sound_1", duration=20)
    mock_camera.play_sound.side_effect = lib.ConnectError("gone")

    await pass_time(hass, freezer, 5)
    await pass_time(hass, freezer, 5)

    assert hass.states.get(siren).state == STATE_OFF
    assert mock_camera.play_sound.await_count == 2
    assert caplog.text.count("siren replay failed: gone") == 1


async def test_turn_off_during_a_replay_leaves_the_siren_off(
    hass: HomeAssistant,
    siren: str,
    mock_camera: FakeSannceCamera,
    freezer: FrozenDateTimeFactory,
) -> None:
    await turn_on(hass, siren, tone="sound_1", duration=60)
    release = asyncio.Event()

    async def slow_play(sample: int) -> None:
        await release.wait()

    mock_camera.play_sound.side_effect = slow_play
    freezer.tick(5)
    async_fire_time_changed(hass)
    await asyncio.sleep(0)
    await turn_off(hass, siren)
    release.set()
    await hass.async_block_till_done()
    await pass_time(hass, freezer, 10)

    assert mock_camera.play_sound.await_count == 2
    assert mock_camera.stop_sound.await_count == 2
    assert hass.states.get(siren).state == STATE_OFF


async def test_a_turn_on_during_a_replay_leaves_one_repeat_chain(
    hass: HomeAssistant,
    siren: str,
    mock_camera: FakeSannceCamera,
    freezer: FrozenDateTimeFactory,
) -> None:
    await turn_on(hass, siren, tone="sound_1", duration=60)
    working = mock_camera.play_sound.side_effect
    release = asyncio.Event()

    async def slow_play(sample: int) -> None:
        await release.wait()

    mock_camera.play_sound.side_effect = slow_play
    freezer.tick(5)
    async_fire_time_changed(hass)
    await asyncio.sleep(0)
    mock_camera.play_sound.side_effect = working
    await turn_on(hass, siren, tone="sound_2")
    release.set()
    await hass.async_block_till_done()
    await pass_time(hass, freezer, 5)

    assert [c.args[0] for c in mock_camera.play_sound.await_args_list] == [0, 0, 1, 1]
    await turn_off(hass, siren)
    await pass_time(hass, freezer, 10)
    assert mock_camera.play_sound.await_count == 4


@pytest.mark.parametrize(
    "newest_first", [False, True], ids=["oldest_first", "newest_first"]
)
async def test_two_concurrent_turn_ons_leave_one_repeat_chain(
    hass: HomeAssistant,
    siren: str,
    mock_camera: FakeSannceCamera,
    freezer: FrozenDateTimeFactory,
    newest_first: bool,
) -> None:
    gates, both_started = gate_play(mock_camera, 2)
    calls = [
        hass.async_create_task(turn_on(hass, siren, tone="sound_1", duration=60)),
        hass.async_create_task(turn_on(hass, siren, tone="sound_2", duration=60)),
    ]
    await until(both_started)

    for gate in reversed(gates) if newest_first else gates:
        gate.set()
        await asyncio.sleep(0)
    await asyncio.gather(*calls)
    await pass_time(hass, freezer, 5)
    await pass_time(hass, freezer, 5)

    assert hass.states.get(siren).state == STATE_ON
    assert [c.args[0] for c in mock_camera.play_sound.await_args_list] == [0, 1, 1, 1]

    await turn_off(hass, siren)
    await pass_time(hass, freezer, 10)

    assert mock_camera.play_sound.await_count == 4
    assert hass.states.get(siren).state == STATE_OFF


async def test_turn_off_during_the_first_play_leaves_the_siren_off(
    hass: HomeAssistant,
    siren: str,
    mock_camera: FakeSannceCamera,
    freezer: FrozenDateTimeFactory,
) -> None:
    (gate,), started = gate_play(mock_camera, 1)
    call = hass.async_create_task(turn_on(hass, siren, tone="sound_2"))
    await until(started)

    await turn_off(hass, siren)
    gate.set()
    await call
    await pass_time(hass, freezer, 5)
    await pass_time(hass, freezer, 5)

    assert hass.states.get(siren).state == STATE_OFF
    assert mock_camera.play_sound.await_count == 1
    assert mock_camera.stop_sound.await_args_list[-1].args == (1,)


async def test_removing_the_siren_during_the_first_play_leaves_no_timer(
    hass: HomeAssistant,
    siren: str,
    mock_camera: FakeSannceCamera,
    entity_registry: er.EntityRegistry,
    freezer: FrozenDateTimeFactory,
) -> None:
    (gate,), started = gate_play(mock_camera, 1)
    call = hass.async_create_task(turn_on(hass, siren, tone="sound_3"))
    await until(started)

    entity_registry.async_remove(siren)
    await until(lambda: hass.states.get(siren) is None)
    gate.set()
    await call
    await pass_time(hass, freezer, 10)

    assert mock_camera.play_sound.await_count == 1
    assert mock_camera.stop_sound.await_args_list[-1].args == (2,)


async def test_a_turn_on_that_fails_stops_an_older_turn_on_that_lands_late(
    hass: HomeAssistant,
    siren: str,
    mock_camera: FakeSannceCamera,
    freezer: FrozenDateTimeFactory,
) -> None:
    (gate,), started = gate_play(mock_camera, 1)
    older = hass.async_create_task(turn_on(hass, siren, tone="sound_2"))
    await until(started)
    mock_camera.play_sound.side_effect = lib.ConnectError("gone")

    with pytest.raises(HomeAssistantError):
        await turn_on(hass, siren, tone="sound_1")
    gate.set()
    await older
    await pass_time(hass, freezer, 10)

    assert hass.states.get(siren).state == STATE_OFF
    assert mock_camera.play_sound.await_count == 2
    assert mock_camera.stop_sound.await_args_list[-1].args == (1,)


async def test_a_replay_that_outlasts_the_duration_ends_the_siren(
    hass: HomeAssistant,
    siren: str,
    mock_camera: FakeSannceCamera,
    freezer: FrozenDateTimeFactory,
) -> None:
    await turn_on(hass, siren, tone="sound_1", duration=7)

    def slow_play(sample: int) -> None:
        freezer.tick(3)

    mock_camera.play_sound.side_effect = slow_play
    await pass_time(hass, freezer, 5)
    await pass_time(hass, freezer, 10)

    assert mock_camera.play_sound.await_count == 2
    assert hass.states.get(siren).state == STATE_OFF


async def test_removing_the_siren_stops_the_repeat(
    hass: HomeAssistant,
    siren: str,
    mock_camera: FakeSannceCamera,
    entity_registry: er.EntityRegistry,
    freezer: FrozenDateTimeFactory,
) -> None:
    await turn_on(hass, siren, tone="sound_1")

    entity_registry.async_remove(siren)
    await hass.async_block_till_done()
    await pass_time(hass, freezer, 10)

    assert hass.states.get(siren) is None
    assert mock_camera.play_sound.await_count == 1


async def test_unloading_stops_the_repeat(
    hass: HomeAssistant,
    identified_entry: MockConfigEntry,
    siren: str,
    mock_camera: FakeSannceCamera,
    freezer: FrozenDateTimeFactory,
) -> None:
    await turn_on(hass, siren, tone="sound_1")

    assert await hass.config_entries.async_unload(identified_entry.entry_id)
    await hass.async_block_till_done()
    await pass_time(hass, freezer, 10)

    assert mock_camera.play_sound.await_count == 1


async def test_siren_follows_the_connection(
    hass: HomeAssistant, siren: str, mock_camera: FakeSannceCamera
) -> None:
    mock_camera.set_available(False)
    await hass.async_block_till_done()

    assert hass.states.get(siren).state == STATE_UNAVAILABLE

    mock_camera.set_available(True)
    await hass.async_block_till_done()

    assert hass.states.get(siren).state == STATE_OFF


async def test_losing_the_connection_ends_the_siren(
    hass: HomeAssistant,
    siren: str,
    mock_camera: FakeSannceCamera,
    freezer: FrozenDateTimeFactory,
) -> None:
    await turn_on(hass, siren, tone="sound_2")

    mock_camera.set_available(False)
    await hass.async_block_till_done()
    await pass_time(hass, freezer, 5)
    await pass_time(hass, freezer, 5)

    assert mock_camera.play_sound.await_count == 1
    mock_camera.stop_sound.assert_awaited_once_with(1)

    mock_camera.set_available(True)
    await hass.async_block_till_done()

    assert hass.states.get(siren).state == STATE_OFF


async def test_losing_the_connection_during_the_first_play_stops_that_sound(
    hass: HomeAssistant,
    siren: str,
    mock_camera: FakeSannceCamera,
    freezer: FrozenDateTimeFactory,
) -> None:
    (gate,), started = gate_play(mock_camera, 1)
    call = hass.async_create_task(turn_on(hass, siren, tone="sound_3"))
    await until(started)

    mock_camera.set_available(False)
    gate.set()
    await call
    await pass_time(hass, freezer, 10)
    mock_camera.set_available(True)
    await hass.async_block_till_done()

    assert mock_camera.play_sound.await_count == 1
    assert [c.args for c in mock_camera.stop_sound.await_args_list] == [(2,)]
    assert hass.states.get(siren).state == STATE_OFF


async def test_a_failed_stop_after_a_drop_is_logged_at_debug(
    hass: HomeAssistant,
    siren: str,
    mock_camera: FakeSannceCamera,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG, logger="custom_components.sannce.siren")
    await turn_on(hass, siren, tone="sound_1")
    mock_camera.stop_sound.side_effect = lib.ConnectError("gone")

    mock_camera.set_available(False)
    await hass.async_block_till_done()

    assert "stopping sound 0 failed: gone" in caplog.text
    mock_camera.set_available(True)
    await hass.async_block_till_done()
    assert hass.states.get(siren).state == STATE_OFF


@pytest.mark.parametrize(
    "caps",
    [without("siren", "speaker"), ()],
    ids=["no_sounds_no_speaker", "none"],
)
async def test_no_siren_without_sounds_or_a_speaker(
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


async def test_the_alarm_alternates_800_and_1000_hz_loudly(
    hass: HomeAssistant, siren: str, mock_camera: FakeSannceCamera
) -> None:
    await turn_on(hass, siren, tone="alarm", duration=1)
    await hass.async_block_till_done(wait_background_tasks=True)

    pcm = samples(b"".join(mock_camera.played))
    quarter = SAMPLE_RATE // 4
    assert len(pcm) == SAMPLE_RATE
    peaks = [peak_frequency(pcm[n : n + quarter]) for n in range(0, len(pcm), quarter)]
    assert peaks == [800, 1000, 800, 1000]
    assert 0.75 * FULL_SCALE < max(abs(sample) for sample in pcm) <= 0.85 * FULL_SCALE


async def test_the_alarm_and_the_state_end_with_the_duration(
    hass: HomeAssistant, siren: str, mock_camera: FakeSannceCamera
) -> None:
    release = hold_audio(mock_camera)
    await turn_on(hass, siren, tone="alarm", duration=2)

    assert hass.states.get(siren).state == STATE_ON
    assert mock_camera.talk_active is True

    release.set()
    await hass.async_block_till_done(wait_background_tasks=True)

    assert played_seconds(mock_camera) == 2
    assert mock_camera.talk_active is False
    assert hass.states.get(siren).state == STATE_OFF


@pytest.mark.parametrize("data", [{}, {"duration": 1000}], ids=["unset", "too_long"])
async def test_the_alarm_lasts_300_seconds_at_most(
    hass: HomeAssistant,
    siren: str,
    mock_camera: FakeSannceCamera,
    data: dict[str, int],
) -> None:
    await turn_on(hass, siren, tone="alarm", **data)
    await hass.async_block_till_done(wait_background_tasks=True)

    assert played_seconds(mock_camera) == 300


async def test_turn_off_stops_the_alarm(
    hass: HomeAssistant, siren: str, mock_camera: FakeSannceCamera
) -> None:
    hold_audio(mock_camera)
    await turn_on(hass, siren, tone="alarm")

    await turn_off(hass, siren)

    assert hass.states.get(siren).state == STATE_OFF
    assert mock_camera.talk_active is False
    assert (mock_camera.talk_starts, mock_camera.talk_stops) == (1, 1)
    mock_camera.stop_sound.assert_not_awaited()


async def test_a_speaker_play_replaces_the_alarm(
    hass: HomeAssistant, siren: str, mock_camera: FakeSannceCamera
) -> None:
    release = hold_audio(mock_camera)
    await turn_on(hass, siren, tone="alarm")

    with patch.object(audio, "_ffmpeg_pcm", feed(b"\x01\x02")):
        play = hass.async_create_task(play_on_speaker(hass, "http://host/tts.mp3"))
        await until(lambda: mock_camera.talk_starts == 2)

        assert hass.states.get(siren).state == STATE_OFF
        assert mock_camera.played[-1] == b"\x01\x02"

        release.set()
        await play

    assert hass.states.get(siren).state == STATE_OFF
    assert mock_camera.talk_stops == 2


async def test_the_alarm_replaces_a_speaker_play(
    hass: HomeAssistant, siren: str, mock_camera: FakeSannceCamera
) -> None:
    hold_audio(mock_camera)

    with patch.object(audio, "_ffmpeg_pcm", feed(b"\x01\x02")):
        play = hass.async_create_task(play_on_speaker(hass, "http://host/tts.mp3"))
        await until(lambda: mock_camera.talk_active)

        await turn_on(hass, siren, tone="alarm")
        await play

    assert hass.states.get(siren).state == STATE_ON
    assert hass.states.get(SPEAKER).state == MediaPlayerState.IDLE
    assert (mock_camera.talk_starts, mock_camera.talk_stops) == (2, 1)


async def test_a_siren_preempted_by_talk_turns_off_without_an_error(
    hass: HomeAssistant,
    siren: str,
    mock_camera: FakeSannceCamera,
    caplog: pytest.LogCaptureFixture,
) -> None:
    hold_audio(mock_camera)
    await turn_on(hass, siren, tone="alarm")
    assert hass.states.get(siren).state == STATE_ON

    mock_camera.preempt()
    await hass.async_block_till_done(wait_background_tasks=True)

    assert hass.states.get(siren).state == STATE_OFF
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]


async def test_media_stop_leaves_the_alarm_playing(
    hass: HomeAssistant, siren: str, mock_camera: FakeSannceCamera
) -> None:
    hold_audio(mock_camera)
    await turn_on(hass, siren, tone="alarm")

    await hass.services.async_call(
        MP_DOMAIN, SERVICE_MEDIA_STOP, {ATTR_ENTITY_ID: SPEAKER}, blocking=True
    )

    assert hass.states.get(siren).state == STATE_ON
    assert mock_camera.talk_active is True


@pytest.mark.usefixtures("translations")
async def test_a_refused_audio_channel_fails_the_alarm(
    hass: HomeAssistant, siren: str, mock_camera: FakeSannceCamera
) -> None:
    mock_camera.play_audio.side_effect = lib.TalkBusyError(
        "the camera refused the audio channel: RTSP 453"
    )

    with pytest.raises(HomeAssistantError) as raised:
        await turn_on(hass, siren, tone="alarm")

    assert raised.value.translation_key == "siren_failed"
    assert str(raised.value) == (
        f"Cannot sound {siren}: the camera refused the audio channel: RTSP 453"
    )
    assert hass.states.get(siren).state == STATE_OFF


async def test_losing_the_connection_stops_the_alarm(
    hass: HomeAssistant, siren: str, mock_camera: FakeSannceCamera
) -> None:
    hold_audio(mock_camera)
    await turn_on(hass, siren, tone="alarm")

    mock_camera.set_available(False)
    await hass.async_block_till_done()

    assert mock_camera.talk_active is False

    mock_camera.set_available(True)
    await hass.async_block_till_done()

    assert hass.states.get(siren).state == STATE_OFF


async def test_switching_between_the_alarm_and_a_sound_keeps_one_sounding(
    hass: HomeAssistant,
    siren: str,
    mock_camera: FakeSannceCamera,
    freezer: FrozenDateTimeFactory,
) -> None:
    hold_audio(mock_camera)
    await turn_on(hass, siren, tone="alarm")

    await turn_on(hass, siren, tone="sound_2")

    assert mock_camera.talk_active is False
    assert mock_camera.sounds == [(1, 1)]
    assert hass.states.get(siren).state == STATE_ON

    await turn_on(hass, siren, tone="alarm")
    await pass_time(hass, freezer, 10)

    assert mock_camera.sounds == [(1, 1), (1, 0)]
    assert mock_camera.talk_active is True
    assert (mock_camera.talk_starts, mock_camera.talk_stops) == (2, 1)
    assert hass.states.get(siren).state == STATE_ON

    await turn_off(hass, siren)

    assert mock_camera.talk_active is False
    assert mock_camera.sounds == [(1, 1), (1, 0)]


async def test_a_sound_that_lands_after_an_alarm_turn_on_is_stopped(
    hass: HomeAssistant, siren: str, mock_camera: FakeSannceCamera
) -> None:
    hold_audio(mock_camera)
    (gate,), started = gate_play(mock_camera, 1)
    older = hass.async_create_task(turn_on(hass, siren, tone="sound_2"))
    await until(started)

    await turn_on(hass, siren, tone="alarm")
    gate.set()
    await older

    assert mock_camera.sounds[-2:] == [(1, 1), (1, 0)]
    assert mock_camera.talk_active is True
    assert hass.states.get(siren).state == STATE_ON


async def test_a_turn_off_while_the_old_sound_stops_keeps_the_alarm_silent(
    hass: HomeAssistant, siren: str, mock_camera: FakeSannceCamera
) -> None:
    await turn_on(hass, siren, tone="sound_2")
    release = asyncio.Event()

    async def slow_stop(sample: int) -> None:
        await release.wait()

    mock_camera.stop_sound.side_effect = slow_stop
    call = hass.async_create_task(turn_on(hass, siren, tone="alarm"))
    await until(lambda: mock_camera.stop_sound.await_count == 1)

    await turn_off(hass, siren)
    release.set()
    await call

    mock_camera.play_audio.assert_not_awaited()
    assert hass.states.get(siren).state == STATE_OFF


async def test_a_newer_alarm_replaces_one_that_has_not_started(
    hass: HomeAssistant, siren: str, mock_camera: FakeSannceCamera
) -> None:
    accept = asyncio.Event()
    working = mock_camera.play_audio.side_effect

    async def slow_open(pcm: AsyncIterable[bytes]) -> None:
        if mock_camera.play_audio.await_count == 1:
            await accept.wait()
        await working(pcm)

    mock_camera.play_audio.side_effect = slow_open
    hold_audio(mock_camera)
    older = hass.async_create_task(turn_on(hass, siren, tone="alarm"))
    await until(lambda: mock_camera.play_audio.await_count == 1)

    await turn_on(hass, siren, tone="alarm")
    await older

    assert hass.states.get(siren).state == STATE_ON
    assert mock_camera.talk_active is True
    assert mock_camera.talk_starts == 1


async def test_the_alarm_turn_on_waits_for_the_camera_to_take_the_tone(
    hass: HomeAssistant, siren: str, mock_camera: FakeSannceCamera
) -> None:
    accept = asyncio.Event()
    working = mock_camera.play_audio.side_effect

    async def slow_open(pcm: AsyncIterable[bytes]) -> None:
        await accept.wait()
        await working(pcm)

    mock_camera.play_audio.side_effect = slow_open
    hold_audio(mock_camera)
    call = hass.async_create_task(turn_on(hass, siren, tone="alarm"))
    await until(lambda: mock_camera.play_audio.await_count == 1)

    assert not call.done()
    assert hass.states.get(siren).state == STATE_OFF

    accept.set()
    await call

    assert hass.states.get(siren).state == STATE_ON


@pytest.mark.usefixtures("translations")
async def test_an_unanswered_alarm_start_times_out_and_stops(
    hass: HomeAssistant, siren: str, mock_camera: FakeSannceCamera
) -> None:
    async def stall(pcm: AsyncIterable[bytes]) -> None:
        mock_camera.talk_active = True
        try:
            await asyncio.Event().wait()
        finally:
            mock_camera.talk_active = False

    mock_camera.play_audio.side_effect = stall

    with (
        patch.object(sannce_siren, "_START_SECONDS", 0.05),
        pytest.raises(HomeAssistantError) as raised,
    ):
        await turn_on(hass, siren, tone="alarm")

    assert raised.value.translation_key == "siren_failed"
    assert str(raised.value) == f"Cannot sound {siren}: the alarm tone did not start in 0.05 s"
    assert mock_camera.talk_active is False
    assert hass.states.get(siren).state == STATE_OFF


def test_the_start_bound_outlasts_a_backchannel_connect_and_reply() -> None:
    timeout = inspect.signature(Backchannel).parameters["timeout"].default

    assert sannce_siren._START_SECONDS > 2 * timeout


async def test_a_cancelled_alarm_turn_on_stops_the_tone(
    hass: HomeAssistant, siren: str, mock_camera: FakeSannceCamera
) -> None:
    accept = asyncio.Event()

    async def slow_open(pcm: AsyncIterable[bytes]) -> None:
        mock_camera.talk_active = True
        try:
            await accept.wait()
            async for chunk in pcm:
                mock_camera.played.append(chunk)
        finally:
            mock_camera.talk_active = False

    mock_camera.play_audio.side_effect = slow_open
    call = hass.async_create_task(turn_on(hass, siren, tone="alarm"))
    await until(lambda: mock_camera.talk_active)

    call.cancel()
    with pytest.raises(asyncio.CancelledError):
        await call
    accept.set()
    await hass.async_block_till_done(wait_background_tasks=True)

    assert mock_camera.played == []
    assert mock_camera.talk_active is False
    assert hass.states.get(siren).state == STATE_OFF


async def test_an_alarm_failure_after_the_start_is_logged(
    hass: HomeAssistant,
    siren: str,
    mock_camera: FakeSannceCamera,
    caplog: pytest.LogCaptureFixture,
) -> None:
    release = asyncio.Event()

    async def drop(pcm: AsyncIterable[bytes]) -> None:
        async for _ in pcm:
            await release.wait()
            raise lib.ConnectError("audio send failed")

    mock_camera.play_audio.side_effect = drop
    await turn_on(hass, siren, tone="alarm")
    assert hass.states.get(siren).state == STATE_ON

    release.set()
    await hass.async_block_till_done(wait_background_tasks=True)

    assert hass.states.get(siren).state == STATE_OFF
    assert caplog.text.count("siren tone failed: audio send failed") == 1


async def test_an_alarm_that_ends_before_it_starts_leaves_the_siren_off(
    hass: HomeAssistant, siren: str, mock_camera: FakeSannceCamera
) -> None:
    mock_camera.play_audio.side_effect = None

    await turn_on(hass, siren, tone="alarm")

    assert hass.states.get(siren).state == STATE_OFF


async def test_removing_the_siren_stops_the_alarm(
    hass: HomeAssistant,
    siren: str,
    mock_camera: FakeSannceCamera,
    entity_registry: er.EntityRegistry,
) -> None:
    hold_audio(mock_camera)
    await turn_on(hass, siren, tone="alarm")

    entity_registry.async_remove(siren)
    await hass.async_block_till_done()

    assert hass.states.get(siren) is None
    assert mock_camera.talk_active is False


async def test_losing_the_connection_during_the_alarm_start_stops_it(
    hass: HomeAssistant, siren: str, mock_camera: FakeSannceCamera
) -> None:
    accept = asyncio.Event()
    working = mock_camera.play_audio.side_effect

    async def slow_open(pcm: AsyncIterable[bytes]) -> None:
        await accept.wait()
        await working(pcm)

    mock_camera.play_audio.side_effect = slow_open
    call = hass.async_create_task(turn_on(hass, siren, tone="alarm"))
    await until(lambda: mock_camera.play_audio.await_count == 1)

    mock_camera.set_available(False)
    accept.set()
    await call
    await hass.async_block_till_done(wait_background_tasks=True)
    mock_camera.set_available(True)
    await hass.async_block_till_done()

    assert mock_camera.played == []
    assert hass.states.get(siren).state == STATE_OFF


async def test_cancelling_an_older_alarm_turn_on_leaves_the_newer_one(
    hass: HomeAssistant, siren: str, mock_camera: FakeSannceCamera
) -> None:
    closing = asyncio.Event()
    working = mock_camera.play_audio.side_effect

    async def slow_close(pcm: AsyncIterable[bytes]) -> None:
        if mock_camera.play_audio.await_count == 1:
            try:
                await asyncio.Event().wait()
            finally:
                await closing.wait()
        await working(pcm)

    mock_camera.play_audio.side_effect = slow_close
    hold_audio(mock_camera)
    older = hass.async_create_task(turn_on(hass, siren, tone="alarm"))
    await until(lambda: mock_camera.play_audio.await_count == 1)
    newer = hass.async_create_task(turn_on(hass, siren, tone="alarm"))
    for _ in range(10):
        await asyncio.sleep(0)

    older.cancel()
    closing.set()
    with pytest.raises(asyncio.CancelledError):
        await older
    await newer
    await hass.async_block_till_done()

    assert mock_camera.talk_active is True
    assert hass.states.get(siren).state == STATE_ON
