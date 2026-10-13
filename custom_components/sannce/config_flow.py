from homeassistant.config_entries import ConfigFlow

from .const import DOMAIN


class SannceConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1
