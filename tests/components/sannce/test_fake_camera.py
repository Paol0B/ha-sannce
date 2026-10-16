import asyncio
from collections.abc import AsyncIterator

import pytest

from custom_components.sannce import lib

from .conftest import FakeSannceCamera


def test_fake_has_library_surface() -> None:
    public = {name for name in dir(lib.SannceCamera) if not name.startswith("_")}

    assert public <= set(dir(FakeSannceCamera()))


async def test_fake_pushes_events_and_availability() -> None:
    camera = FakeSannceCamera()
    events: list[lib.Event] = []
    availability: list[bool] = []
    unsubscribe = camera.subscribe(events.append)
    camera.on_availability(availability.append)

    await camera.connect()
    camera.emit(lib.Event("motion", True, 0))
    unsubscribe()
    unsubscribe()
    camera.emit(lib.Event("motion", False, 0))
    await camera.close()

    assert events == [lib.Event("motion", True, 0)]
    assert availability == [True, False]


async def test_fake_setters_change_what_getters_return() -> None:
    camera = FakeSannceCamera()

    await camera.set_floodlight(True, brightness=40)
    await camera.set_detection(person=False)
    await camera.set_sensitivity(20)
    await camera.set_volume(30)
    await camera.set_siren_on_event(True)

    assert await camera.get_floodlight() == lib.Floodlight(on=True, brightness=40)
    assert await camera.get_light_mode() == "color"
    assert await camera.get_detection() == lib.Detection(
        person=False, vehicle=True, motion=False, sensitivity=20
    )
    assert await camera.get_volume() == 30
    assert await camera.get_siren_on_event() is True

    await camera.set_floodlight(False, base_mode="infrared")
    await camera.set_light_mode("smart")

    assert await camera.get_floodlight() == lib.Floodlight(on=False, brightness=40)
    assert await camera.get_light_mode() == "smart"


async def test_fake_keeps_a_custom_mode_when_forced_on() -> None:
    camera = FakeSannceCamera()
    camera.light_mode = "custom"

    await camera.set_floodlight(True)

    assert camera.light_mode == "custom"
    assert camera.brightness == 100


async def test_fake_records_sounds() -> None:
    camera = FakeSannceCamera()

    await camera.play_sound(2)
    await camera.stop_sound(2)

    assert camera.sounds == [(2, 1), (2, 0)]


async def endless(streaming: asyncio.Event) -> AsyncIterator[bytes]:
    yield b"\x00\x01"
    streaming.set()
    await asyncio.Event().wait()


async def test_fake_play_owns_the_speaker_until_it_ends() -> None:
    camera = FakeSannceCamera()
    owners: list[str | None] = []
    camera.speaker.subscribe(owners.append)

    async def once() -> AsyncIterator[bytes]:
        yield b"\x00\x01"

    assert await camera.play_audio(once()) is True

    assert owners == ["play", None]
    assert camera.speaker.owner is None
    assert camera.played == [b"\x00\x01"]
    assert (camera.talk_active, camera.talk_starts, camera.talk_stops) == (
        False,
        1,
        1,
    )


async def test_fake_preempt_ends_the_play_and_gives_talk_the_speaker() -> None:
    camera = FakeSannceCamera()
    streaming = asyncio.Event()
    play = asyncio.create_task(camera.play_audio(endless(streaming)))
    await streaming.wait()

    camera.preempt()

    assert await play is False
    assert camera.speaker.owner == "talk"
    assert camera.talk_active is False
    assert (camera.talk_starts, camera.talk_stops) == (1, 1)


async def test_fake_newer_play_preempts_the_running_one() -> None:
    camera = FakeSannceCamera()
    streaming = asyncio.Event()
    first = asyncio.create_task(camera.play_audio(endless(streaming)))
    await streaming.wait()

    async def once() -> AsyncIterator[bytes]:
        yield b"\x02\x03"

    assert await camera.play_audio(once()) is True

    assert await first is False
    assert camera.played == [b"\x00\x01", b"\x02\x03"]
    assert camera.speaker.owner is None
    assert camera.talk_active is False
    assert (camera.talk_starts, camera.talk_stops) == (2, 2)


async def test_fake_cancelled_play_still_raises() -> None:
    camera = FakeSannceCamera()
    streaming = asyncio.Event()
    play = asyncio.create_task(camera.play_audio(endless(streaming)))
    await streaming.wait()

    play.cancel()

    with pytest.raises(asyncio.CancelledError):
        await play
    assert camera.speaker.owner is None
    assert camera.talk_active is False


async def test_fake_speaker_stops_calling_an_unsubscribed_callback() -> None:
    camera = FakeSannceCamera()
    owners: list[str | None] = []
    unsubscribe = camera.speaker.subscribe(owners.append)

    camera.speaker.set_owner("talk")
    unsubscribe()
    unsubscribe()
    camera.speaker.set_owner(None)

    assert owners == ["talk"]
    assert camera.speaker.subscribers == []


async def test_fake_close_frees_the_speaker() -> None:
    camera = FakeSannceCamera()
    camera.speaker.set_owner("talk")

    await camera.close()

    assert camera.speaker.owner is None


async def test_fake_pulls_one_chunk_before_it_opens_the_backchannel() -> None:
    camera = FakeSannceCamera()
    camera.open_backchannel.side_effect = lib.TalkBusyError("RTSP 453")
    pulled: list[bytes] = []

    async def two() -> AsyncIterator[bytes]:
        for chunk in (b"\x00\x01", b"\x02\x03"):
            pulled.append(chunk)
            yield chunk

    with pytest.raises(lib.TalkBusyError):
        await camera.play_audio(two())

    assert pulled == [b"\x00\x01"]
    assert camera.played == []
    assert camera.talk_active is False


async def test_fake_holds_a_play_at_the_audio_gate() -> None:
    camera = FakeSannceCamera()
    camera.audio_gate = gate = asyncio.Event()

    async def two() -> AsyncIterator[bytes]:
        yield b"\x00\x01"
        yield b"\x02\x03"

    play = asyncio.create_task(camera.play_audio(two()))
    for _ in range(5):
        await asyncio.sleep(0)

    assert camera.played == [b"\x00\x01"]
    assert camera.talk_active is True

    gate.set()
    await play

    assert camera.played == [b"\x00\x01", b"\x02\x03"]
    assert camera.talk_active is False
