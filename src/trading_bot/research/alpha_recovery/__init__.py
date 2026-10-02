"""ARP-002 — Alpha Recovery experiment package (research-only, deterministic).

This package implements the deterministic, PIT-safe signal rules for the first
cost-aware experiment campaign (EXP-ARP-001/002/003/005). It is a **research**
package:

* no runtime module imports it; the PAPER runtime composition is untouched;
* it cannot size, risk-check, execute or promote anything;
* every rule is a pure function of already-closed bars (``data_time <= decision_time``).

It is deliberately separate from the ``experimental`` candidate subpackage (which
must stay untracked because it consumes the orphan HTF helper implicated in
``DEF-HTF-PIT-001``). These experiments read the 5-minute corpus only and never
touch a higher-timeframe bar, so promoting this package to tracked source cannot
escalate that defect.
"""

from __future__ import annotations

from .experiments import (
    EXP001_CONFIG,
    EXP002_CONFIG,
    EXP003_CONFIG,
    EXP005_CONFIG,
    Exp001PullbackContinuation,
    Exp002VoidRetest,
    Exp003RelativeStrength,
    Exp005PivotFade,
)
from .series import atr_series, ema_series, sma_series
from .simulate import SimulationResult, Trade, simulate

__all__ = [
    "EXP001_CONFIG",
    "EXP002_CONFIG",
    "EXP003_CONFIG",
    "EXP005_CONFIG",
    "Exp001PullbackContinuation",
    "Exp002VoidRetest",
    "Exp003RelativeStrength",
    "Exp005PivotFade",
    "SimulationResult",
    "Trade",
    "atr_series",
    "ema_series",
    "simulate",
    "sma_series",
]
