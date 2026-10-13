import pytest_asyncio

from bench.hass_client import CAMERA_HOST

from . import ENTITY_KEYS, MAC, MODEL, SERIAL, add_by_ip, add_by_search, clear


@pytest_asyncio.fixture(autouse=True, loop_scope="session")
async def clean(hass, camera):
    await clear(hass, camera)
    yield
    await clear(hass, camera)


async def test_adding_by_ip_creates_the_entry_and_every_entity(hass, camera):
    entry = await add_by_ip(hass, camera)

    assert set(entry.entity_ids) == ENTITY_KEYS
    [listed] = await hass.entries()
    assert (listed["entry_id"], listed["title"], listed["state"]) == (
        entry.entry_id,
        MODEL,
        "loaded",
    )


async def test_adding_by_ip_fills_the_identity_from_the_lan_search(hass, camera):
    entry = await add_by_ip(hass, camera)

    [device] = await hass.devices(entry.entry_id)
    assert (device["model"], device["serial_number"]) == (MODEL, SERIAL)
    assert device["connections"] == [["mac", MAC.lower()]]


async def test_a_wrong_password_shows_invalid_auth(hass, camera):
    login = await camera.state()

    result = await hass.add_camera(CAMERA_HOST, login["user"], "wrong-password")

    assert (result["type"], result["errors"]) == ("form", {"base": "invalid_auth"})
    assert await hass.entries() == []


async def test_lan_search_lists_the_camera_and_fills_its_identity(hass, camera):
    entry = await add_by_search(hass, camera)

    [listed] = await hass.entries()
    assert listed["title"] == MODEL
    [device] = await hass.devices(entry.entry_id)
    assert (device["model"], device["serial_number"]) == (MODEL, SERIAL)
    assert device["connections"] == [["mac", MAC.lower()]]


async def test_the_same_camera_twice_aborts(hass, camera):
    await add_by_ip(hass, camera)
    login = await camera.state()

    result = await hass.add_camera(CAMERA_HOST, login["user"], login["password"])

    assert (result["type"], result["reason"]) == ("abort", "already_configured")
