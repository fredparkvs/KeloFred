"""Reef spectral model: sun elevation -> per-channel coral-light intensities.

Builds on :mod:`keloray.solar` (real solar position) but, instead of a single
white-temperature value, produces a 7-channel spectral mix appropriate for a
reef. The physical motivation:

- Brightness follows the sun's elevation (same illuminance envelope as solar).
- Spectrum shifts with sun angle the way it does underwater: at low sun
  (dawn/dusk, shallow-angle light) warm wavelengths dominate -> more deep red
  and cool white; at high sun (midday, light penetrating deeper) water absorbs
  red and blue dominates -> royal/sky blue and UV peak, red fades. This mimics
  the blue-shifted light corals actually receive at depth.

Output is a dict ``{"onOff": .., "channels": {logical: 0..100, ...}}``; the
SceneRunner's ChannelMap turns the logical channels into the fixture's real
datapoints. ``caps`` (per-channel 0..100) lets you cap any channel for coral
acclimation; ``intensity_scale`` dims the whole fixture (e.g. wet season).
"""
from __future__ import annotations

from . import solar
from .channels import CORAL_CHANNELS


def _smooth(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return t * t * (3 - 2 * t)


def reef_channels(elev_deg: float, caps: dict | None = None,
                  intensity_scale: float = 1.0,
                  moonlight: float = 0.0) -> dict:
    """Spectral channel mix for a given solar elevation (degrees).

    caps: {logical: 0..100} per-channel maximum (acclimation), default 100.
    intensity_scale: overall multiplier (wet-season/cloud dimming).
    moonlight: faint blue level (0..100) to hold at night instead of full off.
    """
    caps = caps or {}

    def capped(ch: dict) -> dict:
        out = {}
        for k in CORAL_CHANNELS:
            cap = float(caps.get(k, 100.0))
            out[k] = int(round(max(0.0, min(100.0, ch.get(k, 0.0))) * cap / 100.0))
        return out

    # Night: optional faint blue "moonlight", otherwise off.
    if elev_deg <= -3.0:
        if moonlight > 0:
            night = {"rb": moonlight, "sb": moonlight * 0.6}
            return {"onOff": 1, "channels": capped(night)}
        return {"onOff": 0, "channels": capped({})}

    # Overall brightness envelope (0..1), reusing the researched lux model.
    intensity = solar.lux_to_lum(solar.lux_from_elevation(elev_deg)) / 100.0
    intensity *= max(0.0, intensity_scale)

    # Blue/depth shift: 0 at low sun -> 1 at high sun (saturating ~50 deg).
    b = _smooth(elev_deg / 50.0)

    raw = {
        "cw": intensity * (40 + 25 * (1 - b)),   # white: stronger at low/mid sun
        "rb": intensity * (40 + 60 * b),         # royal blue: peaks midday
        "sb": intensity * (30 + 50 * b),         # sky blue: peaks midday
        "uv1": intensity * (5 + 70 * b),         # UV: strongest at high sun
        "uv2": intensity * (5 + 65 * b),
        "dr": intensity * (10 + 75 * (1 - b)),   # deep red: strong at dawn/dusk
        "g": intensity * 25,                      # green: modest flat accent
    }
    return {"onOff": 1, "channels": capped(raw)}


def elevation_now(now, latitude_deg: float, longitude_deg: float,
                  utc_offset_hours: float) -> float:
    """Solar elevation (deg) for a datetime ``now`` at a location."""
    from datetime import date
    doy = date(now.year, now.month, now.day).timetuple().tm_yday
    hour_local = now.hour + now.minute / 60.0
    return solar.solar_elevation(doy, hour_local, latitude_deg,
                                 longitude_deg, utc_offset_hours)
