# ABLATION_REPORT — BOT-CRI-01 (RFC-TAP-AI-BOTS-004)

**Generated:** 2026-10-18T17:58:13Z · **Status:** `INCONCLUSIVE_VALUE` · **Recommendation:** `DO_NOT_ADOPT_PENDING_PROSPECTIVE`

## Matching

- Assets: BTC/USDT and ETH/USDT, 10 decision points, 4 actionable proposals.
- Same sequence across arms: **True**. Same capital, fees, slippage and latency settings.
- Data is historical and synthetic: this is **not** a forward test.

## Arms

| Arm | Executed | Fills | Closed | Net realised | Final equity | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| NO_CRITIC | yes | 2 | 2 | 5.26 | 10005.26 | canonical lane |
| SHADOW | yes | 2 | 2 | 5.26 | 10005.26 | 8 reviews, economics untouched |
| NO_TRADE | yes | 0 | 0 | 0.00 | 10000.00 | legitimate control |
| GATED_PAPER | **no** | — | — | — | — | `BLOCKED_GATED_PAPER_NOT_AUTHORIZED` |

## What the shadow measured

- Verdicts: `{'ACCEPT': 3, 'CHALLENGE': 5}`.
- Entries a gated critic *would* have suppressed: **1** of 4 (simulation only).
- Protective reviews: 4; blocked: **0** (must be zero).
- Degenerate blanket veto: **False** — a critic that vetoes everything cannot pass.
- Critic cost: **0.0 USD** (mock receipts).
- Review latency (mock): median 1.043 ms,
  max 1.58 ms.

## Verdict

`ECONOMIC_VALUE = UNMEASURED`. The mechanism is implemented and observable, but there is no
real model call, no prospective sample and no measured improvement. `DO_NOT_ADOPT` for
production; `SHADOW_ONLY` continues. `REAL_CRITIC_MODEL_CALLED = false`.
