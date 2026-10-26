"""ARP-005 ALPHA EXPANSION — data expansion + cross-sectional research infra.

Research-only package. No runtime module imports it; it cannot size, risk-check,
execute or promote anything. It provides:

* :mod:`htf` — PIT-safe 4h/8h/1d construction from native 1h bars;
* :mod:`data` — the isolated expanded corpus (2019-2026) with frozen splits;
* :mod:`xsec` — the fail-closed ``CrossSectionalSnapshot`` contract;
* :mod:`strategies` — three orthogonal cross-sectional factor rotations.

Deliberately separate from the ``experimental`` candidate subpackage, which must
stay untracked because it consumes the orphan HTF helper implicated in
``DEF-HTF-PIT-001``. This package derives its own HTF bars and never calls that
helper.
"""

from __future__ import annotations

from .htf import HTFBar, build_htf_bars, completed_bars
from .strategies import RotationConfig, simulate_xsec_rotation
from .xsec import (
    CrossSectionalSnapshot,
    CrossSectionalSnapshotBuilder,
    SnapshotRequest,
)

__all__ = [
    "CrossSectionalSnapshot",
    "CrossSectionalSnapshotBuilder",
    "HTFBar",
    "RotationConfig",
    "SnapshotRequest",
    "build_htf_bars",
    "completed_bars",
    "simulate_xsec_rotation",
]
