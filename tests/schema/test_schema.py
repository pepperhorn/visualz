import pytest
from jsonschema import Draft202012Validator

from visualz.schema import SCHEMAS, defaults, validate


def test_defaults_and_contracts():
    for schema in SCHEMAS.values():
        Draft202012Validator.check_schema(schema)
    state = defaults()
    validate("settings", state["settings"])
    for template in state["overlays"].values():
        validate("overlay", template)


@pytest.mark.parametrize(
    "field,value",
    [
        ("audio", {"left_channel": -1}),
        ("look", {"style": "both"}),
        ("stage", {"render_width": 99999}),
    ],
)
def test_invalid_settings(field, value):
    state = defaults()["settings"]
    state[field].update(value)
    with pytest.raises(ValueError, match=field):
        validate("settings", state)


def test_invalid_overlay_readable():
    template = defaults()["overlays"]["lower-third"]
    template["texts"][0]["colour"] = "red"
    with pytest.raises(ValueError, match="texts.0.colour"):
        validate("overlay", template)


def test_s2_mode_maps_open_identifiers_and_hardware_profile():
    settings = defaults()["settings"]
    settings["mode"] = "future-mode"
    settings["modes"]["future-mode"] = {
        "params": {"iterations": 12, "curve": [1, 2, 3]},
        "quality": "high",
    }
    settings["hardware_profile"] = "low"
    settings["audio"].update(device="shared_capture", left_channel=63, right_channel=64)
    validate("settings", settings)
    scene = {
        "id": "future",
        "name": "Future",
        "mode": "future-mode",
        "modes": settings["modes"],
        "look": settings["look"],
    }
    validate("scene", scene)
    settings["modes"]["future-mode"]["quality"] = "bad"
    with pytest.raises(ValueError, match="quality"):
        validate("settings", settings)


def test_theme_and_palettes_are_hex_only():
    settings = defaults()["settings"]
    settings["theme"]["primary"] = "@primary"
    with pytest.raises(ValueError, match="primary"):
        validate("settings", settings)
    settings = defaults()["settings"]
    settings["palettes"]["neon"][0] = "@accent"
    with pytest.raises(ValueError, match="palettes"):
        validate("settings", settings)


def test_r2_2_profile_auto_and_full_hd_contract():
    from visualz.schema.profiles import profile_defaults, stage_size, resolve_profile

    settings = defaults()["settings"]
    assert all(value == "auto" for value in settings["stage"].values())
    assert all(value["quality"] == "auto" for value in settings["modes"].values())
    validate("settings", settings)
    settings["stage"].update(render_width=1920, render_height=1080)
    validate("settings", settings)
    assert profile_defaults("low", pi_model="pi2")["internal"] == (320, 180)
    assert profile_defaults("low")["internal"] == (480, 270)
    assert profile_defaults("low")["target_fps"] == 30
    assert profile_defaults("high", output=(1920, 1080))["internal"] == (1920, 1080)
    assert profile_defaults("high")["target_fps"] == 60
    assert resolve_profile("auto", None) == "low"
    assert resolve_profile("auto", "high") == "high"
    assert stage_size(settings, "high") == (1920, 1080)
