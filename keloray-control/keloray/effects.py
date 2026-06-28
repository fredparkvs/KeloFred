"""Scene / effect engine.

Effects are async generators of attr-frames that get written to a device on a
fixed tick. Everything is rate-limited so we never hammer the Gizwits cloud
(it enforces per-device request limits). A frame is just an ``attrs`` dict, so
effects compose from the same datapoints the app uses: onOff, lum, hsv,
temperature.

Each effect is registered by name and takes keyword params, so the API/CLI/
scheduler can launch any of them with a JSON blob of options.
"""
from __future__ import annotations

import asyncio
import logging
import math
import random
from dataclasses import dataclass
from datetime import datetime
from typing import AsyncIterator, Awaitable, Callable

from . import solar
from .client import GizwitsClient, GizwitsError

logger = logging.getLogger("keloray.effects")

# A frame is an attrs dict to write. An effect yields frames until exhausted
# (finite, e.g. a fade) or forever (e.g. color loop) until cancelled.
Frame = dict
Effect = Callable[..., AsyncIterator[Frame]]

_REGISTRY: dict[str, "SceneSpec"] = {}


@dataclass
class SceneSpec:
    name: str
    fn: Effect
    description: str
    defaults: dict


def scene(name: str, description: str = "", **defaults):
    def deco(fn: Effect) -> Effect:
        _REGISTRY[name] = SceneSpec(name, fn, description or fn.__doc__ or "", defaults)
        return fn
    return deco


def list_scenes() -> list[SceneSpec]:
    return list(_REGISTRY.values())


def get_scene(name: str) -> SceneSpec:
    if name not in _REGISTRY:
        raise KeyError(f"unknown scene '{name}'. known: {sorted(_REGISTRY)}")
    return _REGISTRY[name]


# --- math helpers ---------------------------------------------------------
def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def _ease(t: float) -> float:
    """Smoothstep easing for natural-looking ramps."""
    return t * t * (3 - 2 * t)


# --- effects --------------------------------------------------------------
@scene("solid", "Set a fixed state once.", lum=100, on=True)
async def solid(*, lum=100, on=True, temperature=None, hsv=None, **_) -> AsyncIterator[Frame]:
    frame: Frame = {"onOff": 1 if on else 0}
    if lum is not None:
        frame["lum"] = int(lum)
    if temperature is not None:
        frame["temperature"] = int(temperature)
    if hsv is not None:
        frame["hsv"] = hsv
    yield frame


@scene("fade", "Smoothly fade brightness from one level to another.",
       start=0, end=100, seconds=5, tick=0.4)
async def fade(*, start=0, end=100, seconds=5, tick=0.4, **_) -> AsyncIterator[Frame]:
    steps = max(1, int(seconds / tick))
    yield {"onOff": 1}
    for i in range(steps + 1):
        t = _ease(i / steps)
        yield {"lum": int(round(_lerp(start, end, t)))}
        await asyncio.sleep(tick)


@scene("sunrise", "Warm, slow dawn: brightness + color temperature ramp up.",
       seconds=900, tick=2.0, warm=0, cool=100)
async def sunrise(*, seconds=900, tick=2.0, warm=0, cool=100, **_) -> AsyncIterator[Frame]:
    steps = max(1, int(seconds / tick))
    yield {"onOff": 1, "lum": 1}
    for i in range(steps + 1):
        t = _ease(i / steps)
        yield {"lum": max(1, int(round(_lerp(1, 100, t)))),
               "temperature": int(round(_lerp(warm, cool, t)))}
        await asyncio.sleep(tick)


@scene("sunset", "Reverse of sunrise: dim down to warm, then off.",
       seconds=900, tick=2.0, warm=0, cool=100)
async def sunset(*, seconds=900, tick=2.0, warm=0, cool=100, **_) -> AsyncIterator[Frame]:
    steps = max(1, int(seconds / tick))
    for i in range(steps + 1):
        t = _ease(i / steps)
        yield {"lum": max(1, int(round(_lerp(100, 1, t)))),
               "temperature": int(round(_lerp(cool, warm, t)))}
        await asyncio.sleep(tick)
    yield {"onOff": 0}


@scene("color_loop", "Cycle hue endlessly at fixed saturation/brightness.",
       saturation=100, value=100, period=30, tick=0.5)
async def color_loop(*, saturation=100, value=100, period=30, tick=0.5, **_) -> AsyncIterator[Frame]:
    yield {"onOff": 1}
    elapsed = 0.0
    while True:
        hue = int((elapsed / period) * 360) % 360
        yield {"hsv": {"h": hue, "s": int(saturation), "v": int(value)}}
        await asyncio.sleep(tick)
        elapsed += tick


@scene("breathe", "Gentle brightness pulse (sinusoidal).",
       low=10, high=100, period=6, tick=0.3)
async def breathe(*, low=10, high=100, period=6, tick=0.3, **_) -> AsyncIterator[Frame]:
    yield {"onOff": 1}
    elapsed = 0.0
    while True:
        # sine in [0,1]
        s = (math.sin(2 * math.pi * elapsed / period - math.pi / 2) + 1) / 2
        yield {"lum": int(round(_lerp(low, high, s)))}
        await asyncio.sleep(tick)
        elapsed += tick


@scene("candle", "Warm flicker that mimics a candle flame.",
       base=60, jitter=25, tick=0.25)
async def candle(*, base=60, jitter=25, tick=0.25, **_) -> AsyncIterator[Frame]:
    # Deterministic pseudo-flicker (no RNG dependency): layered sines.
    yield {"onOff": 1, "temperature": 5}
    elapsed = 0.0
    while True:
        f = (math.sin(elapsed * 7.3) + math.sin(elapsed * 13.1) * 0.5
             + math.sin(elapsed * 23.7) * 0.25)
        lum = base + f / 1.75 * jitter
        yield {"lum": max(1, min(100, int(round(lum))))}
        await asyncio.sleep(tick)
        elapsed += tick


@scene("thunderstorm", "Overcast storm with random lightning flashes.",
       base_lum=8, flash_lum=100, min_gap=2.0, max_gap=15.0,
       double_flash_chance=0.4, tick=0.5, seed=None)
async def thunderstorm(*, base_lum=8, flash_lum=100, min_gap=2.0, max_gap=15.0,
                       double_flash_chance=0.4, tick=0.5, seed=None,
                       **_) -> AsyncIterator[Frame]:
    """Simulate an overcast storm punctuated by lightning.

    The base state is a dim, cool/blue overcast (low ``base_lum`` with a faint
    blue tint and cool white). At random intervals (``min_gap``..``max_gap``
    seconds apart) a sudden bright flash (``flash_lum``, very cool/white) fires,
    sometimes as a quick double/triple flicker, before returning to the dark
    base.

    Params: ``base_lum`` (overcast brightness), ``flash_lum`` (flash peak),
    ``min_gap``/``max_gap`` (seconds between flashes), ``double_flash_chance``
    (probability of a multi-flicker), ``tick`` (base poll interval), and an
    optional ``seed`` for reproducible output in tests.

    CAVEAT: the SceneRunner enforces a ``min_interval`` (~0.25s) between cloud
    writes and the Gizwits cloud control path has its own latency, so true
    sub-100ms strobe is NOT achievable over the cloud — flashes here are only
    approximate. Crisp, snappy strobe would require local/BLE control instead
    of the cloud round-trip.
    """
    rng = random.Random(seed)

    def base_frame() -> Frame:
        # dim, cool, faint-blue overcast
        lum = max(1, min(100, int(base_lum)))
        return {"onOff": 1, "lum": lum, "temperature": 100,
                "hsv": {"h": 220, "s": 30, "v": lum}}

    def flash_frame() -> Frame:
        lum = max(1, min(100, int(flash_lum)))
        return {"onOff": 1, "lum": lum, "temperature": 100,
                "hsv": {"h": 0, "s": 0, "v": lum}}

    # establish the dark overcast base
    yield base_frame()
    while True:
        # wait out a random gap in the dark, polling at ``tick``
        gap = rng.uniform(min_gap, max_gap)
        waited = 0.0
        while waited < gap:
            yield base_frame()
            await asyncio.sleep(tick)
            waited += tick

        # LIGHTNING: one flash, possibly a quick double/triple flicker
        flickers = 1
        if rng.random() < double_flash_chance:
            flickers = rng.choice((2, 3))
        for _i in range(flickers):
            yield flash_frame()
            await asyncio.sleep(tick)
            # brief dark dip between flickers
            yield base_frame()
            await asyncio.sleep(tick)


@scene("tropics", "Track real tropical daylight (default ~Singapore).",
       latitude=solar.DEFAULT_LAT, longitude=solar.DEFAULT_LON,
       utc_offset=solar.DEFAULT_UTC, tick=60, wet_season=False, wet_months=None)
async def tropics(*, latitude=solar.DEFAULT_LAT, longitude=solar.DEFAULT_LON,
                  utc_offset=solar.DEFAULT_UTC, tick=60, wet_season=False,
                  wet_months=None, **_) -> AsyncIterator[Frame]:
    """Mirror real tropical daylight on the lamp, tracking the actual clock.

    On each tick (default every ``tick``=60s) the current local time is read
    via ``datetime.now()`` and run through the researched solar model in
    :mod:`keloray.solar`. The result tracks the real day: a warm, dim dawn
    (with a faint warm tint), ramping to a bright, cool noon, easing back to a
    warm dusk (faint blue tint just after sunset), then OFF (``onOff=0``) once
    the sun drops well below the horizon at night.

    ``latitude``/``longitude``/``utc_offset`` are configurable; the defaults
    correspond to roughly Singapore (1.35N, 103.82E, UTC+8).

    Wet-season tweak: when ``wet_season`` is on and the current month is in
    ``wet_months`` (defaults to Nov-Jan, the NE monsoon), the model is dimmed
    (lux x0.6) and pushed a touch cooler (+600K CCT) to evoke overcast,
    rain-laden tropical skies.

    Runs indefinitely, tracking the real day, until cancelled.
    """
    if wet_months is None:
        wet_months = [11, 12, 1]
    while True:
        now = datetime.now()
        lux_scale = 1.0
        cct_bump_k = 0.0
        if wet_season and now.month in wet_months:
            lux_scale = 0.6
            cct_bump_k = 600.0
        frame = solar.sun_channels(
            (now.year, now.month, now.day, now.hour, now.minute),
            latitude_deg=latitude, longitude_deg=longitude,
            utc_offset_hours=utc_offset, lux_scale=lux_scale, cct_bump_k=cct_bump_k)
        yield frame
        await asyncio.sleep(tick)


# --- runner ---------------------------------------------------------------
class SceneRunner:
    """Runs one effect against one device, writing frames with rate limiting.

    Only one scene runs per device at a time; starting a new one cancels the
    previous. ``min_interval`` is the floor between cloud writes.
    """

    def __init__(self, client: GizwitsClient, min_interval: float = 0.25):
        self.client = client
        self.min_interval = min_interval
        self._tasks: dict[str, asyncio.Task] = {}

    def running(self, did: str) -> bool:
        t = self._tasks.get(did)
        return bool(t and not t.done())

    async def stop(self, did: str) -> None:
        t = self._tasks.pop(did, None)
        if t and not t.done():
            t.cancel()
            try:
                await t
            except asyncio.CancelledError:
                pass

    async def start(self, did: str, scene_name: str, **params) -> None:
        await self.stop(did)
        spec = get_scene(scene_name)
        opts = {**spec.defaults, **params}
        self._tasks[did] = asyncio.create_task(self._run(did, spec, opts))

    async def _run(self, did: str, spec: SceneSpec, opts: dict) -> None:
        # Bounded retry with backoff, and tolerance for persistent failure so a
        # flaky/dead device can't kill the asyncio task silently.
        max_attempts = 3
        backoff = (0.5, 1.0)  # delay before retry 2 and 3
        max_consecutive_failures = 10
        last = 0.0
        consecutive_failures = 0
        try:
            async for frame in spec.fn(**opts):
                # enforce minimum spacing between cloud writes
                now = asyncio.get_running_loop().time()
                wait = self.min_interval - (now - last)
                if wait > 0:
                    await asyncio.sleep(wait)

                wrote = False
                for attempt in range(1, max_attempts + 1):
                    try:
                        await self.client.control(did, frame)
                        wrote = True
                        break
                    except asyncio.CancelledError:
                        raise
                    except (GizwitsError, Exception) as exc:  # noqa: B014
                        if attempt < max_attempts:
                            delay = backoff[min(attempt - 1, len(backoff) - 1)]
                            logger.warning(
                                "scene %r device %s: control write failed "
                                "(attempt %d/%d): %s; retrying in %.1fs",
                                spec.name, did, attempt, max_attempts, exc, delay)
                            await asyncio.sleep(delay)
                        else:
                            logger.warning(
                                "scene %r device %s: control write failed after "
                                "%d attempts: %s; skipping frame",
                                spec.name, did, max_attempts, exc)
                    finally:
                        last = asyncio.get_running_loop().time()

                if wrote:
                    consecutive_failures = 0
                else:
                    consecutive_failures += 1
                    if consecutive_failures >= max_consecutive_failures:
                        logger.error(
                            "scene %r device %s: %d consecutive failed frames; "
                            "stopping scene",
                            spec.name, did, consecutive_failures)
                        break
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception(
                "scene %r device %s: unexpected error; stopping scene",
                spec.name, did)

    async def stop_all(self) -> None:
        for did in list(self._tasks):
            await self.stop(did)
