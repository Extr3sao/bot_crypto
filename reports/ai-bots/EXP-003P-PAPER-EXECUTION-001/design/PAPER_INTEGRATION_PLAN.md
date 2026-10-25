# PAPER INTEGRATION PLAN — WP-003P-04

> Status: `BLOCKED_NOT_CONFIGURED`. Nothing in this document was executed against a venue.
> It is the minimum plan an authorised paper integration has to satisfy, written before any
> credential exists so the plan cannot be shaped by an observed result.

## 1. What exists today, and what does not

| element | state in this workspace | evidence |
| --- | --- | --- |
| `config/runtime.yaml` `mode` | `paper`, `live_trading_enabled: false` | `evidence/BASELINE.json` `config_sha256` |
| order-submitting paper/testnet adapter | **none configured** | `provider_viability` in `evidence/BASELINE.json` |
| credentials for one | **none present** | only `.env.example` exists; no `.env`; `credential_names_present: []` |
| `PaperBroker` | in-process book; its fills are `OFFLINE_SIMULATED` by construction | `src/trading_bot/paper/broker.py` |
| `SimulatedPaperVenue` | declared test double used by the scenario phase | `src/trading_bot/paper/lifecycle/venue.py` |
| market-data sandbox (`set_sandbox_mode`) | data access only, not order submission | `src/trading_bot/market_data/exchange_connector.py` |
| lifecycle engine, store, ledger, reconciliation | executed and verified offline | `VERIFICATION.json`, `RECONCILIATION.json` |

The gap is therefore one component, not one platform: an adapter that turns an
`OrderIntent` into a real message on an authorised paper/testnet endpoint and returns the
provider's own events. Everything downstream of that adapter already exists and already
has an accepted contract.

## 2. The adapter contract (what WP-04 must implement)

```python
class PaperVenueAdapter(Protocol):
    adapter_id: str                    # e.g. "BINANCE_TESTNET", never "PAPER" for a live URL
    provider_environment: str          # "TESTNET" | "PAPER" | "DEMO"

    def submit(self, intent: OrderIntent) -> VenueAck: ...
    def poll(self, client_order_id: str) -> list[VenueMessage]: ...
    def cancel(self, client_order_id: str, venue_order_id: str | None) -> VenueMessage: ...
    def snapshot(self) -> dict[str, object]: ...
```

Non-negotiable properties:

1. **The engine stays the only writer.** The adapter returns messages; `LifecycleEngine`
   validates them and `DurableEventStore` persists them. An adapter that writes envelopes
   itself loses the hash chain and the dedupe key.
2. **Stable identity.** `client_order_id` is generated once, persisted with the intent and
   re-sent unchanged on every retry. A retry never invents a new identifier.
3. **Query before resend.** On timeout the order becomes `UNKNOWN`; the next step is
   `poll(client_order_id)`, never a new `submit`.
4. **Idempotent cancellation.** Cancelling an already terminal order returns the current
   state, not an error that would be read as "unknown".
5. **No environment guessing.** `provider_environment` comes from the configured endpoint,
   not from a flag an operator can flip at runtime; a `LIVE` endpoint must be refused at
   construction time with `LIVE_MODE_FORBIDDEN`.
6. **Redaction.** No key, secret, account id or signed URL may reach an envelope payload,
   a log line or a published artifact.

## 3. Mapping provider events to the existing envelope vocabulary

| provider event | envelope `event_type` | may it move quantity? |
| --- | --- | --- |
| order accepted / `NEW` | `ORDER_ACKNOWLEDGED` | no |
| `PARTIALLY_FILLED` | `ORDER_PARTIALLY_FILLED` | yes, by `filled_quantity` |
| `FILLED` | `ORDER_FILLED` | yes, by the delta |
| `CANCELED` / `EXPIRED` | `ORDER_CANCELED` / `ORDER_EXPIRED` | no |
| `REJECTED` | `ORDER_REJECTED` | no |
| timeout with no answer | `ORDER_UNKNOWN` | no |

`venue_order_id` and `provider_event_id` are preserved verbatim. `provenance` is
`VENUE_REPORTED_PAPER` only for a message that arrived from the endpoint; anything the
adapter derives locally stays `OFFLINE_SIMULATED`. The provenance cannot be raised by
relabelling — the contract refuses it (`NEG-14`).

## 4. Acceptance checks for the paper phase

Each check is `PASS`, `FAIL` or `INCOMPLETE` with the evidence named. No check is allowed
to pass on a default or a tolerance widened after the fact.

| id | check | evidence |
| --- | --- | --- |
| `P1` | the endpoint is a paper/testnet URL of the configured venue and the account belongs to that environment | endpoint and account proof, secrets redacted |
| `P2` | at least one `VENUE_REPORTED_PAPER` fill for an order of this cycle | `EXECUTION_TRACE.jsonl` |
| `P3` | that fill's `client_order_id` matches the submitted intent, and `venue_order_id` is the provider's | envelope correlation |
| `P4` | the provider's own snapshot, the local order projection and the ledger agree on quantity | `RECONCILIATION.json` |
| `P5` | `data_time <= decision_time <= order_intent_time` on every submitted order | verifier `V3` |
| `P6` | a forced timeout produces `UNKNOWN`, a query, and no second submit | control run in the paper cycle |
| `P7` | fees arrive in the provider's currency and are not assumed zero | ledger fees |
| `P8` | `live_orders == 0` and every envelope's `provider_environment` is paper/testnet | verifier `V7` |
| `P9` | the run is reproducible from its config digest, adapter id and recorded events | `RUN_REPORT.json` |
| `P10` | no credential-shaped string in any published artifact | verifier `V13` |

`PAPER_VALIDATION=PASS` requires `P1..P10`. A single filled order is the minimum for
`P2`; a phase that observes no fill reports `INCOMPLETE_FILL_OBSERVATION`, never `PASS`.

## 5. Authorisation and blast radius

WP-04 needs, in this order: an explicit authorisation to use a specific paper/testnet
account; credentials delivered through the environment (never committed, never pasted into
a report); a spend and rate limit declared in advance; and an operator able to revoke the
keys. Without the first item the phase stays `BLOCKED_NOT_CONFIGURED`.

This plan does not authorise: live trading, real capital, new leverage, strategy promotion,
holdout access, or any change to `config/runtime.yaml`, `config/risk.yaml` or
`config/vision.yaml`. The kill switch stays the existing one; the adapter adds no new way
to send an order.

## 6. What remains true after a successful WP-04

Observed paper execution would prove that this code can carry an order through a venue and
reconcile it. It would not prove an economic edge, and it would not make `EXP-003O`'s
missing 4h coverage or its organisational independence any better. Those stay declared.

## 7. Declared limits of this plan

- No adapter was written: writing one without an authorised endpoint would be untested code
  pretending to be readiness.
- The event names in §3 are the envelope vocabulary this repository already uses; a provider
  whose stream cannot be mapped onto them without inventing a state is not integrable
  without a contract change, and that change is out of scope here.
- The plan assumes the provider can be queried by `client_order_id`. If it cannot, every
  timeout is `UNKNOWN` and the phase stops after it, which is a real limitation of that
  provider and must be declared in the phase's own run report.
