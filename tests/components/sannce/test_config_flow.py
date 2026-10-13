import json
from collections.abc import Generator
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import probatio
import pytest
from homeassistant.config_entries import (
    SOURCE_DHCP,
    SOURCE_IGNORE,
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
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.service_info.dhcp import DhcpServiceInfo
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
LOGIN = {CONF_USERNAME: USERNAME, CONF_PASSWORD: PASSWORD}
OTHER_HOST = "192.168.1.99"
IDENTIFIED = lib.CameraInfo(model="I91FW", serial=SERIAL, firmware="1.0.0", mac=MAC)
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


def keyed_entry(
    hass: HomeAssistant, unique_id: str, host: str = OTHER_HOST, **identity: str
) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=unique_id,
        data=USER_INPUT | DEFAULT_PORTS | {CONF_HOST: host} | identity,
    )
    entry.add_to_hass(hass)
    return entry


def ignored_entry(hass: HomeAssistant, unique_id: str) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN, source=SOURCE_IGNORE, unique_id=unique_id, data={}
    )
    entry.add_to_hass(hass)
    return entry


def siren_id(registry: er.EntityRegistry, key: str) -> str | None:
    return registry.async_get_entity_id("siren", DOMAIN, f"{key}_siren")


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


async def start_dhcp(
    hass: HomeAssistant, ip: str = HOST, mac: str = "00005e00532a"
) -> ConfigFlowResult:
    return await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_DHCP},
        data=DhcpServiceInfo(ip=ip, hostname="ipc", macaddress=mac),
    )


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
    mock_find_camera: AsyncMock,
    mock_camera: FakeSannceCamera,
    mock_setup_entry: AsyncMock,
) -> None:
    mock_camera.info = IDENTIFIED
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
    mock_find_camera.assert_not_awaited()


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
    "stored",
    [{CONF_SERIAL: SERIAL}, {CONF_MAC: "00-00-5e-00-53-2a"}],
    ids=["serial", "mac"],
)
async def test_adding_a_camera_an_address_keyed_entry_knows_aborts(
    hass: HomeAssistant, mock_camera: FakeSannceCamera, stored: dict[str, str]
) -> None:
    entry = keyed_entry(hass, OTHER_HOST, **stored)
    mock_camera.info = IDENTIFIED
    result = await start_flow(hass)

    result = await submit(hass, result, USER_INPUT)

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert hass.config_entries.async_entries(DOMAIN) == [entry]


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
    keyed_entry(hass, "192.168.1.70", "192.168.1.70", serial="SN0000000005")
    keyed_entry(hass, "192.168.1.80", "192.168.1.80", mac="00:00:5E:00:53:2C")
    ignored_entry(hass, "SN0000000009")
    mock_discover.return_value = [
        discovered(ip="192.168.1.60", serial=SERIAL),
        discovered(ip="192.168.1.12", serial="SN0000000002"),
        discovered(ip="192.168.1.13", serial="SN0000000003"),
        discovered(ip="192.168.1.71", serial="SN0000000005", mac=""),
        discovered(ip="192.168.1.81", serial="", mac="00:00:5e:00:53:2c"),
        discovered(ip="192.168.1.91", serial="SN0000000009"),
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
    assert entry.unique_id == SERIAL


async def test_reconfigure_moves_an_address_key_and_the_entity_ids(
    hass: HomeAssistant,
    mock_camera: FakeSannceCamera,
    entity_registry: er.EntityRegistry,
    device_registry: dr.DeviceRegistry,
) -> None:
    entry = camera_entry(mac=MAC)
    result = await start_reconfigure(hass, entry)
    siren = siren_id(entity_registry, HOST)
    entities = er.async_entries_for_config_entry(entity_registry, entry.entry_id)

    result = await submit(hass, result, USER_INPUT | {CONF_HOST: NEW_HOST})
    await hass.async_block_till_done()

    assert result["reason"] == "reconfigure_successful"
    assert entry.unique_id == NEW_HOST
    assert siren is not None
    assert siren_id(entity_registry, NEW_HOST) == siren
    moved = er.async_entries_for_config_entry(entity_registry, entry.entry_id)
    assert len(moved) == len(entities)
    [device] = dr.async_entries_for_config_entry(device_registry, entry.entry_id)
    assert device.identifiers == {(DOMAIN, NEW_HOST)}
    assert entry.state is ConfigEntryState.LOADED


async def test_reconfigure_frees_the_old_address_for_another_camera(
    hass: HomeAssistant, mock_camera: FakeSannceCamera, mock_setup_entry: AsyncMock
) -> None:
    entry = add_entry(hass, HOST, HOST)
    result = await entry.start_reconfigure_flow(hass)
    result = await submit(hass, result, USER_INPUT | {CONF_HOST: NEW_HOST})
    assert result["reason"] == "reconfigure_successful"

    result = await submit(hass, await start_flow(hass), USER_INPUT)

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["result"].unique_id == HOST
    assert entry.unique_id == NEW_HOST


@pytest.mark.parametrize(
    ("stored", "found", "kept", "unique_id"),
    [
        ({CONF_SERIAL: SERIAL, CONF_MAC: MAC}, None, {}, NEW_HOST),
        (
            {CONF_MAC: MAC},
            discovered(ip=NEW_HOST, serial="SN0000000002", mac=""),
            {CONF_SERIAL: "SN0000000002"},
            "SN0000000002",
        ),
    ],
    ids=["nothing_known", "no_shared_key"],
)
async def test_reconfigure_to_an_unproven_camera_forgets_the_old_identity(
    hass: HomeAssistant,
    mock_camera: FakeSannceCamera,
    mock_find_camera: AsyncMock,
    device_registry: dr.DeviceRegistry,
    stored: dict[str, str],
    found: lib.DiscoveredCamera | None,
    kept: dict[str, str],
    unique_id: str,
) -> None:
    entry = camera_entry(model="I91FW", **stored)
    result = await start_reconfigure(hass, entry)
    mock_find_camera.return_value = found

    result = await submit(hass, result, USER_INPUT | {CONF_HOST: NEW_HOST})
    await hass.async_block_till_done()

    assert result["reason"] == "reconfigure_successful"
    identity = {key: entry.data.get(key) for key in (CONF_SERIAL, CONF_MAC)}
    assert {key: value for key, value in identity.items() if value} == kept
    assert entry.unique_id == unique_id
    [device] = dr.async_entries_for_config_entry(device_registry, entry.entry_id)
    assert device.connections == set()

    mock_find_camera.return_value = discovered()
    result = await start_dhcp(hass)
    await hass.async_block_till_done()

    assert result["step_id"] == "dhcp_confirm"
    assert entry.data[CONF_HOST] == NEW_HOST


async def test_reconfigure_at_the_same_address_keeps_the_identity(
    hass: HomeAssistant, mock_camera: FakeSannceCamera
) -> None:
    entry = camera_entry(model="I91FW", serial=SERIAL, mac=MAC)
    result = await start_reconfigure(hass, entry)

    result = await submit(hass, result, USER_INPUT | {CONF_USERNAME: "viewer"})
    await hass.async_block_till_done()

    assert result["reason"] == "reconfigure_successful"
    assert (entry.data[CONF_SERIAL], entry.data[CONF_MAC]) == (SERIAL, MAC)
    assert entry.unique_id == SERIAL


async def test_reconfigure_skips_the_lan_search_when_the_login_gives_the_identity(
    hass: HomeAssistant, mock_camera: FakeSannceCamera, mock_find_camera: AsyncMock
) -> None:
    mock_camera.info = IDENTIFIED
    entry = camera_entry(model="I91FW", serial=SERIAL, mac=MAC)
    result = await start_reconfigure(hass, entry)

    result = await submit(hass, result, USER_INPUT | {CONF_HOST: NEW_HOST})
    await hass.async_block_till_done()

    assert result["reason"] == "reconfigure_successful"
    assert entry.data[CONF_HOST] == NEW_HOST
    mock_find_camera.assert_not_awaited()


async def test_reconfigure_takes_a_camera_whose_discovery_was_ignored(
    hass: HomeAssistant,
    mock_camera: FakeSannceCamera,
    mock_find_camera: AsyncMock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    ignored_entry(hass, SERIAL)
    entry = camera_entry()
    result = await start_reconfigure(hass, entry)
    mock_find_camera.return_value = discovered(ip=NEW_HOST)

    result = await submit(hass, result, USER_INPUT | {CONF_HOST: NEW_HOST})
    await hass.async_block_till_done()

    assert result["reason"] == "reconfigure_successful"
    assert entry.unique_id == SERIAL
    assert hass.config_entries.async_entries(DOMAIN, include_ignore=True) == [entry]
    assert "already in use" not in caplog.text


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


@pytest.mark.parametrize(
    "stored",
    [{CONF_SERIAL: SERIAL}, {CONF_MAC: "00-00-5e-00-53-2a"}],
    ids=["serial", "mac"],
)
async def test_reconfigure_to_a_camera_an_address_keyed_entry_knows_aborts(
    hass: HomeAssistant,
    mock_camera: FakeSannceCamera,
    mock_find_camera: AsyncMock,
    stored: dict[str, str],
) -> None:
    keyed_entry(hass, OTHER_HOST, **stored)
    entry = camera_entry()
    result = await start_reconfigure(hass, entry)
    mock_find_camera.return_value = discovered(ip=NEW_HOST)

    result = await submit(hass, result, USER_INPUT | {CONF_HOST: NEW_HOST})

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert entry.data[CONF_HOST] == HOST


async def test_reconfigure_leaves_a_key_another_entry_holds(
    hass: HomeAssistant, mock_camera: FakeSannceCamera
) -> None:
    keyed_entry(hass, NEW_HOST)
    entry = camera_entry()
    result = await start_reconfigure(hass, entry)

    result = await submit(hass, result, USER_INPUT | {CONF_HOST: NEW_HOST})

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert (entry.unique_id, entry.data[CONF_HOST]) == (HOST, HOST)


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


async def test_dhcp_adds_a_new_camera_after_the_login(
    hass: HomeAssistant,
    mock_find_camera: AsyncMock,
    mock_camera_class: MagicMock,
    mock_camera: FakeSannceCamera,
    mock_setup_entry: AsyncMock,
) -> None:
    mock_find_camera.return_value = discovered()

    result = await start_dhcp(hass)

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "dhcp_confirm"
    assert result["description_placeholders"] == {"name": f"I91FW ({HOST})"}
    assert list(fields(result)) == [CONF_USERNAME, CONF_PASSWORD]
    mock_find_camera.assert_awaited_once_with(HOST)

    result = await submit(hass, result, LOGIN)

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "I91FW"
    assert result["result"].unique_id == SERIAL
    assert result["data"] == USER_INPUT | {
        CONF_NVS_PORT: 3001,
        CONF_HTTP_PORT: 8080,
        CONF_RTSP_PORT: 554,
        CONF_MODEL: "I91FW",
        CONF_SERIAL: SERIAL,
        CONF_MAC: MAC,
    }
    assert mock_camera_class.call_args.kwargs["nvs_port"] == 3001


async def test_dhcp_confirm_shows_a_failed_login(
    hass: HomeAssistant,
    mock_find_camera: AsyncMock,
    mock_camera: FakeSannceCamera,
    mock_setup_entry: AsyncMock,
) -> None:
    mock_find_camera.return_value = discovered()
    mock_camera.connect.side_effect = lib.AuthError("bad password")
    result = await start_dhcp(hass)

    result = await submit(hass, result, LOGIN)

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "dhcp_confirm"
    assert result["errors"] == {"base": "invalid_auth"}

    mock_camera.connect.side_effect = None
    result = await submit(hass, result, LOGIN)

    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_dhcp_offers_a_camera_that_does_not_answer_the_lookup(
    hass: HomeAssistant,
    mock_find_camera: AsyncMock,
    mock_camera: FakeSannceCamera,
    mock_setup_entry: AsyncMock,
) -> None:
    result = await start_dhcp(hass)

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "dhcp_confirm"
    assert result["description_placeholders"] == {"name": f"SANNCE ({HOST})"}

    result = await submit(hass, result, LOGIN)

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == HOST
    assert result["result"].unique_id == HOST
    assert result["data"] == USER_INPUT | DEFAULT_PORTS | {CONF_MAC: MAC.lower()}


async def test_dhcp_lookup_failure_still_checks_the_login(
    hass: HomeAssistant,
    mock_camera: FakeSannceCamera,
    mock_setup_entry: AsyncMock,
) -> None:
    mock_camera.connect.side_effect = lib.ConnectError("offline")
    result = await start_dhcp(hass)

    result = await submit(hass, result, LOGIN)

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_dhcp_moves_a_known_camera_to_its_new_address(
    hass: HomeAssistant,
    mock_find_camera: AsyncMock,
    mock_camera_class: MagicMock,
    mock_camera: FakeSannceCamera,
) -> None:
    entry = camera_entry(model="I91FW", serial=SERIAL, mac=MAC)
    await setup_integration(hass, entry)

    result = await start_dhcp(hass, ip=NEW_HOST)
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert entry.data[CONF_HOST] == NEW_HOST
    assert entry.state is ConfigEntryState.LOADED
    assert mock_camera_class.call_args.args[0] == NEW_HOST
    mock_find_camera.assert_not_awaited()


async def test_dhcp_moves_an_address_key_with_the_address(
    hass: HomeAssistant,
    mock_find_camera: AsyncMock,
    mock_camera: FakeSannceCamera,
    entity_registry: er.EntityRegistry,
) -> None:
    entry = camera_entry(mac=MAC)
    await setup_integration(hass, entry)
    siren = siren_id(entity_registry, HOST)

    result = await start_dhcp(hass, ip=NEW_HOST)
    await hass.async_block_till_done()

    assert result["reason"] == "already_configured"
    assert (entry.unique_id, entry.data[CONF_HOST]) == (NEW_HOST, NEW_HOST)
    assert siren is not None
    assert siren_id(entity_registry, NEW_HOST) == siren
    assert entry.state is ConfigEntryState.LOADED


async def test_dhcp_leaves_a_key_another_entry_holds(
    hass: HomeAssistant, mock_find_camera: AsyncMock
) -> None:
    keyed_entry(hass, NEW_HOST)
    entry = camera_entry(mac=MAC)
    entry.add_to_hass(hass)

    result = await start_dhcp(hass, ip=NEW_HOST)

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert (entry.unique_id, entry.data[CONF_HOST]) == (HOST, HOST)


async def test_dhcp_at_the_known_address_changes_nothing(
    hass: HomeAssistant,
    mock_find_camera: AsyncMock,
    mock_camera_class: MagicMock,
    mock_camera: FakeSannceCamera,
) -> None:
    entry = camera_entry(model="I91FW", serial=SERIAL, mac=MAC)
    await setup_integration(hass, entry)

    result = await start_dhcp(hass)
    await hass.async_block_till_done()

    assert result["reason"] == "already_configured"
    assert entry.data[CONF_HOST] == HOST
    assert mock_camera_class.call_count == 1


async def test_dhcp_for_a_camera_added_by_address_aborts(
    hass: HomeAssistant, mock_find_camera: AsyncMock
) -> None:
    entry = add_entry(hass, HOST, HOST)

    result = await start_dhcp(hass)

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert hass.config_entries.async_entries(DOMAIN) == [entry]
    mock_find_camera.assert_not_awaited()


async def test_dhcp_leaves_an_entry_without_a_unique_id_alone(
    hass: HomeAssistant, mock_find_camera: AsyncMock
) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN, data=USER_INPUT | DEFAULT_PORTS | {CONF_MAC: MAC}
    )
    entry.add_to_hass(hass)

    result = await start_dhcp(hass, ip=NEW_HOST)

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert entry.data[CONF_HOST] == HOST
    mock_find_camera.assert_not_awaited()


async def test_dhcp_finds_a_known_serial_at_a_new_address(
    hass: HomeAssistant,
    mock_find_camera: AsyncMock,
    mock_camera: FakeSannceCamera,
) -> None:
    entry = camera_entry(model="I91FW", serial=SERIAL)
    await setup_integration(hass, entry)
    mock_find_camera.return_value = discovered(ip=NEW_HOST)

    result = await start_dhcp(hass, ip=NEW_HOST)
    await hass.async_block_till_done()

    assert result["reason"] == "already_configured"
    assert entry.data[CONF_HOST] == NEW_HOST
    assert entry.state is ConfigEntryState.LOADED


async def test_dhcp_keeps_a_stale_host_key_off_another_camera(
    hass: HomeAssistant,
    mock_find_camera: AsyncMock,
    mock_camera_class: MagicMock,
    mock_camera: FakeSannceCamera,
) -> None:
    entry = camera_entry(host=NEW_HOST, mac=MAC)
    await setup_integration(hass, entry)
    mock_find_camera.return_value = discovered(serial="", mac="00:00:5E:00:53:99")

    result = await start_dhcp(hass, mac="00005e005399")
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert entry.unique_id == HOST
    assert entry.data[CONF_HOST] == NEW_HOST
    assert mock_camera_class.call_count == 1


async def test_dhcp_follows_the_serial_stored_in_a_host_keyed_entry(
    hass: HomeAssistant,
    mock_find_camera: AsyncMock,
    mock_camera: FakeSannceCamera,
) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=HOST,
        data=USER_INPUT | DEFAULT_PORTS | {CONF_SERIAL: SERIAL},
    )
    await setup_integration(hass, entry)
    mock_find_camera.return_value = discovered(ip=NEW_HOST)

    result = await start_dhcp(hass, ip=NEW_HOST)
    await hass.async_block_till_done()

    assert result["reason"] == "already_configured"
    assert entry.data[CONF_HOST] == NEW_HOST
    assert entry.state is ConfigEntryState.LOADED
    assert hass.config_entries.async_entries(DOMAIN) == [entry]


async def test_dhcp_does_not_move_a_camera_onto_a_host_in_use(
    hass: HomeAssistant,
    mock_find_camera: AsyncMock,
    mock_camera_class: MagicMock,
    mock_camera: FakeSannceCamera,
) -> None:
    moving = camera_entry(model="I91FW", serial=SERIAL, mac=MAC)
    holder = camera_entry(host=NEW_HOST, serial="SN0000000002")
    await setup_integration(hass, moving)
    await setup_integration(hass, holder)

    result = await start_dhcp(hass, ip=NEW_HOST)
    await hass.async_block_till_done()

    assert result["reason"] == "already_configured"
    assert moving.data[CONF_HOST] == HOST
    assert holder.data[CONF_HOST] == NEW_HOST
    mock_find_camera.assert_not_awaited()


async def test_dhcp_leaves_an_ignored_camera_alone(
    hass: HomeAssistant, mock_find_camera: AsyncMock
) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN, source=SOURCE_IGNORE, unique_id=SERIAL, data={}
    )
    entry.add_to_hass(hass)
    mock_find_camera.return_value = discovered(ip=NEW_HOST)

    result = await start_dhcp(hass, ip=NEW_HOST)

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert entry.data == {}


async def test_a_second_dhcp_flow_for_the_camera_aborts(
    hass: HomeAssistant, mock_find_camera: AsyncMock
) -> None:
    mock_find_camera.return_value = discovered()
    first = await start_dhcp(hass)

    second = await start_dhcp(hass)

    assert first["step_id"] == "dhcp_confirm"
    assert second["type"] is FlowResultType.ABORT
    assert second["reason"] == "already_in_progress"


def test_strings_cover_the_flow() -> None:
    config = json.loads((INTEGRATION_DIR / "strings.json").read_text())["config"]

    assert set(config["step"]) == {
        "user",
        "pick_camera",
        "dhcp_confirm",
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
    assert set(config["step"]["dhcp_confirm"]["data"]) == {CONF_USERNAME, CONF_PASSWORD}
    assert "{name}" in config["step"]["dhcp_confirm"]["description"]
    assert config["flow_title"] == "{name}"
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
