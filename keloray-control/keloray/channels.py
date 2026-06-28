"""Spectral channel mapping for multi-channel fixtures (e.g. coral lights).

The Keloray AL-series coral lights are NOT RGB bulbs — they expose several
independent LED intensity channels (cool white, royal blue, sky blue, UV1,
UV2, deep red, green). We address them with stable *logical* names and map
those to whatever the device's real Gizwits datapoints are called/scaled.

We don't know your fixture's exact datapoint names until you run
``python -m keloray discover <did>`` — so the map defaults to identity (logical
name == datapoint name) and is meant to be overridden from config once you see
the real schema. Scaling lets a logical 0..100 map onto a datapoint's real
range (e.g. 0..1000).

Logical channels (canonical order):
    cw  - cool white       rb  - royal blue      sb  - sky blue
    uv1 - ultraviolet 1    uv2 - ultraviolet 2   dr  - deep red
    g   - green
"""
from __future__ import annotations

from dataclasses import dataclass

# Canonical logical channels for a typical 7-channel reef fixture.
CORAL_CHANNELS = ["cw", "rb", "sb", "uv1", "uv2", "dr", "g"]

CHANNEL_LABELS = {
    "cw": "cool white", "rb": "royal blue", "sb": "sky blue",
    "uv1": "UV 1", "uv2": "UV 2", "dr": "deep red", "g": "green",
}


@dataclass
class ChannelSpec:
    """How one logical channel maps onto the device.

    ``name`` is the real datapoint key; logical 0..100 is scaled linearly onto
    ``lo``..``hi`` (the datapoint's real numeric range).
    """
    name: str
    lo: float = 0.0
    hi: float = 100.0

    def to_device(self, value: float) -> int:
        v = max(0.0, min(100.0, float(value)))
        return int(round(self.lo + (self.hi - self.lo) * (v / 100.0)))


class ChannelMap:
    """Maps logical channel dicts to device ``attrs`` dicts.

    Defaults to identity for the known coral channels. Override per fixture
    from config, e.g.::

        channels:
          cw:  {name: "Cold_white", hi: 1000}
          rb:  {name: "Royal_blue", hi: 1000}
          uv1: "UV1"                      # shorthand: just the datapoint name
    """

    def __init__(self, mapping: dict | None = None):
        self.specs: dict[str, ChannelSpec] = {
            k: ChannelSpec(name=k) for k in CORAL_CHANNELS
        }
        for logical, v in (mapping or {}).items():
            self.specs[logical] = self._coerce(logical, v)

    @staticmethod
    def _coerce(logical: str, v) -> ChannelSpec:
        if isinstance(v, ChannelSpec):
            return v
        if isinstance(v, str):
            return ChannelSpec(name=v)
        if isinstance(v, dict):
            return ChannelSpec(
                name=v.get("name", logical),
                lo=float(v.get("lo", v.get("min", 0.0))),
                hi=float(v.get("hi", v.get("max", 100.0))),
            )
        # unknown shape -> identity, don't crash
        return ChannelSpec(name=logical)

    def to_attrs(self, channels: dict[str, float]) -> dict:
        """Translate {logical: 0..100} -> {datapoint_name: scaled_int}.

        Unknown logical names pass through unchanged so raw datapoint writes
        still work."""
        out: dict = {}
        for logical, value in channels.items():
            spec = self.specs.get(logical)
            if spec is None:
                out[logical] = value
            else:
                out[spec.name] = spec.to_device(value)
        return out

    def configured(self) -> bool:
        """True if any channel was mapped away from its identity default."""
        return any(s.name != k or s.lo != 0.0 or s.hi != 100.0
                   for k, s in self.specs.items())
