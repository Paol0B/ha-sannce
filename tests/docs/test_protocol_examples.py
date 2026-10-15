import json
import re
from pathlib import Path

import pytest

DOCS = Path(__file__).resolve().parents[2] / "docs"
EXAMPLES = DOCS / "protocol-examples.json"
PROTOCOL = DOCS / "protocol.md"

SECTIONS = {"framing", "login", "login_encrypted", "heartbeat", "events", "talk", "discovery", "http"}
DIRECTIONS = {"client_to_camera", "camera_to_client"}
TRANSPORTS = {"nvs_tcp", "nvs_udp", "nvs_ws", "http"}
STATUSES = {"static", "inferred", "verified"}
ID_PATTERN = re.compile(r"^[a-z0-9_]+$")
HEX_PATTERN = re.compile(r"^([0-9a-f]{2})+$")
EVIDENCE_PATTERN = re.compile(
    r"^(lib[A-Za-z0-9_]+\.so:.+@0x[0-9a-f]+|java:[^:]+:\d+|web:/\S+)$"
)

REQUIRED_IDS: set[str] = {
    "framing_parameter_get_request",
    "framing_two_messages_one_read",
    "logon_request",
    "logon_reply_success",
    "logon_request_password_with_tab",
    "logoff_request",
    "heartbeat_request",
    "event_motion_start",
    "event_motion_stop",
    "event_smart_person",
    "event_smart_vehicle",
    "event_vca_intrusion",
    "event_video_cover",
    "talk_start_request",
    "talk_refused_busy",
    "talk_audio_frame_g711a",
    "talk_stop_request",
    "discovery_seek_request",
    "discovery_reply",
    "http_device_info_reply",
    "http_capabilities_reply",
    "http_whitelight_get_reply",
    "http_whitelight_set_manual_on",
    "http_light_mode_set_smart",
    "http_motion_detection_get_reply",
}


def load_examples() -> list[dict]:
    return json.loads(EXAMPLES.read_text(encoding="utf-8"))["examples"]


def example_ids() -> list[str]:
    return [ex["id"] for ex in load_examples()]


def test_ids_are_unique():
    ids = example_ids()
    assert len(ids) == len(set(ids))


def test_required_examples_exist():
    assert REQUIRED_IDS <= set(example_ids()), REQUIRED_IDS - set(example_ids())


@pytest.mark.parametrize("example", load_examples(), ids=lambda ex: ex["id"])
def test_example_shape(example):
    assert ID_PATTERN.match(example["id"])
    assert example["section"] in SECTIONS
    assert example["direction"] in DIRECTIONS
    assert example["transport"] in TRANSPORTS
    assert example["status"] in STATUSES
    has_hex = bool(example.get("hex"))
    has_text = bool(example.get("text"))
    assert has_hex != has_text, "exactly one of hex or text"
    if has_hex:
        assert HEX_PATTERN.match(example["hex"])
    assert isinstance(example.get("fields", {}), dict)
    assert example["evidence"], "evidence must not be empty"
    for item in example["evidence"]:
        assert EVIDENCE_PATTERN.match(item), item
    assert bool(example.get("source")) == (example["status"] == "verified")


@pytest.mark.parametrize("example_id", example_ids())
def test_example_is_referenced_in_doc(example_id):
    assert f"[example: {example_id}]" in PROTOCOL.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "example",
    [
        ex
        for ex in load_examples()
        if ex["transport"] == "http"
        and (
            "/channels/" in ex.get("text", "")
            or "/channels/" in ex.get("fields", {}).get("path", "")
        )
    ],
    ids=lambda ex: ex["id"],
)
def test_http_channel_examples_state_channel(example):
    assert type(example.get("fields", {}).get("channel")) is int


CHECKLIST = DOCS / "hardware-checklist.md"


@pytest.mark.parametrize(
    "example_id",
    [ex["id"] for ex in load_examples() if ex["status"] != "verified"],
)
def test_unverified_example_has_hardware_check(example_id):
    assert f"`{example_id}`" in CHECKLIST.read_text(encoding="utf-8")


def open_questions() -> list[str]:
    text = PROTOCOL.read_text(encoding="utf-8")
    section = text.split("\n## Open questions\n", 1)[1].split("\n## ", 1)[0]
    return [line[2:] for line in section.splitlines() if line.startswith("- ")]


def test_open_questions_have_hardware_checks():
    questions = open_questions()
    checklist = CHECKLIST.read_text(encoding="utf-8")
    assert questions
    assert not [q for q in questions if q not in checklist]


def test_status_summary_total_row_matches_data():
    statuses = [ex["status"] for ex in load_examples()]
    counts = " | ".join(
        str(n)
        for n in (
            statuses.count("static"),
            statuses.count("inferred"),
            statuses.count("verified"),
            len(open_questions()),
        )
    )
    row = f"| total | {counts} |"
    assert row in PROTOCOL.read_text(encoding="utf-8")


def test_status_summary_rows_match_data():
    text = PROTOCOL.read_text(encoding="utf-8")
    rows = re.findall(r"^\| (\w+) \| (\d+) \| (\d+) \| (\d+) \| (\d+) \|$", text, re.MULTILINE)
    areas = {row[0]: tuple(int(n) for n in row[1:]) for row in rows}
    assert set(areas) == SECTIONS | {"transport", "total"}
    examples = load_examples()
    questions = open_questions()
    for area, counts in areas.items():
        if area == "total":
            continue
        statuses = [ex["status"] for ex in examples if ex["section"] == area]
        expected = (
            statuses.count("static"),
            statuses.count("inferred"),
            statuses.count("verified"),
            len([q for q in questions if q.startswith(f"{area}: ")]),
        )
        assert counts == expected, area
