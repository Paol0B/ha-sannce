from homeassistant.const import Platform

DOMAIN = "sannce"

PLATFORMS: list[Platform] = []

CONF_NVS_PORT = "nvs_port"
CONF_HTTP_PORT = "http_port"
CONF_RTSP_PORT = "rtsp_port"

DEFAULT_USERNAME = "admin"
DEFAULT_NVS_PORT = 3000
DEFAULT_HTTP_PORT = 80
DEFAULT_RTSP_PORT = 554
