from datetime import timedelta

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import UpdateFailed
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.sannce import lib
from custom_components.sannce.const import UPDATE_INTERVAL
from custom_components.sannce.coordinator import SannceCoordinator, SannceData

from . import setup_integration
from .conftest import ALL_CAPS, FakeSannceCamera

MOTION_ON = lib.Event("motion", True, 0)
MOTION_OFF = lib.Event("motion", False, 0)


@pytest.fixture
async def coordinator(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_camera: FakeSannceCamera,
) -> SannceCoordinator:
    await setup_integration(hass, mock_config_entry)
    return mock_config_entry.runtime_data


async def test_first_refresh_exposes_camera_settings(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_camera: FakeSannceCamera,
) -> None:
    mock_camera.light_on = True
    mock_camera.light_mode = "smart"
    mock_camera.detection = lib.Detection(person=False, vehicle=True, motion=False)

    await setup_integration(hass, mock_config_entry)

    assert mock_config_entry.state is ConfigEntryState.LOADED
    assert mock_config_entry.runtime_data.data == SannceData(
        light=True,
        light_mode="smart",
        detection=lib.Detection(person=False, vehicle=True, motion=False),
    )
    mock_camera.get_light.assert_awaited_once()
    mock_camera.get_light_mode.assert_awaited_once()
    mock_camera.get_detection.assert_awaited_once()


async def test_polls_every_minute(
    hass: HomeAssistant,
    coordinator: SannceCoordinator,
    mock_camera: FakeSannceCamera,
    freezer: FrozenDateTimeFactory,
) -> None:
    assert coordinator.update_interval == timedelta(seconds=60)
    stop_listening = coordinator.async_add_listener(lambda: None)
    mock_camera.light_on = True

    freezer.tick(UPDATE_INTERVAL)
    async_fire_time_changed(hass)
    await hass.async_block_till_done(wait_background_tasks=True)

    assert mock_camera.get_light.await_count == 2
    assert coordinator.data.light is True
    stop_listening()


@pytest.mark.parametrize("getter", ["get_light", "get_light_mode", "get_detection"])
@pytest.mark.parametrize(
    "error",
    [lib.ConnectError("unreachable"), lib.ProtocolError("bad reply")],
    ids=["connect", "protocol"],
)
async def test_failed_poll_marks_data_stale(
    coordinator: SannceCoordinator,
    mock_camera: FakeSannceCamera,
    getter: str,
    error: lib.SannceError,
) -> None:
    before = coordinator.data
    method = getattr(mock_camera, getter)
    working = method.side_effect
    method.side_effect = error

    await coordinator.async_refresh()

    assert coordinator.last_update_success is False
    assert isinstance(coordinator.last_exception, UpdateFailed)
    assert coordinator.data == before

    method.side_effect = working
    await coordinator.async_refresh()

    assert coordinator.last_update_success is True


async def test_failed_poll_notifies_listeners(
    coordinator: SannceCoordinator, mock_camera: FakeSannceCamera
) -> None:
    seen: list[bool] = []
    stop_listening = coordinator.async_add_listener(
        lambda: seen.append(coordinator.last_update_success)
    )
    working = mock_camera.get_light.side_effect

    mock_camera.get_light.side_effect = lib.ConnectError("unreachable")
    await coordinator.async_refresh()
    mock_camera.get_light.side_effect = working
    await coordinator.async_refresh()

    assert seen == [False, True]
    stop_listening()


async def test_unchanged_poll_does_not_notify_listeners(
    coordinator: SannceCoordinator, mock_camera: FakeSannceCamera
) -> None:
    calls: list[SannceData] = []
    stop_listening = coordinator.async_add_listener(
        lambda: calls.append(coordinator.data)
    )

    await coordinator.async_refresh()
    assert calls == []

    mock_camera.light_on = True
    await coordinator.async_refresh()

    assert [data.light for data in calls] == [True]
    stop_listening()


async def test_poll_auth_error_starts_reauth(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    coordinator: SannceCoordinator,
    mock_camera: FakeSannceCamera,
) -> None:
    mock_camera.get_light.side_effect = lib.AuthError("credentials rejected")

    await coordinator.async_refresh()
    await hass.async_block_till_done()

    assert coordinator.last_update_success is False
    flows = list(mock_config_entry.async_get_active_flows(hass, {SOURCE_REAUTH}))
    assert len(flows) == 1


async def test_reconnect_give_up_starts_reauth(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    coordinator: SannceCoordinator,
    mock_camera: FakeSannceCamera,
) -> None:
    mock_camera.set_available(False)
    mock_camera.fail_login(lib.AuthError("login refused 3 times"))
    await hass.async_block_till_done()

    flows = list(mock_config_entry.async_get_active_flows(hass, {SOURCE_REAUTH}))
    assert len(flows) == 1


@pytest.mark.parametrize(
    ("caps", "expected"),
    [
        (ALL_CAPS, (1, 1, 1)),
        (("white_light", "talk"), (1, 0, 0)),
        (("light_mode",), (0, 1, 0)),
        (("person",), (0, 0, 1)),
        (("vehicle",), (0, 0, 1)),
        (("motion",), (0, 0, 1)),
        ((), (0, 0, 0)),
    ],
    ids=["all", "light", "mode", "person", "vehicle", "motion", "none"],
)
async def test_poll_reads_only_supported_settings(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_camera: FakeSannceCamera,
    caps: tuple[str, ...],
    expected: tuple[int, int, int],
) -> None:
    mock_camera.caps = frozenset(caps)

    await setup_integration(hass, mock_config_entry)

    assert mock_config_entry.state is ConfigEntryState.LOADED
    data = mock_config_entry.runtime_data.data
    polled = (
        mock_camera.get_light.await_count,
        mock_camera.get_light_mode.await_count,
        mock_camera.get_detection.await_count,
    )
    exposed = (
        int(data.light is not None),
        int(data.light_mode is not None),
        int(data.detection is not None),
    )
    assert polled == exposed == expected


@pytest.mark.parametrize(
    ("error", "state"),
    [
        (lib.ConnectError("unreachable"), ConfigEntryState.SETUP_RETRY),
        (lib.ProtocolError("bad reply"), ConfigEntryState.SETUP_RETRY),
        (lib.AuthError("credentials rejected"), ConfigEntryState.SETUP_ERROR),
    ],
    ids=["connect", "protocol", "auth"],
)
async def test_setup_fails_when_first_poll_fails(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_camera: FakeSannceCamera,
    error: lib.SannceError,
    state: ConfigEntryState,
) -> None:
    mock_camera.get_light.side_effect = error

    await setup_integration(hass, mock_config_entry)

    assert mock_config_entry.state is state
    mock_camera.close.assert_awaited_once()


async def test_events_reach_listeners(
    coordinator: SannceCoordinator, mock_camera: FakeSannceCamera
) -> None:
    first: list[lib.Event] = []
    second: list[lib.Event] = []
    stop_first = coordinator.async_add_event_listener(first.append)
    coordinator.async_add_event_listener(second.append)

    mock_camera.emit(MOTION_ON)
    stop_first()
    mock_camera.emit(MOTION_OFF)

    assert first == [MOTION_ON]
    assert second == [MOTION_ON, MOTION_OFF]


async def test_broken_listener_does_not_stop_the_others(
    coordinator: SannceCoordinator,
    mock_camera: FakeSannceCamera,
    caplog: pytest.LogCaptureFixture,
) -> None:
    def broken(event: lib.Event) -> None:
        raise RuntimeError("listener failed")

    seen: list[lib.Event] = []
    coordinator.async_add_event_listener(broken)
    coordinator.async_add_event_listener(seen.append)

    mock_camera.emit(MOTION_ON)

    assert seen == [MOTION_ON]
    assert "listener failed" in caplog.text


async def test_connected_after_setup(coordinator: SannceCoordinator) -> None:
    assert coordinator.connected is True


async def test_connected_starts_false(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_camera: FakeSannceCamera,
) -> None:
    coordinator = SannceCoordinator(hass, mock_config_entry, mock_camera)

    assert coordinator.connected is False

    await mock_camera.connect()

    assert coordinator.connected is True


async def test_connected_follows_camera_availability(
    coordinator: SannceCoordinator, mock_camera: FakeSannceCamera
) -> None:
    seen: list[bool] = []
    stop_listening = coordinator.async_add_listener(
        lambda: seen.append(coordinator.connected)
    )

    mock_camera.set_available(False)
    assert coordinator.connected is False
    mock_camera.set_available(True)
    assert coordinator.connected is True

    assert seen == [False, True]
    stop_listening()


async def test_reconnect_refreshes_the_settings(
    hass: HomeAssistant,
    coordinator: SannceCoordinator,
    mock_camera: FakeSannceCamera,
) -> None:
    mock_camera.set_available(False)
    mock_camera.light_on = True
    await hass.async_block_till_done(wait_background_tasks=True)

    assert mock_camera.get_light.await_count == 1

    mock_camera.set_available(True)
    await hass.async_block_till_done(wait_background_tasks=True)

    assert mock_camera.get_light.await_count == 2
    assert coordinator.data.light is True


async def test_unload_drops_the_event_subscription(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    coordinator: SannceCoordinator,
    mock_camera: FakeSannceCamera,
) -> None:
    seen: list[lib.Event] = []
    coordinator.async_add_event_listener(seen.append)

    assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
    mock_camera.emit(MOTION_ON)

    assert seen == []
    mock_camera.close.assert_awaited_once()
