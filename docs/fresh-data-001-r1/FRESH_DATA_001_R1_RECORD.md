# FRESH-DATA-001-R1 — FULL-HISTORY INGESTION, EDGE-SANITY AUDIT & HONEST RERUN

```text
CHECKPOINT_ID: FRESH-DATA-001-R1
BASE_IMPLEMENTATION: f5c1d99  (FRESH-DATA-001)
BASE_EVIDENCE:       897465c
BRANCH: feat/fresh-data-001-r1 (isolated worktree .worktrees/fresh-data-001-r1)
IMPLEMENTATION_COMMIT: 21ee272
EVIDENCE_COMMIT: (this commit)
R0_DISPOSITION: all 9 candidates SUPERSEDED_INSUFFICIENT_DISCOVERY_WINDOW
                (preserved in docs/fresh-data-001/evidence/, refused by the
                selection gate; never used for R1 parameters/selection)
```

## 1. Root cause of the R0 truncation (G1)

`DatasetFetcher` broke out of the pagination loop when a page returned fewer
rows than requested. Binance Futures returns short pages routinely, so the
dataset stopped at the first page boundary (~1000 bars ≈ 3.5 days). R1
pagination continues until genuine exhaustion (empty batch), validating page
continuity (no overlap / no missing page), monotonic timestamps, and
closed-candle-only semantics. Fixed NOW (2026-09-06 15:15 UTC, last closed
5m candle) the full fresh history is:

```text
FETCH_PAGES:      6 per symbol (page limit 1000)
CANDLES/SYMBOL:   5367  (BTC, ETH, SOL — identical bounded window)
DATA_RANGE:       2026-08-19T00:00:00Z .. 2026-09-06T15:15:00Z
TOTAL_FRESH_DAYS: 18.635  (>= 14 => discovery authorized)
DATA_CUTOFF:      2026-09-06T15:15:00Z (= last closed candle at execution)
QUALITY:          duplicates=0, gaps=0, OHLC violations=0, non-positive
                  volume=0, pre-start candles=0; per-symbol SHA-256 in
                  DATA_MANIFEST.json; no imputation
```

## 2. Edge-sanity audit (G5–G9) — defects found and fixed

| # | Audit item | R0 behaviour | R1 behaviour |
|---|---|---|---|
| 1 | R definition | net after costs, risk from slippaged entry | same, but **initial risk frozen at entry** and explicit per-trade `risk_per_unit` |
| 2 | Fees | entry + exit | entry + exit (unchanged), asserted > 0 in every trade |
| 3 | Slippage | **entry only** (exit optimistic) | entry AND exit (`eff_exit = exit * (1 -/+ slip)`) |
| 4 | Future leakage | pinned structurally (tests) | same pins + ledger-level PIT fields |
| 5 | Entry availability | signal at t, entry at open of t+1 | unchanged (pinned) |
| 6 | SL/TP intrabar | exits only strictly after entry bar (conservative, deterministic) | unchanged, pinned by source-audit test |
| 7 | **Overlapping positions** | **possible** (new signal opened while previous trade still open) | **impossible**: single-position policy; a combo re-enters only after its previous trade closes |
| 8 | Capital/concurrency | one combo = unbounded parallel exposure | one position per combo (per-combo isolation = capital policy of the harness) |
| 9 | Duplicate executions | one signal → ≤1 trade (structural) | unchanged + ledger dedup check `{entry_signal_ts}` == N |
| 10 | Expectancy recomputation | not possible (no ledger) | `TRADE_LEDGERS.json`: `sum(net_r)/N` recomputed independently == `net_expectancy_r` for every combo |
| 11 | Unclosed trades | silently excluded | excluded explicitly (deterministic) |

## 3. Audit finding: regime-concentration metric degeneracy

The canonical `RegimeEngine` labels **98.5%** of real-market bars `MIXED`
(measured on the R1 discovery slice). R0's `regime_concentration` counted the
default bucket, forcing ≈1.0 on every `ALL`-filter combo — a measurement
artifact, not edge information. R1: concentration = max share over
**informative** labels only (default bucket excluded); an all-MIXED run has
0.0. Threshold (0.90) unchanged.

## 4. New split (hashed, immutable, locked)

```text
DISCOVERY:      2026-08-19T00:00:00Z .. 2026-08-30T04:20:59.999Z  (60%, 11.2 days)
CONFIRMATION:   2026-08-30T04:20:59.999Z .. 2026-09-02T21:47:59.999Z (20%, LOCKED)
FINAL_HOLDOUT:  2026-09-02T21:47:59.999Z .. 2026-09-06T15:15:00Z  (20%, LOCKED)
SPLIT_SHA256:   bbbaf275540d8e506a85f8e58513f48d0fc1888d56b86b1a5138a8b82175d4ff
locked_after_freeze: true; accessor raises on confirmation/holdout reads
(live probe + unit tests)
```

## 5. Discovery V2 (from scratch; zero reuse of R0 results)

```text
GRID:            3 symbols x 6 committed families x ALL x {LONG, SHORT} = 36
MIN_TRADES:      30 (pre-registered); combos qualifying: 24
COSTS:           fee 0.0005/side, slippage 5 bps entry+exit, R units
DETERMINISM:     two in-process passes, byte-identical (G14)
```

### Result: STOP_NO_EDGE (evidence-backed)

Best honest runs after the audit (all rejected by the pre-registered v2
criteria):

| combo | n | net ExpR | net PF | why rejected |
|---|---|---|---|---|
| volatility:SOL LONG | 8 | +0.664 | 2.417 | n<30; only 1/3 subperiods positive |
| trend:ETH LONG | 15 | +0.613 | 1.799 | n<30; thirds t2/t3 negative |
| breakout:ETH LONG | 47 | +0.479 | 1.467 | net PF < 1.15; thirds t2/t3 negative |
| breakout:SOL LONG | 51 | +0.312 | 1.308 | net PF < 1.15; thirds t2/t3 negative |
| breakout:BTC LONG | 43 | +0.153 | 1.148 | PF < 1.15; expectancy < 0.05R |
| momentum:SOL LONG | 74 | +0.079 | 1.104 | PF < 1.15; no subperiod stability |

Rejection-reason frequencies (36 rejections): `insufficient_subperiod_stability`
34, `net_pf_below_threshold` 31, `net_exp_r_below_threshold` 29,
`no_stability_across_halves` 22, `trades<30` 12, `temporal_concentration` 2.

**Structural pattern**: every positive combo concentrates its edge in the
first third of the window (t1 positive, t2/t3 negative) and no combo clears
net PF 1.15 with n ≥ 30. The R0 magnitudes (+2R/+3R per trade, PF up to 10)
were artifacts of overlapping positions, missing exit slippage, and the
truncated window — exactly what this checkpoint was sent to find.

## 6. Gates

```text
G1  full pagination                    PASS (6 pages/symbol, continuity-validated)
G2  cutoff = last closed candle        PASS (2026-09-06T15:15:00Z)
G3  >1000 candles/symbol               PASS (5367)
G4  data quality PASS                  PASS (0 defects)
G5  edge sanity audit PASS             PASS (overlap-free, costs both sides, dedup)
G6  R independent recomputation PASS   PASS (ledger == metrics, exact)
G7  fees/slippage PASS                 PASS (entry+exit, fee_r/slip_r > 0)
G8  no-lookahead PASS                  PASS (structural pins + deterministic policy)
G9  overlap/capital semantics PASS     PASS (single-position policy + tests)
G10 old candidates SUPERSEDED          PASS (9/9, preserved, selection-refused)
G11 new split hashed/immutable         PASS (bbbaf275…)
G12 confirmation inaccessible          PASS (fail-closed probe + tests)
G13 holdout inaccessible               PASS (fail-closed probe + tests)
G14 deterministic discovery            PASS (double-run byte-identical)
G15 legacy impact = 0                  PASS (no code path; context-only)
G16 PAPER impact = 0                   PASS (no PaperBroker/RiskManager references)
G17 LIVE = 0                           PASS (public data only, no orders)
G18 full regression PASS               PASS (844 passed, 0 failed; Ruff 0; Mypy 0)
GATES: 18/18
```

## 7. Decision & artifacts

```text
RESULT: STOP_NO_EDGE
CANDIDATES: 0 frozen  (frozen-on-PF-alone is now structurally impossible)
NEXT_AUTHORIZED_ACTION: none requiring candidates. Options: (a) extend the
fresh window with more elapsed calendar time and re-run discovery; (b) treat
the audit itself as the deliverable (R0's apparent edge was simulation
defect). Confirmation/holdout remain LOCKED and unread. LIVE = 0.
```

Artifacts in `docs/fresh-data-001-r1/evidence/`: DATA_MANIFEST, FETCH_STATS,
SPLIT_MANIFEST, DISCOVERY_RESULTS, TRADE_LEDGERS (per-trade audit trail),
CANDIDATE_REGISTRY (empty candidates + 36 rejected), REJECTED_HYPOTHESES,
GATE_REPORT.
