from dataclasses import dataclass

from bench.hass_client import CAMERA_HOST, CameraControl, HassClient

MODEL = "I91FW-SIM"
SERIAL = "SIM0000000001"
MAC = "00:00:5E:00:53:01"
ENTITY_KEYS = frozenset(
    {
        "motion", "person", "vehicle", "intrusion", "line", "tamper", "video_loss",
        "sub", "main", "floodlight", "light_mode",
        "person_detection", "vehicle_detection", "motion_detection", "siren_on_event",
        "siren", "speaker", "volume", "motion_sensitivity",
    }
)
# these start disabled, so they have no state
DISABLED_KEYS = frozenset({"intrusion", "line", "tamper", "video_loss"})


@dataclass(frozen=True)
class Entry:
    entry_id: str
    entity_ids: dict[str, str]


async def clear(hass: HassClient, camera: CameraControl) -> None:
    await hass.remove_entries()
    await camera.reset()
    await camera.wait_clients(0)


async def add_by_ip(hass: HassClient, camera: CameraControl) -> Entry:
    login = await camera.state()
    result = await hass.add_camera(CAMERA_HOST, login["user"], login["password"])
    assert result["type"] == "create_entry", result
    return await load_entry(hass, result["result"]["entry_id"], SERIAL)


async def add_by_search(hass: HassClient, camera: CameraControl) -> Entry:
    login = await camera.state()
    blank = {"host": "", "username": login["user"], "password": login["password"]}
    flow = await hass.start_flow()
    picked = await hass.configure_flow(flow["flow_id"], blank)
    assert picked["step_id"] == "pick_camera", picked
    choices = picked["data_schema"][0]["options"]
    assert choices == [[CAMERA_HOST, f"{MODEL} ({CAMERA_HOST})"]], choices
    form = await hass.configure_flow(flow["flow_id"], {"host": CAMERA_HOST})
    assert form["step_id"] == "user", form
    result = await hass.configure_flow(flow["flow_id"], blank | {"host": CAMERA_HOST})
    assert result["type"] == "create_entry", result
    return await load_entry(hass, result["result"]["entry_id"], SERIAL)


async def load_entry(hass: HassClient, entry_id: str, unique_id: str) -> Entry:
    prefix = f"{unique_id}_"
    entities = await hass.entities(entry_id)
    entry = Entry(
        entry_id,
        {
            key.removeprefix(prefix): entity_id
            for key, entity_id in entities.items()
            if key.startswith(prefix)
        },
    )
    for key, entity_id in entry.entity_ids.items():
        if key not in DISABLED_KEYS:
            await hass.wait_available(entity_id, timeout=30)
    return entry
