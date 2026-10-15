import json
from pathlib import Path

import pytest

import custom_components.sannce as integration
from custom_components.sannce.binary_sensor import EVENT_SENSORS
from custom_components.sannce.camera import CAMERAS
from custom_components.sannce.const import PLATFORMS
from custom_components.sannce.light import FLOODLIGHT
from custom_components.sannce.media_player import SPEAKER
from custom_components.sannce.number import NUMBERS
from custom_components.sannce.select import LIGHT_MODE
from custom_components.sannce.siren import SIREN
from custom_components.sannce.switch import SWITCHES

STRINGS = json.loads((Path(integration.__file__).parent / "strings.json").read_text())
DESCRIPTIONS = {
    "binary_sensor": EVENT_SENSORS,
    "camera": CAMERAS,
    "light": (FLOODLIGHT,),
    "media_player": (SPEAKER,),
    "number": NUMBERS,
    "select": (LIGHT_MODE,),
    "siren": (SIREN,),
    "switch": SWITCHES,
}


def test_every_platform_is_listed() -> None:
    assert set(DESCRIPTIONS) == {platform.value for platform in PLATFORMS}


@pytest.mark.parametrize("platform", DESCRIPTIONS)
def test_entity_strings_match_the_descriptions(platform: str) -> None:
    descriptions = DESCRIPTIONS[platform]
    keys = {d.translation_key for d in descriptions if d.translation_key}
    entities = STRINGS["entity"][platform]

    assert set(entities) == keys
    assert all(entities[key]["name"] for key in keys)
    assert all(d.device_class for d in descriptions if not d.translation_key)


@pytest.mark.parametrize("step", STRINGS["config"]["step"])
def test_flow_step_strings_are_complete(step: str) -> None:
    strings = STRINGS["config"]["step"][step]

    assert strings["title"]
    assert strings["description"]
    assert set(strings["data_description"]) == set(strings["data"])
    assert all(strings["data"].values())
    assert all(strings["data_description"].values())
