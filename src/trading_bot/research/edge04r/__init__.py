"""WP-EDGE-04R — why the forward lane lost triggers, and what would stop it.

WP-EDGE-04 built an autonomous forward observer and declared, honestly, that it was
0 of 60 admissible days because the host was not continuously available. That
declaration rested on a count (74 of 96 triggers in a window) without a cause: the
operating system's own trigger history was unavailable, so the loss could not be
attributed to anything in particular.

This package answers the question with evidence instead of an inference:

* :mod:`trading_bot.research.edge04r.os_evidence` reads what the host itself
  recorded — boots, shutdowns, session logons and logoffs, power transitions, the
  registered task and its definition, the storage estate — and never asserts a
  cause the host did not write down.
* :mod:`trading_bot.research.edge04r.continuity` turns the lane's own tick log and
  that host evidence into an attributed account of every missed trigger, plus the
  availability metrics that follow from it.

Nothing here changes a strategy, a risk limit, a coverage threshold or an admission
condition, and nothing here promotes anything. Research only: public market data,
no credentials, no orders, no capital.
"""

from __future__ import annotations

__all__ = ["continuity", "os_evidence"]
