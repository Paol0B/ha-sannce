import asyncio

import pytest_asyncio

from bench.hass_client import POLL_SECONDS

from .sound import peak_frequency, read_wav, rms

OFFER = (
    "v=0\r\no=- 1 1 IN IP4 127.0.0.1\r\ns=-\r\nt=0 0\r\na=group:BUNDLE 0\r\n"
    "m=audio 9 UDP/TLS/RTP/SAVPF 8 0\r\nc=IN IP4 0.0.0.0\r\na=mid:0\r\na=sendrecv\r\n"
    "a=rtcp-mux\r\na=ice-ufrag:abcd\r\na=ice-pwd:abcdefghijklmnopqrstuvwx\r\n"
    "a=fingerprint:sha-256 " + ":".join(["AB"] * 32) + "\r\na=setup:actpass\r\n"
    "a=rtpmap:8 PCMA/8000\r\na=rtpmap:0 PCMU/8000\r\n"
)


@pytest_asyncio.fixture(autouse=True, loop_scope="session")
async def backchannel_released(camera):
    yield
    # the speaker keeps the camera's backchannel open 3 s after the last sound
    await camera.wait_quiet()


async def talking_during(camera, seconds):
    loop = asyncio.get_running_loop()
    end = loop.time() + seconds
    seen = set()
    while loop.time() < end:
        seen.add((await camera.state())["talking"])
        await asyncio.sleep(POLL_SECONDS)
    return seen


async def test_go2rtc_accepts_audio_from_the_client_on_fluent(hass, camera, entry):
    answer = await hass.webrtc_answer(entry.entity_ids["sub"], OFFER)

    audio = answer.split("m=audio", 1)[1]
    assert "a=inactive" not in audio
    assert "a=recvonly" in audio or "a=sendrecv" in audio
    # the relay answers go2rtc's backchannel SETUP, so the camera never sees it
    assert await talking_during(camera, 1) == {False}


async def test_a_second_talk_on_the_same_camera_also_gets_audio(hass, camera, entry):
    fluent = entry.entity_ids["sub"]

    async with hass.webrtc_session(fluent, OFFER) as first:
        assert await talking_during(camera, 1) == {False}
        # go2rtc sets up the backchannel again on the same RTSP session
        async with hass.webrtc_session(fluent, OFFER) as second:
            assert await talking_during(camera, 1) == {False}

    for answer in (first, second):
        audio = answer.split("m=audio", 1)[1]
        assert "a=sendrecv" in audio
        assert "a=inactive" not in audio


async def test_the_siren_plays_right_after_an_intercom_session(hass, camera, entry):
    siren = entry.entity_ids["siren"]
    await hass.webrtc_answer(entry.entity_ids["sub"], OFFER)

    await hass.call("siren", "turn_on", siren, duration=1)
    await hass.wait_state(siren, "off", timeout=10)

    rate, samples = read_wav(await camera.audio())
    assert rms(samples) > 500
    assert peak_frequency(samples, rate, 600, 1200, 10) in (800, 1000)
