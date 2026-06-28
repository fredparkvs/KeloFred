"""FastAPI server: programmable REST API + a small web dashboard.

Run:  uvicorn keloray.server:app   (after configuring credentials)
or:   python -m keloray serve

Endpoints
---------
GET  /api/devices                      list bound devices (+ online state)
GET  /api/devices/{did}                latest datapoint values
POST /api/devices/{did}/control        body: {"attrs": {...}}  raw write
POST /api/devices/{did}/power          body: {"on": true}
POST /api/devices/{did}/scene          body: {"scene": "...", "params": {...}}
POST /api/devices/{did}/scene/stop     stop the running scene
GET  /api/scenes                       list available scenes + defaults
GET  /api/schedules                    list automations
POST /api/schedules                    add/replace an automation rule
DELETE /api/schedules/{name}           remove an automation
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .client import GizwitsClient, GizwitsError
from .config import Config
from .effects import SceneRunner, list_scenes
from .scheduler import Automations, Rule

WEB_DIR = Path(__file__).resolve().parent / "web"


class State:
    client: GizwitsClient
    runner: SceneRunner
    autos: Automations


state = State()


@asynccontextmanager
async def lifespan(app: FastAPI):
    cfg = Config.load()
    if not cfg.app_id:
        raise RuntimeError(
            "No app_id configured. Set KELORAY_APP_ID (run `python -m keloray "
            "probe` to find it) or use a config file."
        )
    state.client = GizwitsClient(
        app_id=cfg.app_id, region=cfg.region, creds_path=cfg.creds_path
    )
    if not state.client.token and not cfg.username:
        raise RuntimeError(
            "No usable authentication. Either run `python -m keloray login` "
            "first to cache a token, or set KELORAY_USERNAME and "
            "KELORAY_PASSWORD. Refusing to start so the server doesn't 401 on "
            "every request."
        )
    if not state.client.token and cfg.username:
        try:
            await state.client.login(cfg.username, cfg.password)
        except GizwitsError as e:
            raise RuntimeError(
                "Login failed with the configured credentials "
                "(KELORAY_USERNAME/KELORAY_PASSWORD). Check the username and "
                f"password are correct: {e}"
            ) from e
    state.runner = SceneRunner(state.client, min_interval=cfg.min_interval)
    state.autos = Automations(state.runner)
    state.autos.load(cfg.rules)
    state.autos.start()
    try:
        yield
    finally:
        await state.runner.stop_all()
        state.autos.shutdown()
        await state.client.aclose()


app = FastAPI(title="Keloray Control", version="0.1.0", lifespan=lifespan)


# --- models ---------------------------------------------------------------
class ControlBody(BaseModel):
    attrs: dict[str, Any]


class PowerBody(BaseModel):
    on: bool


class SceneBody(BaseModel):
    scene: str
    params: dict[str, Any] = {}


class ScheduleBody(BaseModel):
    name: str
    did: str
    scene: str
    params: dict[str, Any] = {}
    cron: dict[str, Any] = {}
    at: str | None = None
    enabled: bool = True


def _wrap(exc: GizwitsError) -> HTTPException:
    return HTTPException(status_code=502, detail={"gizwits_status": exc.status, "body": exc.payload})


# --- device routes --------------------------------------------------------
@app.get("/api/devices")
async def devices():
    try:
        return [d.__dict__ for d in await state.client.bindings()]
    except GizwitsError as e:
        raise _wrap(e)


@app.get("/api/devices/{did}")
async def device_state(did: str):
    try:
        return {"did": did, "attrs": await state.client.latest(did),
                "scene_running": state.runner.running(did)}
    except GizwitsError as e:
        raise _wrap(e)


@app.post("/api/devices/{did}/control")
async def control(did: str, body: ControlBody):
    await state.runner.stop(did)  # manual control overrides any running scene
    try:
        return {"ok": True, "result": await state.client.control(did, body.attrs)}
    except GizwitsError as e:
        raise _wrap(e)


@app.post("/api/devices/{did}/power")
async def power(did: str, body: PowerBody):
    await state.runner.stop(did)
    try:
        return {"ok": True, "result": await state.client.set_power(did, body.on)}
    except GizwitsError as e:
        raise _wrap(e)


@app.post("/api/devices/{did}/scene")
async def run_scene(did: str, body: SceneBody):
    try:
        await state.runner.start(did, body.scene, **body.params)
    except KeyError as e:
        raise HTTPException(404, str(e))
    return {"ok": True, "scene": body.scene}


@app.post("/api/devices/{did}/scene/stop")
async def stop_scene(did: str):
    await state.runner.stop(did)
    return {"ok": True}


# --- scenes / schedules ---------------------------------------------------
@app.get("/api/scenes")
async def scenes():
    return [{"name": s.name, "description": s.description, "defaults": s.defaults}
            for s in list_scenes()]


@app.get("/api/schedules")
async def schedules():
    return [r.__dict__ for r in state.autos.list()]


@app.post("/api/schedules")
async def add_schedule(body: ScheduleBody):
    state.autos.add(Rule(**body.model_dump()))
    return {"ok": True}


@app.delete("/api/schedules/{name}")
async def del_schedule(name: str):
    state.autos.remove(name)
    return {"ok": True}


# --- dashboard ------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
async def index():
    idx = WEB_DIR / "index.html"
    return idx.read_text() if idx.exists() else "<h1>Keloray Control</h1>"


if WEB_DIR.exists():
    app.mount("/web", StaticFiles(directory=str(WEB_DIR)), name="web")
