import asyncio
import functools
import logging
import math
import struct
from collections.abc import AsyncIterator
from typing import Any

from homeassistant.components.siren import (
    SirenEntity,
    SirenEntityDescription,
    SirenEntityFeature,
)
from homeassistant.components.siren.const import ATTR_DURATION, ATTR_TONE
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import lib
from .audio import SAMPLE_RATE, SAMPLE_WIDTH
from .const import DOMAIN
from .coordinator import SannceConfigEntry, SannceCoordinator
from .entity import SannceEntity

PARALLEL_UPDATES = 0

_LOGGER = logging.getLogger(__name__)

# tone name -> (alternating frequencies in Hz, seconds per segment)
_TONES: dict[str, tuple[tuple[float, float], float]] = {
    "alarm": ((800.0, 1000.0), 0.25),
    "chime": ((1046.0, 1318.0), 0.5),
}
_DEFAULT_TONE = "alarm"
_DEFAULT_DURATION = 10
_MAX_DURATION = 300
# the library gives up on talk start after 10 s; this only backstops it
_START_SECONDS = 15
_AMPLITUDE = 0.6
_CHUNK_BYTES = SAMPLE_RATE // 10 * SAMPLE_WIDTH

SIREN = SirenEntityDescription(key="siren", translation_key="siren")


@functools.cache
def _tone_cycle(tone: str) -> bytes:
    freqs, segment = _TONES[tone]
    peak = int(32767 * _AMPLITUDE)
    seg_samples = max(1, int(SAMPLE_RATE * segment))
    count = seg_samples * len(freqs)
    samples = (
        int(peak * math.sin(2 * math.pi * freqs[n // seg_samples] * n / SAMPLE_RATE))
        for n in range(count)
    )
    return struct.pack(f"<{count}h", *samples)


async def _tone_chunks(duration: int, tone: str) -> AsyncIterator[bytes]:
    cycle = _tone_cycle(tone)
    left = SAMPLE_RATE * duration * SAMPLE_WIDTH
    while left > 0:
        for start in range(0, min(left, len(cycle)), _CHUNK_BYTES):
            yield cycle[start : min(start + _CHUNK_BYTES, left)]
        left -= len(cycle)


async def _announce_start(
    chunks: AsyncIterator[bytes], started: asyncio.Future[None]
) -> AsyncIterator[bytes]:
    async for chunk in chunks:
        if not started.done():
            started.set_result(None)
        yield chunk


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SannceConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    if "talk" in coordinator.camera.caps:
        async_add_entities([SannceSiren(coordinator, SIREN)])


class SannceSiren(SannceEntity, SirenEntity):
    _attr_supported_features = (
        SirenEntityFeature.TURN_ON
        | SirenEntityFeature.TURN_OFF
        | SirenEntityFeature.DURATION
        | SirenEntityFeature.TONES
    )
    _attr_available_tones = list(_TONES)

    def __init__(
        self, coordinator: SannceCoordinator, description: SirenEntityDescription
    ) -> None:
        super().__init__(coordinator, description)
        self._attr_is_on = False
        self._task: asyncio.Task[None] | None = None

    async def async_turn_on(self, **kwargs: Any) -> None:
        duration = min(kwargs.get(ATTR_DURATION) or _DEFAULT_DURATION, _MAX_DURATION)
        tone = kwargs.get(ATTR_TONE) or _DEFAULT_TONE
        started: asyncio.Future[None] = self.hass.loop.create_future()
        self._task = task = self.coordinator.config_entry.async_create_background_task(
            self.hass, self._sound(duration, tone, started), "sannce siren"
        )
        task.add_done_callback(self._finished)
        try:
            async with asyncio.timeout(_START_SECONDS):
                await started
        except (lib.SannceError, TimeoutError) as err:
            await self.coordinator.audio.stop()
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="siren_failed",
                translation_placeholders={
                    "entity_id": self.entity_id,
                    "error": str(err) or f"no answer in {_START_SECONDS} s",
                },
            ) from err
        self._attr_is_on = not task.done()
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        if self._task is not None and not self._task.done():
            await self.coordinator.audio.stop()
        self._attr_is_on = False
        self.async_write_ha_state()

    async def async_will_remove_from_hass(self) -> None:
        if self._task is not None and not self._task.done():
            self._task = None
            await self.coordinator.audio.stop()

    async def _sound(
        self, duration: int, tone: str, started: asyncio.Future[None]
    ) -> None:
        chunks = _announce_start(_tone_chunks(duration, tone), started)
        try:
            await self.coordinator.audio.play(chunks)
        except Exception as err:
            if started.done():
                raise
            started.set_exception(err)
        finally:
            # stopped or superseded before the camera took the tone
            if not started.done():
                started.set_result(None)

    def _finished(self, task: asyncio.Task[None]) -> None:
        if task is not self._task:
            return
        if not task.cancelled() and (err := task.exception()):
            _LOGGER.error("siren playback failed: %s", err)
        self._attr_is_on = False
        self.async_write_ha_state()
