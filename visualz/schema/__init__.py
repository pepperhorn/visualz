"""Published JSON contracts; colours use #RRGGBB[AA] or @theme-name.

Channel indices are zero-based. Sizes/offsets are output pixels; times are seconds
unless named minutes. Partial objects are merged before validating the full state.
"""

import json
from copy import deepcopy
from importlib.resources import files

from jsonschema import Draft202012Validator

NAMES = ("settings", "scene", "overlay", "picture_set", "now_playing", "asset")
SCHEMAS = {
    name: json.loads(files(__package__).joinpath(f"{name}.json").read_text()) for name in NAMES
}


def defaults():
    """Return an independent first-run state."""
    return json.loads(files(__package__).joinpath("defaults.json").read_text())


def validate(name, value):
    """Raise ValueError with readable paths; return an independent valid value."""
    errors = sorted(
        Draft202012Validator(SCHEMAS[name]).iter_errors(value), key=lambda e: str(list(e.path))
    )
    if errors:
        raise ValueError(
            "; ".join(f"{name}.{'.'.join(map(str, e.path))}: {e.message}" for e in errors)
        )
    return deepcopy(value)
