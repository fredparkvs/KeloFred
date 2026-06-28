"""Offline tests: mock the Gizwits HTTP layer so we exercise request-building,
auth headers, control payloads, and the effects engine without a real account.
"""
import asyncio

import httpx
import pytest

from keloray.client import GizwitsClient
from keloray.effects import SceneRunner, list_scenes, fade


def make_client(handler) -> GizwitsClient:
    c = GizwitsClient(app_id="testapp", region="cn")
    c._http = httpx.AsyncClient(
        base_url=c.base, transport=httpx.MockTransport(handler)
    )
    return c


def test_control_payload_and_headers():
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["url"] = str(req.url)
        seen["app_id"] = req.headers.get("X-Gizwits-Application-Id")
        seen["token"] = req.headers.get("X-Gizwits-User-token")
        seen["body"] = req.content.decode()
        return httpx.Response(200, json={"ok": True})

    async def run():
        c = make_client(handler)
        c.token = "tok123"
        await c.control("DID1", {"onOff": 1, "lum": 80})
        await c.aclose()

    asyncio.run(run())
    assert seen["url"].endswith("/app/control/DID1")
    assert seen["app_id"] == "testapp"
    assert seen["token"] == "tok123"
    import json as _json
    body = _json.loads(seen["body"])
    assert body == {"attrs": {"onOff": 1, "lum": 80}}


def test_login_caches_token():
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"uid": "u1", "token": "abc", "expire_at": 1})

    async def run():
        c = make_client(handler)
        await c.login("user", "pw")
        tok = c.token
        await c.aclose()
        return tok

    assert asyncio.run(run()) == "abc"


def test_bindings_parsing():
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"devices": [
            {"did": "D1", "product_key": "pk", "dev_alias": "Desk", "is_online": True},
        ]})

    async def run():
        c = make_client(handler)
        devs = await c.bindings()
        await c.aclose()
        return devs

    devs = asyncio.run(run())
    assert devs[0].did == "D1" and devs[0].alias == "Desk" and devs[0].is_online


def test_scene_registry_nonempty():
    names = {s.name for s in list_scenes()}
    assert {"solid", "fade", "sunrise", "color_loop", "breathe", "candle"} <= names


def test_fade_yields_frames():
    async def run():
        frames = [f async for f in fade(start=0, end=100, seconds=1, tick=0.5)]
        return frames

    frames = asyncio.run(run())
    assert frames[0] == {"onOff": 1}
    assert any("lum" in f for f in frames)
    assert frames[-1]["lum"] == 100


def test_runner_writes_frames():
    writes = []

    def handler(req: httpx.Request) -> httpx.Response:
        writes.append(req.content.decode())
        return httpx.Response(200, json={"ok": True})

    async def run():
        c = make_client(handler)
        runner = SceneRunner(c, min_interval=0.0)
        await runner.start("D1", "fade", start=0, end=100, seconds=1, tick=0.2)
        await asyncio.sleep(1.6)
        await runner.stop("D1")
        await c.aclose()

    asyncio.run(run())
    assert len(writes) >= 3
    assert any('"lum"' in w for w in writes)
