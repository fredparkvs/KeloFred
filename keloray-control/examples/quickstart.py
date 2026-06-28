"""Minimal end-to-end example.

    export KELORAY_APP_ID=...        # from `python -m keloray probe`
    export KELORAY_USERNAME=...
    export KELORAY_PASSWORD=...
    python examples/quickstart.py
"""
import asyncio
import os

from keloray import GizwitsClient
from keloray.effects import SceneRunner


async def main():
    async with GizwitsClient(
        app_id=os.environ["KELORAY_APP_ID"],
        region=os.environ.get("KELORAY_REGION", "cn"),
    ) as c:
        await c.login(os.environ["KELORAY_USERNAME"], os.environ["KELORAY_PASSWORD"])

        devices = await c.bindings()
        if not devices:
            print("No devices on this account.")
            return
        dev = devices[0]
        print(f"Using {dev.alias!r} ({dev.did}), online={dev.is_online}")

        print("current state:", await c.latest(dev.did))
        print("datapoint schema:", await c.datapoints(dev.product_key))

        # turn on, set warm 40% brightness
        await c.control(dev.did, {"onOff": 1, "lum": 40, "temperature": 10})
        await asyncio.sleep(2)

        # run a 20s sunrise
        runner = SceneRunner(c)
        await runner.start(dev.did, "sunrise", seconds=20, tick=1.0)
        await asyncio.sleep(22)
        await runner.stop(dev.did)


if __name__ == "__main__":
    asyncio.run(main())
