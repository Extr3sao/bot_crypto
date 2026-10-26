"""EDGE-08 — alpha on an unread cross-section, with ACTIVE and QUALITY kept apart.

The lane has four parts and cannot place an order:

* :mod:`registration` — the RFC-EDGE-008 registration in machine-readable form: the windows, the
  criteria, the two tracks and the multiplicity, all of them written down before any figure of
  the cross-section existed;
* :mod:`books` — the six proposed books (three low-frequency QUALITY, three ACTIVE on a clock the
  cost barrier can pay) plus the three frozen books the CURRENT-vs-PROPOSED comparison needs;
* :mod:`universe` — the unread cross-section as a corpus (``data/edge08/universe-1h/``), the
  known universe as the screening ground, and the market-context labels both are read against;
* :mod:`screens`, :mod:`economics`, :mod:`validation` — the gross screen on the known universe,
  the economic matrix with its robustness readings, and the registered verdicts on the
  cross-section.

Research only: no credentials, no orders, no capital. ``order_sent`` stays ``false`` and
``promotion`` stays ``NONE`` for every arm.
"""

from __future__ import annotations

__all__ = [
    "analysis",
    "books",
    "economics",
    "registration",
    "runner",
    "screens",
    "universe",
    "validation",
]
