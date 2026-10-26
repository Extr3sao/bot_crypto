"""Reconciliation: what the events say, what the ledger booked, what the source reports.

The three derivations are independent on purpose:

* the **projection** walks the order state machine over the preserved events;
* the **ledger** books fills exactly once into cash, position, fees and realised PnL;
* the **snapshot** is the source's own tally -- the offline venue's emitted messages, or
  the paper broker's book.

A ``PASS`` is only possible when every source needed for the comparison is present and
every number agrees. A missing primary source is ``INCOMPLETE``; an unexplained monetary
difference is ``FAIL``. There is no tolerance that is widened to fit an observation.
"""

from __future__ import annotations

from typing import Any

from .contracts import ReconciliationResult
from .store import FillLedger, Projection

#: Quantities are decimals in a float world; this is a representation epsilon, not a
#: policy tolerance -- it is 12 orders of magnitude below one satoshi of a unit price.
EPSILON: float = 1e-9


def _diff(
    code: str, scope: str, subject: str, local: Any, provider: Any
) -> dict[str, Any]:
    return {"code": code, "scope": scope, "subject": subject, "local": local, "provider": provider}


def _close(left: float | None, right: float | None) -> bool:
    if left is None or right is None:
        return False
    return abs(float(left) - float(right)) <= EPSILON


def _ledger_by_order(ledger: FillLedger) -> dict[str, dict[str, float]]:
    """Aggregate the applied fills per venue order id (client id when there is none)."""

    totals: dict[str, dict[str, float]] = {}
    for fill in ledger.raw_fills():
        order = str(fill.get("venue_order_id") or fill.get("client_order_id"))
        quantity = float(fill["filled_quantity"])
        signed = quantity if str(fill["side"]) == "buy" else -quantity
        bucket = totals.setdefault(
            order,
            {
                "quantity": 0.0,
                "signed_quantity": 0.0,
                "notional": 0.0,
                "fees_usdt": 0.0,
                "fills": 0.0,
            },
        )
        bucket["quantity"] += quantity
        bucket["signed_quantity"] += signed
        bucket["notional"] += quantity * float(fill["fill_price"])
        if str(fill.get("fee_currency", "USDT")) == "USDT":
            bucket["fees_usdt"] += float(fill.get("fee_amount", 0.0))
        bucket["fills"] += 1
    return totals


def reconcile(
    *,
    run_id: str,
    as_of_utc: str,
    projection: Projection,
    ledger: FillLedger,
    source: str,
    venue_snapshot: dict[str, Any] | None = None,
    broker_snapshot: dict[str, Any] | None = None,
) -> ReconciliationResult:
    """Compare the three derivations and state the verdict, not the hope."""

    differences: list[dict[str, Any]] = []
    evidence: list[str] = [source]

    by_order = _ledger_by_order(ledger)
    local_orders = {
        key: {
            "state": order.state,
            "cum_filled_qty": round(order.cum_filled_qty, 12),
            "fills": len(order.fills),
            "terminal": order.terminal,
        }
        for key, order in sorted(projection.orders.items())
    }

    # -- 1. projection vs ledger ---------------------------------------------
    # The state machine's cumulative quantity must equal what the ledger booked. A
    # divergence means one of the two derivations counted an event the other refused.
    ledger_qty_by_client: dict[str, float] = {}
    for fill in ledger.raw_fills():
        key = str(fill.get("client_order_id"))
        ledger_qty_by_client[key] = ledger_qty_by_client.get(key, 0.0) + float(
            fill["filled_quantity"]
        )
    for order_key, order in sorted(projection.orders.items()):
        booked = ledger_qty_by_client.get(order.client_order_id, 0.0)
        if not _close(booked, order.cum_filled_qty):
            differences.append(
                _diff(
                    "LEDGER_MISMATCH",
                    "projection_vs_ledger",
                    order_key,
                    round(order.cum_filled_qty, 12),
                    round(booked, 12),
                )
            )

    if ledger.duplicates:
        # A duplicate that reached the ledger is not a cosmetic warning: it means the
        # idempotency gate was bypassed somewhere. The accounting is still correct (the
        # ledger refused it), and it must be reported, never hidden.
        for duplicate in ledger.duplicates:
            differences.append(
                _diff(
                    "DUPLICATE_FILL",
                    "ledger",
                    str(duplicate.get("fill_key")),
                    "refused",
                    duplicate.get("reason"),
                )
            )

    # -- 2. ledger vs the source snapshot ------------------------------------
    if venue_snapshot is None:
        return ReconciliationResult(
            run_id=run_id,
            source=source,
            as_of_time=as_of_utc,
            local_order_state=local_orders,
            provider_order_state=None,
            local_qty=round(sum(v["signed_quantity"] for v in by_order.values()), 12),
            provider_qty=None,
            cash_delta=None,
            position_delta=None,
            fee_delta=None,
            differences=tuple(differences),
            result="INCOMPLETE",
            evidence_refs=(source, "venue_snapshot=NOT_AVAILABLE"),
        )

    provider_orders: dict[str, dict[str, float]] = {}
    for order_id, row in (venue_snapshot.get("orders") or {}).items():
        provider_orders[str(order_id)] = {
            "quantity": float(row.get("quantity", 0.0)),
            "notional": float(row.get("notional", 0.0)),
            "fees_usdt": float(row.get("fees_usdt", 0.0)),
        }

    for order_id in sorted(set(provider_orders) | set(by_order)):
        local = by_order.get(order_id)
        provider = provider_orders.get(order_id)
        if local is None:
            differences.append(
                _diff("RECONCILIATION_FAIL", "ledger_vs_source", order_id, None, provider)
            )
            continue
        if provider is None:
            # The source does not know about a fill the ledger booked: that is a hard
            # failure, because the fill claims an origin the source never produced.
            differences.append(
                _diff("RECONCILIATION_FAIL", "ledger_vs_source", order_id, local, None)
            )
            continue
        if not _close(local["quantity"], provider["quantity"]):
            differences.append(
                _diff(
                    "RECONCILIATION_FAIL",
                    "ledger_vs_source",
                    order_id,
                    round(local["quantity"], 12),
                    round(provider["quantity"], 12),
                )
            )
        if not _close(round(local["notional"], 8), round(provider["notional"], 8)):
            differences.append(
                _diff(
                    "RECONCILIATION_FAIL",
                    "ledger_vs_source_notional",
                    order_id,
                    round(local["notional"], 8),
                    round(provider["notional"], 8),
                )
            )
        if not _close(round(local["fees_usdt"], 8), round(provider["fees_usdt"], 8)):
            differences.append(
                _diff(
                    "RECONCILIATION_FAIL",
                    "ledger_vs_source_fees",
                    order_id,
                    round(local["fees_usdt"], 8),
                    round(provider["fees_usdt"], 8),
                )
            )

    local_qty = round(sum(v["signed_quantity"] for v in by_order.values()), 12)
    provider_qty = round(sum(v["quantity"] for v in provider_orders.values()), 12)

    # -- 3. ledger vs the broker book (when the runtime booked it) ------------
    broker_realized: float | None = None
    if broker_snapshot is not None:
        evidence.append("broker_snapshot")
        # The broker's own ``accounting_snapshot`` reports open positions as a list with an
        # unsigned quantity and an explicit side; the ledger keeps a signed quantity.
        broker_positions: dict[str, dict[str, float]] = {}
        for row in broker_snapshot.get("open_positions") or []:
            asset = str(row.get("symbol", "")).split("/")[0]
            quantity = float(row.get("quantity", 0.0))
            signed = quantity if str(row.get("side")) == "buy" else -quantity
            bucket = broker_positions.setdefault(asset, {"quantity": 0.0})
            bucket["quantity"] += signed
        for asset, row in sorted(ledger.positions.items()):
            ledger_qty = round(float(row["quantity"]), 12)
            book_qty = round(
                float((broker_positions.get(asset) or {}).get("quantity", 0.0)), 12
            )
            if not _close(ledger_qty, book_qty):
                differences.append(
                    _diff(
                        "LEDGER_MISMATCH",
                        "ledger_vs_broker_position",
                        asset,
                        ledger_qty,
                        book_qty,
                    )
                )
        broker_realized = broker_snapshot.get("realised_pnl")
        local_realized = ledger.net_realized_pnl_usdt
        holding_something = any(
            abs(float(row["quantity"])) > EPSILON for row in ledger.positions.values()
        )
        if holding_something:
            # The two books book an open leg's entry fee at different moments (the ledger
            # at the fill, the broker at the close), so realised PnL is not comparable
            # until the book is flat. Declared, not silently skipped.
            evidence.append("realised_pnl_comparison=DEFERRED_OPEN_POSITION")
        elif (
            broker_realized is not None
            and local_realized is not None
            and not _close(round(local_realized, 6), round(float(broker_realized), 6))
        ):
            differences.append(
                _diff(
                    "LEDGER_MISMATCH",
                    "ledger_vs_broker_realized",
                    "USDT",
                    round(local_realized, 6),
                    round(float(broker_realized), 6),
                )
            )
    else:
        evidence.append("broker_snapshot=NOT_AVAILABLE")

    result = "FAIL" if differences else "PASS"
    return ReconciliationResult(
        run_id=run_id,
        source=source,
        as_of_time=as_of_utc,
        local_order_state=local_orders,
        provider_order_state={
            "orders": {
                key: {metric: round(value, 12) for metric, value in row.items()}
                for key, row in sorted(provider_orders.items())
            }
        },
        local_qty=local_qty,
        provider_qty=provider_qty,
        cash_delta=round(sum(ledger.cash.values()), 10),
        position_delta=round(
            sum(row["quantity"] for row in ledger.positions.values()), 12
        ),
        fee_delta=round(sum(ledger.fees_by_currency.values()), 10),
        differences=tuple(differences),
        result=result,
        evidence_refs=tuple(evidence),
    )


__all__ = ["EPSILON", "reconcile"]
