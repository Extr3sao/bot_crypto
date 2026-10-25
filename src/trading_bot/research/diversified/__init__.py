"""ARP-006 DIVERSIFIED ALPHA SEARCH — PIT dynamic universe + broad-universe factors.

Research-only. No runtime module imports it; it cannot size, risk-check, execute or
promote anything. It provides:

* :mod:`data` — the broader isolated daily corpus (native 1d klines) with frozen
  DEV/VALIDATION/OOS_LOCK splits;
* :mod:`universe` — the fail-closed PIT :class:`DynamicAssetUniverse` and
  :class:`UniverseSnapshot`;
* :mod:`daily` — the two ready daily experiments (EXP-ARP-006, EXP-ARP-008);
* :mod:`xsec` — the NEW broader-universe cross-sectional factors (EXP-ARP-016/017/018);
* :mod:`analytics` — concentration, breadth, temporal and regime metrics.
"""

from __future__ import annotations

from .analytics import (
    concentration_by_asset_and_period,
    pnl_by_asset,
    pnl_by_year,
    regime_by_day,
)
from .daily import (
    Exp006Config,
    Exp006LiquidityReversal,
    Exp008Config,
    simulate_exp006,
    simulate_exp008,
)
from .data import DailyBar, corpus_digest, load_corpus, load_symbol
from .universe import DynamicAssetUniverse, UniverseConfig, UniverseSnapshot
from .xsec import XsecUniverseConfig, simulate_universe_xsec, xsec_universe_configs

__all__ = [
    "DailyBar",
    "DynamicAssetUniverse",
    "Exp006Config",
    "Exp006LiquidityReversal",
    "Exp008Config",
    "UniverseConfig",
    "UniverseSnapshot",
    "XsecUniverseConfig",
    "concentration_by_asset_and_period",
    "corpus_digest",
    "load_corpus",
    "load_symbol",
    "pnl_by_asset",
    "pnl_by_year",
    "regime_by_day",
    "simulate_exp006",
    "simulate_exp008",
    "simulate_universe_xsec",
    "xsec_universe_configs",
]
