import asyncio

import pytest
from homeassistant.components.light import (
    ATTR_COLOR_MODE,
    ATTR_SUPPORTED_COLOR_MODES,
    ColorMode,
)
from homeassistant.components.light import DOMAIN as LIGHT_DOMAIN
from homeassistant.const import (
    ATTR_ENTITY_ID,
    ATTR_FRIENDLY_NAME,
    SERVICE_TOGGLE,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    STATE_OFF,
    STATE_ON,
    STATE_UNAVAILABLE,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.sannce import lib
from custom_components.sannce.const import DOMAIN

from . import setup_integration
from .conftest import ALL_CAPS, FakeSannceCamera


def floodlight_id(registry: er.EntityRegistry, entry: MockConfigEntry) -> str | None:
    return registry.async_get_entity_id(
        LIGHT_DOMAIN, DOMAIN, f"{entry.unique_id}_floodlight"
    )


async def call(hass: HomeAssistant, service: str, entity_id: str) -> None:
    await hass.services.async_call(
        LIGHT_DOMAIN, service, {ATTR_ENTITY_ID: entity_id}, blocking=True
    )


async def refresh(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()


@pytest.fixture
async def floodlight(
    hass: HomeAssistant,
    identified_entry: MockConfigEntry,
    mock_camera: FakeSannceCamera,
    entity_registry: er.EntityRegistry,
) -> str:
    await setup_integration(hass, identified_entry)
    entity_id = floodlight_id(entity_registry, identified_entry)
    assert entity_id, "no floodlight is registered"
    return entity_id


async def test_floodlight_starts_in_auto_mode(
    hass: HomeAssistant, floodlight: str
) -> None:
    state = hass.states.get(floodlight)

    assert state.state == STATE_OFF
    assert state.attributes[ATTR_SUPPORTED_COLOR_MODES] == [ColorMode.ONOFF]


async def test_floodlight_reads_a_forced_on_light(
    hass: HomeAssistant,
    identified_entry: MockConfigEntry,
    mock_camera: FakeSannceCamera,
    entity_registry: er.EntityRegistry,
) -> None:
    mock_camera.light_on = True

    await setup_integration(hass, identified_entry)

    state = hass.states.get(floodlight_id(entity_registry, identified_entry))
    assert state.state == STATE_ON
    assert state.attributes[ATTR_COLOR_MODE] == ColorMode.ONOFF


async def test_floodlight_follows_the_poll(
    hass: HomeAssistant,
    identified_entry: MockConfigEntry,
    floodlight: str,
    mock_camera: FakeSannceCamera,
) -> None:
    mock_camera.light_on = True
    await refresh(hass, identified_entry)

    assert hass.states.get(floodlight).state == STATE_ON

    mock_camera.light_on = False
    await refresh(hass, identified_entry)

    assert hass.states.get(floodlight).state == STATE_OFF


async def test_turn_on_forces_the_light_on(
    hass: HomeAssistant, floodlight: str, mock_camera: FakeSannceCamera
) -> None:
    await call(hass, SERVICE_TURN_ON, floodlight)

    mock_camera.set_light.assert_awaited_once_with(True)
    assert hass.states.get(floodlight).state == STATE_ON


async def test_turn_off_returns_the_light_to_auto_mode(
    hass: HomeAssistant,
    identified_entry: MockConfigEntry,
    floodlight: str,
    mock_camera: FakeSannceCamera,
) -> None:
    mock_camera.light_on = True
    await refresh(hass, identified_entry)
    assert hass.states.get(floodlight).state == STATE_ON

    await call(hass, SERVICE_TURN_OFF, floodlight)

    mock_camera.set_light.assert_awaited_once_with(False)
    assert hass.states.get(floodlight).state == STATE_OFF


@pytest.mark.parametrize(
    ("forced_on", "command"), [(False, True), (True, False)], ids=["on", "off"]
)
async def test_toggle_switches_between_forced_on_and_auto(
    hass: HomeAssistant,
    identified_entry: MockConfigEntry,
    floodlight: str,
    mock_camera: FakeSannceCamera,
    forced_on: bool,
    command: bool,
) -> None:
    mock_camera.light_on = forced_on
    await refresh(hass, identified_entry)

    await call(hass, SERVICE_TOGGLE, floodlight)

    mock_camera.set_light.assert_awaited_once_with(command)
    assert hass.states.get(floodlight).state == (STATE_ON if command else STATE_OFF)


async def test_commands_refresh_the_settings(
    hass: HomeAssistant, floodlight: str, mock_camera: FakeSannceCamera
) -> None:
    assert mock_camera.get_light.await_count == 1

    await call(hass, SERVICE_TURN_ON, floodlight)

    assert mock_camera.get_light.await_count == 2


async def test_state_follows_back_to_back_commands(
    hass: HomeAssistant, floodlight: str
) -> None:
    await call(hass, SERVICE_TURN_ON, floodlight)
    await call(hass, SERVICE_TURN_OFF, floodlight)

    assert hass.states.get(floodlight).state == STATE_OFF


async def test_commands_run_one_at_a_time(
    hass: HomeAssistant, floodlight: str, mock_camera: FakeSannceCamera
) -> None:
    started: list[bool] = []
    release = asyncio.Event()

    async def hold(on: bool) -> None:
        started.append(on)
        await release.wait()

    mock_camera.set_light.side_effect = hold
    on = hass.async_create_task(call(hass, SERVICE_TURN_ON, floodlight))
    off = hass.async_create_task(call(hass, SERVICE_TURN_OFF, floodlight))
    for _ in range(10):
        await asyncio.sleep(0)

    assert started == [True]

    release.set()
    await asyncio.gather(on, off)

    assert started == [True, False]


@pytest.mark.parametrize(
    "error",
    [
        lib.ConnectError("unreachable"),
        lib.AuthError("credentials rejected"),
        lib.ProtocolError("bad reply"),
    ],
    ids=["connect", "auth", "protocol"],
)
async def test_failed_command_raises_an_ha_error(
    hass: HomeAssistant,
    floodlight: str,
    mock_camera: FakeSannceCamera,
    error: lib.SannceError,
) -> None:
    mock_camera.set_light.side_effect = error

    with pytest.raises(HomeAssistantError, match=f"{floodlight}: {error}"):
        await call(hass, SERVICE_TURN_ON, floodlight)

    assert hass.states.get(floodlight).state == STATE_OFF
    assert mock_camera.get_light.await_count == 1


async def test_floodlight_follows_the_private_connection(
    hass: HomeAssistant, floodlight: str, mock_camera: FakeSannceCamera
) -> None:
    mock_camera.set_available(False)
    await hass.async_block_till_done()

    assert hass.states.get(floodlight).state == STATE_UNAVAILABLE

    mock_camera.set_available(True)
    await hass.async_block_till_done()

    assert hass.states.get(floodlight).state == STATE_OFF


async def test_failed_poll_makes_the_floodlight_unavailable(
    hass: HomeAssistant,
    identified_entry: MockConfigEntry,
    floodlight: str,
    mock_camera: FakeSannceCamera,
) -> None:
    working = mock_camera.get_light.side_effect
    mock_camera.get_light.side_effect = lib.ConnectError("unreachable")
    await refresh(hass, identified_entry)

    assert hass.states.get(floodlight).state == STATE_UNAVAILABLE

    mock_camera.get_light.side_effect = working
    await refresh(hass, identified_entry)

    assert hass.states.get(floodlight).state == STATE_OFF


@pytest.mark.parametrize(
    "caps",
    [
        tuple(cap for cap in ALL_CAPS if cap != "white_light"),
        ("light_mode",),
        (),
    ],
    ids=["all_but_light", "mode_only", "none"],
)
async def test_no_floodlight_without_the_white_light_cap(
    hass: HomeAssistant,
    identified_entry: MockConfigEntry,
    mock_camera: FakeSannceCamera,
    entity_registry: er.EntityRegistry,
    caps: tuple[str, ...],
) -> None:
    mock_camera.caps = frozenset(caps)

    await setup_integration(hass, identified_entry)

    assert floodlight_id(entity_registry, identified_entry) is None
    assert hass.states.async_entity_ids(LIGHT_DOMAIN) == []


async def test_floodlight_joins_the_camera_device(
    hass: HomeAssistant,
    identified_entry: MockConfigEntry,
    floodlight: str,
    entity_registry: er.EntityRegistry,
    device_registry: dr.DeviceRegistry,
) -> None:
    (device,) = dr.async_entries_for_config_entry(
        device_registry, identified_entry.entry_id
    )

    assert hass.states.get(floodlight).attributes[ATTR_FRIENDLY_NAME] == (
        "I91FW Floodlight"
    )
    assert entity_registry.async_get(floodlight).device_id == device.id
