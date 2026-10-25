"""DEF-RUN-017 — la contabilidad, atacada desde el contrato.

Cada prueba construye un ledger mínimo con su cadena hash correcta y comprueba una cosa:
que la reconstrucción **recalcula** el dinero desde precios y cantidades, y que una sola
mentira (un cierre de más, una comisión cambiada, un coste contado dos veces, una posición
abierta sin marca) tumba una comprobación concreta.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from trading_bot.vision.economic_audit import (
    GENESIS,
    EconomicContractError,
    FillRecord,
    attribute,
    dec,
    line_hash,
    opinion_id,
    pair_trades,
    read_ledger,
    reconstruct,
    verify_chain,
)

SYMBOL = "BTC/USDT"
CHART = "a" * 64


def build_ledger(
    path: Path,
    *,
    side: str = "buy",
    entry_price: float = 100.0,
    exit_price: float = 99.0,
    entry_reference: float = 99.976,
    exit_reference: float = 99.024,
    quantity: float = 5.0,
    fee: float = 0.5,
    with_close: bool = True,
    duplicate_close: bool = False,
    age_ms: int = 1_000,
    decision_ts_ms: int = 1_000_000,
    quote_ts_ms: int = 1_060_000,
    run_end_override: dict[str, Any] | None = None,
) -> Path:
    """Un run de una sola opinión con números consistentes y cadena válida."""
    signed = quantity if side == "buy" else -quantity
    gross = signed * (exit_price - entry_price)
    reference_gross = signed * (exit_reference - entry_reference)
    slippage = reference_gross - gross
    fees = 2 * fee
    net = gross - fees
    entries: list[tuple[str, dict[str, Any]]] = [
        (
            "RUN",
            {
                "book_id": "mini",
                "equity_usdt": 10_000.0,
                "dataset": {
                    SYMBOL: {
                        "bars": 10,
                        "first_open_utc": "2021-01-04T00:00:00Z",
                        "last_open_utc": "2021-01-04T00:10:00Z",
                        "sha256": "b" * 64,
                    }
                },
                "lane": {"max_opinion_age_ms": 60_000, "timeframe": "1m"},
                "provider": {"provider": "strategy-signal"},
                "risk_policy": {"max_risk_per_trade_pct": 0.25},
            },
        ),
        (
            "DECISION",
            {
                "intent": "OPEN_LONG" if side == "buy" else "OPEN_SHORT",
                "chart": {"sha256": CHART, "symbol": SYMBOL, "timeframe": "1m"},
                "decision": {
                    "action": "LONG" if side == "buy" else "SHORT",
                    "horizon_bars": 8,
                    "invalidation": "fast EMA",
                    "invalidation_price": 98.0,
                    "confidence": 0.5,
                },
                "coherence_reason": "MODEL_LONG",
            },
        ),
        (
            "DECISION_OUTCOME",
            {
                "decision_seq": 2,
                "intent": "OPEN_LONG" if side == "buy" else "OPEN_SHORT",
                "approved": True,
                "executed": True,
                "phase": "OPEN_ENTRY",
            },
        ),
        (
            "FILL",
            {
                "position_id": "pos-1",
                "decision_seq": 2,
                "quantity": quantity,
                "entry_price": entry_price,
                "reference_price": entry_reference,
                "entry_commission_usdt": fee,
                "commission_bps": 10.0,
                "side": side,
                "intent": "OPEN_LONG" if side == "buy" else "OPEN_SHORT",
                "symbol": SYMBOL,
                "quote_ts_ms": quote_ts_ms,
                "ts_ms": quote_ts_ms,
                "received_at_ms": decision_ts_ms,
                "decision_ts_ms": decision_ts_ms,
                "opinion_age_ms": age_ms,
                "stop_distance_bps": 25.0,
                "round_trip_cost_bps": 24.79,
                "ts_utc": "2021-01-04T00:01:00Z",
            },
        ),
    ]
    if with_close:
        close = {
            "position_id": "pos-1",
            "quantity": quantity,
            "entry_price": entry_price,
            "exit_price": exit_price,
            "exit_reference_price": exit_reference,
            "entry_commission_usdt": fee,
            "exit_commission_usdt": fee,
            "commissions_usdt": fees,
            "gross_pnl_usdt": gross,
            "pnl_net_usdt": net,
            "execution_cost_usdt": slippage,
            "exit_reason": "stop_loss",
            "ts_ms": quote_ts_ms + 60_000,
            "bars_held": 1,
        }
        entries.append(("CLOSE", close))
        if duplicate_close:
            entries.append(("CLOSE", dict(close)))
    run_end = {
        "kind": "RUN_END",
        "book_id": "mini",
        "calls": 1,
        "fills": 1,
        "closed_trades": 1 if with_close else 0,
        "pnl_realised_usdt": net if with_close else 0.0,
        "net_realised_usdt": round(net, 6) if with_close else 0.0,
        "costs_realised_usdt": fees + (slippage if with_close else 0.0),
        "marked_equity_usdt": 10_000.0 + (net if with_close else 0.0),
        "gross_realised_usdt": round(gross, 6) if with_close else 0.0,
        "accounting": {"initial_equity_usdt": 10_000.0, "mark_prices": {SYMBOL: 99.5}},
        "opinion_accounting": {"generated": 1, "unrecorded": [], "duplicate_terminals": []},
    }
    if run_end_override:
        run_end.update(run_end_override)
    entries.append(("RUN_END", run_end))

    prev = GENESIS
    lines: list[str] = []
    holder: dict[str, Any] = {}
    #: La cadena se calcula en dos pasadas: primero el contenido, después los hashes, porque
    #: una fila puede necesitar el ``seq`` de otra (los DECISION_OUTCOME apuntan a su opinión).
    for seq, (kind, payload) in enumerate(entries, start=1):
        entry = {"kind": kind, "recorded_at_utc": "2021-01-04T00:00:00Z", **payload}
        digest = line_hash(seq, prev, entry)
        lines.append(
            json.dumps(
                {"seq": seq, "prev_sha256": prev, "entry": entry, "sha256": digest},
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        prev = digest
    holder["lines"] = lines
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    return path


# -- contrato ------------------------------------------------------------------


def test_money_is_decimal_and_refuses_booleans():
    assert dec(0.1) + dec(0.2) == Decimal("0.3")
    with pytest.raises(EconomicContractError) as error:
        dec(True)
    assert error.value.code == "NOT_A_NUMBER"


def test_a_fill_without_a_side_is_refused():
    with pytest.raises(EconomicContractError) as error:
        FillRecord.from_entry(
            {
                "position_id": "p",
                "decision_seq": 1,
                "quantity": 1.0,
                "entry_price": 1.0,
                "reference_price": 1.0,
                "entry_commission_usdt": 0.1,
                "intent": "OPEN_LONG",
            },
            opinions={},
        )
    assert error.value.code == "FILL_MISSING_FIELD"


def test_a_zero_quantity_is_refused():
    with pytest.raises(EconomicContractError) as error:
        FillRecord.from_entry(
            {
                "position_id": "p",
                "decision_seq": 1,
                "quantity": 0.0,
                "entry_price": 1.0,
                "reference_price": 1.0,
                "entry_commission_usdt": 0.1,
                "side": "buy",
                "intent": "OPEN_LONG",
            },
            opinions={},
        )
    assert error.value.code == "NON_POSITIVE_QTY"


def test_the_opinion_identity_is_the_image_and_the_answer():
    first = {
        "chart": {"sha256": CHART, "symbol": SYMBOL, "timeframe": "1m"},
        "decision": {"action": "LONG", "horizon_bars": 8, "confidence": 0.5},
    }
    second = json.loads(json.dumps(first))
    second["decision"]["action"] = "SHORT"
    assert opinion_id(first) == opinion_id(first)
    assert opinion_id(first) != opinion_id(second)


# -- reconstrucción --------------------------------------------------------------


def test_a_long_round_trip_is_recomputed_from_prices(tmp_path):
    path = build_ledger(tmp_path / "long.jsonl")
    run = reconstruct(path, source_commit="test")
    trade = run.trades[0]
    assert run.status == "PASS", run.failed
    assert trade.gross_pnl_quote == Decimal("-5.00000000")
    assert trade.fees_quote == Decimal("1.0")
    assert trade.realized_pnl_quote == Decimal("-6.00000000")
    assert run.totals["net_realised_usdt"] == "-6.00000000"
    #: comisiones 1,00 + slippage 0,24 (2,4 bps por lado sobre 5 x 100)
    assert run.totals["costs_total_usdt"] == "1.24000000"


def test_a_short_round_trip_has_the_same_sign_behaviour(tmp_path):
    """Un corto que sube pierde; el signo no se invierte por comodidad."""
    path = build_ledger(
        tmp_path / "short.jsonl",
        side="sell",
        entry_price=100.0,
        exit_price=101.0,
        entry_reference=100.024,
        exit_reference=100.976,
    )
    run = reconstruct(path, source_commit="test")
    assert run.status == "PASS", run.failed
    assert run.trades[0].realized_pnl_quote == Decimal("-6.00000000")


def test_a_position_open_at_the_cutoff_is_marked_and_not_counted_as_realised(tmp_path):
    path = build_ledger(tmp_path / "open.jsonl", with_close=False, run_end_override={
        "pnl_realised_usdt": 0.0,
        "net_realised_usdt": 0.0,
        "costs_realised_usdt": 0.0,
        "marked_equity_usdt": 10_000.0 + (5.0 * (99.5 - 100.0)) - 0.5,
    })
    run = reconstruct(path, source_commit="test", mark_price=Decimal("99.5"))
    assert run.status == "PASS", run.failed
    assert run.trades[0].terminal_status == "OPEN_AT_CUTOFF"
    assert run.trades[0].realized_pnl_quote == Decimal("0")
    assert run.totals["unrealised_at_cutoff_usdt"] == "-3.00000000"
    assert run.totals["net_realised_usdt"] == "0.00000000"


def test_an_open_position_without_a_mark_is_a_failure_not_a_zero(tmp_path):
    """Sin precio de marca (ni del llamante ni del ledger) no se inventa un cero."""
    path = build_ledger(
        tmp_path / "open.jsonl",
        with_close=False,
        run_end_override={"accounting": {"initial_equity_usdt": 10_000.0}},
    )
    run = reconstruct(path, source_commit="test")
    assert run.status == "FAIL"
    assert "OPEN_POSITIONS_MARKED" in {check["code"] for check in run.failed}


def test_a_duplicate_close_is_named(tmp_path):
    path = build_ledger(tmp_path / "dup.jsonl", duplicate_close=True)
    run = reconstruct(path, source_commit="test")
    codes = {check["code"] for check in run.failed}
    assert "NO_DUPLICATE_CLOSE" in codes
    assert "RUN_END_COUNTERS" not in codes


def test_a_tampered_byte_breaks_the_chain(tmp_path):
    path = build_ledger(tmp_path / "tampered.jsonl")
    lines = path.read_text(encoding="utf-8").splitlines()
    lines[3] = lines[3].replace('"quantity":5.0', '"quantity":5.5')
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    chain = verify_chain(read_ledger(path))
    assert chain["ok"] is False
    assert chain["reason"].startswith("TAMPERED_LINE")


def test_a_cost_counted_twice_is_caught(tmp_path):
    """net = gross - fees - slippage contaría el slippage dos veces."""
    path = build_ledger(tmp_path / "double.jsonl")
    lines = path.read_text(encoding="utf-8").splitlines()
    record = json.loads(lines[4])
    entry = record["entry"]
    entry["pnl_net_usdt"] = entry["gross_pnl_usdt"] - entry["commissions_usdt"] - entry["execution_cost_usdt"]
    record["entry"] = entry
    record["sha256"] = line_hash(record["seq"], record["prev_sha256"], entry)
    lines[4] = json.dumps(record, sort_keys=True, separators=(",", ":"))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    run = reconstruct(path, source_commit="test")
    codes = {check["code"] for check in run.failed}
    assert "LEDGER_FIELDS_MATCH_RECOMPUTATION" in codes


def test_a_run_end_that_claims_another_number_is_refused(tmp_path):
    path = build_ledger(
        tmp_path / "lie.jsonl", run_end_override={"pnl_realised_usdt": -1.0}
    )
    run = reconstruct(path, source_commit="test")
    codes = {check["code"] for check in run.failed}
    assert "RUN_END_NET_RECONCILED" in codes


def test_a_fill_older_than_the_declared_window_is_refused(tmp_path):
    path = build_ledger(tmp_path / "late.jsonl", age_ms=61_000)
    run = reconstruct(path, source_commit="test")
    assert "FILL_WITHIN_OPINION_TTL" in {check["code"] for check in run.failed}


def test_a_fill_priced_before_its_answer_is_refused(tmp_path):
    path = build_ledger(
        tmp_path / "before.jsonl", decision_ts_ms=2_000_000, quote_ts_ms=1_060_000
    )
    run = reconstruct(path, source_commit="test")
    assert "FILL_AFTER_ANSWER" in {check["code"] for check in run.failed}


# -- emparejamiento --------------------------------------------------------------


def test_pairs_are_matched_by_opinion_and_everything_else_is_kept(tmp_path):
    base = reconstruct(build_ledger(tmp_path / "b.jsonl"), source_commit="test")
    other = reconstruct(
        build_ledger(tmp_path / "c.jsonl", entry_price=101.0, exit_price=99.4,
                     entry_reference=100.976, exit_reference=99.424),
        source_commit="test",
    )
    pairs = pair_trades(base, other, scenario="s")
    assert len(pairs) == 1
    assert pairs[0].match_status == "MATCHED"
    assert pairs[0].baseline_net != pairs[0].candidate_net


def test_a_different_chart_is_a_different_opinion(tmp_path):
    base = reconstruct(build_ledger(tmp_path / "b.jsonl"), source_commit="test")
    path = tmp_path / "c.jsonl"
    build_ledger(path)
    lines = path.read_text(encoding="utf-8").splitlines()
    for index, line in enumerate(lines):
        record = json.loads(line)
        if record["entry"].get("chart", {}).get("sha256") == CHART:
            record["entry"]["chart"]["sha256"] = "c" * 64
            lines[index] = json.dumps(
                {
                    "seq": record["seq"],
                    "prev_sha256": record["prev_sha256"],
                    "entry": record["entry"],
                    "sha256": line_hash(record["seq"], record["prev_sha256"], record["entry"]),
                },
                sort_keys=True,
                separators=(",", ":"),
            )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    other = reconstruct(path, source_commit="test")
    result = attribute({"s": base}, {"s": other})
    assert result["totals"]["matched_pairs"] == 0
    assert result["totals"]["baseline_only"] == 1
    assert result["totals"]["candidate_only"] == 1


def test_the_delta_is_gross_minus_fees_and_closes(tmp_path):
    base = reconstruct(build_ledger(tmp_path / "b.jsonl"), source_commit="test")
    other = reconstruct(
        build_ledger(tmp_path / "c.jsonl", exit_price=98.0, exit_reference=98.024),
        source_commit="test",
    )
    result = attribute({"s": base}, {"s": other})
    totals = result["totals"]
    assert Decimal(totals["delta_net_usdt"]) == Decimal(totals["delta_gross_usdt"]) - Decimal(
        totals["delta_fees_usdt"]
    )
    assert result["per_scenario"]["s"]["reconciled"] is True
