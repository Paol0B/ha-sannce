import asyncio

import pytest
from homeassistant.components.select import (
    ATTR_OPTION,
    ATTR_OPTIONS,
    SERVICE_SELECT_OPTION,
)
from homeassistant.components.select import DOMAIN as SELECT_DOMAIN
from homeassistant.const import (
    ATTR_ENTITY_ID,
    ATTR_FRIENDLY_NAME,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import translation
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.sannce import lib
from custom_components.sannce.const import DOMAIN

from . import setup_integration
from .conftest import ALL_CAPS, FakeSannceCamera

MODES = ["infrared", "color", "smart"]


def light_mode_id(registry: er.EntityRegistry, entry: MockConfigEntry) -> str | None:
    return registry.async_get_entity_id(
        SELECT_DOMAIN, DOMAIN, f"{entry.unique_id}_light_mode"
    )


async def pick(hass: HomeAssistant, entity_id: str, option: str) -> None:
    await hass.services.async_call(
        SELECT_DOMAIN,
        SERVICE_SELECT_OPTION,
        {ATTR_ENTITY_ID: entity_id, ATTR_OPTION: option},
        blocking=True,
    )


async def refresh(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()


@pytest.fixture
async def light_mode(
    hass: HomeAssistant,
    identified_entry: MockConfigEntry,
    mock_camera: FakeSannceCamera,
    entity_registry: er.EntityRegistry,
) -> str:
    await setup_integration(hass, identified_entry)
    entity_id = light_mode_id(entity_registry, identified_entry)
    assert entity_id, "no light mode select is registered"
    return entity_id


async def test_options_are_the_settable_modes(
    hass: HomeAssistant, light_mode: str
) -> None:
    assert hass.states.get(light_mode).attributes[ATTR_OPTIONS] == MODES


@pytest.mark.parametrize("mode", MODES)
async def test_select_starts_on_the_camera_mode(
    hass: HomeAssistant,
    identified_entry: MockConfigEntry,
    mock_camera: FakeSannceCamera,
    entity_registry: er.EntityRegistry,
    mode: str,
) -> None:
    mock_camera.light_mode = mode

    await setup_integration(hass, identified_entry)

    state = hass.states.get(light_mode_id(entity_registry, identified_entry))
    assert state.state == mode


async def test_select_follows_the_poll(
    hass: HomeAssistant,
    identified_entry: MockConfigEntry,
    light_mode: str,
    mock_camera: FakeSannceCamera,
) -> None:
    mock_camera.light_mode = "smart"
    await refresh(hass, identified_entry)

    assert hass.states.get(light_mode).state == "smart"


async def test_a_custom_camera_mode_reads_as_unknown(
    hass: HomeAssistant,
    identified_entry: MockConfigEntry,
    light_mode: str,
    mock_camera: FakeSannceCamera,
) -> None:
    mock_camera.light_mode = "custom"
    await refresh(hass, identified_entry)

    state = hass.states.get(light_mode)
    assert state.state == STATE_UNKNOWN
    assert state.attributes[ATTR_OPTIONS] == MODES


@pytest.mark.parametrize(
    ("start", "target"),
    [("infrared", "color"), ("color", "smart"), ("smart", "infrared")],
    ids=["color", "smart", "infrared"],
)
async def test_selecting_a_mode_sets_it_on_the_camera(
    hass: HomeAssistant,
    identified_entry: MockConfigEntry,
    light_mode: str,
    mock_camera: FakeSannceCamera,
    start: str,
    target: str,
) -> None:
    mock_camera.light_mode = start
    await refresh(hass, identified_entry)
    assert hass.states.get(light_mode).state == start

    await pick(hass, light_mode, target)

    mock_camera.set_light_mode.assert_awaited_once_with(target)
    assert hass.states.get(light_mode).state == target


async def test_commands_refresh_the_settings(
    hass: HomeAssistant, light_mode: str, mock_camera: FakeSannceCamera
) -> None:
    assert mock_camera.get_light_mode.await_count == 1

    await pick(hass, light_mode, "smart")

    assert mock_camera.get_light_mode.await_count == 2


async def test_state_follows_back_to_back_commands(
    hass: HomeAssistant, light_mode: str
) -> None:
    await pick(hass, light_mode, "color")
    await pick(hass, light_mode, "smart")

    assert hass.states.get(light_mode).state == "smart"


async def test_commands_run_one_at_a_time(
    hass: HomeAssistant, light_mode: str, mock_camera: FakeSannceCamera
) -> None:
    started: list[str] = []
    release = asyncio.Event()

    async def hold(mode: str) -> None:
        started.append(mode)
        await release.wait()

    mock_camera.set_light_mode.side_effect = hold
    first = hass.async_create_task(pick(hass, light_mode, "color"))
    second = hass.async_create_task(pick(hass, light_mode, "smart"))
    for _ in range(10):
        await asyncio.sleep(0)

    assert started == ["color"]

    release.set()
    await asyncio.gather(first, second)

    assert started == ["color", "smart"]


async def test_a_mode_outside_the_options_is_rejected(
    hass: HomeAssistant, light_mode: str, mock_camera: FakeSannceCamera
) -> None:
    with pytest.raises(ServiceValidationError):
        await pick(hass, light_mode, "custom")

    mock_camera.set_light_mode.assert_not_awaited()


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
    light_mode: str,
    mock_camera: FakeSannceCamera,
    error: lib.SannceError,
) -> None:
    mock_camera.set_light_mode.side_effect = error

    with pytest.raises(HomeAssistantError, match=f"{light_mode}: {error}"):
        await pick(hass, light_mode, "smart")

    assert hass.states.get(light_mode).state == "infrared"
    assert mock_camera.get_light_mode.await_count == 1


async def test_select_follows_the_private_connection(
    hass: HomeAssistant, light_mode: str, mock_camera: FakeSannceCamera
) -> None:
    mock_camera.set_available(False)
    await hass.async_block_till_done()

    assert hass.states.get(light_mode).state == STATE_UNAVAILABLE

    mock_camera.set_available(True)
    await hass.async_block_till_done()

    assert hass.states.get(light_mode).state == "infrared"


async def test_failed_poll_makes_the_select_unavailable(
    hass: HomeAssistant,
    identified_entry: MockConfigEntry,
    light_mode: str,
    mock_camera: FakeSannceCamera,
) -> None:
    working = mock_camera.get_light_mode.side_effect
    mock_camera.get_light_mode.side_effect = lib.ConnectError("unreachable")
    await refresh(hass, identified_entry)

    assert hass.states.get(light_mode).state == STATE_UNAVAILABLE

    mock_camera.get_light_mode.side_effect = working
    await refresh(hass, identified_entry)

    assert hass.states.get(light_mode).state == "infrared"


@pytest.mark.parametrize(
    "caps",
    [
        tuple(cap for cap in ALL_CAPS if cap != "light_mode"),
        ("white_light",),
        (),
    ],
    ids=["all_but_mode", "light_only", "none"],
)
async def test_no_select_without_the_light_mode_cap(
    hass: HomeAssistant,
    identified_entry: MockConfigEntry,
    mock_camera: FakeSannceCamera,
    entity_registry: er.EntityRegistry,
    caps: tuple[str, ...],
) -> None:
    mock_camera.caps = frozenset(caps)

    await setup_integration(hass, identified_entry)

    assert light_mode_id(entity_registry, identified_entry) is None
    assert hass.states.async_entity_ids(SELECT_DOMAIN) == []


async def test_select_joins_the_camera_device(
    hass: HomeAssistant,
    identified_entry: MockConfigEntry,
    light_mode: str,
    entity_registry: er.EntityRegistry,
    device_registry: dr.DeviceRegistry,
) -> None:
    (device,) = dr.async_entries_for_config_entry(
        device_registry, identified_entry.entry_id
    )

    assert hass.states.get(light_mode).attributes[ATTR_FRIENDLY_NAME] == (
        "I91FW Light mode"
    )
    assert entity_registry.async_get(light_mode).device_id == device.id


async def test_every_mode_has_a_translated_name(
    hass: HomeAssistant, light_mode: str
) -> None:
    translations = await translation.async_get_translations(
        hass, "en", "entity", [DOMAIN]
    )

    prefix = f"component.{DOMAIN}.entity.select.light_mode.state."
    assert {
        key.removeprefix(prefix): text
        for key, text in translations.items()
        if key.startswith(prefix)
    } == {"infrared": "Infrared", "color": "Color", "smart": "Smart"}
