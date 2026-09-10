# H1 REPORT SEMANTICS — COST-INDEPENDENT vs COST-DEPENDENT EVIDENCE (Track M)

Checkpoint: H3-PREREG-VERIFICATION-AND-DISCOVERY-01 · Date: 2026-09-10
Documentation-only clarification. **`H1_RESULT.json` is NOT altered.** No historical
evidence is deleted. Purpose: make explicit which H1 evidence depends on the cost
model and which does not, after DEF-RESEARCH-COST-001 (display-only, fixed).

## Cost-independent evidence (never touches any cost model)

| Metric | H1 value | Source |
| --- | --- | --- |
| gross expectancy | −0.003034 R ≈ 0 | recomputed from raw immutable dataset in COST_SENSITIVITY_AUDIT.json (TRADE_SET_SHA256 recorded) |
| gross PF | 0.995 < 1 | same |
| temporal structure of gross edge | zero-gross mechanism; no cost-independent edge exists | same |

## Cost-dependent evidence (depends on the preregistered 10 bps RT cost; unaffected by DEF-RESEARCH-COST-001)

| Metric | H1 value | Note |
| --- | --- | --- |
| net expectancy | −0.1275 R | computed from `t.net_r` precomputed at 10 bps — arithmetically independent of the defective sensitivity branch |
| PF_net | 0.833 | same |
| Sharpe / CI95 | −0.0665 · [−0.0876, −0.0445] | same; CI entirely < 0 |
| P(Sharpe>0) / permutation p | 0.0 / 1.0 | same |
| halves / thirds / walk-forward | [−1,−1] / [−1,−1,−1] / −0.0884 R | same |
| corrected sensitivity curve | −0.003 → −0.252 R (0→20 bps) | supersedes the defective display values |

## Conclusion (unchanged by this clarification)

**H1 remains DISCOVERY_FAIL** because BOTH legs of the rejection hold:

1. **Gross edge ≤ breakeven** (cost-independent): gross expectancy −0.0030 R ≈ 0 and
   gross PF 0.995 < 1 — the mechanism carries no edge even before any cost is applied.
2. **The correctly computed preregistered base-cost case fails** (cost-dependent):
   net −0.1275 R, PF_net 0.833, Sharpe CI entirely < 0, halves/thirds uniformly negative.

The rejection is therefore doubly determined and does not depend on any potentially
defective metric. DEF-RESEARCH-COST-001 affected only a display field; no gate and no
historical evidence is affected or deleted.
