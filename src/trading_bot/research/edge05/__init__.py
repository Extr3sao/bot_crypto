"""EDGE-05 — reliability and forward integrity for the autonomous forward lane.

WP-EDGE-04 made the lane observe by itself. This package is what keeps that observation honest
over sixty days without an operator:

* :mod:`trading_bot.research.edge05.watchdog` — an independent reading of the lane, its scheduler,
  its evidence and its resources, with a verdict that separates a quiet market from a failed
  operation. It holds no lease, runs no pipeline and makes no market request.
* :mod:`trading_bot.research.edge05.reconcile` — the auditable correspondence between stored bars,
  the ticks that claimed them and the decisions they produced, including the bars a killed tick
  left behind with no run row of its own.

Both are read-only with respect to the lane: they never rewrite a run log, never prune a daily
evidence file and never touch the store. Research only: no orders, no credentials, no capital, no
promotion.
"""

from __future__ import annotations

__all__ = ["reconcile", "watchdog"]
