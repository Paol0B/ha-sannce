import logging
from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import (
    CONF_HOST,
    CONF_MAC,
    CONF_MODEL,
    CONF_PASSWORD,
    CONF_USERNAME,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv

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

USER_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_HOST, default=""): str,
        vol.Required(CONF_USERNAME, default=DEFAULT_USERNAME): str,
        vol.Optional(CONF_PASSWORD, default=""): str,
        vol.Optional(CONF_NVS_PORT, default=DEFAULT_NVS_PORT): cv.port,
        vol.Optional(CONF_HTTP_PORT, default=DEFAULT_HTTP_PORT): cv.port,
        vol.Optional(CONF_RTSP_PORT, default=DEFAULT_RTSP_PORT): cv.port,
    }
)
REAUTH_SCHEMA = vol.Schema({vol.Required(CONF_PASSWORD): str})


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


def _label(camera: lib.DiscoveredCamera) -> str:
    return f"{camera.model or 'SANNCE'} ({camera.ip})"


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
            return self._show_user_form(
                self._input
                | {
                    CONF_HOST: camera.ip,
                    CONF_NVS_PORT: camera.server_port or DEFAULT_NVS_PORT,
                    CONF_HTTP_PORT: camera.http_port or DEFAULT_HTTP_PORT,
                },
                {},
            )

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
            if camera.ip not in known and camera.serial not in known
        }
        if not self._found:
            return self._show_user_form(self._input, {"base": "no_cameras_found"})
        return self.async_show_form(
            step_id="pick_camera",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_HOST): vol.In(
                        {ip: _label(camera) for ip, camera in self._found.items()}
                    )
                }
            ),
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
        found = self._found.get(host)
        serial = info.serial or (found and found.serial)
        model = info.model or (found and found.model)
        mac = info.mac or (found and found.mac)
        await self.async_set_unique_id(serial or host)
        self._abort_if_unique_id_configured()
        identity = {CONF_MODEL: model, CONF_SERIAL: serial, CONF_MAC: mac}
        return self.async_create_entry(
            title=model or host,
            data=data | {key: value for key, value in identity.items() if value},
        )
