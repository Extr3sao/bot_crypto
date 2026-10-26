# ARP-005 — DEV RESULTS (§8/§10)

Canonical cost applied at DEV = 23.559 bps round trip. DEV windows: baseline
W1–W4 (122 d/symbol); extended WX1–W6 + W1–W4 (303 d/symbol).

| experiment | strategy | dataset | trades | trades/day | active days | zero-trade days | median hold | gross bps | net bps | win | PF | DD bps | top1 | DEV verdict |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| EXP-ARP-009 | H-XSEC-RELSTR-001 | baseline | 17 | 0.139 | 17 | 105 | ~ | **−100.114** | −123.673 | 0.529 | 0.607 | 3837.0 | 0.348 | **INSUFFICIENT_EVIDENCE** |
| EXP-ARP-011 | H-VOLEXP-BREAK-001 | baseline | 2 | 0.016 | 2 | 120 | ~ | **−63.301** | −86.861 | 0.500 | 0.081 | 189.0 | 1.000 | **INSUFFICIENT_EVIDENCE** |
| EXP-ARP-012 | STRAT-CAND-016-VARIANT-B | extended | 62 | 0.205 | 33 | 270 | 4.0 d | **+27.610** | +4.051 | 0.468 | 1.014 | 4136.8 | 0.106 | **PASS** |

## Per-asset gross (DEV)

- **EXP-ARP-009** — single cross-sectional stream: −100.114 bps.
- **EXP-ARP-011** — BTC +38.836, ETH −165.438, SOL no trade (2 trades total).
- **EXP-ARP-012** — BTC −56.973, ETH +79.716, SOL +61.711. **The positive DEV result
  is carried by ETH+SOL while BTC is negative** — a fragility flag that VALIDATION
  later confirmed.

## §10 sample sufficiency (explicit statuses)

- `EXP-ARP-009` — **INSUFFICIENT_EVIDENCE**: 17 rotations < the frozen minimum 20.
  The frozen `lookback_days=30` was **not** shortened to manufacture sample. Gross is
  also negative, so even a larger sample would be `REJECT_NO_EDGE`.
- `EXP-ARP-011` — **INSUFFICIENT_EVIDENCE**: 2 trades < 10. The volatility-expansion
  gate is trigger-starved on ~122 days; the frozen gates were **not** relaxed.
- `EXP-ARP-012` — **SUFFICIENT_EVIDENCE**: 62 trades ≥ 10; top1 share 0.106 < 0.5.

## Distribution checks (EXP-ARP-012)

- Exit mix: stop 20 / target 7 / window_expiry 35.
- Concentration: top1 0.106, top5 0.366, top10 % 0.424 — no single-trade dominance.
- Drawdown 4136.8 bps on a 500 USD notional and +12.56 USD net — a thin, high-variance
  edge, which is exactly why the COST and VALIDATION stages exist.

## Gate

`DEV survivors (PASS) = 1` (EXP-ARP-012) → proceeds to COST. `EXP-ARP-009` and
`EXP-ARP-011` short-circuit: COST NOT_REACHED, VALIDATION NOT_REACHED, OOS never opened.
