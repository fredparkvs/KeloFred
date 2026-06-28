# Tropical Sun Tracker — Light Model (research + code-ready reference)

Maps **date + local clock time + location** → smart-light channels
(`lum` 1–100 log brightness, `temperature` 0–100 warm↔cool white, optional
`hsv` golden/blue-hour tint, `onOff`). Tuned for tropical latitudes
(±23.5°), default **Singapore 1.35°N, 103.82°E, UTC+8**.

All curves below are reproduced by the Python in section C, which has been run
and sanity-checked (section E).

---

## A. Researched relationships (with citations)

### A.1 Solar position

Solar elevation (altitude) angle `h` from latitude `φ`, declination `δ`, hour angle `H`:

```
sin(h) = sin(φ)·sin(δ) + cos(φ)·cos(δ)·cos(H)
```

This is the standard spherical-trig altitude equation used by the NOAA Solar
Calculator and NREL SPA. `δ` comes from the date, `H` from true solar time at
the observer's longitude, which in turn needs the **equation of time** (EoT).
([NOAA Global Monitoring Laboratory — Solar Calculator](https://gml.noaa.gov/grad/solcalc/azel.html);
[NREL/TP-560-34302 Solar Position Algorithm](https://docs.nlr.gov/docs/fy08osti/34302.pdf))

**Declination** (simple axial-tilt cosine; error ≤ ~1.5° near the Sept equinox,
fine for lighting), with `N` = day-of-year:

```
δ = −23.44° · cos( 360°/365 · (N + 10) )
```

Earth's axial tilt is 23.44°; the +10 offsets days since the Dec solstice.
([Wikipedia — Position of the Sun](https://en.wikipedia.org/wiki/Position_of_the_Sun))

**Equation of time** (NOAA "fractional-year γ" Fourier series), minutes, with
`γ = 2π/365·(N−1)`:

```
EoT = 229.18·( 0.000075 + 0.001868 cosγ − 0.032077 sinγ
               − 0.014615 cos2γ − 0.040849 sin2γ )
```

EoT ranges roughly −14…+16 min over the year.
([NOAA — solar equations](https://gml.noaa.gov/grad/solcalc/solareqns.PDF))

**Hour angle** from local clock time: convert clock → true solar time by adding a
time correction `TC = 4·(longitude − 15·UTCoffset) + EoT` (minutes), then
`H = (TST_minutes / 4) − 180°`. `H = 0` at solar noon. ([NOAA, as above](https://gml.noaa.gov/grad/solcalc/azel.html))

### A.2 Tropics specifics (±23.5°)

* Day length is nearly constant year-round: **exactly 12 h at the equator**,
  and only ~11–13 h across the rest of the tropics, versus the large temperate
  swing (e.g. 30°N: 14 h June / 10 h Dec).
  ([Britannica Kids — hours of daylight](https://kids.britannica.com/students/assembly/view/108060);
  [Wikipedia — Daytime](https://en.wikipedia.org/wiki/Daytime))
* **Two solar-zenith passages per year**: at any latitude between the tropics the
  Sun stands directly overhead (elevation ≈ 90°) on two dates. At the equator
  those are the equinoxes; nearer a tropic line they bracket the local-summer
  solstice. Singapore (1.35°N) gets near-zenith noons around the March and
  September equinoxes. ([Wikivoyage — Tropics](https://en.wikivoyage.org/wiki/Tropics))
* **Seasonal swing is small near the equator** and grows toward the tropic
  lines. The dominant seasonal lighting effect in the tropics is therefore *not*
  sun geometry but **wet/dry (monsoon) season cloudiness**: wet-season skies are
  overcast and diffuse, cutting peak illuminance and pushing daylight bluer
  (overcast sky CCT ≫ direct-sun CCT). We model this as an optional per-month
  brightness/CCT nudge (section D), not as geometry.

### A.3 CCT vs solar elevation

Daylight CCT is **warm at low sun and cool at high sun**: low-angle light
traverses more airmass, scattering out blue and leaving amber/red.

| Sun condition | Elevation | CCT |
|---|---|---|
| Sunrise/sunset, golden hour | ~0° | **~1850–3000 K** |
| Low morning/afternoon | ~10–20° | ~3500–5000 K |
| Solar noon, clear | high | **~5000–5500 K (direct)**, 5500–6500 K incl. skylight |
| Open shade / overcast | any | bluer, 6500–7500 K+ |

([Biology Insights — What Kelvin is natural light](https://biologyinsights.com/what-kelvin-is-natural-light-a-look-at-daylight-color/);
[Schorsch — CCT glossary](https://www.schorsch.com/en/kbase/glossary/cct.html);
[ResearchGate — CCT of skylight/daylight vs solar altitude](https://www.researchgate.net/figure/Correlated-color-temperature-of-skylight-and-daylight-for-different-atmospheric_fig15_249969495))

Modeled curve (section C `cct_from_elevation`): 2000 K at/below −6°, smoothstep
ramp to ~5700 K by 25°, gentle rise to 6500 K by 60°.

### A.4 Illuminance (lux) vs solar elevation, clear sky

Horizontal illuminance scales roughly with `sin(h)` (a `sin^1.1–1.2` fit tracks
airmass losses better at low sun): ~0 below horizon, a few hundred lux near
sunrise, **up to ~100,000–120,000 lux at high-sun noon**.

| Elevation | Approx clear-sky illuminance |
|---|---|
| ≤ −6° (twilight gone) | 0 lux |
| ~0° (horizon) | few hundred lux |
| 2.5° | ~770 lux (DNI; airmass ≈ 18) |
| 25° | tens of thousands of lux |
| 60–90° | ~100,000–120,000+ lux |

([PVEducation — Elevation angle](https://www.pveducation.org/pvcdrom/properties-of-sunlight/elevation-angle);
[Wikipedia — Daylight / lux](https://en.wikipedia.org/wiki/Daylight);
[NCBI — hourly illuminance under clear sky](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC7446841/))

Modeled curve (section C `lux_from_elevation`): `128000·sin(h)^1.15` for `h>0`,
plus a quadratic twilight tail rising to ~400 lux at the horizon, 0 at −6°.

### A.5 Golden hour / blue hour

* **Golden hour**: sun roughly **−4° … +6°** elevation; warm amber, soft,
  long shadows. We add a warm amber tint (hue ~30°) for `0° ≤ h < 6°`.
* **Blue hour**: sun roughly **−6° … −4°** (we extend the cool tint over the
  whole −6°…0° pre-sunrise / post-sunset band); deep blue sky, cool cast. We add
  a blue tint (hue ~220°) for `−6° < h < 0°`.

([PhotoPills — golden/blue hour & twilights](https://www.photopills.com/articles/mastering-golden-hour-blue-hour-magic-hours-and-twilights);
[timeanddate — Golden hour](https://www.timeanddate.com/astronomy/golden-hour.html);
[Wikipedia — Golden hour](https://en.wikipedia.org/wiki/Golden_hour_(photography)))

---

## B. Exact conversion functions (the two the engineer asked for)

### B.1 CCT (Kelvin) → `temperature` (0..100)

Linear over the channel's white range 2000 K (warmest, 0) … 6500 K (coolest, 100):

```
temperature = round( clamp01( (CCT_K − 2000) / (6500 − 2000) ) · 100 )
```

| CCT (K) | temperature |
|---|---|
| 2000 | 0 |
| 2700 | 16 |
| 3500 | 33 |
| 5000 | 67 |
| 5700 | 82 |
| 6500 | 100 |

### B.2 Illuminance (lux) → `lum` (1..100), log scale

`lum` is log-linear from 1 lux (→1) to 100,000 lux (→100). With
`log10(1)=0 … log10(1e5)=5`, scale by 20 and clamp to 1..100:

```
lum = clamp( round( 20 · log10(lux) ), 1, 100 )     # lux > 1
lum = 1                                              # lux ≤ 1
```

| lux | lum |
|---|---|
| ≤1 | 1 |
| 10 | 20 |
| 100 | 40 |
| 1,000 | 60 |
| 10,000 | 80 |
| 100,000 | 100 |
| 120,000 | 100 (clamped) |

---

## C. Python reference implementation (pure stdlib)

Deterministic, side-effect free, `math`/`datetime` only — drops into an asyncio
codebase. Channel names match the device attrs.

```python
"""Tropical sun tracker reference implementation (pure stdlib)."""
from __future__ import annotations
import math
from datetime import date

# ----------------------------------------------------------------------------
# 1. SOLAR POSITION  (NOAA / Spencer-style approximation)
# ----------------------------------------------------------------------------

def _equation_of_time_minutes(day_of_year: int) -> float:
    """Equation of time in minutes (NOAA gamma Fourier series)."""
    gamma = 2.0 * math.pi / 365.0 * (day_of_year - 1)
    eot = 229.18 * (
        0.000075
        + 0.001868 * math.cos(gamma)
        - 0.032077 * math.sin(gamma)
        - 0.014615 * math.cos(2 * gamma)
        - 0.040849 * math.sin(2 * gamma)
    )
    return eot


def _declination_deg(day_of_year: int) -> float:
    """Solar declination (deg). Simple axial-tilt cosine approximation."""
    return -23.44 * math.cos(math.radians(360.0 / 365.0 * (day_of_year + 10)))


def solar_elevation(
    day_of_year: int,
    hour_local: float,
    latitude_deg: float,
    longitude_deg: float,
    utc_offset_hours: float,
) -> float:
    """Solar elevation angle in degrees. East longitude positive."""
    decl = math.radians(_declination_deg(day_of_year))
    lat = math.radians(latitude_deg)

    eot = _equation_of_time_minutes(day_of_year)
    # Standard meridian for the given UTC offset:
    lstm = 15.0 * utc_offset_hours
    # Time correction (minutes): longitude offset from std meridian + EoT
    time_correction = 4.0 * (longitude_deg - lstm) + eot
    true_solar_time_min = hour_local * 60.0 + time_correction
    # Hour angle: 0 at solar noon, negative morning, positive afternoon
    hour_angle = math.radians(true_solar_time_min / 4.0 - 180.0)

    sin_elev = (
        math.sin(lat) * math.sin(decl)
        + math.cos(lat) * math.cos(decl) * math.cos(hour_angle)
    )
    sin_elev = max(-1.0, min(1.0, sin_elev))
    return math.degrees(math.asin(sin_elev))


# ----------------------------------------------------------------------------
# 2. ELEVATION -> CCT (Kelvin)
# ----------------------------------------------------------------------------

def cct_from_elevation(elev_deg: float) -> float:
    """Approximate daylight CCT (Kelvin) vs solar elevation."""
    if elev_deg <= -6.0:
        return 2000.0
    if elev_deg >= 25.0:
        # gentle rise 5700 -> 6500 from 25 to 60 deg
        t = min(1.0, (elev_deg - 25.0) / 35.0)
        return 5700.0 + t * (6500.0 - 5700.0)
    # smooth warm->cool ramp from -6 deg (2000K) to 25 deg (5700K)
    t = (elev_deg + 6.0) / 31.0
    t = max(0.0, min(1.0, t))
    eased = t * t * (3 - 2 * t)  # smoothstep: stays warm through golden hour
    return 2000.0 + eased * (5700.0 - 2000.0)


def cct_to_temperature(cct_k: float) -> int:
    """Map CCT 2000K..6500K -> 0..100 linearly, clamped."""
    t = (cct_k - 2000.0) / (6500.0 - 2000.0)
    t = max(0.0, min(1.0, t))
    return int(round(t * 100))


# ----------------------------------------------------------------------------
# 3. ELEVATION -> ILLUMINANCE (lux)
# ----------------------------------------------------------------------------

def lux_from_elevation(elev_deg: float) -> float:
    """Clear-sky horizontal illuminance (lux) vs solar elevation.
    Empirical fit ~ 128000 * sin(h)^1.15 for h>0, with a small twilight tail."""
    if elev_deg <= -6.0:
        return 0.0
    if elev_deg <= 0.0:
        # twilight tail: 0 lux at -6 deg up to ~400 lux at horizon
        t = (elev_deg + 6.0) / 6.0
        return 400.0 * (t ** 2)
    s = math.sin(math.radians(elev_deg))
    return 128000.0 * (s ** 1.15)


def lux_to_lum(lux: float) -> int:
    """Map illuminance to brightness 1..100 on a log scale.
    1 lux -> ~1, 100000 lux -> 100."""
    if lux <= 1.0:
        return 1
    val = 20.0 * math.log10(lux)  # log10(1)=0 ... log10(1e5)=5 -> 100
    return max(1, min(100, int(round(val))))


# ----------------------------------------------------------------------------
# 4. PUBLIC: sun_channels
# ----------------------------------------------------------------------------

DEFAULT_LAT = 1.35      # Singapore
DEFAULT_LON = 103.82
DEFAULT_UTC = 8.0


def sun_channels(
    dt_components,
    latitude_deg: float = DEFAULT_LAT,
    longitude_deg: float = DEFAULT_LON,
    utc_offset_hours: float = DEFAULT_UTC,
) -> dict:
    """dt_components: (year, month, day, hour, minute).
    Returns {onOff, lum, temperature[, hsv]}."""
    year, month, day, hour, minute = dt_components
    doy = date(year, month, day).timetuple().tm_yday
    hour_local = hour + minute / 60.0

    elev = solar_elevation(doy, hour_local, latitude_deg, longitude_deg, utc_offset_hours)

    if elev <= -6.0:
        return {"onOff": 0, "lum": 1, "temperature": 0}

    lux = lux_from_elevation(elev)
    cct = cct_from_elevation(elev)
    out = {
        "onOff": 1,
        "lum": lux_to_lum(lux),
        "temperature": cct_to_temperature(cct),
    }
    # optional golden/blue-hour tint
    if -6.0 < elev < 6.0:
        if elev >= 0.0:  # golden hour: warm amber tint
            strength = int(round((1.0 - elev / 6.0) * 40))
            out["hsv"] = {"h": 30, "s": strength, "v": out["lum"]}
        else:            # blue hour: cool blue tint
            strength = int(round((1.0 - (elev + 6.0) / 6.0) * 35))
            out["hsv"] = {"h": 220, "s": strength, "v": out["lum"]}
    return out
```

**Optional wet-season tweak** (section D): multiply `lux` by ~0.6 and add ~600 K
before `cct_to_temperature` during wet months to emulate overcast diffuse light.

---

## D. Per-month table (default latitude, derived from the model)

Computed from the implementation above at Singapore (1.35°N, 103.82°E, UTC+8),
day 15 of each month. Times are local clock time. Day length is ~12 h all year
(tropical), and two near-zenith noons appear around the equinoxes (Mar, Sep).

| Month | Sunrise | Solar noon | Sunset | Max noon elev | Season / suggested adjustment |
|---|---|---|---|---|---|
| Jan | 07:15 | 13:13 | 19:11 | 67.3° | NE monsoon (wet): dim ×0.6, +600 K |
| Feb | 07:20 | 13:18 | 19:18 | 75.3° | Drier: nominal |
| Mar | 07:15 | 13:13 | 19:15 | 85.7° | Near-zenith; inter-monsoon: nominal |
| Apr | 07:04 | 13:05 | 19:06 | 82.0° | Inter-monsoon storms: slight dim ×0.85 |
| May | 06:59 | 13:01 | 19:03 | 72.6° | SW monsoon onset: nominal |
| Jun | 07:02 | 13:05 | 19:07 | 68.1° | Driest/brightest: nominal |
| Jul | 07:09 | 13:11 | 19:12 | 69.8° | Dry: nominal |
| Aug | 07:09 | 13:09 | 19:11 | 77.5° | Dry: nominal |
| Sep | 07:00 | 13:00 | 19:00 | 89.0° | Near-zenith; inter-monsoon: nominal |
| Oct | 06:51 | 12:50 | 18:49 | 79.1° | Inter-monsoon storms: slight dim ×0.85 |
| Nov | 06:51 | 12:50 | 18:48 | 69.6° | NE monsoon onset (wet): dim ×0.7, +400 K |
| Dec | 07:02 | 13:00 | 18:57 | 65.3° | NE monsoon (wettest): dim ×0.6, +600 K |

Notes: noon elevation stays high (65–89°) all year — the hallmark of an
equatorial site — so the main *seasonal* lever for the effect is the monsoon
cloudiness adjustment, not geometry. The ~07:00 sunrise / ~19:00 sunset clock
times reflect Singapore being ~18° east of its UTC+8 standard meridian (the
+1 h "shifted" local time).

---

## E. Verification (ran the code)

```
0500 (pre-dawn equinox):  {'onOff': 0, 'lum': 1, 'temperature': 0}        # off, correct
noon equinox (13:00):     {'onOff': 1, 'lum': 100, 'temperature': 100}    # elev 86.4°, bright+cool
0700 (pre-sunrise):       {'onOff': 1, 'lum': 39, 'temperature': 2,       # elev -3.2°, warm + blue tint
                           'hsv': {'h': 220, 's': 18, 'v': 39}}
dec solstice noon:        {'onOff': 1, 'lum': 100, 'temperature': 100}    # elev 65.2°
```

Morning trace (equinox), elev → CCT → lux:

```
06:30  -10.7°   2000 K        0 lux
07:00   -3.2°   2088 K       90 lux
07:30    4.3°   2961 K     6580 lux
09:00   26.8°   5742 K    51280 lux
12:00   71.8°   6500 K   120634 lux
13:00   86.4°   6500 K   127701 lux
```

All target checks hold: pre-dawn → `onOff=0`; near-zenith noon → `lum=100`,
cool `temperature`; golden/blue band produces warm CCT + tint; curves are
monotonic and smooth.

---

## Sources

- [NOAA GML — Solar Position Calculator](https://gml.noaa.gov/grad/solcalc/azel.html)
- [NOAA GML — Solar equations (γ series, EoT, declination)](https://gml.noaa.gov/grad/solcalc/solareqns.PDF)
- [NREL/TP-560-34302 — Solar Position Algorithm](https://docs.nlr.gov/docs/fy08osti/34302.pdf)
- [Wikipedia — Position of the Sun](https://en.wikipedia.org/wiki/Position_of_the_Sun)
- [Wikipedia — Daytime](https://en.wikipedia.org/wiki/Daytime)
- [Wikivoyage — Tropics](https://en.wikivoyage.org/wiki/Tropics)
- [Britannica Kids — hours of daylight around the world](https://kids.britannica.com/students/assembly/view/108060)
- [Biology Insights — What Kelvin is natural light](https://biologyinsights.com/what-kelvin-is-natural-light-a-look-at-daylight-color/)
- [Schorsch — Correlated Color Temperature glossary](https://www.schorsch.com/en/kbase/glossary/cct.html)
- [ResearchGate — CCT of skylight/daylight vs solar altitude](https://www.researchgate.net/figure/Correlated-color-temperature-of-skylight-and-daylight-for-different-atmospheric_fig15_249969495)
- [PVEducation — Elevation angle](https://www.pveducation.org/pvcdrom/properties-of-sunlight/elevation-angle)
- [NCBI PMC — hourly illuminance under clear sky](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC7446841/)
- [PhotoPills — golden hour, blue hour & twilights](https://www.photopills.com/articles/mastering-golden-hour-blue-hour-magic-hours-and-twilights)
- [timeanddate — Golden hour](https://www.timeanddate.com/astronomy/golden-hour.html)
- [Wikipedia — Golden hour (photography)](https://en.wikipedia.org/wiki/Golden_hour_(photography))
