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
  conservative intrabar fills, decomposed costs;
* :mod:`campaign` — pre-registered splits, scenarios, metrics and the
  ADMIT / REJECT / INSUFFICIENT_EVIDENCE gate.

Nothing in this package can place an order: it produces trades, curves and
verdicts, and it is exercised by ``scripts/edge01_run.py``.
"""

from __future__ import annotations

__all__ = [
    "campaign",
    "candidates",
    "costs",
    "data",
    "features",
    "simulator",
]
