import asyncio
from collections.abc import AsyncIterator
from unittest.mock import MagicMock, patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from pytest_homeassistant_custom_component.common import MockConfigEntry

import custom_components.sannce as integration
from custom_components.sannce import lib
from custom_components.sannce.const import (
    CONF_HTTP_PORT,
    CONF_NVS_PORT,
    CONF_RTSP_PORT,
    DOMAIN,
)

from . import HOST, PASSWORD, USERNAME, setup_integration
from .conftest import FakeRelay, FakeSannceCamera


async def test_setup_and_unload_entry(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_camera_class: MagicMock,
    mock_camera: FakeSannceCamera,
    mock_relays: list[FakeRelay],
) -> None:
    await setup_integration(hass, mock_config_entry)

    assert mock_config_entry.state is ConfigEntryState.LOADED
    (relay,) = mock_relays
    assert relay.data is mock_config_entry.data
    relay.start.assert_awaited_once()
    relay.close.assert_not_awaited()
    mock_camera_class.assert_called_once_with(
        HOST,
        USERNAME,
        PASSWORD,
        nvs_port=3002,
        http_port=80,
        rtsp_port=554,
        session=async_get_clientsession(hass),
    )
    mock_camera.connect.assert_awaited_once()
    assert mock_config_entry.runtime_data.camera is mock_camera
    mock_camera.close.assert_not_awaited()

    assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.NOT_LOADED
    mock_camera.close.assert_awaited_once()
    relay.close.assert_awaited_once()


async def test_reload_closes_the_relay_and_starts_a_new_one(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_camera: FakeSannceCamera,
    mock_relays: list[FakeRelay],
) -> None:
    await setup_integration(hass, mock_config_entry)

    assert await hass.config_entries.async_reload(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    old, new = mock_relays
    old.close.assert_awaited_once()
    new.start.assert_awaited_once()
    new.close.assert_not_awaited()
    assert mock_config_entry.state is ConfigEntryState.LOADED


async def test_setup_retries_when_the_relay_cannot_listen(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_camera: FakeSannceCamera,
) -> None:
    relay = FakeRelay(mock_config_entry.data)
    relay.start.side_effect = OSError("address in use")

    with patch("custom_components.sannce.lib.create_relay", return_value=relay):
        await setup_integration(hass, mock_config_entry)

    assert mock_config_entry.state is ConfigEntryState.SETUP_RETRY
    assert mock_config_entry.reason == (
        f"Cannot open the video relay for {HOST}: address in use"
    )
    assert mock_config_entry.error_reason_translation_key == "relay_failed"
    mock_camera.close.assert_awaited_once()
    relay.close.assert_not_awaited()


async def test_unload_stops_audio_before_closing_the_camera(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_camera: FakeSannceCamera,
) -> None:
    await setup_integration(hass, mock_config_entry)
    streaming = asyncio.Event()
    talk_at_close: list[bool] = []
    close = mock_camera.close.side_effect

    async def endless() -> AsyncIterator[bytes]:
        yield b"\x00\x01"
        streaming.set()
        await asyncio.Event().wait()

    async def record_close() -> None:
        talk_at_close.append(mock_camera.talk_active)
        await close()

    mock_camera.close.side_effect = record_close
    play = asyncio.create_task(mock_config_entry.runtime_data.audio.play(endless()))
    await streaming.wait()

    assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
    await play

    assert talk_at_close == [False]


async def test_setup_uses_entry_ports(
    hass: HomeAssistant,
    mock_camera_class: MagicMock,
    mock_relays: list[FakeRelay],
) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_HOST: HOST,
            CONF_USERNAME: USERNAME,
            CONF_PASSWORD: PASSWORD,
            CONF_NVS_PORT: 3001,
            CONF_HTTP_PORT: 8080,
            CONF_RTSP_PORT: 8554,
        },
    )

    await setup_integration(hass, entry)

    assert entry.state is ConfigEntryState.LOADED
    _, kwargs = mock_camera_class.call_args
    assert (kwargs["nvs_port"], kwargs["http_port"], kwargs["rtsp_port"]) == (
        3001,
        8080,
        8554,
    )
    assert mock_relays[0].data is entry.data


@pytest.mark.parametrize(("stored", "migrated"), [(3000, 3002), (3100, 3100)])
async def test_version_1_entry_moves_from_port_3000_to_3002(
    hass: HomeAssistant,
    mock_camera: FakeSannceCamera,
    stored: int,
    migrated: int,
) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=1,
        unique_id="SN1",
        data={
            CONF_HOST: HOST,
            CONF_USERNAME: USERNAME,
            CONF_PASSWORD: PASSWORD,
            CONF_NVS_PORT: stored,
        },
    )

    await setup_integration(hass, entry)

    assert entry.state is ConfigEntryState.LOADED
    assert entry.version == 2
    assert entry.data[CONF_NVS_PORT] == migrated


async def test_an_entry_from_a_newer_version_does_not_load(
    hass: HomeAssistant, mock_camera: FakeSannceCamera
) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=3,
        unique_id="SN1",
        data={CONF_HOST: HOST, CONF_USERNAME: USERNAME, CONF_PASSWORD: PASSWORD},
    )

    await setup_integration(hass, entry)

    assert entry.state is ConfigEntryState.MIGRATION_ERROR
    mock_camera.connect.assert_not_awaited()


async def test_migration_refuses_an_entry_from_a_newer_version(
    hass: HomeAssistant,
) -> None:
    entry = MockConfigEntry(domain=DOMAIN, version=3)

    assert await integration.async_migrate_entry(hass, entry) is False


async def test_setup_retries_when_camera_unreachable(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_camera: FakeSannceCamera,
) -> None:
    mock_camera.connect.side_effect = lib.ConnectError("unreachable")

    await setup_integration(hass, mock_config_entry)

    assert mock_config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_setup_error_on_bad_credentials(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_camera: FakeSannceCamera,
) -> None:
    mock_camera.connect.side_effect = lib.AuthError("bad password")

    await setup_integration(hass, mock_config_entry)

    assert mock_config_entry.state is ConfigEntryState.SETUP_ERROR
    assert "bad password" in mock_config_entry.reason
