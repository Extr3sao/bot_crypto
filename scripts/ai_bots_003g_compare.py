"""ai_bots_003g_compare — CURRENT vs PROPOSED on the very same collected minutes.

    ./.venv/Scripts/python.exe scripts/ai_bots_003g_compare.py --session <dir>

Both runs receive identical 5-minute series (rebuilt from the session's raw 1-minute
JSONL, and checked against the hash the session published), the same provider script, the
same declared latency, capital, costs and risk policy. The only difference is
``subbar_entries``: ``False`` fills at the next bar open, ``True`` fills at the first
one-minute quote at or after the answer.

The script refuses to compare when the rebuilt series does not match the session's digest:
two runs on different data are not a comparison, they are two measurements.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import sys
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

from trading_bot.config.settings import load_settings  # noqa: E402
from trading_bot.market_data.minute_collector import (  # noqa: E402
    MinuteBar,
    MinuteStore,
    aggregate_complete,
)
from trading_bot.vision.clock import timeframe_ms  # noqa: E402
from trading_bot.vision.lane import VisionLane  # noqa: E402
from trading_bot.vision.ledger import read_entries  # noqa: E402
from trading_bot.vision.prospective import (  # noqa: E402
    PaperScriptProvider,
    display_symbol,
)
from trading_bot.vision.quotes import MinuteBarQuoteFeed, MinuteSeries  # noqa: E402
from trading_bot.vision.settings import load_vision_config  # noqa: E402


def _load_minutes(path: Path) -> list[MinuteBar]:
    if not path.exists():
        raise SystemExit(f"missing minute store {path}")
    store = MinuteStore(path).open()
    try:
        return store.contiguous_tail()
    finally:
        store.close()


def _digest(series: dict[str, list[Any]], key: str = "ts_ms") -> str:
    payload = json.dumps(
        [
            [
                int(getattr(bar, key)),
                round(float(bar.open), 8),
                round(float(bar.high), 8),
                round(float(bar.low), 8),
                round(float(bar.close), 8),
                round(float(bar.volume), 8),
            ]
            for bars in series.values()
            for bar in bars
        ],
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _feed(minutes: dict[str, list[MinuteBar]]) -> MinuteBarQuoteFeed:
    series = {
        display_symbol(symbol): MinuteSeries.from_rows(
            display_symbol(symbol),
            [
                [bar.open_ms, bar.open, bar.high, bar.low, bar.close, bar.volume]
                for bar in bars
            ],
        )
        for symbol, bars in minutes.items()
    }
    return MinuteBarQuoteFeed(series)


def _run(
    *,
    label: str,
    series: dict[str, list[Any]],
    minutes: dict[str, list[MinuteBar]],
    out: Path,
    subbar: bool,
    config: Any,
    risk_policy: Any,
    data_delay_ms: int,
    latency_ms: int,
    decision_from_ms: int,
    interval_ms: int,
    window_bars: int,
    decision_every: int,
) -> dict[str, Any]:
    target = out / label
    target.mkdir(parents=True, exist_ok=True)
    ledger = target / "ledger.jsonl"
    if ledger.exists():
        ledger.unlink()
    lane = VisionLane(
        series={symbol: list(bars) for symbol, bars in series.items()},
        provider=PaperScriptProvider(latency_ms=latency_ms),
        config=replace(
            config,
            lane=replace(
                config.lane,
                window_bars=window_bars,
                decision_every_bars=decision_every,
                data_delay_ms=data_delay_ms,
            ),
        ),
        risk_policy=risk_policy,
        ledger_path=ledger,
        equity=10_000.0,
        book_id=f"paper-003g-{label.lower()}",
        decision_every_bars=decision_every,
        quote_feed=_feed(minutes),
        subbar_entries=subbar,
        decision_from_ms=decision_from_ms,
    )
    summary = lane.run()
    (target / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    entries = read_entries(ledger)
    fills = [row["entry"] for row in entries if row["entry"]["kind"] == "FILL"]
    closes = [row["entry"] for row in entries if row["entry"]["kind"] == "CLOSE"]
    decisions = [row["entry"] for row in entries if row["entry"]["kind"] == "DECISION"]
    lags = [int(fill["quote_lag_ms"]) for fill in fills]
    return {
        "label": label,
        "subbar_entries": subbar,
        "ledger": str(ledger.relative_to(out)),
        "ledger_sha256": hashlib.sha256(ledger.read_bytes()).hexdigest(),
        "decisions": len(decisions),
        "actions": summary.get("counters", {}),
        "fills": len(fills),
        "closed_trades": len(closes),
        "net_realised_usdt": summary.get("net_realised_usdt"),
        "gross_realised_usdt": summary.get("gross_realised_usdt"),
        "costs_usdt": summary.get("costs_usdt"),
        #: 003H: same accounting contract on both sides of the comparison, so a cost is
        #: never "cheaper" because one variant ended holding a position.
        "costs_realised_usdt": summary.get("costs_realised_usdt"),
        "entry_commissions_accrued_open_usdt": summary.get(
            "entry_commissions_accrued_open_usdt"
        ),
        "costs_total_usdt": summary.get("costs_total_usdt"),
        "pnl_realised_usdt": summary.get("pnl_realised_usdt"),
        "pnl_unrealised_usdt": summary.get("pnl_unrealised_usdt"),
        "pnl_total_usdt": summary.get("pnl_total_usdt"),
        "marked_equity_usdt": summary.get("marked_equity_usdt"),
        "open_positions_at_end": len(summary.get("open_positions_at_end") or {}),
        "accounting_schema_version": (summary.get("accounting") or {}).get("schema_version"),
        "drawdown_pct": summary.get("drawdown_pct"),
        "final_equity_usdt": summary.get("final_equity_usdt"),
        "median_quote_lag_ms": statistics.median(lags) if lags else None,
        "sub_bar_fills": summary.get("execution", {}).get("sub_bar_fills"),
        "entry_quote_sources": summary.get("execution", {}).get("entry_quote_sources"),
        "execution": summary.get("execution"),
        "reconciliation": summary.get("reconciliation"),
        "fills_detail": [
            {
                "position_id": fill.get("position_id"),
                "symbol": fill.get("symbol"),
                "side": fill.get("side"),
                "quote_ts_ms": fill.get("quote_ts_ms"),
                "quote_price": fill.get("quote_price"),
                "quote_source": fill.get("quote_source"),
                "quote_lag_ms": fill.get("quote_lag_ms"),
                "received_at_ms": fill.get("received_at_ms"),
            }
            for fill in fills
        ],
    }


def _delta(current: Any, proposed: Any) -> float | None:
    """Difference of one accounting term, or ``None`` when either side omits it."""

    if current is None or proposed is None:
        return None
    return round(float(proposed) - float(current), 8)


def _price_delta_bps(current: list[dict[str, Any]], proposed: list[dict[str, Any]]) -> dict[str, Any]:
    by_position = {str(row["position_id"]): row for row in proposed}
    deltas: list[float] = []
    for row in current:
        other = by_position.get(str(row["position_id"]))
        if other is None:
            continue
        before = float(row["quote_price"])
        after = float(other["quote_price"])
        if before <= 0:
            continue
        sign = 1.0 if str(row.get("side", "")).lower() in {"buy", "long"} else -1.0
        deltas.append(sign * (after - before) / before * 10_000.0)
    if not deltas:
        return {"matched": 0}
    return {
        "matched": len(deltas),
        "median_bps_improvement": round(statistics.median(deltas), 6),
        "min_bps": round(min(deltas), 6),
        "max_bps": round(max(deltas), 6),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="CURRENT vs PROPOSED on one dataset")
    parser.add_argument("--session", required=True)
    parser.add_argument("--out", default=None)
    parser.add_argument(
        "--full-store",
        action="store_true",
        help=(
            "compare over every collected minute (warm-up included). This is a "
            "retrospective measurement on real data, not the prospective claim: the "
            "decisions before the session started are replayed, not lived."
        ),
    )
    args = parser.parse_args(argv)

    session = Path(args.session)
    #: 003H: the two scopes get their own directory. Sharing one made the second run
    #: overwrite the first comparison, which is evidence loss, not a formatting detail.
    out = (
        Path(args.out)
        if args.out
        else session / ("compare-full" if args.full_store else "compare")
    )
    out.mkdir(parents=True, exist_ok=True)
    stream = read_entries(session / "STREAM.jsonl")
    if not stream:
        raise SystemExit(f"{session}/STREAM.jsonl is empty or missing")
    start = stream[0]["entry"]
    cycles = [row["entry"] for row in stream if row["entry"]["kind"] == "CYCLE"]
    executed = [row for row in cycles if row.get("status") == "EXECUTED"]
    if not executed:
        raise SystemExit("the session has no executed cycle to compare")
    last = executed[-1]
    config = start["config"]
    interval_ms = timeframe_ms(config["timeframe"])
    started_ms = int(
        datetime.strptime(start["started_at_utc"], "%Y-%m-%dT%H:%M:%SZ")
        .replace(tzinfo=UTC)
        .timestamp()
        * 1000
    )
    data_time_ms = int(last["data_time_ms"])

    symbols = tuple(config["symbols"])
    minutes: dict[str, list[MinuteBar]] = {}
    series: dict[str, list[Any]] = {}
    rebuilt: dict[str, Any] = {}
    for symbol in symbols:
        bars = _load_minutes(session / "market-1m" / f"{symbol}.jsonl")
        usable = bars if args.full_store else [bar for bar in bars if bar.close_ms <= data_time_ms]
        grouped, meta = aggregate_complete(usable, interval_ms=interval_ms)
        minutes[symbol] = usable
        series[display_symbol(symbol)] = grouped
        rebuilt[symbol] = {
            "minutes": len(usable),
            "bars": len(grouped),
            "sha256": _digest({display_symbol(symbol): grouped}),
            "matches_session": None
            if args.full_store
            else _digest({display_symbol(symbol): grouped})
            == last["series"][display_symbol(symbol)]["sha256"],
            "incomplete_groups": meta["incomplete_groups"],
        }
    if not args.full_store and not all(item["matches_session"] for item in rebuilt.values()):
        raise SystemExit(
            "the rebuilt series does not match the digest the session published: "
            f"{json.dumps(rebuilt, indent=2)}"
        )
    if args.full_store:
        data_time_ms = max(
            (bar.close_ms for bars in minutes.values() for bar in bars), default=data_time_ms
        )

    vision = load_vision_config(env={})
    vision = replace(vision, lane=replace(vision.lane, timeframe=config["timeframe"]))
    settings = load_settings(config_dir=REPO / "config", env_file=None)
    common = dict(
        series=series,
        minutes=minutes,
        out=out,
        config=vision,
        risk_policy=settings.risk,
        data_delay_ms=int(last["data_delay_ms"]),
        latency_ms=int(config["declared_latency_ms"]),
        decision_from_ms=0 if args.full_store else started_ms,
        interval_ms=interval_ms,
        window_bars=int(config["window_bars"]),
        decision_every=int(config["decision_every_bars"]),
    )
    current = _run(label="CURRENT", subbar=False, **common)
    proposed = _run(label="PROPOSED", subbar=True, **common)
    delta = _price_delta_bps(current["fills_detail"], proposed["fills_detail"])

    net_delta = None
    if current["net_realised_usdt"] is not None and proposed["net_realised_usdt"] is not None:
        net_delta = round(
            float(proposed["net_realised_usdt"]) - float(current["net_realised_usdt"]), 6
        )
    dd_delta_pp = None
    if current["drawdown_pct"] is not None and proposed["drawdown_pct"] is not None:
        dd_delta_pp = round(
            float(proposed["drawdown_pct"]) - float(current["drawdown_pct"]), 6
        )

    closed = min(current["closed_trades"], proposed["closed_trades"])
    if closed < 30:
        gate = "INSUFFICIENT_SAMPLE"
        gate_detail = (
            f"{closed} closed trades: the 003F gate requires >= 30 to judge economics"
        )
    elif net_delta is None or dd_delta_pp is None:
        gate = "NOT_MEASURABLE"
        gate_detail = "net or drawdown is missing from one of the runs"
    elif net_delta > 0 and dd_delta_pp <= 0.10:
        gate = "PASS"
        gate_detail = "net improved and drawdown did not exceed +0.10 pp"
    else:
        gate = "FAIL"
        gate_detail = "net did not improve or drawdown exceeded +0.10 pp"

    result = {
        "schema_version": "AI_BOTS_003G_COMPARISON_V1",
        "session": str(session),
        "scope": (
            "RETROSPECTIVE_FULL_COLLECTED_WINDOW"
            if args.full_store
            else "PROSPECTIVE_SESSION_WINDOW"
        ),
        "dataset": {
            "data_time_ms": data_time_ms,
            "timeframe": config["timeframe"],
            "bar_interval_ms": interval_ms,
            "symbols": rebuilt,
        },
        "controls": {
            "same_provider": "paper-script",
            "same_latency_ms": int(config["declared_latency_ms"]),
            "same_data_delay_ms": int(last["data_delay_ms"]),
            "same_equity_usdt": 10_000.0,
            "same_risk_policy": True,
            "decision_from_ms": started_ms,
        },
        "current": current,
        "proposed": proposed,
        "delta": {
            "net_realised_usdt": net_delta,
            "costs_total_usdt": _delta(
                current["costs_total_usdt"], proposed["costs_total_usdt"]
            ),
            "pnl_total_usdt": _delta(current["pnl_total_usdt"], proposed["pnl_total_usdt"]),
            "drawdown_pp": dd_delta_pp,
            "entry_price": delta,
            "fills": proposed["fills"] - current["fills"],
            "closed_trades": proposed["closed_trades"] - current["closed_trades"],
            "sub_bar_fills": proposed["sub_bar_fills"],
        },
        "gate": {"verdict": gate, "detail": gate_detail},
    }
    (out / "COMPARISON.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    print(json.dumps({k: result[k] for k in ("delta", "gate")}, indent=2))
    for label, run in (("CURRENT", current), ("PROPOSED", proposed)):
        print(
            f"{label:8s} decisions={run['decisions']:3d} fills={run['fills']:3d} "
            f"closed={run['closed_trades']:3d} net={run['net_realised_usdt']} "
            f"dd={run['drawdown_pct']} sub_bar_fills={run['sub_bar_fills']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
