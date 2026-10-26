# ARP-004 — EXPERIMENT SUMMARY

Stage order: `DEV → COST → VALIDATION → ROBUSTNESS → OOS`. A stage below `NOT_REACHED`
was never executed; experiments stop at the first failing gate (§8, §10, §13, §19).

| experiment | DEV | COST | VALIDATION | ROBUSTNESS | OOS | FINAL |
| --- | --- | --- | --- | --- | --- | --- |
| `EXP-ARP-007` | **PASS** | **REJECT_COSTS** | NOT_REACHED | NOT_REACHED | NOT_OPENED | **REJECT_COSTS** |
| `EXP-ARP-010` | **INSUFFICIENT_EVIDENCE** | NOT_REACHED | NOT_REACHED | NOT_REACHED | NOT_OPENED | **INSUFFICIENT_EVIDENCE** |

## DEV detail (combined, 3 assets, fixed 500 USD notional)

| metric | EXP-ARP-007 | EXP-ARP-010 |
| --- | --- | --- |
| trades | 153 | 6 |
| gross expectancy | **+0.776 bps** | **−75.059 bps** |
| canonical cost (1.0×) | 23.559 bps | 23.559 bps |
| net expectancy | **−22.783 bps** | −98.619 bps |
| win rate | 0.5163 | 0.5000 |
| profit factor | 0.8137 | 0.7255 |
| max drawdown | 5335.5 bps | 1199.6 bps |
| top-1 positive-net share | 0.039 | 0.389 |
| exit mix | stop 57 · target 73 · expiry 23 | stop 2 · target 3 · expiry 1 |
| capture ratio | 0.0039 | −0.3784 |
| by asset gross (bps) | BTC +9.96 · ETH +12.50 · SOL −19.36 | BTC −120.01 · ETH +55.09 · SOL −160.26 |

## Interpretation (deliberately conservative)

* `EXP-ARP-007` produced a positive but economically negligible gross expectancy
  (+0.776 bps) against a 23.559 bps round trip — a cost-dominated result, not an edge.
  Its per-asset split is inconsistent (SOL gross is negative), and the DEV gross is
  ~30× below the frozen kill threshold. **No attribution to `STRAT-CAND-019` source.**
* `EXP-ARP-010` is sample-starved (6 DEV trades; 0 signals in VALIDATION and OOS).
  The frozen `vol_z_entry=2.0` threshold was **not** lowered after seeing DEV. With
  ≈122 DEV days (≈60 lost to warmup) the trigger is too rare to evaluate. This is
  reported as `INSUFFICIENT_EVIDENCE`, **not** as a pass or an edge.

## Verdict vocabulary used

`REJECT_COSTS`, `INSUFFICIENT_EVIDENCE` are from the allowed experiment-result set.
`REJECT_COSTS` is emitted at the COST stage (§9/§10); it is the frozen manifest's
"DEV gross ≤ 23.559 bps → REJECT_COSTS" criterion evaluated where cost thresholds
belong. No forbidden word (`CERTIFIED`/`READY`/`PRODUCTION_READY`) is used anywhere.
