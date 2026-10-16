import asyncio
import functools
import logging
import math
import struct
from collections.abc import AsyncIterator
from datetime import datetime, timedelta
from typing import Any

from homeassistant.components.siren import (
    SirenEntity,
    SirenEntityDescription,
    SirenEntityFeature,
)
from homeassistant.components.siren.const import ATTR_DURATION, ATTR_TONE
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.event import async_call_later
from homeassistant.util import dt as dt_util

from . import lib
from .audio import SAMPLE_RATE, SAMPLE_WIDTH
from .const import DOMAIN
from .coordinator import SannceConfigEntry, SannceCoordinator
from .entity import SannceEntity

PARALLEL_UPDATES = 0

_LOGGER = logging.getLogger(__name__)

# a built-in sound plays a few seconds; replay it to keep the siren going
# (checked at acceptance, protocol.md, Warning sound)
_REPEAT_SECONDS = 5.0
_MAX_DURATION = 300
_ALARM = "alarm"
_ALARM_HZ = (800.0, 1000.0)
_ALARM_SEGMENT_SECONDS = 0.25
_AMPLITUDE = 0.8
_CHUNK_BYTES = SAMPLE_RATE // 10 * SAMPLE_WIDTH
# bounds the whole start; a silent camera hits the backchannel's own 10 s bounds
# sooner, but a slow DESCRIBE, SETUP and PLAY can add up past this
_START_SECONDS = 25

SIREN = SirenEntityDescription(key="siren", translation_key="siren")


@functools.cache
def _alarm_cycle() -> bytes:
    peak = int(32767 * _AMPLITUDE)
    segment = int(SAMPLE_RATE * _ALARM_SEGMENT_SECONDS)
    count = segment * len(_ALARM_HZ)
    samples = (
        int(peak * math.sin(2 * math.pi * _ALARM_HZ[n // segment] * n / SAMPLE_RATE))
        for n in range(count)
    )
    return struct.pack(f"<{count}h", *samples)


async def _alarm_chunks(seconds: int) -> AsyncIterator[bytes]:
    cycle = _alarm_cycle()
    left = SAMPLE_RATE * seconds * SAMPLE_WIDTH
    while left > 0:
        for start in range(0, min(left, len(cycle)), _CHUNK_BYTES):
            yield cycle[start : min(start + _CHUNK_BYTES, left)]
        left -= len(cycle)


async def _announce_start(
    chunks: AsyncIterator[bytes], started: asyncio.Future[None]
) -> AsyncIterator[bytes]:
    # the speaker opens the camera session after the first pull; the second proves it
    async for chunk in chunks:
        yield chunk
        if not started.done():
            started.set_result(None)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SannceConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    if {"siren", "speaker"} & coordinator.camera.caps:
        async_add_entities([SannceSiren(coordinator, SIREN)])


class SannceSiren(SannceEntity, SirenEntity):
    _attr_supported_features = (
        SirenEntityFeature.TURN_ON
        | SirenEntityFeature.TURN_OFF
        | SirenEntityFeature.DURATION
        | SirenEntityFeature.TONES
    )

    def __init__(
        self, coordinator: SannceCoordinator, description: SirenEntityDescription
    ) -> None:
        super().__init__(coordinator, description)
        caps = coordinator.camera.caps
        count = coordinator.camera.sound_count if "siren" in caps else 0
        self._samples = {f"sound_{n}": n - 1 for n in range(1, count + 1)}
        self._tones = ([_ALARM] if "speaker" in caps else []) + list(self._samples)
        self._attr_available_tones = list(self._tones)
        self._attr_is_on = False
        self._tone = self._tones[0]
        self._sample = 0
        self._ends_at = dt_util.utcnow()
        self._next: CALLBACK_TYPE | None = None
        # a play that finishes under a newer generation no longer owns the siren
        self._generation = 0
        self._wanted = False

    async def async_turn_on(self, **kwargs: Any) -> None:
        tone = kwargs.get(ATTR_TONE) or self._tones[0]
        duration = min(kwargs.get(ATTR_DURATION) or _MAX_DURATION, _MAX_DURATION)
        self._generation += 1
        generation = self._generation
        self._cancel_repeat()
        previous = self._tone if self._wanted else None
        self._wanted = True
        self._tone = tone
        try:
            # the speaker and the built-in sounds would play over each other
            if previous and (previous == _ALARM) != (tone == _ALARM):
                await self._silence(previous)
                if generation != self._generation:
                    return
            if tone == _ALARM:
                await self._sound_alarm(generation, duration)
            else:
                await self._sound_builtin(generation, self._samples[tone], duration)
        except (lib.SannceError, TimeoutError) as err:
            if generation == self._generation:
                self._wanted = False
                self._set_on(False)
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="siren_failed",
                translation_placeholders={
                    "entity_id": self.entity_id,
                    "error": str(err),
                },
            ) from err

    async def async_turn_off(self, **kwargs: Any) -> None:
        self._generation += 1
        self._wanted = False
        self._cancel_repeat()
        self._set_on(False)
        await self._silence(self._tone)

    async def async_will_remove_from_hass(self) -> None:
        self._generation += 1
        self._wanted = False
        self._cancel_repeat()
        await self.coordinator.audio.stop(owner=self)

    @callback
    def _handle_coordinator_update(self) -> None:
        # HA skips service calls to an unavailable entity: a turn_off would never come
        if not self.available and self._wanted:
            sounding = self._attr_is_on
            self._generation += 1
            self._wanted = False
            self._cancel_repeat()
            self._attr_is_on = False
            # an alarm may still be starting; the stop ends only a play the siren owns
            if sounding or self._tone == _ALARM:
                self.coordinator.config_entry.async_create_background_task(
                    self.hass, self._silence(self._tone), "sannce siren stop"
                )
        super()._handle_coordinator_update()

    async def _sound_alarm(self, generation: int, duration: int) -> None:
        started: asyncio.Future[None] = self.hass.loop.create_future()
        task = self.coordinator.config_entry.async_create_background_task(
            self.hass, self._alarm(generation, duration, started), "sannce siren"
        )
        bound = asyncio.timeout(_START_SECONDS)
        try:
            async with bound:
                await started
        except asyncio.CancelledError:
            # finish the stop even if this call is cancelled again
            await asyncio.shield(self._stop_alarm(generation))
            raise
        except TimeoutError:
            if not bound.expired():
                raise
            await self._stop_alarm(generation)
            raise TimeoutError(f"the alarm tone did not start in {_START_SECONDS} s") from None
        if generation == self._generation:
            self._set_on(not task.done())

    async def _alarm(
        self, generation: int, duration: int, started: asyncio.Future[None]
    ) -> None:
        chunks = _announce_start(_alarm_chunks(duration), started)
        try:
            await self.coordinator.audio.play(chunks, owner=self)
        except Exception as err:
            if started.done():
                _LOGGER.error("siren tone failed: %s", err)
            else:
                started.set_exception(err)
        finally:
            # stopped or replaced before the camera took the tone
            if not started.done():
                started.set_result(None)
            if generation == self._generation:
                self._set_on(False)

    async def _stop_alarm(self, generation: int) -> None:
        # under a newer generation, a stop here could end a newer alarm
        if generation == self._generation:
            await self.coordinator.audio.stop(owner=self)

    async def _sound_builtin(self, generation: int, sample: int, duration: int) -> None:
        await self.coordinator.camera.play_sound(sample)
        if not await self._owns(generation, sample):
            return
        self._sample = sample
        self._ends_at = dt_util.utcnow() + timedelta(seconds=duration)
        self._schedule()
        self._set_on(True)

    async def _owns(self, generation: int, sample: int) -> bool:
        if generation == self._generation:
            return True
        # a newer built-in sound replaces this one on the camera; nothing else does
        if not self._wanted or self._tone == _ALARM:
            await self._stop(sample)
        return False

    async def _silence(self, tone: str) -> None:
        if tone == _ALARM:
            await self.coordinator.audio.stop(owner=self)
        else:
            await self._stop(self._sample)

    async def _stop(self, sample: int) -> None:
        try:
            await self.coordinator.camera.stop_sound(sample)
        except lib.SannceError as err:
            _LOGGER.debug("stopping sound %d failed: %s", sample, err)

    def _left(self) -> float:
        return (self._ends_at - dt_util.utcnow()).total_seconds()

    def _schedule(self) -> None:
        self._cancel_repeat()
        left = self._left()
        if left <= 0:
            self._set_on(False)
            return
        self._next = async_call_later(
            self.hass, min(_REPEAT_SECONDS, left), self._replay
        )

    @callback
    def _replay(self, _now: datetime) -> None:
        self._next = None
        if self._left() <= 0:
            self._set_on(False)
            return
        self.coordinator.config_entry.async_create_background_task(
            self.hass,
            self._play_again(self._generation, self._sample),
            "sannce siren replay",
        )

    async def _play_again(self, generation: int, sample: int) -> None:
        try:
            await self.coordinator.camera.play_sound(sample)
        except lib.SannceError as err:
            _LOGGER.error("siren replay failed: %s", err)
            if generation == self._generation:
                self._set_on(False)
            return
        if await self._owns(generation, sample):
            self._schedule()

    def _cancel_repeat(self) -> None:
        if self._next is not None:
            self._next()
            self._next = None

    def _set_on(self, on: bool) -> None:
        if self._attr_is_on != on:
            self._attr_is_on = on
            self.async_write_ha_state()
