# RFC-046 RUN REPORT — CONTROLLED DISCOVERY, FIRST CAMPAIGN

generated_at_utc = 2026-10-08T12:16:20Z (computed, not authored)
head_at_run = c9d4a55a9da5f0a3eb10145ada0601b59132fd1e
campaign_status = **DISCOVERY_CAMPAIGN_FAILED**
discovery_offline_authorized = TRUE (ADR-0024)
live_trading = DISABLED
trades_authorized = 0
false_success = 0

## Candidates (frozen before evaluation; one run, no tuning)

| candidate | hypothesis | mechanism | asset | strategy | spec_sha256 | trades | OOS trades | net expectancy | net PF | verdict | failed gates |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| CAND-046-001 | HYP-001 | forced_flows | BTCUSDT | funding_capitulation | `e5e58176e4c8fb01` | 38 | 10 | -19.26 bps | 0.729 | **CANDIDATE_REJECTED** | PG-1, PG-2, PG-3, PG-4, PG-5, PG-6, PG-7, PG-8 |
| CAND-046-002 | HYP-002 | market_microstructure | ETHUSDT | settlement_dip | `3336b8f343d899af` | 75 | 23 | -49.25 bps | 0.417 | **CANDIDATE_REJECTED** | PG-1, PG-2, PG-3, PG-4, PG-5, PG-6, PG-7, PG-8 |
| CAND-046-003 | HYP-003 | institutional_constraint | BTCUSDT | weekend_rebound | `8f99b0366301a304` | 0 | 0 | n/a | n/a | **CANDIDATE_REJECTED** | PG-1, PG-2, PG-3, PG-4, PG-5, PG-6, PG-7 |

Cost model: 23.7906 bps round trip (Binance Spot VIP0 taker, ~1,000 USD notional, COST_MODEL_V3) and 1.5x = 35.6859 bps in the stress column. Long/cash only: the runtime excludes derivatives (SRC-02) and spot cannot short.

Partitions (frozen in the specs, final OOS opened once, never used for selection):

| partition | window |
| --- | --- |
| development | 2024-10-01 → 2025-07-01 |
| validation | 2025-07-01 → 2026-01-01 |
| final_oos | 2026-01-01 → 2026-10-01 |

## Gate detail (PROFITABILITY_GATE_V1, PG-1..PG-11)

### CAND-046-001 — CANDIDATE_REJECTED

| gate | requirement | pass | observed |
| --- | --- | --- | --- |
| PG-1 | net expectancy > 0 | False | -0.001926 |
| PG-2 | OOS net > 0 | False | -0.0983815 |
| PG-3 | PF >= 1.10 | False | 0.728793 |
| PG-4 | sample >= 100 total and >= 30 OOS | False | {'total': 38, 'oos': 10} |
| PG-5 | positive in every partition | False | {'development': (19, 0.08455765347026321), 'validation': (8, -0.06531844991685452), 'final_oos': (10, -0.09838148395466174)} |
| PG-6 | block-bootstrap LCB > 0 | False | -0.00877928 |
| PG-7 | 1.5x cost stress > 0 | False | -0.00311553 |
| PG-8 | no risk-engine violation (<=1x, DD <= 10%) | False | 0.156705 |
| PG-9 | no single trade > 40% and no quarter > 60% of positive net | True | {'trade_share': 0.21779980674065177, 'quarter_share': 0.5576017838087776, 'trade_index': 2} |
| PG-10 | multiple-testing correction applied | True | {'trials': 3, 'alpha': 0.016666666666666666} |
| PG-11 | no look-ahead / PIT violation | True | 0 |

### CAND-046-002 — CANDIDATE_REJECTED

| gate | requirement | pass | observed |
| --- | --- | --- | --- |
| PG-1 | net expectancy > 0 | False | -0.00492486 |
| PG-2 | OOS net > 0 | False | -0.0742162 |
| PG-3 | PF >= 1.10 | False | 0.417033 |
| PG-4 | sample >= 100 total and >= 30 OOS | False | {'total': 75, 'oos': 23} |
| PG-5 | positive in every partition | False | {'development': (34, -0.10731876741307465), 'validation': (18, -0.18782972789153296), 'final_oos': (23, -0.07421615521000612)} |
| PG-6 | block-bootstrap LCB > 0 | False | -0.0100218 |
| PG-7 | 1.5x cost stress > 0 | False | -0.00611439 |
| PG-8 | no risk-engine violation (<=1x, DD <= 10%) | False | 0.361749 |
| PG-9 | no single trade > 40% and no quarter > 60% of positive net | True | {'trade_share': 0.09729123091364227, 'quarter_share': 0.2657661451697813, 'trade_index': 15} |
| PG-10 | multiple-testing correction applied | True | {'trials': 3, 'alpha': 0.016666666666666666} |
| PG-11 | no look-ahead / PIT violation | True | 0 |

### CAND-046-003 — CANDIDATE_REJECTED

| gate | requirement | pass | observed |
| --- | --- | --- | --- |
| PG-1 | net expectancy > 0 | False | None |
| PG-2 | OOS net > 0 | False | 0 |
| PG-3 | PF >= 1.10 | False | None |
| PG-4 | sample >= 100 total and >= 30 OOS | False | {'total': 0, 'oos': 0} |
| PG-5 | positive in every partition | False | {'development': (0, 0), 'validation': (0, 0), 'final_oos': (0, 0)} |
| PG-6 | block-bootstrap LCB > 0 | False | None |
| PG-7 | 1.5x cost stress > 0 | False | None |
| PG-8 | no risk-engine violation (<=1x, DD <= 10%) | True | 0 |
| PG-9 | no single trade > 40% and no quarter > 60% of positive net | True | {'trade_share': 0.0, 'quarter_share': 0.0, 'trade_index': -1} |
| PG-10 | multiple-testing correction applied | True | {'trials': 3, 'alpha': 0.016666666666666666} |
| PG-11 | no look-ahead / PIT violation | True | 0 |

## Stop rule

- NONE — a failed campaign ends; no new hypotheses are generated
- Builder and verifier are different programs (`scripts/rfc046_campaign_verify.py`).
- A rejection is recorded evidence, not a failure to hide.

## Standing state (unchanged by this run)

```text
G_BUSINESS_REENTRY != PASS
LIVE_TRADING = DISABLED
TRADES_AUTHORIZED = 0
PROFITABILITY_VERIFIED = FALSE
```
