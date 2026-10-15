import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

STORE = Path("/config/.storage/http")
STORE_VERSION = 2


def seed():
    return {
        "version": STORE_VERSION,
        "minor_version": 2,
        "key": "http",
        "data": {
            "stable": {
                "server_port": 8123,
                "cors_allowed_origins": ["https://cast.home-assistant.io"],
                "login_attempts_threshold": -1,
                "ip_ban_enabled": True,
                "ssl_profile": "modern",
                "use_x_frame_options": True,
                "created_at": datetime.now(UTC).isoformat(),
                "error": None,
                "error_message": None,
            },
            "pending": None,
            "yaml_migration_done": True,
        },
    }


def apply(doc, host):
    if doc["version"] != STORE_VERSION:
        sys.exit(f"unsupported http store version: {doc['version']}")
    data = doc["data"]
    data["pending"] = None
    if host:
        data["stable"]["server_host"] = [host]
    else:
        data["stable"].pop("server_host", None)
    return doc


def write(doc):
    tmp = STORE.with_name("http.bench")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as out:
        json.dump(doc, out, indent=4)
    os.replace(tmp, STORE)


def main():
    host = os.environ.get("BENCH_SERVER_HOST", "")
    if STORE.exists():
        old = json.loads(STORE.read_text())
    elif host:
        STORE.parent.mkdir(exist_ok=True)
        old = None
    else:
        return
    new = apply(json.loads(json.dumps(old)) if old else seed(), host)
    if new != old:
        write(new)


if __name__ == "__main__":
    main()
