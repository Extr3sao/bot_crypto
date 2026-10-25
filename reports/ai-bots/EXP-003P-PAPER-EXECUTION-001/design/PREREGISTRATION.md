# EXP-003P — PREREGISTRATION (frozen before the first rehearsal)

- run: `EXP-003P-PAPER-EXECUTION-001`
- frozen at: `2026-10-21T00:00:00Z`
- mode: `OFFLINE_SIMULATED`; live enabled: `False`; live orders allowed: `0`
- dependency: `EXP-003O-INDEPENDENT-SIGNAL-VERIFICATION-001` (`PASS_PARTIAL_INCOMPLETE_REAL_DATA`)
- config digest: `sha256:4f93519d8fc6b4040e82df6f6c495671ae5f510fe47ee246937a4400baa071fa`
- protocol sha256: `9f349bda6f2dbbfea5aed8b27418ffd9d92d59cdf26068172fad5ba841d00c9a`

## What is frozen

| item | value |
| --- | --- |
| runtime entrypoint | `scripts/exp_003p_rehearsal.py` |
| execution boundary | `trading_bot.paper.broker.PaperBroker` |
| window | `2026-07-26T00:00:00Z` → `2026-08-06T00:00:00Z` |
| symbols | `BTCUSDT, ETHUSDT, SOLUSDT` |
| timeframe / cadence | `1h` / every `4` bars |
| equity | `10000.0` USDT (paper) |

## Success rules

### OFFLINE_RUNTIME_VALIDATION
- **requires**: ['two rehearsals produce the same trace digest', 'every persisted event carries provenance, adapter and correlation', 'no illegal transition and no unexplained anomaly in the runtime phase', 'reconciliation against the broker book is PASS', 'scenario reconciliation against the venue snapshot is PASS', 'live_orders == 0']
- **on_failure**: FAIL

### PAPER_VALIDATION
- **requires**: ['an authorised paper provider, endpoint and account already configured', 'at least one fill observed from that provider in the evaluated cycle']
- **on_absence**: BLOCKED_NOT_CONFIGURED
- **note**: No paper venue is configured in this workspace. The phase therefore reports BLOCKED and does not relabel an offline simulation as observed paper.

### FINAL_STATUS
- PARTIAL unless PAPER_VALIDATION is PASS

## Scenario scripts

| id | mode | side | quantity | tranches | delays (ms) | duplicates | reorder |
| --- | --- | --- | --- | --- | --- | --- | --- |
| S01_FULL_FILL | FULL_FILL | buy | 1.0 | [1.0] | [120] | False | False |
| S02_PARTIAL_THEN_FILL | PARTIAL_THEN_FILL | buy | 2.0 | [0.4, 0.6] | [90, 240] | False | False |
| S03_PARTIAL_THEN_CANCEL | PARTIAL_THEN_CANCEL | sell | 2.0 | [0.5] | [150] | False | False |
| S04_DUPLICATE_DELIVERY | FULL_FILL | buy | 1.5 | [1.0] | [75] | True | False |
| S05_OUT_OF_ORDER | PARTIAL_THEN_FILL | buy | 1.0 | [0.5, 0.5] | [40, 80] | False | True |
| S06_TIMEOUT_UNKNOWN | TIMEOUT_UNKNOWN | buy | 1.0 | [1.0] | [100] | False | False |
| S07_REJECT | REJECT_AT_SUBMIT | buy | 1.0 | [1.0] | [100] | False | False |
| S08_ACK_WITHOUT_FILL | ACK_WITHOUT_FILL | buy | 1.0 | [1.0] | [100] | False | False |

## Declared limits (frozen with the protocol, not added afterwards)

- the offline venue is a test double, not a paper broker; a fill from it proves code semantics and never venue acceptance
- the broker-observed events stamp the decision instant with the booking instant of the fill; the payload says so instead of inventing a decision clock
- the recorded risk gate on broker-observed events is the broker's notional guard, not a copy of the RiskManager transcript
- PAPER_VALIDATION stays BLOCKED until an authorised paper provider exists
- organisational independence is false: the same agent wrote producer, verifier and controls

## Sequence

1. this file and `PROTOCOL.json` are written before any rehearsal;
2. the rehearsal records the protocol digest it ran under;
3. `--check` refuses a protocol whose bytes moved after that record.
