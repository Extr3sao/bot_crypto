"""Worktree-authoritative sys.path guard (EXT-PORTABLE-DATA-001 companion).

The shared virtualenv ships an editable install whose .pth pins the MAIN
repository's ``src`` directory (absolute path). In a git worktree that means
``import trading_bot`` silently resolves to the main checkout's code, not this
worktree's — tests would validate the wrong tree and hermetic results would be
contaminated by cross-worktree imports.

This conftest guarantees that THIS checkout's ``src`` takes precedence for all
pytest runs in this repository/worktree. In the main repo it is a no-op
(the same path is moved to the front).
"""

from __future__ import annotations

import sys
from pathlib import Path

_SRC = str((Path(__file__).resolve().parent / "src").resolve())

if sys.path and Path(sys.path[0]).resolve() != Path(_SRC):
    if _SRC in sys.path:
        sys.path.remove(_SRC)
    sys.path.insert(0, _SRC)
