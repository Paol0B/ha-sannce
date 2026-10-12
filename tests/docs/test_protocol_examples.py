import json
import re
from pathlib import Path

import pytest

DOCS = Path(__file__).resolve().parents[2] / "docs"
EXAMPLES = DOCS / "protocol-examples.json"
PROTOCOL = DOCS / "protocol.md"

SECTIONS = {"framing", "login", "login_encrypted", "heartbeat", "events", "talk", "discovery", "http"}
DIRECTIONS = {"client_to_camera", "camera_to_client"}
TRANSPORTS = {"nvs_tcp", "nvs_udp", "http"}
STATUSES = {"static", "inferred", "verified"}
ID_PATTERN = re.compile(r"^[a-z0-9_]+$")
HEX_PATTERN = re.compile(r"^([0-9a-f]{2})+$")
EVIDENCE_PATTERN = re.compile(r"^(lib[A-Za-z0-9_]+\.so:.+@0x[0-9a-f]+|java:[^:]+:\d+)$")

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


@pytest.mark.parametrize("example_id", example_ids())
def test_example_is_referenced_in_doc(example_id):
    assert f"[example: {example_id}]" in PROTOCOL.read_text(encoding="utf-8")
