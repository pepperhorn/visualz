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
