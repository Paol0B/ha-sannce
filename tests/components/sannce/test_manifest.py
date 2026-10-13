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
# IEEE MA-L assignments to Tiandy Technologies (standards-oui.ieee.org/oui/oui.txt)
TIANDY_PREFIXES = ("3CDA6D", "BC516C", "E4E66C")
DOC_SECTIONS = {
    "Supported devices",
    "Data updates",
    "Use cases",
    "Automation examples",
    "Known limits",
    "Troubleshooting",
    "Remove",
}


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


def test_manifest_depends_on_stream_for_camera_snapshots() -> None:
    assert "stream" in MANIFEST["dependencies"]


def test_manifest_discovers_tiandy_cameras_and_known_devices() -> None:
    assert MANIFEST["dhcp"] == [
        {"registered_devices": True},
        *({"macaddress": f"{prefix}*"} for prefix in TIANDY_PREFIXES),
    ]


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


def test_readme_has_the_sections_the_quality_scale_asks_for() -> None:
    readme = (ROOT / "README.md").read_text()
    headings = {line[3:] for line in readme.splitlines() if line.startswith("## ")}

    assert DOC_SECTIONS <= headings


@pytest.mark.parametrize("doc", ["README.md", "docs/hardware-checklist.md"])
def test_docs_list_the_dhcp_prefixes(doc: str) -> None:
    text = (ROOT / doc).read_text()

    for prefix in TIANDY_PREFIXES:
        assert f"`{prefix[:2]}:{prefix[2:4]}:{prefix[4:]}`" in text


def test_lib_exports_come_from_the_vendored_library() -> None:
    modules = {
        name: getattr(lib, name).__module__
        for name in lib.__all__
        if name != "create_camera"
    }

    foreign = {k: v for k, v in modules.items() if not v.startswith(f"{VENDORED}.")}
    assert foreign == {}
