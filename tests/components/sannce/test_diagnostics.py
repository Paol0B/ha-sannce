import json

import pytest
from homeassistant.components.diagnostics import REDACTED
from homeassistant.const import CONF_HOST, CONF_MAC
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.components.diagnostics import (
    get_diagnostics_for_config_entry,
)
from pytest_homeassistant_custom_component.typing import ClientSessionGenerator

from custom_components.sannce import lib
from custom_components.sannce.const import CONF_SERIAL

from . import setup_integration
from .conftest import ALL_CAPS, FakeSannceCamera


async def test_diagnostics_redact_login_and_identity(
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
    identified_entry: MockConfigEntry,
    mock_camera: FakeSannceCamera,
) -> None:
    mock_camera.info = lib.CameraInfo(
        model="I91FW",
        serial=identified_entry.data[CONF_SERIAL],
        firmware="1.0.0",
        mac=identified_entry.data[CONF_MAC],
    )
    mock_camera.floodlight_on = True
    mock_camera.brightness = 60
    mock_camera.light_mode = "color"
    mock_camera.detection = lib.Detection(
        person=False, vehicle=True, motion=False, sensitivity=40
    )
    await setup_integration(hass, identified_entry)

    result = await get_diagnostics_for_config_entry(hass, hass_client, identified_entry)

    assert result == {
        "entry": {
            "host": REDACTED,
            "username": REDACTED,
            "password": REDACTED,
            "model": "I91FW",
            "serial": REDACTED,
            "mac": REDACTED,
        },
        "info": {
            "model": "I91FW",
            "serial": REDACTED,
            "firmware": "1.0.0",
            "mac": REDACTED,
        },
        "caps": sorted(ALL_CAPS),
        "coordinator": {
            "connected": True,
            "last_update_success": True,
            "settings": {
                "floodlight": {"on": True, "brightness": 60},
                "light_mode": "color",
                "detection": {
                    "person": False,
                    "vehicle": True,
                    "motion": False,
                    "sensitivity": 40,
                },
                "volume": 80,
                "siren_on_event": False,
            },
        },
    }


async def test_diagnostics_hide_a_host_used_as_title_and_unique_id(
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
    mock_config_entry: MockConfigEntry,
    mock_camera: FakeSannceCamera,
) -> None:
    host = mock_config_entry.data[CONF_HOST]
    assert mock_config_entry.title == mock_config_entry.unique_id == host
    await setup_integration(hass, mock_config_entry)

    result = await get_diagnostics_for_config_entry(
        hass, hass_client, mock_config_entry
    )

    dump = json.dumps(result)
    assert not [v for v in mock_config_entry.data.values() if v in dump]


async def test_diagnostics_without_caps_or_info(
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
    mock_config_entry: MockConfigEntry,
    mock_camera: FakeSannceCamera,
) -> None:
    mock_camera.caps = frozenset()
    mock_camera.info = lib.CameraInfo()
    await setup_integration(hass, mock_config_entry)

    result = await get_diagnostics_for_config_entry(
        hass, hass_client, mock_config_entry
    )

    assert result["entry"] == {
        "host": REDACTED,
        "username": REDACTED,
        "password": REDACTED,
    }
    assert result["info"] == {
        "model": None,
        "serial": None,
        "firmware": None,
        "mac": None,
    }
    assert result["caps"] == []
    assert result["coordinator"]["settings"] == {
        "floodlight": None,
        "light_mode": None,
        "detection": None,
        "volume": None,
        "siren_on_event": None,
    }


@pytest.mark.parametrize(
    ("connected", "polled"),
    [(False, True), (True, False)],
    ids=["push_down", "poll_down"],
)
async def test_diagnostics_report_connection_and_poll_state(
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
    mock_config_entry: MockConfigEntry,
    mock_camera: FakeSannceCamera,
    connected: bool,
    polled: bool,
) -> None:
    await setup_integration(hass, mock_config_entry)
    coordinator = mock_config_entry.runtime_data
    coordinator.connected = connected
    coordinator.last_update_success = polled

    result = await get_diagnostics_for_config_entry(
        hass, hass_client, mock_config_entry
    )

    assert result["coordinator"]["connected"] is connected
    assert result["coordinator"]["last_update_success"] is polled
