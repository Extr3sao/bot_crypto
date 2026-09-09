# FINAL REPORT — POC02-LAUNCH-AND-DISCOVERY-BATCH-02

| Field | Value |
| --- | --- |
| CHECKPOINT | POC02-LAUNCH-AND-DISCOVERY-BATCH-02 |
| BASE | `61d9bbd` (ALPHA-DISCOVERY-AND-SHADOW-V2-01, PASS, hermetic 1052/1052) |
| EXECUTED | 2026-09-09 (UTC), branch `feat/ma-2-specialist-opportunity-swarm` |
| HEAD | `2939276` + `STRATEGY_LAB_CANDIDATES_02` + this report |

## TRACK A — POC02 LAUNCH

| Field | Value |
| --- | --- |
| POC02_MANIFEST | PASS — `docs/external-audit-01/POC02_MANIFEST.md`, sha256 `895a9374c13901cc…` verified against the committed blob (launch gate fixed: it previously compared its argument to itself — a false-pass; recorded constant corrected) |
| POC02_LAUNCH_GATES | 6/6 PASS (`evaluate_launch_gates`, gates unchanged from preregistration) |
| POC02_LAUNCHED | **true** (2026-09-09T13:38:55+00:00, automatic — PAPER only, no human gate required) |
| POC02_CAMPAIGN_ID | `POC-02-paper-clean-01` (NEW identity; never reuses POC01 state) |
| POC02_RUNTIME | `Poc02Bundle` + `scripts/launch_poc02_campaign.py` (durable state, resume, cycle ledger, daily coverage rows) |
| POC02_WINDOW | start 2026-09-09T13:38:55Z → end 2026-09-30T13:38:55Z (21 counted days + 1 burn-in) |
| POC02_MARKET_DATA_PROVIDER | `binanceusdm` (public REST OHLCV, no credentials); zero downgrades so far; explicit fallback-with-downgrade-tracking if ever unreachable |
| POC02_EXECUTION_MODE | PAPER |
| POC02_EXECUTION_VENUE_MODEL | PaperBroker (`trading_bot.paper`) |
| POC02_COVERAGE | day 2026-09-09 row persisted: expected 1440 min / 288 cycles; observed minute-stamped rows accrue per cycle; ratio 0.0007 at launch instant, `day_validity=PENDING` (canonical validity contract at day close); zero-trade valid days remain valid |
| POC02_SHADOW_ACTIVE | **true** — `RiskGateRouter` + `ShadowCaptureHook` at the real Risk-REJECT arm, ledger at `reports/poc02-paper-clean-01/shadow/` (separate from POC01) |
| POC02_PAPER_TRADES | 0 (first cycle: 2 proposals, 0 selected → AGENT_FILTER bottleneck; valid no-trade) |
| POC02_SHADOW_CAPTURES | 0 (no Risk REJECT occurred in cycle 1; capture path live and tested) |
| POC02_SHADOW_RESOLVED | 0 |
| SHADOW_ISOLATION | SHADOW_PAPERBROKER_CALLS = 0 · SHADOW_PORTFOLIO_MUTATIONS = 0 · SHADOW_RISK_MUTATIONS = 0 · SHADOW_PNL_IN_PAPER = 0 · SHADOW_TRADES_IN_FREQUENCY = 0 |
| POC02_LIVE_CALLS | **0** (also REAL_BROKER_CALLS = 0, PRIVATE_EXCHANGE_CALLS = 0; fail-closed assert after every cycle) |

## TRACK B — POC01 CONTINUITY

| Field | Value |
| --- | --- |
| POC01_RUNTIME_CHANGED | **0** — `git diff 61d9bbd..HEAD -- reports/paper-observation-01/` is empty; campaign state untouched (`POC-01-paper-observation-01`, READY, provider fake, heartbeat 2026-09-09T08:28Z captured as-is); classification remains DEGRADED_OBSERVATIONAL_CAMPAIGN, continues to its original end |
| POC01 certification value | OBSERVATIONAL ONLY (unchanged) |

## TRACK C — DISCOVERY BATCH 02

| Field | Value |
| --- | --- |
| DISCOVERY_BATCH_02 | COMPLETE — preregistered (`e1f1193`), re-frozen pre-results, executed (`2939276`); results `DISCOVERY_BATCH_02_RESULTS.json` |
| DB2-01..DB2-03 | new preregistration ✅ · immutable fingerprints ✅ (spec mirror drift caught and corrected BEFORE any result was persisted, trade-for-trade identical to the batch-01 source of truth: 196/196) · no lead retuning ✅ (`verify_batch01_spec_unchanged` hard gate) |
| DB2-06/07/08 | carry unit repair ✅ (`FUNDING-UNITS-CANONICAL-V1` + a second real unit bug found and fixed in the funding authority: ms-spacing stored as seconds) · real funding data ✅ (90 obs/symbol, 8h spacing, depth-limited — INSUFFICIENT_DATA recorded, never synthesized) · PIT ✅ (settlement-ms keys, decision-time visibility) |
| DB2-09/10 | frozen batch-01 protocol costs (4 bps + 2 bps both sides) ✅ · robustness via frozen harness gates (Sharpe CI, permutation p, expectancy, PF) ✅ |
| DB2-11 | regime attribution per cell ✅ (all cells carry regime × asset × timeframe; no global PASS from one cell — nothing passed anywhere) |
| DB2-12 | frequency + days-with-opportunity persisted per category ✅ (Track E below) |
| DB2-13/14 | all failures persisted ✅ · promotions = **0** ✅ |

### C3 — volatility_structure_v2 (deeper window, NO retuning)

| Cell | n | net expectancy | PF | Sharpe/trade | perm p | Verdict |
| --- | --- | --- | --- | --- | --- | --- |
| BTC 1h | 196 | −0.00081 | 0.922 | −0.030 | 0.66 | DISCOVERY_FAIL |
| ETH 1h | 187 | <0 | FAIL | FAIL | FAIL | DISCOVERY_FAIL |
| SOL 1h | 186 | <0 | FAIL | FAIL | FAIL | DISCOVERY_FAIL |
| BTC/ETH/SOL 5m | 15/14/15 | <0 | FAIL | FAIL | FAIL | DISCOVERY_FAIL / INSUFFICIENT |

**The batch-01 lead (PF ≈ 2.5–3.0 on ~60 days) does NOT survive the independent ~730-day window.** Lead status: LEAD_ONLY → REFUTED_BY_DEEPER_WINDOW.

### C4 — cross_sectional_v2

Universe BTC+ETH+SOL (per-protocol cell): 1h n=181, 5m n=16 — both DISCOVERY_FAIL (all gates). Redundancy protocol (preregistered rule): persistence 0.86 (1h) / 0.85 (5m), turnover ≈ 14–15/100 bars, momentum-family correlation **0.89–0.91** → `DISTINCT_EVIDENCE` by the frozen rule (high corr but high persistence), recorded as redundant-behavior evidence; the candidate failed performance gates regardless.

### C5 — carry_funding_v2 (DEF-DISCOVERY-001 repair)

True-carry direction rule (SHORT receives positive funding) under the canonical unit contract on REAL binanceusdm funding. Evaluable cells (5m): n=16 each, all DISCOVERY_FAIL (BTC PF 0.72, p 0.69). 1h cells: n=8 < 15 → INSUFFICIENT_SAMPLE (public funding depth ≈ 30 days; recorded, not extended — DB2-07). DEF-DISCOVERY-001 is **resolved**: batch-01 spec untouched in history; v2 carries a new fingerprint.

## TRACK D/E — REGIME & FREQUENCY (observational)

- Every batch-02 cell is attributed Strategy × Asset × Timeframe × Regime (all landed in HIGH_VOL|MIXED windows at this anchor; per-cell metrics persisted).
- Frequency: opportunities 613 (vol-structure) / 197 (cross-sectional) / 72 (carry); days-with-opportunity 275 / 185 / 12 over the ~730-day 1h window. Carry is structurally sparse (8h settlements) — it cannot be a NO_SIGNAL filler at 5m cadence; vol-structure fires frequently but with negative expectancy after costs.
- Answer to the Track E question: no batch-02 candidate provides *positive-expectancy* incremental opportunities during POC01's NO_SIGNAL periods; frequency exists but edge does not (this is observational, not a promotion input).

## TRACK F — BOTTLENECK

| Field | Value |
| --- | --- |
| BN-01 | BottleneckState model live in POC02 telemetry (`classify_window`; NO_SIGNAL/STRATEGY_FILTER/AGENT_FILTER/VERIFIER_FILTER/RISK_COOLDOWN/RISK_POSITIONS/EXECUTION/NONE) — observational only, not a trading authority |
| BN-02/F1 | Cycle-1 evidence: BTC/ETH/SOL windows classified AGENT_FILTER (proposals existed, none selected) under the prevailing regime key; POC01's forensic funnel already records NO_SIGNAL concentration at the PROPOSAL gate — the regime×bottleneck table accumulates per cycle in `POC02_CYCLE_LEDGER.jsonl` |
| BN-03 | Observational only ✅ |

## TRACKS G/H — LAB STATES & CONFIRMATION LOCK

| Field | Value |
| --- | --- |
| G | `STRATEGY_LAB_CANDIDATES_02.json`: batch-02 = COMPLETE (never "PASS"); batch-01 leads displayed LEAD_ONLY with the refutation recorded |
| H | `CONF-EDGE-002-001` untouched: manifest exists ONLY in the immutable evidence tree (`39578a6`, `bb46c92`), `consumed=false`, window 2026-09-08→2026-09-22, executions=0; no mutable worktree copy was ever created; verification re-run this checkpoint |

## GOVERNANCE

| Field | Value |
| --- | --- |
| GOV-01 POC01 unchanged | **0 changes** |
| GOV-02 POC02 PAPER | ✅ (mode PAPER, `live_trading_enabled=false` enforced in-bundle) |
| GOV-03 confirmation untouched | ✅ consumed=false, executions=0 |
| GOV-04 LIVE 0 | LIVE_CALLS=0 · REAL_BROKER_CALLS=0 · PRIVATE_EXCHANGE_CALLS=0 |
| GOV-05 FALSE_SUCCESS 0 | ✅ one false-pass WAS caught and fixed (self-comparing manifest gate) — that is the guard working, not a false success; corrected constant + hash-against-disk gate |

## VALIDATION

| Field | Value |
| --- | --- |
| HERMETIC_REGRESSION | **1118 passed / 0 failed** (full suite incl. new funding/batch-02/POC02/bottleneck tests; 4:08) |
| Focused | research 125 · poc02 runner 8 · bottleneck 15 · funding units 43 — all green pre-execution |

## FINAL OUTPUT

```
CHECKPOINT                    = POC02-LAUNCH-AND-DISCOVERY-BATCH-02
BASE                          = 61d9bbd
POC01                         = UNCHANGED / DEGRADED_OBSERVATIONAL_CAMPAIGN / continues to original end
POC02_MANIFEST                = PASS (sha256 verified against committed blob; gate false-pass FIXED)
POC02_LAUNCH_GATES            = 6/6
POC02_LAUNCHED                = true (2026-09-09T13:38:55Z, window → 2026-09-30)
POC02_CAMPAIGN_ID             = POC-02-paper-clean-01
POC02_RUNTIME                 = Poc02Bundle + durable campaign runner (resume, coverage, telemetry)
POC02_MARKET_DATA_PROVIDER    = binanceusdm (public, no credentials)
POC02_EXECUTION_MODE          = PAPER
POC02_EXECUTION_VENUE_MODEL   = PaperBroker
POC02_COVERAGE                = day rows accruing; contract >= 0.80 pending day close; zero-trade days valid
POC02_SHADOW_ACTIVE           = true (Risk-REJECT arm; isolated ledger; isolation counters all 0)
POC02_PAPER_TRADES            = 0 (cycle 1: AGENT_FILTER; valid no-trade)
POC02_SHADOW_CAPTURES         = 0 (no REJECT yet; path live)
POC02_SHADOW_RESOLVED         = 0
POC02_LIVE_CALLS              = 0
DISCOVERY_BATCH_02            = COMPLETE (preregistered e1f1193 → executed 2939276)
VOLATILITY_STRUCTURE          = DISCOVERY_FAIL (deeper window refutes the batch-01 lead)
CROSS_SECTIONAL               = DISCOVERY_FAIL (momentum-family corr 0.89–0.91 recorded)
CARRY_FUNDING                 = DEF-DISCOVERY-001 RESOLVED; 5m FAIL, 1h INSUFFICIENT_SAMPLE (funding depth)
DISCOVERY_PASSERS             = none
DISCOVERY_FAILURES            = volatility_structure_v2, cross_sectional_v2, carry_funding_v2 (all cells)
INSUFFICIENT                  = carry 1h cells (n=8 < 15), ETH 5m vol (n=14)
REDUNDANT                     = none by the frozen rule (redundancy evidence recorded for cross_sectional)
INCREMENTAL_OPPORTUNITIES_PER_DAY = frequency persisted per category (613/197/72 opps over ~730d)
INCREMENTAL_NO_SIGNAL_OPPORTUNITIES = none with positive expectancy (observational answer: NO)
BOTTLENECK_STATES             = live (cycle 1: AGENT_FILTER on all assets)
REGIME_BOTTLENECK_FINDINGS    = accumulating per cycle in POC02_CYCLE_LEDGER.jsonl; POC01 funnel: NO_SIGNAL at PROPOSAL gate
CONFIRMATION_CONSUMED         = false
CONFIRMATION_EXECUTIONS       = 0
PAPER_PROMOTIONS              = 0
POC01_RUNTIME_CHANGED         = 0
LIVE_CALLS                    = 0
FALSE_SUCCESS                 = 0
HERMETIC_REGRESSION           = 1118 PASS / 0 FAIL
STATUS                        = PASS
NEXT                          = RUN_POC02 (daily cycles to 2026-09-30) + REVIEW_BATCH02 (leads refuted; no promotion) + CONFIRMATION_WAIT (2026-09-22)
```

## Commits (this checkpoint)

| Commit | Content |
| --- | --- |
| `e1f1193` | batch-02 preregistration committed BEFORE execution (specs, windows, funding unit contract, carry direction repair) |
| `686dfe7` | POC02 launch (manifest-gate false-pass fixed; binanceusdm authority; campaign runner; first real cycle) |
| `524ab12` | funding-data authority unit regression fix (ms→s interval) |
| `2939276` | batch-02 execution + results (mirror corrected pre-results; forward-paginated fetcher; no promotions) |
