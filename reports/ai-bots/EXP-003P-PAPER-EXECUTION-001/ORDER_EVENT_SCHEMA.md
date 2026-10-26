# ORDER EVENT SCHEMA — EXP-003P

> Generated from `src/trading_bot/paper/lifecycle/contracts.py`; schema version `AI_BOTS_003P_ENVELOPE_V1`.

## Provenance

| provenance | allowed `provider_environment` | what it proves |
| --- | --- | --- |
| `OFFLINE_SIMULATED` | `OFFLINE` | what this code does with a given input; never that a venue accepted it |
| `REPLAY_CAPTURED` | `OFFLINE, REPLAY` | that a captured session replays identically; not a new order or fill |
| `VENUE_REPORTED_PAPER` | `PAPER, TESTNET` | that a paper/testnet venue reported the event; not a real fill |

## ExecutionEnvelope

| field | type | required |
| --- | --- | --- |
| `run_id` | `str` | True |
| `commit_sha` | `str` | True |
| `config_digest` | `str` | True |
| `client_order_id` | `str` | True |
| `event_id` | `str` | True |
| `asset` | `str` | True |
| `strategy_id` | `str` | True |
| `adapter_id` | `str` | True |
| `event_type` | `str` | True |
| `event_time_utc` | `str` | True |
| `received_time_utc` | `str` | True |
| `clock_source` | `str` | True |
| `provenance` | `str` | True |
| `provider_environment` | `str` | True |
| `decision_id` | `str | None` | False |
| `proposal_id` | `str | None` | False |
| `signal_id` | `str | None` | False |
| `venue_order_id` | `str | None` | False |
| `correlation_parent_id` | `str | None` | False |
| `schema_version` | `str` | False |
| `payload` | `dict[str, Any]` | False |

## OrderIntent

| field | type | required |
| --- | --- | --- |
| `client_order_id` | `str` | True |
| `asset` | `str` | True |
| `side` | `str` | True |
| `order_type` | `str` | True |
| `quantity` | `float` | True |
| `strategy_id` | `str` | True |
| `decision_time_utc` | `str` | True |
| `data_cutoff_utc` | `str` | True |
| `limit_price` | `float | None` | False |
| `time_in_force` | `str | None` | False |
| `risk_evaluation_id` | `str` | False |
| `policy_verification_id` | `str` | False |
| `notional_usdt` | `float` | False |
| `stop_loss_pct` | `float | None` | False |
| `take_profit_pct` | `float | None` | False |
| `decision_id` | `str | None` | False |
| `proposal_id` | `str | None` | False |
| `signal_id` | `str | None` | False |

## FillFact

| field | type | required |
| --- | --- | --- |
| `fill_key` | `str` | True |
| `client_order_id` | `str` | True |
| `asset` | `str` | True |
| `side` | `str` | True |
| `filled_quantity` | `float` | True |
| `fill_price` | `float` | True |
| `fee_amount` | `float` | True |
| `fee_currency` | `str` | True |
| `event_time_utc` | `str` | True |
| `provenance` | `str` | True |
| `provider_environment` | `str` | True |
| `raw_event_digest` | `str` | True |
| `venue_order_id` | `str | None` | False |
| `fee_conversion_rate` | `float | None` | False |
| `fee_conversion_currency` | `str | None` | False |

## ReconciliationResult

| field | type | required |
| --- | --- | --- |
| `run_id` | `str` | True |
| `source` | `str` | True |
| `as_of_time` | `str` | True |
| `local_order_state` | `dict[str, Any]` | True |
| `provider_order_state` | `dict[str, Any] | None` | True |
| `local_qty` | `float` | True |
| `provider_qty` | `float | None` | True |
| `cash_delta` | `float | None` | True |
| `position_delta` | `float | None` | True |
| `fee_delta` | `float | None` | True |
| `differences` | `tuple[dict[str, Any], ...]` | True |
| `result` | `str` | True |
| `evidence_refs` | `tuple[str, ...]` | False |

## Event types and the state they assert

| event_type | asserted state |
| --- | --- |
| `ORDER_CREATED` | `CREATED` |
| `ORDER_RISK_REJECTED` | `RISK_REJECTED` |
| `ORDER_SUBMITTED` | `SUBMITTING` |
| `ORDER_ACKNOWLEDGED` | `ACKNOWLEDGED` |
| `ORDER_PARTIALLY_FILLED` | `PARTIALLY_FILLED` |
| `ORDER_FILLED` | `FILLED` |
| `ORDER_CANCELED` | `CANCELED` |
| `ORDER_REJECTED` | `REJECTED` |
| `ORDER_EXPIRED` | `EXPIRED` |
| `ORDER_UNKNOWN` | `UNKNOWN` |
| `ORDER_STATE_RESOLVED` | `ACKNOWLEDGED` |

## Rules

- event_id is deduplicated inside (provenance, provider_environment)
- an envelope is refused before persistence if provenance and environment disagree
- LIVE is never a paper provider_environment
- received_time_utc >= event_time_utc >= decision_time_utc >= data_cutoff_utc
- a fill key books exactly once inside its provenance namespace
- ACK never moves quantity; only a fill fact does
- a terminal state is never reopened; a contradiction is audited, not applied
- UNKNOWN blocks any further send for that intent until a primary source resolves it

## Defect vocabulary

`DUPLICATE_EVENT`, `DUPLICATE_FILL`, `OUT_OF_ORDER_EVENT`, `FILL_WITHOUT_ACK`, `ILLEGAL_TRANSITION`, `TERMINAL_STATE_MUTATION`, `QUANTITY_EXCEEDED`, `NEGATIVE_QUANTITY`, `CAUSALITY_VIOLATION`, `PROVENANCE_MISMATCH`, `DATA_INTEGRITY_FAIL`, `RISK_GATE_VIOLATION`, `LIVE_MODE_FORBIDDEN`, `EXIT_WITHOUT_POSITION`, `FEE_UNPRICED`, `LEDGER_MISMATCH`, `UNKNOWN_REQUIRES_RECONCILIATION`
