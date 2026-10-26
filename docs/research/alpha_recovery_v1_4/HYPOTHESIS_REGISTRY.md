# ARP-005 — HYPOTHESIS REGISTRY (delta)

New/extended hypotheses carried to a frozen experiment in ARP-005. The canonical
registry (`docs/research/hypotheses/HYPOTHESIS_REGISTRY.md`) is updated in the same
change set (HYP-035+).

## Carried to a frozen experiment

### H-XSEC-RELSTR-001 — `EXP-ARP-009`

- **Economic rationale.** Cross-sectional momentum: relative winners tend to keep
  winning over multi-week horizons as flows chase recent outperformance.
- **Mechanism.** Rank BTC/ETH/SOL daily by trailing 30-day return; hold the leader,
  rotate on rank loss.
- **Universe / timeframe / horizon.** BTC/ETH/SOL · 1d · days-to-weeks.
- **Entry/exit/invalidation.** Next-day open on rank leadership; rotate on rank loss;
  `max_hold_days=30`; invalidated if it does not rotate (degenerates to one name).
- **Expected turnover.** Low (daily rebalance, but slow metric).
- **Cost sensitivity.** High — a rotation is a full round trip.
- **Required data.** Synchronized multi-asset daily bars (delivered by `xsec.py`).
- **Known failure modes.** Fixed 3-asset universe too small for a real quantile;
  sample starvation; regime-dependent.

### H-VOLEXP-BREAK-001 — `EXP-ARP-011`

- **Economic rationale.** Volatility clustering + accepted directional expansion.
- **Mechanism.** Close > prior 20-day high **and** ATR(14) > its prior-20 median.
- **Entry/exit.** Next open, long; stop 1.5×ATR; target 3×ATR; `max_hold_days=10`.
- **Expected turnover.** Low.
- **Cost sensitivity.** Medium; multi-day holds.
- **Known failure modes.** Trigger starvation; false breakouts in chop; long-only
  misses down-side expansions.

### H-LIQ-VOID-REV-001 (as `STRAT-CAND-016-VARIANT-B`) — `EXP-ARP-012`

- **Economic rationale.** A fast, ≥2×ATR one-sided displacement is a temporary
  liquidity vacuum more likely to retrace than continue when price re-enters its origin.
- **Mechanism.** ≥3-day strictly monotone run, displacement ≥2×ATR(14); fade after a
  band retest within 10 days.
- **Entry/exit.** Next open, opposite the void; stop 1.5×ATR; target 3×ATR; hold 5 days.
- **Expected turnover.** Low–medium.
- **Cost sensitivity.** Medium; 5-day holds.
- **Known failure modes.** Trends that do not retrace; regime shift in 2025-09…2026-02
  vs 2026-07…08 (realised: DEV edge did not generalise).

## Deferred (not carried)

- `H-DAILY-TSMOM-001` (`EXP-ARP-008`) — `DATA_SHORT_FOR_HORIZON` (needs ≈830–1230 DEV
  days; extension reaches 303).
- `H-VOLSPIKE-MR-001` (`EXP-ARP-010`) — ARP-004 `INSUFFICIENT_EVIDENCE`; not re-run.
