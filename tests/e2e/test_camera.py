import pytest

from bench.hass_client import wait_for

# start-of-frame markers: every 0xCn except DHT (C4), JPG (C8) and DAC (CC)
FRAME_MARKERS = set(range(0xC0, 0xD0)) - {0xC4, 0xC8, 0xCC}


def jpeg_size(data: bytes) -> tuple[int, int]:
    assert data[:2] == b"\xff\xd8", "not a JPEG"
    index = 2
    while index + 9 <= len(data):
        assert data[index] == 0xFF, f"no JPEG marker at byte {index}"
        marker = data[index + 1]
        if marker in FRAME_MARKERS:
            height = int.from_bytes(data[index + 5 : index + 7])
            width = int.from_bytes(data[index + 7 : index + 9])
            return width, height
        index += 2 + int.from_bytes(data[index + 2 : index + 4])
    raise AssertionError("the JPEG has no frame header")


async def test_the_main_stream_is_clear_and_the_sub_stream_fluent(entry):
    assert entry.entity_ids["main"] == "camera.i91fw_sim_clear"
    assert entry.entity_ids["sub"] == "camera.i91fw_sim_fluent"


@pytest.mark.parametrize(("key", "size"), [("sub", (640, 360)), ("main", (1280, 720))])
async def test_each_snapshot_is_a_jpeg_of_its_stream_size(hass, entry, key, size):
    path = f"/api/camera_proxy/{entry.entity_ids[key]}"

    image = await wait_for(
        lambda: hass.fetch(path),
        lambda body: body is not None,
        60,
        "waiting for a snapshot",
    )

    assert jpeg_size(image) == size


async def test_the_sub_stream_serves_an_hls_playlist(hass, entry):
    url = await hass.stream_url(entry.entity_ids["sub"])

    playlist = await wait_for(
        lambda: hass.fetch(url), lambda body: body is not None, 60, "waiting for HLS"
    )

    assert playlist.startswith(b"#EXTM3U")
