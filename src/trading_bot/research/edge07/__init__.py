"""EDGE-07 — validate the frozen fixed-target trend book on a window nobody has read.

The lane has three parts, and none of them can place an order:

* :mod:`validation` — the pre-registered reading of ``edge07_trend_fixed`` (the WP-EDGE-06
  ``edge06_trend_fixed`` parameters, unchanged) and of the frozen trailing ruleset as a
  comparison, on the campaign's own windows plus the new holdout fetched from public Binance
  REST;
* ``reports/edge-recovery/WP-EDGE-07/PREREGISTRATION.{md,json}`` — the criteria, committed
  before the holdout was fetched and before any figure of it existed;
* ``reports/edge-recovery/WP-EDGE-07/VALIDATION.{json,md}`` — what was measured, and the
  verdict the registered criteria produce.

Nothing here sizes a position: ``config/risk.yaml`` decides, through the campaign's own risk
policy, and the simulator is the campaign's own. Research only — no credentials, no orders.
"""

from __future__ import annotations

__all__ = ["validation"]
