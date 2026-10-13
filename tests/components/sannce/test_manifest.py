import json
import re
from pathlib import Path

import pytest

import custom_components.sannce as integration
from custom_components.sannce import lib
from custom_components.sannce.const import DOMAIN

INTEGRATION_DIR = Path(integration.__file__).parent
ROOT = INTEGRATION_DIR.parents[1]
MANIFEST = json.loads((INTEGRATION_DIR / "manifest.json").read_text())
HACS = json.loads((ROOT / "hacs.json").read_text())
HACS_KEYS = {
    "content_in_root",
    "country",
    "filename",
    "hacs",
    "hide_default_branch",
    "homeassistant",
    "name",
    "persistent_directory",
    "zip_release",
}
VENDORED = "custom_components.sannce.sannce_aio"


def test_manifest_describes_a_local_push_device() -> None:
    assert INTEGRATION_DIR.name == MANIFEST["domain"] == DOMAIN
    assert MANIFEST["name"] == "SANNCE"
    assert MANIFEST["config_flow"] is True
    assert MANIFEST["integration_type"] == "device"
    assert MANIFEST["iot_class"] == "local_push"


def test_manifest_requires_nothing_while_the_library_is_vendored() -> None:
    assert MANIFEST["requirements"] == []


def test_manifest_depends_on_the_audio_components() -> None:
    assert {"ffmpeg", "media_source"} <= set(MANIFEST["dependencies"])


@pytest.mark.parametrize("key", ["documentation", "issue_tracker"])
def test_manifest_links_are_https_urls(key: str) -> None:
    assert re.fullmatch(r"https://\S+", MANIFEST[key])


def test_manifest_version_has_three_numbers() -> None:
    assert re.fullmatch(r"\d+\.\d+\.\d+", MANIFEST["version"])


def test_manifest_keys_follow_the_hassfest_order() -> None:
    rest = sorted(set(MANIFEST) - {"domain", "name"})

    assert list(MANIFEST) == ["domain", "name", *rest]


def test_hacs_json_has_a_name_and_only_keys_hacs_reads() -> None:
    assert HACS["name"]
    assert set(HACS) - HACS_KEYS == set()


def test_hacs_minimum_home_assistant_is_a_calendar_version() -> None:
    assert re.fullmatch(r"\d{4}\.\d{1,2}\.\d+", HACS["homeassistant"])


def test_root_readme_exists_for_hacs_to_show() -> None:
    assert (ROOT / "README.md").read_text().strip()


def test_lib_exports_come_from_the_vendored_library() -> None:
    modules = {
        name: getattr(lib, name).__module__
        for name in lib.__all__
        if name != "create_camera"
    }

    foreign = {k: v for k, v in modules.items() if not v.startswith(f"{VENDORED}.")}
    assert foreign == {}
