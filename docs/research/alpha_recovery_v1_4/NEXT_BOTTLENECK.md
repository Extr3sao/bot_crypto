# ARP-005 §25 — NEXT BOTTLENECK (autonomous continuation)

ARP-005 completed with `PROMOTION_CANDIDATES = 0`. Per §25, the demonstrated next
bottleneck is identified here; no work beyond ARP-005 was started.

## What is now demonstrated

1. **Cost is no longer the only blocker.** One candidate (`EXP-ARP-012`) *did* clear
   the canonical cost (gross +27.61 bps > 23.56 bps; net +4.05 bps) — then failed
   **VALIDATION** by a wide margin (9 trades, −374.82 bps gross).
   → By §25 the primary next investigation is **generalization**: why a DEV edge with
   `gross/cost ≈ 1.17` did not survive W5–W6.
2. **Daily *selection* mechanisms are sample-starved on this calendar.**
   `EXP-ARP-009` (17 rotations) and `EXP-ARP-011` (2 trades) could not reach their
   frozen minimum samples even on the extended corpus, and their frozen thresholds must
   not be lowered.
   → The secondary bottleneck is **calendar/universe size for daily mechanisms**.
3. **`EXP-ARP-008` remains `DATA_SHORT_FOR_HORIZON`** (20-day holds need ≈830–1230 DEV
   days; the extension reaches 303).
   → A long-horizon test requires a genuinely deeper history.

## Ranked next steps (safe, no promotion boundary crossed)

1. **Generalization study of the cost-surviving DEV edge.** Decompose `EXP-ARP-012`'s
   DEV result (ETH/SOL-carried, BTC negative) by regime and by asset; state *ex ante*
   whether the collapse was predictable from the DEV fragility (break-even 27.6 vs cost
   23.6; negative at 1.25×). This is diagnostic research, not a promotion.
2. **Lengthen the daily calendar for selection mechanisms.** Extend the isolated corpus
   further (e.g. +12–18 months) so a cross-sectional / gated-daily mechanism can reach
   its frozen minimum sample without loosening rules. Requires only the same read-only
   fetch (free, reproducible, fingerprintable).
3. **Long-horizon unlock for `EXP-ARP-008`.** Requires ≈2–3 years of additional daily
   history — a larger fetch, still free/read-only, but a bigger storage/time commitment.

## Explicit stop conditions reached / not reached

- No `OOS_GATE_ELIGIBLE` boundary was reached → independent verification was not
  triggered and OOS `W7` stays unopened.
- Nothing in the ranked list requires LIVE trading, capital, credentials, a destructive
  action or a governance exception. **No stop condition was hit**; the next safe
  action is a generalization study (step 1) or a further corpus extension (step 2).
