"""Defensive JSON boundary for volatile worker values; no NumPy dependency."""

import logging
import math
from collections.abc import Sized
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

    def _check_size(self, value, key, remaining, seen):
        """Bound aggregate container slots/bytes before allocating conversions."""
        if id(value) in seen:
            return
        seen.add(id(value))
        try:
            if isinstance(value, dict):
                remaining[0] -= 2 * len(value)
                children = (child for pair in value.items() for child in pair)
            elif isinstance(value, (list, tuple, set, frozenset)):
                remaining[0] -= len(value)
                children = iter(value)
            elif type(value).__module__.split(".")[0] == "numpy":
                remaining[0] -= int(getattr(value, "size", 1))
                # Object arrays can themselves contain sequences or arrays.
                children = (
                    iter(value.flat)
                    if getattr(getattr(value, "dtype", None), "hasobject", False)
                    and hasattr(value, "flat")
                    else ()
                )
            elif isinstance(value, Sized) and not isinstance(value, str):
                remaining[0] -= value.nbytes if isinstance(value, memoryview) else len(value)
                children = ()
            else:
                return
            if remaining[0] < 0:
                raise ValueError(f"{key}: total size exceeds the {remaining[1]} element status limit")
            for child in children:
                self._check_size(child, key, remaining, seen)
        finally:
            seen.remove(id(value))

    def __call__(self, value, key="status", _seen=None, *, max_elements=None):
        # Opt-in at publication only: defensive send-time coercion stays tolerant.
        if max_elements is not None:
            self._check_size(value, key, [max_elements, max_elements], set())
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
