import ast
import json
import string
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.components.light import DOMAIN as LIGHT_DOMAIN
from homeassistant.components.media_player import (
    ATTR_MEDIA_CONTENT_ID,
    ATTR_MEDIA_CONTENT_TYPE,
    SERVICE_PLAY_MEDIA,
    MediaType,
)
from homeassistant.components.media_player import DOMAIN as MP_DOMAIN
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import ATTR_ENTITY_ID, SERVICE_TURN_ON
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.update_coordinator import UpdateFailed
from pytest_homeassistant_custom_component.common import MockConfigEntry

import custom_components.sannce as integration
from custom_components.sannce import lib, media_player
from custom_components.sannce.const import DOMAIN

from . import HOST, setup_integration
from .conftest import FakeSannceCamera

INTEGRATION_DIR = Path(integration.__file__).parent
STRINGS = json.loads((INTEGRATION_DIR / "strings.json").read_text())
MESSAGES = {key: value["message"] for key, value in STRINGS["exceptions"].items()}
ERRORS = {
    "ConfigEntryAuthFailed",
    "ConfigEntryError",
    "ConfigEntryNotReady",
    "HomeAssistantError",
    "ServiceValidationError",
    "UpdateFailed",
}


def raised_errors() -> list[tuple[str, ast.Call]]:
    found = []
    for path in sorted(INTEGRATION_DIR.glob("*.py")):
        for node in ast.walk(ast.parse(path.read_text())):
            if (
                isinstance(node, ast.Raise)
                and isinstance(node.exc, ast.Call)
                and isinstance(node.exc.func, ast.Name)
                and node.exc.func.id in ERRORS
            ):
                found.append((f"{path.name}:{node.lineno}", node.exc))
    return found


RAISED = raised_errors()


def keywords(call: ast.Call) -> dict[str, ast.expr]:
    return {keyword.arg: keyword.value for keyword in call.keywords if keyword.arg}


def fields(message: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(message) if name}


def test_the_integration_raises_ten_errors() -> None:
    assert len(RAISED) == 10


@pytest.mark.parametrize(("where", "call"), RAISED, ids=[where for where, _ in RAISED])
def test_each_error_is_translated_with_every_placeholder(
    where: str, call: ast.Call
) -> None:
    given = keywords(call)

    assert not call.args
    assert ast.unparse(given["translation_domain"]) == "DOMAIN"
    key = ast.literal_eval(given["translation_key"])
    placeholders = given["translation_placeholders"]
    assert isinstance(placeholders, ast.Dict)
    names = {ast.literal_eval(name) for name in placeholders.keys if name}
    assert names == fields(MESSAGES[key])


def test_every_message_is_used() -> None:
    used = {ast.literal_eval(keywords(call)["translation_key"]) for _, call in RAISED}

    assert used == set(MESSAGES)


@pytest.mark.parametrize(
    ("error", "state", "key", "reason"),
    [
        (
            lib.AuthError("bad password"),
            ConfigEntryState.SETUP_ERROR,
            "login_failed",
            f"Login to {HOST} failed: bad password",
        ),
        (
            lib.ConnectError("unreachable"),
            ConfigEntryState.SETUP_RETRY,
            "cannot_connect",
            f"Cannot connect to {HOST}: unreachable",
        ),
    ],
    ids=["auth", "connect"],
)
async def test_setup_errors_are_translated(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_camera: FakeSannceCamera,
    error: lib.SannceError,
    state: ConfigEntryState,
    key: str,
    reason: str,
) -> None:
    mock_camera.connect.side_effect = error

    await setup_integration(hass, mock_config_entry)

    assert mock_config_entry.state is state
    assert mock_config_entry.reason == reason
    assert mock_config_entry.error_reason_translation_key == key


async def test_a_failed_poll_is_translated(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_camera: FakeSannceCamera,
) -> None:
    await setup_integration(hass, mock_config_entry)
    mock_camera.get_floodlight.side_effect = lib.ConnectError("unreachable")

    await mock_config_entry.runtime_data.async_refresh()

    error = mock_config_entry.runtime_data.last_exception
    assert isinstance(error, UpdateFailed)
    assert error.translation_key == "settings_read_failed"
    assert str(error) == f"Cannot read settings from {HOST}: unreachable"


async def test_a_failed_command_is_translated(
    hass: HomeAssistant,
    identified_entry: MockConfigEntry,
    mock_camera: FakeSannceCamera,
    entity_registry: er.EntityRegistry,
) -> None:
    await setup_integration(hass, identified_entry)
    light = entity_registry.async_get_entity_id(
        LIGHT_DOMAIN, DOMAIN, f"{identified_entry.unique_id}_floodlight"
    )
    mock_camera.set_floodlight.side_effect = lib.ConnectError("unreachable")

    with pytest.raises(HomeAssistantError) as raised:
        await hass.services.async_call(
            LIGHT_DOMAIN, SERVICE_TURN_ON, {ATTR_ENTITY_ID: light}, blocking=True
        )

    assert raised.value.translation_key == "command_failed"
    assert str(raised.value) == f"Cannot update {light}: unreachable"


async def test_a_failed_play_is_translated(
    hass: HomeAssistant,
    identified_entry: MockConfigEntry,
    mock_camera: FakeSannceCamera,
    entity_registry: er.EntityRegistry,
) -> None:
    await setup_integration(hass, identified_entry)
    speaker = entity_registry.async_get_entity_id(
        MP_DOMAIN, DOMAIN, f"{identified_entry.unique_id}_speaker"
    )
    play = AsyncMock(side_effect=lib.TalkBusyError("talk is already active"))

    with (
        patch.object(media_player, "play_media_to_camera", play),
        pytest.raises(HomeAssistantError) as raised,
    ):
        await hass.services.async_call(
            MP_DOMAIN,
            SERVICE_PLAY_MEDIA,
            {
                ATTR_ENTITY_ID: speaker,
                ATTR_MEDIA_CONTENT_TYPE: MediaType.MUSIC,
                ATTR_MEDIA_CONTENT_ID: "http://host/a.mp3",
            },
            blocking=True,
        )

    assert raised.value.translation_key == "play_failed"
    message = f"Cannot play media on {speaker}: talk is already active"
    assert str(raised.value) == message
