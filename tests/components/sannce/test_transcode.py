import asyncio
import logging
import socket
import struct
from collections.abc import AsyncIterator

import pytest
from homeassistant.core import HomeAssistant

from custom_components.sannce import transcode
from custom_components.sannce.transcode import TranscodeServer

from . import PASSWORD, USERNAME
from .conftest import FakeProcess, ffmpeg_running

OK = b"HTTP/1.0 200 OK\r\nContent-Type: video/mp2t\r\n\r\n"
NOT_FOUND = b"HTTP/1.0 404 Not Found\r\nContent-Length: 0\r\n\r\n"
BAD_GATEWAY = b"HTTP/1.0 502 Bad Gateway\r\nContent-Length: 0\r\n\r\n"


def source(stream: str) -> str:
    return f"rtsp://{USERNAME}:{PASSWORD}@127.0.0.1:18554/{stream}"


@pytest.fixture
async def server(
    hass: HomeAssistant, socket_enabled: None
) -> AsyncIterator[TranscodeServer]:
    server = TranscodeServer(hass, source)
    await server.start()
    yield server
    await server.close()


async def connect(
    server: TranscodeServer, head: bytes
) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
    reader, writer = await asyncio.open_connection("127.0.0.1", server.port)
    writer.write(head)
    await writer.drain()
    return reader, writer


async def request(server: TranscodeServer, head: bytes) -> bytes:
    reader, writer = await connect(server, head)
    try:
        return await reader.read()
    finally:
        writer.close()
        await writer.wait_closed()


async def test_url_names_the_stream_on_the_listening_port(
    server: TranscodeServer,
) -> None:
    assert server.port > 0
    assert server.url("sub") == f"http://127.0.0.1:{server.port}/sub"


async def test_stream_comes_as_mpegts_with_aac_audio(server: TranscodeServer) -> None:
    proc = FakeProcess(b"ts bytes", eof=True, exit_code=0)

    with ffmpeg_running(proc) as spawn:
        body = await request(server, b"GET /main HTTP/1.0\r\n\r\n")

    assert body == OK + b"ts bytes"
    args = spawn.call_args.args
    assert args[0] == "ffmpeg"
    assert args[args.index("-i") + 1] == source("main")
    assert args[args.index("-c:v") + 1] == "copy"
    assert args[args.index("-c:a") + 1] == "aac"
    assert args[args.index("-f") + 1] == "mpegts"


@pytest.mark.parametrize(
    "head",
    [
        b"GET /other HTTP/1.0\r\n\r\n",
        b"POST /main HTTP/1.0\r\n\r\n",
        b"GET\r\n\r\n",
    ],
    ids=["unknown stream", "not a GET", "no path"],
)
async def test_other_requests_are_not_found(
    server: TranscodeServer, head: bytes
) -> None:
    with ffmpeg_running(FakeProcess(b"", eof=True, exit_code=0)) as spawn:
        body = await request(server, head)

    assert body == NOT_FOUND
    spawn.assert_not_called()


async def test_incomplete_request_gets_no_answer(server: TranscodeServer) -> None:
    with ffmpeg_running(FakeProcess(b"", eof=True, exit_code=0)) as spawn:
        reader, writer = await connect(server, b"GET /main")
        writer.write_eof()
        body = await reader.read()
        writer.close()
        await writer.wait_closed()

    assert body == b""
    spawn.assert_not_called()


async def test_camera_failure_is_a_bad_gateway_with_a_redacted_log(
    server: TranscodeServer, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG, logger=transcode.__name__)
    error = f"{source('sub')}: Connection refused".encode()
    proc = FakeProcess(b"", eof=True, exit_code=1, stderr=error)

    with ffmpeg_running(proc):
        body = await request(server, b"GET /sub HTTP/1.0\r\n\r\n")

    assert body == BAD_GATEWAY
    assert "Connection refused" in caplog.text
    assert PASSWORD not in caplog.text


async def test_close_stops_a_running_ffmpeg(
    hass: HomeAssistant, socket_enabled: None
) -> None:
    server = TranscodeServer(hass, source)
    await server.start()
    proc = FakeProcess(b"ts", eof=False, exit_code=0)

    with ffmpeg_running(proc):
        reader, writer = await connect(server, b"GET /sub HTTP/1.0\r\n\r\n")
        assert await reader.readexactly(len(OK) + 2) == OK + b"ts"
        await server.close()
        rest = await reader.read()
        writer.close()
        await writer.wait_closed()

    assert proc.killed
    assert rest == b""


async def test_client_leaving_stops_ffmpeg(server: TranscodeServer) -> None:
    proc = FakeProcess(b"x" * 0x400000, eof=False, exit_code=0)

    with ffmpeg_running(proc):
        reader, writer = await connect(server, b"GET /main HTTP/1.0\r\n\r\n")
        assert await reader.readexactly(len(OK)) == OK
        # linger 0: close with a reset, as a client that crashed
        writer.get_extra_info("socket").setsockopt(
            socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0)
        )
        writer.close()
        async with asyncio.timeout(5):
            await proc.wait()

    assert proc.killed


async def test_close_twice_is_harmless(server: TranscodeServer) -> None:
    await server.close()
    await server.close()
