import json
from collections.abc import Generator
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import probatio
import pytest
from homeassistant.config_entries import (
    SOURCE_REAUTH,
    SOURCE_USER,
    ConfigEntryState,
    ConfigFlowResult,
)
from homeassistant.const import (
    CONF_HOST,
    CONF_MAC,
    CONF_MODEL,
    CONF_PASSWORD,
    CONF_USERNAME,
)
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from pytest_homeassistant_custom_component.common import MockConfigEntry

import custom_components.sannce as integration
from custom_components.sannce import lib
from custom_components.sannce.const import (
    CONF_HTTP_PORT,
    CONF_NVS_PORT,
    CONF_RTSP_PORT,
    CONF_SERIAL,
    DOMAIN,
)

from . import HOST, PASSWORD, USERNAME, setup_integration
from .conftest import FakeSannceCamera

USER_INPUT = {CONF_HOST: HOST, CONF_USERNAME: USERNAME, CONF_PASSWORD: PASSWORD}
DEFAULT_PORTS = {CONF_NVS_PORT: 3000, CONF_HTTP_PORT: 80, CONF_RTSP_PORT: 554}
SERIAL = "SN0000000001"
MAC = "00:00:5E:00:53:2A"
NEW_HOST = "192.168.1.20"
INTEGRATION_DIR = Path(integration.__file__).parent

pytestmark = pytest.mark.usefixtures("mock_find_camera")


@pytest.fixture
def mock_setup_entry() -> Generator[AsyncMock]:
    with patch(
        "custom_components.sannce.async_setup_entry", return_value=True
    ) as setup_entry:
        yield setup_entry


@pytest.fixture
def mock_discover() -> Generator[AsyncMock]:
    with patch(
        "custom_components.sannce.lib.discover", AsyncMock(return_value=[])
    ) as discover:
        yield discover


@pytest.fixture
async def reauth_flow(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_camera: FakeSannceCamera,
) -> ConfigFlowResult:
    mock_camera.connect.side_effect = lib.AuthError("bad password")
    await setup_integration(hass, mock_config_entry)
    flows = list(mock_config_entry.async_get_active_flows(hass, {SOURCE_REAUTH}))
    assert len(flows) == 1
    return flows[0]


def discovered(**fields: Any) -> lib.DiscoveredCamera:
    values = {
        "ip": HOST,
        "mac": MAC,
        "serial": SERIAL,
        "model": "I91FW",
        "http_port": 8080,
        "server_port": 3001,
        "channels": 1,
    }
    return lib.DiscoveredCamera(**(values | fields))


def add_entry(hass: HomeAssistant, host: str, unique_id: str) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title=host,
        unique_id=unique_id,
        data={CONF_HOST: host, CONF_USERNAME: USERNAME, CONF_PASSWORD: PASSWORD},
    )
    entry.add_to_hass(hass)
    return entry


def camera_entry(**identity: str) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title="I91FW",
        unique_id=identity.get(CONF_SERIAL, HOST),
        data=USER_INPUT | DEFAULT_PORTS | identity,
    )


async def start_reconfigure(
    hass: HomeAssistant, entry: MockConfigEntry
) -> ConfigFlowResult:
    await setup_integration(hass, entry)
    return await entry.start_reconfigure_flow(hass)


async def start_flow(hass: HomeAssistant) -> ConfigFlowResult:
    return await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )


async def submit(
    hass: HomeAssistant, result: ConfigFlowResult, user_input: dict[str, Any]
) -> ConfigFlowResult:
    return await hass.config_entries.flow.async_configure(result["flow_id"], user_input)


def fields(result: ConfigFlowResult) -> dict[str, dict[str, Any]]:
    serialized = probatio.to_field_list(
        result["data_schema"], custom_serializer=cv.custom_serializer
    )
    return {field["name"]: field for field in serialized}


def suggested(result: ConfigFlowResult) -> dict[str, Any]:
    return {
        key.schema: key.description["suggested_value"]
        for key in result["data_schema"].schema
        if key.description and "suggested_value" in key.description
    }


async def test_user_form_fields(hass: HomeAssistant) -> None:
    result = await start_flow(hass)

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert not result["errors"]
    form = fields(result)
    assert list(form) == [
        CONF_HOST,
        CONF_USERNAME,
        CONF_PASSWORD,
        CONF_NVS_PORT,
        CONF_HTTP_PORT,
        CONF_RTSP_PORT,
    ]
    assert {name: form[name]["default"] for name in DEFAULT_PORTS} == DEFAULT_PORTS


async def test_config_flow_user_success(
    hass: HomeAssistant,
    mock_camera_class: MagicMock,
    mock_camera: FakeSannceCamera,
    mock_setup_entry: AsyncMock,
) -> None:
    ports = {CONF_NVS_PORT: 3001, CONF_HTTP_PORT: 8080, CONF_RTSP_PORT: 8554}
    result = await start_flow(hass)

    result = await submit(hass, result, USER_INPUT | ports)

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == HOST
    assert result["data"] == USER_INPUT | ports
    assert result["result"].unique_id == HOST
    mock_camera_class.assert_called_once_with(
        HOST,
        USERNAME,
        PASSWORD,
        nvs_port=3001,
        http_port=8080,
        rtsp_port=8554,
        session=async_get_clientsession(hass),
    )
    mock_camera.connect.assert_awaited_once()
    mock_camera.close.assert_awaited_once()
    mock_setup_entry.assert_awaited_once()


async def test_config_flow_default_ports(
    hass: HomeAssistant,
    mock_camera: FakeSannceCamera,
    mock_setup_entry: AsyncMock,
) -> None:
    result = await start_flow(hass)

    result = await submit(hass, result, USER_INPUT)

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == USER_INPUT | DEFAULT_PORTS


async def test_config_flow_uses_model_and_serial(
    hass: HomeAssistant,
    mock_camera: FakeSannceCamera,
    mock_setup_entry: AsyncMock,
) -> None:
    mock_camera.info = lib.CameraInfo(
        model="I91FW", serial=SERIAL, firmware="1.0.0", mac=MAC
    )
    result = await start_flow(hass)

    result = await submit(hass, result, USER_INPUT)

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "I91FW"
    assert result["result"].unique_id == SERIAL
    assert result["data"] == USER_INPUT | DEFAULT_PORTS | {
        CONF_MODEL: "I91FW",
        CONF_SERIAL: SERIAL,
        CONF_MAC: MAC,
    }


async def test_config_flow_invalid_auth(
    hass: HomeAssistant,
    mock_camera: FakeSannceCamera,
    mock_setup_entry: AsyncMock,
) -> None:
    mock_camera.connect.side_effect = lib.AuthError("bad password")
    result = await start_flow(hass)

    result = await submit(hass, result, USER_INPUT)

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {"base": "invalid_auth"}
    assert suggested(result) == USER_INPUT | DEFAULT_PORTS
    mock_camera.close.assert_awaited_once()

    mock_camera.connect.side_effect = None
    result = await submit(hass, result, USER_INPUT)

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert mock_camera.close.await_count == 2


@pytest.mark.parametrize(
    "error",
    [lib.ConnectError("unreachable"), lib.ProtocolError("bad reply")],
    ids=["connect", "protocol"],
)
async def test_config_flow_cannot_connect(
    hass: HomeAssistant,
    mock_camera: FakeSannceCamera,
    mock_setup_entry: AsyncMock,
    error: lib.SannceError,
) -> None:
    mock_camera.connect.side_effect = error
    result = await start_flow(hass)

    result = await submit(hass, result, USER_INPUT)

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {"base": "cannot_connect"}
    mock_camera.close.assert_awaited_once()

    mock_camera.connect.side_effect = None
    result = await submit(hass, result, USER_INPUT)

    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_config_flow_unknown_error(
    hass: HomeAssistant,
    mock_camera: FakeSannceCamera,
) -> None:
    mock_camera.connect.side_effect = RuntimeError("boom")
    result = await start_flow(hass)

    result = await submit(hass, result, USER_INPUT)

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "unknown"}
    mock_camera.close.assert_awaited_once()


@pytest.mark.parametrize(
    "host",
    [
        "http://192.168.1.10",
        "192.168.1.10/live",
        "admin@192.168.1.10",
        "192.168.1.10?x=1",
        "192.168.1.10#top",
    ],
)
async def test_config_flow_invalid_host(hass: HomeAssistant, host: str) -> None:
    result = await start_flow(hass)

    result = await submit(hass, result, USER_INPUT | {CONF_HOST: host})

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {"base": "invalid_host"}


async def test_config_flow_duplicate(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_camera: FakeSannceCamera,
) -> None:
    mock_config_entry.add_to_hass(hass)
    result = await start_flow(hass)

    result = await submit(hass, result, USER_INPUT)

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_config_flow_duplicate_host(
    hass: HomeAssistant,
    mock_camera_class: MagicMock,
) -> None:
    add_entry(hass, HOST, SERIAL)
    result = await start_flow(hass)

    result = await submit(hass, result, USER_INPUT)

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    mock_camera_class.assert_not_called()


async def test_config_flow_duplicate_serial(
    hass: HomeAssistant,
    mock_camera: FakeSannceCamera,
) -> None:
    add_entry(hass, "192.168.1.99", SERIAL)
    mock_camera.info = lib.CameraInfo(serial=SERIAL)
    result = await start_flow(hass)

    result = await submit(hass, result, USER_INPUT)

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    mock_camera.close.assert_awaited_once()


@pytest.mark.parametrize(
    ("camera", "identity"),
    [
        (discovered(), {CONF_MODEL: "I91FW", CONF_SERIAL: SERIAL, CONF_MAC: MAC}),
        (discovered(mac=""), {CONF_MODEL: "I91FW", CONF_SERIAL: SERIAL}),
    ],
    ids=["full", "no_mac"],
)
async def test_config_flow_discovery(
    hass: HomeAssistant,
    mock_discover: AsyncMock,
    mock_find_camera: AsyncMock,
    mock_camera_class: MagicMock,
    mock_setup_entry: AsyncMock,
    camera: lib.DiscoveredCamera,
    identity: dict[str, str],
) -> None:
    mock_discover.return_value = [camera]
    result = await start_flow(hass)

    result = await submit(hass, result, {CONF_HOST: ""})

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "pick_camera"
    mock_discover.assert_awaited_once()
    options = fields(result)[CONF_HOST]["options"]
    assert [value for value, _ in options] == [HOST]
    assert "I91FW" in options[0][1]

    result = await submit(hass, result, {CONF_HOST: HOST})

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert suggested(result)[CONF_HOST] == HOST
    assert suggested(result)[CONF_NVS_PORT] == 3001
    assert suggested(result)[CONF_HTTP_PORT] == 8080

    login = {CONF_USERNAME: USERNAME, CONF_PASSWORD: PASSWORD}
    result = await submit(hass, result, suggested(result) | login)

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "I91FW"
    assert result["result"].unique_id == SERIAL
    assert result["data"] == USER_INPUT | DEFAULT_PORTS | identity | {
        CONF_NVS_PORT: 3001,
        CONF_HTTP_PORT: 8080,
    }
    mock_camera_class.assert_called_once_with(
        HOST,
        USERNAME,
        PASSWORD,
        nvs_port=3001,
        http_port=8080,
        rtsp_port=554,
        session=async_get_clientsession(hass),
    )
    mock_find_camera.assert_not_awaited()


async def test_config_flow_discovery_skips_configured(
    hass: HomeAssistant, mock_discover: AsyncMock
) -> None:
    add_entry(hass, "192.168.1.50", SERIAL)
    add_entry(hass, "192.168.1.12", "192.168.1.12")
    mock_discover.return_value = [
        discovered(ip="192.168.1.60", serial=SERIAL),
        discovered(ip="192.168.1.12", serial="SN0000000002"),
        discovered(ip="192.168.1.13", serial="SN0000000003"),
    ]
    result = await start_flow(hass)

    result = await submit(hass, result, {CONF_HOST: ""})

    assert result["step_id"] == "pick_camera"
    options = fields(result)[CONF_HOST]["options"]
    assert [value for value, _ in options] == ["192.168.1.13"]


@pytest.mark.parametrize(
    "failure", [None, OSError("network unreachable")], ids=["empty", "scan_failed"]
)
async def test_config_flow_discovery_finds_nothing(
    hass: HomeAssistant,
    mock_discover: AsyncMock,
    failure: OSError | None,
) -> None:
    mock_discover.side_effect = failure
    result = await start_flow(hass)

    result = await submit(hass, result, {CONF_HOST: "", CONF_USERNAME: "viewer"})

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {"base": "no_cameras_found"}
    assert suggested(result)[CONF_USERNAME] == "viewer"


async def test_adding_by_ip_takes_the_identity_from_the_lan_search(
    hass: HomeAssistant,
    mock_find_camera: AsyncMock,
    mock_camera: FakeSannceCamera,
    mock_setup_entry: AsyncMock,
) -> None:
    mock_find_camera.return_value = discovered()
    result = await start_flow(hass)

    result = await submit(hass, result, USER_INPUT)

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "I91FW"
    assert result["result"].unique_id == SERIAL
    assert result["data"] == USER_INPUT | DEFAULT_PORTS | {
        CONF_MODEL: "I91FW",
        CONF_SERIAL: SERIAL,
        CONF_MAC: MAC,
    }
    mock_find_camera.assert_awaited_once_with(HOST)


@pytest.mark.parametrize(
    "failure", [None, OSError("network unreachable")], ids=["silent", "failed"]
)
async def test_adding_by_ip_without_a_search_answer_keys_the_entry_by_host(
    hass: HomeAssistant,
    mock_find_camera: AsyncMock,
    mock_camera: FakeSannceCamera,
    mock_setup_entry: AsyncMock,
    failure: OSError | None,
) -> None:
    mock_find_camera.side_effect = failure
    result = await start_flow(hass)

    result = await submit(hass, result, USER_INPUT)

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert (result["title"], result["result"].unique_id) == (HOST, HOST)
    assert result["data"] == USER_INPUT | DEFAULT_PORTS


async def test_a_failed_login_skips_the_lan_search(
    hass: HomeAssistant,
    mock_find_camera: AsyncMock,
    mock_camera: FakeSannceCamera,
) -> None:
    mock_camera.connect.side_effect = lib.AuthError("bad password")
    result = await start_flow(hass)

    result = await submit(hass, result, USER_INPUT)

    assert result["errors"] == {"base": "invalid_auth"}
    mock_find_camera.assert_not_awaited()


async def test_adding_a_known_camera_at_a_new_address_aborts(
    hass: HomeAssistant,
    mock_find_camera: AsyncMock,
    mock_camera: FakeSannceCamera,
) -> None:
    entry = add_entry(hass, "192.168.1.99", SERIAL)
    mock_find_camera.return_value = discovered()
    result = await start_flow(hass)

    result = await submit(hass, result, USER_INPUT)

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert entry.data[CONF_HOST] == "192.168.1.99"
    assert len(hass.config_entries.async_entries(DOMAIN)) == 1


async def test_setup_auth_failure_starts_reauth(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    reauth_flow: ConfigFlowResult,
) -> None:
    assert mock_config_entry.state is ConfigEntryState.SETUP_ERROR
    assert reauth_flow["step_id"] == "reauth_confirm"
    assert reauth_flow["context"]["source"] == SOURCE_REAUTH
    assert reauth_flow["context"]["entry_id"] == mock_config_entry.entry_id


async def test_reauth_flow(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_camera_class: MagicMock,
    mock_camera: FakeSannceCamera,
    reauth_flow: ConfigFlowResult,
) -> None:
    form = await hass.config_entries.flow.async_configure(reauth_flow["flow_id"])
    assert form["type"] is FlowResultType.FORM
    assert list(fields(form)) == [CONF_PASSWORD]
    placeholders = form["description_placeholders"]
    assert (placeholders[CONF_HOST], placeholders[CONF_USERNAME]) == (HOST, USERNAME)
    mock_camera.connect.side_effect = None

    result = await submit(hass, reauth_flow, {CONF_PASSWORD: "new-secret"})
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert mock_config_entry.data == USER_INPUT | {CONF_PASSWORD: "new-secret"}
    assert mock_config_entry.state is ConfigEntryState.LOADED
    passwords = [call.args[2] for call in mock_camera_class.call_args_list]
    assert passwords == [PASSWORD, "new-secret", "new-secret"]


async def test_reauth_flow_invalid_auth(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_camera: FakeSannceCamera,
    reauth_flow: ConfigFlowResult,
) -> None:
    result = await submit(hass, reauth_flow, {CONF_PASSWORD: "still-wrong"})

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"
    assert result["errors"] == {"base": "invalid_auth"}
    assert mock_config_entry.data[CONF_PASSWORD] == PASSWORD
    mock_camera.close.assert_awaited_once()

    mock_camera.connect.side_effect = None
    result = await submit(hass, result, {CONF_PASSWORD: "new-secret"})
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert mock_config_entry.data[CONF_PASSWORD] == "new-secret"


async def test_reconfigure_form_shows_the_current_settings(
    hass: HomeAssistant, mock_camera: FakeSannceCamera
) -> None:
    entry = camera_entry(serial=SERIAL, mac=MAC)

    result = await start_reconfigure(hass, entry)

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reconfigure"
    assert list(fields(result)) == [
        CONF_HOST,
        CONF_USERNAME,
        CONF_PASSWORD,
        CONF_NVS_PORT,
        CONF_HTTP_PORT,
        CONF_RTSP_PORT,
    ]
    current = {CONF_HOST: HOST, CONF_USERNAME: USERNAME} | DEFAULT_PORTS
    assert suggested(result) == current


async def test_reconfigure_moves_the_entry_to_a_new_address(
    hass: HomeAssistant,
    mock_camera_class: MagicMock,
    mock_camera: FakeSannceCamera,
    mock_find_camera: AsyncMock,
) -> None:
    entry = camera_entry(model="I91FW", serial=SERIAL, mac=MAC)
    result = await start_reconfigure(hass, entry)
    mock_find_camera.return_value = discovered(ip=NEW_HOST)

    moved = USER_INPUT | DEFAULT_PORTS | {CONF_HOST: NEW_HOST, CONF_PASSWORD: ""}

    result = await submit(hass, result, moved)
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.data == USER_INPUT | DEFAULT_PORTS | {
        CONF_HOST: NEW_HOST,
        CONF_MODEL: "I91FW",
        CONF_SERIAL: SERIAL,
        CONF_MAC: MAC,
    }
    assert entry.state is ConfigEntryState.LOADED
    assert mock_camera_class.call_args.args == (NEW_HOST, USERNAME, PASSWORD)
    mock_find_camera.assert_awaited_once_with(NEW_HOST)


async def test_reconfigure_changes_the_login_and_the_ports(
    hass: HomeAssistant, mock_camera: FakeSannceCamera
) -> None:
    changes = {
        CONF_USERNAME: "viewer",
        CONF_PASSWORD: "new-secret",
        CONF_NVS_PORT: 3001,
        CONF_HTTP_PORT: 8080,
        CONF_RTSP_PORT: 8554,
    }
    entry = camera_entry()
    result = await start_reconfigure(hass, entry)

    result = await submit(hass, result, {CONF_HOST: HOST} | changes)
    await hass.async_block_till_done()

    assert result["reason"] == "reconfigure_successful"
    assert entry.data == {CONF_HOST: HOST} | changes
    assert entry.unique_id == HOST


async def test_reconfigure_stores_an_identity_it_learns(
    hass: HomeAssistant, mock_camera: FakeSannceCamera, mock_find_camera: AsyncMock
) -> None:
    entry = camera_entry()
    result = await start_reconfigure(hass, entry)
    mock_find_camera.return_value = discovered()

    result = await submit(hass, result, USER_INPUT | DEFAULT_PORTS)
    await hass.async_block_till_done()

    assert result["reason"] == "reconfigure_successful"
    assert entry.data == USER_INPUT | DEFAULT_PORTS | {
        CONF_MODEL: "I91FW",
        CONF_SERIAL: SERIAL,
        CONF_MAC: MAC,
    }
    assert entry.unique_id == HOST


@pytest.mark.parametrize(
    ("error", "base"),
    [
        (lib.AuthError("bad password"), "invalid_auth"),
        (lib.ConnectError("unreachable"), "cannot_connect"),
    ],
    ids=["auth", "connect"],
)
async def test_reconfigure_keeps_the_entry_when_the_probe_fails(
    hass: HomeAssistant,
    mock_camera: FakeSannceCamera,
    mock_find_camera: AsyncMock,
    error: lib.SannceError,
    base: str,
) -> None:
    entry = camera_entry(serial=SERIAL)
    result = await start_reconfigure(hass, entry)
    mock_camera.connect.side_effect = error
    typed = USER_INPUT | DEFAULT_PORTS | {CONF_HOST: NEW_HOST, CONF_PASSWORD: "wrong"}

    result = await submit(hass, result, typed)

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reconfigure"
    assert result["errors"] == {"base": base}
    assert suggested(result)[CONF_HOST] == NEW_HOST
    assert CONF_PASSWORD not in suggested(result)
    assert (entry.data[CONF_HOST], entry.data[CONF_PASSWORD]) == (HOST, PASSWORD)
    mock_find_camera.assert_not_awaited()

    mock_camera.connect.side_effect = None
    result = await submit(hass, result, typed | {CONF_PASSWORD: "new-secret"})
    await hass.async_block_till_done()

    assert result["reason"] == "reconfigure_successful"
    assert entry.data[CONF_PASSWORD] == "new-secret"


@pytest.mark.parametrize(
    ("identity", "found"),
    [
        (
            {CONF_SERIAL: SERIAL, CONF_MAC: MAC},
            discovered(ip=NEW_HOST, serial="SN0000000002", mac=MAC),
        ),
        (
            {CONF_MAC: MAC},
            discovered(ip=NEW_HOST, serial="SN0000000002", mac="00:00:5E:00:53:2B"),
        ),
    ],
    ids=["serial", "mac"],
)
async def test_reconfigure_refuses_a_different_camera(
    hass: HomeAssistant,
    mock_camera: FakeSannceCamera,
    mock_find_camera: AsyncMock,
    identity: dict[str, str],
    found: lib.DiscoveredCamera,
) -> None:
    entry = camera_entry(**identity)
    result = await start_reconfigure(hass, entry)
    mock_find_camera.return_value = found

    result = await submit(hass, result, USER_INPUT | {CONF_HOST: NEW_HOST})

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "wrong_camera"
    assert entry.data[CONF_HOST] == HOST


async def test_reconfigure_matches_the_mac_in_any_format(
    hass: HomeAssistant, mock_camera: FakeSannceCamera, mock_find_camera: AsyncMock
) -> None:
    entry = camera_entry(mac="00-00-5e-00-53-2a")
    result = await start_reconfigure(hass, entry)
    mock_find_camera.return_value = discovered(ip=NEW_HOST, serial="")

    result = await submit(hass, result, USER_INPUT | {CONF_HOST: NEW_HOST})
    await hass.async_block_till_done()

    assert result["reason"] == "reconfigure_successful"
    assert entry.data[CONF_HOST] == NEW_HOST


async def test_reconfigure_to_another_configured_camera_aborts(
    hass: HomeAssistant, mock_camera: FakeSannceCamera, mock_find_camera: AsyncMock
) -> None:
    add_entry(hass, "192.168.1.99", SERIAL)
    entry = camera_entry()
    result = await start_reconfigure(hass, entry)
    mock_find_camera.return_value = discovered(ip=NEW_HOST)

    result = await submit(hass, result, USER_INPUT | {CONF_HOST: NEW_HOST})

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert entry.data[CONF_HOST] == HOST


async def test_reconfigure_to_an_address_in_use_aborts(
    hass: HomeAssistant, mock_camera: FakeSannceCamera
) -> None:
    add_entry(hass, NEW_HOST, NEW_HOST)
    entry = camera_entry()
    result = await start_reconfigure(hass, entry)
    connects = mock_camera.connect.await_count

    result = await submit(hass, result, USER_INPUT | {CONF_HOST: NEW_HOST})

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert mock_camera.connect.await_count == connects


def test_strings_cover_the_flow() -> None:
    config = json.loads((INTEGRATION_DIR / "strings.json").read_text())["config"]

    assert set(config["step"]) == {
        "user",
        "pick_camera",
        "reauth_confirm",
        "reconfigure",
    }
    assert set(config["step"]["user"]["data"]) == {
        CONF_HOST,
        CONF_USERNAME,
        CONF_PASSWORD,
        CONF_NVS_PORT,
        CONF_HTTP_PORT,
        CONF_RTSP_PORT,
    }
    assert set(config["step"]["reconfigure"]["data"]) == set(
        config["step"]["user"]["data"]
    )
    assert set(config["step"]["pick_camera"]["data"]) == {CONF_HOST}
    assert set(config["step"]["reauth_confirm"]["data"]) == {CONF_PASSWORD}
    for name in (CONF_HOST, CONF_USERNAME):
        assert f"{{{name}}}" in config["step"]["reauth_confirm"]["description"]
    assert set(config["error"]) == {
        "cannot_connect",
        "invalid_auth",
        "invalid_host",
        "no_cameras_found",
        "unknown",
    }
    assert set(config["abort"]) == {
        "already_configured",
        "reauth_successful",
        "wrong_camera",
    }


def test_translations_match_strings() -> None:
    strings = (INTEGRATION_DIR / "strings.json").read_text()
    english = (INTEGRATION_DIR / "translations" / "en.json").read_text()

    assert json.loads(english) == json.loads(strings)
