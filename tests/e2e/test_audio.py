import asyncio
from pathlib import Path

import pytest
import pytest_asyncio

from bench.hass_client import CommandError, wait_for

from .sound import peak_frequency, power, read_wav, rms, tone_wav, wav_seconds

MEDIA_DIR = Path(__file__).resolve().parents[2] / "bench" / "media"
TONE_FILE = "tone-440.wav"


@pytest_asyncio.fixture(autouse=True, loop_scope="session")
async def quiet(hass, camera, entry):
    await silence(hass, camera, entry)
    yield
    await silence(hass, camera, entry)


async def silence(hass, camera, entry):
    await camera.talk_busy(False)
    await hass.call("siren", "turn_off", entry.entity_ids["siren"])
    await hass.call("media_player", "media_stop", entry.entity_ids["speaker"])
    await camera.wait_quiet()


async def sound_count(camera):
    return len((await camera.state())["sounds"])


async def sounds_since(camera, count):
    return (await camera.state())["sounds"][count:]


async def play_tone(hass, entry, seconds=1.0):
    (MEDIA_DIR / TONE_FILE).write_bytes(tone_wav(440, seconds))
    await hass.call(
        "media_player",
        "play_media",
        entry.entity_ids["speaker"],
        media_content_id=f"media-source://media_source/local/{TONE_FILE}",
        media_content_type="music",
    )


async def test_the_alarm_tone_plays_800_and_1000_hz_for_its_duration(
    hass, camera, entry
):
    siren = entry.entity_ids["siren"]
    before = await sound_count(camera)

    await hass.call("siren", "turn_on", siren, tone="alarm", duration=2)
    await hass.wait_state(siren, "off", timeout=10)

    rate, samples = read_wav(await camera.audio())
    assert len(samples) == 2 * rate
    wanted = min(power(samples, rate, 800), power(samples, rate, 1000))
    others = (440, 600, 1200, 1500)
    assert wanted > 100 * max(power(samples, rate, freq) for freq in others)
    assert await sounds_since(camera, before) == []


async def test_a_siren_shorter_than_the_replay_plays_its_sound_once(
    hass, camera, entry
):
    siren = entry.entity_ids["siren"]
    before = await sound_count(camera)

    await hass.call("siren", "turn_on", siren, tone="sound_2", duration=2)
    await hass.wait_state(siren, "off", timeout=10)

    assert await sounds_since(camera, before) == [[1, 1]]


async def test_turning_the_siren_off_stops_its_sound(hass, camera, entry):
    siren = entry.entity_ids["siren"]
    before = await sound_count(camera)

    await hass.call("siren", "turn_on", siren, tone="sound_1")
    await hass.call("siren", "turn_off", siren)

    await hass.wait_state(siren, "off", timeout=5)
    assert await sounds_since(camera, before) == [[0, 1], [0, 0]]


async def test_the_speaker_plays_a_media_file(hass, camera, entry):
    await play_tone(hass, entry)

    rate, samples = read_wav(await camera.audio())
    assert abs(len(samples) / rate - 1) <= 0.05
    assert peak_frequency(samples, rate, 200, 1000, 10) == 440


async def test_the_speaker_plays_demo_tts(hass, camera, entry):
    await hass.call(
        "media_player",
        "play_media",
        entry.entity_ids["speaker"],
        media_content_id="media-source://tts/demo?message=bench",
        media_content_type="music",
    )

    rate, samples = read_wav(await camera.audio())
    assert len(samples) / rate > 1
    assert rms(samples) > 500


async def test_a_busy_talk_channel_fails_the_play_with_a_readable_error(
    hass, camera, entry
):
    await camera.talk_busy(True)

    with pytest.raises(CommandError, match="refused the audio channel") as failure:
        await play_tone(hass, entry)

    assert failure.value.code == "home_assistant_error"


async def test_the_speaker_and_the_siren_work_at_the_same_time(hass, camera, entry):
    siren = entry.entity_ids["siren"]
    before = await sound_count(camera)

    async with asyncio.TaskGroup() as group:
        group.create_task(play_tone(hass, entry, seconds=3))
        await wait_for(
            camera.state, lambda state: state["talking"], 5, "waiting for the speaker"
        )
        # the play holds the websocket until it ends, so use the REST API
        await hass.request(
            "POST",
            "/api/services/siren/turn_on",
            {"entity_id": siren, "tone": "sound_1", "duration": 2},
        )

    assert abs(wav_seconds(await camera.audio()) - 3) <= 0.05
    assert await sounds_since(camera, before) == [[0, 1]]
