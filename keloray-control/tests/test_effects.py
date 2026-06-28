"""Offline tests for effects engine resilience, thunderstorm, tropics."""
from __future__ import annotations

import asyncio

import pytest

from keloray import solar
from keloray.client import GizwitsError
from keloray.effects import SceneRunner, _REGISTRY, get_scene

_ORIG_SLEEP = asyncio.sleep


# --- helpers --------------------------------------------------------------
async def _collect(agen, cap):
    """Consume up to ``cap`` frames from an async generator, sleeping as no-op."""
    frames = []
    async for frame in agen:
        frames.append(frame)
        if len(frames) >= cap:
            break
    await agen.aclose()
    return frames


@pytest.fixture(autouse=True)
def _fast_sleep(monkeypatch):
    """Make asyncio.sleep a no-op so generators iterate instantly."""
    async def _noop(*_a, **_k):
        return None
    monkeypatch.setattr(asyncio, "sleep", _noop)


# --- registry -------------------------------------------------------------
def test_registry_has_new_scenes():
    assert "thunderstorm" in _REGISTRY
    assert "tropics" in _REGISTRY
    assert get_scene("thunderstorm").name == "thunderstorm"
    assert get_scene("tropics").name == "tropics"


# --- thunderstorm ---------------------------------------------------------
def test_thunderstorm_base_dim_and_flashes():
    spec = get_scene("thunderstorm")
    agen = spec.fn(base_lum=8, flash_lum=100, min_gap=0.5, max_gap=1.5,
                   double_flash_chance=0.5, tick=0.5, seed=1234)
    frames = asyncio.run(_collect(agen, 40))

    base_frames = [f for f in frames if f.get("lum", 0) <= 12]
    flash_frames = [f for f in frames if f.get("lum", 0) >= 90]

    assert base_frames, "expected dim overcast base frames"
    assert all(f["lum"] <= 12 for f in base_frames)
    assert flash_frames, "expected at least one bright flash frame"
    assert max(f["lum"] for f in flash_frames) >= 90


def test_thunderstorm_seed_reproducible():
    spec = get_scene("thunderstorm")
    a = asyncio.run(_collect(
        spec.fn(min_gap=0.5, max_gap=1.5, tick=0.5, seed=7), 30))
    b = asyncio.run(_collect(
        spec.fn(min_gap=0.5, max_gap=1.5, tick=0.5, seed=7), 30))
    assert a == b


# --- tropics / solar ------------------------------------------------------
def test_tropics_predawn_off():
    # ~04:00 local, well before sunrise in Singapore -> lights off
    frame = solar.sun_channels((2026, 6, 28, 4, 0))
    assert frame["onOff"] == 0


def test_tropics_noon_bright_cool():
    # ~13:00 local, near solar noon at default tropical lat
    frame = solar.sun_channels((2026, 6, 28, 13, 0))
    assert frame["onOff"] == 1
    assert frame["lum"] >= 80
    assert frame["temperature"] >= 80  # cool white near noon


def test_tropics_wet_season_dims():
    dry = solar.sun_channels((2026, 6, 28, 13, 0), lux_scale=1.0, cct_bump_k=0.0)
    wet = solar.sun_channels((2026, 6, 28, 13, 0), lux_scale=0.6, cct_bump_k=600.0)
    assert wet["lum"] < dry["lum"]


def test_tropics_scene_yields_frame():
    spec = get_scene("tropics")
    agen = spec.fn(tick=60)
    frames = asyncio.run(_collect(agen, 2))
    assert frames
    assert "onOff" in frames[0]


# --- F8 runner resilience -------------------------------------------------
class _FlakyClient:
    """Fails ``fail_times`` writes then succeeds; or always fails."""

    def __init__(self, fail_times=0, always_fail=False):
        self.fail_times = fail_times
        self.always_fail = always_fail
        self.calls = 0
        self.successes = 0

    async def control(self, did, attrs):
        self.calls += 1
        if self.always_fail or self.calls <= self.fail_times:
            raise GizwitsError("boom")
        self.successes += 1
        return {"ok": True}


def _short_effect(n=5):
    async def gen(**_):
        for i in range(n):
            yield {"lum": i + 1}
    return gen


def test_runner_retries_then_continues():
    client = _FlakyClient(fail_times=2)  # first two attempts fail, then ok
    runner = SceneRunner(client, min_interval=0.0)

    from keloray.effects import SceneSpec
    spec = SceneSpec("t", _short_effect(3), "", {})

    asyncio.run(runner._run("dev1", spec, {}))
    # 2 failed attempts + 1 success on first frame, then 2 more frames succeed.
    assert client.successes >= 3
    assert client.calls >= 5


def test_runner_permanent_failure_stops_cleanly():
    client = _FlakyClient(always_fail=True)
    runner = SceneRunner(client, min_interval=0.0)

    async def gen(**_):
        # effectively infinite; runner must stop on its own
        while True:
            yield {"lum": 1}

    from keloray.effects import SceneSpec
    spec = SceneSpec("t", gen, "", {})

    # Must NOT raise out of _run despite permanent failures.
    asyncio.run(runner._run("dev1", spec, {}))
    # Stopped after the consecutive-failure threshold (10 frames x 3 attempts).
    assert client.successes == 0
    assert client.calls == 30


def test_runner_cancellation_propagates(monkeypatch):
    # Use the real asyncio.sleep here so the loop actually yields control,
    # letting cancellation land.
    real_sleep = _ORIG_SLEEP
    monkeypatch.setattr(asyncio, "sleep", real_sleep)

    client = _FlakyClient()
    runner = SceneRunner(client, min_interval=0.0)

    async def gen(**_):
        while True:
            yield {"lum": 1}
            await asyncio.sleep(0.01)

    from keloray.effects import SceneSpec
    spec = SceneSpec("t", gen, "", {})

    async def drive():
        task = asyncio.create_task(runner._run("dev1", spec, {}))
        await asyncio.sleep(0.02)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(drive())
