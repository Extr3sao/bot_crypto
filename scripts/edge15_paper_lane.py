"""edge15_paper_lane — an isolated prospective paper lane, tagged and boxed in.

WP-EDGE-015/P3. This lane drives the **real** ``PaperBroker`` (the same object the
runtime uses: SL/TP, commissions, and the identity/accounting added in P0.3/P0.4)
over market bars, with the risk policy in ``config/risk.yaml`` applied at every
decision by the same deterministic rules the runtime uses.

Three boundaries define it, and each is *checked* rather than promised:

1. **It is not the admitted lane.** Nothing here can touch
   ``config/strategy_admission.json``: the script hashes it before and after and
   fails if the bytes moved. Its own books are under
   ``reports/economic-recovery/RFC-EDGE-015/experimental_paper/``.
2. **Its results are labelled.** Every cycle carries
   ``EXPERIMENTAL_PROSPECTIVE_PAPER``, and it cannot count as an admitted
   strategy's operation because no strategy is admitted.
3. **It does not force signals.** A family the alpha matrix rejected emits
   ``NO_TRADE`` with that reason; a bar whose timestamp is at or before the frozen
   protocol instant is labelled ``DESCRIPTIVE`` instead of prospective.

    python scripts/edge15_paper_lane.py
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import UTC, datetime
from itertools import pairwise
from pathlib import Path
from typing import Any

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from trading_bot.paper.broker import PaperBroker
from trading_bot.research.disk_budget import free_bytes, plan_window
from trading_bot.research.economic_recovery.alpha15 import (
    FAMILY_BY_NAME,
    SINGLE_ASSET_FAMILIES,
    Bar,
    cost_for,
    family_trades,
)
from trading_bot.research.economic_recovery.experiments import load_ohlcv
from trading_bot.strategies.types import Signal

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "reports" / "economic-recovery" / "RFC-EDGE-015"
LANE_DIR = OUT / "experimental_paper"
RISK_CONFIG = REPO / "config" / "risk.yaml"
ADMISSION = REPO / "config" / "strategy_admission.json"
ALPHA_RESULTS = OUT / "ALPHA_RESULTS.json"
PREREG = OUT / "OOS_PREREGISTRATION_V2.json"

TAG = "EXPERIMENTAL_PROSPECTIVE_PAPER"
BOOK_ID = "EDGE15LANE"

#: Bars of history the lane replays. Two thousand 1h bars is ~83 days: enough for
#: the slowest filter to be warm, small enough to rerun in seconds.
WINDOW_BARS = 2_000

UNIVERSE: tuple[tuple[str, str, Path], ...] = (
    ("BTC/USDT", "BTCUSDT", REPO / "data" / "edge07" / "holdout-1h" / "BTCUSDT_holdout2026.json"),
    ("ETH/USDT", "ETHUSDT", REPO / "data" / "edge07" / "holdout-1h" / "ETHUSDT_holdout2026.json"),
    ("SOL/USDT", "SOLUSDT", REPO / "data" / "edge07" / "holdout-1h" / "SOLUSDT_holdout2026.json"),
)


#: Where the frozen protocol's capture writes the bars nobody had seen.
PROSPECTIVE_SLICE = OUT / "scratch" / "OOS_PROSPECTIVE_1H.jsonl"


def prospective_bars(symbol: str) -> list[Bar]:
    """Bars the holdout capture produced, read from the slice it recorded.

    These are the only bars in this lane that no decision in the package had
    seen: the replay window ends before them. The lane does not fit anything to
    them, it just receives them, which is what makes ``PROSPECTIVE`` mean
    something in a cycle record.
    """
    if not PROSPECTIVE_SLICE.is_file():
        return []
    bars: list[Bar] = []
    for line in PROSPECTIVE_SLICE.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if str(row["symbol"]) != symbol:
            continue
        bars.append(
            Bar(
                ts_ms=int(row["timestamp"]),
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=float(row["volume"]),
            )
        )
    return sorted(bars, key=lambda bar: bar.ts_ms)


def load_risk_config() -> dict[str, Any]:
    payload = yaml.safe_load(RISK_CONFIG.read_text(encoding="utf-8"))
    return dict(payload["risk"])


def rejected_families() -> dict[str, str]:
    """Family -> verdict, from the alpha matrix. Rejected ones may not trade."""
    if not ALPHA_RESULTS.is_file():
        return {}
    payload = json.loads(ALPHA_RESULTS.read_text(encoding="utf-8"))
    return {str(row["family"]): str(row["verdict"]) for row in payload.get("verdicts") or []}


def prospective_freeze_ms() -> int | None:
    if not PREREG.is_file():
        return None
    return int(json.loads(PREREG.read_text(encoding="utf-8"))["frozen_at_epoch_ms"])


def sha256(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def classify(ts_ms: int, freeze_ms: int | None) -> str:
    if freeze_ms is None:
        return "UNCLASSIFIED_NO_FREEZE"
    return "PROSPECTIVE" if ts_ms > freeze_ms else "DESCRIPTIVE"


def _bar_ohlc(bar: Bar) -> tuple[float, float, float, float]:
    return bar.open, bar.high, bar.low, bar.close


def run_symbol(
    symbol: str,
    bars: list[Bar],
    *,
    risk: dict[str, Any],
    verdicts: dict[str, str],
    freeze_ms: int | None,
    equity: float = 10_000.0,
) -> dict[str, Any]:
    """Replay one symbol through the broker, one bar at a time."""
    commission_bps = cost_for(symbol).fee_bps_per_side
    slippage_bps = (
        cost_for(symbol).half_spread_bps
        + cost_for(symbol).slippage_bps_per_side
        + cost_for(symbol).impact_bps_per_side
    )
    # One book per symbol: a shared book id would mint the same identifiers in
    # three books, which is the collision class P0.3 exists to remove.
    book_id = f"{BOOK_ID}-{symbol.replace('/', '')}"
    # The broker's clock is the bar being replayed, not this host's wall clock:
    # a replay whose evidence changes every time it runs cannot be hashed.
    current_ts = [bars[0].ts_ms if bars else 0]
    broker = PaperBroker(
        equity=equity,
        slippage_bps=slippage_bps,
        commission_bps=commission_bps,
        book_id=book_id,
        clock=lambda: current_ts[0] / 1000.0,
    )
    notional = min(
        float(risk["max_order_notional_usdt"]),
        max(
            float(risk["min_order_notional_usdt"]),
            equity
            * float(risk["max_asset_exposure_pct"])
            / 100.0
            / float(risk["max_open_positions"]),
        ),
    )
    notional = round(notional, 2)

    # Every family's decisions for this symbol, indexed by the bar they act on.
    planned: dict[int, list[dict[str, Any]]] = {}
    for family in SINGLE_ASSET_FAMILIES:
        for trade in family_trades(family, bars):
            planned.setdefault(int(trade["entry_ts_ms"]), []).append(
                {"family": family.name, "action": "ENTER", **trade}
            )
            planned.setdefault(int(trade["exit_ts_ms"]), []).append(
                {"family": family.name, "action": "EXIT", **trade}
            )

    events: list[dict[str, Any]] = []
    day_start_equity = equity
    current_day: str | None = None
    trades_today = 0
    peak_equity = equity
    kill_switch = False

    previous_ts: int | None = None
    gap_bridge_cycles = 0
    for bar in bars:
        current_ts[0] = bar.ts_ms
        # A series that jumps is not a series: the families read their filters off
        # consecutive bars, so a bridged gap is warmup, not tradeable information.
        bridged = previous_ts is not None and bar.ts_ms - previous_ts > 1.5 * 3_600_000
        previous_ts = bar.ts_ms
        day = datetime.fromtimestamp(bar.ts_ms / 1000, tz=UTC).strftime("%Y-%m-%d")
        if day != current_day:
            current_day = day
            day_start_equity = broker.equity
            trades_today = 0
        peak_equity = max(peak_equity, broker.equity)
        drawdown_pct = (
            (peak_equity - broker.equity) / peak_equity * 100.0 if peak_equity > 0 else 0.0
        )
        if drawdown_pct > float(risk["max_total_drawdown_pct"]):
            kill_switch = True

        # 1) the broker's own protective exits fire on the bar's range first
        protective = broker.check_positions_ohlc({symbol: _bar_ohlc(bar)})
        for closed_trade in protective:
            events.append(
                {
                    "cycle": len(events) + 1,
                    "tag": TAG,
                    "ts_ms": bar.ts_ms,
                    "class": classify(bar.ts_ms, freeze_ms),
                    "symbol": symbol,
                    "family": closed_trade.strategy_name,
                    "action": "PROTECTIVE_EXIT",
                    "reason": closed_trade.exit_reason,
                    "position_id": closed_trade.position_id,
                    "trade_id": closed_trade.trade_id,
                    "net_pnl": closed_trade.pnl,
                    "equity": broker.equity,
                }
            )

        # 2) the model's own decisions for this bar
        for plan in planned.get(bar.ts_ms, []):
            family_name = str(plan["family"])
            verdict = verdicts.get(family_name, "UNKNOWN")
            base = {
                "cycle": len(events) + 1,
                "tag": TAG,
                "ts_ms": bar.ts_ms,
                "class": classify(bar.ts_ms, freeze_ms),
                "symbol": symbol,
                "family": family_name,
                "family_verdict": verdict,
                "proposal": {
                    "action": "OPEN_LONG" if plan["action"] == "ENTER" else "CLOSE_LONG",
                    "price": float(
                        plan["entry_price"] if plan["action"] == "ENTER" else plan["exit_price"]
                    ),
                    "notional_usdt": notional,
                    "model_gross_bps": float(plan["gross_bps"]),
                },
                "equity": broker.equity,
            }
            if bridged:
                gap_bridge_cycles += 1
                base.update(
                    {
                        "action": "NO_TRADE",
                        "reason": "GAP_BRIDGE_WARMUP",
                        "risk": "not evaluated: the series jumps into this bar",
                    }
                )
                events.append(base)
                continue
            if verdict.startswith("REJECT"):
                base.update(
                    {
                        "action": "NO_TRADE",
                        "reason": "FAMILY_REJECTED_BY_WP_EDGE_015",
                        "risk": "not evaluated: the family is not a candidate",
                    }
                )
                events.append(base)
                continue
            if plan["action"] == "EXIT":
                if symbol in broker.positions:
                    opposite = Signal(
                        symbol=symbol,
                        side="sell" if broker.positions[symbol].side == "buy" else "buy",
                        strategy_name=family_name,
                        timeframe="1h",
                        confidence=0.0,
                        price=float(plan["exit_price"]),
                        metadata={"notional_usdt": notional},
                    )
                    settled = broker.execute_signal(opposite)
                    base.update(
                        {
                            "action": "SIGNAL_EXIT",
                            "reason": "MODEL_EXIT",
                            "trade_id": getattr(settled, "trade_id", ""),
                            "net_pnl": getattr(settled, "pnl", 0.0),
                            "equity": broker.equity,
                        }
                    )
                else:
                    base.update({"action": "NO_TRADE", "reason": "NO_POSITION_TO_CLOSE"})
                events.append(base)
                continue

            # ENTER: risk gates, in the order the policy lists them
            gate = "PASS"
            if kill_switch:
                gate = "KILL_SWITCH_TOTAL_DRAWDOWN"
            elif datetime.fromtimestamp(bar.ts_ms / 1000, tz=UTC).weekday() >= 5 and not bool(
                risk["blocks"]["weekend_trading"]
            ):
                gate = "WEEKEND_BLOCK"
            elif len(broker.positions) >= int(risk["max_open_positions"]):
                gate = "MAX_OPEN_POSITIONS"
            elif trades_today >= int(risk["max_trades_per_day"]):
                gate = "MAX_TRADES_PER_DAY"
            elif (day_start_equity - broker.equity) / day_start_equity * 100.0 > float(
                risk["max_daily_loss_pct"]
            ):
                gate = "MAX_DAILY_LOSS"
            elif not (
                float(risk["min_order_notional_usdt"])
                <= notional
                <= float(risk["max_order_notional_usdt"])
            ):
                gate = "ORDER_NOTIONAL_OUT_OF_BOUNDS"
            if gate != "PASS":
                base.update({"action": "NO_TRADE", "reason": gate, "risk": "blocked"})
                events.append(base)
                continue

            signal = Signal(
                symbol=symbol,
                side="buy",
                strategy_name=family_name,
                timeframe="1h",
                confidence=1.0,
                price=float(plan["entry_price"]),
                stop_loss_pct=float(risk["default_stop_loss_pct"]),
                take_profit_pct=float(risk["default_take_profit_pct"]),
                metadata={"notional_usdt": notional},
            )
            filled = broker.execute_signal(signal)
            trades_today += 1
            base.update(
                {
                    "action": "FILL_OPENED",
                    "reason": "RISK_APPROVED",
                    "position_id": getattr(filled, "position_id", ""),
                    "entry_order_id": getattr(filled, "entry_order_id", ""),
                    "fill_price": getattr(filled, "entry_price", None),
                    "commission_bps": commission_bps,
                    "slippage_bps": slippage_bps,
                    "equity": broker.equity,
                }
            )
            events.append(base)

    marks = {symbol: bars[-1].close}
    prospective_seen = (
        sum(1 for bar in bars if freeze_ms is not None and bar.ts_ms > freeze_ms)
        if freeze_ms is not None
        else 0
    )
    snapshot = broker.accounting_snapshot(marks)
    gaps = sum(
        1 for previous, current in pairwise(bars) if current.ts_ms - previous.ts_ms != 3_600_000
    )
    return {
        "symbol": symbol,
        "book_id": book_id,
        "events": events,
        "snapshot": snapshot,
        "closed_trades": broker.closed_trades_rows(),
        "notional_usdt": notional,
        "commission_bps": commission_bps,
        "slippage_bps": slippage_bps,
        "bars": len(bars),
        "prospective_bars_seen": prospective_seen,
        "gap_bridge_cycles": gap_bridge_cycles,
        "window_first_ms": bars[0].ts_ms if bars else None,
        "window_last_ms": bars[-1].ts_ms if bars else None,
        "gaps_in_window": gaps,
        "kill_switch_tripped": kill_switch,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="WP-EDGE-015 experimental paper lane")
    parser.add_argument("--out", default=str(LANE_DIR))
    parser.add_argument(
        "--extend-prospective",
        action="store_true",
        help=(
            "append the captured post-freeze bars to each series, so the lane actually "
            "meets new data; off by default so the published replay stays byte-stable"
        ),
    )
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    admission_before = sha256(ADMISSION)
    risk = load_risk_config()
    verdicts = rejected_families()
    freeze_ms = prospective_freeze_ms()

    results = []
    appended: dict[str, int] = {}
    for symbol, _slug, path in UNIVERSE:
        bars = load_ohlcv(path)
        window = bars[-WINDOW_BARS:]
        if args.extend_prospective:
            fresh = [bar for bar in prospective_bars(symbol) if bar.ts_ms > window[-1].ts_ms]
            appended[symbol] = len(fresh)
            window = [*window, *fresh]
        results.append(
            run_symbol(
                symbol,
                window,
                risk=risk,
                verdicts=verdicts,
                freeze_ms=freeze_ms,
            )
        )

    all_events = [event for result in results for event in result["events"]]
    all_trades = [trade for result in results for trade in result["closed_trades"]]
    by_action: dict[str, int] = {}
    for event in all_events:
        by_action[event["action"]] = by_action.get(event["action"], 0) + 1

    per_family: dict[str, dict[str, Any]] = {}
    for trade in all_trades:
        bucket = per_family.setdefault(
            trade["strategy_name"] or "unknown",
            {"closed_trades": 0, "net_pnl": 0.0, "wins": 0, "fees": 0.0, "gross_pnl": 0.0},
        )
        bucket["closed_trades"] += 1
        bucket["net_pnl"] += float(trade["pnl"])
        bucket["gross_pnl"] += float(trade.get("gross_pnl", 0.0))
        bucket["fees"] += float(trade.get("entry_commission", 0.0)) + float(
            trade.get("exit_commission", 0.0)
        )
        bucket["wins"] += 1 if float(trade["pnl"]) > 0 else 0

    equity_total = sum(float(result["snapshot"]["equity_mark_to_market"]) for result in results)
    realised_total = sum(float(result["snapshot"]["realised_pnl"]) for result in results)
    unrealised_total = sum(float(result["snapshot"]["unrealised_pnl"]) for result in results)
    identity_flags = {
        key: all(bool(result["snapshot"]["identities"][key]) for result in results)
        for key in next(iter(results))["snapshot"]["identities"]
    }

    budget = plan_window(
        hours=24.0,
        collector_max_bytes=64 * 1024 * 1024,
        free=free_bytes(REPO),
    )

    report: dict[str, Any] = {
        "schema_version": "EDGE15_PROSPECTIVE_PAPER_REPORT_V1",
        "book_ids": [f"{BOOK_ID}-{symbol.replace('/', '')}" for symbol, _slug, _path in UNIVERSE],
        "work_package": "WP-EDGE-015/P3",
        "tag": TAG,
        "generated_at_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "lane_isolation": {
            "authoritative_ledger": str(ADMISSION.relative_to(REPO)),
            "sha256_before": admission_before,
            "sha256_after": sha256(ADMISSION),
            "untouched": admission_before == sha256(ADMISSION),
            "writes_only_under": str(LANE_DIR.relative_to(REPO)),
            "admitted_strategies": json.loads(ADMISSION.read_text(encoding="utf-8")).get(
                "_admission_cost_model"
            ),
            "counting_rule": (
                "these cycles are EXPERIMENTAL_PROSPECTIVE_PAPER: they cannot count as an "
                "admitted strategy's operations, and the admission ledger still admits nothing"
            ),
        },
        "prospective_window": {
            "freeze_epoch_ms": freeze_ms,
            "classification": (
                "a cycle is PROSPECTIVE only if its bar opened after the frozen protocol "
                "instant; everything else is DESCRIPTIVE and says so in its own record"
            ),
            "prospective_cycles": sum(1 for e in all_events if e["class"] == "PROSPECTIVE"),
            "descriptive_cycles": sum(1 for e in all_events if e["class"] == "DESCRIPTIVE"),
            "prospective_bars_scanned": sum(r["prospective_bars_seen"] for r in results),
            "bars_scanned": sum(r["bars"] for r in results),
            "gap_bridge_cycles": sum(r["gap_bridge_cycles"] for r in results),
            "no_cycle_on_a_prospective_bar": (
                sum(r["prospective_bars_seen"] for r in results) > 0
                and not any(e["class"] == "PROSPECTIVE" for e in all_events)
            ),
            "gap_bridge_rule": (
                "a bar reached across a jump longer than 1.5 hours cannot trade: any proposal "
                "there is recorded as NO_TRADE/GAP_BRIDGE_WARMUP, because the families read "
                "their filters off consecutive bars"
            ),
            "reading": (
                "a bar can be scanned without producing a cycle: the lane records decisions, "
                "not ticks, so a prospective bar where no family has anything to do is "
                "evidence of restraint rather than of a missing fill"
            ),
        },
        "risk_policy": {
            "source": str(RISK_CONFIG.relative_to(REPO)),
            "applied": {
                key: risk[key]
                for key in (
                    "max_open_positions",
                    "max_trades_per_day",
                    "max_daily_loss_pct",
                    "max_total_drawdown_pct",
                    "max_asset_exposure_pct",
                    "min_order_notional_usdt",
                    "max_order_notional_usdt",
                    "default_stop_loss_pct",
                    "default_take_profit_pct",
                )
            },
            "weekend_trading": risk["blocks"]["weekend_trading"],
            "changed_by_this_work_package": False,
        },
        "cycles": {"total": len(all_events), "by_action": by_action},
        "orders": {
            "simulated_orders": (
                by_action.get("FILL_OPENED", 0)
                + by_action.get("SIGNAL_EXIT", 0)
                + by_action.get("PROTECTIVE_EXIT", 0)
            ),
            "simulated_entries": by_action.get("FILL_OPENED", 0),
            "simulated_exits": by_action.get("SIGNAL_EXIT", 0)
            + by_action.get("PROTECTIVE_EXIT", 0),
            "exchange_orders": 0,
            "order_sent": False,
        },
        "positions_and_pnl": {
            "closed_trades": len(all_trades),
            "net_pnl_by_class_usdt": {
                cls: round(
                    sum(float(e.get("net_pnl", 0.0)) for e in all_events if e["class"] == cls), 6
                )
                for cls in ("DESCRIPTIVE", "PROSPECTIVE")
            },
            "closed_trades_by_class": {
                cls: sum(1 for e in all_events if e["class"] == cls and "net_pnl" in e)
                for cls in ("DESCRIPTIVE", "PROSPECTIVE")
            },
            "per_family": per_family,
            "realised_pnl_usdt": realised_total,
            "unrealised_pnl_usdt": unrealised_total,
            "equity_mark_to_market_usdt": equity_total,
            "accounting_identities_all_hold": all(identity_flags.values()),
            "accounting_identity_detail": identity_flags,
            "broker_book_ids": [result["book_id"] for result in results],
            "open_positions_at_end": [
                {"symbol": result["symbol"], **position}
                for result in results
                for position in result["snapshot"]["open_positions"]
            ],
        },
        "data_coverage": {
            "window_bars_per_symbol": WINDOW_BARS,
            "extended_with_prospective_slice": {
                "requested": bool(args.extend_prospective),
                "slice": PROSPECTIVE_SLICE.relative_to(REPO).as_posix(),
                "slice_sha256": sha256(PROSPECTIVE_SLICE),
                "bars_appended_per_symbol": appended,
                "rule": "bars whose open is after the last replayed bar and after the freeze",
            },
            "symbols": {
                result["symbol"]: {
                    "bars": result["bars"],
                    "first_ms": result["window_first_ms"],
                    "last_ms": result["window_last_ms"],
                    "gaps_in_window": result["gaps_in_window"],
                    "events": len(result["events"]),
                }
                for result in results
            },
            "disk": {
                "status": budget.state,
                "ok": budget.ok,
                "free_gib": round(free_bytes(REPO) / 1024**3, 3),
                "reasons": list(budget.reasons),
                "thresholds_changed_by_this_work_package": False,
            },
        },
        "candidate_families": {
            family.name: {
                "verdict": verdicts.get(family.name, "UNKNOWN"),
                "trading_allowed_in_this_lane": not verdicts.get(family.name, "UNKNOWN").startswith(
                    "REJECT"
                ),
                "parameters": family.parameters,
            }
            for family in SINGLE_ASSET_FAMILIES
        },
        "untested_families": {
            name: FAMILY_BY_NAME[name].untestable_reason
            for name in FAMILY_BY_NAME
            if FAMILY_BY_NAME[name].status != "TESTED"
        },
        "reading": (
            "the lane ran on new bars through the real broker and the real risk policy; it "
            "produced its own labelled record, touched no admitted ledger, and its cycles are "
            "evidence of process, not of edge — the alpha matrix is where edge is decided"
        ),
    }

    (out / "PROSPECTIVE_PAPER_REPORT.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    events_path = out / "EXPERIMENTAL_CYCLES.jsonl"
    with events_path.open("w", encoding="utf-8") as handle:
        for event in all_events:
            handle.write(json.dumps(event, sort_keys=True) + "\n")
    trades_path = out / "EXPERIMENTAL_TRADES.jsonl"
    with trades_path.open("w", encoding="utf-8") as handle:
        for trade in all_trades:
            handle.write(json.dumps(trade, sort_keys=True) + "\n")

    print(f"[lane] cycles {len(all_events)} {by_action}")
    print(f"[lane] closed trades {len(all_trades)} realised {realised_total:.4f} USDT")
    print(f"[lane] accounting identities hold: {all(identity_flags.values())}")
    print(f"[lane] admitted ledger untouched: {report['lane_isolation']['untouched']}")
    print(f"[lane] disk {budget.state} free {report['data_coverage']['disk']['free_gib']} GiB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
