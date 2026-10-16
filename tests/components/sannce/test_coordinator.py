import logging
from datetime import timedelta
from unittest.mock import patch

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

from . import HOST, setup_integration
from .conftest import ALL_CAPS, FakeSannceCamera

MOTION_ON = lib.Event("motion", True, 0)
MOTION_OFF = lib.Event("motion", False, 0)
LOGGER = "custom_components.sannce.coordinator"


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
    mock_camera.floodlight_on = True
    mock_camera.brightness = 60
    mock_camera.light_mode = "color"
    mock_camera.detection = lib.Detection(
        person=False, vehicle=True, motion=False, sensitivity=40
    )
    mock_camera.volume = 35
    mock_camera.siren_on_event = True

    await setup_integration(hass, mock_config_entry)

    assert mock_config_entry.state is ConfigEntryState.LOADED
    assert mock_config_entry.runtime_data.data == SannceData(
        floodlight=lib.Floodlight(on=True, brightness=60),
        light_mode="color",
        detection=lib.Detection(
            person=False, vehicle=True, motion=False, sensitivity=40
        ),
        volume=35,
        siren_on_event=True,
    )
    mock_camera.get_floodlight.assert_awaited_once()
    mock_camera.get_light_mode.assert_awaited_once()
    mock_camera.get_detection.assert_awaited_once()
    mock_camera.get_volume.assert_awaited_once()
    mock_camera.get_siren_on_event.assert_awaited_once()


async def test_base_mode_follows_the_camera_mode(
    coordinator: SannceCoordinator, mock_camera: FakeSannceCamera
) -> None:
    assert coordinator.base_mode == "infrared"

    mock_camera.light_mode = "smart"
    await coordinator.async_refresh()

    assert coordinator.base_mode == "smart"


@pytest.mark.parametrize(
    ("floodlight_on", "light_mode"),
    [(True, "color"), (False, "custom")],
    ids=["forced_on", "custom"],
)
async def test_base_mode_ignores_a_mode_the_user_did_not_pick(
    coordinator: SannceCoordinator,
    mock_camera: FakeSannceCamera,
    floodlight_on: bool,
    light_mode: str,
) -> None:
    mock_camera.floodlight_on = floodlight_on
    mock_camera.light_mode = light_mode

    await coordinator.async_refresh()

    assert coordinator.base_mode == "infrared"


async def test_base_mode_stays_unset_while_forced_on(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_camera: FakeSannceCamera,
) -> None:
    mock_camera.floodlight_on = True
    mock_camera.light_mode = "color"
    coordinator = SannceCoordinator(hass, mock_config_entry, mock_camera)

    await coordinator.async_refresh()

    assert coordinator.last_update_success is True
    assert coordinator.base_mode is None


async def test_polls_every_minute(
    hass: HomeAssistant,
    coordinator: SannceCoordinator,
    mock_camera: FakeSannceCamera,
    freezer: FrozenDateTimeFactory,
) -> None:
    assert coordinator.update_interval == timedelta(seconds=60)
    stop_listening = coordinator.async_add_listener(lambda: None)
    mock_camera.floodlight_on = True

    freezer.tick(UPDATE_INTERVAL)
    async_fire_time_changed(hass)
    await hass.async_block_till_done(wait_background_tasks=True)

    assert mock_camera.get_floodlight.await_count == 2
    assert coordinator.data.floodlight == lib.Floodlight(on=True, brightness=100)
    stop_listening()


@pytest.mark.parametrize(
    "getter",
    [
        "get_floodlight",
        "get_light_mode",
        "get_detection",
        "get_volume",
        "get_siren_on_event",
    ],
)
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
    working = mock_camera.get_floodlight.side_effect

    mock_camera.get_floodlight.side_effect = lib.ConnectError("unreachable")
    await coordinator.async_refresh()
    mock_camera.get_floodlight.side_effect = working
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

    mock_camera.volume = 30
    await coordinator.async_refresh()

    assert [data.volume for data in calls] == [30]
    stop_listening()


async def test_poll_auth_error_starts_reauth(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    coordinator: SannceCoordinator,
    mock_camera: FakeSannceCamera,
) -> None:
    mock_camera.get_floodlight.side_effect = lib.AuthError("credentials rejected")

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
        (ALL_CAPS, (1, 1, 1, 1, 1)),
        (("white_light", "light_mode"), (1, 1, 0, 0, 0)),
        (("white_light", "speaker"), (0, 0, 0, 0, 0)),
        (("light_mode",), (0, 1, 0, 0, 0)),
        (("person",), (0, 0, 1, 0, 0)),
        (("vehicle",), (0, 0, 1, 0, 0)),
        (("motion",), (0, 0, 1, 0, 0)),
        (("volume",), (0, 0, 0, 1, 0)),
        (("siren_on_event",), (0, 0, 0, 0, 1)),
        ((), (0, 0, 0, 0, 0)),
    ],
    ids=[
        "all",
        "floodlight",
        "light_only",
        "mode",
        "person",
        "vehicle",
        "motion",
        "volume",
        "siren_on_event",
        "none",
    ],
)
async def test_poll_reads_only_supported_settings(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_camera: FakeSannceCamera,
    caps: tuple[str, ...],
    expected: tuple[int, ...],
) -> None:
    mock_camera.caps = frozenset(caps)

    await setup_integration(hass, mock_config_entry)

    assert mock_config_entry.state is ConfigEntryState.LOADED
    data = mock_config_entry.runtime_data.data
    polled = (
        mock_camera.get_floodlight.await_count,
        mock_camera.get_light_mode.await_count,
        mock_camera.get_detection.await_count,
        mock_camera.get_volume.await_count,
        mock_camera.get_siren_on_event.await_count,
    )
    exposed = (
        int(data.floodlight is not None),
        int(data.light_mode is not None),
        int(data.detection is not None),
        int(data.volume is not None),
        int(data.siren_on_event is not None),
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
    mock_camera.get_floodlight.side_effect = error

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
    mock_camera.floodlight_on = True
    await hass.async_block_till_done(wait_background_tasks=True)

    assert mock_camera.get_floodlight.await_count == 1

    mock_camera.set_available(True)
    await hass.async_block_till_done(wait_background_tasks=True)

    assert mock_camera.get_floodlight.await_count == 2
    assert coordinator.data.floodlight == lib.Floodlight(on=True, brightness=100)


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


async def test_a_speaker_owner_change_updates_the_listeners(
    coordinator: SannceCoordinator, mock_camera: FakeSannceCamera
) -> None:
    owners: list[str | None] = []
    stop_listening = coordinator.async_add_listener(
        lambda: owners.append(mock_camera.speaker.owner)
    )

    mock_camera.speaker.set_owner("talk")
    mock_camera.speaker.set_owner(None)

    assert owners == ["talk", None]
    stop_listening()


async def test_unload_drops_the_speaker_subscription(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    coordinator: SannceCoordinator,
    mock_camera: FakeSannceCamera,
) -> None:
    owners: list[str | None] = []
    coordinator.async_add_listener(lambda: owners.append(mock_camera.speaker.owner))

    assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
    owners.clear()
    mock_camera.speaker.set_owner("talk")

    assert owners == []
    assert mock_camera.speaker.subscribers == []


def availability_log(caplog: pytest.LogCaptureFixture) -> list[tuple[int, str]]:
    return [
        (record.levelno, record.getMessage())
        for record in caplog.records
        if record.name == LOGGER and record.getMessage().startswith("Camera ")
    ]


async def test_a_drop_and_a_return_log_once_each(
    hass: HomeAssistant,
    coordinator: SannceCoordinator,
    mock_camera: FakeSannceCamera,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG, logger=LOGGER)

    with patch.object(
        coordinator, "async_request_refresh", wraps=coordinator.async_request_refresh
    ) as refresh:
        mock_camera.set_available(False)
        mock_camera.set_available(False)
        mock_camera.set_available(True)
        mock_camera.set_available(True)
        await hass.async_block_till_done(wait_background_tasks=True)

    assert availability_log(caplog) == [
        (logging.INFO, f"Camera {HOST} is unavailable"),
        (logging.INFO, f"Camera {HOST} is back online"),
    ]
    # the debouncer would hide a second request from the poll count
    refresh.assert_awaited_once()
    assert mock_camera.get_floodlight.await_count == 2


async def test_setup_and_unload_log_no_availability_change(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_camera: FakeSannceCamera,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG, logger=LOGGER)

    await setup_integration(hass, mock_config_entry)
    assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    mock_camera.close.assert_awaited_once()
    assert availability_log(caplog) == []
