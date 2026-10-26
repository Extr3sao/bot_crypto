"""exp_003j_analysis — measure the two arms from their own bytes.

Everything here is derived from the lane's ``ledger.jsonl`` (the book's own record) plus,
for the experimental arm, the provider's ``SIGNAL_TRACE.jsonl``. No number is copied from a
summary that was not first re-derived from rows, and the accounting identities are checked
rather than quoted.

    ./.venv/Scripts/python.exe scripts/exp_003j_analysis.py

Outputs (all under ``reports/ai-bots/EXP-003J-REAL-SIGNAL-PAPER-001/``):

``DECISION_TRACE.jsonl``     every decision of both arms, joined to risk and broker outcome
``PAPER_LEDGER.csv``         closed trades and open positions, both arms, one row each
``SCENARIO_COMPARISON.csv``  one row per arm x partition
``METRICS_BY_ASSET.csv``     one row per arm x partition x asset
``analysis/METRICS.json``    the same numbers, machine-readable
``analysis/RECONCILIATION.json``  the identity checks and their inputs
``ACCOUNTING_RECONCILIATION.md``  the human-readable version

What this script refuses to do: treat a signal as a fill, treat an open position as a
closed trade, compute expectancy over anything but closed trades, or report a metric whose
input row it could not find.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import statistics
import sys
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

from trading_bot.vision.clock import timeframe_ms  # noqa: E402

EXPERIMENT_OUT = REPO / "reports" / "ai-bots" / "EXP-003J-REAL-SIGNAL-PAPER-001"
RUNS = EXPERIMENT_OUT / "runs"
ARMS = ("control", "real")
PARTITIONS = ("research", "oos")
BOOTSTRAP_SEED = 20261020
BOOTSTRAP_ROUNDS = 10_000


def _utc(ms: int) -> str:
    return datetime.fromtimestamp(int(ms) / 1000.0, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load(path: Path) -> list[dict[str, Any]]:
    """Ledger entries, with the chain's own sequence number carried as ``_seq``.

    ``DECISION_OUTCOME`` rows point at the decision they settle by ``decision_seq``; the
    decision row itself only knows its chain position, so the position travels with it
    rather than being guessed from order-of-appearance.
    """

    if not path.exists():
        raise FileNotFoundError(f"missing {path}; run scripts/exp_003j_replay.py first")
    entries: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        wrapper = json.loads(line)
        entry = dict(wrapper["entry"])
        entry["_seq"] = int(wrapper.get("seq", 0))
        entries.append(entry)
    return entries


def _of(rows: list[dict[str, Any]], kind: str) -> list[dict[str, Any]]:
    return [row for row in rows if row.get("kind") == kind]


def _round(value: float | None, digits: int = 6) -> float | None:
    return None if value is None else round(float(value), digits)


def _percentile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    index = min(len(ordered) - 1, max(0, round(q * (len(ordered) - 1))))
    return ordered[index]


def bootstrap_mean_ci(values: list[float]) -> dict[str, Any]:
    """A seeded bootstrap of the mean. Seeded so the report is reproducible."""

    if not values:
        return {"n": 0, "mean": None, "ci95": [None, None], "rounds": 0}
    rng = random.Random(BOOTSTRAP_SEED)
    means = [
        sum(rng.choices(values, k=len(values))) / len(values) for _ in range(BOOTSTRAP_ROUNDS)
    ]
    return {
        "n": len(values),
        "mean": _round(statistics.fmean(values)),
        "ci95": [_round(_percentile(means, 0.025)), _round(_percentile(means, 0.975))],
        "rounds": BOOTSTRAP_ROUNDS,
        "seed": BOOTSTRAP_SEED,
    }


def _trade_rows(
    closes: list[dict[str, Any]],
    fills: list[dict[str, Any]],
    *,
    arm: str,
    bars: dict[str, list[Any]] | None,
    interval_ms: int,
) -> list[dict[str, Any]]:
    """One row per closed trade, with the excursion measured from the bars it lived in."""

    # A close names its position, not its decision: the fill that opened it is the join.
    fill_by_position = {str(fill["position_id"]): fill for fill in fills}
    rows: list[dict[str, Any]] = []
    for close in closes:
        entry_ts = int(close.get("entry_quote_ts_ms") or close.get("entry_decision_ts_ms") or 0)
        exit_ts = int(close["ts_ms"])
        entry = float(close["entry_price"])
        side = str(close["side"]).lower()
        mfe = None
        mae = None
        series = (bars or {}).get(close["symbol"])
        if series and entry > 0:
            window = [bar for bar in series if entry_ts <= int(bar.ts_ms) <= exit_ts]
            if window:
                high = max(float(bar.high) for bar in window)
                low = min(float(bar.low) for bar in window)
                if side == "buy":
                    mfe = (high / entry - 1.0) * 100.0
                    mae = (low / entry - 1.0) * 100.0
                else:
                    mfe = (entry / low - 1.0) * 100.0
                    mae = (entry / high - 1.0) * 100.0 * -1.0
        fill = fill_by_position.get(str(close["position_id"]))
        rows.append(
            {
                "arm": arm,
                "trade_id": close["trade_id"],
                "position_id": close["position_id"],
                "symbol": close["symbol"],
                "side": close["side"],
                "entry_ts_ms": entry_ts,
                "entry_utc": _utc(entry_ts) if entry_ts else None,
                "exit_ts_ms": exit_ts,
                "exit_utc": _utc(exit_ts),
                "entry_price": float(close["entry_price"]),
                "exit_price": float(close["exit_price"]),
                "quantity": float(close["quantity"]),
                "notional_usdt": float(fill["notional_usdt"]) if fill else None,
                "stop_loss_price": close.get("stop_loss_price"),
                "take_profit_price": close.get("take_profit_price"),
                "exit_reason": close["exit_reason"],
                "exit_ts_resolution": close["exit_ts_resolution"],
                "bars_held": close.get("bars_held"),
                "holding_minutes": (
                    None
                    if close.get("bars_held") is None
                    else round(float(close["bars_held"]) * interval_ms / 60_000.0, 3)
                ),
                "gross_pnl_usdt": float(close["gross_pnl_usdt"]),
                "reference_gross_pnl_usdt": float(close["reference_gross_pnl_usdt"]),
                "execution_cost_usdt": float(close["execution_cost_usdt"]),
                "commissions_usdt": float(close["commissions_usdt"]),
                "pnl_net_usdt": float(close["pnl_net_usdt"]),
                "mfe_pct": _round(mfe),
                "mae_pct": _round(mae),
            }
        )
    return rows


def _accounting_checks(
    *,
    rows: list[dict[str, Any]],
    fills: list[dict[str, Any]],
    closes: list[dict[str, Any]],
    summary: dict[str, Any],
    open_positions: dict[str, Any],
    initial_equity: float,
) -> dict[str, Any]:
    """Re-derive every identity the summary claims, from the ledger rows."""

    checks: list[dict[str, Any]] = []

    def add(code: str, ok: bool, detail: str) -> None:
        checks.append({"code": code, "ok": bool(ok), "detail": detail})

    trade_identities = []
    for close in closes:
        net = float(close["pnl_net_usdt"])
        gross = float(close["gross_pnl_usdt"])
        reference = float(close["reference_gross_pnl_usdt"])
        execution = float(close["execution_cost_usdt"])
        commissions = float(close["commissions_usdt"])
        at_paid = abs(net - (gross - commissions)) <= 1e-6
        at_reference = abs(net - (reference - execution - commissions)) <= 1e-6
        trade_identities.append(
            {
                "trade_id": close["trade_id"],
                "net_equals_gross_minus_commissions": at_paid,
                "net_equals_reference_minus_execution_minus_commissions": at_reference,
            }
        )
    add(
        "every_close_nets_its_named_costs",
        bool(trade_identities)
        and all(
            item["net_equals_gross_minus_commissions"]
            or item["net_equals_reference_minus_execution_minus_commissions"]
            for item in trade_identities
        ),
        f"{len(trade_identities)} closes checked",
    )
    summed_net = sum(float(close["pnl_net_usdt"]) for close in closes)
    add(
        "net_realised_rebuilds_from_closes",
        abs(summed_net - float(summary.get("net_realised_usdt") or 0.0)) <= 1e-6,
        f"sum(closes)={summed_net:.8f} summary={summary.get('net_realised_usdt')}",
    )
    add(
        "initial_plus_realised_is_final_equity",
        abs((initial_equity + summed_net) - float(summary.get("final_equity_usdt") or 0.0)) <= 1e-6,
        f"{initial_equity} + {summed_net:.8f} vs {summary.get('final_equity_usdt')}",
    )
    add(
        "risk_equity_equals_marked_equity",
        abs(
            float(summary.get("risk_equity_usdt") or 0.0)
            - float(summary.get("marked_equity_usdt") or 0.0)
        )
        <= 1e-6,
        f"risk={summary.get('risk_equity_usdt')} marked={summary.get('marked_equity_usdt')}",
    )
    closed_ids = {close["position_id"] for close in closes}
    add(
        "open_positions_are_disjoint_from_closed_trades",
        not (closed_ids & set(open_positions)),
        f"open={sorted(open_positions)}",
    )
    lane_identities = (summary.get("reconciliation") or {}).get("identities") or {}
    add(
        "lane_reconciliation_identities_all_true",
        bool(lane_identities) and all(bool(value) for value in lane_identities.values()),
        f"{sum(1 for value in lane_identities.values() if value)}/{len(lane_identities)} true",
    )
    # A fill names the decision that authorised it by chain sequence, and a DECISION row only
    # knows its own chain position (`_seq`, attached by `_load`). Matching on the entry's own
    # ``decision_seq`` would compare two absences and call it a pass.
    decision_seqs = {
        int(row["_seq"]) for row in _of(rows, "DECISION") if row.get("_seq") is not None
    }
    unmatched = [
        fill for fill in fills if int(fill.get("decision_seq", -1)) not in decision_seqs
    ]
    add(
        "every_fill_has_a_decision_row",
        not unmatched,
        f"{len(fills)} fills, {len(unmatched)} unmatched",
    )
    add(
        "no_live_order_was_recorded",
        all(int(row.get("live_orders", 0) or 0) == 0 for row in rows),
        "every ledger row carries live_orders=0 (or none)",
    )
    return {
        "checks": checks,
        "passed": sum(1 for check in checks if check["ok"]),
        "failed": sum(1 for check in checks if not check["ok"]),
        "trade_identities": trade_identities,
        "sum_net_realised_usdt": _round(summed_net),
    }


def _metrics(
    *,
    arm: str,
    partition: str,
    rows: list[dict[str, Any]],
    summary: dict[str, Any],
    trade_rows: list[dict[str, Any]],
    initial_equity: float,
    interval_ms: int,
    window_end_ms: int,
    trace_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    decisions = _of(rows, "DECISION")
    outcomes = {int(row["decision_seq"]): row for row in _of(rows, "DECISION_OUTCOME")}
    fills = _of(rows, "FILL")
    directional = [row for row in decisions if (row.get("decision") or {}).get("action") in ("LONG", "SHORT")]
    long_count = sum(1 for row in directional if row["decision"]["action"] == "LONG")
    short_count = sum(1 for row in directional if row["decision"]["action"] == "SHORT")
    no_trade = [row for row in decisions if (row.get("decision") or {}).get("action") == "NO_TRADE"]
    trace_reasons = Counter(
        str(row.get("reason_code")) for row in trace_rows if row.get("action") == "NO_TRADE"
    )
    if not trace_reasons and no_trade:
        # The control arm has no provider trace by design; its only reason is the script.
        trace_reasons = Counter({"LEGACY_PARITY_SCRIPT": len(no_trade)})
    vetoes = Counter(
        str(row.get("risk_blocked_by")) for row in outcomes.values() if not row.get("approved", True)
    )
    slot_rejections = sum(
        1 for row in outcomes.values() if row.get("risk_blocked_by") == "SYMBOL_SLOT_OCCUPIED"
    )
    # A directional signal that arrives while the symbol already holds a position is dropped
    # by ``resolve_intent`` *before* an order exists, so the execution-level counter above is
    # almost always zero. The capacity question is answered here, on the coherence reason.
    coherence = Counter(
        str(row.get("coherence_reason")) for row in decisions if row.get("coherence_reason")
    )
    slot_dropped = sum(
        coherence.get(reason, 0)
        for reason in ("ALREADY_LONG", "ALREADY_SHORT", "OPPOSITE_LONG_OPEN", "OPPOSITE_SHORT_OPEN")
    )
    weekend_blocks = sum(
        1 for row in outcomes.values() if row.get("risk_gate") == "WEEKEND_BLOCK"
    )
    approved = sum(1 for row in outcomes.values() if row.get("approved"))
    net = sum(float(trade["pnl_net_usdt"]) for trade in trade_rows)
    commissions = sum(float(trade["commissions_usdt"]) for trade in trade_rows)
    execution = sum(float(trade["execution_cost_usdt"]) for trade in trade_rows)
    notionals = [float(trade["notional_usdt"]) for trade in trade_rows if trade["notional_usdt"]]
    holdings = [
        float(trade["holding_minutes"]) for trade in trade_rows if trade["holding_minutes"] is not None
    ]

    # Exposure is sampled on the decision grid from the trades' own lifetimes, not assumed.
    intervals = []
    for trade in trade_rows:
        intervals.append((trade["entry_ts_ms"], trade["exit_ts_ms"], float(trade["notional_usdt"] or 0.0)))
    open_positions = summary.get("open_positions_at_end") or {}
    for position in open_positions.values() if isinstance(open_positions, dict) else []:
        entry_ms = int(float(position.get("opened_at", 0)) * 1000)
        intervals.append((entry_ms, window_end_ms, float(position.get("notional_usdt") or 0.0)))
    grid = sorted({trade["entry_ts_ms"] for trade in trade_rows} | {trade["exit_ts_ms"] for trade in trade_rows})
    exposures = []
    simultaneous = []
    for ts in grid:
        live = [notional for start, end, notional in intervals if start <= ts <= end]
        simultaneous.append(len(live))
        exposures.append(sum(live) / initial_equity * 100.0)
    traded_bars = sum(1 for _ in grid)
    # Capital utilisation is the mean share of equity deployed, sampled on the same grid as
    # exposure: two names for one measurement, never two different formulas.
    utilisation = statistics.fmean(exposures) if exposures else 0.0

    return {
        "arm": arm,
        "partition": partition,
        "decisions": len(decisions),
        "directional": len(directional),
        "long": long_count,
        "short": short_count,
        "no_trade": len(no_trade),
        "no_trade_reasons": dict(sorted(trace_reasons.items())),
        "risk_approved": approved,
        "risk_vetoed": sum(vetoes.values()),
        "risk_veto_reasons": dict(sorted(vetoes.items())),
        "symbol_slot_rejections": slot_rejections,
        "slot_share_of_directional_pct": _round(
            100.0 * slot_rejections / len(directional) if directional else None
        ),
        "slot_dropped_signals": slot_dropped,
        "slot_dropped_share_pct": _round(
            100.0 * slot_dropped / len(directional) if directional else None
        ),
        "coherence_reasons": dict(sorted(coherence.items())),
        "weekend_blocks": weekend_blocks,
        "fills": len(fills),
        "closes": len(trade_rows),
        "open_at_end": len(open_positions) if isinstance(open_positions, (dict, list)) else 0,
        "net_realised_usdt": _round(net),
        "gross_realised_usdt": _round(sum(float(trade["gross_pnl_usdt"]) for trade in trade_rows)),
        "commissions_usdt": _round(commissions),
        "execution_costs_usdt": _round(execution),
        "expectancy_usdt": _round(net / len(trade_rows)) if trade_rows else None,
        "win_rate_pct": _round(
            100.0 * sum(1 for trade in trade_rows if float(trade["pnl_net_usdt"]) > 0) / len(trade_rows)
        )
        if trade_rows
        else None,
        "mean_holding_minutes": _round(statistics.fmean(holdings)) if holdings else None,
        "median_holding_minutes": _round(statistics.median(holdings)) if holdings else None,
        "time_to_first_close_minutes": _round(
            (min(trade["exit_ts_ms"] for trade in trade_rows) - min(trade["entry_ts_ms"] for trade in trade_rows))
            / 60_000.0
        )
        if trade_rows
        else None,
        "mfe_pct_mean": _round(statistics.fmean([trade["mfe_pct"] for trade in trade_rows if trade["mfe_pct"] is not None]))
        if any(trade["mfe_pct"] is not None for trade in trade_rows)
        else None,
        "mae_pct_mean": _round(statistics.fmean([trade["mae_pct"] for trade in trade_rows if trade["mae_pct"] is not None]))
        if any(trade["mae_pct"] is not None for trade in trade_rows)
        else None,
        "turnover_usdt": _round(sum(notionals)),
        "mean_gross_exposure_pct": _round(statistics.fmean(exposures)) if exposures else 0.0,
        "max_gross_exposure_pct": _round(max(exposures)) if exposures else 0.0,
        "max_simultaneous_positions": max(simultaneous) if simultaneous else 0,
        "capital_utilisation_pct": _round(utilisation),
        "max_drawdown_pct": _round(summary.get("drawdown_pct")),
        "final_equity_usdt": _round(summary.get("final_equity_usdt")),
        "marked_equity_usdt": _round(summary.get("marked_equity_usdt")),
        "bootstrap_mean_pnl": bootstrap_mean_ci([float(trade["pnl_net_usdt"]) for trade in trade_rows]),
        "traded_grid_points": traded_bars,
        "interval_ms": interval_ms,
    }


def _weekly(trade_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    buckets: dict[str, list[float]] = defaultdict(list)
    counts: Counter[str] = Counter()
    for trade in trade_rows:
        iso = datetime.fromtimestamp(trade["exit_ts_ms"] / 1000.0, tz=UTC).isocalendar()
        key = f"{iso.year}-W{iso.week:02d}"
        buckets[key].append(float(trade["pnl_net_usdt"]))
        counts[key] += 1
    return [
        {
            "week": key,
            "closes": counts[key],
            "net_realised_usdt": _round(sum(values)),
            "mean_usdt": _round(statistics.fmean(values)),
        }
        for key, values in sorted(buckets.items())
    ]


def _write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field) for field in fields})


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", default=str(RUNS))
    parser.add_argument("--out", default=str(EXPERIMENT_OUT))
    args = parser.parse_args(argv)
    runs = Path(args.runs)
    out = Path(args.out)

    series: dict[str, list[Any]] = {}
    from exp_003j_replay import load_series

    boundaries = json.loads((out / "PARTITIONS.json").read_text(encoding="utf-8"))
    research = boundaries["research"]
    start_ms = int(
        datetime.strptime(research["start_utc"], "%Y-%m-%dT%H:%M:%SZ")
        .replace(tzinfo=UTC)
        .timestamp()
        * 1000
    )
    end_ms = int(
        datetime.strptime(boundaries["oos"]["end_utc"], "%Y-%m-%dT%H:%M:%SZ")
        .replace(tzinfo=UTC)
        .timestamp()
        * 1000
    )
    series, _report = load_series(
        symbols=["BTCUSDT", "ETHUSDT", "SOLUSDT"],
        start_ms=start_ms,
        end_ms=end_ms,
        interval_ms=timeframe_ms("5m"),
    )

    metrics: list[dict[str, Any]] = []
    trades_all: list[dict[str, Any]] = []
    reconciliation: dict[str, Any] = {}
    decision_trace: list[dict[str, Any]] = []
    per_asset: list[dict[str, Any]] = []
    weekly: dict[str, Any] = {}
    robustness: dict[str, Any] = {}

    for arm in ARMS:
        for partition in PARTITIONS:
            run_dir = runs / arm / partition
            rows = _load(run_dir / "ledger.jsonl")
            meta = json.loads((run_dir / "RUN_META.json").read_text(encoding="utf-8"))
            summary = json.loads((run_dir / "SUMMARY.json").read_text(encoding="utf-8"))
            interval_ms = int(meta["interval_ms"])
            window_end_ms = int(
                datetime.strptime(meta["window_end_utc"], "%Y-%m-%dT%H:%M:%SZ")
                .replace(tzinfo=UTC)
                .timestamp()
                * 1000
            )
            trace_path = run_dir / "SIGNAL_TRACE.jsonl"
            trace_rows = (
                [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines()]
                if trace_path.exists()
                else []
            )
            trace_index = {
                (row["asset"], int(row["decision_bar_open_ms"])): row for row in trace_rows
            }
            trade_rows = _trade_rows(
                _of(rows, "CLOSE"), _of(rows, "FILL"), arm=arm, bars=series, interval_ms=interval_ms
            )
            trades_all.extend(trade_rows)
            initial = float(meta["equity_usdt"])
            checks = _accounting_checks(
                rows=rows,
                fills=_of(rows, "FILL"),
                closes=_of(rows, "CLOSE"),
                summary=summary,
                open_positions=summary.get("open_positions_at_end") or {},
                initial_equity=initial,
            )
            reconciliation[f"{arm}/{partition}"] = checks
            metrics.append(
                _metrics(
                    arm=arm,
                    partition=partition,
                    rows=rows,
                    summary=summary,
                    trade_rows=trade_rows,
                    initial_equity=initial,
                    interval_ms=interval_ms,
                    window_end_ms=window_end_ms,
                    trace_rows=trace_rows,
                )
            )
            weekly[f"{arm}/{partition}"] = _weekly(trade_rows)

            # -- per-asset ------------------------------------------------------
            for symbol in sorted({row["symbol"] for row in _of(rows, "DECISION")}):
                subset = [trade for trade in trade_rows if trade["symbol"] == symbol]
                decisions = [
                    row
                    for row in _of(rows, "DECISION")
                    if row["symbol"] == symbol and (row.get("decision") or {}).get("action") in ("LONG", "SHORT")
                ]
                net = sum(float(trade["pnl_net_usdt"]) for trade in subset)
                per_asset.append(
                    {
                        "arm": arm,
                        "partition": partition,
                        "symbol": symbol,
                        "decisions": len([row for row in _of(rows, "DECISION") if row["symbol"] == symbol]),
                        "directional": len(decisions),
                        "long": sum(1 for row in decisions if row["decision"]["action"] == "LONG"),
                        "short": sum(1 for row in decisions if row["decision"]["action"] == "SHORT"),
                        "fills": len([fill for fill in _of(rows, "FILL") if fill["symbol"] == symbol]),
                        "closes": len(subset),
                        "net_realised_usdt": _round(net),
                        "expectancy_usdt": _round(net / len(subset)) if subset else None,
                        "win_rate_pct": _round(
                            100.0 * sum(1 for trade in subset if float(trade["pnl_net_usdt"]) > 0) / len(subset)
                        )
                        if subset
                        else None,
                        "mean_holding_minutes": _round(
                            statistics.fmean([float(trade["holding_minutes"]) for trade in subset])
                        )
                        if subset
                        else None,
                        "mfe_pct_mean": _round(
                            statistics.fmean([trade["mfe_pct"] for trade in subset if trade["mfe_pct"] is not None])
                        )
                        if any(trade["mfe_pct"] is not None for trade in subset)
                        else None,
                        "mae_pct_mean": _round(
                            statistics.fmean([trade["mae_pct"] for trade in subset if trade["mae_pct"] is not None])
                        )
                        if any(trade["mae_pct"] is not None for trade in subset)
                        else None,
                        "commissions_usdt": _round(sum(float(trade["commissions_usdt"]) for trade in subset)),
                    }
                )

            # -- joined decision trace -----------------------------------------
            outcomes = {int(row["decision_seq"]): row for row in _of(rows, "DECISION_OUTCOME")}
            fill_seqs = {int(row["decision_seq"]) for row in _of(rows, "FILL") if "decision_seq" in row}
            for row in _of(rows, "DECISION"):
                seq = int(row["_seq"])
                decision = row.get("decision") or {}
                outcome = outcomes.get(seq, {})
                trace = trace_index.get((row["symbol"], int(row["decision_bar_ts_ms"])), {})
                risk_result = "NOT_REACHED"
                if outcome:
                    risk_result = "ALLOW" if outcome.get("approved") else "VETO"
                elif decision.get("action") in ("LONG", "SHORT"):
                    risk_result = "NOT_REACHED"
                broker_result = "NOT_SUBMITTED"
                if seq in fill_seqs:
                    broker_result = "FILLED"
                elif outcome and not outcome.get("approved"):
                    broker_result = "REJECTED"
                decision_trace.append(
                    {
                        "run_id": f"003j-{arm}-{partition}",
                        "arm": arm,
                        "asset": row["symbol"],
                        "timeframe": meta["timeframe"],
                        "strategy_id": trace.get("strategy_id"),
                        "strategy_version": trace.get("strategy_version"),
                        "strategy_classification": trace.get("strategy_classification"),
                        "decision_time_utc": row["ts_utc"],
                        "decision_bar_open_utc": _utc(int(row["decision_bar_ts_ms"])),
                        "max_input_data_time_utc": trace.get("max_input_data_time_utc"),
                        "market_data_fingerprint": trace.get("market_data_fingerprint"),
                        "chart_sha256": (row.get("chart") or {}).get("sha256"),
                        "action": decision.get("action"),
                        "proposal_id": f"proposal-{arm}-{partition}-{seq:06d}"
                        if decision.get("action") in ("LONG", "SHORT")
                        else None,
                        "evidence_refs": trace.get("evidence_refs") or [],
                        "counter_evidence_refs": trace.get("counter_evidence_refs") or [],
                        "invalidation": decision.get("invalidation"),
                        "reason_code": trace.get("reason_code")
                        or ("LEGACY_PARITY_ROTATION" if decision.get("action") else "PARSE_OR_GUARD_FAILURE"),
                        "quality_status": trace.get("quality_status")
                        or ("PASS" if decision.get("action") else "REJECT"),
                        "risk_result": risk_result,
                        "risk_blocked_by": outcome.get("risk_blocked_by"),
                        "broker_result": broker_result,
                        "decision_seq": seq,
                    }
                )

    # -- outputs -------------------------------------------------------------
    (out / "analysis").mkdir(parents=True, exist_ok=True)
    (out / "analysis" / "METRICS.json").write_text(
        json.dumps({"metrics": metrics, "weekly": weekly}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    (out / "analysis" / "RECONCILIATION.json").write_text(
        json.dumps(reconciliation, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )

    with (out / "DECISION_TRACE.jsonl").open("w", encoding="utf-8", newline="\n") as handle:
        for row in decision_trace:
            handle.write(json.dumps(row, sort_keys=True) + "\n")

    _write_csv(
        out / "PAPER_LEDGER.csv",
        sorted(trades_all, key=lambda row: (row["arm"], row["exit_ts_ms"], row["trade_id"])),
        [
            "arm",
            "trade_id",
            "position_id",
            "symbol",
            "side",
            "entry_utc",
            "exit_utc",
            "entry_price",
            "exit_price",
            "quantity",
            "notional_usdt",
            "stop_loss_price",
            "take_profit_price",
            "exit_reason",
            "exit_ts_resolution",
            "bars_held",
            "holding_minutes",
            "gross_pnl_usdt",
            "reference_gross_pnl_usdt",
            "execution_cost_usdt",
            "commissions_usdt",
            "pnl_net_usdt",
            "mfe_pct",
            "mae_pct",
        ],
    )
    _write_csv(
        out / "SCENARIO_COMPARISON.csv",
        metrics,
        [
            "arm",
            "partition",
            "decisions",
            "directional",
            "long",
            "short",
            "no_trade",
            "fills",
            "closes",
            "net_realised_usdt",
            "expectancy_usdt",
            "win_rate_pct",
            "mean_holding_minutes",
            "commissions_usdt",
            "execution_costs_usdt",
            "turnover_usdt",
            "mean_gross_exposure_pct",
            "max_simultaneous_positions",
            "capital_utilisation_pct",
            "max_drawdown_pct",
            "final_equity_usdt",
            "symbol_slot_rejections",
            "slot_share_of_directional_pct",
            "slot_dropped_signals",
            "slot_dropped_share_pct",
            "weekend_blocks",
        ],
    )
    _write_csv(
        out / "METRICS_BY_ASSET.csv",
        per_asset,
        [
            "arm",
            "partition",
            "symbol",
            "decisions",
            "directional",
            "long",
            "short",
            "fills",
            "closes",
            "net_realised_usdt",
            "expectancy_usdt",
            "win_rate_pct",
            "mean_holding_minutes",
            "mfe_pct_mean",
            "mae_pct_mean",
            "commissions_usdt",
        ],
    )

    # -- robustness ----------------------------------------------------------
    real_research = next(
        (row for row in metrics if row["arm"] == "real" and row["partition"] == "research"), None
    )
    real_oos = next((row for row in metrics if row["arm"] == "real" and row["partition"] == "oos"), None)
    control_research = next(
        (row for row in metrics if row["arm"] == "control" and row["partition"] == "research"), None
    )
    robustness = {
        "schema_version": "AI_BOTS_003J_ROBUSTNESS_V1",
        "weekly_real": weekly.get("real/research"),
        "weekly_control": weekly.get("control/research"),
        "research_vs_oos": {
            "real_closes": [real_research["closes"] if real_research else None, real_oos["closes"] if real_oos else None],
            "real_net": [
                real_research["net_realised_usdt"] if real_research else None,
                real_oos["net_realised_usdt"] if real_oos else None,
            ],
            "control_net": control_research["net_realised_usdt"] if control_research else None,
            "sign_flip": (
                None
                if not (real_research and real_oos)
                else (real_research["net_realised_usdt"] > 0) != (real_oos["net_realised_usdt"] > 0)
            ),
        },
        "bootstrap": {
            "real_research": real_research["bootstrap_mean_pnl"] if real_research else None,
            "real_oos": real_oos["bootstrap_mean_pnl"] if real_oos else None,
        },
        "declared_limitations": [
            "One strategy, one configuration, one 60-day window: the OOS is 14 days, not a regime sample.",
            "Fills use the next bar open; no intrabar price is modelled beyond the bar range for stops.",
            "The strategy's structural stop is reported, not used: the policy stop is what executes.",
            "No hyperparameter search was performed, so there is no in-sample optimum to overfit.",
        ],
    }
    (out / "analysis" / "ROBUSTNESS.json").write_text(
        json.dumps(robustness, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    print(json.dumps({"metrics": metrics, "reconciliation": {
        key: {"passed": value["passed"], "failed": value["failed"]} for key, value in reconciliation.items()
    }}, indent=2)[:4000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
