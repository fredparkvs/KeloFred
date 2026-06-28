"""Tests for the spectral channel layer: ChannelMap, reef model, reef scenes,
and the SceneRunner's channels->attrs expansion. All offline."""
from keloray import reef
from keloray.channels import ChannelMap
from keloray.effects import SceneRunner, list_scenes


def test_channel_map_identity():
    m = ChannelMap()
    assert m.to_attrs({"cw": 50, "rb": 100}) == {"cw": 50, "rb": 100}
    assert not m.configured()


def test_channel_map_rename_and_scale():
    m = ChannelMap({
        "cw": "Cold_white",
        "rb": {"name": "Royal_blue", "hi": 1000},
        "uv1": {"name": "UV1", "lo": 0, "hi": 255},
    })
    out = m.to_attrs({"cw": 50, "rb": 100, "uv1": 100})
    assert out == {"Cold_white": 50, "Royal_blue": 1000, "UV1": 255}
    assert m.configured()


def test_channel_map_unknown_passthrough():
    m = ChannelMap()
    assert m.to_attrs({"mystery": 42}) == {"mystery": 42}


def test_reef_night_off():
    out = reef.reef_channels(-12.0)
    assert out["onOff"] == 0
    assert all(v == 0 for v in out["channels"].values())


def test_reef_night_moonlight():
    out = reef.reef_channels(-12.0, moonlight=20)
    assert out["onOff"] == 1
    assert out["channels"]["rb"] > 0


def test_reef_midday_is_blue_dominant():
    ch = reef.reef_channels(80.0)["channels"]
    assert ch["rb"] > ch["dr"]          # blue beats red at high sun
    assert ch["uv1"] > ch["dr"]


def test_reef_dawn_is_red_leaning():
    ch = reef.reef_channels(2.0)["channels"]
    assert ch["dr"] > ch["rb"]          # red beats blue at low sun


def test_reef_caps_limit_channel():
    full = reef.reef_channels(80.0)["channels"]
    capped = reef.reef_channels(80.0, caps={"rb": 50})["channels"]
    assert capped["rb"] <= full["rb"] // 2 + 1


def test_reef_scenes_registered():
    names = {s.name for s in list_scenes()}
    assert {"reef_day", "reef_storm"} <= names


def test_runner_expands_channels():
    runner = SceneRunner(client=None, channel_map=ChannelMap({
        "cw": "Cold_white", "rb": {"name": "Royal_blue", "hi": 1000}}))
    frame = {"onOff": 1, "channels": {"cw": 50, "rb": 100}}
    assert runner._expand(frame) == {"onOff": 1, "Cold_white": 50, "Royal_blue": 1000}
    # frames without channels are untouched
    assert runner._expand({"lum": 80}) == {"lum": 80}
