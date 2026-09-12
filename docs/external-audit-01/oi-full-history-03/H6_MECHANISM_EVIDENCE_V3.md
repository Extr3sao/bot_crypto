# H6 MECHANISM EVIDENCE V3 — H6-OI-CONFIRMED-CONTINUATION-03

Checkpoint: `H6-V3-REPAIR-PREREG` · **no profitability claim is made anywhere in this document**

## Mechanism (carried forward unchanged from V2)

**Hypothesis:** a qualifying 1h expansion in open interest (position stock), coincident with a completed 1h price bar, confirms directional continuation into the next hour. Direction is price-derived only: price UP ⇒ LONG, price DOWN ⇒ SHORT (entry next-hour OPEN, exit same bar CLOSE; holding exactly 1h; stop NONE; cooldown NONE).

- **Qualifying expansion:** `delta_oi > 0 AND robust_z_oi >= +1.0`, where `delta_oi` = last 5m OI snapshot of completed hour H minus last snapshot of hour H−1 (base-asset units; exactly 12 distinct snapshots required in both hours), and `robust_z_oi = (delta_oi − rolling_median_720h) / (1.4826 × rolling_MAD_720h)` with `min_observations = 336`.
- **MAD == 0 ⇒ NO_TRADE. OI contraction (delta_oi ≤ 0) ⇒ NO_TRADE regardless of z** (raw-sign rule; a negative median/MAD cannot make a contraction qualify — regression-tested).
- **Ex-ante tier of evidence:** E-1 CME official education material (OI change as canonical confirmation/contradiction signal); E-2 corroborating exchange material; E-3 peer-reviewed leveraged-perp feedback dynamics (corrected citation: International Journal of Financial Studies 14(7):178). Tier: OFFICIAL + PEER_REVIEWED_CORROBORATION. Evidence quality claim is about mechanism plausibility ONLY — the frozen gates decide all economic outcomes.

## What V3 adds to mechanism credibility (no economics)

The V2 external verification failed on **authority defects** (whitelist enforcement, hash malformation, data portability, fingerprint binding, PIT dynamics, confirmation ledger), not on the mechanism hypothesis itself. V3 repairs exactly those authority defects:

- Every feature the mechanism consumes now provably flows through a fail-closed whitelist accessor (`WHITELIST_BYPASS_PATHS=0`).
- The dataset the mechanism consumes is now provably the official-source-derived, byte-committed authority (fingerprint commits to actual normalized bytes; adversarial mutation detected; full A/B determinism from raw official files).
- PIT causality of the mechanism's inputs is now proven dynamically, not just statically (future perturbations byte-invisible at T).
- The confirmation gate that will authorize the first economic execution is now ledger-authoritative and exactly-once.

None of these repairs uses any performance information; `H6_EXECUTIONS=0`, `H6_BACKTESTS=0`, `PERFORMANCE_OBSERVED=false`.

## Isolation

Mechanism inputs derive exclusively from: `sum_open_interest`, `sum_open_interest_value` (whitelisted OI fields) and completed 1h price bars (price authority). No Shadow outcome, no MAX_POSITIONS performance, no prior confirmation result enters hypothesis, features, threshold, asset selection, or cost selection.
