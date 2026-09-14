"""Worktree-authoritative sys.path guard (same pattern as h6-v4-repair / main horizon).

The shared virtualenv ships an editable install whose .pth pins the MAIN
repository's ``src`` directory. Without this guard ``import trading_bot``
in the .research worktree resolves to the main checkout, not this worktree's
src/trading_bot/research/arc01 — tests observe the wrong tree.

This conftest guarantees THIS checkout's ``src`` takes precedence for all
pytest runs in this worktree. In the main repo it is a no-op (same path).
"""

from __future__ import annotations

import sys
from pathlib import Path

_SRC = str((Path(__file__).resolve().parent / "src").resolve())

if sys.path and Path(sys.path[0]).resolve() != Path(_SRC).resolve():
    if _SRC in sys.path:
        sys.path.remove(_SRC)
    sys.path.insert(0, _SRC)
