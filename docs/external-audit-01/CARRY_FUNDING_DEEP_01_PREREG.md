# CARRY-FUNDING-DEEP-01 — PREREGISTRATION (no execution)

Checkpoint: **MA-DIRECTION-ARBITRATION-AND-POC02-REPAIR-01** (TRACK I)
Status: **PREREGISTERED — NOT STARTED.** No research executes in this
checkpoint; this document freezes the contracts required before any run.

## 1. Authoritative source finding (carried from POC02-OBSERVATION-01, §15)

The Binance USD-M public funding-rate endpoint (`/fapi/v1/fundingRate`)
returns **1000 observations per page** and paginates to full history depth of
approximately **2019-09-10 → present** (probed live on 2026-09-09; see
`FUNDING_HISTORY_SOURCE_PROPOSAL.md`). The Discovery-Batch-02
`INSUFFICIENT_SAMPLE` verdict was a fetch-page artifact (`limit` param), not a
true data ceiling. The old invalid fingerprint is discarded — never reused.

## 2. Preregistered contracts (all must be validated BEFORE execution)

| Contract | Requirement |
| --- | --- |
| PAGINATION | Explicit `startTime` cursor pagination; page size 1000; loop until `now`; assert continuity (no gaps > 1 funding interval) and monotone timestamps. |
| UNITS | Funding rate stored as decimal fraction (8-hour rate, as returned); any annualization happens ONLY in feature code with an explicit named transform. |
| TIMESTAMP | `fundingTime` semantics = instant the rate applies (PIT boundary). Store raw exchange ms; derive UTC datetimes once. |
| PIT | Every candidate feature must provably use only rows with `fundingTime <= decision_time`. PIT proof = per-feature test with a decision-time boundary fixture. |
| FINGERPRINT | New dataset fingerprint: sha256 over canonicalized (symbol, fundingTime, rate) rows; recorded in the research ledger. The prior invalid fingerprint is never referenced. |
| COST | Funding cash-flow semantics: payer/receiver by sign and position side; applied at funding timestamps inside the backtest cost model, never in signal generation. |

## 3. Gate

Execution is authorized only after source, schema, timestamp semantics, PIT
semantics and cost semantics are validated and recorded in the research
ledger. Until then this checkpoint records: **CARRY_FUNDING_DEEP_PREREG = PREREGISTERED / NOT_STARTED**.
