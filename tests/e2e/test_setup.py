import json

import pytest_asyncio

from bench.hass_client import CAMERA_HOST

from . import ENTITY_KEYS, MAC, MODEL, SERIAL, add_by_ip, add_by_search, clear

NEW_PASSWORD = "bench-new-pass"


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


async def test_adding_by_ip_stores_the_default_ports(hass, camera):
    entry = await add_by_ip(hass, camera)

    text = await hass.text(f"/api/diagnostics/config_entry/{entry.entry_id}")

    data = json.loads(text)["data"]["entry"]
    assert (data["nvs_port"], data["http_port"], data["rtsp_port"]) == (3002, 80, 554)


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


async def test_reconfigure_takes_a_new_password(hass, camera):
    entry = await add_by_ip(hass, camera)
    login = await camera.state()
    await camera.set_password(NEW_PASSWORD)
    settings = {
        "host": CAMERA_HOST,
        "username": login["user"],
        "password": "wrong-password",
        "nvs_port": 3002,
        "http_port": 80,
        "rtsp_port": 554,
    }

    form = await hass.start_flow(entry.entry_id)
    wrong = await hass.configure_flow(form["flow_id"], settings)
    done = await hass.configure_flow(
        form["flow_id"], settings | {"password": NEW_PASSWORD}
    )
    # setup reads the stored login, so a stale password fails here
    await hass.reload_entry(entry.entry_id)

    assert form["step_id"] == "reconfigure", form
    assert (wrong["type"], wrong["errors"]) == ("form", {"base": "invalid_auth"})
    assert (done["type"], done["reason"]) == ("abort", "reconfigure_successful")
    assert [listed["state"] for listed in await hass.entries()] == ["loaded"]
    await hass.wait_available(entry.entity_ids["motion"], timeout=30)
