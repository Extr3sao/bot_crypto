"""EDGE-01 — three operational candidates, backtested on local historical data.

Lane layout (research side; it never touches the live path):

* :mod:`data` — local 15m and 1h corpora with provenance and upward aggregation;
* :mod:`features` — causal features (resistance, ATR, EMA, pivots, FVG) that can
  only read closed bars;
* :mod:`costs` — the venue cost plane read from ``COST_MODEL_V3`` plus stress
  variants derived from the same components;
* :mod:`candidates` — ``edge_intra_01``, ``edge_intra_02`` (+ the FVG ablation)
  and ``edge_trend_01`` (4h/1d), with parameters frozen before any measurement;
* :mod:`simulator` — deterministic portfolio simulation: risk-limited sizing,
  conservative intrabar fills, decomposed costs, and the optional resting limit
  entry a signal can ask for (``entry_limit``), which is off for the frozen lanes;
* :mod:`campaign` — pre-registered splits, scenarios, metrics and the
  ADMIT / REJECT / INSUFFICIENT_EVIDENCE gate;
* :mod:`retest` — the H6 variant: the frozen intraday signals with their entry
  moved to a resting limit at the broken level, rules unchanged;
* :mod:`closure` — the H6 experiment and the out-of-sample review of the frozen
  4h trend ruleset, each with its decision rule frozen before it ran.

Nothing in this package can place an order: it produces trades, curves and
verdicts, and it is exercised by ``scripts/edge01_run.py``.
"""

from __future__ import annotations

__all__ = [
    "campaign",
    "candidates",
    "closure",
    "costs",
    "data",
    "features",
    "retest",
    "simulator",
]
