"""Tropical sun tracker reference implementation (pure stdlib)."""
from __future__ import annotations
import math
from datetime import date

def _equation_of_time_minutes(day_of_year: int) -> float:
    gamma = 2.0 * math.pi / 365.0 * (day_of_year - 1)
    eot = 229.18 * (0.000075 + 0.001868 * math.cos(gamma) - 0.032077 * math.sin(gamma)
                    - 0.014615 * math.cos(2 * gamma) - 0.040849 * math.sin(2 * gamma))
    return eot

def _declination_deg(day_of_year: int) -> float:
    return -23.44 * math.cos(math.radians(360.0 / 365.0 * (day_of_year + 10)))

def solar_elevation(day_of_year: int, hour_local: float, latitude_deg: float,
                    longitude_deg: float, utc_offset_hours: float) -> float:
    decl = math.radians(_declination_deg(day_of_year))
    lat = math.radians(latitude_deg)
    eot = _equation_of_time_minutes(day_of_year)
    lstm = 15.0 * utc_offset_hours
    time_correction = 4.0 * (longitude_deg - lstm) + eot
    true_solar_time_min = hour_local * 60.0 + time_correction
    hour_angle = math.radians(true_solar_time_min / 4.0 - 180.0)
    sin_elev = (math.sin(lat) * math.sin(decl)
                + math.cos(lat) * math.cos(decl) * math.cos(hour_angle))
    sin_elev = max(-1.0, min(1.0, sin_elev))
    return math.degrees(math.asin(sin_elev))

def cct_from_elevation(elev_deg: float) -> float:
    if elev_deg <= -6.0:
        return 2000.0
    if elev_deg >= 25.0:
        t = min(1.0, (elev_deg - 25.0) / 35.0)
        return 5700.0 + t * (6500.0 - 5700.0)
    t = (elev_deg + 6.0) / 31.0
    t = max(0.0, min(1.0, t))
    eased = t * t * (3 - 2 * t)
    return 2000.0 + eased * (5700.0 - 2000.0)

def cct_to_temperature(cct_k: float) -> int:
    t = (cct_k - 2000.0) / (6500.0 - 2000.0)
    t = max(0.0, min(1.0, t))
    return int(round(t * 100))

def lux_from_elevation(elev_deg: float) -> float:
    if elev_deg <= -6.0:
        return 0.0
    if elev_deg <= 0.0:
        t = (elev_deg + 6.0) / 6.0
        return 400.0 * (t ** 2)
    s = math.sin(math.radians(elev_deg))
    return 128000.0 * (s ** 1.15)

def lux_to_lum(lux: float) -> int:
    if lux <= 1.0:
        return 1
    val = 20.0 * math.log10(lux)
    return max(1, min(100, int(round(val))))

DEFAULT_LAT = 1.35
DEFAULT_LON = 103.82
DEFAULT_UTC = 8.0

def sun_channels(dt_components, latitude_deg: float = DEFAULT_LAT,
                 longitude_deg: float = DEFAULT_LON, utc_offset_hours: float = DEFAULT_UTC,
                 lux_scale: float = 1.0, cct_bump_k: float = 0.0) -> dict:
    """dt_components: (year, month, day, hour, minute). Returns {onOff, lum, temperature[, hsv]}.
    lux_scale/cct_bump_k allow wet-season dimming/cooling adjustments."""
    year, month, day, hour, minute = dt_components
    doy = date(year, month, day).timetuple().tm_yday
    hour_local = hour + minute / 60.0
    elev = solar_elevation(doy, hour_local, latitude_deg, longitude_deg, utc_offset_hours)
    if elev <= -6.0:
        return {"onOff": 0, "lum": 1, "temperature": 0}
    lux = lux_from_elevation(elev) * lux_scale
    cct = cct_from_elevation(elev) + cct_bump_k
    out = {"onOff": 1, "lum": lux_to_lum(lux), "temperature": cct_to_temperature(cct)}
    if -6.0 < elev < 6.0:
        if elev >= 0.0:
            strength = int(round((1.0 - elev / 6.0) * 40))
            out["hsv"] = {"h": 30, "s": strength, "v": out["lum"]}
        else:
            strength = int(round((1.0 - (elev + 6.0) / 6.0) * 35))
            out["hsv"] = {"h": 220, "s": strength, "v": out["lum"]}
    return out
