# RFC-EXCHANGE-CONFORMANCE-01 — Exchange Adapter Conformance Contract

Status: **DRAFT** (contract only; no implementation in this checkpoint)
Checkpoint: EXTERNAL-AUDIT-RECONCILIATION-01
Audited HEAD: `a282fcc`
Directive 16: create contract only unless implementation is trivial. Do not import vn.py.

## 1. Problem

Adapter capabilities exist but are not pinned by a unified conformance suite:

- `market_data/types.py` — Protocol with `create_order` / `cancel_order` /
  `client_order_id` propagation.
- `market_data/exchange_connector.py` — CCXT connector with idempotent
  retries (tenacity), sandbox, exchange whitelist; generates cloid only when
  the caller does not supply one.
- `market_data/bitunix.py` / `bitunix_futures.py` — loud-fail when
  `client_order_id` cannot be correlated (spot client), `clientId` echo for
  futures idempotency.
- Tests: `tests/unit/market_data/` (7 files) cover individual behaviors; no
  cross-adapter conformance suite exists.

## 2. Contract: common future adapter capabilities

Every conforming adapter MUST define behavior for:

| Capability | Contract |
| --- | --- |
| identity | stable adapter id + venue id; reported in every result |
| metadata | instrument metadata: symbol, precision, min size, fees schedule |
| account | account/balance snapshot (read-only) |
| positions | current positions with entry price, size, side |
| orders | open orders query by `client_order_id` AND `venue_order_id` |
| fills | fills with stable `venue_fill_id`; delivery may duplicate/reorder |
| submit | accepts `client_order_id`; echoes it back; never invents one when given |
| query | order state query by stable identity (for ACK_UNKNOWN recovery) |
| cancel | cancel by id; returns definitive outcome or uncertainty (never silent) |
| reconnect | reconnect policy with resubscribe + state revalidation |
| reconciliation | open-orders + positions snapshot for orphan/startup reconciliation |
| stale behavior | explicit staleness signal for feeds; no silent stale pricing |
| timeouts | explicit timeout classification: transport vs acknowledged |
| rate limits | deterministic backoff; no unbounded retry |
| error normalization | venue errors mapped to a canonical error taxonomy |

## 3. Conformance test harness (future)

`tests/unit/market_data/conformance/` — a parametrized suite run against every
registered adapter + a fake adapter reference implementation:

- submit echoes `client_order_id`
- duplicate submit with same `client_order_id` -> single economic order
- fills delivered twice -> applied once
- cancel timeout -> uncertainty, not assumed-cancelled
- reconnect -> no lost orders/positions
- error normalization -> canonical taxonomy

## 4. Non-goals

- No vn.py import or code adoption (pattern reference only, per directive 17).
- No live adapter enablement; LIVE remains DISABLED.
- No change to existing adapters in this checkpoint.

## 5. Decision

Contract recorded. Implementation deferred; existing adapters already satisfy
the identity/submit/idempotency subset per `GAP_MATRIX.md` #13.