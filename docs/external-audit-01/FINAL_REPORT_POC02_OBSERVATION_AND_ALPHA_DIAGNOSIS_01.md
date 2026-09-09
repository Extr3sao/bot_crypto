# FINAL REPORT — POC02-OBSERVATION-AND-ALPHA-DIAGNOSIS-01

| Field | Value |
| --- | --- |
| CHECKPOINT | POC02-OBSERVATION-AND-ALPHA-DIAGNOSIS-01 |
| AUTHORITATIVE_BASE | `53c5910` (POC02-LAUNCH-AND-DISCOVERY-BATCH-02) |
| EXECUTED | 2026-09-09 (UTC), branch `feat/ma-2-specialist-opportunity-swarm` |
| MODE | PAPER only — no credentials, no private calls, no live plumbing |

## Canonical checkpoint report (exact fields)

| Field | Value |
| --- | --- |
| POC02_STATUS | ACTIVE — runtime healthy (heartbeat fresh, gates pass, campaign identity unchanged) |
| CAMPAIGN_ID | `POC-02-paper-clean-01` (window 2026-09-09T13:38:55Z → 2026-09-30T13:38:55Z) |
| COMPLETED_VALID_DAYS | 0 (campaign day 1 still OPEN at checkpoint time; UTC day not yet closed → nothing finalizable) |
| CURRENT_COVERAGE | `NOT_YET_MEASURABLE` (closed-days authority; day 1 provisional minutes = 7/1440 observed at checkpoint instant; ≥0.80 contract unchanged) |
| INVALID_DAYS | 0 |
| TOTAL_PAPER_TRADES | 0 |
| TRADES_PER_VALID_DAY | n/a (zero completed valid days — never fabricated from partial days) |
| DAYS_GE_3 | 0 |
| FREQUENCY_TARGET_RATE | n/a (denominator 0; target ≥3 trades/valid-day unchanged, not lowered) |
| NET_PNL | 0.0 (no paper positions opened) |
| PRIMARY_BOTTLENECK | `AGENT_FILTER` — 33/33 windows (100%) |
| BOTTLENECK_DISTRIBUTION | AGENT_FILTER 100% (33/33 windows); all other canonical buckets 0 |
| REGIME_BOTTLENECK_TOP | `NEUTRAL\|WEAK\|LOW\|RANGE\|NORMAL\|NORMAL` 17 windows; `NEUTRAL\|WEAK\|LOW\|TREND\|NORMAL\|NORMAL` 12 — all AGENT_FILTER (regime-dependence NOT yet assessable: bottleneck is uniform across every observed regime) |
| STRATEGY_CONTRIBUTION | `momentum` only strategy producing proposals (18 attributed candidates = 9 BTC/ETH/SOL × LONG/SHORT pairs); 18 AGENT_REJECTs, 0 selected, 0 risk stages, 0 paper; Trend/Breakout/MeanReversion/Volatility: zero attributed proposals in evidence so far (NO_SIGNAL at strategy surface) |
| AGENT_FILTER_RATE | 1.0 (18/18 candidates reaching the agent decision were rejected) |
| RISK_ACCEPT_RATE | n/a — no candidate reached Risk (upstream collapse at AGENT_FILTER) |
| SHADOW_CAPTURES | 0 (no Risk REJECT occurred — capture path armed + tested) |
| SHADOW_RESOLVED | 0 |
| SHADOW_EXPECTANCY | n/a — INSUFFICIENT_SAMPLE (0 resolved) |
| MAX_POSITIONS_SHADOW | n/a — INSUFFICIENT_SAMPLE |
| COOLDOWN_SHADOW | n/a — INSUFFICIENT_SAMPLE |
| WELL_COVERED_REGIMES | none (all regime cells < 20 windows with ≥2 strategies) |
| UNDER_COVERED_REGIMES | none yet classified (day 1 evidence only) |
| NEXT_RESEARCH_TARGET_REGIMES | none declared from day-1 evidence (§13: no coverage gap is yet actionable; matrix accumulation continues) |
| DISCOVERY_BATCH03 | NOT_STARTED |
| CONFIRMATION_CONSUMED | false (verified from committed manifest `39578a6`) |
| CONFIRMATION_EXECUTIONS | 0 |
| LIVE_CALLS | 0 (also REAL_BROKER_CALLS = 0, PRIVATE_EXCHANGE_CALLS = 0, SHADOW_PAPERBROKER_CALLS = 0) |
| FALSE_SUCCESS | 0 |
| HERMETIC_REGRESSION | 1152 passed / 0 failed (staged working tree; new modules git-added before the run) |
| STATUS | OBSERVATION_CONTINUE |

## Checkpoint questions — evidence-based answers

1. **Where are opportunities being lost?** 100% at the AGENT_FILTER stage.
   Every cycle produces 2 momentum proposals per asset (LONG+SHORT), both die
   with `UNRESOLVED_CONFLICT` + `material_dissent=true` from
   `critic-counter-signal` (per-candidate rows in
   `cycles/POC02_ATTRIBUTION.jsonl`). Zero losses at strategy/verifier/risk
   stages so far. This is structural (LONG vs SHORT on the same data always
   conflict), not regime-dependent.
2. **Does the bottleneck depend on market regime?** Not yet determinable:
   the bottleneck is AGENT_FILTER in **all five** observed regimes — no
   contrast exists yet. Matrix cells with <5 windows are flagged
   `single_observation`/INSUFFICIENT_EVIDENCE and are not interpreted.
3. **Are Risk rejects good or bad opportunities?** Unanswerable today: zero
   Risk rejections have occurred, so zero shadow captures exist. The
   shadow arm is live and tested; analysis will accumulate automatically.
4. **Which strategies contribute useful opportunities?** Only `momentum`
   reaches the board; its proposals are never selected (100% agent
   rejection). Profitability claims: NONE (no sample). The other four
   legacy strategies show zero attributed proposals in day-1 evidence.
5. **Which regimes lack usable strategies?** Every observed regime has
   proposals but zero downstream progress — formally they fall into
   UNDER_COVERED/NO_EDGE classes, but with day-1 sample sizes all regime
   cells are INSUFFICIENT_EVIDENCE; the map (§12) is persisted and will
   reclassify as windows accumulate.
6. **Is POC02 approaching ≥3 trades/day?** No — 0 trades and a 100%
   upstream agent-stage collapse. The trajectory question (whether removal
   of the conflict would translate proposals into trades) is NOT analyzed
   as a change here; observation continues.

## §8 AGENT_FILTER diagnosis (observational only — agents NOT loosened)

| Item | Value |
| --- | --- |
| AGENT_FILTER_RATE | 1.0 |
| by regime | 1.0 in all 5 observed regimes |
| by strategy | 1.0 for momentum (only strategy observed) |
| by asset | 1.0 for BTC, ETH, SOL |
| dominant decision reason | `UNRESOLVED_CONFLICT` (18/18) |
| critic evidence | `critic-counter-signal` challenges standing on every candidate; LONG and SHORT of the same asset/time mutually refute |

Per-candidate rows persist strategy, asset, regime, evidence refs,
counter-evidence refs, critic ids, decision score, and typed rejection
reasons — the required §8 persistence — in
`reports/poc02-paper-clean-01/cycles/POC02_ATTRIBUTION.jsonl`.
**No agent was changed.** Rate evolution will be tracked over checkpoints.

## §9/§10/§11 — Shadow V2

- Capture path armed at the real Risk-REJECT arm (unchanged from launch);
  0 captures so far because 0 candidates reached Risk.
- `SHADOW_PAPERBROKER_CALLS = 0`; `SHADOW_PNL_CONTAMINATION = 0`;
  `SHADOW_FREQUENCY_CONTAMINATION = 0` (structural isolation, labels on
  every capture).
- PIT resolver added (`trading_bot.shadow.resolver`, real public
  binanceusdm 5m bars, capture-horizon aware, no synthesis; tested).
- Risk-value test (§11): status `INSUFFICIENT_SAMPLE — no interpretation,
  no Risk change` (hard-coded until ≥20 resolved on both arms).

## §15 — carry funding DATA (investigation only)

Probes (public, no credentials, 2026-09-09): default
`fetchFundingRateHistory` returns the most-recent page only (500 obs ≈
166 d) — batch-02's `INSUFFICIENT_SAMPLE` was a fetch artifact, **not** a
data ceiling. With explicit deep `since`, the authoritative endpoint
(`/fapi/v1/fundingRate`, 8h settlements, epoch-ms) yields 1000 obs/page
back to **2019-09-10** for BTC perp. Recorded as a **SOURCE proposal only**
(`docs/external-audit-01/FUNDING_HISTORY_SOURCE_PROPOSAL.md`): source,
schema, timestamp/PIT/cost semantics are drafted with validation gates;
**no research executed, no thresholds touched.**

## Governance negatives (all verified)

| Negative | Value |
| --- | --- |
| LIVE_CALLS / REAL_BROKER_CALLS / PRIVATE_EXCHANGE_CALLS | 0 / 0 / 0 |
| POC01 runtime changed (diff `61d9bbd..HEAD` + working tree) | 0 files |
| Confirmation lock CONF-EDGE-002-001 | untouched (consumed=false, executions=0) |
| Discovery Batch 03 | NOT_STARTED |
| Trading parameters changed | 0 (risk policy hash unchanged; classification logic is observational-only) |
| Zero-trade valid days removed | 0 (kept by construction in daily rows) |
| Coverage threshold lowered | Never (0.80 preregistered) |

## New evidence infrastructure (additive; nothing gates or tunes)

| Artifact | Role |
| --- | --- |
| `src/trading_bot/paper/poc02_observation.py` | pure observation analytics (§2–§12, §18) over persisted ledgers |
| `src/trading_bot/shadow/resolver.py` | §9 PIT shadow resolution (real public bars, horizon-aware, no synthesis) |
| `scripts/poc02_observation.py` | `--daily` / `--status` / `--resolve-shadow` CLI; read-only STATUS.json + STATUS.html (PAPER vs SHADOW badges, RUNTIME_STALE surfacing, no controls) |
| `cycles/POC02_ATTRIBUTION.jsonl` | per-candidate funnel attribution (AGENT_REJECT / SELECTED / RISK_REJECT / PAPER_OPEN / PAPER_CLOSE) |
| `observation/DAILY_OBSERVATION_*.json`, `observation/STATUS.*` | daily + live observation surfaces |
| `docs/external-audit-01/FUNDING_HISTORY_SOURCE_PROPOSAL.md` | §15 SOURCE proposal (not executed) |

Bottleneck taxonomy: `OTHER_RISK` added per §5; rejections without a
persisted reason split now classify as OTHER_RISK instead of being
*labeled* RISK_COOLDOWN (the old default was an inference; the frozen
runner passes an explicit `OTHER` split so its behavior is preserved
truthfully).

## STATUS rationale

`OBSERVATION_CONTINUE` — day 1 is not yet closed; no completed valid day
exists; the single dominant finding (100% AGENT_FILTER on momentum-only
proposals) is structural but must accumulate across regimes and days
before any hypothesis or change is justified. Checkpoint summary triggers
(first 3 valid days / 25 shadow resolutions / 2026-09-22 / campaign end)
remain armed via `scripts/poc02_observation.py --daily` + the trigger
conditions encoded in the daily report fields.
