import argparse
import asyncio
import itertools
import sys
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import aiohttp

HASS_URL = "http://127.0.0.1:8123"
CAMERA_HOST = "172.31.250.10"
CONTROL_URL = f"http://{CAMERA_HOST}:8099"
OWNER = "dev"
OWNER_PASSWORD = "sannce-bench"
DOMAIN = "sannce"
EVENT_KINDS = ("motion", "vehicle", "intrusion", "line", "tamper", "video_loss")
START_TIMEOUT = 300
POLL_SECONDS = 0.1
TIMEOUT = aiohttp.ClientTimeout(total=60, connect=5)

_CLIENT_ID = f"{HASS_URL}/"
_REDIRECT_URI = f"{HASS_URL}/?auth_callback=1"


class BenchError(Exception):
    pass


class CommandError(BenchError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


async def wait_for[T](
    probe: Callable[[], Awaitable[T]],
    accept: Callable[[T], bool],
    timeout: float,
    what: str,
) -> T:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not accept(value := await probe()):
        if loop.time() >= deadline:
            raise BenchError(f"{what}: still {value!r} after {timeout:g} s")
        await asyncio.sleep(POLL_SECONDS)
    return value


class HassClient:
    def __init__(self, session: aiohttp.ClientSession, url: str = HASS_URL) -> None:
        self._session = session
        self._url = url
        self._token = ""
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._ids = itertools.count(1)
        self._ws_lock = asyncio.Lock()

    async def close(self) -> None:
        if self._ws is not None:
            await self._ws.close()
            self._ws = None

    async def sign_in(self, timeout: float = START_TIMEOUT) -> None:
        await wait_for(
            self._try_sign_in,
            lambda problem: problem is None,
            timeout,
            f"signing in to {self._url} as {OWNER}",
        )
        await self._finish_onboarding()
        await wait_for(
            self._config_state,
            lambda state: state == "RUNNING",
            timeout,
            f"waiting for {self._url} to start",
        )

    async def request(self, method: str, path: str, payload: Any = None) -> Any:
        async with self._session.request(
            method, self._url + path, json=payload, headers=self._headers()
        ) as response:
            await _check(response)
            return await response.json(content_type=None)

    async def fetch(self, path: str) -> bytes | None:
        async with self._session.get(
            self._url + path, headers=self._headers()
        ) as response:
            return await response.read() if response.status == 200 else None

    async def text(self, path: str) -> str:
        async with self._session.get(
            self._url + path, headers=self._headers()
        ) as response:
            await _check(response)
            return await response.text()

    async def command(self, message: dict[str, Any]) -> Any:
        async with self._ws_lock:
            message_id = next(self._ids)
            ws = await self._send({"id": message_id, **message})
            try:
                reply = await _result(ws, message_id)
            except aiohttp.WSMessageTypeError:
                # no resend: the command may have run, and a service must not run twice
                await ws.close()
                raise BenchError(
                    f"the websocket closed before the {message['type']} reply"
                ) from None
        if not reply["success"]:
            raise CommandError(reply["error"]["code"], reply["error"]["message"])
        return reply["result"]

    async def call(self, domain: str, service: str, entity_id: str, **data: Any) -> Any:
        return await self.command(
            {
                "type": "call_service",
                "domain": domain,
                "service": service,
                "service_data": data,
                "target": {"entity_id": entity_id},
            }
        )

    async def state(self, entity_id: str) -> str | None:
        async with self._session.get(
            f"{self._url}/api/states/{entity_id}", headers=self._headers()
        ) as response:
            if response.status == 404:
                return None
            await _check(response)
            return (await response.json())["state"]

    async def wait_state(self, entity_id: str, state: str, timeout: float) -> None:
        await wait_for(
            lambda: self.state(entity_id),
            lambda seen: seen == state,
            timeout,
            f"waiting for {entity_id} to be {state}",
        )

    async def wait_available(self, entity_id: str, timeout: float) -> None:
        await wait_for(
            lambda: self.state(entity_id),
            lambda seen: seen not in (None, "unavailable"),
            timeout,
            f"waiting for {entity_id} to be available",
        )

    async def entries(self) -> list[dict[str, Any]]:
        return await self.request(
            "GET", f"/api/config/config_entries/entry?domain={DOMAIN}"
        )

    async def remove_entry(self, entry_id: str) -> None:
        await self.request("DELETE", f"/api/config/config_entries/entry/{entry_id}")

    async def remove_entries(self) -> None:
        for entry in await self.entries():
            await self.remove_entry(entry["entry_id"])

    async def reload_entry(self, entry_id: str) -> None:
        await self.request(
            "POST", f"/api/config/config_entries/entry/{entry_id}/reload"
        )

    async def start_flow(self, entry_id: str | None = None) -> dict[str, Any]:
        # an entry id makes it a reconfigure flow for that entry
        payload = {"handler": DOMAIN} | ({"entry_id": entry_id} if entry_id else {})
        return await self.request("POST", "/api/config/config_entries/flow", payload)

    async def configure_flow(
        self, flow_id: str, data: dict[str, Any]
    ) -> dict[str, Any]:
        return await self.request(
            "POST", f"/api/config/config_entries/flow/{flow_id}", data
        )

    async def add_camera(
        self, host: str, username: str, password: str
    ) -> dict[str, Any]:
        flow = await self.start_flow()
        login = {"host": host, "username": username, "password": password}
        return await self.configure_flow(flow["flow_id"], login)

    async def flows(self) -> list[dict[str, Any]]:
        return await self.command({"type": "config_entries/flow/progress"})

    async def entities(self, entry_id: str) -> dict[str, str]:
        registry = await self.command({"type": "config/entity_registry/list"})
        return {
            item["unique_id"]: item["entity_id"]
            for item in registry
            if item["config_entry_id"] == entry_id
        }

    async def enable_entity(self, entity_id: str) -> None:
        await self.command(
            {
                "type": "config/entity_registry/update",
                "entity_id": entity_id,
                "disabled_by": None,
            }
        )

    async def devices(self, entry_id: str) -> list[dict[str, Any]]:
        registry = await self.command({"type": "config/device_registry/list"})
        return [device for device in registry if device["config_entry_id"] == entry_id]

    async def stream_url(self, entity_id: str) -> str:
        reply = await self.command({"type": "camera/stream", "entity_id": entity_id})
        return reply["url"]

    async def _try_sign_in(self) -> str | None:
        # 404s and refused connections mean Home Assistant is still starting
        try:
            async with self._session.get(f"{self._url}/auth/providers") as response:
                status = response.status
                body = await response.json(content_type=None) if status == 400 else {}
            if status == 400 and body.get("code") == "onboarding_required":
                await self._create_owner()
                return None
            if status != 200:
                return f"HTTP {status} from /auth/providers"
            return None if await self._log_in() else "login refused"
        except (aiohttp.ClientError, TimeoutError, BenchError) as exc:
            return _cause(exc)

    async def _create_owner(self) -> None:
        reply = await self.request(
            "POST",
            "/api/onboarding/users",
            {
                "client_id": _CLIENT_ID,
                "name": OWNER,
                "username": OWNER,
                "password": OWNER_PASSWORD,
                "language": "en",
            },
        )
        await self._take_token(reply["auth_code"])

    async def _log_in(self) -> bool:
        flow = await self.request(
            "POST",
            "/auth/login_flow",
            {
                "client_id": _CLIENT_ID,
                "handler": ["homeassistant", None],
                "redirect_uri": _REDIRECT_URI,
            },
        )
        result = await self.request(
            "POST",
            f"/auth/login_flow/{flow['flow_id']}",
            {"client_id": _CLIENT_ID, "username": OWNER, "password": OWNER_PASSWORD},
        )
        if result.get("type") != "create_entry":
            return False
        await self._take_token(result["result"])
        return True

    async def _take_token(self, code: str) -> None:
        form = {
            "grant_type": "authorization_code",
            "code": code,
            "client_id": _CLIENT_ID,
        }
        async with self._session.post(f"{self._url}/auth/token", data=form) as response:
            await _check(response)
            self._token = (await response.json())["access_token"]

    async def _finish_onboarding(self) -> None:
        async with self._session.get(f"{self._url}/api/onboarding") as response:
            if response.status == 404:
                return
            await _check(response)
            done = {step["step"] for step in await response.json() if step["done"]}
        steps = (
            ("core_config", None),
            ("analytics", None),
            ("integration", {"client_id": _CLIENT_ID, "redirect_uri": _REDIRECT_URI}),
        )
        for step, payload in steps:
            if step not in done:
                await self.request("POST", f"/api/onboarding/{step}", payload)

    async def _config_state(self) -> str:
        return (await self.request("GET", "/api/config"))["state"]

    async def _send(self, frame: dict[str, Any]) -> aiohttp.ClientWebSocketResponse:
        ws = await self._websocket()
        try:
            await ws.send_json(frame)
        except aiohttp.ClientConnectionResetError:
            # the socket died while idle and nothing was sent, so send again
            await ws.close()
            ws = await self._websocket()
            await ws.send_json(frame)
        return ws

    async def _websocket(self) -> aiohttp.ClientWebSocketResponse:
        if self._ws is None or self._ws.closed:
            # an idle socket never answers Home Assistant's 55 s ping: ping sooner
            ws = await self._session.ws_connect(
                self._url + "/api/websocket", heartbeat=30
            )
            await ws.receive_json(timeout=TIMEOUT.total)
            await ws.send_json({"type": "auth", "access_token": self._token})
            reply = await ws.receive_json(timeout=TIMEOUT.total)
            if reply.get("type") != "auth_ok":
                await ws.close()
                raise BenchError(f"websocket login failed: {reply}")
            self._ws = ws
        return self._ws

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token}"} if self._token else {}


class CameraControl:
    def __init__(self, session: aiohttp.ClientSession, url: str = CONTROL_URL) -> None:
        self._session = session
        self._url = url

    async def state(self) -> dict[str, Any]:
        return await self._request("GET", "/state")

    async def event(self, kind: str, active: bool) -> None:
        await self._request("POST", "/event", {"kind": kind, "active": active})

    async def settings(self, **changes: Any) -> None:
        await self._request("POST", "/settings", changes)

    async def set_password(self, password: str) -> None:
        await self._request("POST", "/password", {"password": password})

    async def drop(self, seconds: float) -> None:
        await self._request("POST", "/drop", {"seconds": seconds})

    async def talk_busy(self, busy: bool) -> None:
        await self._request("POST", "/talk-busy", {"busy": busy})

    async def reset(self) -> None:
        await self._request("POST", "/reset")

    async def audio(self) -> bytes:
        async with self._session.get(f"{self._url}/audio.wav") as response:
            await _check(response)
            return await response.read()

    async def wait_ready(self, timeout: float) -> dict[str, Any]:
        return await wait_for(
            self._try_state, bool, timeout, f"waiting for {self._url}"
        )

    async def wait_clients(self, count: int, timeout: float = 10) -> None:
        await wait_for(
            self.state,
            lambda state: state["clients"] == count,
            timeout,
            f"waiting for {count} camera sessions",
        )

    async def wait_quiet(self, timeout: float = 10) -> None:
        await wait_for(
            self.state,
            lambda state: not state["talking"],
            timeout,
            "waiting for the talk session to end",
        )

    async def _try_state(self) -> dict[str, Any] | None:
        try:
            return await self.state()
        except (aiohttp.ClientError, TimeoutError):
            return None

    async def _request(self, method: str, path: str, payload: Any = None) -> Any:
        async with self._session.request(
            method, self._url + path, json=payload
        ) as response:
            await _check(response)
            return None if response.status == 204 else await response.json()


async def _result(
    ws: aiohttp.ClientWebSocketResponse, message_id: int
) -> dict[str, Any]:
    while True:
        reply = await ws.receive_json(timeout=TIMEOUT.total)
        if reply.get("id") == message_id and reply.get("type") == "result":
            return reply


async def _check(response: aiohttp.ClientResponse) -> None:
    if response.status >= 400:
        detail = (await response.text()).strip()
        raise BenchError(
            f"{response.method} {response.url.path}: HTTP {response.status} {detail}"
        )


def _cause(exc: BaseException) -> str:
    return str(exc) or type(exc).__name__


async def _setup(session: aiohttp.ClientSession, args: argparse.Namespace) -> None:
    hass = HassClient(session)
    try:
        await hass.sign_in()
        login = await CameraControl(session).wait_ready(START_TIMEOUT)
        print(f"Home Assistant: {HASS_URL}")
        print(f"login: {OWNER} / {OWNER_PASSWORD}")
        print(f"camera {CAMERA_HOST}: {await _add_camera(hass, login)}")
    finally:
        await hass.close()


async def _add_camera(hass: HassClient, login: dict[str, Any]) -> str:
    result = await hass.add_camera(CAMERA_HOST, login["user"], login["password"])
    if result["type"] == "abort" and result["reason"] == "already_configured":
        return "already added"
    if result["type"] != "create_entry":
        problem = result.get("errors") or result.get("reason")
        raise BenchError(f"adding camera {CAMERA_HOST} failed: {problem}")
    entry = result["result"]
    entities = await hass.entities(entry["entry_id"])
    return f"added, {entry['state']}, {len(entities)} entities"


async def _event(session: aiohttp.ClientSession, args: argparse.Namespace) -> None:
    await CameraControl(session).event(args.kind, args.state == "on")


async def _audio(session: aiohttp.ClientSession, args: argparse.Namespace) -> None:
    args.file.write_bytes(await CameraControl(session).audio())


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hass_client.py", description="drive the bench for scripts/bench.sh"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    setup = commands.add_parser(
        "setup", help="onboard Home Assistant and add the simulated camera"
    )
    setup.set_defaults(run=_setup)
    event = commands.add_parser("event", help="push a camera event")
    event.add_argument("kind", choices=EVENT_KINDS)
    event.add_argument("state", nargs="?", choices=("on", "off"), default="on")
    event.set_defaults(run=_event)
    audio = commands.add_parser("audio", help="save the last talk session as WAV")
    audio.add_argument("file", type=Path)
    audio.set_defaults(run=_audio)
    return parser


async def _run(args: argparse.Namespace) -> None:
    async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
        await args.run(session, args)


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        asyncio.run(_run(args))
    except (BenchError, aiohttp.ClientError, TimeoutError, OSError) as exc:
        print(f"error: {_cause(exc)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
