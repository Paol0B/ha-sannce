import json
from pathlib import Path

import pytest

import custom_components.sannce as integration
from custom_components.sannce.select import LIGHT_MODE

from .test_strings import DESCRIPTIONS

INTEGRATION_DIR = Path(integration.__file__).parent
ICONS = json.loads((INTEGRATION_DIR / "icons.json").read_text())["entity"]
# the speaker's entity class sets its device class, not its description
CLASS_DEVICE_CLASS = {"speaker"}


@pytest.mark.parametrize("platform", DESCRIPTIONS)
def test_icons_cover_entities_without_a_device_class(platform: str) -> None:
    keys = {
        description.translation_key
        for description in DESCRIPTIONS[platform]
        if description.translation_key
        and description.device_class is None
        and description.translation_key not in CLASS_DEVICE_CLASS
    }

    assert set(ICONS.get(platform, {})) == keys


def test_every_icon_is_a_material_design_icon() -> None:
    icons = [
        icon
        for entities in ICONS.values()
        for entity in entities.values()
        for icon in [entity["default"], *entity.get("state", {}).values()]
    ]

    assert len(icons) == 18
    assert all(icon.startswith("mdi:") for icon in icons)


def test_light_mode_has_an_icon_per_option() -> None:
    assert set(ICONS["select"]["light_mode"]["state"]) == set(LIGHT_MODE.options)


def test_no_icon_is_set_in_code() -> None:
    for path in INTEGRATION_DIR.glob("*.py"):
        text = path.read_text()
        assert "_attr_icon" not in text, path.name
        assert "icon=" not in text, path.name
