import logging
from collections.abc import Mapping
from typing import Any

import probatio
from homeassistant.config_entries import (
    SOURCE_IGNORE,
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
)
from homeassistant.const import (
    CONF_HOST,
    CONF_MAC,
    CONF_MODEL,
    CONF_PASSWORD,
    CONF_USERNAME,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC, format_mac
from homeassistant.helpers.service_info.dhcp import DhcpServiceInfo

from . import lib
from .const import (
    CONF_HTTP_PORT,
    CONF_NVS_PORT,
    CONF_RTSP_PORT,
    CONF_SERIAL,
    DEFAULT_HTTP_PORT,
    DEFAULT_NVS_PORT,
    DEFAULT_RTSP_PORT,
    DEFAULT_USERNAME,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

USER_SCHEMA = probatio.Schema(
    {
        probatio.Optional(CONF_HOST, default=""): str,
        probatio.Required(CONF_USERNAME, default=DEFAULT_USERNAME): str,
        probatio.Optional(CONF_PASSWORD, default=""): str,
        probatio.Optional(CONF_NVS_PORT, default=DEFAULT_NVS_PORT): cv.port,
        probatio.Optional(CONF_HTTP_PORT, default=DEFAULT_HTTP_PORT): cv.port,
        probatio.Optional(CONF_RTSP_PORT, default=DEFAULT_RTSP_PORT): cv.port,
    }
)
LOGIN_SCHEMA = probatio.Schema(
    {
        probatio.Required(CONF_USERNAME, default=DEFAULT_USERNAME): str,
        probatio.Required(CONF_PASSWORD): str,
    }
)
REAUTH_SCHEMA = probatio.Schema({probatio.Required(CONF_PASSWORD): str})
RECONFIGURE_SCHEMA = probatio.Schema(
    {
        probatio.Required(CONF_HOST): str,
        probatio.Required(CONF_USERNAME): str,
        probatio.Optional(CONF_PASSWORD, default=""): str,
        probatio.Required(CONF_NVS_PORT, default=DEFAULT_NVS_PORT): cv.port,
        probatio.Required(CONF_HTTP_PORT, default=DEFAULT_HTTP_PORT): cv.port,
        probatio.Required(CONF_RTSP_PORT, default=DEFAULT_RTSP_PORT): cv.port,
    }
)


class _ProbeError(Exception):
    pass


async def _async_probe(hass: HomeAssistant, data: Mapping[str, Any]) -> lib.CameraInfo:
    try:
        camera = lib.create_camera(hass, data)
    except ValueError as err:
        raise _ProbeError("invalid_host") from err
    try:
        await camera.connect()
        return camera.info
    except lib.AuthError as err:
        raise _ProbeError("invalid_auth") from err
    except lib.SannceError as err:
        raise _ProbeError("cannot_connect") from err
    except Exception as err:
        _LOGGER.exception("Unexpected error while connecting to %s", data[CONF_HOST])
        raise _ProbeError("unknown") from err
    finally:
        await camera.close()


async def _async_find(host: str) -> lib.DiscoveredCamera | None:
    try:
        return await lib.find_camera(host)
    except OSError as err:
        _LOGGER.debug("Searching the network for %s failed: %s", host, err)
        return None


def _identity(
    info: lib.CameraInfo, found: lib.DiscoveredCamera | None
) -> dict[str, str]:
    identity = {CONF_MODEL: info.model, CONF_SERIAL: info.serial, CONF_MAC: info.mac}
    if found:
        searched = {
            CONF_MODEL: found.model,
            CONF_SERIAL: found.serial,
            CONF_MAC: found.mac,
        }
        identity = {key: value or searched[key] for key, value in identity.items()}
    return {key: value for key, value in identity.items() if value}


def _same_camera(known: Mapping[str, Any], seen: Mapping[str, str]) -> bool | None:
    # the serial decides when both sides know it, else the MAC, else nothing does
    if known.get(CONF_SERIAL) and seen.get(CONF_SERIAL):
        return str(known[CONF_SERIAL]) == seen[CONF_SERIAL]
    if known.get(CONF_MAC) and seen.get(CONF_MAC):
        return format_mac(known[CONF_MAC]) == format_mac(seen[CONF_MAC])
    return None


def _knows(entry: ConfigEntry, identity: Mapping[str, str]) -> bool:
    serial = identity.get(CONF_SERIAL)
    if serial and serial in (entry.unique_id, entry.data.get(CONF_SERIAL)):
        return True
    mac, known = identity.get(CONF_MAC), entry.data.get(CONF_MAC)
    return bool(mac and known and format_mac(mac) == format_mac(known))


def _key(entry: ConfigEntry, data: Mapping[str, Any]) -> str | None:
    # the serial keys an entry; without one the address does and moves with it
    if data.get(CONF_SERIAL):
        return str(data[CONF_SERIAL])
    return None if entry.unique_id is None else str(data[CONF_HOST])


@callback
def _async_move_ids(
    hass: HomeAssistant, entry: ConfigEntry, key: str, mac: str | None
) -> None:
    # entities and the device take their ids from the entry's unique id
    old = entry.unique_id or entry.entry_id
    entities = er.async_get(hass)
    for entity in er.async_entries_for_config_entry(entities, entry.entry_id):
        name = entity.unique_id.removeprefix(f"{old}_")
        entities.async_update_entity(entity.entity_id, new_unique_id=f"{key}_{name}")
    devices = dr.async_get(hass)
    connections = {(CONNECTION_NETWORK_MAC, format_mac(mac))} if mac else set()
    for device in dr.async_entries_for_config_entry(devices, entry.entry_id):
        devices.async_update_device(
            device.id, new_identifiers={(DOMAIN, key)}, new_connections=connections
        )


def _label(camera: lib.DiscoveredCamera) -> str:
    return f"{camera.model or 'SANNCE'} ({camera.ip})"


def _unanswered(host: str, mac: str) -> lib.DiscoveredCamera:
    return lib.DiscoveredCamera(
        ip=host, mac=mac, serial="", model="", http_port=0, server_port=0, channels=0
    )


def _settings(camera: lib.DiscoveredCamera) -> dict[str, Any]:
    return {
        CONF_HOST: camera.ip,
        CONF_NVS_PORT: camera.server_port or DEFAULT_NVS_PORT,
        CONF_HTTP_PORT: camera.http_port or DEFAULT_HTTP_PORT,
    }


class SannceConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._input: dict[str, Any] = {}
        self._found: dict[str, lib.DiscoveredCamera] = {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            host = user_input[CONF_HOST]
            if not host:
                self._input = user_input
                return await self.async_step_pick_camera()
            self._async_abort_entries_match({CONF_HOST: host})
            try:
                info = await _async_probe(self.hass, user_input)
            except _ProbeError as err:
                errors["base"] = str(err)
            else:
                return await self._async_create_entry(user_input, info)
        return self._show_user_form(user_input, errors)

    async def async_step_pick_camera(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            camera = self._found[user_input[CONF_HOST]]
            return self._show_user_form(self._input | _settings(camera), {})

        known = self._async_current_ids() | {
            entry.data[CONF_HOST] for entry in self._async_current_entries()
        }
        try:
            cameras = await lib.discover()
        except OSError as err:
            _LOGGER.warning("Searching the network failed: %s", err)
            cameras = []
        self._found = {
            camera.ip: camera
            for camera in cameras
            if camera.ip not in known
            and not self._entry_for_camera(
                {CONF_SERIAL: camera.serial, CONF_MAC: camera.mac}, include_ignore=True
            )
        }
        if not self._found:
            return self._show_user_form(self._input, {"base": "no_cameras_found"})
        return self.async_show_form(
            step_id="pick_camera",
            data_schema=probatio.Schema(
                {
                    probatio.Required(CONF_HOST): probatio.In(
                        {ip: _label(camera) for ip, camera in self._found.items()}
                    )
                }
            ),
        )

    async def async_step_dhcp(
        self, discovery_info: DhcpServiceInfo
    ) -> ConfigFlowResult:
        host = discovery_info.ip
        mac = format_mac(discovery_info.macaddress)
        if entry := self._entry_for_camera({CONF_MAC: mac}):
            return await self._async_follow(entry, host)
        self._async_abort_entries_match({CONF_HOST: host})
        camera = await _async_find(host) or _unanswered(host, mac)
        if entry := self._entry_for_camera({CONF_SERIAL: camera.serial}):
            return await self._async_follow(entry, host)
        await self.async_set_unique_id(camera.serial or host)
        self._abort_if_unique_id_configured()
        self._found = {host: camera}
        self._input = _settings(camera) | {CONF_RTSP_PORT: DEFAULT_RTSP_PORT}
        self.context["title_placeholders"] = {"name": _label(camera)}
        return await self.async_step_dhcp_confirm()

    async def async_step_dhcp_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            data = self._input | user_input
            try:
                info = await _async_probe(self.hass, data)
            except _ProbeError as err:
                errors["base"] = str(err)
            else:
                return await self._async_create_entry(data, info)
        camera = self._found[self._input[CONF_HOST]]
        return self.async_show_form(
            step_id="dhcp_confirm",
            data_schema=self.add_suggested_values_to_schema(LOGIN_SCHEMA, user_input),
            description_placeholders={"name": _label(camera)},
            errors=errors,
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                await _async_probe(self.hass, entry.data | user_input)
            except _ProbeError as err:
                errors["base"] = str(err)
            else:
                return self.async_update_reload_and_abort(
                    entry, data_updates=user_input
                )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=REAUTH_SCHEMA,
            description_placeholders={
                CONF_HOST: entry.data[CONF_HOST],
                CONF_USERNAME: entry.data[CONF_USERNAME],
            },
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            host = user_input[CONF_HOST]
            self._async_abort_entries_match({CONF_HOST: host})
            data = user_input | {
                CONF_PASSWORD: user_input[CONF_PASSWORD] or entry.data[CONF_PASSWORD]
            }
            try:
                info = await _async_probe(self.hass, data)
            except _ProbeError as err:
                errors["base"] = str(err)
            else:
                return await self._async_reconfigure(entry, data, info)
        current = {
            key: value
            for key, value in (user_input or entry.data).items()
            if key != CONF_PASSWORD
        }
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                RECONFIGURE_SCHEMA, current
            ),
            errors=errors,
        )

    async def _async_follow(self, entry: ConfigEntry, host: str) -> ConfigFlowResult:
        others = self._async_current_entries(include_ignore=False)
        if any(o is not entry and o.data.get(CONF_HOST) == host for o in others):
            return self.async_abort(reason="already_configured")
        key = _key(entry, entry.data | {CONF_HOST: host})
        await self.async_set_unique_id(key)
        if not await self._async_rekey(entry, key, entry.data.get(CONF_MAC)):
            return self.async_abort(reason="already_configured")
        self.hass.config_entries.async_update_entry(entry, unique_id=key)
        self._abort_if_unique_id_configured(updates={CONF_HOST: host})
        # the helper returns, not aborts, when the entry has no unique id
        return self.async_abort(reason="already_configured")

    async def _async_reconfigure(
        self, entry: ConfigEntry, settings: dict[str, Any], info: lib.CameraInfo
    ) -> ConfigFlowResult:
        host = settings[CONF_HOST]
        identity = await self._async_identity(host, info)
        if self._entry_for_camera(identity, other_than=entry):
            return self.async_abort(reason="already_configured")
        same = _same_camera(entry.data, identity)
        if same is False:
            return self.async_abort(reason="wrong_camera")
        data = dict(entry.data)
        if same is None and host != entry.data[CONF_HOST]:
            # nothing ties the camera at the new address to the stored identity
            data.pop(CONF_SERIAL, None)
            data.pop(CONF_MAC, None)
        data |= settings | identity
        key = _key(entry, data)
        if not await self._async_rekey(entry, key, data.get(CONF_MAC)):
            return self.async_abort(reason="already_configured")
        return self.async_update_reload_and_abort(entry, unique_id=key, data=data)

    async def _async_rekey(
        self, entry: ConfigEntry, key: str | None, mac: str | None
    ) -> bool:
        if key is None or key == entry.unique_id:
            return True
        entries = self.hass.config_entries
        if holder := entries.async_entry_for_domain_unique_id(DOMAIN, key):
            if holder.source != SOURCE_IGNORE:
                return False
            # configuring the camera ends the ignore, as a user flow would
            await entries.async_remove(holder.entry_id)
        _async_move_ids(self.hass, entry, key, mac)
        return True

    def _entry_for_camera(
        self,
        identity: Mapping[str, str],
        *,
        other_than: ConfigEntry | None = None,
        include_ignore: bool = False,
    ) -> ConfigEntry | None:
        return next(
            (
                entry
                for entry in self._async_current_entries(include_ignore=include_ignore)
                if entry is not other_than and _knows(entry, identity)
            ),
            None,
        )

    async def _async_identity(
        self, host: str, info: lib.CameraInfo
    ) -> dict[str, str]:
        found = self._found.get(host)
        if found is None and not (info.serial and info.model and info.mac):
            found = await _async_find(host)
        return _identity(info, found)

    def _show_user_form(
        self, suggested: Mapping[str, Any] | None, errors: dict[str, str]
    ) -> ConfigFlowResult:
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(USER_SCHEMA, suggested),
            errors=errors,
        )

    async def _async_create_entry(
        self, data: dict[str, Any], info: lib.CameraInfo
    ) -> ConfigFlowResult:
        host = data[CONF_HOST]
        identity = await self._async_identity(host, info)
        if self._entry_for_camera(identity):
            return self.async_abort(reason="already_configured")
        await self.async_set_unique_id(identity.get(CONF_SERIAL) or host)
        self._abort_if_unique_id_configured()
        return self.async_create_entry(
            title=identity.get(CONF_MODEL) or host, data=data | identity
        )
