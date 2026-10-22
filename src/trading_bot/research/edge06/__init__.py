"""EDGE-06 — three registered families, measured on the frozen corpus and windows.

This package answers a question the frozen campaign left open: the intraday setup it measured
loses money **before** costs, so no fee reduction can repair it, and the next useful step is a
different family rather than a better execution of the same one.

Lane layout (research only; it never touches the live path):

* :mod:`families` — ``edge06_xs_momentum`` (relative strength within the declared universe),
  ``edge06_fade_extension`` (a stretched pullback back to the mean) and
  ``edge06_trend_fixed`` (the frozen trend entry with a fixed target instead of a trail),
  each subclassing the frozen ``edge01`` base so the signals differ, not the accounting;
* :mod:`program` — the runner: the campaign's own splits, corpus loader, cost scenarios, risk
  policy, metric definitions and admission gate, plus a cost-sensitivity, concentration and
  leave-out-the-largest reading that can only downgrade a verdict.

Nothing here promotes a strategy, sizes an order or relaxes a limit; the parameters are the
ones ``reports/edge-recovery/WP-EDGE-06/research/HYPOTHESES.md`` registered before the run.
"""

from __future__ import annotations

__all__ = ["families", "program"]
