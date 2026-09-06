# FRESH-DATA-001 — PROSPECTIVE DISCOVERY DATASET & CANDIDATE FREEZE

```text
CHECKPOINT_ID: FRESH-DATA-001
BASE_IMPLEMENTATION: aa065cf4047031e402c9f6f9d469f19414429d78  (LEGACY-HIST-001)
BASE_EVIDENCE:       e55bd767a26a622559ed39f53d4fee7ec3e656ae
BRANCH: feat/fresh-data-001 (isolated worktree .worktrees/fresh-data-001)
IMPLEMENTATION_COMMIT: f5c1d99
EVIDENCE_COMMIT: (this commit)
```

## Data

```text
PROVIDER:        binanceusdm-public (ccxt, no credentials, public endpoints only)
TIMEFRAME:       5m
SYMBOLS:         BTC/USDT:USDT, ETH/USDT:USDT, SOL/USDT:USDT
FRESH_START:     2026-08-19T00:00:00Z   (strictly > 2026-08-18)
DATA_CUTOFF:     2026-08-22T11:20:00Z
CANDLES/SYMBOL:  1000 (complete 5m bars from fresh start)
DATA_QUALITY:    PASS — duplicates=0, gaps=0, gap_bars=0, OHLC violations=0,
                 non-positive volume=0, candles before start=0, UTC throughout
INPUT HASHES:    per-symbol SHA-256 in docs/fresh-data-001/evidence/DATA_MANIFEST.json
NO IMPUTATION:   absent data is reported, never silently filled
```

## Immutable split (hashed, locked)

```text
DISCOVERY:      2026-08-19T00:00:00Z .. 2026-08-21T01:59:59.999Z   (~60%)
CONFIRMATION:   2026-08-21T01:59:59.999Z .. 2026-08-21T18:39:59.999Z (~20%, LOCKED)
FINAL_HOLDOUT:  2026-08-21T18:39:59.999Z .. 2026-08-22T11:20:00Z    (~20%, LOCKED)
SPLIT_SHA256:   6c7179f9d70461d5986256518f0e9338d88a378eeb2e1c98af7da67a9f6300c8
locked_after_freeze: true; SplitAccessor raises SplitAccessError on any
confirmation/holdout read (fail-closed, unit-tested).
```

## Discovery (DISCOVERY slice only)

```text
GRID:        3 symbols x 6 committed families x regime ALL x {LONG, SHORT} = 36 combos
             (families: Momentum, Trend, Breakout, MeanReversion, Volatility, EmaCrossover)
MIN_TRADES:  30 (pre-registered)
COMBOS>=30:  18
COSTS:       fee_rate=0.0005 (round-trip), slippage=5 bps; metrics in R units
PIT:         signal on candles[:i+1]; entry at open of i+1 (+slippage); exits
             evaluated strictly after the entry bar; no parameter sweeps
DETERMINISM: grid executed twice in-process; byte-identical run records (G10)
```

### Frozen candidates (9) — status FROZEN_AWAITING_CONFIRMATION

| candidate | n | net ExpR | net PF | net PnL(R) | win rate |
|---|---|---|---|---|---|
| trend:BTC LONG | 71 | 0.0940 | 1.2558 | +6.67 | 0.408 |
| momentum:ETH LONG | 121 | 0.7760 | 2.3062 | +93.90 | 0.388 |
| trend:ETH LONG | 138 | 2.3735 | 10.0322 | +327.55 | 0.594 |
| breakout:ETH LONG | 30 | 3.3728 | 5.5254 | +101.18 | 0.433 |
| ema_crossover:ETH LONG | 338 | 2.9013 | 4.9652 | +980.65 | 0.399 |
| momentum:SOL LONG | 107 | 1.6612 | 4.3429 | +177.75 | 0.458 |
| trend:SOL LONG | 73 | 0.0925 | 1.2084 | +6.75 | 0.384 |
| breakout:SOL LONG | 32 | 3.3015 | 6.7027 | +105.65 | 0.563 |
| ema_crossover:SOL LONG | 357 | 2.5056 | 4.8413 | +894.49 | 0.454 |

All 9 configs are frozen with `config_sha256` + `frozen_sha256` in
`CANDIDATE_REGISTRY.json`; modification before confirmation is prohibited.
Rejected hypotheses: 27 (`REJECTED_HYPOTHESES.json`), dominated by SHORT-side
negative expectancy, regime concentration > 0.9, and n<30. Legacy evidence was
consulted for context only — it cannot score, select, or promote (G7=0,
unit-tested: no import path from legacy modules into discovery code).

## Gates

```text
G1  source baseline certified        PASS (aa065cf / e55bd767)
G2  fresh start > 2026-08-18         PASS (2026-08-19T00:00:00Z)
G3  dataset quality PASS             PASS (0 defects, 3/3 symbols)
G4  chronological immutable split    PASS (split_sha256, locked)
G5  confirmation unread              PASS (accessor fail-closed probe + unit tests)
G6  final holdout unread             PASS (accessor fail-closed probe + unit tests)
G7  legacy decision impact = 0       PASS (context-only; no code path)
G8  PIT / no-lookahead               PASS (structural unit tests)
G9  realistic costs                  PASS (fees + slippage in all metrics)
G10 deterministic rerun              PASS (double-run byte-identical)
G11 candidate configs frozen+hashed  PASS (9/9 config+frozen SHA-256)
G12 no post-hoc selection            PASS (pre-registered criteria, no sweep)
G13 no PAPER routing impact          PASS (no PaperBroker/RiskManager references)
G14 LIVE execution = 0               PASS (public data only; no orders anywhere)
G15 full regression PASS            PASS (821 passed, 0 failed)
GATES: 15/15
```

## Decision

```text
RESULT: CANDIDATES_FROZEN_AWAITING_CONFIRMATION
BEST_NET_EXPECTANCY: 3.3728 R (breakout:ETH LONG)
BEST_NET_PF: 10.0322 (trend:ETH LONG)
NEXT_AUTHORIZED_ACTION: CONFIRMATION on the locked confirmation window, then
(finally) FINAL_HOLDOUT evaluation. No confirmation executed in this
checkpoint. No paper promotion. No 7-day campaign start. LIVE remains 0.
```

## Notes

1. The window available at execution time is short (3.5 days at 5m). The
   split fractions hold; absolute sample sizes are small — confirmation and
   holdout exist precisely to punish the discovery-side optimism visible in
   the ETH/SOL LONG numbers.
2. Artifacts mirrored under `docs/fresh-data-001/evidence/` (reports/ is
   gitignored); `reports/fresh-data-001/` remains the runtime output.
3. Host `EXCHANGE_ID` override neutralized during regression (pre-existing,
   classified env baseline from CERT-DEMO-PAPER-01).
