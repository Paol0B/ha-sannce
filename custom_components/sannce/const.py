from datetime import timedelta

from homeassistant.const import Platform

DOMAIN = "sannce"
MANUFACTURER = "SANNCE"

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.CAMERA,
    Platform.LIGHT,
    Platform.MEDIA_PLAYER,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SIREN,
    Platform.SWITCH,
]

CONF_NVS_PORT = "nvs_port"
CONF_HTTP_PORT = "http_port"
CONF_RTSP_PORT = "rtsp_port"
CONF_SERIAL = "serial"

DEFAULT_USERNAME = "admin"
DEFAULT_NVS_PORT = 3002
# version 1 entries used the TCP port the I91FX keeps closed (protocol.md, Ports)
LEGACY_NVS_PORT = 3000
DEFAULT_HTTP_PORT = 80
DEFAULT_RTSP_PORT = 554
RELAY_HOST = "127.0.0.1"

UPDATE_INTERVAL = timedelta(seconds=60)
