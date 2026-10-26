"""RFC-025 Part C — PIT-safe orthogonal signal arrays.

A signal at the close of bundle bar ``i`` is in {-1, 0, +1}; execution happens
at the OPEN of bar ``i + 1`` (the certified engine). The orthogonal feature is
aligned as-of (``ortho_on_bundle``); the certified volatility detector
(``sprint002_signals._vol_shock``) is imported, never redefined.

Direction is fixed by the Part B information audit: the pooled Spearman IC of
``basis`` / ``taker_*`` against future signed return is NEGATIVE, so a high
feature value implies a LOWER forward return and the rule is contrarian.
"""

from __future__ import annotations

import sys
from typing import Any

import numpy as np
from numpy.typing import NDArray

sys.path.insert(0, "scripts")
import sprint002_lib as L
import sprint025_lib as OL


def signal_array(
    asset: str,
    b: L.Bundle,
    feature: str,
    z_thr: float,
    cond_vol: bool,
) -> NDArray[Any]:
    """Contrarian threshold rule on an orthogonal feature (PIT, as-of aligned)."""
    feats = OL.ortho_on_bundle(asset, b, at="close")
    x = np.asarray(feats[feature], dtype=np.float64)
    sig = np.zeros(len(b), dtype=np.int8)
    high = np.isfinite(x) & (x >= z_thr)
    low = np.isfinite(x) & (x <= -z_thr)
    if cond_vol:
        shock = OL.vol_shock_of(b)
        high = high & shock
        low = low & shock
    sig[low] = 1  # feature very low -> expected up (IC negative)
    sig[high] = -1
    return sig
