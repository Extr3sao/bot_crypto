"""RFC-EDGE-014 — economic recovery, real trade-path audit and external benchmarking.

The brief stops measuring progress by the number of RFCs and starts measuring it by four
things: trades actually executed or simulated, the verifiable reason for every NO_TRADE,
a net edge that survives realistic cost and risk, and independence of verification. This
package is organised by those four questions, not by the artefacts it happens to write.

* :mod:`~trading_bot.research.economic_recovery.trade_path` — **14A**. What the runtime
  actually did over the window its own ledger covers: the funnel from market data to
  settled outcome, and the reason every cycle that produced no trade produced none. It
  keeps absence of evidence apart from evidence of zero, because they are not the same
  claim.
* :mod:`~trading_bot.research.economic_recovery.costs` — **14B**. What one round trip
  costs, rebuilt from the frozen gate artefact, and the reconciliation of the two
  contradictory fee shares WP-EDGE-09 published. The contradiction is a population
  mismatch, proven by reproducing the published number from the primary source.
* :mod:`~trading_bot.research.economic_recovery.frequency` — **14B**. The two frequency
  curves kept apart: overlapping selector opportunities and non-overlapping trade slots.
* :mod:`~trading_bot.research.economic_recovery.parity` — **14C**. The pinned clone
  registry, the license preflight, and the neutral-strategy parity plan with its
  tolerance frozen before the run.
* :mod:`~trading_bot.research.economic_recovery.candidates` — **14D**. Three hypotheses,
  checked against the families already in the tree before they are registered, so a
  duplicate is rejected by name rather than dressed up as new.
* :mod:`~trading_bot.research.economic_recovery.contracts` — the four formal records the
  brief defines, each refusing to be constructed in the shape the brief forbids.

Two rules hold everywhere here, exactly as in the EDGE-012 package. Nothing promotes a
strategy, sends an order or holds a credential: every record carries ``order_sent: false``
and ``promotion: "NONE"``. And nothing rewrites a primary source: the WP-EDGE-09 artefacts
are read, hashed and superseded by reference, never edited in place.
"""

from __future__ import annotations

__all__ = [
    "candidates",
    "contracts",
    "costs",
    "evidence",
    "frequency",
    "parity",
    "trade_path",
]
