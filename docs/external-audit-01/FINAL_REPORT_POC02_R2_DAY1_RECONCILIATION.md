# FINAL REPORT — POC02-R2-DAY1-EXECUTION-RECONCILIATION-01 + STRATEGY-AUTHORITY-DECISION-01

| Field | Value |
| --- | --- |
| **CHECKPOINT** | POC02-R2-DAY1-EXECUTION-RECONCILIATION-01 + STRATEGY-AUTHORITY-DECISION-01 |
| **CAMPAIGN** | `POC-02-R2-direction-arbitration-01` — ACTIVE, heartbeat fresh, no restart, no new identity |
| **DAY1** | **2026-09-09 FINALIZED VALID** (finalized 2026-09-10T05:09Z, `FINALIZATION_COUNT_PER_DAY=1`, reason `CONTRACT_SATISFIED`, receipts=4, cycles=6) |
| **DAY1_VALID** | VALID per preregistered evidence contract (trade-count independent, DEF-POC01-OBS-006) |
| **DAY1_COVERAGE** | coverage_ratio **0.0028** (4/1440 observed minutes) — **below 0.80**, recorded as outage evidence, never tuned |
| **RAW_RISK_ACCEPT_EVENTS** | **25** (per-candidate verdicts across 12 R2 runs; receipt-scoped subset was 10 — scope mismatch explained, not a defect) |
| **UNIQUE_ACCEPTED_INTENTS** | **9** (dedup `utc_date\|asset\|direction\|strategy`; 25 accepts collapse because each 5m-window evaluation of 3 assets × replayed runs re-fires the same economic intents) |
| **EXECUTION_ATTEMPTS** | **4** (all post-repair `007b691`; every pre-repair attempt crashed before reaching the broker) |
| **PAPER_OPENS** | **4** (BTC SHORT 09-09, BTC LONG 09-10 05:00, BTC SHORT 09-10 05:09, BTC LONG 09-10 06:58) |
| **PAPER_TRADES** | 4 opens / 0 closes; realized PnL 0.0 (no close yet) |
| **ACCEPT_WITHOUT_TRADE** | 21 pre-repair accepts (silent at the time, terminally classified now) |
| **ACCEPT_WITHOUT_TRADE_REASONS** | `EXECUTION_FAILED ×21` (DEF-R2-001: `Signal` is frozen+slots → `__dict__` copy crash before any order) |
| **DEF_R2_002** | **CONFIRMED** (telemetry/execution-evidence only — no Risk decision altered): funnel double-count in receipts 001-004; coverage finalizer blind to R2 ledger filename; telemetry `campaign_id` hardcoded to frozen id; accepts could vanish without typed disposition; one pre-enforcement cross-process duplicate (09-10 BTC-LONG ×2) |
| **ECONOMIC_ORDERS_PER_INTENT** | avg **0.33** / **max 2 pre-enforcement → 1 post-arm** (`R2_INTENT_LEDGER.jsonl` armed from 2026-09-10T06:58Z; post-arm cycles max=1) |
| **COMPLETED_VALID_DAYS** | 1 (2026-09-09) |
| **DAYS_GE_3** | 0 |
| **TRADES_PER_VALID_DAY** | **1.0** (1 canonical paper trade / 1 valid day) → **FREQUENCY_DAY_FAIL** (target ≥3, unchanged, no tuning) |
| **SHADOW_CAPTURES / RESOLVED** | **6 / 0** (all `OTHER_RISK`=max_positions; earliest matures 2026-09-11T21:15Z — 48h PIT horizon respected, no fabricated outcomes) |
| **MOMENTUM_AUTHORITY** | **LEGACY_CURRENT_CAMPAIGN_ONLY** (modern validation FAILED; future = revalidation required) |
| **TREND_AUTHORITY** | **RESEARCH_ONLY** (INSUFFICIENT cells, n<15 binding) |
| **BREAKOUT_AUTHORITY** | **RESEARCH_ONLY** (FAILED significance) |
| **MEAN_REVERSION_AUTHORITY** | **RESEARCH_ONLY** (FAILED significance) |
| **VOLATILITY_AUTHORITY** | **RESEARCH_ONLY** (INSUFFICIENT cells) |
| **FUTURE_PAPER_ELIGIBLE_STRATEGIES** | **NONE** (runtime compatibility ≠ paper authority — AUTH-02/03 enforced) |
| **CURRENT_CAMPAIGN_STRATEGIES_CHANGED** | **0** (frozen manifest universe untouched) |
| **RISK_CHANGED** | **0** (RiskManager untouched; dispositions are evidence rows, not gates) |
| **CONFIRMATION_CONSUMED / EXECUTIONS** | **false / 0** (CONF-EDGE-002-001, closes 2026-09-22) |
| **LIVE_CALLS** | **0** (REAL_BROKER=0, PRIVATE=0, SHADOW_PAPERBROKER=0) |
| **FALSE_SUCCESS** | **0** |
| **HERMETIC_REGRESSION** | **1187 passed / 0 failed** (ruff clean; mypy delta = 0 pre-existing) |
| **STATUS** | **PASS** — reconciliation complete, defects typed & repaired (telemetry only), frequency honestly FAIL |
| **NEXT** | CONTINUE_R2 + MATURE_SHADOW (first resolutions 09-11+) + REGIME_EVIDENCE + FUTURE_STRATEGY_RESEARCH |

## A1 — Counter semantics (proven, not inferred)

`RISK_ACCEPT = 10` in the earlier receipt view and `RAW_RISK_ACCEPT_EVENTS = 25` in the
full ledger are **scopes, not contradictions**:
- `state.risk_accepts` counts **per candidate** Risk verdicts (a 3-asset cycle can yield 3).
- Receipts 001-004 covered only receipted runs (10 accepts); runs `8254401/8255955/8292568`
  (9 accepts) and `8294016` (3 accepts) predate receipt coverage; today's cycles added 2.
- Classification: **EXPECTED_SEMANTICS** for counter scope + **POST_RISK_EXECUTION_DEFECT**
  (DEF-R2-001, already repaired in `007b691`) for the accept→order gap. **TELEMETRY_DEFECT**
  confirmed for the funnel (double-count) — repaired.

## Track A artifacts

- `docs/external-audit-01/poc02-r2-reconciliation/POC02_R2_RECONCILIATION.{json,md}` —
  one row per accept with terminal disposition and classification source; built by
  `scripts/poc02_r2_reconciliation.py` (read-only over immutable ledgers).
- Every accept now terminates in exactly one typed class: `PAPER_OPENED`,
  `ALREADY_OPEN_POSITION`, `DUPLICATE_ECONOMIC_INTENT`, `EXECUTION_FAILED`,
  `CLOSED_OPPOSITE_POSITION`, `CANCELLED_BY_EXPLICIT_POST_RISK_GATE`, `OTHER_TYPED_REASON`.

## Repairs (telemetry/execution-evidence only — zero trading-parameter changes)

1. **Typed terminal rows** (`RISK_ACCEPT_RESOLVED`) on every accept path — no silent accepts (EXE-05).
2. **Funnel single-source**: dashboard computes risk/open counts from the cycle ledger
   (receipts stay immutable evidence; mixing sources corrupted totals).
3. **`DayStateAuthority(coverage_filename=…)`** — R2 finalizer can now see `R2_COVERAGE_DAILY.jsonl`
   (default unchanged → frozen POC02 byte-identical).
4. **Telemetry `campaign_id` from bundle** — no more frozen-id misattribution.
5. **`PaperIntentLedger`** — durable exactly-once per `(utc_date, asset, direction, strategy)`,
   R2-composition-only (`arbitrate=True`); duplicate intent → `DUPLICATE_ECONOMIC_INTENT`, never a second position.

## TRACK G (frontend)

Spanish funnel now shows **Autorizadas por seguridad → Intentos de ejecución → Operaciones**
with an explicit gap notice ("No todas las autorizadas se abrieron: 24 autorizadas vs 3
operaciones…"), so users never infer that every Risk ACCEPT was a trade.
