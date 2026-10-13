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


async def recorded_seconds(camera):
    return wav_seconds(await camera.audio())


async def play_tone(hass, entry):
    (MEDIA_DIR / TONE_FILE).write_bytes(tone_wav(440, 1.0))
    await hass.call(
        "media_player",
        "play_media",
        entry.entity_ids["speaker"],
        media_content_id=f"media-source://media_source/local/{TONE_FILE}",
        media_content_type="music",
    )


@pytest.mark.parametrize(
    ("tone", "low", "high"), [("alarm", 800, 1000), ("chime", 1046, 1318)]
)
async def test_the_siren_plays_its_tone_for_the_duration(
    hass, camera, entry, tone, low, high
):
    siren = entry.entity_ids["siren"]

    await hass.call("siren", "turn_on", siren, tone=tone, duration=2)
    await hass.wait_state(siren, "off", timeout=10)

    rate, samples = read_wav(await camera.audio())
    assert len(samples) == 2 * rate
    others = [freq for freq in (440, 800, 1000, 1046, 1318) if freq not in (low, high)]
    wanted = min(power(samples, rate, low), power(samples, rate, high))
    assert wanted > 100 * max(power(samples, rate, freq) for freq in others)


async def test_turning_the_siren_off_stops_the_sound(hass, camera, entry):
    siren = entry.entity_ids["siren"]
    await hass.call("siren", "turn_on", siren, tone="alarm", duration=10)
    await wait_for(
        lambda: recorded_seconds(camera),
        lambda seconds: seconds >= 1,
        5,
        "waiting for 1 s of siren",
    )

    await hass.call("siren", "turn_off", siren)

    await hass.wait_state(siren, "off", timeout=5)
    assert (await camera.state())["talking"] is False
    assert 1 <= await recorded_seconds(camera) < 3


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

    with pytest.raises(CommandError, match="refused talk") as failure:
        await play_tone(hass, entry)

    assert failure.value.code == "home_assistant_error"


async def test_stopping_the_speaker_leaves_the_siren_playing(hass, camera, entry):
    siren = entry.entity_ids["siren"]
    await hass.call("siren", "turn_on", siren, tone="alarm", duration=10)
    await wait_for(
        camera.state, lambda state: state["talking"], 5, "waiting for the siren"
    )

    await hass.call("media_player", "media_stop", entry.entity_ids["speaker"])

    stopped_at = await recorded_seconds(camera)
    await wait_for(
        lambda: recorded_seconds(camera),
        lambda seconds: seconds >= stopped_at + 0.5,
        5,
        "waiting for more siren audio",
    )
    assert await hass.state(siren) == "on"
