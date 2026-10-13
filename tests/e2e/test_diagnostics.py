import json

import pytest_asyncio

from bench.hass_client import CAMERA_HOST

from . import MAC, SERIAL, add_by_search, clear

REDACTED_KEYS = ("host", "username", "password", "serial", "mac")


@pytest_asyncio.fixture(scope="module", loop_scope="session")
async def found(hass, camera):
    await clear(hass, camera)
    yield await add_by_search(hass, camera)
    await clear(hass, camera)


async def test_diagnostics_redact_the_login_and_the_camera_identity(
    hass, camera, found
):
    text = await hass.text(f"/api/diagnostics/config_entry/{found.entry_id}")

    data = json.loads(text)["data"]["entry"]
    redacted = {key: data[key] for key in REDACTED_KEYS}
    assert redacted == dict.fromkeys(REDACTED_KEYS, "**REDACTED**")
    password = (await camera.state())["password"]
    for secret in (password, SERIAL, MAC, MAC.lower(), CAMERA_HOST):
        assert secret not in text
