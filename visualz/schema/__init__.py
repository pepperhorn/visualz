"""Published JSON contracts; colours use #RRGGBB[AA] or @theme-name.

Channel indices are zero-based. Sizes/offsets are output pixels; times are seconds
unless named minutes. Stage dimensions and modes.*.quality accept 'auto',
meaning use the resolved profile default from schema.profiles (unknown detection
falls back to low). State carries schema_version; schema.migrations runs on load.
Partial objects are merged before validating the full state.
"""

import json
from copy import deepcopy
from importlib.resources import files

from jsonschema import Draft202012Validator

NAMES = ("settings", "scene", "overlay", "picture_set", "now_playing", "asset", "logo_loop")
SCHEMAS = {
    name: json.loads(files(__package__).joinpath(f"{name}.json").read_text()) for name in NAMES
}

VALIDATORS = {name: Draft202012Validator(schema) for name, schema in SCHEMAS.items()}
_DEFAULTS = json.loads(files(__package__).joinpath("defaults.json").read_text())


def defaults():
    """Return an independent first-run state."""
    return deepcopy(_DEFAULTS)


def validate(name, value):
    """Raise ValueError with readable paths; return an independent valid value."""
    errors = sorted(VALIDATORS[name].iter_errors(value), key=lambda e: str(list(e.path)))
    if errors:
        raise ValueError(
            "; ".join(f"{name}.{'.'.join(map(str, e.path))}: {e.message}" for e in errors)
        )
    return deepcopy(value)
