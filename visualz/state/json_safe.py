"""Defensive JSON boundary for volatile worker values; no NumPy dependency."""

import logging
import math
from threading import RLock


class JsonCoercer:
    def __init__(self):
        self._warned = set()
        self._lock = RLock()

    def _string(self, value, key):
        with self._lock:
            if key not in self._warned:
                self._warned.add(key)
                logging.warning("Coercing non-JSON value at %s (%s)", key, type(value).__name__)
        try:
            return str(value)
        except Exception:
            return f"<{type(value).__module__}.{type(value).__name__}>"

    def __call__(self, value, key="status", _seen=None):
        seen = set() if _seen is None else _seen
        if value is None or isinstance(value, (str, bool, int)):
            return value
        if isinstance(value, float):
            return float(value) if math.isfinite(value) else None
        if id(value) in seen:
            return self._string(value, key)
        seen.add(id(value))
        try:
            if isinstance(value, dict):
                result = {}
                for k, v in value.items():
                    name = (
                        str(k)
                        if isinstance(k, (str, int, float, bool)) or k is None
                        else self._string(k, key + ".<key>")
                    )
                    result[name] = self(v, f"{key}.{name}", seen)
                return result
            if isinstance(value, (list, tuple, set, frozenset)):
                return [self(v, f"{key}[]", seen) for v in value]
            if type(value).__module__.split(".")[0] == "numpy":
                try:
                    converted = value.tolist() if hasattr(value, "tolist") else value.item()
                    # longdouble.item()/tolist() may return another NumPy scalar.
                    if type(converted).__module__.split(".")[0] == "numpy":
                        kind = getattr(getattr(converted, "dtype", None), "kind", None)
                        if kind in ("f", "b", "i", "u"):
                            converted = (
                                bool(converted)
                                if kind == "b"
                                else (int(converted) if kind in ("i", "u") else float(converted))
                            )
                        else:
                            return self._string(converted, key)
                    return self(converted, key, seen)
                except Exception:
                    pass
            return self._string(value, key)
        finally:
            seen.remove(id(value))
