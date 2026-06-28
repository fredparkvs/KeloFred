# Keloray Control

A programmable controller for **Keloray smart lights** (and other
**Gizwits**-based devices), giving you custom scenes, effects, schedules, and a
REST API + web dashboard — well beyond what the stock app exposes.

It talks to the **same Gizwits OpenAPI** the official app uses, so it controls
**your own devices on your own account**. No firmware mods, no cloud bypass —
just a richer client. Reverse-engineered for personal interoperability.

> Heads-up: this depends on Gizwits' cloud and on the app's public
> `Application-Id` staying valid. If Gizwits changes either, calls may need
> updating. A fully-offline (local BLE) path is possible but is a separate,
> larger project.

## How it works

The Keloray app is a Gizwits white-label IoT app. Devices are controlled by
writing **datapoints** (`attrs`) through the cloud:

| attr | meaning | typical range |
|------|---------|---------------|
| `onOff` | power | 0 / 1 |
| `lum` | brightness | 1–100 |
| `temperature` | white color temp | 0–100 |
| `hsv` | color | `{h:0–360, s:0–100, v:0–100}` |
| `mode` / `scene` | device presets | per product |

The exact set and ranges for *your* light are discovered live via
`datapoints(product_key)` and `state(did)` — don't assume, query.

## Install

```bash
cd keloray-control
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt        # or: pip install -e .
```

## Configure

1. **Find the live App-Id** (the app ships a few; one is active per region):
   ```bash
   python -m keloray --region cn probe        # try us / eu if none match
   export KELORAY_APP_ID=<the value it prints>
   ```
2. **Provide your app login:**
   ```bash
   export KELORAY_USERNAME='you@example.com'
   export KELORAY_PASSWORD='...'
   python -m keloray login                     # caches a token
   ```
   (Or copy `config.example.yaml` → `config.yaml` and
   `export KELORAY_CONFIG=./config.yaml`.)

## Use it

```bash
python -m keloray devices                       # list your lights -> get a <did>
python -m keloray state <did>                    # current attrs
python -m keloray datapoints <product_key>       # what this product supports

# raw datapoint writes
python -m keloray set <did> onOff=1 lum=80 temperature=20
python -m keloray set <did> hsv='{"h":280,"s":100,"v":100}'

# run a live effect (Ctrl-C to stop)
python -m keloray scene <did> sunrise seconds=600
python -m keloray scene <did> color_loop period=20
python -m keloray scenes                          # list effects + their options
```

## Scenes / effects

| name | what it does | key params |
|------|--------------|-----------|
| `solid` | one fixed state | `lum, on, temperature, hsv` |
| `fade` | smooth brightness ramp | `start, end, seconds` |
| `sunrise` | dawn: brightness + temp ramp up | `seconds, warm, cool` |
| `sunset` | dusk: dim to warm, then off | `seconds, warm, cool` |
| `color_loop` | endless hue cycle | `period, saturation, value` |
| `breathe` | sinusoidal brightness pulse | `low, high, period` |
| `candle` | warm flicker | `base, jitter` |
| `thunderstorm` | dim blue overcast + random lightning flashes | `base_lum, flash_lum, min_gap, max_gap, double_flash_chance, seed` |
| `tropics` | tracks real tropical daylight all day (see below) | `latitude, longitude, utc_offset, tick, wet_season, wet_months` |
| `reef_day` | **coral fixtures:** tropical reef sun as a 7-channel spectral mix (see below) | `latitude, longitude, utc_offset, tick, wet_season, caps, moonlight` |
| `reef_storm` | **coral fixtures:** dim blue/white overcast + lightning on the white channels | `base, flash, min_gap, max_gap, double_flash_chance, seed` |

`solid…tropics` drive RGB/white bulbs (`lum`/`hsv`/`temperature`); `reef_*`
drive multi-channel spectral fixtures (`channels`). Effects are tiny async
generators in `keloray/effects.py` — add your own with the `@scene(...)`
decorator and it shows up everywhere (CLI, API, scheduler).

### Tropical sun tracker (`tropics`)

Mirrors real tropical daylight: warm dim dawn → bright cool midday → warm dusk
→ off at night, computed live from solar position (`keloray/solar.py`, derived
from the NOAA solar-position equations + daylight CCT/illuminance curves; full
write-up and citations in `../research/tropical-sunlight.md`). It samples the
clock every `tick` seconds (default 60) and re-aims the channels.

```bash
# default ~Singapore; override for your latitude/longitude/timezone
python -m keloray scene <did> tropics latitude=1.35 longitude=103.82 utc_offset=8
python -m keloray scene <did> tropics wet_season=true   # monsoon dimming/cooling
```

Seasonality: near the equator daylight barely changes month-to-month (two
near-zenith noons around the equinoxes), so the dominant seasonal lever is
monsoon cloudiness — enable `wet_season` (optionally tune `wet_months`) to dim
brightness ~40% and shift cooler in those months.

> `thunderstorm` flashes and `tropics` are written through the cloud, which
> rate-limits and adds latency — so lightning is approximate (no true
> sub-100ms strobe). Crisp strobe needs the local/BLE path.

## Coral / spectral fixtures (e.g. Keloray AL-series)

The AL-series coral lights aren't RGB bulbs — they expose **seven independent
LED channels** (cool white, royal blue, sky blue, UV1, UV2, deep red, green).
This controller addresses them with stable *logical* names (`cw, rb, sb, uv1,
uv2, dr, g`) and maps those to your fixture's real Gizwits datapoints.

**Step 1 — learn your fixture's real channels:**

```bash
python -m keloray discover <did>     # dumps the datapoint schema + current values
```

**Step 2 — map them** in `config.yaml` under `channels:` (datapoint name + range
per logical channel; see `config.example.yaml`). Until you do, the map is
identity and the logical names are sent verbatim — which probably won't match,
so this step is required for `reef_*` scenes to work on your light.

**Step 3 — run a reef scene:**

```bash
python -m keloray scene <did> reef_day latitude=1.35 longitude=103.82 utc_offset=8
python -m keloray scene <did> reef_day caps='{"uv1":60,"uv2":60}' moonlight=8
python -m keloray scene <did> reef_storm
```

`reef_day` mirrors a tropical reef day across the spectrum (`keloray/reef.py`):
**red-leaning dawn → blue/UV-dominant midday** (mimicking sunlight filtered
through water, where red is absorbed and blue penetrates deepest) **→ warm dusk
→ off** (or faint blue `moonlight`) at night, tracking the real clock and date
so the mix also shifts across the year. `caps` lets you ceiling any channel for
coral acclimation; `wet_season` dims for monsoon months. The REST API exposes
the same via `GET /api/devices/{did}/discover` and the `reef_*` scenes.

> Reality check: the exact datapoint names/ranges for the AL100 aren't in the
> app (the product catalog is server-side), so the channel map **must** be
> confirmed with `discover` against your account before `reef_*` will drive the
> right LEDs.

### Robustness

Color/temperature/brightness writes are **normalized to your product's actual
datapoint schema** (discovered via `datapoints()`), so `hsv` maps correctly
whether your light uses one packed color datapoint or separate H/S/V channels —
falling back to pass-through if the schema is unknown. Running effects also
**survive transient cloud errors**: each write retries with backoff and logs
instead of silently killing the scene.

## REST API + dashboard

```bash
python -m keloray serve            # http://127.0.0.1:8000  (dashboard at /)
```

Key endpoints (full list in `keloray/server.py`):

```
GET  /api/devices
GET  /api/devices/{did}
POST /api/devices/{did}/control     {"attrs": {"lum": 60}}
POST /api/devices/{did}/power       {"on": true}
POST /api/devices/{did}/scene       {"scene": "sunrise", "params": {"seconds": 900}}
POST /api/devices/{did}/scene/stop
GET  /api/scenes
GET/POST/DELETE /api/schedules
```

The dashboard gives you power, brightness/temp sliders, a color picker, and
one-click scenes per device.

## Automations / schedules

Define rules in your config (`rules:`) or POST them at runtime:

```yaml
rules:
  - name: "weekday wake-up"
    did: "<device id>"
    scene: "sunrise"
    params: { seconds: 1200 }
    cron: { hour: 6, minute: 30, day_of_week: "mon-fri" }
```

## Rate limits & safety

Gizwits rate-limits per device; the effects engine spaces writes by
`min_interval` (default 0.25s). If you see `502` errors with a rate-limit body,
raise it. Manual control (`/control`, `/power`) cancels any running scene on
that device so you never fight an effect loop.

## Tests

```bash
pip install pytest
pytest -q        # offline; mocks the Gizwits HTTP layer
```

## Layout

```
keloray/
  client.py      Gizwits OpenAPI client (auth, bindings, control, discovery)
  effects.py     scene/effect engine + runner (rate-limited)
  scheduler.py   APScheduler automations
  server.py      FastAPI REST API + dashboard
  config.py      env + YAML config
  __main__.py    CLI
web/index.html   dashboard
examples/        quickstart
tests/           offline tests
```
