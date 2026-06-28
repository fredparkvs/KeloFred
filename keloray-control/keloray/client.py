"""Async client for the Gizwits OpenAPI v1.

Reverse-engineered from the Keloray Smart Light app (com.keloray.smartlight),
which is a white-label Gizwits IoT app. The request contract was confirmed from
the app's JS bundle:

    headers: X-Gizwits-Application-Id: <app_id>
             X-Gizwits-User-token:    <user token>   (for authed calls)
    flow:    POST /app/users           -> anonymous register (uid + token)
             POST /app/login           -> username/password login
             GET  /app/bindings        -> bound devices (did, product_key, ...)
             GET  /app/devdata/{did}/latest  -> latest datapoint values
             POST /app/control/{did}   -> body {"attrs": {...}}
             GET  /app/datapoint?product_key=<pk>  -> datapoint schema

Everything you control lives in the device's `attrs` map. For these lights the
common attributes are: onOff, lum (brightness), hsv (color), temperature
(white color temperature), mode/scene. The exact set + ranges for *your*
device are discovered live via `datapoints()` and `latest()`.
"""
from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

# Region -> OpenAPI host. Confirmed in the bundle: api / usapi / euapi.
REGIONS = {
    "cn": "https://api.gizwitsapi.com",
    "us": "https://usapi.gizwitsapi.com",
    "eu": "https://euapi.gizwitsapi.com",
}

# App-Id candidates extracted from the app bundle. The live one is whichever
# answers `POST /app/users` with a token; use `probe_app_id()` to find it, or
# set your own in config. (These are the app's public Application-Id, not the
# AppSecret -- the Application-Id is sent in the clear on every request.)
CANDIDATE_APP_IDS = [
    "b04a7fb790fd42b69026721f1930ad4e",
    "f089fe16912a4680bf9b276b121581b0",
    "afb8f41dbb274cb19d0fdf472945fbf3",
    "f50095a20a2f4152a3685a01a863ec5a",
]


class GizwitsError(RuntimeError):
    """Raised when the Gizwits API returns an error envelope."""

    def __init__(self, status: int, payload: Any):
        self.status = status
        self.payload = payload
        super().__init__(f"Gizwits API error {status}: {payload}")


@dataclass
class Device:
    did: str
    product_key: str
    mac: str = ""
    alias: str = ""
    product_name: str = ""
    is_online: bool = False
    raw: dict = field(default_factory=dict)

    @classmethod
    def from_api(cls, d: dict) -> "Device":
        return cls(
            did=d.get("did", ""),
            product_key=d.get("product_key", ""),
            mac=d.get("mac", ""),
            alias=d.get("dev_alias") or d.get("remark") or d.get("product_name", ""),
            product_name=d.get("product_name", ""),
            is_online=bool(d.get("is_online", False)),
            raw=d,
        )


class GizwitsClient:
    """Minimal async wrapper around the Gizwits OpenAPI used by the app."""

    def __init__(
        self,
        app_id: str,
        region: str = "cn",
        token: str | None = None,
        uid: str | None = None,
        timeout: float = 15.0,
        creds_path: str | Path | None = None,
    ):
        if region not in REGIONS:
            raise ValueError(f"region must be one of {list(REGIONS)}")
        self.app_id = app_id
        self.region = region
        self.base = REGIONS[region]
        self.token = token
        self.uid = uid
        self._creds_path = Path(creds_path).expanduser() if creds_path else None
        self._http = httpx.AsyncClient(timeout=timeout, base_url=self.base)
        # Per-device schema awareness (F1). Lazily populated on first control():
        #   _did_pk:     did -> product_key (sourced from bindings())
        #   _pk_schema:  product_key -> raw datapoint schema (from datapoints())
        # Both caches tolerate fetch failures; on any uncertainty control()
        # falls back to sending the canonical attrs through unchanged.
        self._did_pk: dict[str, str] = {}
        self._pk_schema: dict[str, dict] = {}
        if self._creds_path and self._creds_path.exists() and not token:
            self._load_creds()

    # -- lifecycle ---------------------------------------------------------
    async def aclose(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> "GizwitsClient":
        return self

    async def __aexit__(self, *exc) -> None:
        await self.aclose()

    # -- low level ---------------------------------------------------------
    def _headers(self, authed: bool = True) -> dict:
        h = {
            "Content-Type": "application/json",
            "X-Gizwits-Application-Id": self.app_id,
        }
        if authed and self.token:
            h["X-Gizwits-User-token"] = self.token
        return h

    async def _request(self, method: str, path: str, *, authed: bool = True, **kw) -> Any:
        headers = {**self._headers(authed), **kw.pop("headers", {})}
        resp = await self._http.request(method, path, headers=headers, **kw)
        ctype = resp.headers.get("content-type", "")
        body = resp.json() if "json" in ctype else resp.text
        if resp.status_code >= 400:
            raise GizwitsError(resp.status_code, body)
        return body

    # -- auth --------------------------------------------------------------
    async def register_anonymous(self, phone_id: str = "keloray-control") -> dict:
        """Create an anonymous Gizwits user. Returns {uid, token, expire_at}.

        Anonymous users cannot see devices bound to your real account; use
        `login()` with your app credentials to reach your real lights. This is
        mainly useful for `probe_app_id()` and smoke tests.
        """
        data = await self._request(
            "POST", "/app/users", authed=False,
            json={"phone_id": phone_id, "lang": "en"},
        )
        self._apply_auth(data)
        return data

    async def login(self, username: str, password: str) -> dict:
        """Log in with the same username/password you use in the app."""
        data = await self._request(
            "POST", "/app/login", authed=False,
            json={"username": username, "password": password, "lang": "en"},
        )
        self._apply_auth(data)
        return data

    def _apply_auth(self, data: dict) -> None:
        if isinstance(data, dict) and data.get("token"):
            self.token = data["token"]
            self.uid = data.get("uid", self.uid)
            if self._creds_path:
                self._save_creds()

    # -- devices -----------------------------------------------------------
    async def bindings(self, limit: int = 50, skip: int = 0) -> list[Device]:
        data = await self._request(
            "GET", "/app/bindings", params={"limit": limit, "skip": skip}
        )
        return [Device.from_api(d) for d in data.get("devices", [])]

    async def latest(self, did: str) -> dict:
        """Latest datapoint values for a device: {attr: {...}, ...}."""
        data = await self._request("GET", f"/app/devdata/{did}/latest")
        return data.get("attr", data) if isinstance(data, dict) else data

    async def control(self, did: str, attrs: dict[str, Any]) -> Any:
        """Write datapoints. e.g. control(did, {"onOff": 1, "lum": 80}).

        Canonical attrs (onOff, lum, temperature, hsv) are first normalized to
        whatever datapoint names/shapes the device's product actually exposes
        (see `_normalized`). The wire format is unchanged: we still POST
        /app/control/{did} with body {"attrs": <normalized>}. If the product's
        schema cannot be discovered (or anything is ambiguous), the attrs are
        sent through unchanged.
        """
        attrs = await self._normalized(did, attrs)
        return await self._request("POST", f"/app/control/{did}", json={"attrs": attrs})

    async def datapoints(self, product_key: str) -> dict:
        """Datapoint schema for a product (names, types, ranges, enums)."""
        return await self._request(
            "GET", "/app/datapoint", authed=False,
            params={"product_key": product_key},
        )

    # -- schema-aware normalization (F1) -----------------------------------
    async def _product_key_for(self, did: str) -> str | None:
        """Resolve (and cache) the product_key for a device id.

        Sourced from bindings(); tolerant of failures (returns None so the
        caller can fall back to pass-through control).
        """
        if did in self._did_pk:
            return self._did_pk[did]
        try:
            for dev in await self.bindings():
                if dev.did and dev.product_key:
                    self._did_pk[dev.did] = dev.product_key
        except Exception:
            return None
        return self._did_pk.get(did)

    async def _schema_for(self, did: str) -> dict | None:
        """Resolve (and cache) the datapoint schema for a device's product.

        Tolerant of failures: returns None if the product_key or the schema
        cannot be fetched, which makes control() fall back to pass-through.
        """
        pk = await self._product_key_for(did)
        if not pk:
            return None
        if pk not in self._pk_schema:
            try:
                self._pk_schema[pk] = await self.datapoints(pk)
            except Exception:
                return None
        return self._pk_schema.get(pk)

    async def refresh_schema(self, did: str) -> dict | None:
        """Force a re-fetch of a device's product_key + datapoint schema.

        Useful after a product firmware/profile change. Returns the freshly
        fetched schema, or None if it could not be discovered.
        """
        self._did_pk.pop(did, None)
        pk = await self._product_key_for(did)
        if pk:
            self._pk_schema.pop(pk, None)
        return await self._schema_for(did)

    async def _normalized(self, did: str, attrs: dict[str, Any]) -> dict[str, Any]:
        """Rewrite canonical attrs to the product's real datapoint schema.

        Real Gizwits light products vary: some expose a single packed color
        datapoint, others separate H/S/V datapoints, and names/ranges differ.
        We discover the product's datapoint schema (lazily cached) and map our
        canonical keys onto it. This is purely additive/defensive -- if the
        schema can't be fetched or a mapping is ambiguous, the original attr is
        passed through unchanged.

        Mapping heuristic (only applied when the relevant datapoint is found):
          * hsv -> a single color datapoint whose name contains 'hsv'/'color'
            or whose type is object/json: sent as {"h","s","v"} under that
            real name. If instead three separate hue/saturation/value (a.k.a.
            H/S/V or color_h/color_s/color_v style) datapoints exist, hsv is
            split into them, scaling each component from its canonical range
            (h 0..360, s/v 0..100) to the datapoint's declared min/max.
          * lum / temperature / onOff are pass-through, but if a matching
            datapoint declares a different name and/or numeric min/max, the
            value is renamed and scaled from its canonical range to that range.
        """
        schema = await self._schema_for(did)
        if not schema:
            return attrs
        index = self._index_schema(schema)
        if not index:
            return attrs

        out: dict[str, Any] = {}
        for key, value in attrs.items():
            try:
                mapped = self._map_attr(key, value, index)
            except Exception:
                mapped = {key: value}
            out.update(mapped)
        return out

    @staticmethod
    def _index_schema(schema: dict) -> dict[str, dict]:
        """Flatten a Gizwits datapoint schema into {lower_name: attr_dict}.

        Gizwits schema JSON shapes vary; we parse loosely and look for attr
        descriptors (each having a `name`) wherever they appear -- typically
        under entities[].attrs[], but also a top-level attrs[]/datapoints[].
        Each descriptor may carry type, uint_spec/min/max, enum, etc. Returns
        an empty dict if nothing recognizable is found (-> pass-through).
        """
        index: dict[str, dict] = {}

        def consume(attr: Any) -> None:
            if isinstance(attr, dict) and isinstance(attr.get("name"), str):
                index.setdefault(attr["name"].lower(), attr)

        def walk(node: Any) -> None:
            if isinstance(node, dict):
                # A datapoint descriptor in its own right.
                if isinstance(node.get("name"), str) and (
                    "type" in node or "data_type" in node
                    or "uint_spec" in node or "enum" in node
                ):
                    consume(node)
                for v in node.values():
                    walk(v)
            elif isinstance(node, list):
                for item in node:
                    walk(item)

        walk(schema)
        return index

    @staticmethod
    def _range_of(attr: dict) -> tuple[float, float] | None:
        """Best-effort (min, max) for a numeric datapoint, or None.

        Looks at common locations: top-level min/max and the nested
        uint_spec/value range used by Gizwits boolean/numeric/enum types.
        """
        for spec in (attr, attr.get("uint_spec"), attr.get("value")):
            if isinstance(spec, dict):
                lo, hi = spec.get("min"), spec.get("max")
                if isinstance(lo, (int, float)) and isinstance(hi, (int, float)):
                    return float(lo), float(hi)
        return None

    @staticmethod
    def _scale(value: float, src: tuple[float, float], dst: tuple[float, float]) -> int:
        """Linearly rescale value from src range to dst range, clamped+rounded."""
        (slo, shi), (dlo, dhi) = src, dst
        if shi == slo:
            return int(round(dlo))
        frac = (float(value) - slo) / (shi - slo)
        frac = max(0.0, min(1.0, frac))
        return int(round(dlo + frac * (dhi - dlo)))

    def _color_field(self, index: dict[str, dict], *needles: str) -> str | None:
        """Find a datapoint whose name contains all `needles` (case-insensitive)."""
        for name, attr in index.items():
            if all(n in name for n in needles):
                return attr.get("name", name)
        return None

    def _map_attr(self, key: str, value: Any, index: dict[str, dict]) -> dict[str, Any]:
        """Map a single canonical attr onto the product's datapoint(s).

        Returns a dict (usually one entry) to merge into the outgoing attrs.
        Falls back to {key: value} whenever the mapping is not confident.
        """
        kl = key.lower()

        if kl == "hsv" and isinstance(value, dict):
            return self._map_hsv(value, index)

        # Scalar canonical attrs: onOff / lum / temperature.
        # Prefer an exact (case-insensitive) name match; otherwise pass through.
        target = None
        if key in index:
            target = key
        elif kl in index:
            target = index[kl].get("name", key)
        else:
            # Common alias hunting for renamed-but-recognizable datapoints.
            aliases = {
                "lum": ("lum", "bright"),
                "temperature": ("temp",),
                "onoff": ("onoff", "switch", "power"),
            }.get(kl, ())
            for needle in aliases:
                hit = self._color_field(index, needle)
                if hit:
                    target = hit
                    break
        if target is None:
            return {key: value}

        attr = index.get(target.lower(), {})
        dst = self._range_of(attr)
        canonical_src = {"lum": (1.0, 100.0), "temperature": (0.0, 100.0)}.get(kl)
        if (
            isinstance(value, (int, float))
            and dst is not None
            and canonical_src is not None
            and dst != canonical_src
        ):
            return {target: self._scale(value, canonical_src, dst)}
        return {target: value}

    def _map_hsv(self, hsv: dict, index: dict[str, dict]) -> dict[str, Any]:
        """Map a canonical {"h","s","v"} onto the product's color datapoint(s)."""
        h = hsv.get("h", 0)
        s = hsv.get("s", 0)
        v = hsv.get("v", 0)

        # 1) Single packed color datapoint (name contains hsv/color, or an
        #    object/json-typed datapoint): send {"h","s","v"} under its name.
        packed = self._color_field(index, "hsv") or self._color_field(index, "color")
        if packed is None:
            for name, attr in index.items():
                t = str(attr.get("type") or attr.get("data_type") or "").lower()
                if t in ("object", "json", "struct"):
                    packed = attr.get("name", name)
                    break
        # Only treat as packed if it is NOT one of the separate components.
        if packed is not None and not any(
            c in packed.lower() for c in ("_h", "_s", "_v")
        ) and packed.lower() not in ("h", "s", "v"):
            return {packed: {"h": int(h), "s": int(s), "v": int(v)}}

        # 2) Separate hue/saturation/value (or H/S/V, or color_h/_s/_v) fields.
        def find(*needle_sets: tuple[str, ...]) -> str | None:
            for needles in needle_sets:
                hit = self._color_field(index, *needles)
                if hit:
                    return hit
            return None

        h_dp = find(("hue",), ("color_h",), ("_h",)) or ("h" if "h" in index else None)
        s_dp = find(("saturation",), ("color_s",), ("_s",)) or ("s" if "s" in index else None)
        v_dp = find(("value",), ("color_v",), ("brightness_v",), ("_v",)) or ("v" if "v" in index else None)

        if h_dp and s_dp and v_dp:
            out: dict[str, Any] = {}
            for dp, comp, src in (
                (h_dp, h, (0.0, 360.0)),
                (s_dp, s, (0.0, 100.0)),
                (v_dp, v, (0.0, 100.0)),
            ):
                attr = index.get(dp.lower(), {})
                dst = self._range_of(attr)
                out[attr.get("name", dp)] = (
                    self._scale(comp, src, dst) if dst and dst != src else int(comp)
                )
            return out

        # 3) Nothing recognizable: pass the canonical hsv through unchanged.
        return {"hsv": {"h": int(h), "s": int(s), "v": int(v)}}

    # -- helpers -----------------------------------------------------------
    async def set_power(self, did: str, on: bool):
        return await self.control(did, {"onOff": 1 if on else 0})

    async def set_brightness(self, did: str, lum: int):
        return await self.control(did, {"lum": int(lum)})

    async def set_temperature(self, did: str, temperature: int):
        return await self.control(did, {"temperature": int(temperature)})

    async def set_hsv(self, did: str, h: int, s: int, v: int):
        # The app uses tinycolor HSV (h 0-360, s/v 0-100). Many Gizwits light
        # products pack this as a single object attr named "hsv"; some expose
        # separate H/S/V datapoints. We send the object form by default and
        # let discovery tell you if your product differs.
        return await self.control(did, {"hsv": {"h": int(h), "s": int(s), "v": int(v)}})

    # -- app-id probing ----------------------------------------------------
    @staticmethod
    async def probe_app_id(region: str = "cn", candidates: list[str] | None = None) -> list[str]:
        """Return the subset of candidate App-Ids that the cloud accepts.

        A valid Application-Id returns a token from POST /app/users; an invalid
        one returns an error envelope. Lets you find the live App-Id without
        guessing.
        """
        candidates = candidates or CANDIDATE_APP_IDS
        good: list[str] = []
        for app_id in candidates:
            c = GizwitsClient(app_id=app_id, region=region)
            try:
                data = await c.register_anonymous()
                if data.get("token"):
                    good.append(app_id)
            except Exception:
                pass
            finally:
                await c.aclose()
        return good

    # -- credential cache --------------------------------------------------
    def _save_creds(self) -> None:
        self._creds_path.parent.mkdir(parents=True, exist_ok=True)
        self._creds_path.write_text(json.dumps({
            "app_id": self.app_id, "region": self.region,
            "token": self.token, "uid": self.uid, "saved_at": int(time.time()),
        }, indent=2))

    def _load_creds(self) -> None:
        try:
            d = json.loads(self._creds_path.read_text())
            if d.get("region") == self.region and d.get("app_id") == self.app_id:
                self.token = d.get("token")
                self.uid = d.get("uid")
        except Exception:
            pass
