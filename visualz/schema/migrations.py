"""Ordered load-time migrations. Version 0 is the otherwise-current unversioned state.

Append future (from_version, callable) entries; each callable returns a new state.
Unknown newer versions are rejected and quarantined by Store, never overwritten.
"""

from copy import deepcopy

SCHEMA_VERSION = 1


def stamp_version(state):
    state["schema_version"] = 1
    return state


MIGRATIONS = {0: stamp_version}


def migrate(state):
    if not isinstance(state, dict):
        raise ValueError("State must be an object")
    result = deepcopy(state)
    version = result.get("schema_version", 0)
    if isinstance(version, bool) or not isinstance(version, int) or version < 0:
        raise ValueError("Invalid schema_version")
    if version > SCHEMA_VERSION:
        raise ValueError(f"Newer schema_version {version}; supported {SCHEMA_VERSION}")
    while version < SCHEMA_VERSION:
        result = MIGRATIONS[version](result)
        next_version = result.get("schema_version")
        if next_version != version + 1:
            raise ValueError("Migration must advance exactly one version")
        version = next_version
    return result
