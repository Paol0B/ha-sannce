import asyncio
from pathlib import Path
from typing import NoReturn

import aiohttp
import pytest
import pytest_asyncio
from pytest_asyncio import is_async_test

from bench.hass_client import TIMEOUT, BenchError, CameraControl, HassClient

from . import add_by_ip, clear

E2E_DIR = Path(__file__).parent
NOT_RUNNING = "bench is not running: scripts/bench.sh up"


def not_running(exc: BaseException) -> NoReturn:
    cause = str(exc)
    pytest.exit(f"{NOT_RUNNING} ({cause})" if cause else NOT_RUNNING, returncode=1)


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--bench",
        action="store_true",
        help="run the end-to-end suite against the running bench",
    )


def pytest_configure(config: pytest.Config) -> None:
    bench = config.getoption("--bench", default=False)
    if bench and config.pluginmanager.has_plugin("homeassistant"):
        raise pytest.UsageError("the end-to-end suite needs -p no:homeassistant")


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    e2e = [item for item in items if E2E_DIR in item.path.parents]
    if not config.getoption("--bench", default=False):
        skip = pytest.mark.skip(reason="needs --bench and a running bench")
        for item in e2e:
            item.add_marker(skip)
        return
    # one event loop for the run: the session fixtures hold its connections
    session_loop = pytest.mark.asyncio(loop_scope="session")
    for item in e2e:
        if is_async_test(item):
            item.add_marker(session_loop, append=False)
    # the log check reads what every other test left behind
    items.sort(key=lambda item: item.path == E2E_DIR / "test_log.py")


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def http():
    async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
        yield session


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def camera(http):
    control = CameraControl(http)
    try:
        await asyncio.wait_for(control.state(), 3)
    except (aiohttp.ClientError, TimeoutError, BenchError) as exc:
        not_running(exc)
    return control


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def hass(http, camera):
    client = HassClient(http)
    try:
        await client.sign_in(timeout=5)
    except (aiohttp.ClientError, BenchError) as exc:
        not_running(exc)
    yield client
    await client.close()


@pytest_asyncio.fixture(scope="module", loop_scope="session")
async def entry(hass, camera):
    await clear(hass, camera)
    try:
        yield await add_by_ip(hass, camera)
    finally:
        await clear(hass, camera)
