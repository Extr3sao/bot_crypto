"""exp_003o_original — Builder A: the frozen EXP-003N producer, replayed per instant.

Builder A is allowed to be the producer: it imports the frozen modules, calls the frozen
families and the frozen lane-B machines, and reports what they decide at **every** instant
of the 003O calendar — including the instants where they decide nothing. 003N only published
the signals it emitted, so a parity check against that file alone could never see a missing
*no-signal*; this replay is what makes the join meaningful.

Two anchors keep the replay honest:

* ``--check-published`` compares its own SIGNAL rows against
  ``analysis/SIGNALS.jsonl.gz`` of 003N (cell, symbol, instant, direction) and its lane-B
  trades against the published ``gross_bps`` rows. A replay that drifted is caught before
  anything is compared.
* ``--check-lane-b`` drives the machines with an instrumented copy of the frozen driver and
  asserts the trades are identical to ``run_family``'s own output.

Usage
-----
``python scripts/exp_003o_original.py --out signals/original_evaluations.jsonl.gz``
``python scripts/exp_003o_original.py --check-published --out /tmp/a.jsonl.gz``
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
for extra in (REPO / "scripts", REPO / "src"):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

import exp_003n_screen as frozen  # noqa: E402
import numpy as np  # noqa: E402
from exp_003o_contract import (  # noqa: E402
    OUT,
    SOURCE_003N,
    Bar,
    bar_bytes,
    read_json,
    utc_ms,
    window_digest,
    write_jsonl_gz,
)

from trading_bot.research.economic_recovery.experiments import Bar as FrozenBar  # noqa: E402
from trading_bot.research.economic_recovery.pit15 import machine_for, run_family  # noqa: E402
from trading_bot.vision.signal_sources import STRATEGY_SPECS  # noqa: E402

PRODUCER = "original"


def _contract_bar(item: Any) -> Bar:
    return Bar(
        ts_ms=int(item.timestamp),
        open=float(item.open),
        high=float(item.high),
        low=float(item.low),
        close=float(item.close),
        volume=float(item.volume),
    )


def load_series(protocol: dict[str, Any], symbol: str, timeframe: str, truncate: int | None) -> Any:
    """The frozen loader, the frozen aggregation and the frozen holdout cut."""

    frozen.DATASET = REPO / "reports" / "ai-bots" / "EXP-003K-CANDIDATE-001" / "dataset"
    minutes = frozen.load_minute(symbol)
    series = frozen.aggregate(minutes, int(protocol["timeframes_ms"][timeframe]))
    series = frozen.head(series, utc_ms(protocol["holdout"]["start_utc"]))
    frozen.assert_holdout_closed(series, utc_ms(protocol["holdout"]["start_utc"]))
    if truncate is not None:
        series = frozen.Series(
            symbol=series.symbol,
            stamps=series.stamps[:truncate],
            open=series.open[:truncate],
            high=series.high[:truncate],
            low=series.low[:truncate],
            close=series.close[:truncate],
            volume=series.volume[:truncate],
        )
    return series


def lane_a_rows(
    protocol: dict[str, Any], cell: dict[str, Any], symbol: str, series: Any
) -> list[dict[str, Any]]:
    interval = int(protocol["timeframes_ms"][str(cell["timeframe"])])
    spec = STRATEGY_SPECS[str(cell["family"])]
    family = spec.family_cls()
    bars = frozen.candles(series)
    window = max(int(spec.min_candles) + 1, 80)
    parameter_hash = str(cell["parameter_hash"])
    rows: list[dict[str, Any]] = []
    running = hashlib.sha256()
    for index, candle in enumerate(bars):
        running.update(bar_bytes(_contract_bar(candle)))
        if index < window - 1:
            rows.append(
                _row(
                    cell,
                    symbol,
                    interval,
                    int(candle.timestamp) + interval,
                    "NOT_READY",
                    None,
                    "WARMUP",
                    parameter_hash,
                    running.hexdigest(),
                    int(bars[0].timestamp),
                    int(candle.timestamp),
                    index + 1,
                )
            )
            continue
        start = max(0, index - window + 1)
        signals = family.generate(bars[start : index + 1], {}, None)
        emitted = [
            str(getattr(signal, "direction", "")).upper()
            for signal in signals
            if str(getattr(signal, "direction", "")).upper() in {"LONG", "SHORT"}
        ]
        if emitted:
            rows.append(
                _row(
                    cell,
                    symbol,
                    interval,
                    int(candle.timestamp) + interval,
                    "SIGNAL",
                    emitted[0],
                    None,
                    parameter_hash,
                    window_digest([_contract_bar(bar) for bar in bars[start : index + 1]]),
                    int(bars[start].timestamp),
                    int(candle.timestamp),
                    index - start + 1,
                )
            )
        else:
            rows.append(
                _row(
                    cell,
                    symbol,
                    interval,
                    int(candle.timestamp) + interval,
                    "NO_SIGNAL",
                    None,
                    "RULE_FALSE",
                    parameter_hash,
                    window_digest([_contract_bar(bar) for bar in bars[start : index + 1]]),
                    int(bars[start].timestamp),
                    int(candle.timestamp),
                    index - start + 1,
                )
            )
    return rows


def _frozen_bars(series: Any) -> list[FrozenBar]:
    return [
        FrozenBar(
            ts_ms=int(series.stamps[index]),
            open=float(series.open[index]),
            high=float(series.high[index]),
            low=float(series.low[index]),
            close=float(series.close[index]),
            volume=float(series.volume[index]),
        )
        for index in range(len(series.stamps))
    ]


def lane_b_rows(
    protocol: dict[str, Any], cell: dict[str, Any], symbol: str, series: Any
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """The frozen machines, driven by an instrumented copy of the frozen driver."""

    bars = _frozen_bars(series)
    interval = int(protocol["timeframes_ms"][str(cell["timeframe"])])
    family = str(cell["family"])
    params = dict(cell["parameters"])
    warmup = int(protocol["evaluation_contract"]["lane_b_warmup_bars"][family])
    machine = machine_for(family, params)
    parameter_hash = str(cell["parameter_hash"])

    rows: list[dict[str, Any]] = []
    trades: list[dict[str, Any]] = []
    digest = hashlib.sha256()
    opening: dict[str, Any] | None = None
    pending: Any = None
    last_exit_fill: int | None = None

    for index, bar in enumerate(bars):
        if pending is not None and pending.fill_index == index:
            if pending.kind == "ENTRY":
                opening = {
                    "fill_index": index,
                    "price": bar.open,
                    "rule": pending.rule,
                    "signal_index": pending.signal_index,
                }
                machine.notify_fill("ENTRY", index, bar.open)
            else:
                assert opening is not None
                trades.append(
                    _close(
                        opening,
                        index,
                        bar.open,
                        machine,
                        bars,
                        pending.rule,
                        pending.signal_index,
                        is_mark=False,
                    )
                )
                machine.notify_fill("EXIT", index, bar.open)
                opening = None
                last_exit_fill = index
            pending = None

        decision = machine.on_closed_bar(index, bar, in_position=opening is not None)
        digest.update(
            bar_bytes(
                Bar(
                    ts_ms=int(bar.ts_ms),
                    open=float(bar.open),
                    high=float(bar.high),
                    low=float(bar.low),
                    close=float(bar.close),
                    volume=float(bar.volume),
                )
            )
        )
        if index < warmup:
            state, direction, reason = "NOT_READY", None, "WARMUP"
        elif decision is None:
            state = "NO_SIGNAL"
            direction = None
            reason = "IN_POSITION" if opening is not None else "RULE_FALSE"
        elif decision.kind == "ENTRY":
            state, direction, reason = "SIGNAL", "LONG", "ENTRY_RULE"
        else:
            state, direction, reason = "SIGNAL", "FLAT", "EXIT_RULE"
        rows.append(
            _row(
                cell,
                symbol,
                interval,
                int(bar.ts_ms) + interval,
                state,
                direction,
                reason,
                parameter_hash,
                digest.hexdigest(),
                int(bars[0].ts_ms),
                int(bar.ts_ms),
                index + 1,
            )
        )

        if decision is None:
            continue
        if decision.fill_index >= len(bars):
            continue
        if (
            decision.kind == "ENTRY"
            and last_exit_fill is not None
            and decision.fill_index <= last_exit_fill
        ):
            continue
        pending = decision

    if opening is not None:
        last = len(bars) - 1
        trades.append(
            _close(
                opening,
                last,
                bars[last].close,
                machine,
                bars,
                "TERMINAL_MARK_AT_LAST_CLOSE",
                last,
                is_mark=True,
            )
        )
    return rows, trades


def _close(
    opening: dict[str, Any],
    exit_index: int,
    exit_price: float,
    machine: Any,
    bars: list[FrozenBar],
    rule: str,
    signal_index: int,
    *,
    is_mark: bool,
) -> dict[str, Any]:
    return {
        "entry_ts_ms": int(bars[opening["fill_index"]].ts_ms),
        "exit_ts_ms": int(bars[exit_index].ts_ms),
        "entry_signal_ts_ms": int(bars[opening["signal_index"]].ts_ms),
        "exit_signal_ts_ms": int(bars[signal_index].ts_ms),
        "entry_price": float(opening["price"]),
        "exit_price": float(exit_price),
        "gross_bps": (float(exit_price) / float(opening["price"]) - 1.0) * 10_000.0,
        "bars_held": exit_index - int(opening["fill_index"]),
        "direction": "long",
        "entry_rule": str(opening["rule"]),
        "exit_rule": rule,
        "is_mark": bool(is_mark),
    }


def _row(
    cell: dict[str, Any],
    symbol: str,
    interval: int,
    decision_ms: int,
    state: str,
    direction: str | None,
    reason: str | None,
    parameter_hash: str,
    digest: str,
    window_first_ms: int,
    window_last_ms: int,
    window_bars: int,
) -> dict[str, Any]:
    return {
        "cell_id": str(cell["cell_id"]),
        "symbol": symbol,
        "timeframe": str(cell["timeframe"]),
        "decision_ms": int(decision_ms),
        "bar_open_ms": int(window_last_ms),
        "bar_close_ms": int(window_last_ms) + interval,
        "data_available_ms": int(window_last_ms) + interval,
        "state": state,
        "direction": direction,
        "reason": reason,
        "parameter_hash": parameter_hash,
        "input_snapshot_hash": digest,
        "window_first_ms": int(window_first_ms),
        "window_last_ms": int(window_last_ms),
        "window_bars": int(window_bars),
        "producer": PRODUCER,
    }


def published_calendar() -> dict[str, Any]:
    with gzip.open(SOURCE_003N / "analysis" / "SIGNALS.jsonl.gz", "rt", encoding="utf-8") as handle:
        payload = json.load(handle)
    return payload  # type: ignore[no-any-return]


def run(
    protocol: dict[str, Any], truncate: int | None
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    trades: list[dict[str, Any]] = []
    symbols = [str(symbol) for symbol in protocol["symbols"]]
    timeframes = sorted({str(cell["timeframe"]) for cell in protocol["cells"]})
    cache = {
        (symbol, timeframe): load_series(protocol, symbol, timeframe, truncate)
        for symbol in symbols
        for timeframe in timeframes
    }
    for cell in protocol["cells"]:
        for symbol in symbols:
            series = cache[(symbol, str(cell["timeframe"]))]
            if cell["lane"] == "A":
                rows.extend(lane_a_rows(protocol, cell, str(symbol), series))
            else:
                cell_rows, cell_trades = lane_b_rows(protocol, cell, str(symbol), series)
                rows.extend(cell_rows)
                for trade in cell_trades:
                    trades.append({"cell_id": cell["cell_id"], "symbol": symbol, **trade})
    return rows, trades


def check_lane_b(protocol: dict[str, Any], truncate: int | None) -> int:
    """The instrumented driver must reproduce ``run_family``'s own trades exactly."""

    failures = 0
    for cell in protocol["cells"]:
        if cell["lane"] != "B":
            continue
        for symbol in protocol["symbols"]:
            series = load_series(protocol, str(symbol), str(cell["timeframe"]), truncate)
            bars = _frozen_bars(series)
            direct = run_family(str(cell["family"]), bars, dict(cell["parameters"]))
            _, driven = lane_b_rows(protocol, cell, str(symbol), series)
            keys = ("entry_ts_ms", "exit_ts_ms", "gross_bps", "bars_held", "is_mark", "exit_rule")
            if len(direct) != len(driven):
                print(
                    f"[003o-original] FAIL — {cell['cell_id']}/{symbol}: run_family={len(direct)} "
                    f"driver={len(driven)}",
                    file=sys.stderr,
                )
                failures += 1
                continue
            for left, right in zip(direct, driven, strict=True):
                if any(left[key] != right[key] for key in keys):
                    print(
                        f"[003o-original] FAIL — {cell['cell_id']}/{symbol} trade differs",
                        file=sys.stderr,
                    )
                    failures += 1
                    break
    print(f"[003o-original] lane B driver parity: {'OK' if not failures else f'{failures} FAILED'}")
    return 0 if not failures else 6


def check_published(
    protocol: dict[str, Any], rows: list[dict[str, Any]], trades: list[dict[str, Any]]
) -> dict[str, Any]:
    """Anchor this replay to the calendar 003N actually published.

    A published row's ``ts_ms`` is the **open** of the signal bar; this replay keys a decision
    by the bar's **close**, so the comparison shifts by exactly one interval per cell. Getting
    that wrong would compare two different instants and call the difference a defect.
    """

    payload = published_calendar()
    published = payload["signals"]
    intervals = {
        str(cell["cell_id"]): int(protocol["timeframes_ms"][str(cell["timeframe"])])
        for cell in protocol["cells"]
    }
    lane_a_families = {str(cell["family"]) for cell in protocol["cells"] if cell["lane"] == "A"}
    published_a = {
        (row["family"] + "@" + row["timeframe"], row["symbol"], int(row["ts_ms"]), row["direction"])
        for row in published
        if row.get("direction") in {"LONG", "SHORT"} and row["family"] in lane_a_families
    }
    replayed_a = {
        (
            row["cell_id"],
            row["symbol"],
            int(row["decision_ms"]) - intervals[str(row["cell_id"])],
            row["direction"],
        )
        for row in rows
        if row["state"] == "SIGNAL"
        and row["direction"] in {"LONG", "SHORT"}
        and str(row["cell_id"]).split("@")[0] in lane_a_families
    }
    missing = sorted(published_a - replayed_a)[:5]
    extra = sorted(replayed_a - published_a)[:5]
    published_b = {
        (row["family"] + "@" + row["timeframe"], row["symbol"], int(row["ts_ms"]))
        for row in published
        if row.get("gross_bps") is not None
    }
    replayed_b = {
        (trade["cell_id"], trade["symbol"], int(trade["entry_ts_ms"]))
        for trade in trades
        if not trade["is_mark"]
    }
    return {
        "published_signals": len(published_a),
        "replayed_signals": len(replayed_a),
        "missing_from_replay": len(published_a - replayed_a),
        "extra_in_replay": len(replayed_a - published_a),
        "missing_examples": missing,
        "extra_examples": extra,
        "published_lane_b_trades": len(published_b),
        "replayed_lane_b_trades": len(replayed_b),
        "lane_b_missing": len(published_b - replayed_b),
        "lane_b_extra": len(replayed_b - published_b),
        "matches": not (published_a ^ replayed_a) and not (published_b - replayed_b),
    }


def run_fixtures(protocol: dict[str, Any], fixtures: Path, out: Path) -> int:
    """Replay the frozen producer over the frozen synthetic series."""

    out.mkdir(parents=True, exist_ok=True)
    files = sorted(path for path in fixtures.glob("*.json") if path.name != "FIXTURE_MANIFEST.json")
    if not files:
        print(f"[003o-original] FAIL — no fixture in {fixtures}", file=sys.stderr)
        return 4
    for path in files:
        payload = read_json(path)
        cell = next(
            (item for item in protocol["cells"] if item["cell_id"] == payload["cell_id"]), None
        )
        if cell is None:
            print(f"[003o-original] FAIL — {path.name} names an unknown cell", file=sys.stderr)
            return 5
        bars = payload["bars"]
        series = frozen.Series(
            symbol=str(payload["fixture_id"]),
            stamps=np.asarray([int(bar["ts_ms"]) for bar in bars], dtype=np.int64),
            open=np.asarray([float(bar["open"]) for bar in bars], dtype=np.float64),
            high=np.asarray([float(bar["high"]) for bar in bars], dtype=np.float64),
            low=np.asarray([float(bar["low"]) for bar in bars], dtype=np.float64),
            close=np.asarray([float(bar["close"]) for bar in bars], dtype=np.float64),
            volume=np.asarray([float(bar["volume"]) for bar in bars], dtype=np.float64),
        )
        if cell["lane"] == "A":
            rows = lane_a_rows(protocol, cell, str(payload["fixture_id"]), series)
        else:
            rows, _ = lane_b_rows(protocol, cell, str(payload["fixture_id"]), series)
        write_jsonl_gz(out / f"{payload['fixture_id']}.jsonl.gz", rows)
        signals = sum(1 for row in rows if row["state"] == "SIGNAL")
        print(
            f"[003o-original] fixture {payload['fixture_id']}: rows={len(rows)} signals={signals}"
        )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="EXP-003O original producer replay")
    parser.add_argument("--protocol", default=str(OUT / "design" / "PROTOCOL.json"))
    parser.add_argument("--out", default=str(OUT / "signals" / "original_evaluations.jsonl.gz"))
    parser.add_argument("--truncate", type=int, default=None)
    parser.add_argument("--check-published", action="store_true")
    parser.add_argument("--check-lane-b", action="store_true")
    parser.add_argument("--fixtures", type=Path, default=None)
    parser.add_argument("--fixture-out", type=Path, default=None)
    args = parser.parse_args(argv)

    protocol = read_json(Path(args.protocol))
    if args.check_lane_b:
        return check_lane_b(protocol, args.truncate)
    if args.fixtures is not None:
        if args.fixture_out is None:
            print("[003o-original] FAIL — --fixtures needs --fixture-out", file=sys.stderr)
            return 2
        return run_fixtures(protocol, args.fixtures, args.fixture_out)

    rows, trades = run(protocol, args.truncate)
    write_jsonl_gz(Path(args.out), rows)
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["state"]] = counts.get(row["state"], 0) + 1
    print(f"[003o-original] rows={len(rows)} states={sorted(counts.items())} trades={len(trades)}")
    if args.check_published:
        anchor = check_published(protocol, rows, trades)
        print(f"[003o-original] published anchor: {json.dumps(anchor, sort_keys=True)}")
        return 0 if anchor["matches"] else 7
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
