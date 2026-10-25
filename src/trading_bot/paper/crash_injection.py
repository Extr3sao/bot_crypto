"""Deterministic crash points for PAPER durability evidence (G-6).

The production runtime must not crash on its own.  These hooks are inert
unless ``PAPER_CRASH_POINT`` names the point being crossed.  When it does,
the process writes a small marker with fsync and then parks forever; the
parent harness terminates it with a real forced kill (``taskkill /F`` on
Windows, ``SIGKILL`` elsewhere).  Parking instead of calling ``os._exit`` is
deliberate: the parent can prove the child was alive at the boundary and that
the termination came from outside the process, exactly like an operator or
the operating system killing it.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

__all__ = ["crash_point", "enabled_point"]


def enabled_point() -> str:
    return os.environ.get("PAPER_CRASH_POINT", "").strip()


def crash_point(name: str, **details: Any) -> None:
    """Park the process at ``name`` when the harness selected that point."""
    if enabled_point() != name:
        return
    marker = Path(os.environ.get("PAPER_CRASH_MARKER", "")).expanduser()
    if not str(marker):
        raise RuntimeError("PAPER_CRASH_POINT requires PAPER_CRASH_MARKER")
    payload = {
        "point": name,
        "pid": os.getpid(),
        "at_ms": int(time.time() * 1000),
        "details": details,
    }
    marker.parent.mkdir(parents=True, exist_ok=True)
    tmp = marker.with_suffix(marker.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, sort_keys=True, default=str)
        fh.write("\n")
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, marker)
    # Deliberately block: the parent kills this process.  No Python cleanup,
    # no finally block, no atexit hook, no flush of a pending state write.
    while True:
        time.sleep(3600.0)
