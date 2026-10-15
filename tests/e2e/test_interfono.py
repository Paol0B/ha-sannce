import pytest_asyncio

from bench.hass_client import wait_for

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
    # go2rtc keeps the backchannel about 30 s after the WebRTC session ends
    await camera.wait_quiet(timeout=60)


async def test_go2rtc_accepts_audio_from_the_client_on_fluent(hass, camera, entry):
    answer = await hass.webrtc_answer(entry.entity_ids["sub"], OFFER)

    audio = answer.split("m=audio", 1)[1]
    assert "a=inactive" not in audio
    assert "a=recvonly" in audio or "a=sendrecv" in audio
    await wait_for(
        camera.state,
        lambda state: state["talking"],
        5,
        "waiting for go2rtc to open the backchannel",
    )


async def test_a_second_talk_on_the_same_camera_also_gets_audio(hass, camera, entry):
    fluent = entry.entity_ids["sub"]

    async with hass.webrtc_session(fluent, OFFER) as first:
        await wait_for(
            camera.state,
            lambda state: state["talking"],
            5,
            "waiting for go2rtc to open the backchannel",
        )
        # go2rtc sets up the backchannel again on the same RTSP session
        async with hass.webrtc_session(fluent, OFFER) as second:
            answers = [first, second]

    for answer in answers:
        audio = answer.split("m=audio", 1)[1]
        assert "a=sendrecv" in audio
        assert "a=inactive" not in audio
