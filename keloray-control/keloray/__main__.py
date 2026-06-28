"""Command-line interface.

Examples
--------
  python -m keloray probe                      # find the live App-Id
  python -m keloray login                       # log in, cache token
  python -m keloray devices                     # list your lights
  python -m keloray state <did>                 # show current attrs
  python -m keloray set <did> onOff=1 lum=80    # raw datapoint write
  python -m keloray scene <did> sunrise seconds=600
  python -m keloray serve                       # run API + dashboard
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys

from .client import GizwitsClient, CANDIDATE_APP_IDS
from .config import Config
from .effects import SceneRunner, list_scenes


def _coerce(v: str):
    """Turn CLI 'key=val' values into int/float/bool/json where sensible."""
    for cast in (int, float):
        try:
            return cast(v)
        except ValueError:
            pass
    if v.lower() in ("true", "false"):
        return v.lower() == "true"
    if v and v[0] in "{[":
        try:
            return json.loads(v)
        except ValueError:
            pass
    return v


def _kv(pairs: list[str]) -> dict:
    out = {}
    for p in pairs:
        if "=" not in p:
            raise SystemExit(f"expected key=value, got '{p}'")
        k, v = p.split("=", 1)
        out[k] = _coerce(v)
    return out


def _client(cfg: Config) -> GizwitsClient:
    if not cfg.app_id:
        raise SystemExit("No app_id. Run `python -m keloray probe` then set KELORAY_APP_ID.")
    return GizwitsClient(app_id=cfg.app_id, region=cfg.region, creds_path=cfg.creds_path)


async def cmd_probe(args, cfg):
    print(f"Probing {len(CANDIDATE_APP_IDS)} candidate App-Ids in region '{cfg.region}'...")
    good = await GizwitsClient.probe_app_id(region=cfg.region)
    if good:
        print("Live App-Id(s):")
        for g in good:
            print(f"  {g}")
        print("\nSet one:  export KELORAY_APP_ID=<value>")
    else:
        print("None accepted in this region. Try --region us / eu.")


async def cmd_login(args, cfg):
    if not (cfg.username and cfg.password):
        raise SystemExit("Set KELORAY_USERNAME and KELORAY_PASSWORD (or use config).")
    async with _client(cfg) as c:
        data = await c.login(cfg.username, cfg.password)
        print(f"Logged in. uid={data.get('uid')}, token cached -> {cfg.creds_path}")


async def cmd_devices(args, cfg):
    async with _client(cfg) as c:
        for d in await c.bindings():
            mark = "online" if d.is_online else "offline"
            print(f"{d.did}  [{mark}]  {d.alias!r}  product_key={d.product_key}")


async def cmd_state(args, cfg):
    async with _client(cfg) as c:
        print(json.dumps(await c.latest(args.did), indent=2))


async def cmd_discover(args, cfg):
    """Dump a device's datapoint schema + current values together.

    This is what you run on a coral fixture (e.g. the AL100) to learn its real
    channel datapoints, then copy them into the config `channels:` map."""
    async with _client(cfg) as c:
        dev = next((d for d in await c.bindings() if d.did == args.did), None)
        if not dev:
            raise SystemExit(f"device {args.did} not found in your bindings "
                             "(run `python -m keloray devices`)")
        print(f"# {dev.alias!r}  did={dev.did}  product_key={dev.product_key}  "
              f"online={dev.is_online}")
        print("\n## datapoint schema (the real channel names + ranges):")
        print(json.dumps(await c.datapoints(dev.product_key), indent=2))
        print("\n## current values:")
        print(json.dumps(await c.latest(dev.did), indent=2))


async def cmd_datapoints(args, cfg):
    async with _client(cfg) as c:
        print(json.dumps(await c.datapoints(args.product_key), indent=2))


async def cmd_set(args, cfg):
    async with _client(cfg) as c:
        print(json.dumps(await c.control(args.did, _kv(args.attrs)), indent=2))


async def cmd_scene(args, cfg):
    async with _client(cfg) as c:
        runner = SceneRunner(c, min_interval=cfg.min_interval,
                             channel_map=cfg.channel_map())
        await runner.start(args.did, args.scene, **_kv(args.params))
        print(f"Running '{args.scene}' on {args.did}. Ctrl-C to stop.")
        try:
            while runner.running(args.did):
                await asyncio.sleep(0.5)
        except KeyboardInterrupt:
            await runner.stop(args.did)
            print("stopped.")


async def cmd_scenes(args, cfg):
    for s in list_scenes():
        print(f"{s.name:12} {s.description}")
        print(f"             defaults: {s.defaults}")


def cmd_serve(args, cfg):
    import uvicorn
    uvicorn.run("keloray.server:app", host=args.host, port=args.port, reload=False)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="keloray", description="Keloray smart-light controller")
    p.add_argument("--region", help="cn|us|eu (overrides config/env)")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("probe", help="find the live App-Id")
    sub.add_parser("login", help="log in and cache a token")
    sub.add_parser("devices", help="list bound devices")
    sub.add_parser("scenes", help="list available scenes")

    sp = sub.add_parser("state", help="show a device's latest attrs"); sp.add_argument("did")
    sp = sub.add_parser("discover", help="dump a device's datapoint schema + current values"); sp.add_argument("did")
    sp = sub.add_parser("datapoints", help="show product datapoint schema"); sp.add_argument("product_key")
    sp = sub.add_parser("set", help="write attrs: set <did> k=v ..."); sp.add_argument("did"); sp.add_argument("attrs", nargs="+")
    sp = sub.add_parser("scene", help="run a scene: scene <did> <name> k=v ...")
    sp.add_argument("did"); sp.add_argument("scene"); sp.add_argument("params", nargs="*", default=[])
    sp = sub.add_parser("serve", help="run API + dashboard")
    sp.add_argument("--host", default="127.0.0.1"); sp.add_argument("--port", type=int, default=8000)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    cfg = Config.load()
    if args.region:
        cfg.region = args.region
    handlers = {
        "probe": cmd_probe, "login": cmd_login, "devices": cmd_devices,
        "state": cmd_state, "discover": cmd_discover, "datapoints": cmd_datapoints,
        "set": cmd_set, "scene": cmd_scene, "scenes": cmd_scenes,
    }
    if args.cmd == "serve":
        return cmd_serve(args, cfg)
    asyncio.run(handlers[args.cmd](args, cfg))


if __name__ == "__main__":
    main()
