# DEF-CORR-001 — STATIC_CORRELATION_USED_AS_RISK_FACT — **REJECTED**

Checkpoint: EXTERNAL-AUDIT-RECONCILIATION-01
Audited HEAD: `a282fcc`

## Claim (external audit)

"Current `correlation_cluster` really uses constants such as 0.85
BTC/ETH/SOL/AVAX and 0.55 others."

## Audit performed (directive 14: do not assume the audit is correct)

| Check | Result |
| --- | --- |
| `grep -r "0.85" src/trading_bot/` at HEAD | **0 matches** |
| `grep -rn "0.55" src/trading_bot/` at HEAD | 1 match: `charting/local_renderer.py:84` — candle-width layout constant, unrelated to risk |
| `CORRELATION_CLUSTER` references | `domain/enums/risk.py:29` declares the enum value; **no implementation references it** (single match in repo) |
| `paper/candidate_portfolio.py:42` | uses `correlation_group: str | None` as a **label** (e.g. `"crypto-beta"`), not numeric correlation constants |
| Same checks at audited commits `3c274cc` and `bb46c92` (`git grep`) | identical: no 0.85/0.55 risk constants; only the charting layout constant and the correlation_group label |

## Verdict

**REJECTED.** There is no static correlation risk factor in the runtime. The
`CORRELATION_CLUSTER` risk reason is a declared-but-unimplemented enum value
(`NOT_RUNTIME_REACHABLE`). The external audit's claim could not be reproduced
at HEAD or at the audited commits.

DEF-CORR-001 is therefore **not registered as an active defect**; this file is
the record of the rejection.

## Residual design work (not a defect)

Real rolling correlation is genuinely absent (gap matrix #11/#12). The design
for it is recorded in `RFC-CORRELATION-REGIME-01.md` as forward work — not as
a repair of a static-correlation defect, since none exists.