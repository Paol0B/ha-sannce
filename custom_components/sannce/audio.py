import asyncio
from collections.abc import AsyncGenerator, AsyncIterable, Awaitable
from contextlib import aclosing, suppress
from typing import TYPE_CHECKING

from homeassistant.components import media_source
from homeassistant.components.media_player.browse_media import (
    async_process_play_media_url,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from .const import DOMAIN

if TYPE_CHECKING:
    from .coordinator import SannceCoordinator

SAMPLE_RATE = 8000
SAMPLE_WIDTH = 2

_READ_SIZE = 8192
_STALL_SECONDS = 60
_ERROR_BYTES = 2048


async def play_media_to_camera(
    hass: HomeAssistant,
    coordinator: "SannceCoordinator",
    media: str,
    owner: object | None = None,
) -> None:
    media_id = await _resolve(hass, media)
    async with aclosing(_ffmpeg_pcm(hass, media_id)) as pcm:
        await coordinator.audio.play(pcm, owner)


async def _resolve(hass: HomeAssistant, media: str) -> str:
    if media_source.is_media_source_id(media):
        resolved = await media_source.async_resolve_media(hass, media, None)
        media = resolved.url
    return async_process_play_media_url(hass, media)


async def _ffmpeg_pcm(hass: HomeAssistant, media_id: str) -> AsyncGenerator[bytes]:
    # lazy import: haffmpeg is a HA core dependency, absent from the unit test env
    from homeassistant.components import ffmpeg

    manager = ffmpeg.get_ffmpeg_manager(hass)
    proc = await asyncio.create_subprocess_exec(
        manager.binary,
        "-nostdin",
        "-hide_banner",
        "-nostats",
        "-loglevel",
        "error",
        "-protocol_whitelist",
        "http,https,file,tcp,tls,crypto,pipe",
        "-i",
        media_id,
        "-ac",
        "1",
        "-ar",
        str(SAMPLE_RATE),
        "-f",
        "s16le",
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
        while chunk := await _bounded(proc.stdout.read(_READ_SIZE), media_id):
            yield chunk
        await _bounded(proc.wait(), media_id)
    finally:
        # still running: the play was closed early, cancelled or stalled
        if proc.returncode is None:
            with suppress(ProcessLookupError):
                proc.kill()
        # wait() returns only after stdout reaches EOF
        await proc.stdout.read()
        await proc.wait()
        stderr = await errors
    if code := proc.returncode:
        detail = stderr.decode(errors="replace").strip() or f"exit code {code}"
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="ffmpeg_failed",
            translation_placeholders={"media": media_id, "detail": detail},
        )


async def _bounded[T](step: Awaitable[T], media_id: str) -> T:
    try:
        return await asyncio.wait_for(step, _STALL_SECONDS)
    except TimeoutError:
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="ffmpeg_stalled",
            translation_placeholders={
                "seconds": str(_STALL_SECONDS),
                "media": media_id,
            },
        ) from None


async def _tail(stream: asyncio.StreamReader) -> bytes:
    tail = b""
    while chunk := await stream.read(_READ_SIZE):
        tail = (tail + chunk)[-_ERROR_BYTES:]
    return tail


async def _join(task: asyncio.Task[None]) -> None:
    try:
        await task
    except asyncio.CancelledError:
        # the task's own cancel is a normal stop; a cancel aimed at us must propagate
        if (current := asyncio.current_task()) and current.cancelling():
            raise


class AudioPlayer:
    """Feed one sound at a time to the camera speaker; a new play supersedes."""

    def __init__(self, coordinator: "SannceCoordinator") -> None:
        self._hass = coordinator.hass
        self._entry = coordinator.config_entry
        self._camera = coordinator.camera
        self._task: asyncio.Task[None] | None = None
        self._owner: object | None = None
        self._lock = asyncio.Lock()

    @property
    def playing(self) -> bool:
        task = self._task
        return task is not None and not task.done()

    async def play(
        self, pcm: AsyncIterable[bytes], owner: object | None = None
    ) -> None:
        async with self._lock:
            await self._cancel()
            task = self._entry.async_create_background_task(
                self._hass, self._camera.play_audio(pcm), "sannce play audio"
            )
            self._task = task
            self._owner = owner
        await _join(task)

    async def stop(self, owner: object | None = None) -> None:
        async with self._lock:
            if owner is None or owner is self._owner:
                await self._cancel()

    async def _cancel(self) -> None:
        task = self._task
        self._task = None
        if task is None or task.done():
            return
        task.cancel()
        await _join(task)
