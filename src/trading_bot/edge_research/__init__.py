"""EDGE-RESEARCH-002 — orthogonal edge hypotheses on fresh post-legacy data.

Pre-registered hypotheses (H-A..H-F) executed ONCE each against a NEW
discovery window, using the certified R1 simulation semantics. R1's window
is CONSUMED_DISCOVERY and is never re-used; R1 confirmation/holdout remain
locked. No parameter sweeps, no threshold tuning, no cherry-picking.
"""

from __future__ import annotations

from .hypotheses import (
    Hypothesis,
    preregistered_hypotheses,
    register_payload,
)

__all__ = ["Hypothesis", "preregistered_hypotheses", "register_payload"]
