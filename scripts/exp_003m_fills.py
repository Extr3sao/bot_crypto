"""exp_003m_fills — price a maker entry against the observed trade tape.

    ./.venv/Scripts/python.exe scripts/exp_003m_fills.py

The question this module answers is narrow and measurable: *when* would a resting post-only
limit order at the pre-registered price have been filled, given every aggregate trade the
exchange published, and what does the resulting position earn after the same fees and the
same exits as EXP-003L?

Mechanism (frozen in ``design/DESIGN.json``):

* placement at ``decision + latency``;
* queue ahead of us = ``q * order_qty`` base units, ``q`` declared per scenario and swept
  when it matters, because no spot L2 feed exists to observe it;
* a resting buy is filled by seller aggressors trading at or below the limit, a resting
  sell by buyer aggressors trading at or above it;
* fill fraction = ``clamp((aggressor_volume - queue_ahead) / order_qty, 0, 1)`` inside the
  horizon; a signal that never clears the queue is a MISS, and misses stay in the
  denominator;
* exits, stop/target levels, fee schedules and the research window are EXP-003L's.

``F0_touch_full`` is EXP-003L's own assumption (any touch fills us fully). It is kept so
this experiment can prove it reproduces the predecessor before it judges the successor. It
is an upper bound, not a mechanism.
"""

from __future__ import annotations

import argparse
import gzip
import json
import statistics as stats
from bisect import bisect_left, bisect_right
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

REPO = Path(__file__).resolve().parents[1]

OUT = REPO / "reports" / "ai-bots" / "EXP-003M-MAKER-FILL-REALITY-001"
DATASET = REPO / "reports" / "ai-bots" / "EXP-003K-CANDIDATE-001" / "dataset"
PREDECESSOR = REPO / "reports" / "ai-bots" / "EXP-003L-EXECUTION-ECONOMICS-001"

SCHEMA = "AI_BOTS_003M_FILL_MODEL_V1"
MINUTE_MS = 60_000
STOP_LOSS_PCT = 0.5
TAKE_PROFIT_PCT = 0.75
#: End of the research window, computed rather than typed: an off-by-a-day here would
#: quietly read one bar of the holdout.
RESEARCH_END_MS = int(datetime(2026, 8, 6, tzinfo=UTC).timestamp() * 1000)


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def load_bars(dataset: Path = DATASET) -> dict[str, dict[str, Any]]:
    """The frozen 1-minute series, the only thing that adjudicates exits."""

    bars: dict[str, dict[str, Any]] = {}
    for path in sorted(dataset.glob("*.1m.jsonl.gz")):
        symbol = path.name.split(".")[0]
        stamps: list[int] = []
        rows: list[list[float]] = []
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                row = json.loads(line)
                stamps.append(int(row[0]))
                rows.append([float(row[1]), float(row[2]), float(row[3]), float(row[4])])
        array = np.asarray(rows, dtype=float)
        bars[symbol] = {
            "symbol": symbol,
            "stamps": stamps,
            "index": {stamp: position for position, stamp in enumerate(stamps)},
            "open": array[:, 0],
            "high": array[:, 1],
            "low": array[:, 2],
            "close": array[:, 3],
        }
    return bars


def load_tape(manifest_path: Path, out: Path) -> dict[str, list[tuple[int, float, float, bool]]]:
    """Every kept trade, keyed by symbol, sorted by time: the observed market path."""

    manifest = _read_json(manifest_path)
    tape: dict[str, list[tuple[int, float, float, bool]]] = {}
    for entry in manifest["pairs"].values():
        target = out / entry["tape"]["file"]
        with gzip.open(target, "rt", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                _agg_id, price, qty, ts_ms, buyer_is_maker = json.loads(line)
                tape.setdefault(str(entry["symbol"]), []).append(
                    (int(ts_ms) * 1000, float(price), float(qty), bool(buyer_is_maker))
                )
    for symbol in tape:
        tape[symbol].sort(key=lambda row: (row[0], row[1]))
    return tape


def tape_fill(
    trades: list[tuple[int, float, float, bool]],
    *,
    side: str,
    limit: float,
    order_qty: float,
    queue_multiple: float,
    start_us: int,
    horizon_us: int,
) -> dict[str, Any]:
    """Fill one resting limit against the tape. Pure: same inputs, same answer.

    ``queue_multiple`` is how many of *our own orders* are assumed to be ahead of us. It
    is the one number the tape cannot supply, which is why it is declared per scenario and
    swept in the sensitivity table instead of being tuned to a result.
    """

    if order_qty <= 0 or limit <= 0:
        raise ValueError("order_qty and limit must be positive")
    if horizon_us <= 0:
        raise ValueError("horizon must be positive")
    aggressor_is_seller = side == "buy"
    queue_ahead = max(queue_multiple, 0.0) * order_qty
    end_us = start_us + horizon_us
    cumulative = 0.0
    fill_us: int | None = None
    volume_at_limit_before = 0.0
    touched = False
    for ts_us, price, qty, buyer_is_maker in trades:
        if ts_us < start_us:
            continue
        if ts_us > end_us:
            break
        if buyer_is_maker != aggressor_is_seller:
            continue
        if side == "buy" and price > limit:
            continue
        if side == "sell" and price < limit:
            continue
        touched = True
        if fill_us is None:
            volume_at_limit_before = cumulative
        cumulative += qty
        if fill_us is None and cumulative > queue_ahead:
            fill_us = ts_us
    filled = 0.0
    if cumulative > queue_ahead:
        filled = min(1.0, (cumulative - queue_ahead) / order_qty)
    return {
        "touched": touched,
        "fill_fraction": round(filled, 10),
        "fill_ts_us": fill_us,
        "seconds_to_fill": None if fill_us is None else round((fill_us - start_us) / 1e6, 3),
        "aggressor_volume": round(cumulative, 10),
        "queue_ahead": round(queue_ahead, 10),
        "volume_before_fill": round(volume_at_limit_before, 10),
        "horizon_seconds": round(horizon_us / 1e6, 3),
        "miss_reason": None
        if filled > 0
        else ("QUEUE_NEVER_REACHED" if touched else "NO_AGGRESSOR_AT_LIMIT"),
    }


def levels(entry: float, side: str) -> tuple[float, float]:
    """``(stop, target)`` from the fill price, the lane's own policy."""

    if side == "buy":
        return entry * (1.0 - STOP_LOSS_PCT / 100.0), entry * (1.0 + TAKE_PROFIT_PCT / 100.0)
    return entry * (1.0 + STOP_LOSS_PCT / 100.0), entry * (1.0 - TAKE_PROFIT_PCT / 100.0)


def exit_path(
    bars: dict[str, Any],
    *,
    side: str,
    entry: float,
    start_index: int,
    end_index: int,
    stop_friction_bps: float,
) -> dict[str, Any]:
    """Walk the frozen 1-minute bars to the first level, ``stop_first`` inside a minute.

    The friction is applied to the exit the way a real stop works: the stop crosses the
    spread and pays the taker terms, while the target rests as a maker order and pays none.
    """

    stop, target = levels(entry, side)
    last = min(end_index, len(bars["stamps"]) - 1)
    if start_index > last:
        return {
            "status": "OPEN_AT_END",
            "exit_reason": None,
            "exit_ts_ms": bars["stamps"][last] if last >= 0 else None,
            "exit_price": None,
            "exit_index": None,
            "gapped": False,
            "minutes_held": 0,
        }
    highs = bars["high"][start_index : last + 1]
    lows = bars["low"][start_index : last + 1]
    opens = bars["open"][start_index : last + 1]
    if side == "buy":
        stop_hits = lows <= stop
        target_hits = highs >= target
    else:
        stop_hits = highs >= stop
        target_hits = lows <= target
    stop_index = int(np.argmax(stop_hits)) if bool(stop_hits.any()) else None
    target_index = int(np.argmax(target_hits)) if bool(target_hits.any()) else None
    if stop_index is not None and (target_index is None or stop_index <= target_index):
        opened = float(opens[stop_index])
        gapped = (opened <= stop) if side == "buy" else (opened >= stop)
        reference = opened if gapped else stop
        factor = 1.0 + stop_friction_bps / 10_000.0
        price = reference / factor if side == "buy" else reference * factor
        return {
            "status": "CLOSED",
            "exit_reason": "stop_loss",
            "exit_ts_ms": bars["stamps"][start_index + stop_index],
            "exit_price": price,
            "exit_index": start_index + stop_index,
            "gapped": gapped,
            "minutes_held": stop_index + 1,
        }
    if target_index is not None:
        return {
            "status": "CLOSED",
            "exit_reason": "take_profit",
            "exit_ts_ms": bars["stamps"][start_index + target_index],
            "exit_price": target,
            "exit_index": start_index + target_index,
            "gapped": False,
            "minutes_held": target_index + 1,
        }
    return {
        "status": "OPEN_AT_END",
        "exit_reason": None,
        "exit_ts_ms": bars["stamps"][last] if last >= 0 else None,
        "exit_price": None,
        "exit_index": None,
        "gapped": False,
        "minutes_held": max(0, last - start_index + 1),
    }


def adverse_bps(bars: dict[str, Any], side: str, entry: float, index: int, horizon: int) -> float | None:
    """Forward move after the fill, signed positive when it goes against the position."""

    target = index + horizon
    if target >= len(bars["close"]):
        return None
    close = float(bars["close"][target])
    move = (entry - close) / entry * 10_000.0 if side == "buy" else (close - entry) / entry * 10_000.0
    return round(move, 6)


def window_slice(
    trades: list[tuple[int, float, float, bool]],
    stamps: list[int],
    start_us: int,
    end_us: int,
) -> list[tuple[int, float, float, bool]]:
    """Only the trades that can matter. The tape is sorted, so this is a binary search."""

    return trades[bisect_left(stamps, start_us) : bisect_right(stamps, end_us)]


def evaluate_signal(
    signal: dict[str, Any],
    *,
    scenario: str,
    bars: dict[str, Any],
    trades: list[tuple[int, float, float, bool]],
    tape_stamps: list[int],
    queue_multiple: float,
    latency_ms: int,
    horizon_minutes: int,
    offset_bps: float,
    maker_bps: float,
    taker_bps: float,
    price_bps_per_side: float,
    end_index: int,
    touch_only: bool,
) -> dict[str, Any]:
    """One signal, one mechanism. ``touch_only`` reproduces EXP-003L's F0 assumption."""

    offset = f"{offset_bps:g}"
    symbol = str(signal["symbol"])
    side = str(signal["side"])
    notional = float(signal["notional_usdt"])
    limit = float(signal["limit_price"][offset])
    order_qty = notional / limit
    decision_ms = int(signal["decision_ts_ms"])
    start_index = bars["index"].get(decision_ms)
    if start_index is None:
        raise SystemExit(f"[003m-fills] BLOCKED — no 1m bar at {decision_ms} for {symbol}")

    fill: dict[str, Any]
    if touch_only:
        horizon_index = min(start_index + horizon_minutes, len(bars["stamps"]) - 1)
        window = slice(start_index, horizon_index + 1)
        touched = (
            bool((bars["low"][window] <= limit).any())
            if side == "buy"
            else bool((bars["high"][window] >= limit).any())
        )
        if touched:
            hits = bars["low"][window] <= limit if side == "buy" else bars["high"][window] >= limit
            touch_index = start_index + int(np.argmax(hits))
        else:
            touch_index = None
        fill = {
            "touched": touched,
            "fill_fraction": 1.0 if touched else 0.0,
            "fill_ts_us": None if touch_index is None else bars["stamps"][touch_index] * 1000,
            "seconds_to_fill": None,
            "aggressor_volume": None,
            "queue_ahead": None,
            "volume_before_fill": None,
            "horizon_seconds": horizon_minutes * 60,
            "miss_reason": None if touched else "NO_TOUCH_IN_OHLC",
        }
        fill_index = touch_index
    else:
        start_us = (decision_ms + latency_ms) * 1000
        end_us = start_us + horizon_minutes * 60 * 1_000_000
        fill = tape_fill(
            window_slice(trades, tape_stamps, start_us, end_us),
            side=side,
            limit=limit,
            order_qty=order_qty,
            queue_multiple=queue_multiple,
            start_us=start_us,
            horizon_us=horizon_minutes * 60 * 1_000_000,
        )
        #: The fill instant is a trade timestamp, not an array position. Floor it to the
        #: minute that contains it and look that minute up in the bar index; using the raw
        #: epoch division here silently produced an index far past the end of the series.
        fill_index = None
        if fill["fill_ts_us"] is not None:
            minute_ms = (int(fill["fill_ts_us"]) // 1000) // MINUTE_MS * MINUTE_MS
            fill_index = bars["index"].get(minute_ms)
            if fill_index is None:
                raise SystemExit(
                    f"[003m-fills] BLOCKED — no 1m bar at the fill minute {minute_ms} for {symbol}"
                )

    row: dict[str, Any] = {
        "index": int(signal["index"]),
        "position_id": str(signal["position_id"]),
        "symbol": symbol,
        "side": side,
        "scenario": scenario,
        "decision_ts_ms": decision_ms,
        "limit_price": limit,
        "order_qty": order_qty,
        "touched": fill["touched"],
        "fill_fraction": fill["fill_fraction"],
        "fill_ts_ms": None if fill["fill_ts_us"] is None else int(fill["fill_ts_us"] // 1000),
        "seconds_to_fill": fill["seconds_to_fill"],
        "aggressor_volume": fill["aggressor_volume"],
        "queue_ahead": fill["queue_ahead"],
        "volume_before_fill": fill["volume_before_fill"],
        "horizon_seconds": fill["horizon_seconds"],
        "miss_reason": fill["miss_reason"],
        "status": "MISS",
        "exit_reason": None,
        "exit_ts_ms": None,
        "exit_price": None,
        "gross_usdt": 0.0,
        "entry_fee_usdt": 0.0,
        "exit_fee_usdt": 0.0,
        "net_usdt": 0.0,
        "minutes_held": 0,
        "adverse_1m_bps": None,
        "adverse_5m_bps": None,
        "adverse_15m_bps": None,
    }
    fraction = float(fill["fill_fraction"])
    if fraction <= 0 or fill_index is None:
        return row

    #: The minute that contains the fill cannot be adjudicated for the exit: its range may
    #: have been spent before the fill existed. Both mechanisms get the same guard.
    exit_start = fill_index + 1
    result = exit_path(
        bars,
        side=side,
        entry=limit,
        start_index=exit_start,
        end_index=end_index,
        stop_friction_bps=price_bps_per_side,
    )
    quantity = notional / limit
    closed = result["status"] == "CLOSED"
    #: A position still open at the end of the partition was never sold: charging it an
    #: exit fee would invent a trade. It pays its entry fee, and its unrealised PnL is not
    #: counted — the same convention EXP-003L uses.
    exit_fee_bps = (
        (maker_bps if result["exit_reason"] == "take_profit" else taker_bps) if closed else 0.0
    )
    exit_price = result["exit_price"]
    gross = 0.0
    if exit_price is not None:
        gross = (
            (float(exit_price) - limit) * quantity
            if side == "buy"
            else (limit - float(exit_price)) * quantity
        )
    entry_fee = fraction * notional * maker_bps / 10_000.0
    exit_fee = fraction * notional * exit_fee_bps / 10_000.0
    net = fraction * gross - entry_fee - exit_fee
    row.update(
        {
            "status": result["status"],
            "exit_reason": result["exit_reason"],
            "exit_ts_ms": result["exit_ts_ms"],
            "exit_price": exit_price,
            "gross_usdt": round(fraction * gross, 10),
            "entry_fee_usdt": round(entry_fee, 10),
            "exit_fee_usdt": round(exit_fee, 10),
            "net_usdt": round(net, 10),
            "minutes_held": result["minutes_held"],
            "gapped": result["gapped"],
            "adverse_1m_bps": adverse_bps(bars, side, limit, fill_index, 1),
            "adverse_5m_bps": adverse_bps(bars, side, limit, fill_index, 5),
            "adverse_15m_bps": adverse_bps(bars, side, limit, fill_index, 15),
        }
    )
    return row


def aggregate(rows: list[dict[str, Any]], *, signals: int) -> dict[str, Any]:
    """Per-signal and per-fill statistics. Misses count in the denominator, not the PnL."""

    filled = [row for row in rows if row["fill_fraction"] > 0]
    closed = [row for row in rows if row["status"] == "CLOSED"]
    net = sum(float(row["net_usdt"]) for row in rows)
    gross = sum(float(row["gross_usdt"]) for row in rows)
    fees = sum(float(row["entry_fee_usdt"]) + float(row["exit_fee_usdt"]) for row in rows)
    by_reason: dict[str, int] = {}
    for row in closed:
        key = str(row["exit_reason"])
        by_reason[key] = by_reason.get(key, 0) + 1
    misses: dict[str, int] = {}
    for row in rows:
        if row["fill_fraction"] <= 0:
            key = str(row["miss_reason"])
            misses[key] = misses.get(key, 0) + 1

    def mean(key: str) -> float | None:
        values = [float(row[key]) for row in filled if row.get(key) is not None]
        return round(stats.fmean(values), 6) if values else None

    fill_fractions = [float(row["fill_fraction"]) for row in filled]
    seconds = [float(row["seconds_to_fill"]) for row in filled if row.get("seconds_to_fill") is not None]
    return {
        "signals": signals,
        "filled": len(filled),
        "closed": len(closed),
        "open_at_end": len(filled) - len(closed),
        "fill_rate": round(len(filled) / signals, 6) if signals else None,
        "fill_fraction_mean": round(stats.fmean(fill_fractions), 6) if fill_fractions else None,
        "fill_fraction_median": round(stats.median(fill_fractions), 6) if fill_fractions else None,
        "seconds_to_fill_median": round(stats.median(seconds), 3) if seconds else None,
        "net_usdt": round(net, 8),
        "net_per_signal_usdt": round(net / signals, 8) if signals else None,
        "net_per_fill_usdt": round(net / len(filled), 8) if filled else None,
        "gross_per_fill_usdt": round(gross / len(filled), 8) if filled else None,
        "fees_per_fill_usdt": round(fees / len(filled), 8) if filled else None,
        "win_rate": round(sum(1 for row in filled if float(row["net_usdt"]) > 0) / len(filled), 6)
        if filled
        else None,
        "exit_reasons": by_reason,
        "miss_reasons": misses,
        "gapped_exits": sum(1 for row in closed if row.get("gapped")),
        "adverse_1m_bps_mean": mean("adverse_1m_bps"),
        "adverse_5m_bps_mean": mean("adverse_5m_bps"),
        "adverse_15m_bps_mean": mean("adverse_15m_bps"),
        "minutes_held_median": round(
            stats.median([float(row["minutes_held"]) for row in filled]), 2
        )
        if filled
        else None,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=str(OUT))
    parser.add_argument("--dataset", default=str(DATASET))
    args = parser.parse_args(argv)

    out = Path(args.out)
    design = _read_json(out / "design" / "DESIGN.json")
    _assert_config_unchanged(design)
    signals_doc = _read_json(out / "analysis" / "SIGNALS.json")
    signals = signals_doc["signals"]
    manifest_path = out / "dataset" / "TAPE_MANIFEST.json"
    if not manifest_path.exists():
        raise SystemExit(f"[003m-fills] BLOCKED — {manifest_path} is missing; build the tape first")

    bars = load_bars(Path(args.dataset))
    tape = load_tape(manifest_path, out)
    tape_stamps = {symbol: [row[0] for row in rows] for symbol, rows in tape.items()}
    schedules = design["fee_schedules"]
    #: Taker terms for the stop leg, read from EXP-003L's frozen cost table: a stop has to
    #: cross the spread, and that friction is not this experiment's to invent.
    cost_table = _read_json(PREDECESSOR / "design" / "DESIGN.json")["cost_table"]
    friction = {
        str(row["symbol"]).replace("/", ""): float(row["price_bps_per_side"]) for row in cost_table
    }

    end_index = {symbol: int(np.searchsorted(bars[symbol]["stamps"], RESEARCH_END_MS)) - 1 for symbol in bars}

    results: dict[str, Any] = {}
    per_signal: dict[str, list[dict[str, Any]]] = {}
    for name, scenario in design["scenarios"].items():
        schedule = schedules[scenario["fee_schedule"]]
        rows = [
            evaluate_signal(
                signal,
                scenario=name,
                bars=bars[str(signal["symbol"]).replace("/", "")],
                trades=tape.get(str(signal["symbol"]).replace("/", ""), []),
                tape_stamps=tape_stamps.get(str(signal["symbol"]).replace("/", ""), []),
                queue_multiple=float(scenario["queue_multiple"]),
                latency_ms=int(scenario["latency_ms"]),
                horizon_minutes=int(scenario["horizon_minutes"]),
                offset_bps=float(scenario["offset_bps"]),
                maker_bps=float(schedule["maker_bps"]),
                taker_bps=float(schedule["taker_bps"]),
                price_bps_per_side=friction[str(signal["symbol"]).replace("/", "")],
                end_index=end_index[str(signal["symbol"]).replace("/", "")],
                touch_only=name == "F0_touch_full",
            )
            for signal in signals
        ]
        per_signal[name] = rows
        results[name] = {
            "parameters": scenario,
            **aggregate(rows, signals=len(signals)),
        }
        print(
            f"[003m-fills] {name}: filled {results[name]['filled']}/{len(signals)} "
            f"net/signal {results[name]['net_per_signal_usdt']} "
            f"net/fill {results[name]['net_per_fill_usdt']}",
            flush=True,
        )

    sensitivity = design["sensitivity"]
    schedule = schedules[sensitivity["fee_schedule"]]
    grid: list[dict[str, Any]] = []
    for queue_multiple in sensitivity["queue_multiple"]:
        for latency_ms in sensitivity["latency_ms"]:
            rows = [
                evaluate_signal(
                    signal,
                    scenario=f"sensitivity_q{queue_multiple:g}_l{latency_ms}",
                    bars=bars[str(signal["symbol"]).replace("/", "")],
                    trades=tape.get(str(signal["symbol"]).replace("/", ""), []),
                    tape_stamps=tape_stamps.get(str(signal["symbol"]).replace("/", ""), []),
                    queue_multiple=float(queue_multiple),
                    latency_ms=int(latency_ms),
                    horizon_minutes=int(sensitivity["horizon_minutes"]),
                    offset_bps=float(sensitivity["offset_bps"]),
                    maker_bps=float(schedule["maker_bps"]),
                    taker_bps=float(schedule["taker_bps"]),
                    price_bps_per_side=friction[str(signal["symbol"]).replace("/", "")],
                    end_index=end_index[str(signal["symbol"]).replace("/", "")],
                    touch_only=False,
                )
                for signal in signals
            ]
            summary = aggregate(rows, signals=len(signals))
            grid.append(
                {
                    "queue_multiple": queue_multiple,
                    "latency_ms": latency_ms,
                    "filled": summary["filled"],
                    "fill_rate": summary["fill_rate"],
                    "fill_fraction_mean": summary["fill_fraction_mean"],
                    "net_per_signal_usdt": summary["net_per_signal_usdt"],
                    "net_per_fill_usdt": summary["net_per_fill_usdt"],
                    "gross_per_fill_usdt": summary["gross_per_fill_usdt"],
                }
            )
    print(f"[003m-fills] sensitivity grid: {len(grid)} points", flush=True)

    _write_json(
        out / "analysis" / "FILL_MODEL.json",
        {
            "schema_version": SCHEMA,
            "experiment": "EXP-003M-MAKER-FILL-REALITY-001",
            "signals": len(signals),
            "design_sha256": _sha256(out / "design" / "DESIGN.json"),
            "signals_sha256": _sha256(out / "analysis" / "SIGNALS.json"),
            "tape_manifest_sha256": _sha256(manifest_path),
            "scenarios": results,
            "sensitivity": grid,
            "per_signal": per_signal,
        },
    )
    return 0


def _assert_config_unchanged(design: dict[str, Any]) -> None:
    """The stop, the target and the live flag come from ``config/``. Check, do not assume.

    A fill model priced with 0.50 %/0.75 % is worthless if the frozen policy has since moved
    to another level: the numbers would describe an exit policy nobody runs.
    """

    frozen = design.get("runtime_config") or {}
    if not frozen:
        raise SystemExit("[003m-fills] BLOCKED — the design has no runtime_config fingerprint")
    import yaml

    risk = yaml.safe_load((REPO / "config" / "risk.yaml").read_text(encoding="utf-8"))
    runtime = yaml.safe_load((REPO / "config" / "runtime.yaml").read_text(encoding="utf-8"))
    risk_block = risk.get("risk") or risk
    runtime_block = runtime.get("runtime") or {}
    stop = float(risk_block["default_stop_loss_pct"])
    target = float(risk_block["default_take_profit_pct"])
    if stop != STOP_LOSS_PCT or target != TAKE_PROFIT_PCT:
        raise SystemExit(
            f"[003m-fills] BLOCKED — config/risk.yaml now says {stop}/{target} %, this engine "
            f"prices {STOP_LOSS_PCT}/{TAKE_PROFIT_PCT} %; refreeze before pricing anything"
        )
    if bool(runtime_block.get("live_trading_enabled")) or str(runtime_block.get("mode")) != "paper":
        raise SystemExit(
            "[003m-fills] REFUSED — config/runtime.yaml no longer declares paper with live off"
        )
    for name, digest in (frozen.get("files") or {}).items():
        current = _sha256(REPO / "config" / name)
        if current != digest:
            raise SystemExit(
                f"[003m-fills] BLOCKED — config/{name} changed since the freeze "
                f"({current[:12]} != {digest[:12]})"
            )


def _sha256(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
