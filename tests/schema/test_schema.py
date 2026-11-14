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
