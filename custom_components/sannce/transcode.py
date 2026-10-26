import asyncio
import logging
from collections.abc import Callable
from contextlib import suppress

from homeassistant.components.stream import redact_credentials
from homeassistant.core import HomeAssistant

from .const import RELAY_HOST

_LOGGER = logging.getLogger(__name__)

STREAMS = frozenset({"main", "sub"})
SAMPLE_RATE = 16000

_READ_SIZE = 0x10000
_ERROR_BYTES = 2048
_HEAD_END = b"\r\n\r\n"
_HEAD_SECONDS = 10
_CLOSE_SECONDS = 2
_OK = b"HTTP/1.0 200 OK\r\nContent-Type: video/mp2t\r\n\r\n"
_NOT_FOUND = b"HTTP/1.0 404 Not Found\r\nContent-Length: 0\r\n\r\n"
_BAD_GATEWAY = b"HTTP/1.0 502 Bad Gateway\r\nContent-Length: 0\r\n\r\n"


class TranscodeServer:
    """Serve each stream as MPEG-TS over HTTP, with the G.711 audio as AAC.

    The stream component keeps only AAC or MP3 audio, so HLS and the
    recordings made from it would have no sound.
    """

    def __init__(self, hass: HomeAssistant, source: Callable[[str], str]) -> None:
        self._hass = hass
        self._source = source
        self._server: asyncio.Server | None = None
        self._bound = 0
        self._connections: set[asyncio.Task[None]] = set()

    @property
    def port(self) -> int:
        return self._bound

    def url(self, stream: str) -> str:
        return f"http://{RELAY_HOST}:{self._bound}/{stream}"

    async def start(self) -> None:
        self._server = await asyncio.start_server(self._handle, RELAY_HOST, 0)
        self._bound = self._server.sockets[0].getsockname()[1]

    async def close(self) -> None:
        server, self._server = self._server, None
        if server is None:
            return
        server.close()
        tasks = list(self._connections)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        with suppress(TimeoutError):
            async with asyncio.timeout(_CLOSE_SECONDS):
                await server.wait_closed()

    async def _handle(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        task = asyncio.current_task()
        assert task is not None
        self._connections.add(task)
        task.add_done_callback(self._connections.discard)
        try:
            stream = await _requested_stream(reader)
            if stream is None:
                return
            if stream not in STREAMS:
                writer.write(_NOT_FOUND)
                return
            await self._serve(stream, writer)
        except ConnectionError as err:
            _LOGGER.debug("AAC stream client went away: %r", err)
        finally:
            await _shut(writer)

    async def _serve(self, stream: str, writer: asyncio.StreamWriter) -> None:
        # lazy import: haffmpeg is a HA core dependency, absent from the unit test env
        from homeassistant.components import ffmpeg

        manager = ffmpeg.get_ffmpeg_manager(self._hass)
        source = self._source(stream)
        proc = await asyncio.create_subprocess_exec(
            manager.binary,
            "-nostdin",
            "-hide_banner",
            "-nostats",
            "-loglevel",
            "error",
            "-rtsp_transport",
            "tcp",
            # end on a silent camera, so the stream worker sees the end and retries
            "-timeout",
            "5000000",
            "-i",
            source,
            "-map",
            "0:v:0",
            "-map",
            "0:a:0?",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-ar",
            str(SAMPLE_RATE),
            "-ac",
            "1",
            "-b:a",
            "32k",
            "-f",
            "mpegts",
            "pipe:1",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            close_fds=False,
        )
        assert proc.stdout is not None
        assert proc.stderr is not None
        # read stderr alongside stdout: a full stderr pipe would stall ffmpeg
        errors = asyncio.create_task(_tail(proc.stderr))
        try:
            # answer only once ffmpeg reads the camera, so a failure is a 502
            if not (chunk := await proc.stdout.read(_READ_SIZE)):
                writer.write(_BAD_GATEWAY)
                return
            writer.write(_OK)
            while chunk:
                writer.write(chunk)
                await writer.drain()
                chunk = await proc.stdout.read(_READ_SIZE)
        finally:
            # still running: the client left or the server is closing
            if proc.returncode is None:
                with suppress(ProcessLookupError):
                    proc.kill()
            # wait() returns only after stdout reaches EOF
            await proc.stdout.read()
            await proc.wait()
            stderr = (await errors).decode(errors="replace").strip()
            if stderr:
                # ffmpeg names its input, login included
                stderr = stderr.replace(source, redact_credentials(source))
                _LOGGER.debug("ffmpeg for the %s AAC stream: %s", stream, stderr)


async def _requested_stream(reader: asyncio.StreamReader) -> str | None:
    try:
        async with asyncio.timeout(_HEAD_SECONDS):
            head = await reader.readuntil(_HEAD_END)
    except (TimeoutError, asyncio.IncompleteReadError, asyncio.LimitOverrunError):
        return None
    words = head.split(b" ", 2)
    if len(words) < 3 or words[0] != b"GET":
        return ""
    return words[1].decode("latin-1").removeprefix("/")


async def _tail(stream: asyncio.StreamReader) -> bytes:
    tail = b""
    while chunk := await stream.read(_READ_SIZE):
        tail = (tail + chunk)[-_ERROR_BYTES:]
    return tail


async def _shut(writer: asyncio.StreamWriter) -> None:
    writer.close()
    try:
        async with asyncio.timeout(_CLOSE_SECONDS):
            await writer.wait_closed()
    except TimeoutError:
        writer.transport.abort()
    except OSError:
        pass
