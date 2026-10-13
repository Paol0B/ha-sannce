import asyncio
import logging
from collections.abc import AsyncIterable, AsyncIterator
from contextlib import suppress
from typing import TYPE_CHECKING

from homeassistant.components import media_source
from homeassistant.components.media_player.browse_media import (
    async_process_play_media_url,
)
from homeassistant.core import HomeAssistant

if TYPE_CHECKING:
    from .coordinator import SannceCoordinator

_LOGGER = logging.getLogger(__name__)

SAMPLE_RATE = 8000
SAMPLE_WIDTH = 2

_READ_SIZE = 8192


async def play_media_to_camera(
    hass: HomeAssistant, coordinator: "SannceCoordinator", media: str
) -> None:
    media_id = await _resolve(hass, media)
    await coordinator.audio.play(_ffmpeg_pcm(hass, media_id))


async def _resolve(hass: HomeAssistant, media: str) -> str:
    if media_source.is_media_source_id(media):
        resolved = await media_source.async_resolve_media(hass, media, None)
        media = resolved.url
    return async_process_play_media_url(hass, media)


async def _ffmpeg_pcm(hass: HomeAssistant, media_id: str) -> AsyncIterator[bytes]:
    # lazy import: haffmpeg is a HA core dependency, absent from the unit test env
    from homeassistant.components import ffmpeg

    manager = ffmpeg.get_ffmpeg_manager(hass)
    proc = await asyncio.create_subprocess_exec(
        manager.binary,
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
    try:
        while chunk := await proc.stdout.read(_READ_SIZE):
            yield chunk
    finally:
        if proc.returncode is None:
            with suppress(ProcessLookupError):
                proc.kill()
        _, stderr = await proc.communicate()
        if proc.returncode:
            _LOGGER.error(
                "ffmpeg failed on %s: %s", media_id, stderr.decode(errors="replace")
            )


async def iter_chunks(data: bytes, size: int) -> AsyncIterator[bytes]:
    for start in range(0, len(data), size):
        yield data[start : start + size]


class AudioPlayer:
    """Feed one sound at a time to the camera speaker; a new play supersedes."""

    def __init__(self, coordinator: "SannceCoordinator") -> None:
        self._hass = coordinator.hass
        self._entry = coordinator.config_entry
        self._camera = coordinator.camera
        self._task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()

    @property
    def playing(self) -> bool:
        task = self._task
        return task is not None and not task.done()

    async def play(self, pcm: AsyncIterable[bytes]) -> None:
        async with self._lock:
            await self._cancel()
            task = self._entry.async_create_background_task(
                self._hass, self._camera.play_audio(pcm), "sannce play audio"
            )
            self._task = task
        with suppress(asyncio.CancelledError):
            await task

    async def stop(self) -> None:
        async with self._lock:
            await self._cancel()

    async def _cancel(self) -> None:
        task = self._task
        self._task = None
        if task is None or task.done():
            return
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
