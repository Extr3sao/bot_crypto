# EDGE-RESEARCH-002 — ORTHOGONAL EDGE HYPOTHESES (PRE-REGISTERED, DORMANT)

```text
CHECKPOINT_ID: EDGE-RESEARCH-002
BASE_IMPLEMENTATION: 21ee272  (FRESH-DATA-001-R1)
BASE_EVIDENCE:       14c7af2
BRANCH: feat/edge-research-002 (isolated worktree .worktrees/edge-research-002)
IMPLEMENTATION_COMMIT: 79b3d2b
EVIDENCE_COMMIT: (this commit)
```

## 1. Precheck & R1 evidence correction (G1/G2)

```text
R1 baseline verified:    21ee272 (implementation) / 14c7af2 (evidence)
Contradiction check:     breakout:ETH LONG was REJECTED in R1 with reason
                         "insufficient_subperiod_stability" (thirds:
                         +1.95 / -0.64 / -0.77 R) while netPF = 1.4672 > 1.15.
                         The REAL reason (temporal instability) is exactly
                         what R1 already recorded — NO contradiction existed,
                         no correction needed, R1 artifacts untouched.
R1 status:               CONSUMED_DISCOVERY — its window, params and results
                         are never reused for R2 parameters/selection.
Confirmation/Holdout:    LOCKED and unread (fail-closed probes + tests).
LIVE:                    0
```

## 2. Data gate → WAIT_FOR_NEW_DATA (honest)

```text
R1 evidence cutoff:      2026-09-06T15:15:00Z
Execution-time cutoff:   2026-09-06T17:10:00Z (last closed candle)
Elapsed new market time: 0.0799 days (~1h55m)
Required minimum:        0.25 days (6h) for a materially NEW window
RESULT:                  WAIT_FOR_NEW_DATA — NO hypothesis was executed,
                         no research fabricated. The registration artifact
                         was committed; execution machinery is dormant,
                         tested end-to-end on synthetic data, and will run
                         unchanged when new time arrives.
```

## 3. Pre-registered hypotheses (registered BEFORE any execution)

| ID | Mechanism | Gate (pre-registered, exact) |
|---|---|---|
| H-A-MTF-CONTEXT | 5m execution with 15m+1h trend alignment | both horizons' last two CLOSED bucket closes rising |
| H-B-VOL-MID-BUCKET | mid ATR% tercile (period 288, q33/q66 ex-ante) | ATR% within discovery-window quantile bucket |
| H-C-MEAN-REVERSION-FADE | committed MeanReversion family, both directions | none (mechanism itself is the hypothesis) |
| H-D-TREND-PULLBACK | committed Trend family behind a pullback gate | last CLOSED 15m bucket closed DOWN (LONG side) |
| H-E-CROSS-SECTIONAL-RS | trade only the 24h RS leader of BTC/ETH/SOL | rank-1 of 3, PIT closes, fail-closed missing data, LONG only |
| H-F-US-SESSION | committed universe inside 13:00–21:00 UTC | session window, ex-ante |

Every hypothesis carries `economic_rationale`, `exact_config`,
`pre_registered_acceptance` (identical to R1's untuned v2 criteria),
`config_sha256`, and `registered_before_execution: true` in
`HYPOTHESES_REGISTERED.json`. One execution per configuration; post-hoc
variants require a new HYPOTHESIS_ID. No parameter sweeps exist in the
package (tested).

## 4. Conditioning contract (audit-safe)

The certified R1 runner accepts an optional `bar_filter: Callable[[int], bool]`
over signal-bar timestamps. Contract (unit-tested):

1. Gate-only: a filtered run's trades are a subset of opportunities; gating a
   single base trade reproduces it with IDENTICAL economics (prices, stop,
   costs, exit reason, net R).
2. `bar_filter=None` (default) reproduces R1 behaviour exactly.
3. Labels are PIT-safe: HTF buckets are consulted only when fully closed
   (forming bucket never read); ATR uses trailing bars; RS uses closes at or
   before the signal bar and fails closed on missing data.

## 5. Gates

```text
G1  R1 baseline verified / evidence consistent   PASS (no contradiction found)
G2  no R1 reuse (CONSUMED_DISCOVERY)             PASS (structural; no import/use)
G3  confirmation/holdout LOCKED                  PASS (fail-closed probes)
G4  new discovery window required                PASS (6h minimum enforced)
G5  hypotheses pre-registered before execution   PASS (artifact committed first)
G6  one execution per config                     PASS (executor runs each once)
G7  no parameter sweeps                          PASS (none exist; tested)
G8  PIT / no-lookahead                           PASS (labeler tests)
G9  costs both sides unchanged                   PASS (R1 simulation reused)
G10 deterministic executor                       PASS (double-run digest equal)
G11 negative results recorded                    PASS (rejections carry reasons)
G12 PAPER impact = 0                             PASS (no PaperBroker/RiskManager refs)
G13 LIVE = 0                                     PASS (public data only, no orders)
G14 full regression PASS                         PASS (862 passed, 0 failed; Ruff 0; Mypy 0)
GATES: 14/14
```

## 6. Decision

```text
RESULT: WAIT_FOR_NEW_DATA
HYPOTHESES_REGISTERED: 6 (frozen configs, hashed)
RUNS: 0 (none authorized yet — no fabrication)
PASSERS / REJECTED: 0 / 0 (nothing executed)
NEXT_AUTHORIZED_ACTION: re-run `python scripts/run_edge_research_002.py`
once >= 6h of new closed-candle time exists since the R1 cutoff
(2026-09-06T15:15:00Z). The script will then build the new split, execute
each hypothesis exactly once, and classify with the unchanged pre-registered
rule. No confirmation execution; R1 confirmation/holdout remain LOCKED;
LIVE = 0.
```

## 7. Re-run instructions (when data is ready)

```bash
env -u EXCHANGE_ID -u BINANCE_API_KEY -u BINANCE_SECRET \
  uv run python scripts/run_edge_research_002.py
```

Artifacts: `reports/edge-research-002/` (runtime) mirrored to
`docs/edge-research-002/evidence/` (committed): HYPOTHESES_REGISTERED,
DATA_MANIFEST, FETCH_STATS, GATE_REPORT (+ SPLIT_MANIFEST,
DISCOVERY_RESULTS, TRADE_LEDGERS, HYPOTHESIS_RESULTS,
REJECTED_HYPOTHESES once executed).
