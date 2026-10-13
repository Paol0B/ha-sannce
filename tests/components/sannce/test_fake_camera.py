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

    await camera.set_light(True)
    await camera.set_light_mode("smart")
    await camera.set_detection(person=False)

    assert await camera.get_light() is True
    assert await camera.get_light_mode() == "smart"
    assert await camera.get_detection() == lib.Detection(
        person=False, vehicle=True, motion=True
    )
